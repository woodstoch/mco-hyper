#!/usr/bin/env python3

import argparse
import json
from pathlib import Path
from types import SimpleNamespace

from validate_fixtures import validate_result
from validate_review_packet import load_manifest, validate_bundle
from validate_snapshot_binding import validate_snapshot_binding


def fail(message):
    raise ValueError(message)


def load_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        fail(f"{path}: expected valid UTF-8 JSON: {exc}")


def validate_packet(packet, args):
    validate_bundle(
        SimpleNamespace(
            packet=packet,
            expected_review_id=args.expected_review_id,
            expected_repository=args.expected_repository,
            expected_pr_number=args.expected_pr_number,
            expected_author=args.expected_author,
            expected_base_sha=args.expected_base_sha,
            expected_head_sha=args.expected_head_sha,
            expected_diff_sha256=args.expected_diff_sha256,
            expected_packet_sha256=args.expected_packet_sha256,
        )
    )
    return load_manifest(packet / "manifest.json")


def validate(args):
    packet = args.packet
    result = args.result
    manifest = validate_packet(packet, args)
    result_value = load_json(result)

    validate_result(result_value)
    if args.expected_reviewer is not None and result_value["reviewer"] != args.expected_reviewer:
        fail(
            f"result.reviewer: expected {args.expected_reviewer!r}, "
            f"got {result_value['reviewer']!r}"
        )

    validate_snapshot_binding(manifest, result_value)

    print(f"PASS result: {result}")
    print(f"reviewer={result_value['reviewer']}")
    print(f"findings={len(result_value['findings'])}")
    print(f"review_id={manifest['review_id']}")
    print(f"packet_sha256={manifest['packet_sha256']}")


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Validate a structured review result against an immutable "
            "Review Packet and runtime identity."
        )
    )
    parser.add_argument("packet", type=Path)
    parser.add_argument("result", type=Path)
    parser.add_argument("--expected-review-id")
    parser.add_argument("--expected-repository")
    parser.add_argument("--expected-pr-number", type=int)
    parser.add_argument("--expected-author")
    parser.add_argument("--expected-base-sha")
    parser.add_argument("--expected-head-sha")
    parser.add_argument("--expected-diff-sha256")
    parser.add_argument("--expected-packet-sha256")
    parser.add_argument("--expected-reviewer")
    return parser.parse_args()


def main():
    try:
        validate(parse_args())
    except ValueError as exc:
        raise SystemExit(f"ERROR: {exc}")


if __name__ == "__main__":
    main()
