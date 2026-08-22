from __future__ import annotations

import uuid
from dataclasses import replace
from typing import Any, Dict, List, Optional, Tuple

from ..contracts import CapabilitySet, TaskInput, TaskRunRef, TaskStatus
from ..session.native import persist_captured_session
from ..session.provider_native import ProviderNativeSessionContext, native_session_context
from .shim import ShimAdapterBase


_COPILOT_SESSION_NAMESPACE = uuid.UUID("9c4df279-f2ba-4b48-8511-0a2df8b7da7e")
_INTERNAL_SESSION_ID = "_mco_hyper_copilot_session_id"


class CopilotAdapter(ShimAdapterBase):
    def __init__(self) -> None:
        super().__init__(
            provider_id="copilot",
            binary_name="copilot",
            capability_set=CapabilitySet(
                tiers=["C0", "C1", "C2", "C3"],
                supports_native_async=False,
                supports_poll_endpoint=False,
                supports_resume_after_restart=True,
                supports_schema_enforcement=False,
                min_supported_version="1.0.65",
                tested_os=["macos"],
            ),
        )
        self._native_sessions: Dict[str, Tuple[ProviderNativeSessionContext, str]] = {}

    def _auth_check_command(self, binary: str) -> List[str]:
        return [binary, "-p", "Reply with exactly OK", "-s", "--allow-all-tools", "--no-ask-user"]

    def supported_model_keys(self) -> List[str]:
        return ["model"]

    def supported_permission_keys(self) -> List[str]:
        return ["access"]

    @staticmethod
    def _session_id_for_context(context: ProviderNativeSessionContext) -> str:
        resolution = context.resolution
        if resolution.native_session_id:
            return resolution.native_session_id
        if resolution.mode == "reuse" and resolution.key is not None:
            # Copilot accepts a valid UUID that either resumes an existing
            # session or creates it when absent. UUIDv5 makes canonical reuse
            # deterministic without requiring a failed first run to be saved.
            return str(uuid.uuid5(_COPILOT_SESSION_NAMESPACE, resolution.key.stable_id))
        return str(uuid.uuid4())

    def run(self, input_task: TaskInput) -> TaskRunRef:
        context = native_session_context(self.id, input_task)
        session_id: Optional[str] = None
        if context is not None:
            session_id = self._session_id_for_context(context)
            # TaskInput is frozen but metadata is intentionally mutable runtime
            # context. Set the exact ID once so command construction and run
            # bookkeeping cannot diverge for fresh UUIDs.
            input_task.metadata[_INTERNAL_SESSION_ID] = session_id
        ref = super().run(input_task)
        if context is not None and session_id is not None:
            self._native_sessions[ref.run_id] = (context, session_id)
            return replace(ref, session_id=session_id)
        return ref

    def poll(self, ref: TaskRunRef) -> TaskStatus:
        status = super().poll(ref)
        if not status.completed:
            return status
        native = self._native_sessions.pop(ref.run_id, None)
        if native is not None and status.attempt_state == "SUCCEEDED":
            context, session_id = native
            persist_captured_session(context.store, context.resolution, session_id)
        # Failure never deletes an existing pointer and never auto-freshes.
        return status

    def _build_command(self, input_task: TaskInput) -> List[str]:
        # One-shot, non-interactive run:
        #   -p              run a single prompt and exit
        #   -s              print only the agent's final response (clean stdout)
        #   --no-ask-user    never block on an ask_user prompt
        cmd = ["copilot", "-p", input_task.prompt, "-s", "--no-ask-user"]

        session_id = input_task.metadata.get(_INTERNAL_SESSION_ID)
        if not isinstance(session_id, str) or not session_id.strip():
            context = native_session_context(self.id, input_task)
            if context is not None:
                session_id = self._session_id_for_context(context)
        if isinstance(session_id, str) and session_id.strip():
            cmd.extend(["--session-id", session_id.strip()])

        permissions = input_task.metadata.get("provider_permissions", {})
        access = permissions.get("access", "read_only") if isinstance(permissions, dict) else "read_only"
        if access == "read_only":
            cmd.extend(["--deny-tool=write", "--deny-tool=shell"])
        elif access == "write":
            cmd.extend(["--allow-tool=write", "--deny-tool=shell"])
        elif access == "yolo":
            cmd.append("--allow-all")
        else:
            raise ValueError("unsupported Copilot access: {}".format(access))
        model = input_task.metadata.get("model")
        if isinstance(model, str) and model.strip():
            cmd.extend(["--model", model.strip()])
        return cmd

    def _build_command_for_record(self) -> List[str]:
        return [
            "copilot", "-p", "<prompt>", "-s", "--no-ask-user",
            "--deny-tool=write", "--deny-tool=shell",
        ]

    def _is_success(self, return_code: int, stdout_text: str, stderr_text: str) -> bool:
        if return_code != 0:
            return False
        return len(stdout_text.strip()) > 0
