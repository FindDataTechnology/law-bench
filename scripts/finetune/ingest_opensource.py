#!/usr/bin/env python3
"""Open-source corpus intake with license gate (design D6).

For each candidate corpus directory, reads its ``LICENSE`` file and
string-matches against the allowlist ``{Apache-2.0, MIT}``. Accepted corpora
are indexed into ``data/finetune/opensource/`` with tier/source/license tags.
Rejected corpora (AGPL/GPL/commercial/missing) are logged to
``data/finetune/manifests/rejected_sources.jsonl`` with the rejection reason.

Usage::

    python scripts/finetune/ingest_opensource.py <corpus_dir> [--tier silver] [--dry-run]

``<corpus_dir>`` is one corpus root (must contain a ``LICENSE`` file). To
ingest several, run once per corpus. Idempotent: re-running over the same
corpus rewrites its index deterministically and appends nothing new to the
rejection log if the outcome is unchanged.
"""
from __future__ import annotations

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from common import (  # noqa: E402
    LICENSE_ALLOWLIST,
    OPENSOURCE_DIR,
    REJECTED_SOURCES,
    check_license,
    dumps_record,
    read_jsonl,
    write_jsonl,
)


def _read_license(corpus_root: pathlib.Path) -> str | None:
    """Read the LICENSE file content from a corpus root, trying common names."""
    for name in ("LICENSE", "LICENSE.md", "LICENSE.txt", "COPYING"):
        candidate = corpus_root / name
        if candidate.exists():
            try:
                return candidate.read_text(encoding="utf-8")
            except OSError:
                return None
    return None


def _index_corpus(corpus_root: pathlib.Path, license_id: str, tier: str) -> dict:
    """Build a deterministic index record for an accepted corpus."""
    files: list[str] = []
    for p in sorted(corpus_root.rglob("*")):
        if p.is_file() and p.name.upper() not in ("LICENSE", "LICENSE.MD", "LICENSE.TXT", "COPYING"):
            files.append(str(p.relative_to(corpus_root)))
    return {
        "corpus": corpus_root.name,
        "source": corpus_root.name,
        "license": license_id,
        "tier": tier,
        "provenance": f"{corpus_root.name}:local",
        "file_count": len(files),
        "files": files[:50],  # cap for readability; full list regenerable
    }


def _record_rejection(corpus_name: str, license_text: str | None, reason: str) -> dict:
    return {
        "dataset": "opensource",
        "source": corpus_name,
        "license": None,
        "tier": None,
        "provenance": f"{corpus_name}:rejected",
        "reason": reason,
    }


def ingest_corpus(corpus_root: pathlib.Path, tier: str = "silver", dry_run: bool = False) -> dict:
    """Ingest one corpus through the license gate. Returns a summary dict."""
    corpus_name = corpus_root.name

    license_text = _read_license(corpus_root)
    if not license_text:
        rec = _record_rejection(corpus_name, None, "缺少许可证声明")
        if not dry_run:
            _append_rejection(rec)
        print(f"[REJECT] {corpus_name}: 缺少许可证声明")
        return {"accepted": 0, "rejected": 1, "reason": "缺少许可证声明"}

    try:
        license_id = check_license(license_text, corpus_name)
    except Exception as e:
        rec = _record_rejection(corpus_name, license_text, str(e))
        if not dry_run:
            _append_rejection(rec)
        print(f"[REJECT] {corpus_name}: {e}")
        return {"accepted": 0, "rejected": 1, "reason": str(e)}

    print(f"[ACCEPT] {corpus_name}: license={license_id}, tier={tier}")
    if dry_run:
        return {"accepted": 1, "rejected": 0, "license": license_id}

    index = _index_corpus(corpus_root, license_id, tier)
    index_path = OPENSOURCE_DIR / f"{corpus_name}_index.json"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(
        dumps_record(index) + "\n", encoding="utf-8"
    )
    return {"accepted": 1, "rejected": 0, "license": license_id, "index": str(index_path)}


def _append_rejection(record: dict) -> None:
    """Append a rejection record idempotently (skip if same reason already logged)."""
    existing = read_jsonl(REJECTED_SOURCES)
    key = (record["source"], record["reason"])
    if any((r.get("source"), r.get("reason")) == key for r in existing):
        return  # already logged — re-run is a no-op (idempotent)
    REJECTED_SOURCES.parent.mkdir(parents=True, exist_ok=True)
    with REJECTED_SOURCES.open("a", encoding="utf-8") as fh:
        fh.write(dumps_record(record) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ingest open-source corpus through license gate.")
    parser.add_argument("corpus_dir", type=pathlib.Path, help="corpus root (must contain LICENSE)")
    parser.add_argument("--tier", default="silver", choices=["silver", "gold", "raw"],
                        help="tier tag for accepted material (default: %(default)s)")
    parser.add_argument("--dry-run", action="store_true", help="gate-check only, write nothing")
    args = parser.parse_args(argv)

    if not args.corpus_dir.is_dir():
        print(f"Error: {args.corpus_dir} is not a directory", file=sys.stderr)
        return 2

    summary = ingest_corpus(args.corpus_dir, tier=args.tier, dry_run=args.dry_run)
    print(f"Summary: accepted={summary['accepted']}, rejected={summary['rejected']}")
    return 0 if summary["rejected"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
