"""Async client for News API (https://newsapi.org/docs)."""

from datetime import datetime
from types import TracebackType
from typing import Any, Literal, Self

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

DEFAULT_BASE_URL = "https://newsapi.org/v2"
DEFAULT_TIMEOUT = 10.0

SortBy = Literal["relevancy", "popularity", "publishedAt"]
Category = Literal[
    "business", "entertainment", "general", "health", "science", "sports", "technology"
]


# --- Exceptions ---


class NewsApiError(Exception):
    """Base error for News API failures.

    Messages are safe to surface to MCP clients: they never contain the API key.
    """

    def __init__(
        self, message: str, *, status_code: int | None = None, code: str | None = None
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code = code


class NewsApiAuthenticationError(NewsApiError):
    """Raised on HTTP 401 (missing or invalid API key)."""


class NewsApiRateLimitError(NewsApiError):
    """Raised on HTTP 429 (request quota exceeded)."""


class NewsApiTimeoutError(NewsApiError):
    """Raised when the request to News API times out."""


# --- Response models ---


class ArticleSource(BaseModel):
    id: str | None = None
    name: str | None = None


class Article(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    source: ArticleSource
    author: str | None = None
    title: str | None = None
    description: str | None = None
    url: str
    url_to_image: str | None = Field(default=None, alias="urlToImage")
    published_at: datetime = Field(alias="publishedAt")
    content: str | None = None


class NewsResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    status: str
    total_results: int = Field(alias="totalResults")
    articles: list[Article]


# --- Client ---


class NewsApiClient:
    """Thin async wrapper around the News API v2 endpoints."""

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._owns_client = http_client is None
        self._client = http_client or httpx.AsyncClient(timeout=timeout)
        self._base_url = base_url.rstrip("/")
        self._headers = {"X-Api-Key": api_key}

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def get_top_headlines(
        self,
        *,
        country: str | None = None,
        category: Category | None = None,
        sources: str | None = None,
        q: str | None = None,
        page_size: int | None = None,
        page: int | None = None,
    ) -> NewsResponse:
        return await self._get(
            "/top-headlines",
            {
                "country": country,
                "category": category,
                "sources": sources,
                "q": q,
                "pageSize": page_size,
                "page": page,
            },
        )

    async def search_everything(
        self,
        *,
        q: str | None = None,
        search_in: str | None = None,
        sources: str | None = None,
        domains: str | None = None,
        exclude_domains: str | None = None,
        from_date: str | None = None,
        to_date: str | None = None,
        language: str | None = None,
        sort_by: SortBy | None = None,
        page_size: int | None = None,
        page: int | None = None,
    ) -> NewsResponse:
        return await self._get(
            "/everything",
            {
                "q": q,
                "searchIn": search_in,
                "sources": sources,
                "domains": domains,
                "excludeDomains": exclude_domains,
                "from": from_date,
                "to": to_date,
                "language": language,
                "sortBy": sort_by,
                "pageSize": page_size,
                "page": page,
            },
        )

    async def _get(self, path: str, params: dict[str, Any]) -> NewsResponse:
        query = {key: value for key, value in params.items() if value is not None}
        try:
            response = await self._client.get(
                f"{self._base_url}{path}", params=query, headers=self._headers
            )
        except httpx.TimeoutException as exc:
            raise NewsApiTimeoutError("Request to News API timed out.") from exc
        except httpx.HTTPError as exc:
            raise NewsApiError(f"Failed to connect to News API: {type(exc).__name__}") from exc

        if response.is_error:
            raise _error_from_response(response)

        try:
            return NewsResponse.model_validate(response.json())
        except (ValueError, ValidationError) as exc:
            raise NewsApiError(
                "Received an unexpected response format from News API.",
                status_code=response.status_code,
            ) from exc


def _error_from_response(response: httpx.Response) -> NewsApiError:
    code: str | None = None
    message = f"News API returned HTTP {response.status_code}."
    try:
        body = response.json()
    except ValueError:
        body = None
    if isinstance(body, dict):
        if isinstance(body.get("code"), str):
            code = body["code"]
        if isinstance(body.get("message"), str):
            message = body["message"]

    error_cls: type[NewsApiError] = NewsApiError
    if response.status_code == 401:
        error_cls = NewsApiAuthenticationError
    elif response.status_code == 429:
        error_cls = NewsApiRateLimitError
    return error_cls(message, status_code=response.status_code, code=code)
