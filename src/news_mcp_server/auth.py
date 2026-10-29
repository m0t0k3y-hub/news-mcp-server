"""Bearer-token authentication for the public HTTP endpoint."""

import hmac
from collections.abc import Iterable

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

DEFAULT_PUBLIC_PATHS = frozenset({"/health"})


class BearerAuthMiddleware:
    """Require `Authorization: Bearer <token>` on every HTTP request except public paths.

    Public paths (by default `/health`) bypass auth so Render / Cloud Run health checks work.
    """

    def __init__(
        self,
        app: ASGIApp,
        token: str,
        public_paths: Iterable[str] = DEFAULT_PUBLIC_PATHS,
    ) -> None:
        if not token:
            raise ValueError("Auth token must not be empty.")
        self.app = app
        self._expected = f"Bearer {token}".encode()
        self._public_paths = frozenset(public_paths)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] in self._public_paths:
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
