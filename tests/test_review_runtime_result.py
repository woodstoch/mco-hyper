import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / ".github/review-runtime/scripts"
FIXTURES = SCRIPTS.parent / "fixtures"
sys.path.insert(0, str(SCRIPTS))

from validate_fixtures import validate_result  # noqa: E402
from validate_review_result import load_json  # noqa: E402
from validate_snapshot_binding import validate_snapshot_binding  # noqa: E402


def load_fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class ReviewResultValidationTests(unittest.TestCase):
    def setUp(self):
        self.packet = load_fixture("review-packet.example.json")
        self.result = load_fixture("review-result.example.json")

    def test_rejects_wrong_head_sha(self):
        result = copy.deepcopy(self.result)
        result["snapshot"]["head_sha"] = "3" * 40

        with self.assertRaisesRegex(ValueError, "head_sha"):
            validate_snapshot_binding(self.packet, result)

    def test_rejects_wrong_packet_sha256(self):
        result = copy.deepcopy(self.result)
        result["snapshot"]["packet_sha256"] = "f" * 64

        with self.assertRaisesRegex(ValueError, "packet_sha256"):
            validate_snapshot_binding(self.packet, result)

    def test_rejects_wrong_diff_sha256(self):
        result = copy.deepcopy(self.result)
        result["snapshot"]["diff_sha256"] = "f" * 64

        with self.assertRaisesRegex(ValueError, "diff_sha256"):
            validate_snapshot_binding(self.packet, result)

    def test_rejects_duplicate_finding_id(self):
        result = copy.deepcopy(self.result)
        result["findings"][1]["id"] = result["findings"][0]["id"]

        with self.assertRaisesRegex(ValueError, "duplicate finding id"):
            validate_result(result)

    def test_rejects_invalid_severity(self):
        result = copy.deepcopy(self.result)
        result["findings"][0]["severity"] = "UNKNOWN"

        with self.assertRaisesRegex(ValueError, "invalid severity"):
            validate_result(result)

    def test_rejects_invalid_category(self):
        result = copy.deepcopy(self.result)
        result["findings"][0]["category"] = "security"

        with self.assertRaisesRegex(ValueError, "invalid category"):
            validate_result(result)

    def test_rejects_missing_evidence(self):
        result = copy.deepcopy(self.result)
        del result["findings"][0]["evidence"]

        with self.assertRaisesRegex(ValueError, "missing keys"):
            validate_result(result)

    def test_rejects_malformed_json(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "result.json"
            path.write_text("{", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "valid UTF-8 JSON"):
                load_json(path)


if __name__ == "__main__":
    unittest.main()
