from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from runtime.adapters.codex import CodexAdapter, _capture_thread_id
from runtime.adapters.copilot import CopilotAdapter
from runtime.contracts import TaskInput
from runtime.hyper_cli import extract_hyper_session_args
from runtime.session.native import NativeSessionKey, NativeSessionStore, execution_profile_fingerprint
from runtime.session.provider_native import native_session_context


class HyperCliSessionArgsTests(unittest.TestCase):
    def test_scope_defaults_to_reuse_and_is_removed_before_upstream_parser(self) -> None:
        filtered, env = extract_hyper_session_args([
            "run", "--scope", "ble-gatt", "--providers", "codex", "--prompt", "inspect",
        ])
        self.assertEqual(filtered, ["run", "--providers", "codex", "--prompt", "inspect"])
        self.assertEqual(env["MCO_HYPER_SCOPE"], "ble-gatt")
        self.assertEqual(env["MCO_HYPER_SESSION_MODE"], "reuse")

    def test_explicit_requires_scope_and_id(self) -> None:
        with self.assertRaisesRegex(ValueError, "requires --scope"):
            extract_hyper_session_args(["review", "--session-mode", "explicit", "--session-id", "abc"])
        with self.assertRaisesRegex(ValueError, "requires --session-id"):
            extract_hyper_session_args(["review", "--scope", "pr-1", "--session-mode", "explicit"])

    def test_fresh_can_be_independent_without_scope(self) -> None:
        filtered, env = extract_hyper_session_args(["run", "--session-mode=fresh", "--prompt", "second opinion"])
        self.assertEqual(filtered, ["run", "--prompt", "second opinion"])
        self.assertEqual(env["MCO_HYPER_SESSION_MODE"], "fresh")


class NativeProviderCommandTests(unittest.TestCase):
    def _task(self, root: str, provider: str, scope: str = "issue-42", mode: str = "reuse") -> TaskInput:
        return TaskInput(
            task_id="task-1",
            prompt="Inspect this repository",
            repo_root=root,
            target_paths=["."],
            metadata={
                "artifact_root": str(Path(root) / "artifacts"),
                "provider_permissions": {"access": "read_only"} if provider == "copilot" else {"sandbox": "read-only"},
                "native_session_scope": scope,
                "native_session_mode": mode,
            },
        )

    def test_codex_capture_uses_top_level_thread_started(self) -> None:
        raw = "\n".join([
            '{"type":"thread.started","thread_id":"thread-123"}',
            '{"type":"item.completed","item":{"type":"agent_message","text":"done"}}',
        ])
        self.assertEqual(_capture_thread_id(raw), "thread-123")

    def test_codex_reuse_builds_exact_resume_after_pointer_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            task = self._task(tmp, "codex")
            adapter = CodexAdapter()
            first = adapter._build_command(task)
            self.assertNotIn("resume", first)

            context = native_session_context("codex", task)
            self.assertIsNotNone(context)
            assert context is not None and context.resolution.key is not None
            context.store.put(context.resolution.key, "thread-123")

            resumed = adapter._build_command(task)
            resume_index = resumed.index("resume")
            self.assertEqual(resumed[resume_index:resume_index + 3], ["resume", "thread-123", task.prompt])

    def test_copilot_same_scope_uses_same_deterministic_session_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            adapter = CopilotAdapter()
            first_task = self._task(tmp, "copilot")
            second_task = self._task(tmp, "copilot")
            first = adapter._build_command(first_task)
            second = adapter._build_command(second_task)
            first_id = first[first.index("--session-id") + 1]
            second_id = second[second.index("--session-id") + 1]
            self.assertEqual(first_id, second_id)

    def test_copilot_different_scope_uses_different_session_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            adapter = CopilotAdapter()
            first = adapter._build_command(self._task(tmp, "copilot", scope="ble-gatt"))
            second = adapter._build_command(self._task(tmp, "copilot", scope="gcp-auth"))
            self.assertNotEqual(
                first[first.index("--session-id") + 1],
                second[second.index("--session-id") + 1],
            )

    def test_model_change_changes_copilot_session_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            adapter = CopilotAdapter()
            first_task = self._task(tmp, "copilot")
            first_task.metadata["model"] = "model-a"
            second_task = self._task(tmp, "copilot")
            second_task.metadata["model"] = "model-b"
            first = adapter._build_command(first_task)
            second = adapter._build_command(second_task)
            self.assertNotEqual(
                first[first.index("--session-id") + 1],
                second[second.index("--session-id") + 1],
            )

    def test_upstream_command_is_unchanged_without_hyper_session_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            codex = CodexAdapter()._build_command(TaskInput(
                task_id="plain",
                prompt="hello",
                repo_root=tmp,
                target_paths=["."],
                metadata={},
            ))
            copilot = CopilotAdapter()._build_command(TaskInput(
                task_id="plain",
                prompt="hello",
                repo_root=tmp,
                target_paths=["."],
                metadata={"provider_permissions": {"access": "read_only"}},
            ))
            self.assertNotIn("resume", codex)
            self.assertNotIn("--session-id", copilot)


if __name__ == "__main__":
    unittest.main()
