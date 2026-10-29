from collections.abc import Iterator

import pytest
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response
from starlette.routing import Route
from starlette.testclient import TestClient

from news_mcp_server.auth import BearerAuthMiddleware

AUTH_TOKEN = "test-auth-token"


async def ok(request: Request) -> Response:
    return PlainTextResponse("ok")


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = Starlette(
        routes=[
            Route("/health", ok),
            Route("/mcp", ok, methods=["GET", "POST"]),
        ],
        middleware=[Middleware(BearerAuthMiddleware, token=AUTH_TOKEN)],
    )
    with TestClient(app) as test_client:
        yield test_client


def test_health_bypasses_auth(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200


def test_valid_token_passes_through(client: TestClient) -> None:
    response = client.post("/mcp", headers={"Authorization": f"Bearer {AUTH_TOKEN}"})

    assert response.status_code == 200
    assert response.text == "ok"


@pytest.mark.parametrize(
    "authorization",
    [
        None,
        "",
        "Bearer",
        "Bearer ",
        "Bearer wrong-token",
        f"Bearer {AUTH_TOKEN}x",
        f"Basic {AUTH_TOKEN}",
        AUTH_TOKEN,
    ],
)
def test_missing_or_invalid_token_returns_401(
    client: TestClient, authorization: str | None
) -> None:
    headers = {} if authorization is None else {"Authorization": authorization}

    response = client.post("/mcp", headers=headers)

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert response.json() == {"error": "unauthorized"}


def test_unknown_path_requires_auth(client: TestClient) -> None:
    response = client.get("/health/../mcp-admin")

    assert response.status_code == 401


def test_public_paths_are_configurable() -> None:
    app = Starlette(
        routes=[Route("/healthz", ok), Route("/health", ok)],
        middleware=[Middleware(BearerAuthMiddleware, token=AUTH_TOKEN, public_paths={"/healthz"})],
    )
    with TestClient(app) as client:
        assert client.get("/healthz").status_code == 200
        assert client.get("/health").status_code == 401


def test_empty_token_is_rejected() -> None:
    with pytest.raises(ValueError):
        BearerAuthMiddleware(ok, token="")
