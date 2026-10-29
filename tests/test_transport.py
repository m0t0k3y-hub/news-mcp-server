import threading
import time
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
import respx
import uvicorn
from mcp import ClientSession
from mcp.client.sse import sse_client
from pydantic import SecretStr
from starlette.testclient import TestClient

from news_mcp_server.config import Settings
from news_mcp_server.server import create_app

BASE_URL = "https://newsapi.org/v2"
API_KEY = "test-api-key"
AUTH_TOKEN = "test-auth-token"
AUTH_HEADERS = {"Authorization": f"Bearer {AUTH_TOKEN}"}

ARTICLES_PAYLOAD: dict[str, Any] = {
    "status": "ok",
    "totalResults": 1,
    "articles": [
        {
            "source": {"id": None, "name": "Example"},
            "author": None,
            "title": "Headline one",
            "description": None,
            "url": "https://example.com/one",
            "urlToImage": None,
            "publishedAt": "2026-10-29T12:00:00Z",
            "content": None,
        }
    ],
}


def make_settings() -> Settings:
    return Settings(news_api_key=SecretStr(API_KEY), auth_token=SecretStr(AUTH_TOKEN))


# --- Auth on SSE endpoints (rejections return immediately, so TestClient is enough) ---


@pytest.fixture
def http_client() -> Iterator[TestClient]:
    with TestClient(create_app(make_settings())) as client:
        yield client


@pytest.mark.parametrize("token", [None, "wrong-token"])
def test_sse_endpoint_rejects_missing_or_invalid_token(
    http_client: TestClient, token: str | None
) -> None:
    headers = {} if token is None else {"Authorization": f"Bearer {token}"}

    response = http_client.get("/sse", headers=headers)

    assert response.status_code == 401


@pytest.mark.parametrize("token", [None, "wrong-token"])
def test_messages_endpoint_rejects_missing_or_invalid_token(
    http_client: TestClient, token: str | None
) -> None:
    headers = {} if token is None else {"Authorization": f"Bearer {token}"}

    response = http_client.post(
        "/messages/?session_id=00000000000000000000000000000000", headers=headers
    )

    assert response.status_code == 401


def test_messages_endpoint_with_valid_token_reaches_transport(http_client: TestClient) -> None:
    # Past auth, the SSE transport itself rejects the unknown session.
    response = http_client.post(
        "/messages/?session_id=00000000000000000000000000000000",
        json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
        headers=AUTH_HEADERS,
    )

    assert response.status_code == 404
    assert "session" in response.text.lower()


# --- End-to-end over a real server (SSE streams never finish, so TestClient can't read them) ---


@pytest.fixture
def live_server_url() -> Iterator[str]:
    config = uvicorn.Config(
        create_app(make_settings()),
        host="127.0.0.1",
        port=0,
        log_level="warning",
        timeout_graceful_shutdown=1,
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 5
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError("uvicorn did not start")
        time.sleep(0.01)
    port = server.servers[0].sockets[0].getsockname()[1]
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=5)


async def test_sse_stream_with_valid_token_announces_message_endpoint(
    live_server_url: str,
) -> None:
    async with httpx.AsyncClient(base_url=live_server_url, headers=AUTH_HEADERS) as client:
        async with client.stream("GET", "/sse") as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            lines = response.aiter_lines()
            assert await anext(lines) == "event: endpoint"
            assert (await anext(lines)).startswith("data: /messages/?session_id=")


@respx.mock
async def test_sse_client_can_list_and_call_tools(live_server_url: str) -> None:
    respx.route(host="127.0.0.1").pass_through()
    respx.get(f"{BASE_URL}/everything").mock(
        return_value=httpx.Response(200, json=ARTICLES_PAYLOAD)
    )

    async with sse_client(f"{live_server_url}/sse", headers=AUTH_HEADERS) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = await session.list_tools()
            result = await session.call_tool("search_everything", {"q": "python"})

    assert {tool.name for tool in tools.tools} == {"get_top_headlines", "search_everything"}
    assert result.is_error is False
    assert result.structured_content is not None
    assert result.structured_content["articles"][0]["title"] == "Headline one"
