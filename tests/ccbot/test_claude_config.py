"""Tests for ccbot.claude_config: directory trust in Claude Code's config."""

import json
import os
from pathlib import Path

import pytest

from ccbot.claude_config import (
    claude_config_file,
    ensure_trusted_directory,
    is_trusted_directory,
    project_key,
)


@pytest.fixture
def claude_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point CLAUDE_CONFIG_DIR at a temp dir and return the config file path."""
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    return tmp_path / ".claude.json"


def _projects(config_file: Path) -> dict:
    return json.loads(config_file.read_text(encoding="utf-8"))["projects"]


class TestClaudeConfigFile:
    def test_uses_claude_config_dir(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", "/custom/claude")
        assert claude_config_file() == Path("/custom/claude/.claude.json")

    def test_defaults_to_home(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
        assert claude_config_file() == Path.home() / ".claude.json"


class TestEnsureTrustedDirectory:
    def test_creates_entry_when_file_missing(self, claude_home: Path, tmp_path: Path):
        work_dir = tmp_path / "proj"
        work_dir.mkdir()

        changed, detail = ensure_trusted_directory(work_dir)

        assert (changed, detail) == (True, "trusted")
        entry = _projects(claude_home)[str(work_dir.resolve())]
        assert entry["hasTrustDialogAccepted"] is True
        assert entry["mcpServers"] == {}

    def test_sets_flag_on_existing_entry(self, claude_home: Path, tmp_path: Path):
        work_dir = tmp_path / "proj"
        work_dir.mkdir()
        key = str(work_dir.resolve())
        claude_home.write_text(
            json.dumps(
                {
                    "numStartups": 3,
                    "projects": {
                        key: {"hasTrustDialogAccepted": False, "allowedTools": ["Bash"]}
                    },
                }
            ),
            encoding="utf-8",
        )

        changed, _ = ensure_trusted_directory(work_dir)

        assert changed is True
        data = json.loads(claude_home.read_text(encoding="utf-8"))
        # Unrelated keys survive the rewrite
        assert data["numStartups"] == 3
        assert data["projects"][key]["allowedTools"] == ["Bash"]
        assert data["projects"][key]["hasTrustDialogAccepted"] is True

    def test_noop_when_already_trusted(self, claude_home: Path, tmp_path: Path):
        work_dir = tmp_path / "proj"
        work_dir.mkdir()
        claude_home.write_text(
            json.dumps(
                {
                    "projects": {
                        str(work_dir.resolve()): {"hasTrustDialogAccepted": True}
                    }
                }
            ),
            encoding="utf-8",
        )
        before = claude_home.stat().st_mtime_ns

        changed, detail = ensure_trusted_directory(work_dir)

        assert (changed, detail) == (False, "already trusted")
        assert claude_home.stat().st_mtime_ns == before

    def test_preserves_file_permissions(self, claude_home: Path, tmp_path: Path):
        work_dir = tmp_path / "proj"
        work_dir.mkdir()
        claude_home.write_text(json.dumps({"projects": {}}), encoding="utf-8")
        os.chmod(claude_home, 0o664)

        ensure_trusted_directory(work_dir)

        assert claude_home.stat().st_mode & 0o777 == 0o664

    def test_does_not_clobber_malformed_config(self, claude_home: Path, tmp_path: Path):
        work_dir = tmp_path / "proj"
        work_dir.mkdir()
        claude_home.write_text("{not json", encoding="utf-8")

        changed, detail = ensure_trusted_directory(work_dir)

        assert changed is False
        assert "could not read" in detail
        assert claude_home.read_text(encoding="utf-8") == "{not json"

    def test_key_is_resolved_path(self, claude_home: Path, tmp_path: Path):
        work_dir = tmp_path / "proj"
        work_dir.mkdir()

        ensure_trusted_directory(f"{work_dir}/./")

        assert project_key(work_dir) in _projects(claude_home)


class TestIsTrustedDirectory:
    def test_false_without_config(self, claude_home: Path, tmp_path: Path):
        assert is_trusted_directory(tmp_path) is False

    def test_true_after_ensure(self, claude_home: Path, tmp_path: Path):
        work_dir = tmp_path / "proj"
        work_dir.mkdir()
        ensure_trusted_directory(work_dir)
        assert is_trusted_directory(work_dir) is True
