"""MCP server exposing News API tools over Streamable HTTP."""

import hmac
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Annotated

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route
from starlette.types import ASGIApp, Receive, Scope, Send

from news_mcp_server.client import (
    Category,
    NewsApiAuthenticationError,
    NewsApiClient,
    NewsApiError,
    NewsApiRateLimitError,
    NewsApiTimeoutError,
    NewsResponse,
    SortBy,
)
from news_mcp_server.config import Settings

logger = logging.getLogger(__name__)

SERVER_NAME = "news-mcp-server"
PUBLIC_PATHS = frozenset({"/health"})

READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=True)

PageSize = Annotated[int, Field(ge=1, le=100, description="Number of articles to return (1-100).")]
Page = Annotated[int, Field(ge=1, description="Page number for pagination (starts at 1).")]


# --- Tool output models ---


class ArticleSummary(BaseModel):
    title: str | None
    source: str | None
    author: str | None
    description: str | None
    url: str
    published_at: datetime
    content: str | None


class NewsResult(BaseModel):
    total_results: int
    articles: list[ArticleSummary]


def _to_result(response: NewsResponse) -> NewsResult:
    return NewsResult(
        total_results=response.total_results,
        articles=[
            ArticleSummary(
                title=article.title,
                source=article.source.name,
                author=article.author,
                description=article.description,
                url=article.url,
                published_at=article.published_at,
                content=article.content,
            )
            for article in response.articles
        ],
    )


def _to_tool_error(exc: NewsApiError) -> ToolError:
    logger.warning("News API request failed: status=%s code=%s", exc.status_code, exc.code)
    if isinstance(exc, NewsApiAuthenticationError):
        return ToolError("News API authentication failed. The server's API key may be invalid.")
    if isinstance(exc, NewsApiRateLimitError):
        return ToolError("News API rate limit exceeded. Please try again later.")
    if isinstance(exc, NewsApiTimeoutError):
        return ToolError("News API request timed out. Please try again later.")
    return ToolError(f"News API error: {exc.message}")


# --- MCP server ---


def create_mcp_server(news_client: NewsApiClient) -> MCPServer:
    mcp = MCPServer(
        SERVER_NAME,
        instructions="Search and retrieve news articles from News API (newsapi.org).",
    )

    @mcp.tool(annotations=READ_ONLY)
    async def get_top_headlines(
        country: Annotated[
            str | None, Field(description="2-letter ISO 3166-1 country code, e.g. 'us', 'jp'.")
        ] = None,
        category: Annotated[Category | None, Field(description="News category.")] = None,
        sources: Annotated[
            str | None,
            Field(
                description="Comma-separated source IDs, e.g. 'bbc-news,cnn'. "
                "Cannot be combined with country or category."
            ),
        ] = None,
        q: Annotated[str | None, Field(description="Keywords to search for.")] = None,
        page_size: PageSize = 10,
        page: Page = 1,
    ) -> NewsResult:
        """Get live top and breaking headlines.

        At least one of country, category, sources or q is required.
        """
        if not any((country, category, sources, q)):
            raise ToolError("Specify at least one of: country, category, sources, q.")
        if sources and (country or category):
            raise ToolError("sources cannot be combined with country or category.")
        try:
            response = await news_client.get_top_headlines(
                country=country,
                category=category,
                sources=sources,
                q=q,
                page_size=page_size,
                page=page,
            )
        except NewsApiError as exc:
            raise _to_tool_error(exc) from exc
        return _to_result(response)

    @mcp.tool(annotations=READ_ONLY)
    async def search_everything(
        q: Annotated[
            str,
            Field(
                min_length=1,
                description="Keywords or phrase. Supports AND/OR/NOT, quotes for exact match, "
                "and +/- prefixes.",
            ),
        ],
        search_in: Annotated[
            str | None,
            Field(description="Comma-separated fields to search: title, description, content."),
        ] = None,
        sources: Annotated[str | None, Field(description="Comma-separated source IDs.")] = None,
        domains: Annotated[
            str | None, Field(description="Comma-separated domains to restrict to.")
        ] = None,
        exclude_domains: Annotated[
            str | None, Field(description="Comma-separated domains to exclude.")
        ] = None,
        from_date: Annotated[
            str | None, Field(description="Oldest article date (ISO 8601, e.g. 2026-10-01).")
        ] = None,
        to_date: Annotated[
            str | None, Field(description="Newest article date (ISO 8601, e.g. 2026-10-29).")
        ] = None,
        language: Annotated[
            str | None, Field(description="2-letter ISO 639-1 language code, e.g. 'en'.")
        ] = None,
        sort_by: Annotated[SortBy | None, Field(description="Sort order of results.")] = None,
        page_size: PageSize = 10,
        page: Page = 1,
    ) -> NewsResult:
        """Search every article published by over 150,000 news sources and blogs."""
        try:
            response = await news_client.search_everything(
                q=q,
                search_in=search_in,
                sources=sources,
                domains=domains,
                exclude_domains=exclude_domains,
                from_date=from_date,
                to_date=to_date,
                language=language,
                sort_by=sort_by,
                page_size=page_size,
                page=page,
            )
        except NewsApiError as exc:
            raise _to_tool_error(exc) from exc
        return _to_result(response)

    return mcp


# --- HTTP app ---


async def health(request: Request) -> Response:
    return JSONResponse({"status": "ok"})


class BearerAuthMiddleware:
    """Require `Authorization: Bearer <token>` on every HTTP request except public paths."""

    def __init__(self, app: ASGIApp, token: str) -> None:
        self.app = app
        self._expected = f"Bearer {token}".encode()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] in PUBLIC_PATHS:
            await self.app(scope, receive, send)
            return
        provided = dict(scope["headers"]).get(b"authorization", b"")
        if not hmac.compare_digest(provided, self._expected):
            response = JSONResponse(
                {"error": "unauthorized"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)


def create_app(settings: Settings) -> Starlette:
    news_client = NewsApiClient(api_key=settings.news_api_key.get_secret_value())
    mcp = create_mcp_server(news_client)
    # Stateless + JSON responses so any replica can serve any request (Cloud Run / Render).
    # DNS rebinding protection is unnecessary here: every request is bearer-authenticated.
    app = mcp.streamable_http_app(stateless_http=True, json_response=True, host=settings.host)
    app.router.routes.append(Route("/health", health, methods=["GET"]))
    app.add_middleware(BearerAuthMiddleware, token=settings.auth_token.get_secret_value())

    mcp_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        async with news_client, mcp_lifespan(app):
            yield

    app.router.lifespan_context = lifespan
    return app
