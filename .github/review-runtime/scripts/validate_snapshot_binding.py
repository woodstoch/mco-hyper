#!/usr/bin/env python3

import argparse
import json
import sys
from pathlib import Path


SNAPSHOT_FIELDS = (
    "base_sha",
    "head_sha",
    "diff_sha256",
    "packet_sha256",
)


def load_json(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{path}: unable to load JSON: {exc}") from exc


def validate_snapshot_binding(packet, result):
    if not isinstance(packet, dict):
        raise ValueError("packet: expected object")

    if not isinstance(result, dict):
        raise ValueError("result: expected object")

    snapshot = result.get("snapshot")
    if not isinstance(snapshot, dict):
        raise ValueError("result.snapshot: expected object")

    mismatches = []

    for field in SNAPSHOT_FIELDS:
        packet_value = packet.get(field)
        result_value = snapshot.get(field)

        if packet_value != result_value:
            mismatches.append(
                f"{field}: packet={packet_value!r}, result={result_value!r}"
            )

    if mismatches:
        details = "\n  ".join(mismatches)
        raise ValueError(
            "review result does not match Review Packet snapshot:\n"
            f"  {details}"
        )


def main():
    parser = argparse.ArgumentParser(
        description="Validate that a review result belongs to a Review Packet."
    )
    parser.add_argument("packet", type=Path)
    parser.add_argument("result", type=Path)
    args = parser.parse_args()

    try:
        packet = load_json(args.packet)
        result = load_json(args.result)
        validate_snapshot_binding(packet, result)
    except ValueError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1

    print(
        "PASS snapshot binding: "
        f"{args.result.name} -> {args.packet.name}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
