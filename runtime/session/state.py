"""Session state persistence — state.json and history.jsonl."""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


_SESSIONS_ROOT = ".mco/sessions"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _auto_name(provider: str) -> str:
    import uuid
    return "{}-{}".format(provider, uuid.uuid4().hex[:4])


@dataclass
class SessionState:
    name: str
    provider: str
    pid: Optional[int] = None
    status: str = "active"  # active | stopped | crashed
    created_at: str = ""
    last_active: str = ""
    repo_root: str = "."
    turn_count: int = 0

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = _now_iso()
        if not self.last_active:
            self.last_active = self.created_at


@dataclass
class HistoryEntry:
    role: str  # "user" | "assistant"
    content: str
    timestamp: str = ""
    wall_clock_seconds: float = 0.0

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = _now_iso()


def sessions_root(repo_root: str = ".") -> Path:
    """Return the sessions root directory for a repo."""
    return Path(repo_root) / _SESSIONS_ROOT


def validate_session_name(name: str) -> None:
    """Validate session name as a safe filesystem path segment.

    Raises ValueError if name is empty, contains path separators,
    absolute-path markers, .. traversal, "." (current-dir), or control characters.
    """
    if not name or not name.strip():
        raise ValueError("session name must not be empty")
    if name == ".":
        raise ValueError("session name must not be a single dot (current directory)")
    if "\x00" in name:
        raise ValueError("session name contains null byte")
    if any(ord(ch) < 0x20 for ch in name):
        raise ValueError("session name contains control characters")
    if name.startswith("/") or name.startswith("\\"):
        raise ValueError("session name must not be an absolute path")
    if ".." in name.replace("\\", "/").split("/"):
        raise ValueError("session name contains path traversal")
    if "/" in name or "\\" in name:
        raise ValueError("session name must not contain path separators")


def session_dir(repo_root: str, name: str) -> Path:
    """Return the directory for a specific session."""
    validate_session_name(name)
    return sessions_root(repo_root) / name


def save_state(repo_root: str, state: SessionState) -> Path:
    """Write session state to state.json. Creates directory if needed."""
    d = session_dir(repo_root, state.name)
    d.mkdir(parents=True, exist_ok=True)
    path = d / "state.json"
    path.write_text(json.dumps(asdict(state), indent=2), encoding="utf-8")
    return path


def load_state(repo_root: str, name: str) -> Optional[SessionState]:
    """Load session state from state.json. Returns None if not found."""
    path = session_dir(repo_root, name) / "state.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return SessionState(**data)
    except (json.JSONDecodeError, TypeError):
        return None


def append_history(repo_root: str, name: str, entry: HistoryEntry) -> None:
    """Append a history entry to history.jsonl."""
    d = session_dir(repo_root, name)
    d.mkdir(parents=True, exist_ok=True)
    path = d / "history.jsonl"
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(asdict(entry), ensure_ascii=True) + "\n")


def load_history(repo_root: str, name: str) -> List[HistoryEntry]:
    """Load all history entries from history.jsonl."""
    path = session_dir(repo_root, name) / "history.jsonl"
    if not path.exists():
        return []
    entries: List[HistoryEntry] = []
    for line in path.read_text(encoding="utf-8").strip().splitlines():
        if not line.strip():
            continue
        try:
            data = json.loads(line)
            entries.append(HistoryEntry(**data))
        except (json.JSONDecodeError, TypeError):
            continue
    return entries


def list_sessions(repo_root: str) -> List[SessionState]:
    """List all sessions by reading state.json from each session directory."""
    root = sessions_root(repo_root)
    if not root.exists():
        return []
    sessions: List[SessionState] = []
    for item in sorted(root.iterdir()):
        if item.is_dir():
            state = load_state(repo_root, item.name)
            if state is not None:
                sessions.append(state)
    return sessions


_MAX_HISTORY_TURNS = 20  # Keep last N user+assistant pairs
_MAX_HISTORY_CHARS = 50_000  # Truncate if total history exceeds this


def _native_session_pointer_available() -> bool:
    """Return whether this session daemon has a canonical native pointer.

    The manager sets these environment values only for providers whose P0
    adapters implement exact native resume. If capture has not succeeded yet,
    return False so the existing synthetic-history path remains the fallback.
    """
    if os.environ.get("MCO_HYPER_NATIVE_SESSION_ACTIVE") != "1":
        return False
    provider = os.environ.get("MCO_HYPER_NATIVE_PROVIDER", "").strip()
    scope = os.environ.get("MCO_HYPER_SCOPE", "").strip()
    repo_root = os.environ.get("MCO_HYPER_NATIVE_REPO_ROOT", "").strip()
    if not provider or not scope or not repo_root:
        return False
    try:
        from .native import (
            NativeSessionKey,
            NativeSessionStore,
            execution_profile_fingerprint,
        )
        key = NativeSessionKey(
            repo_root=repo_root,
            scope=scope,
            provider=provider,
            profile_fingerprint=execution_profile_fingerprint(provider, {}),
        )
        return NativeSessionStore(repo_root).get(key) is not None
    except (OSError, ValueError):
        # Session history is an existing, conservative fallback. Corrupt or
        # temporarily unreadable native metadata must not make continuity fail.
        return False


def build_history_prompt(history: List[HistoryEntry], new_prompt: str) -> str:
    """Build a prompt with synthetic history only when native resume is absent.

    For P0 native-session daemons (Codex, Copilot, AGY), once a reusable native
    pointer has been captured, the provider session is authoritative and only
    the current request is sent. Before a pointer exists, or if native state is
    unavailable, the original synthetic-history behaviour remains the fallback.

    Truncation: keeps the last _MAX_HISTORY_TURNS entries and caps total
    character count at _MAX_HISTORY_CHARS. Earlier entries are summarized
    as "(N earlier turns omitted)".
    """
    if not history or _native_session_pointer_available():
        return new_prompt

    # Truncate to last N entries
    if len(history) > _MAX_HISTORY_TURNS:
        omitted = len(history) - _MAX_HISTORY_TURNS
        history = history[-_MAX_HISTORY_TURNS:]
        prefix_note = "({} earlier turns omitted)\n\n".format(omitted)
    else:
        prefix_note = ""

    lines = ["## Conversation History", ""]
    if prefix_note:
        lines.append(prefix_note)

    total_chars = 0
    for entry in history:
        role_label = "User" if entry.role == "user" else "Assistant"
        text = entry.content
        # Per-entry truncation if total exceeds budget
        remaining = _MAX_HISTORY_CHARS - total_chars
        if remaining <= 0:
            lines.append("({} more turns truncated)".format(len(history) - history.index(entry)))
            break
        if len(text) > remaining:
            text = text[:remaining] + "... (truncated)"
        lines.append("{}: {}".format(role_label, text))
        lines.append("")
        total_chars += len(text)

    lines.append("## Current Request")
    lines.append(new_prompt)
    return "\n".join(lines)
