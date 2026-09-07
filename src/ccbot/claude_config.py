"""Claude Code global config (~/.claude.json) access — directory trust management.

Lets the bot pre-approve a working directory before launching Claude Code in a
freshly created tmux window, so the interactive "Do you trust the files in this
folder?" dialog never blocks the new session.

Key components:
  - claude_config_file(): resolve the config path (honours CLAUDE_CONFIG_DIR)
  - is_trusted_directory(): read projects.<path>.hasTrustDialogAccepted
  - ensure_trusted_directory(): set that flag when missing (no-op if already set)
"""

import json
import logging
import os
from pathlib import Path
from typing import Any

from .utils import atomic_write_json

logger = logging.getLogger(__name__)

# Field Claude Code checks to decide whether to show the trust dialog
TRUST_KEY = "hasTrustDialogAccepted"

# Defaults Claude Code writes when it first records a project; used only when
# creating an entry from scratch so the shape matches what Claude Code expects.
_NEW_PROJECT_ENTRY: dict[str, Any] = {
    "allowedTools": [],
    "mcpContextUris": [],
    "mcpServers": {},
    "enabledMcpjsonServers": [],
    "disabledMcpjsonServers": [],
    TRUST_KEY: True,
    "hasClaudeMdExternalIncludesApproved": False,
    "hasClaudeMdExternalIncludesWarningShown": False,
}


def claude_config_file() -> Path:
    """Path of Claude Code's global config file.

    Claude Code stores it at $CLAUDE_CONFIG_DIR/.claude.json when that env var
    is set, otherwise at ~/.claude.json.
    """
    raw = os.environ.get("CLAUDE_CONFIG_DIR", "")
    base = Path(raw).expanduser() if raw else Path.home()
    return base / ".claude.json"


def project_key(work_dir: str | Path) -> str:
    """Normalize a directory to the key Claude Code uses in `projects`."""
    return str(Path(work_dir).expanduser().resolve())


def _load(path: Path) -> dict[str, Any] | None:
    """Read the config file; None on missing/unreadable/malformed content."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("Cannot read Claude config %s: %s", path, e)
        return None
    return data if isinstance(data, dict) else None


def is_trusted_directory(work_dir: str | Path) -> bool:
    """Whether Claude Code already trusts this directory."""
    data = _load(claude_config_file())
    if not data:
        return False
    projects = data.get("projects")
    if not isinstance(projects, dict):
        return False
    entry = projects.get(project_key(work_dir))
    return isinstance(entry, dict) and entry.get(TRUST_KEY) is True


def ensure_trusted_directory(work_dir: str | Path) -> tuple[bool, str]:
    """Mark `work_dir` as trusted in Claude Code's config unless it already is.

    Returns (changed, detail): `changed` is True only when the file was
    rewritten; `detail` is a short human-readable status or error message.

    The file is read-modify-written atomically. Claude Code holds no lock on it,
    so a concurrent write by a running session could lose one of the two
    updates; the window is small and the alternative is a blocking trust dialog.
    """
    path = claude_config_file()
    key = project_key(work_dir)

    data = _load(path)
    if data is None:
        return False, f"could not read {path}"

    projects = data.get("projects")
    if projects is None:
        projects = {}
        data["projects"] = projects
    elif not isinstance(projects, dict):
        return False, f"unexpected 'projects' value in {path}"

    entry = projects.get(key)
    if isinstance(entry, dict):
        if entry.get(TRUST_KEY) is True:
            return False, "already trusted"
        entry[TRUST_KEY] = True
    else:
        projects[key] = dict(_NEW_PROJECT_ENTRY)

    # Preserve the file's permissions: atomic_write_json renames a 0600 temp
    # file over the target, which would otherwise tighten them silently.
    try:
        mode: int | None = path.stat().st_mode & 0o777
    except OSError:
        mode = None

    try:
        atomic_write_json(path, data)
        if mode is not None:
            os.chmod(path, mode)
    except OSError as e:
        logger.warning("Failed to write Claude config %s: %s", path, e)
        return False, f"could not write {path}: {e}"

    logger.info("Marked %s as trusted in %s", key, path)
    return True, "trusted"
