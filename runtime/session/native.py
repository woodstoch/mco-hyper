"""Provider-native session identity and persistence for MCO Hyper.

This module intentionally owns only session identity/state. Provider-specific
capture/resume behaviour belongs in provider adapters and the session daemon.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Literal, Mapping, Optional


SessionMode = Literal["reuse", "fresh", "explicit"]
_NATIVE_STATE_VERSION = 1
_NATIVE_STATE_PATH = ".mco/native-sessions.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def canonical_repo_root(repo_root: str) -> str:
    """Return a stable repository root, falling back to the resolved path.

    Session identity must be repository-scoped, but callers may enter the same
    repository from different subdirectories. Prefer Git's canonical top-level
    when available and keep non-Git use working via ``Path.resolve``.
    """
    resolved = str(Path(repo_root).expanduser().resolve())
    try:
        result = subprocess.run(
            ["git", "-C", resolved, "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=False,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return resolved
    if result.returncode == 0 and result.stdout.strip():
        return str(Path(result.stdout.strip()).resolve())
    return resolved


def execution_profile_fingerprint(provider: str, metadata: Mapping[str, Any]) -> str:
    """Fingerprint current P0 provider execution settings.

    P1 will introduce named Profiles/Connections. Until then P0 still needs to
    prevent a model or permission/context change from silently reusing a native
    session. Only stable execution-relevant fields participate; prompt/task and
    artifact metadata deliberately do not.
    """
    payload = {
        "provider": provider,
        "model": metadata.get("model"),
        "provider_permissions": metadata.get("provider_permissions"),
        "provider_context": metadata.get("provider_context"),
    }
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class NativeSessionKey:
    """Reusable native-session identity.

    Prompt text is intentionally absent. Topic/workflow identity is always an
    explicit scope supplied by the caller.
    """

    repo_root: str
    scope: str
    provider: str
    profile_fingerprint: str

    def __post_init__(self) -> None:
        scope = self.scope.strip()
        provider = self.provider.strip()
        fingerprint = self.profile_fingerprint.strip()
        if not scope:
            raise ValueError("native session reuse requires a non-empty scope")
        if not provider:
            raise ValueError("native session provider must not be empty")
        if not fingerprint:
            raise ValueError("native session profile fingerprint must not be empty")
        object.__setattr__(self, "repo_root", canonical_repo_root(self.repo_root))
        object.__setattr__(self, "scope", scope)
        object.__setattr__(self, "provider", provider)
        object.__setattr__(self, "profile_fingerprint", fingerprint)

    @property
    def stable_id(self) -> str:
        payload = json.dumps(
            {
                "repo_root": self.repo_root,
                "scope": self.scope,
                "provider": self.provider,
                "profile_fingerprint": self.profile_fingerprint,
            },
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class NativeSessionRecord:
    repo_root: str
    scope: str
    provider: str
    profile_fingerprint: str
    native_session_id: str
    created_at: str
    updated_at: str
    session_type: str = "native"

    @classmethod
    def from_key(
        cls,
        key: NativeSessionKey,
        native_session_id: str,
        *,
        created_at: Optional[str] = None,
    ) -> "NativeSessionRecord":
        native_id = native_session_id.strip()
        if not native_id:
            raise ValueError("native session id must not be empty")
        now = _now_iso()
        return cls(
            repo_root=key.repo_root,
            scope=key.scope,
            provider=key.provider,
            profile_fingerprint=key.profile_fingerprint,
            native_session_id=native_id,
            created_at=created_at or now,
            updated_at=now,
        )


@dataclass(frozen=True)
class NativeSessionResolution:
    mode: SessionMode
    key: Optional[NativeSessionKey]
    native_session_id: Optional[str]
    should_persist: bool


@contextmanager
def _exclusive_lock(lock_path: Path) -> Iterator[None]:
    """Process-safe advisory lock with POSIX and Windows implementations."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+b")
    try:
        try:
            import fcntl  # type: ignore
        except ImportError:  # pragma: no cover - Windows-only branch
            import msvcrt  # type: ignore
            handle.seek(0)
            if handle.tell() == 0:
                handle.write(b"0")
                handle.flush()
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()


