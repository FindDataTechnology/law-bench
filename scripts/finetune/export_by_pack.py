#!/usr/bin/env python3
"""Per-domain-pack flywheel dataset export CLI (task 6.4, add-knowledge-bench-platform).

Generalizes the vertical-specific Judge-C / Drafter-A exporters: the export
machine lives in the domain-neutral kernel (``src.bench.flywheel``), this CLI
only resolves *which pack/kind* to export and supplies the *material adapter*
that maps a pack's own tables onto generic tier-tagged records.

Usage::

    python3 scripts/finetune/export_by_pack.py \
        --pack legal --kind clause --purpose sft_warmup --tier-floor raw \
        --out data/finetune/flywheel/legal-clause-warmup.jsonl

    python3 scripts/finetune/export_by_pack.py \
        --pack finance-data --kind fact --purpose ground_truth

Material resolution, in priority order:

1. A registered adapter for ``"<pack>:<kind>"`` (pack-specific; the flagship
   legal pack's ``clause`` kind maps the legacy vertical tables here).
2. A registered adapter for the bare ``kind`` (kind-specific).
3. Otherwise: the kernel default — knowledge units of ``kind`` from
   ``src.bench.store`` (how every other pack's material should onboard).

Domain packs may register their own adapters either by importing this module
and calling :func:`register_adapter`, or via ``--adapter-module <dotted.path>``
(imported before the export runs; the module registers at import time).

Every tier decision routes through the single-point guards in
``src.bench.tiers`` via the kernel exporter: ground-truth / reward-positive
purposes are gold-only and fail loud on forbidden material; warm-up purposes
filter by tier floor (silver-and-above by default). Zero LLM, zero network.
"""
from __future__ import annotations

import argparse
import os
import pathlib
import sys
from typing import Callable, Iterable

# Repo root so ``src.bench`` resolves with or without the project venv
# (flywheel/tiers are pure stdlib — see scripts/finetune/common.py's pattern).
REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.bench import flywheel  # noqa: E402  (stdlib-only kernel module)
from src.bench.tiers import TIERS, TierGuardError  # noqa: E402  (stdlib-only)

DEFAULT_OUT_ROOT = pathlib.Path("data") / "finetune" / "flywheel"

# Adapter: (conn, pack, kind) -> iterable of tier-tagged material records
# (shape documented in src.bench.flywheel.export_dataset's extract_fn).
Adapter = Callable[..., Iterable[dict]]

# key: "<pack>:<kind>" (pack-specific) or "<kind>" (generic).
ADAPTERS: dict[str, Adapter] = {}


def register_adapter(key: str, fn: Adapter) -> Adapter:
    """Register a material adapter for ``"<pack>:<kind>"`` or ``"<kind>"``.

    Domain packs call this at import time; the CLI picks it up via
    ``--adapter-module <dotted.path>``.
    """
    ADAPTERS[key] = fn
    return fn


# ---------------------------------------------------------------------------
# flagship legal pack adapter: kind 'clause' from the legacy vertical tables
# ---------------------------------------------------------------------------

def legal_clause_material(conn, pack: str, kind: str) -> list[dict]:
    """Map the legacy legal tables onto generic tier-tagged material records.

    - ``clauses`` rows: structural corpus backbone -> tier ``raw`` (per the
      warehouse tier map; no label semantics).
    - ``eval_criteria_results`` rows: machine self-eval -> tier ``bronze``
      (never ground truth; the kernel guard enforces that downstream).

    Read-only: ``SELECT`` only, ordered by id for deterministic output.
    """
    out: list[dict] = []
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM clauses ORDER BY id")
        for row in cur.fetchall():
            out.append(
                {
                    "kind": kind,
                    "namespace": pack,
                    "external_key": f"clauses:{row['id']}",
                    "body": row.get("body") or "",
                    "tags": {
                        "section": row.get("section"),
                        "type": row.get("contract_type"),
                    },
                    "attrs": {k: v for k, v in row.items() if k != "body"},
                    "tier": "raw",
                    "source_path": row.get("source_path"),
                    "provenance": {
                        "table": "clauses",
                        "row_id": row["id"],
                        "body_hash": row.get("body_hash"),
                    },
                }
            )
        cur.execute("SELECT * FROM eval_criteria_results ORDER BY id")
        for row in cur.fetchall():
            out.append(
                {
                    "kind": kind,
                    "namespace": pack,
                    "external_key": f"eval_criteria_results:{row['id']}",
                    "body": row.get("reasoning") or row.get("title") or "",
                    "tags": {"criterion_id": row.get("criterion_id")},
                    "attrs": {"verdict": row.get("verdict"), "run_id": row.get("run_id")},
                    "tier": "bronze",
                    "provenance": {
                        "table": "eval_criteria_results",
                        "row_id": row["id"],
                        "run_id": row.get("run_id"),
                        "annotated_by": "machine_self_eval",
                    },
                }
            )
    return out


