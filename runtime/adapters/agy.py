from __future__ import annotations

import json
import subprocess
from dataclasses import replace
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from ..answer_transport import AnswerDelta, AnswerTransport
from ..contracts import CapabilitySet, TaskInput, TaskRunRef, TaskStatus
from ..session.native import persist_captured_session
from ..session.provider_native import ProviderNativeSessionContext, native_session_context
from .shim import ShimAdapterBase


def _agy_payload(raw: str) -> Optional[Mapping[str, Any]]:
    try:
        payload = json.loads(raw.strip())
    except (json.JSONDecodeError, TypeError):
        return None
    return payload if isinstance(payload, Mapping) else None


def _capture_conversation_id(raw_stdout: str) -> Optional[str]:
    payload = _agy_payload(raw_stdout)
    if payload is None:
        return None
    value = payload.get("conversation_id")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def decode_agy_result(raw: str) -> AnswerTransport:
    """Decode Antigravity headless JSON without changing the answer semantics."""
    payload = _agy_payload(raw)
    if payload is None:
        text = raw.strip()
        return AnswerTransport((AnswerDelta(text),) if text else (), text, "failed", None)

    response = payload.get("response")
    final_answer = response if isinstance(response, str) else ""
    raw_status = payload.get("status")
    normalized = str(raw_status or "").upper()
    status = "succeeded" if normalized == "SUCCESS" else "failed"

    usage_payload = payload.get("usage")
    usage: Optional[dict[str, int]] = None
    if isinstance(usage_payload, Mapping):
        mapped: dict[str, int] = {}
        for source, target in (
            ("input_tokens", "prompt_tokens"),
            ("output_tokens", "completion_tokens"),
            ("total_tokens", "total_tokens"),
            ("thinking_tokens", "thinking_tokens"),
            ("cache_read_tokens", "cache_read_tokens"),
        ):
            value = usage_payload.get(source)
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                mapped[target] = value
        usage = mapped or None

    deltas = (AnswerDelta(final_answer),) if final_answer else ()
    return AnswerTransport(deltas, final_answer, status, usage)


class AgyAdapter(ShimAdapterBase):
    def __init__(self) -> None:
        super().__init__(
            provider_id="agy",  # type: ignore[arg-type]
            binary_name="agy",
            capability_set=CapabilitySet(
                tiers=["C0", "C1", "C2", "C3", "C4", "C5"],
                supports_native_async=False,
                supports_poll_endpoint=False,
                supports_resume_after_restart=True,
                supports_schema_enforcement=True,
                min_supported_version="1.1.8",
                tested_os=["macos"],
            ),
        )
        self._native_sessions: Dict[str, ProviderNativeSessionContext] = {}

    def _auth_check_command(self, binary: str) -> List[str]:
        # AGY has no dedicated non-interactive auth-status command. Since
        # 1.1.12, `models --output-format json` is machine-readable and does
        # not create an agent conversation or spend inference quota.
        return [binary, "models", "--output-format", "json"]

    def _probe_auth(self, binary: str) -> tuple[bool, str]:
        try:
            result = subprocess.run(
                self._auth_check_command(binary),
                capture_output=True,
                text=True,
                check=False,
                stdin=subprocess.DEVNULL,
                timeout=10,
            )
        except subprocess.TimeoutExpired:
            return False, "auth_check_timeout"
        except OSError:
            return False, "probe_unknown_error"
        if result.returncode == 0:
            return True, "ok"
        output = "{}\n{}".format(result.stdout or "", result.stderr or "").lower()
        if any(marker in output for marker in ("authentication required", "not authenticated", "login", "credential")):
            return False, "auth_check_failed"
        if any(marker in output for marker in ("unknown flag", "unknown option", "invalid", "output-format")):
            return False, "probe_config_error"
        return False, "probe_unknown_error"

    def supported_permission_keys(self) -> List[str]:
        # P0 deliberately exposes only what a one-run CLI flag can enforce.
        # Fine-grained allow/deny rules remain owned by AGY settings.
        return ["dangerously_skip_permissions"]

    def supported_model_keys(self) -> List[str]:
        return ["model"]

    def supported_context_keys(self) -> List[str]:
        return ["effort"]

    def decode_transport(self, raw: str) -> AnswerTransport:
        return decode_agy_result(raw)

    def run(self, input_task: TaskInput) -> TaskRunRef:
        context = native_session_context(self.id, input_task)
        ref = super().run(input_task)
        if context is not None:
            self._native_sessions[ref.run_id] = context
            if context.resolution.native_session_id:
                return replace(ref, session_id=context.resolution.native_session_id)
        return ref

    def poll(self, ref: TaskRunRef) -> TaskStatus:
        status = super().poll(ref)
        if not status.completed:
            return status
        context = self._native_sessions.pop(ref.run_id, None)
        if context is None or status.attempt_state != "SUCCEEDED":
            return status
        stdout_path = Path(ref.artifact_path) / "raw" / "agy.stdout.log"
        try:
            raw_stdout = stdout_path.read_text(encoding="utf-8") if stdout_path.exists() else ""
        except OSError:
            raw_stdout = ""
        persist_captured_session(
            context.store,
            context.resolution,
            _capture_conversation_id(raw_stdout),
        )
        return status

    def _build_command(self, input_task: TaskInput) -> List[str]:
        cmd = [
            "agy",
            "-p",
            input_task.prompt,
            "--output-format",
            "json",
            "--print-timeout",
            "{}s".format(max(1, int(input_task.timeout_seconds))),
        ]

        native = native_session_context(self.id, input_task)
        if native is not None and native.resolution.native_session_id:
            cmd.extend(["--conversation", native.resolution.native_session_id])

        permissions = input_task.metadata.get("provider_permissions", {})
        if isinstance(permissions, Mapping):
            dangerous = permissions.get("dangerously_skip_permissions")
            if dangerous == "true":
                cmd.append("--dangerously-skip-permissions")
            elif dangerous not in (None, "", "false"):
                raise ValueError("unsupported AGY dangerously_skip_permissions value: {}".format(dangerous))

        model = input_task.metadata.get("model")
        if isinstance(model, str) and model.strip():
            cmd.extend(["--model", model.strip()])

        if "provider_context" in input_task.metadata:
            context = input_task.metadata.get("provider_context", {})
            if not isinstance(context, Mapping):
                context = {}
            effort = context.get("effort")
            if effort is not None:
                effort_text = str(effort).strip().lower()
                if effort_text not in ("low", "medium", "high"):
                    raise ValueError("unsupported AGY effort: {}".format(effort))
                cmd.extend(["--effort", effort_text])

        output_schema_path = input_task.metadata.get("output_schema_path")
        if isinstance(output_schema_path, str) and output_schema_path.strip():
            cmd.extend(["--json-schema", output_schema_path.strip()])
        return cmd

    def _build_command_for_record(self) -> List[str]:
        return [
            "agy",
            "-p",
            "<prompt>",
            "--output-format",
            "json",
            "--print-timeout",
            "<timeout>",
        ]

    def _is_success(self, return_code: int, stdout_text: str, stderr_text: str) -> bool:
        _ = stderr_text
        if return_code != 0:
            return False
        payload = _agy_payload(stdout_text)
        return bool(payload is not None and str(payload.get("status", "")).upper() == "SUCCESS")
