from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from runtime import cli as upstream_cli
from runtime.adapters.agy import AgyAdapter, _capture_conversation_id, decode_agy_result
from runtime.contracts import TaskInput
from runtime.execution_modes import execution_permissions
from runtime.hyper_cli import _enable_hyper_providers
from runtime.session.manager import _daemon_env
from runtime.session.native import NativeSessionKey, NativeSessionStore, execution_profile_fingerprint
from runtime.session.state import HistoryEntry, SessionState, build_history_prompt, save_state


class AgyTransportTests(unittest.TestCase):
    def test_json_result_preserves_answer_and_usage(self) -> None:
        raw = (
            '{"conversation_id":"conv-123","status":"SUCCESS","response":"done\\n",'
            '"usage":{"input_tokens":10,"output_tokens":4,"thinking_tokens":2,'
            '"cache_read_tokens":7,"total_tokens":14}}'
        )
        transport = decode_agy_result(raw)
        self.assertEqual(transport.status, "succeeded")
        self.assertEqual(transport.final_answer, "done\n")
        self.assertEqual(transport.usage, {
            "prompt_tokens": 10,
            "completion_tokens": 4,
            "thinking_tokens": 2,
            "cache_read_tokens": 7,
            "total_tokens": 14,
        })
        self.assertEqual(_capture_conversation_id(raw), "conv-123")

    def test_error_result_is_not_reported_as_success(self) -> None:
        raw = '{"conversation_id":"","status":"ERROR","response":"","error":"bad model"}'
        self.assertEqual(decode_agy_result(raw).status, "failed")


class AgyCommandTests(unittest.TestCase):
    def _task(self, root: str, **metadata: object) -> TaskInput:
        base = {
            "native_session_scope": "issue-42",
            "native_session_mode": "reuse",
        }
        base.update(metadata)
        return TaskInput(
            task_id="agy-test",
            prompt="Inspect the repository",
            repo_root=root,
            target_paths=["."],
            timeout_seconds=90,
            metadata=base,
        )

    def test_first_turn_uses_structured_json_without_global_continue(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cmd = AgyAdapter()._build_command(self._task(tmp))
            self.assertEqual(cmd[:3], ["agy", "-p", "Inspect the repository"])
            self.assertIn("--output-format", cmd)
            self.assertIn("json", cmd)
            self.assertNotIn("--continue", cmd)
            self.assertNotIn("-c", cmd)
            self.assertNotIn("--conversation", cmd)

    def test_reuse_resumes_exact_conversation_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            task = self._task(tmp)
            key = NativeSessionKey(
                tmp,
                "issue-42",
                "agy",
                execution_profile_fingerprint("agy", task.metadata),
            )
            NativeSessionStore(tmp).put(key, "conv-123")
            cmd = AgyAdapter()._build_command(task)
            index = cmd.index("--conversation")
            self.assertEqual(cmd[index:index + 2], ["--conversation", "conv-123"])
            self.assertNotIn("--continue", cmd)
            self.assertNotIn("-c", cmd)

    def test_model_effort_and_yolo_map_to_native_flags(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            task = self._task(
                tmp,
                model="gemini-test",
                provider_context={"effort": "high"},
                provider_permissions={"dangerously_skip_permissions": "true"},
            )
            cmd = AgyAdapter()._build_command(task)
            self.assertIn("--model", cmd)
            self.assertEqual(cmd[cmd.index("--model") + 1], "gemini-test")
            self.assertIn("--effort", cmd)
            self.assertEqual(cmd[cmd.index("--effort") + 1], "high")
            self.assertIn("--dangerously-skip-permissions", cmd)
            self.assertNotIn("--sandbox", cmd)

    def test_invalid_effort_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "unsupported AGY effort"):
                AgyAdapter()._build_command(self._task(tmp, provider_context={"effort": "xhigh"}))

    def test_unified_permissions_fail_closed_except_explicit_yolo(self) -> None:
        self.assertIsNone(execution_permissions("agy", "read_only"))
        self.assertIsNone(execution_permissions("agy", "write"))
        self.assertEqual(
            execution_permissions("agy", "yolo"),
            {"dangerously_skip_permissions": "true"},
        )


class NativeDaemonContinuityTests(unittest.TestCase):
    def test_native_daemon_uses_session_name_as_scope(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            save_state(tmp, SessionState(name="ble-gatt", provider="codex", repo_root=tmp))
            env = _daemon_env(tmp, "ble-gatt")
            self.assertEqual(env["MCO_HYPER_SCOPE"], "ble-gatt")
            self.assertEqual(env["MCO_HYPER_SESSION_MODE"], "reuse")
            self.assertEqual(env["MCO_HYPER_NATIVE_PROVIDER"], "codex")
            self.assertEqual(env["MCO_HYPER_NATIVE_SESSION_ACTIVE"], "1")

    def test_non_native_daemon_does_not_inherit_hyper_scope(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            save_state(tmp, SessionState(name="legacy", provider="claude", repo_root=tmp))
            with patch.dict(os.environ, {"MCO_HYPER_SCOPE": "leaked", "MCO_HYPER_SESSION_MODE": "reuse"}):
                env = _daemon_env(tmp, "legacy")
            self.assertNotIn("MCO_HYPER_SCOPE", env)
            self.assertNotIn("MCO_HYPER_SESSION_MODE", env)
            self.assertNotIn("MCO_HYPER_NATIVE_SESSION_ACTIVE", env)

    def test_synthetic_history_is_fallback_until_native_pointer_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = {
                "MCO_HYPER_NATIVE_SESSION_ACTIVE": "1",
                "MCO_HYPER_NATIVE_PROVIDER": "codex",
                "MCO_HYPER_NATIVE_REPO_ROOT": tmp,
                "MCO_HYPER_SCOPE": "issue-42",
            }
            history = [
                HistoryEntry(role="user", content="first"),
                HistoryEntry(role="assistant", content="answer"),
            ]
            with patch.dict(os.environ, env, clear=False):
                fallback = build_history_prompt(history, "second")
                self.assertIn("## Conversation History", fallback)

                key = NativeSessionKey(
                    tmp,
                    "issue-42",
                    "codex",
                    execution_profile_fingerprint("codex", {}),
                )
                NativeSessionStore(tmp).put(key, "thread-123")
                self.assertEqual(build_history_prompt(history, "second"), "second")


class HyperProviderRegistrationTests(unittest.TestCase):
    def test_hyper_cli_registers_agy_without_removing_upstream_providers(self) -> None:
        original = upstream_cli.SUPPORTED_PROVIDERS
        original_list = upstream_cli.SUPPORTED_PROVIDER_LIST
        original_doctor = upstream_cli.DEFAULT_DOCTOR_PROVIDERS
        try:
            _enable_hyper_providers()
            self.assertIn("agy", upstream_cli.SUPPORTED_PROVIDERS)
            for provider in original:
                self.assertIn(provider, upstream_cli.SUPPORTED_PROVIDERS)
        finally:
            upstream_cli.SUPPORTED_PROVIDERS = original
            upstream_cli.SUPPORTED_PROVIDER_LIST = original_list
            upstream_cli.DEFAULT_DOCTOR_PROVIDERS = original_doctor


if __name__ == "__main__":
    unittest.main()
