from pathlib import Path

import pytest

from news_mcp_server.__main__ import main

API_KEY = "super-secret-news-api-key"
AUTH_TOKEN = "super-secret-auth-token"


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # Keep a developer's local .env and shell environment out of these tests.
    monkeypatch.chdir(tmp_path)
    for name in ("NEWS_API_KEY", "AUTH_TOKEN", "HOST", "PORT"):
        monkeypatch.delenv(name, raising=False)


def test_missing_setting_exits_without_leaking_secrets(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("NEWS_API_KEY", API_KEY)

    with pytest.raises(SystemExit) as exc_info:
        main()

    message = str(exc_info.value.code)
    assert exc_info.value.code != 0
    assert "AUTH_TOKEN" in message
    assert API_KEY not in message
    captured = capsys.readouterr()
    assert API_KEY not in captured.out + captured.err


def test_invalid_setting_exits_without_leaking_secrets(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("NEWS_API_KEY", API_KEY)
    monkeypatch.setenv("AUTH_TOKEN", AUTH_TOKEN)
    monkeypatch.setenv("PORT", "not-a-port")

    with pytest.raises(SystemExit) as exc_info:
        main()

    message = str(exc_info.value.code)
    assert "PORT" in message
    for secret in (API_KEY, AUTH_TOKEN):
        assert secret not in message
    captured = capsys.readouterr()
    for secret in (API_KEY, AUTH_TOKEN):
        assert secret not in captured.out + captured.err
