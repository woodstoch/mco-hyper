import sys
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / ".github/review-runtime/scripts"
sys.path.insert(0, str(SCRIPTS))

import prepare_review_packet  # noqa: E402


BASE_SHA = "1" * 40
HEAD_SHA = "2" * 40
MERGE_BASE_SHA = "3" * 40
REPOSITORY = "woodstoch/mco-hyper"


def pull_request(**overrides):
    value = {
        "number": 3,
        "state": "open",
        "user": {"login": "woodstoch"},
        "base": {"ref": "main", "sha": BASE_SHA},
        "head": {
            "ref": "feature",
            "sha": HEAD_SHA,
            "repo": {"full_name": REPOSITORY},
        },
        "draft": False,
        "title": "A reviewable change",
        "body": "Intent",
        "changed_files": 0,
    }
    value.update(overrides)
    return value


def compare(files):
    return {
        "status": "ahead",
        "base_commit": {"sha": BASE_SHA},
        "merge_base_commit": {"sha": MERGE_BASE_SHA},
        "files": files,
    }


def changed_file(filename):
    return {
        "filename": filename,
        "status": "modified",
        "additions": 1,
        "deletions": 0,
        "changes": 1,
    }


class PrepareReviewPacketTests(unittest.TestCase):
    def test_rejects_untrusted_author(self):
        metadata = pull_request(user={"login": "someone-else"})

        with self.assertRaisesRegex(ValueError, "author"):
            prepare_review_packet.sanitize_pr(
                metadata,
                REPOSITORY,
                3,
                "woodstoch",
            )

    def test_rejects_closed_pull_request(self):
        metadata = pull_request(state="closed")

        with self.assertRaisesRegex(ValueError, "must be open"):
            prepare_review_packet.sanitize_pr(
                metadata,
                REPOSITORY,
                3,
                "woodstoch",
            )

    def test_rejects_wrong_pull_request_number(self):
        metadata = pull_request(number=4)

        with self.assertRaisesRegex(ValueError, "number mismatch"):
            prepare_review_packet.sanitize_pr(
                metadata,
                REPOSITORY,
                3,
                "woodstoch",
            )

    def test_rejects_cross_repository_head(self):
        metadata = pull_request(
            head={
                "ref": "feature",
                "sha": HEAD_SHA,
                "repo": {"full_name": "someone-else/mco-hyper"},
            }
        )

        with self.assertRaisesRegex(ValueError, "head repository"):
            prepare_review_packet.sanitize_pr(
                metadata,
                REPOSITORY,
                3,
                "woodstoch",
            )

    def test_rejects_compare_file_limit(self):
        files = [changed_file(f"file-{index}.txt") for index in range(300)]

        with self.assertRaisesRegex(ValueError, "file limit"):
            prepare_review_packet.validate_compare(
                compare(files),
                pull_request(changed_files=300),
                BASE_SHA,
            )

    def test_rejects_compare_count_mismatch(self):
        with self.assertRaisesRegex(ValueError, "file count mismatch"):
            prepare_review_packet.validate_compare(
                compare([changed_file("one.txt")]),
                pull_request(changed_files=2),
                BASE_SHA,
            )

    def test_rejects_snapshot_drift(self):
        metadata = pull_request(
            head={
                "ref": "feature",
                "sha": "4" * 40,
                "repo": {"full_name": REPOSITORY},
            }
        )

        with self.assertRaisesRegex(ValueError, "head SHA changed"):
            prepare_review_packet.validate_snapshot(
                metadata,
                REPOSITORY,
                3,
                "woodstoch",
                BASE_SHA,
                HEAD_SHA,
            )

    def test_rejects_base_snapshot_drift(self):
        metadata = pull_request(
            base={"ref": "main", "sha": "4" * 40},
        )

        with self.assertRaisesRegex(ValueError, "base SHA changed"):
            prepare_review_packet.validate_snapshot(
                metadata,
                REPOSITORY,
                3,
                "woodstoch",
                BASE_SHA,
                HEAD_SHA,
            )

    def test_accepts_stable_snapshot(self):
        metadata = pull_request()

        result = prepare_review_packet.validate_snapshot(
            metadata,
            REPOSITORY,
            3,
            "woodstoch",
            BASE_SHA,
            HEAD_SHA,
        )

        self.assertEqual(result["head_sha"], HEAD_SHA)


if __name__ == "__main__":
    unittest.main()
