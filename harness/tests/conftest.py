import pytest


@pytest.fixture(autouse=True)
def isolated_request_rate(tmp_path, monkeypatch):
    # The machine-wide limiter file belongs to live runs, never to tests.
    monkeypatch.setenv("VERACITY_RATE_DB", str(tmp_path / "request-rate.sqlite"))
