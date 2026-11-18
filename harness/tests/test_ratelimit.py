from pathlib import Path

import pytest

from veracity_harness import ratelimit
from veracity_harness.ratelimit import try_acquire


def test_requests_per_model_stay_within_a_sliding_minute_across_callers(tmp_path):
    path = tmp_path / "rate.sqlite"
    # Separate calls stand in for separate processes: all state lives in the file.
    assert [try_acquire(path, "@cf/a", 2, now) for now in (100.0, 101.0)] == [0.0, 0.0]
    # A third start inside the minute waits until the oldest one leaves the window.
    assert try_acquire(path, "@cf/a", 2, 110.0) == 50.0
    # Other models have their own allowance.
    assert try_acquire(path, "@cf/b", 2, 110.0) == 0.0
    assert try_acquire(path, "@cf/a", 2, 160.5) == 0.0
    assert try_acquire(path, "@cf/a", 2, 161.5) == 0.0
    assert try_acquire(path, "@cf/a", 2, 162.0) > 0.0


def test_default_rate_store_honors_writable_xdg_cache(monkeypatch, tmp_path):
    monkeypatch.delenv("VERACITY_RATE_DB")
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    path = ratelimit.default_path()
    assert path == tmp_path / "cache/veracity-harness/request-rate.sqlite"
    assert try_acquire(path, "fixture", 2, 100) == 0


def test_default_rate_store_falls_back_to_one_shared_writable_store(monkeypatch, tmp_path):
    blocked = tmp_path / "blocked"
    blocked.write_text("not a directory")
    temporary = tmp_path / "temporary"
    temporary.mkdir()
    monkeypatch.delenv("VERACITY_RATE_DB")
    monkeypatch.setenv("XDG_CACHE_HOME", str(blocked))
    monkeypatch.setattr(Path, "home", lambda: blocked)
    monkeypatch.setattr("tempfile.gettempdir", lambda: str(temporary))
    first, second = ratelimit.default_path(), ratelimit.default_path()
    assert first == second and first.is_relative_to(temporary)
    assert try_acquire(first, "fixture", 1, 100) == 0
    assert try_acquire(second, "fixture", 1, 110) == 50


def test_explicit_unwritable_rate_store_fails_before_use(monkeypatch, tmp_path):
    blocked = tmp_path / "blocked"
    blocked.write_text("not a directory")
    monkeypatch.setenv("VERACITY_RATE_DB", str(blocked / "rate.sqlite"))
    with pytest.raises(RuntimeError, match="VERACITY_RATE_DB"):
        ratelimit.default_path()
