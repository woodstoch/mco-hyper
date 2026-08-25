#!/usr/bin/env python3

import hashlib
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

SHA_RE = re.compile(r"^[0-9a-f]{40,64}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
REPO_RE = re.compile(r"^[^/]+/[^/]+$")
FINDING_ID_RE = re.compile(r"^[A-Z][A-Z0-9_-]*-[0-9]{3,}$")

SEVERITIES = {
    "BLOCKING",
    "NON_BLOCKING",
    "SUGGESTION",
}

CATEGORIES = {
    "spec",
    "correctness",
    "regression",
    "testing",
    "compatibility",
    "concurrency",
    "error_handling",
    "standards",
}

PACKET_FILES = {
    "diff.patch",
    "pr.json",
    "verification.json",
    "context.md",
}


def fail(message):
    raise ValueError(message)


def load_json(path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def require_object(value, path):
    if not isinstance(value, dict):
        fail(f"{path}: expected object")


def require_exact_keys(value, required, optional, path):
    require_object(value, path)

    keys = set(value)
    missing = required - keys
    extra = keys - required - optional

    if missing:
        fail(f"{path}: missing keys: {sorted(missing)}")
    if extra:
        fail(f"{path}: unexpected keys: {sorted(extra)}")


def require_nonempty_string(value, path):
    if not isinstance(value, str) or not value:
        fail(f"{path}: expected non-empty string")


def require_regex(value, regex, path):
    require_nonempty_string(value, path)
    if not regex.fullmatch(value):
        fail(f"{path}: invalid value: {value!r}")


def validate_packet(packet):
    required = {
        "schema_version",
        "review_id",
        "repository",
        "pr_number",
        "author",
        "base_sha",
        "head_sha",
        "diff_sha256",
        "files",
        "packet_sha256",
    }

    require_exact_keys(packet, required, set(), "packet")

    if packet["schema_version"] != "1":
        fail("packet.schema_version: expected '1'")

    require_nonempty_string(packet["review_id"], "packet.review_id")
    require_regex(packet["repository"], REPO_RE, "packet.repository")
    require_nonempty_string(packet["author"], "packet.author")

    if not isinstance(packet["pr_number"], int) or isinstance(packet["pr_number"], bool):
        fail("packet.pr_number: expected integer")
    if packet["pr_number"] < 1:
        fail("packet.pr_number: must be >= 1")

    require_regex(packet["base_sha"], SHA_RE, "packet.base_sha")
    require_regex(packet["head_sha"], SHA_RE, "packet.head_sha")
    require_regex(packet["diff_sha256"], SHA256_RE, "packet.diff_sha256")

    files = packet["files"]
    require_exact_keys(files, PACKET_FILES, set(), "packet.files")

    for name in sorted(PACKET_FILES):
        require_regex(
            files[name],
            SHA256_RE,
            f"packet.files[{name!r}]",
        )

    if files["diff.patch"] != packet["diff_sha256"]:
        fail(
            "packet.files['diff.patch']: must equal packet.diff_sha256"
        )

    canonical_packet = dict(packet)
    canonical_packet.pop("packet_sha256")
    canonical_bytes = json.dumps(
        canonical_packet,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    expected_packet_sha256 = hashlib.sha256(canonical_bytes).hexdigest()

    require_regex(
        packet["packet_sha256"],
        SHA256_RE,
        "packet.packet_sha256",
    )

    if packet["packet_sha256"] != expected_packet_sha256:
        fail(
            "packet.packet_sha256: canonical manifest hash mismatch; "
            f"expected {expected_packet_sha256}"
        )


def validate_finding(finding, index):
    path = f"result.findings[{index}]"

    required = {
        "id",
        "severity",
        "category",
        "claim",
        "evidence",
    }

    optional = {
        "file",
        "line",
        "validation_hint",
        "contract_refs",
    }

    require_exact_keys(finding, required, optional, path)

    require_regex(finding["id"], FINDING_ID_RE, f"{path}.id")

    if finding["severity"] not in SEVERITIES:
        fail(f"{path}.severity: invalid severity")

    if finding["category"] not in CATEGORIES:
        fail(f"{path}.category: invalid category")

    require_nonempty_string(finding["claim"], f"{path}.claim")
    require_nonempty_string(finding["evidence"], f"{path}.evidence")

    if "file" in finding:
        require_nonempty_string(finding["file"], f"{path}.file")

    if "line" in finding:
        if not isinstance(finding["line"], int) or isinstance(finding["line"], bool):
            fail(f"{path}.line: expected integer")
        if finding["line"] < 1:
            fail(f"{path}.line: must be >= 1")

    if "validation_hint" in finding:
        require_nonempty_string(
            finding["validation_hint"],
            f"{path}.validation_hint",
        )

    if "contract_refs" in finding:
        refs = finding["contract_refs"]
        if not isinstance(refs, list):
            fail(f"{path}.contract_refs: expected array")

        if len(refs) != len(set(refs)):
            fail(f"{path}.contract_refs: duplicate values")

        for ref_index, ref in enumerate(refs):
            require_nonempty_string(
                ref,
                f"{path}.contract_refs[{ref_index}]",
            )


def validate_result(result):
    required = {
        "schema_version",
        "reviewer",
        "snapshot",
        "findings",
    }

    require_exact_keys(result, required, set(), "result")

    if result["schema_version"] != "1":
        fail("result.schema_version: expected '1'")

    require_nonempty_string(result["reviewer"], "result.reviewer")

    snapshot = result["snapshot"]

    snapshot_required = {
        "base_sha",
        "head_sha",
        "diff_sha256",
        "packet_sha256",
    }

    require_exact_keys(
        snapshot,
        snapshot_required,
        set(),
        "result.snapshot",
    )

    require_regex(
        snapshot["base_sha"],
        SHA_RE,
        "result.snapshot.base_sha",
    )
    require_regex(
        snapshot["head_sha"],
        SHA_RE,
        "result.snapshot.head_sha",
    )
    require_regex(
        snapshot["diff_sha256"],
        SHA256_RE,
        "result.snapshot.diff_sha256",
    )
    require_regex(
        snapshot["packet_sha256"],
        SHA256_RE,
        "result.snapshot.packet_sha256",
    )

    findings = result["findings"]

    if not isinstance(findings, list):
        fail("result.findings: expected array")

    ids = set()

    for index, finding in enumerate(findings):
        validate_finding(finding, index)

        finding_id = finding["id"]
        if finding_id in ids:
            fail(f"result.findings: duplicate finding id {finding_id}")
        ids.add(finding_id)


def main():
    # Syntax-check the published JSON Schemas as well.
    schema_paths = [
        ROOT / "schemas/review-packet.schema.json",
        ROOT / "schemas/review-result.schema.json",
    ]

    for path in schema_paths:
        load_json(path)
        print(f"PASS syntax: {path.name}")

    packet = load_json(
        ROOT / "fixtures/review-packet.example.json"
    )
    result = load_json(
        ROOT / "fixtures/review-result.example.json"
    )

    validate_packet(packet)
    print("PASS contract: review-packet.example.json")

    validate_result(result)
    print("PASS contract: review-result.example.json")

    print("Review runtime fixtures: PASS")


if __name__ == "__main__":
    main()
