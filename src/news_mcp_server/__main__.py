import uvicorn

from news_mcp_server.config import Settings
from news_mcp_server.server import create_app


def main() -> None:
    settings = Settings()  # type: ignore[call-arg]  # required fields come from the environment
    uvicorn.run(
        create_app(settings),
        host=settings.host,
        port=settings.port,
        proxy_headers=True,
        forwarded_allow_ips="*",
    )


if __name__ == "__main__":
    main()
