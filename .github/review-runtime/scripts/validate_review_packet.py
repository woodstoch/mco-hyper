#!/usr/bin/env python3

import argparse
import hashlib
import json
from pathlib import Path

from validate_fixtures import PACKET_FILES, validate_packet


BUNDLE_FILES = PACKET_FILES | {"manifest.json"}


def fail(message):
    raise ValueError(message)


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_manifest(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        fail(f"manifest.json: expected valid UTF-8 JSON: {exc}")


def validate_entries(bundle):
    entries = list(bundle.iterdir())

    for entry in entries:
        if entry.is_symlink():
            fail(f"unexpected symlink in packet: {entry.name}")
        if not entry.is_file():
            fail(f"unexpected non-file entry in packet: {entry.name}")

    names = {entry.name for entry in entries}

    missing = BUNDLE_FILES - names
    extra = names - BUNDLE_FILES

    if missing:
        fail(f"packet missing files: {sorted(missing)}")
    if extra:
        fail(f"packet contains unexpected files: {sorted(extra)}")


def require_expected(actual, expected, field):
    if expected is not None and actual != expected:
        fail(
            f"manifest.{field}: expected {expected!r}, "
            f"got {actual!r}"
        )


def validate_payload_formats(bundle):
    for name in ("pr.json", "verification.json"):
        try:
            json.loads((bundle / name).read_text(encoding="utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            fail(f"{name}: expected valid UTF-8 JSON: {exc}")

    try:
        (bundle / "context.md").read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        fail(f"context.md: expected UTF-8 text: {exc}")


def validate_bundle(args):
    bundle = args.packet

    if not bundle.is_dir():
        fail(f"packet directory does not exist: {bundle}")

    validate_entries(bundle)

    manifest = load_manifest(bundle / "manifest.json")

    # Validates manifest shape, canonical packet_sha256, and
    # diff.patch manifest binding semantics.
    validate_packet(manifest)

    for name in sorted(PACKET_FILES):
        expected_hash = manifest["files"][name]
        actual_hash = sha256_file(bundle / name)

        if actual_hash != expected_hash:
            fail(
                f"{name}: payload hash mismatch; "
                f"expected {expected_hash}, got {actual_hash}"
            )

    validate_payload_formats(bundle)

    require_expected(
        manifest["repository"],
        args.expected_repository,
        "repository",
    )
    require_expected(
        manifest["pr_number"],
        args.expected_pr_number,
        "pr_number",
    )
    require_expected(
        manifest["author"],
        args.expected_author,
        "author",
    )
    require_expected(
        manifest["base_sha"],
        args.expected_base_sha,
        "base_sha",
    )
    require_expected(
        manifest["head_sha"],
        args.expected_head_sha,
        "head_sha",
    )
    require_expected(
        manifest["packet_sha256"],
        args.expected_packet_sha256,
        "packet_sha256",
    )

    print(f"PASS packet: {bundle}")
    print(f"review_id={manifest['review_id']}")
    print(f"base_sha={manifest['base_sha']}")
    print(f"head_sha={manifest['head_sha']}")
    print(f"diff_sha256={manifest['diff_sha256']}")
    print(f"packet_sha256={manifest['packet_sha256']}")


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Validate an immutable Review Packet bundle and optionally "
            "bind it to expected runtime identity."
        )
    )

    parser.add_argument("packet", type=Path)

    parser.add_argument("--expected-repository")
    parser.add_argument("--expected-pr-number", type=int)
    parser.add_argument("--expected-author")
    parser.add_argument("--expected-base-sha")
    parser.add_argument("--expected-head-sha")
    parser.add_argument("--expected-packet-sha256")

    return parser.parse_args()


def main():
    try:
        validate_bundle(parse_args())
    except ValueError as exc:
        raise SystemExit(f"ERROR: {exc}")


if __name__ == "__main__":
    main()
