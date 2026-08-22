"""Bridge P0 session identity to provider adapter TaskInput metadata."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from ..contracts import TaskInput
from .native import (
    NativeSessionResolution,
    NativeSessionStore,
    SessionMode,
    NativeSessionKey,
    execution_profile_fingerprint,
    resolve_native_session,
)


_ENV_SCOPE = "MCO_HYPER_SCOPE"
_ENV_MODE = "MCO_HYPER_SESSION_MODE"
_ENV_ID = "MCO_HYPER_SESSION_ID"


@dataclass(frozen=True)
class ProviderNativeSessionContext:
    store: NativeSessionStore
    resolution: NativeSessionResolution


def native_session_context(provider: str, task: TaskInput) -> Optional[ProviderNativeSessionContext]:
    """Resolve native-session state for a task, or None for upstream behaviour.

    Metadata keys are supported for internal callers/tests. The P0 CLI wrapper
    exports the same values through environment variables so existing upstream
    parser/data contracts do not need a broad rewrite.
    """
    raw_scope = task.metadata.get("native_session_scope", os.environ.get(_ENV_SCOPE, ""))
    raw_mode = task.metadata.get("native_session_mode", os.environ.get(_ENV_MODE, ""))
    raw_explicit = task.metadata.get("native_session_id", os.environ.get(_ENV_ID, ""))

    scope = raw_scope.strip() if isinstance(raw_scope, str) else ""
    mode_text = raw_mode.strip() if isinstance(raw_mode, str) else ""
    explicit_id = raw_explicit.strip() if isinstance(raw_explicit, str) else ""

    if not scope and not mode_text and not explicit_id:
        return None

    mode: SessionMode
    if mode_text:
        if mode_text not in ("reuse", "fresh", "explicit"):
            raise ValueError("unsupported native session mode: {}".format(mode_text))
        mode = mode_text  # type: ignore[assignment]
    elif explicit_id:
        mode = "explicit"
    elif scope:
        mode = "reuse"
    else:
        mode = "fresh"

    store = NativeSessionStore(task.repo_root)
    key: Optional[NativeSessionKey] = None
    if scope:
        key = NativeSessionKey(
            repo_root=task.repo_root,
            scope=scope,
            provider=provider,
            profile_fingerprint=execution_profile_fingerprint(provider, task.metadata),
        )

    resolution = resolve_native_session(
        mode=mode,
        store=store,
        key=key,
        explicit_id=explicit_id or None,
    )
    return ProviderNativeSessionContext(store=store, resolution=resolution)