register_adapter("legal:clause", legal_clause_material)


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------

def _dsn() -> str:
    return (
        os.environ.get("database_url")
        or os.environ.get("DATABASE_URL")
        or "postgresql://app:CHANGEME@localhost:5432/law_bench"
    )


def _connect(dsn: str):
    # Lazy import: --help must work without the project venv installed.
    import psycopg
    from psycopg.rows import dict_row

    return psycopg.connect(dsn, row_factory=dict_row, autocommit=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="export_by_pack.py",
        description=(
            "Export one domain pack's Judge/Drafter dataset via the "
            "domain-neutral flywheel kernel (src.bench.flywheel)."
        ),
    )
    parser.add_argument("--pack", required=True, help="domain pack name (packs/<name>)")
    parser.add_argument("--kind", required=True, help="knowledge-unit kind declared by the pack")
    parser.add_argument(
        "--purpose",
        default="ground_truth",
        help=(
            "labeled purposes (gold-only, fail-loud guard): ground_truth, "
            "reward_positive, ...; warm-up purposes (tier-floor filtered): "
            "sft_warmup, warmup"
        ),
    )
    parser.add_argument(
        "--tier-floor",
        dest="tier_floor",
        default=None,
        choices=list(TIERS),
        help="rank cutoff for warm-up exports (default: silver); labeled must be gold",
    )
    parser.add_argument(
        "--out",
        type=pathlib.Path,
        default=None,
        help=f"destination JSONL (default: {DEFAULT_OUT_ROOT}/<pack>-<kind>-<purpose>.jsonl)",
    )
    parser.add_argument(
        "--adapter-module",
        default=None,
        help="dotted module to import before export (pack-side register_adapter hook)",
    )
    parser.add_argument(
        "--dsn",
        default=None,
        help="Postgres DSN (default: $database_url / $DATABASE_URL)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10000,
        help="row cap for the default knowledge-units loader (adapters ignore it)",
    )
    parser.add_argument(
        "--list-adapters",
        action="store_true",
        help="print registered adapters and exit (no DB access)",
    )
    return parser


def _run(args: argparse.Namespace) -> int:
    if args.list_adapters:
        for key in sorted(ADAPTERS):
            print(f"  adapter {key}: {ADAPTERS[key].__qualname__}")
        return 0

    # Lazy heavy imports (yaml via src.bench.packs; env via src.settings).
    from src.bench.packs import load_pack

    try:
        manifest = load_pack(args.pack)
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: cannot load pack {args.pack!r}: {exc}", file=sys.stderr)
        return 2
    kinds = manifest.get("kinds") or []
    if args.kind not in kinds:
        print(
            f"error: kind {args.kind!r} is not declared by pack {args.pack!r} "
            f"(kinds: {kinds}); the pack manifest is the single place a pack "
            f"declares what it exports",
            file=sys.stderr,
        )
        return 2

    adapter = ADAPTERS.get(f"{args.pack}:{args.kind}") or ADAPTERS.get(args.kind)
    conn = _connect(args.dsn or _dsn())
    extract_fn = None
    if adapter is not None:
        extract_fn = lambda k: adapter(conn, args.pack, k)  # noqa: E731

    out_path = args.out or (
        DEFAULT_OUT_ROOT / f"{args.pack}-{args.kind}-{args.purpose}.jsonl"
    )
    stats = flywheel.export_dataset(
        conn,
        pack=args.pack,
        kind=args.kind,
        purpose=args.purpose,
        tier_floor=args.tier_floor,
        out_path=out_path,
        extract_fn=extract_fn,
        limit=args.limit,
    )
    print(
        f"flywheel export: pack={stats['pack']} kind={stats['kind']} "
        f"purpose={stats['purpose']} floor={stats['tier_floor']} "
        f"pool={stats['pool']} exported={stats['exported']} "
        f"tiers={stats['tiers']} -> {stats['out_path']}"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.adapter_module:
        import importlib

        importlib.import_module(args.adapter_module)
    try:
        return _run(args)
    except TierGuardError as exc:
        # Guard trip: refuse the request loudly (exit non-zero, one clean line).
        print(f"guard rejected: {exc}", file=sys.stderr)
        return 3
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


# __main__ guard is mandatory: verify_expand.py (this dir) runs its checks at
# import time and poisons any `import export_by_pack` — never execute on import.
if __name__ == "__main__":
    raise SystemExit(main())
