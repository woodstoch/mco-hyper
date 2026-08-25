#!/usr/bin/env python3

import argparse
import hashlib
import json
import os
import re
import shutil
import tempfile
from pathlib import Path


SHA_RE = re.compile(r"^[0-9a-f]{40,64}$")
REPO_RE = re.compile(r"^[^/]+/[^/]+$")

PAYLOADS = {
    "diff.patch": "diff",
    "pr.json": "pr_json",
    "verification.json": "verification_json",
    "context.md": "context",
}


def fail(message):
    raise ValueError(message)


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def canonical_manifest_bytes(manifest):
    canonical = dict(manifest)
    canonical.pop("packet_sha256", None)
    return json.dumps(
        canonical,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def validate_identity(args):
    if not args.review_id:
        fail("review_id must be non-empty")

    if not REPO_RE.fullmatch(args.repository):
        fail("repository must be in owner/name form")

    if args.pr_number < 1:
        fail("pr_number must be >= 1")

    if not args.author:
        fail("author must be non-empty")

    if not SHA_RE.fullmatch(args.base_sha):
        fail("base_sha must be 40-64 lowercase hexadecimal characters")

    if not SHA_RE.fullmatch(args.head_sha):
        fail("head_sha must be 40-64 lowercase hexadecimal characters")


def load_payload(path, logical_name):
    if not path.is_file():
        fail(f"{logical_name}: input file does not exist: {path}")

    data = path.read_bytes()

    if logical_name in {"pr.json", "verification.json"}:
        try:
            json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            fail(f"{logical_name}: expected valid UTF-8 JSON: {exc}")

    if logical_name == "context.md":
        try:
            data.decode("utf-8")
        except UnicodeDecodeError as exc:
            fail(f"context.md: expected UTF-8 text: {exc}")

    return data


def build_packet(args):
    validate_identity(args)

    output = args.output
    if os.path.lexists(output):
        fail(f"output path already exists: {output}")

    payload_data = {}
    for logical_name, arg_name in PAYLOADS.items():
        source = getattr(args, arg_name)
        payload_data[logical_name] = load_payload(
            source,
            logical_name,
        )

    output.parent.mkdir(parents=True, exist_ok=True)

    staging = Path(
        tempfile.mkdtemp(
            prefix=f".{output.name}.tmp-",
            dir=output.parent,
        )
    )

    try:
        file_hashes = {}
        for logical_name in PAYLOADS:
            data = payload_data[logical_name]
            destination = staging / logical_name
            destination.write_bytes(data)
            file_hashes[logical_name] = sha256_bytes(data)

        manifest = {
            "schema_version": "1",
            "review_id": args.review_id,
            "repository": args.repository,
            "pr_number": args.pr_number,
            "author": args.author,
            "base_sha": args.base_sha,
            "head_sha": args.head_sha,
            "diff_sha256": file_hashes["diff.patch"],
            "files": file_hashes,
        }

        manifest["packet_sha256"] = sha256_bytes(
            canonical_manifest_bytes(manifest)
        )

        manifest_path = staging / "manifest.json"
        manifest_path.write_text(
            json.dumps(
                manifest,
                indent=2,
                sort_keys=True,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )

        # Re-read written payloads so publication only occurs after
        # the staged bundle matches the generated manifest.
        for logical_name, expected_hash in file_hashes.items():
            actual_hash = sha256_bytes(
                (staging / logical_name).read_bytes()
            )
            if actual_hash != expected_hash:
                fail(
                    f"{logical_name}: written payload hash mismatch; "
                    f"expected {expected_hash}, got {actual_hash}"
                )

        if os.path.lexists(output):
            fail(f"output path already exists: {output}")

        staging.rename(output)

    finally:
        if staging.exists():
            shutil.rmtree(staging)

    print(f"PASS build: {output}")
    print(f"diff_sha256={manifest['diff_sha256']}")
    print(f"packet_sha256={manifest['packet_sha256']}")


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Build an immutable deterministic Review Packet bundle "
            "from pre-materialized payload files."
        )
    )

    parser.add_argument("--review-id", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--pr-number", type=int, required=True)
    parser.add_argument("--author", required=True)
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--head-sha", required=True)

    parser.add_argument(
        "--diff",
        type=Path,
        required=True,
        help="Source diff.patch payload.",
    )
    parser.add_argument(
        "--pr-json",
        type=Path,
        required=True,
        help="Source pr.json payload.",
    )
    parser.add_argument(
        "--verification-json",
        type=Path,
        required=True,
        help="Source verification.json payload.",
    )
    parser.add_argument(
        "--context",
        type=Path,
        required=True,
        help="Source context.md payload.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="New directory to create as the Review Packet bundle.",
    )

    return parser.parse_args()


def main():
    try:
        build_packet(parse_args())
    except ValueError as exc:
        raise SystemExit(f"ERROR: {exc}")


if __name__ == "__main__":
    main()
