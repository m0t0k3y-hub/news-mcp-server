from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
import respx

from news_mcp_server.client import (
    NewsApiAuthenticationError,
    NewsApiClient,
    NewsApiError,
    NewsApiRateLimitError,
    NewsApiTimeoutError,
    NewsResponse,
)

BASE_URL = "https://newsapi.org/v2"
API_KEY = "test-api-key"

ARTICLES_PAYLOAD: dict[str, Any] = {
    "status": "ok",
    "totalResults": 2,
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
        },
        {
            "source": {"id": None, "name": "Example"},
            "author": None,
            "title": "Headline two",
            "description": None,
            "url": "https://example.com/two",
            "urlToImage": None,
            "publishedAt": "2026-10-28T08:30:00Z",
            "content": None,
        },
    ],
}


def error_payload(code: str, message: str) -> dict[str, str]:
    return {"status": "error", "code": code, "message": message}


@pytest.fixture
async def client() -> AsyncIterator[NewsApiClient]:
    async with NewsApiClient(api_key=API_KEY) as news_client:
        yield news_client


# --- 正常系 ---


@respx.mock
async def test_get_top_headlines_returns_parsed_response(client: NewsApiClient) -> None:
    route = respx.get(f"{BASE_URL}/top-headlines").mock(
        return_value=httpx.Response(200, json=ARTICLES_PAYLOAD)
    )

    result = await client.get_top_headlines(country="us", category="technology", page_size=2)

    assert isinstance(result, NewsResponse)
    assert result.total_results == 2
    assert len(result.articles) == 2
    first = result.articles[0]
    assert first.source.id == "bbc-news"
    assert first.source.name == "BBC News"
    assert first.title == "Headline one"
    assert first.url_to_image == "https://example.com/one.jpg"
    assert first.published_at.year == 2026
    assert result.articles[1].author is None

    request = route.calls.last.request
    assert request.headers["X-Api-Key"] == API_KEY
    assert request.url.params["country"] == "us"
    assert request.url.params["category"] == "technology"
    assert request.url.params["pageSize"] == "2"
    assert "sources" not in request.url.params
    assert "q" not in request.url.params


@respx.mock
async def test_search_everything_returns_parsed_response(client: NewsApiClient) -> None:
    route = respx.get(f"{BASE_URL}/everything").mock(
        return_value=httpx.Response(200, json=ARTICLES_PAYLOAD)
    )

    result = await client.search_everything(
        q="python",
        language="en",
        sort_by="publishedAt",
        from_date="2026-10-01",
        to_date="2026-10-29",
        domains="example.com",
        page=2,
    )

    assert result.status == "ok"
    assert [a.title for a in result.articles] == ["Headline one", "Headline two"]

    params = route.calls.last.request.url.params
    assert params["q"] == "python"
    assert params["language"] == "en"
    assert params["sortBy"] == "publishedAt"
    assert params["from"] == "2026-10-01"
    assert params["to"] == "2026-10-29"
    assert params["domains"] == "example.com"
    assert params["page"] == "2"
    assert "pageSize" not in params


@respx.mock
async def test_api_key_is_not_sent_as_query_param(client: NewsApiClient) -> None:
    route = respx.get(f"{BASE_URL}/everything").mock(
        return_value=httpx.Response(200, json=ARTICLES_PAYLOAD)
    )

    await client.search_everything(q="python")

    assert API_KEY not in str(route.calls.last.request.url)


# --- 異常系 ---


@respx.mock
async def test_unauthorized_raises_authentication_error(client: NewsApiClient) -> None:
    respx.get(f"{BASE_URL}/top-headlines").mock(
        return_value=httpx.Response(
            401, json=error_payload("apiKeyInvalid", "Your API key is invalid.")
        )
    )

    with pytest.raises(NewsApiAuthenticationError) as exc_info:
        await client.get_top_headlines(country="us")

    assert exc_info.value.status_code == 401
    assert exc_info.value.code == "apiKeyInvalid"
    assert "Your API key is invalid." in str(exc_info.value)
    assert API_KEY not in str(exc_info.value)


@respx.mock
async def test_rate_limited_raises_rate_limit_error(client: NewsApiClient) -> None:
    respx.get(f"{BASE_URL}/everything").mock(
        return_value=httpx.Response(
            429, json=error_payload("rateLimited", "You have made too many requests.")
        )
    )

    with pytest.raises(NewsApiRateLimitError) as exc_info:
        await client.search_everything(q="python")

    assert exc_info.value.status_code == 429
    assert exc_info.value.code == "rateLimited"


@pytest.mark.parametrize(
    ("status_code", "code", "message"),
    [
        (400, "parametersMissing", "Required parameters are missing."),
        (500, "unexpectedError", "Something went wrong on our side."),
    ],
)
@respx.mock
async def test_api_error_raises_news_api_error(
    client: NewsApiClient, status_code: int, code: str, message: str
) -> None:
    respx.get(f"{BASE_URL}/everything").mock(
        return_value=httpx.Response(status_code, json=error_payload(code, message))
    )

    with pytest.raises(NewsApiError) as exc_info:
        await client.search_everything(q="python")

    assert type(exc_info.value) is NewsApiError
    assert exc_info.value.status_code == status_code
    assert exc_info.value.code == code
    assert message in str(exc_info.value)


@respx.mock
async def test_non_json_error_body_raises_news_api_error(client: NewsApiClient) -> None:
    respx.get(f"{BASE_URL}/top-headlines").mock(
        return_value=httpx.Response(502, text="<html>Bad Gateway</html>")
    )

    with pytest.raises(NewsApiError) as exc_info:
        await client.get_top_headlines(country="us")

    assert exc_info.value.status_code == 502
    assert exc_info.value.code is None


@respx.mock
async def test_malformed_success_body_raises_news_api_error(client: NewsApiClient) -> None:
    respx.get(f"{BASE_URL}/top-headlines").mock(
        return_value=httpx.Response(200, json={"unexpected": "shape"})
    )

    with pytest.raises(NewsApiError):
        await client.get_top_headlines(country="us")


@respx.mock
async def test_timeout_raises_timeout_error(client: NewsApiClient) -> None:
    respx.get(f"{BASE_URL}/top-headlines").mock(side_effect=httpx.ReadTimeout("timed out"))

    with pytest.raises(NewsApiTimeoutError) as exc_info:
        await client.get_top_headlines(country="us")

    assert isinstance(exc_info.value, NewsApiError)
    assert exc_info.value.status_code is None


@respx.mock
async def test_connection_error_raises_news_api_error(client: NewsApiClient) -> None:
    respx.get(f"{BASE_URL}/everything").mock(side_effect=httpx.ConnectError("refused"))

    with pytest.raises(NewsApiError) as exc_info:
        await client.search_everything(q="python")

    assert exc_info.value.status_code is None
