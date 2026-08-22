from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from runtime.session.native import (
    NativeSessionKey,
    NativeSessionStore,
    execution_profile_fingerprint,
    persist_captured_session,
    resolve_native_session,
)


class NativeSessionIdentityTests(unittest.TestCase):
    def test_same_scope_and_profile_have_same_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fingerprint = execution_profile_fingerprint("codex", {"model": "gpt-test"})
            left = NativeSessionKey(tmp, "issue-42", "codex", fingerprint)
            right = NativeSessionKey(tmp, "issue-42", "codex", fingerprint)
            self.assertEqual(left.stable_id, right.stable_id)

    def test_scope_and_profile_changes_isolate_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            profile_a = execution_profile_fingerprint("codex", {"model": "model-a"})
            profile_b = execution_profile_fingerprint("codex", {"model": "model-b"})
            base = NativeSessionKey(tmp, "ble-gatt", "codex", profile_a)
            other_scope = NativeSessionKey(tmp, "gcp-auth", "codex", profile_a)
            other_profile = NativeSessionKey(tmp, "ble-gatt", "codex", profile_b)
            self.assertNotEqual(base.stable_id, other_scope.stable_id)
            self.assertNotEqual(base.stable_id, other_profile.stable_id)

    def test_profile_fingerprint_ignores_prompt_and_artifact_metadata(self) -> None:
        first = execution_profile_fingerprint(
            "codex",
            {
                "model": "model-a",
                "provider_permissions": {"sandbox": "read-only"},
                "prompt": "first",
                "artifact_root": "/tmp/one",
            },
        )
        second = execution_profile_fingerprint(
            "codex",
            {
                "model": "model-a",
                "provider_permissions": {"sandbox": "read-only"},
                "prompt": "second",
                "artifact_root": "/tmp/two",
            },
        )
        self.assertEqual(first, second)

    def test_reuse_requires_explicit_scope(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "non-empty scope"):
                NativeSessionKey(tmp, "", "codex", "abc")


class NativeSessionStoreTests(unittest.TestCase):
    def _key(self, root: str) -> NativeSessionKey:
        return NativeSessionKey(root, "issue-42", "codex", "profile-a")

    def test_round_trip_and_reuse_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            key = self._key(tmp)
            store = NativeSessionStore(tmp)
            initial = resolve_native_session(mode="reuse", store=store, key=key)
            self.assertIsNone(initial.native_session_id)
            self.assertTrue(initial.should_persist)

            persist_captured_session(store, initial, "thread-123")
            resumed = resolve_native_session(mode="reuse", store=store, key=key)
            self.assertEqual(resumed.native_session_id, "thread-123")

            raw = json.loads((Path(tmp) / ".mco/native-sessions.json").read_text(encoding="utf-8"))
            self.assertEqual(raw["version"], 1)
            self.assertEqual(raw["sessions"][key.stable_id]["session_type"], "native")

    def test_fresh_does_not_read_or_overwrite_reusable_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            key = self._key(tmp)
            store = NativeSessionStore(tmp)
            store.put(key, "canonical-thread")

            fresh = resolve_native_session(mode="fresh", store=store, key=key)
            self.assertIsNone(fresh.native_session_id)
            self.assertFalse(fresh.should_persist)
            self.assertIsNone(persist_captured_session(store, fresh, "fresh-thread"))
            self.assertEqual(store.get(key).native_session_id, "canonical-thread")  # type: ignore[union-attr]

    def test_explicit_uses_exact_id_without_replacing_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            key = self._key(tmp)
            store = NativeSessionStore(tmp)
            store.put(key, "canonical-thread")

            explicit = resolve_native_session(
                mode="explicit",
                store=store,
                key=key,
                explicit_id="requested-thread",
            )
            self.assertEqual(explicit.native_session_id, "requested-thread")
            self.assertFalse(explicit.should_persist)
            persist_captured_session(store, explicit, "requested-thread")
            self.assertEqual(store.get(key).native_session_id, "canonical-thread")  # type: ignore[union-attr]

    def test_explicit_requires_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            key = self._key(tmp)
            store = NativeSessionStore(tmp)
            with self.assertRaisesRegex(ValueError, "requires a native session id"):
                resolve_native_session(mode="explicit", store=store, key=key)

    def test_delete_is_scoped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            key_a = self._key(tmp)
            key_b = NativeSessionKey(tmp, "other-topic", "codex", "profile-a")
            store = NativeSessionStore(tmp)
            store.put(key_a, "a")
            store.put(key_b, "b")
            self.assertTrue(store.delete(key_a))
            self.assertIsNone(store.get(key_a))
            self.assertEqual(store.get(key_b).native_session_id, "b")  # type: ignore[union-attr]


if __name__ == "__main__":
    unittest.main()
