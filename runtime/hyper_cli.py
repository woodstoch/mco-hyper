"""Thin MCO Hyper CLI pre-parser for fork-specific P0 session flags.

The upstream CLI remains authoritative for all existing options. This wrapper
only removes Hyper session flags, exports their values for provider adapters,
enables fork-specific built-in providers, and then delegates to
``runtime.cli.main``. Keeping the shim isolated avoids a large rewrite of the
upstream parser during P0.
"""
from __future__ import annotations

import os
import sys
from typing import Dict, List, Optional, Tuple

from . import cli as upstream_cli


_ENV_SCOPE = "MCO_HYPER_SCOPE"
_ENV_MODE = "MCO_HYPER_SESSION_MODE"
_ENV_ID = "MCO_HYPER_SESSION_ID"
_SESSION_MODES = {"reuse", "fresh", "explicit"}
_HYPER_PROVIDERS = ("agy",)


def _enable_hyper_providers() -> None:
    providers = list(upstream_cli.SUPPORTED_PROVIDERS)
    for provider in _HYPER_PROVIDERS:
        if provider not in providers:
            providers.append(provider)
    resolved = tuple(providers)
    upstream_cli.SUPPORTED_PROVIDERS = resolved
    upstream_cli.SUPPORTED_PROVIDER_LIST = ",".join(resolved)
    upstream_cli.DEFAULT_DOCTOR_PROVIDERS = resolved


def _pop_value(argv: List[str], index: int, option: str) -> Tuple[str, int]:
    token = argv[index]
    prefix = option + "="
    if token.startswith(prefix):
        value = token[len(prefix):]
        if not value:
            raise ValueError("{} requires a value".format(option))
        return value, index + 1
    if index + 1 >= len(argv):
        raise ValueError("{} requires a value".format(option))
    value = argv[index + 1]
    if value.startswith("--"):
        raise ValueError("{} requires a value".format(option))
    return value, index + 2


def extract_hyper_session_args(argv: List[str]) -> Tuple[List[str], Dict[str, str]]:
    """Remove Hyper P0 flags and return environment values for adapters."""
    if "run" not in argv and "review" not in argv:
        return list(argv), {}

    filtered: List[str] = []
    values: Dict[str, str] = {}
    index = 0
    while index < len(argv):
        token = argv[index]
        if token == "--scope" or token.startswith("--scope="):
            value, index = _pop_value(argv, index, "--scope")
            values[_ENV_SCOPE] = value.strip()
            continue
        if token == "--session-mode" or token.startswith("--session-mode="):
            value, index = _pop_value(argv, index, "--session-mode")
            value = value.strip()
            if value not in _SESSION_MODES:
                raise ValueError("--session-mode must be one of: explicit, fresh, reuse")
            values[_ENV_MODE] = value
            continue
        if token == "--session-id" or token.startswith("--session-id="):
            value, index = _pop_value(argv, index, "--session-id")
            values[_ENV_ID] = value.strip()
            continue
        filtered.append(token)
        index += 1

    scope = values.get(_ENV_SCOPE, "")
    explicit_id = values.get(_ENV_ID, "")
    mode = values.get(_ENV_MODE)

    if scope and mode is None:
        values[_ENV_MODE] = "reuse"
        mode = "reuse"
    if explicit_id and mode is None:
        values[_ENV_MODE] = "explicit"
        mode = "explicit"
    if explicit_id and mode != "explicit":
        raise ValueError("--session-id requires --session-mode explicit")
    if mode in ("reuse", "explicit") and not scope:
        raise ValueError("--session-mode {} requires --scope".format(mode))
    if mode == "explicit" and not explicit_id:
        raise ValueError("--session-mode explicit requires --session-id")

    return filtered, values


def main(argv: Optional[List[str]] = None) -> int:
    raw = list(argv if argv is not None else sys.argv[1:])
    try:
        filtered, values = extract_hyper_session_args(raw)
    except ValueError as exc:
        print("mco: error: {}".format(exc), file=sys.stderr)
        return 2

    _enable_hyper_providers()
    previous = {key: os.environ.get(key) for key in (_ENV_SCOPE, _ENV_MODE, _ENV_ID)}
    try:
        for key in (_ENV_SCOPE, _ENV_MODE, _ENV_ID):
            os.environ.pop(key, None)
        os.environ.update(values)
        return upstream_cli.main(filtered)
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
