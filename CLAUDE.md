# Development Guidelines for Claude Code

## Project Overview
- Purpose: Model Context Protocol (MCP) server for News API, designed for deployment on Render and Google Cloud Run.
- Tech Stack: Python 3.12+, uv, Starlette/FastAPI, MCP SDK, httpx, Ruff, Pytest, Mypy.

## Coding Standards
1. **Type Safety:** All functions, methods, and classes must have strict type annotations. Pass `uv run mypy src` without warnings.
2. **Formatting & Linting:** Code must adhere to Ruff rules. Always run:
   - `uv run ruff format`
   - `uv run ruff check --fix`
3. **Encoding & Line Endings:** UTF-8 (BOM-less) with LF endings only.
4. **Error Handling:** External API errors (e.g., News API limits) must be caught cleanly and converted to informative MCP tool error responses. Never leak raw stack traces or internal secrets.
5. **Configuration:** All secrets (like `NEWS_API_KEY`, `AUTH_TOKEN`) must come from environment variables. Never hardcode credentials.

## Testing & Quality Control (TDD)
- **Framework:** Pytest with `pytest-asyncio`.
- **Mocking:** All HTTP calls to News API must be mocked using `respx` in tests. Do not call the live News API during automated tests.
- **Workflow:** For any new feature or tool, write or update the test first or in tandem. All tests must pass: `uv run pytest`.

## Git & Commit Workflow
- Commit messages must follow Conventional Commits:
  - `feat:` New features / tools
  - `fix:` Bug fixes
  - `test:` Adding or updating tests
  - `refactor:` Code improvements without behavioral change
  - `chore:` Configuration, dependencies, repo maintenance
- Keep commits focused and atomic.