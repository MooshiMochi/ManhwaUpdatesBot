"""Path resolution for /migrate leftovers file is CWD-independent."""

from __future__ import annotations

from pathlib import Path

from manhwa_bot.cogs.migrate import _REPO_ROOT, _leftovers_path


def test_env_override_wins(monkeypatch):
    monkeypatch.setenv("MIGRATION_LEFTOVERS_PATH", "/tmp/custom.json")
    assert _leftovers_path() == Path("/tmp/custom.json")


def test_falls_back_to_repo_root_when_cwd_relative_missing(monkeypatch, tmp_path):
    monkeypatch.delenv("MIGRATION_LEFTOVERS_PATH", raising=False)
    monkeypatch.chdir(tmp_path)  # CWD has no data/migration_leftovers.json
    resolved = _leftovers_path()
    assert resolved == _REPO_ROOT / "data" / "migration_leftovers.json"
    assert resolved.is_absolute()