class NativeSessionStore:
    """Atomic, process-safe store for canonical reusable native sessions."""

    def __init__(self, repo_root: str, path: Optional[Path] = None) -> None:
        self.repo_root = canonical_repo_root(repo_root)
        self.path = path or (Path(self.repo_root) / _NATIVE_STATE_PATH)
        self.lock_path = self.path.with_suffix(self.path.suffix + ".lock")

    def _read_unlocked(self) -> Dict[str, Any]:
        if not self.path.exists():
            return {"version": _NATIVE_STATE_VERSION, "sessions": {}}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("invalid native session state: {}".format(self.path)) from exc
        if not isinstance(data, dict) or data.get("version") != _NATIVE_STATE_VERSION:
            raise ValueError("unsupported native session state version")
        sessions = data.get("sessions")
        if not isinstance(sessions, dict):
            raise ValueError("invalid native session state sessions map")
        return data

    def _write_unlocked(self, data: Dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_name("{}.{}.{}.tmp".format(self.path.name, os.getpid(), uuid.uuid4().hex))
        payload = json.dumps(data, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
        try:
            with temp_path.open("w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, self.path)
        finally:
            try:
                temp_path.unlink()
            except FileNotFoundError:
                pass

    @staticmethod
    def _record_matches_key(record: NativeSessionRecord, key: NativeSessionKey) -> bool:
        return (
            record.repo_root == key.repo_root
            and record.scope == key.scope
            and record.provider == key.provider
            and record.profile_fingerprint == key.profile_fingerprint
        )

    def get(self, key: NativeSessionKey) -> Optional[NativeSessionRecord]:
        with _exclusive_lock(self.lock_path):
            data = self._read_unlocked()
            raw = data["sessions"].get(key.stable_id)
            if not isinstance(raw, dict):
                return None
            try:
                record = NativeSessionRecord(**raw)
            except TypeError as exc:
                raise ValueError("invalid native session record") from exc
            return record if self._record_matches_key(record, key) else None

    def put(self, key: NativeSessionKey, native_session_id: str) -> NativeSessionRecord:
        with _exclusive_lock(self.lock_path):
            data = self._read_unlocked()
            existing_raw = data["sessions"].get(key.stable_id)
            created_at: Optional[str] = None
            if isinstance(existing_raw, dict):
                value = existing_raw.get("created_at")
                if isinstance(value, str) and value:
                    created_at = value
            record = NativeSessionRecord.from_key(key, native_session_id, created_at=created_at)
            data["sessions"][key.stable_id] = asdict(record)
            self._write_unlocked(data)
            return record

    def delete(self, key: NativeSessionKey) -> bool:
        with _exclusive_lock(self.lock_path):
            data = self._read_unlocked()
            removed = data["sessions"].pop(key.stable_id, None) is not None
            if removed:
                self._write_unlocked(data)
            return removed

    def list_records(self) -> List[NativeSessionRecord]:
        with _exclusive_lock(self.lock_path):
            data = self._read_unlocked()
            records: List[NativeSessionRecord] = []
            for raw in data["sessions"].values():
                if not isinstance(raw, dict):
                    continue
                try:
                    records.append(NativeSessionRecord(**raw))
                except TypeError:
                    continue
            return sorted(records, key=lambda item: (item.repo_root, item.scope, item.provider, item.profile_fingerprint))


def resolve_native_session(
    *,
    mode: SessionMode,
    store: NativeSessionStore,
    key: Optional[NativeSessionKey] = None,
    explicit_id: Optional[str] = None,
) -> NativeSessionResolution:
    """Resolve P0 session mode without invoking any provider.

    ``fresh`` never reads or overwrites canonical reusable state. ``explicit``
    uses exactly the supplied ID and likewise does not silently replace the
    reusable mapping. ``reuse`` is the only mode that reads/writes the mapping.
    """
    if mode == "fresh":
        return NativeSessionResolution(mode=mode, key=key, native_session_id=None, should_persist=False)
    if key is None:
        raise ValueError("session mode '{}' requires a scoped native session key".format(mode))
    if mode == "explicit":
        native_id = (explicit_id or "").strip()
        if not native_id:
            raise ValueError("explicit session mode requires a native session id")
        return NativeSessionResolution(mode=mode, key=key, native_session_id=native_id, should_persist=False)
    if mode != "reuse":
        raise ValueError("unsupported session mode: {}".format(mode))
    record = store.get(key)
    return NativeSessionResolution(
        mode=mode,
        key=key,
        native_session_id=record.native_session_id if record else None,
        should_persist=True,
    )


def persist_captured_session(
    store: NativeSessionStore,
    resolution: NativeSessionResolution,
    captured_session_id: Optional[str],
) -> Optional[NativeSessionRecord]:
    """Persist a captured ID only for canonical ``reuse`` resolution."""
    native_id = (captured_session_id or "").strip()
    if not resolution.should_persist or resolution.key is None or not native_id:
        return None
    return store.put(resolution.key, native_id)
