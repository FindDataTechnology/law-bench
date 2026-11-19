"""Corpus adapter: fd-sentiment gold sets -> knowledge units (kind='fact').

Read-only bridge to the sibling repo ``fd-sentiment`` on this machine. The
gold annotation file ``gold/gold-v9.json`` is loaded at runtime from the
sibling checkout and mapped into the platform's knowledge-unit store
(``src.bench.store``). **No data file is copied into this repo**: the path is
the module constant :data:`SENTIMENT_REPO`, overridable via the
``FD_SENTIMENT_REPO`` environment variable (re-read on every call, so tests
can monkeypatch it). The sibling checkout must stay read-only.

gold-v9 item schema (as found in the sibling repo, 105 items, verified
2026-11-03)::

    {"doc_id": "1200474144", "as_of": "2014-12-17",
     "expected_band": "neutral",
     "text_sha256": "940f83cd...", "text_chars": 1114}

- ``expected_band``: the five-band human gold label; the vocabulary is
  ``fd_sentiment.models.BANDS`` in the sibling repo (``strong_bullish``,
  ``bullish``, ``neutral``, ``bearish``, ``strong_bearish``).
- ``text_sha256`` / ``text_chars``: fingerprint and length anchors of the
  source announcement text. The text itself stays in the sibling repo's
  lineage (fd-cn-report downloads) and is NOT ingested here.
- gold-v9 has **no amount fields**; the adapter maps exactly what the file
  contains and invents nothing.

Each item becomes one knowledge unit:

- ``kind='fact'`` (a curated, as-of assertion about one announcement),
- ``namespace='finance-data'``, ``external_key=doc_id`` (unique in the file),
- ``tier='gold'`` (human-annotated gold set),
- ``attrs`` keeps the file's fields verbatim plus a derived three-way
  ``direction`` (bullish/neutral/bearish, same sign grouping as
  ``fd_sentiment.evaluate._BAND_SIGN``).

The load is idempotent: units are upserted on ``(kind, namespace,
external_key)``, so re-running :func:`load_sentiment_gold` updates in place
and returns the same count.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

from src.bench.store import upsert_knowledge_unit

# The kind/namespace this pack owns. Kind 'fact' reflects what is actually
# ingested today (gold annotations); no indicator corpus is on board yet, so
# pack.yaml declares kinds: [fact] honestly.
KIND = "fact"
NAMESPACE = "finance-data"

# Sibling repo root (read-only). Env override FD_SENTIMENT_REPO wins at call
# time via sentiment_repo(); the constant is the documented default.
SENTIMENT_REPO = Path(
    # Default = the sibling checkout next to this repo. An empty default would
    # make the documented "sibling repo" contract false: Path("") is ".", whose
    # .name is "" — so `SENTIMENT_REPO.name == "fd-sentiment"` (the thing that tells a
    # reader where the default points) silently became false. The env var still
    # wins at call time via the accessor.
    os.environ.get("FD_SENTIMENT_REPO", "") or (Path(__file__).resolve().parents[2] / "fd-sentiment")
)

# Gold file inside the sibling repo (verified to exist there).
GOLD_REL = Path("gold") / "gold-v9.json"

# Five-band vocabulary — single source of truth is fd_sentiment.models.BANDS
# in the sibling repo; kept in sync here (checks.py repeats it for
# independence; tests pin the equality via real data).
BANDS = (
    "strong_bullish",
    "bullish",
    "neutral",
    "bearish",
    "strong_bearish",
)

# Band -> three-way direction, same sign grouping as fd_sentiment.evaluate.
BAND_TO_DIRECTION = {
    "strong_bullish": "bullish",
    "bullish": "bullish",
    "neutral": "neutral",
    "bearish": "bearish",
    "strong_bearish": "bearish",
}

_REQUIRED_FIELDS = ("doc_id", "as_of", "expected_band", "text_sha256", "text_chars")


def sentiment_repo() -> Path:
    """The fd-sentiment checkout to read from (env override re-read each call)."""
    env = os.environ.get("FD_SENTIMENT_REPO")
    return Path(env) if env else SENTIMENT_REPO


def _record_from_item(item: Any, payload: dict, path: Path) -> dict:
    """Validate one gold item structurally; raise ValueError on malformation.

    Structural only: presence/type of the documented fields. Semantic checks
    (band vocabulary, fingerprint format, ...) belong to the deterministic
    checkers in checks.py so that bad data is *recorded and failed honestly*,
    not dropped at the door.
    """
    if not isinstance(item, dict):
        raise ValueError(f"{path}: gold item must be a mapping, got {type(item).__name__}")
    missing = [f for f in _REQUIRED_FIELDS if item.get(f) in (None, "")]
    if missing:
        raise ValueError(f"{path}: gold item missing required field(s) {missing}: {item!r}")
    try:
        text_chars = int(item["text_chars"])
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"{path}: text_chars must be an integer, got {item['text_chars']!r}"
        ) from exc
    doc_id = str(item["doc_id"])
    return {
        "doc_id": doc_id,
        "as_of": str(item["as_of"]),
        "expected_band": str(item["expected_band"]),
        "text_sha256": str(item["text_sha256"]),
        "text_chars": text_chars,
        "set_version": payload.get("set_version"),
        "built_at": payload.get("built_at"),
        "source_file": str(path),
    }


def read_gold_records(repo: Optional[Path] = None) -> list[dict]:
    """Read + structurally validate the sibling gold file; return item dicts.

    Raises honestly (FileNotFoundError / json.JSONDecodeError / ValueError)
    when the sibling repo or its gold file is missing or malformed.
    """
    path = (Path(repo) if repo is not None else sentiment_repo()) / GOLD_REL
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path}: gold file must be a JSON object")
    items = payload.get("items")
    if not isinstance(items, list) or not items:
        raise ValueError(f"{path}: 'items' must be a non-empty list")
    return [_record_from_item(item, payload, path) for item in items]


def record_to_unit(record: dict) -> dict:
    """Map one parsed gold record to ``upsert_knowledge_unit`` keyword args."""
    doc_id = record["doc_id"]
    band = record["expected_band"]
    direction = BAND_TO_DIRECTION.get(band)
    body = (
        f"公告情绪金标样本 doc_id={doc_id}"
        f"（金标集 {record.get('set_version')}）：公告日 {record['as_of']}，"
        f"人工金标档位 {band}（方向 {direction or 'unknown'}）；"
        f"原文 {record['text_chars']} 字符，sha256 {record['text_sha256']}。"
        f"原文与金标规则留在 fd-sentiment 兄弟仓，本单元只登记事实与锚点。"
    )
    attrs = {
        "doc_id": doc_id,
        "as_of": record["as_of"],
        "expected_band": band,
        "direction": direction,
        "text_sha256": record["text_sha256"],
        "text_chars": record["text_chars"],
        "gold_set": record.get("set_version"),
        "gold_built_at": record.get("built_at"),
    }
    return {
        "kind": KIND,
        "namespace": NAMESPACE,
        "external_key": doc_id,
        "body": body,
        "attrs": attrs,
        "tier": "gold",
        "source_path": record.get("source_file"),
        "provenance": {
            "source_repo": "fd-sentiment (read-only sibling checkout)",
            "file": GOLD_REL.as_posix(),
            "set_version": record.get("set_version"),
            "built_at": record.get("built_at"),
            "adapter": "packs/finance-data/adapters.py",
        },
    }


def load_sentiment_gold(conn: Any) -> int:
    """Upsert every gold-v9 item as a knowledge unit; return the item count.

    Idempotent: re-running upserts the same ``(kind, namespace, doc_id)``
    identities and returns the same count. Raises as-is when the sibling repo
    is missing/unreadable (never invents data).
    """
    count = 0
    for record in read_gold_records():
        upsert_knowledge_unit(conn, **record_to_unit(record))
        count += 1
    return count
