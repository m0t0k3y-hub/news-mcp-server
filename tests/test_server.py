from collections.abc import AsyncIterator, Iterator
from typing import Any

import httpx
import pytest
import respx
from mcp import Client
from mcp.server.mcpserver import MCPServer
from mcp.types import TextContent
from pydantic import SecretStr
from starlette.testclient import TestClient

from news_mcp_server.client import NewsApiClient
from news_mcp_server.config import Settings
from news_mcp_server.server import create_app, create_mcp_server

BASE_URL = "https://newsapi.org/v2"
API_KEY = "test-api-key"
AUTH_TOKEN = "test-auth-token"

ARTICLES_PAYLOAD: dict[str, Any] = {
    "status": "ok",
    "totalResults": 1,
    "articles": [
        {
            "source": {"id": "bbc-news", "name": "BBC News"},
            "author": "Jane Doe",
            "title": "Headline one",
            "description": "Description one",
            "url": "https://example.com/one",
            "urlToImage": "https://example.com/one.jpg",
            "publishedAt": "2026-10-29T12:00:00Z",
            "content": "Content one",
        }
    ],
}


def error_payload(code: str, message: str) -> dict[str, str]:
    return {"status": "error", "code": code, "message": message}


def text_of(result: Any) -> str:
    return "".join(block.text for block in result.content if isinstance(block, TextContent))


# Client must be opened inside each test: its anyio task group cannot span the
# separate tasks pytest-asyncio uses for fixture setup and teardown.
@pytest.fixture
async def mcp_server() -> AsyncIterator[MCPServer]:
    async with NewsApiClient(api_key=API_KEY) as news_client:
        yield create_mcp_server(news_client)


# --- Tools ---


async def test_list_tools_exposes_news_tools(mcp_server: MCPServer) -> None:
    async with Client(mcp_server) as mcp_client:
        result = await mcp_client.list_tools()

        tools = {tool.name: tool for tool in result.tools}
        assert set(tools) == {"get_top_headlines", "search_everything"}
        for tool in tools.values():
            assert tool.description
            assert tool.annotations is not None
            assert tool.annotations.read_only_hint is True


@respx.mock
async def test_get_top_headlines_tool_returns_articles(mcp_server: MCPServer) -> None:
    route = respx.get(f"{BASE_URL}/top-headlines").mock(
        return_value=httpx.Response(200, json=ARTICLES_PAYLOAD)
    )

    async with Client(mcp_server) as mcp_client:
        result = await mcp_client.call_tool(
            "get_top_headlines", {"country": "us", "category": "technology", "page_size": 5}
        )

        assert result.is_error is False
        assert result.structured_content is not None
        assert result.structured_content["total_results"] == 1
        article = result.structured_content["articles"][0]
        assert article["title"] == "Headline one"
        assert article["source"] == "BBC News"
        assert article["url"] == "https://example.com/one"
        assert article["published_at"].startswith("2026-10-29T12:00:00")

        params = route.calls.last.request.url.params
        assert params["country"] == "us"
        assert params["category"] == "technology"
        assert params["pageSize"] == "5"


@respx.mock
async def test_search_everything_tool_returns_articles(mcp_server: MCPServer) -> None:
    route = respx.get(f"{BASE_URL}/everything").mock(
        return_value=httpx.Response(200, json=ARTICLES_PAYLOAD)
    )

    async with Client(mcp_server) as mcp_client:
        result = await mcp_client.call_tool(
            "search_everything",
            {"q": "python", "language": "en", "sort_by": "publishedAt", "from_date": "2026-10-01"},
        )

        assert result.is_error is False
        assert result.structured_content is not None
        assert result.structured_content["articles"][0]["title"] == "Headline one"

        params = route.calls.last.request.url.params
        assert params["q"] == "python"
        assert params["sortBy"] == "publishedAt"
        assert params["from"] == "2026-10-01"


async def test_get_top_headlines_requires_a_filter(mcp_server: MCPServer) -> None:
    async with Client(mcp_server) as mcp_client:
        result = await mcp_client.call_tool("get_top_headlines", {})

        assert result.is_error is True
        assert "country" in text_of(result)


async def test_get_top_headlines_rejects_sources_with_country(mcp_server: MCPServer) -> None:
    async with Client(mcp_server) as mcp_client:
        result = await mcp_client.call_tool(
            "get_top_headlines", {"sources": "bbc-news", "country": "us"}
        )

        assert result.is_error is True
        assert "sources" in text_of(result)


@pytest.mark.parametrize(
    ("status_code", "code", "expected"),
    [
        (401, "apiKeyInvalid", "authentication failed"),
        (429, "rateLimited", "rate limit"),
        (400, "parameterInvalid", "The q parameter is invalid."),
        (500, "unexpectedError", "Something went wrong."),
    ],
)
@respx.mock
async def test_news_api_errors_become_tool_errors(
    mcp_server: MCPServer, status_code: int, code: str, expected: str
) -> None:
    message = "The q parameter is invalid." if status_code == 400 else "Something went wrong."
    respx.get(f"{BASE_URL}/everything").mock(
        return_value=httpx.Response(status_code, json=error_payload(code, message))
    )

    async with Client(mcp_server) as mcp_client:
        result = await mcp_client.call_tool("search_everything", {"q": "python"})

        assert result.is_error is True
        assert expected in text_of(result)
        assert API_KEY not in text_of(result)


@respx.mock
async def test_timeout_becomes_tool_error(mcp_server: MCPServer) -> None:
    respx.get(f"{BASE_URL}/everything").mock(side_effect=httpx.ReadTimeout("timed out"))

    async with Client(mcp_server) as mcp_client:
        result = await mcp_client.call_tool("search_everything", {"q": "python"})

        assert result.is_error is True
        assert "timed out" in text_of(result)


# --- HTTP app ---


@pytest.fixture
def http_client() -> Iterator[TestClient]:
    settings = Settings(news_api_key=SecretStr(API_KEY), auth_token=SecretStr(AUTH_TOKEN))
    with TestClient(create_app(settings)) as client:
        yield client


INITIALIZE_REQUEST: dict[str, Any] = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-11-25",
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "0.0.0"},
    },
}
MCP_HEADERS = {"Accept": "application/json, text/event-stream"}


def test_health_does_not_require_auth(http_client: TestClient) -> None:
    response = http_client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


# Token validation details are covered in test_auth.py; this only checks the wiring.
def test_mcp_endpoint_requires_token(http_client: TestClient) -> None:
    response = http_client.post(
        "/mcp",
        json=INITIALIZE_REQUEST,
        headers={**MCP_HEADERS, "Authorization": "Bearer wrong-token"},
    )

    assert response.status_code == 401


def test_mcp_endpoint_accepts_valid_token(http_client: TestClient) -> None:
    response = http_client.post(
        "/mcp",
        json=INITIALIZE_REQUEST,
        headers={**MCP_HEADERS, "Authorization": f"Bearer {AUTH_TOKEN}"},
    )

    assert response.status_code == 200
    assert response.json()["result"]["serverInfo"]["name"] == "news-mcp-server"


# --- Settings ---


def test_settings_load_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEWS_API_KEY", API_KEY)
    monkeypatch.setenv("AUTH_TOKEN", AUTH_TOKEN)
    monkeypatch.setenv("PORT", "9000")

    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.news_api_key.get_secret_value() == API_KEY
    assert settings.auth_token.get_secret_value() == AUTH_TOKEN
    assert settings.port == 9000
    assert settings.host == "0.0.0.0"
    assert API_KEY not in repr(settings)
