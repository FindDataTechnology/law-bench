"""One-off: generate stored docx contracts for every (scenario x stance) combo.

For each contract type, enumerate the full tag combination space:
  - base (no tags)
  - each scenario (tagged override)
  - each stance (custom override: pro_a / pro_b / balanced)
  - each (scenario, stance) pair
and call ``generate_stored`` (MinIO upload + ``contract_artifacts`` DB row).
Content-addressed by ``md5(body_text)``: identical inputs reuse the same
artifact (``reused=True``, no re-upload), so re-running is a no-op. Reports
per-type progress + a final new/reused/fail summary.

``--force`` re-uploads every docx (overwriting the MinIO object) even when the
artifact already exists — use it to refresh formatting/visuals after a renderer
change that does not alter ``body_text`` (e.g. the add-contract-docx-formatting
work: new fonts/A4/signature layout, same body hash).

Re-run: ``PYTHONPATH=. python3 scripts/generate_all_types_stored.py [--force]``
"""

from __future__ import annotations

import sys
import time

from src.contracts import list_contract_types
from src.contracts.artifacts import generate_stored
from src.eval.db import connect


def _distinct(conn, key: str, dim: str, source: str) -> list[str]:
    """Distinct values of a tag ``dim`` on clauses of ``source`` for ``key``."""
    rows = conn.execute(
        f"SELECT DISTINCT tags->>'{dim}' AS v FROM clauses "
        "WHERE contract_type = %s AND tags->>'source' = %s AND tags ? %s ORDER BY 1",
        (key, source, dim),
    ).fetchall()
    return [r["v"] for r in rows if r["v"]]


def _combos(scenarios: list[str], stances: list[str]) -> list[tuple[str | None, str | None]]:
    """Full scenario x stance x base combination space for one type."""
    combos: list[tuple[str | None, str | None]] = [(None, None)]
    combos += [(s, None) for s in scenarios]
    combos += [(None, st) for st in stances]
    combos += [(s, st) for s in scenarios for st in stances]
    return combos


def main() -> None:
    force = "--force" in sys.argv[1:]
    if force:
        print("FORCE: re-uploading docx for every existing artifact "
              "(refresh visuals, body_text unchanged)\n", flush=True)
    types = list_contract_types()
    conn = connect()
    ok = reused = fail = 0
    failures: list[str] = []
    t0 = time.time()
    for i, t in enumerate(types, 1):
        key = t["key"]
        scenarios = _distinct(conn, key, "scenario", "tagged")
        stances = _distinct(conn, key, "stance", "custom")
        combos = _combos(scenarios, stances)
        type_ok = type_reused = type_fail = 0
        for s, st in combos:
            label = f"{key}|scen={s or '-'}|stance={st or '-'}"
            try:
                r = generate_stored(key, scenario=s, stance=st, format="docx", force=force)
                if r["reused"]:
                    reused += 1
                    type_reused += 1
                else:
                    ok += 1
                    type_ok += 1
            except Exception as exc:  # noqa: BLE001
                fail += 1
                type_fail += 1
                failures.append(f"{label}: {str(exc)[:80]}")
        print(
            f"  [{i:>2}/{len(types)}] {key:<22} scen={len(scenarios):>2} stance={len(stances)} "
            f"combos={len(combos):>3} | new={type_ok} reused={type_reused} fail={type_fail} "
            f"({time.time()-t0:.0f}s)",
            flush=True,
        )
    conn.close()
    print(f"\nDONE in {time.time()-t0:.0f}s: new={ok} reused={reused} fail={fail}")
    if failures:
        print(f"\n{len(failures)} failures:")
        for f in failures[:40]:
            print(f"  {f}")


if __name__ == "__main__":
    main()
