import sys

import uvicorn
from pydantic import ValidationError

from news_mcp_server.config import Settings
from news_mcp_server.server import create_app


def load_settings() -> Settings:
    """Load settings, exiting with a secret-free message if the environment is invalid.

    pydantic's default error text echoes every input value (including NEWS_API_KEY),
    which would end up in Render / Cloud Run logs.
    """
    try:
        return Settings()  # type: ignore[call-arg]  # required fields come from the environment
    except ValidationError as exc:
        problems = "\n".join(
            f"  {'.'.join(str(part) for part in error['loc']).upper()}: {error['msg']}"
            for error in exc.errors(include_input=False, include_url=False)
        )
        sys.exit(f"Invalid configuration from environment variables:\n{problems}")


def main() -> None:
    settings = load_settings()
    uvicorn.run(
        create_app(settings),
        host=settings.host,
        port=settings.port,
        proxy_headers=True,
        forwarded_allow_ips="*",
    )


if __name__ == "__main__":
    main()
