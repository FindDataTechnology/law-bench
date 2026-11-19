"""Registry adapter: fd-cn-gov 公文爬虫 registry -> knowledge units (kind='gov-fact').

Read-only bridge to the sibling repo ``fd-cn-gov`` on this machine. The
registry file ``fd_cn_gov/registry/registry.json`` is loaded at runtime from
the sibling checkout and mapped into the platform's knowledge-unit store
(``src.bench.store``). **No data file is copied into this repo**: the path is
the module constant :data:`GOV_REPO`, overridable via the ``FD_GOV_REPO``
environment variable (re-read on every call, so tests can monkeypatch it).
The sibling checkout must stay read-only.

registry.json schema (as found on disk, verified 2026-11-03 — 4 sections)::

    {
      "sources":            11 entries, 公文目录抓取源（一源=一个部委/机关的公示档案）
      "datasource_columns": 57 entries, 列 schema（section/title/date/url/...）
      "scraw_configs":      11 entries, 抓取配置（与 sources 按 name 1:1 配对）
      "organizations":      11 entries, 主办机关（code/name_zh/name_en/metadata）
    }

source entry fields actually observed (real data, nothing invented)::

    {"id": 1, "name": "mee_gsgg_archive", "label": "MEE Notice Archive (生态环境部公示公告)",
     "url": "https://www.mee.gov.cn/ywdt/gsgg/", "category": "网页抓取",
     "category_label": "Web Scraw", "description": "...", "config": {...}}

**Important honesty note**: this registry is 公文目录的「源注册表」元数据 —— it
describes *which* 机关档案 feeds are crawled and with *which* column schema
(title/date/url 只是列定义, not document instances). 公文正文与逐件文号 **不在
registry 内**; each unit therefore registers the source-level fact set
(one upsert identity per source), and ``body`` is the source label/description
text — see the pack README.

Each source becomes one knowledge unit:

- ``kind='gov-fact'``, ``namespace='gov'``,
- ``external_key = source name``（如 ``mee_gsgg_archive``；已验证 11 源 name 唯一，
  是文内真实稳定键，组合键无需引入）,
- ``tier='silver'``（官方目录元数据 + 机器可对账事实；未经人工逐条核验，不夸大为 gold）,
- ``attrs`` keeps the cross-table reconciled facts: source fields, the joined
  organization (bound by the ``<org_code.lower()>_`` name-prefix convention),
  the column schema with counts (n_columns / n_primary_keys / pk column names /
  date-column presence), and the 1:1 scraw_config pairing (name + url).

The load is idempotent: units are upserted on ``(kind, namespace,
external_key)``, so re-running :func:`load_gov_registry` updates in place and
returns the same count. Structural corruption of the file raises (never
silently dropped); *semantic* violations stay loadable and are failed honestly
by the deterministic checkers in ``checks.py``.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections import defaultdict
from pathlib import Path
from typing import Any, Optional

from src.bench.store import upsert_knowledge_unit

# The kind/namespace this pack owns. Only 'gov-fact' is ingested today;
# pack.yaml declares kinds accordingly (zhengxin indicators & a live graph DB
# are NOT on board — see README for the honest v1 scope).
KIND = "gov-fact"
NAMESPACE = "gov"

# Sibling repo root (read-only). Env override FD_GOV_REPO wins at call time
# via gov_repo(); the constant is the documented default.
GOV_REPO = Path(
    # Default = the sibling checkout next to this repo. An empty default would
    # make the documented "sibling repo" contract false: Path("") is ".", whose
    # .name is "" — so `SENTIMENT_REPO.name == "fd-cn-gov"` (the thing that tells a
    # reader where the default points) silently became false. The env var still
    # wins at call time via the accessor.
    os.environ.get("FD_GOV_REPO", "") or (Path(__file__).resolve().parents[2] / "fd-cn-gov")
)

# Registry file inside the sibling repo (verified to exist there).
REGISTRY_REL = Path("fd_cn_gov") / "registry" / "registry.json"

# Fields a source entry must carry for the loader to proceed (structural only).
_SOURCE_REQUIRED = ("id", "name", "url")
_SECTION_NAMES = ("sources", "datasource_columns", "scraw_configs", "organizations")

# Column fields kept in unit attrs (verbatim from datasource_columns rows).
_COLUMN_FIELDS = (
    "column_name",
    "column_type",
    "semantic_type",
    "is_primary_key",
    "is_nullable",
)


def gov_repo() -> Path:
    """The fd-cn-gov checkout to read from (env override re-read each call)."""
    env = os.environ.get("FD_GOV_REPO")
    return Path(env) if env else GOV_REPO


def _is_present(value: Any) -> bool:
    """Field presence for structural validation: not None, not empty string."""
    return value not in (None, "")


def registry_path(repo: Optional[Path] = None) -> Path:
    return (Path(repo) if repo is not None else gov_repo()) / REGISTRY_REL


def _load_sections(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path}: registry must be a JSON object")
    for section in _SECTION_NAMES:
        if not isinstance(payload.get(section), list):
            raise ValueError(f"{path}: section {section!r} must be a list")
    if not payload["sources"]:
        raise ValueError(f"{path}: 'sources' must not be empty")
    return payload


def _index_orgs(orgs: list, path: Path) -> list[dict]:
    """Keep well-formed organization rows; skip malformed ones (a source whose
    org binding then fails to resolve is recorded as-is and FAILS the
    organization-binding checker honestly — the loader never invents a match)."""
    out = []
    for org in orgs:
        if (
            isinstance(org, dict)
            and isinstance(org.get("code"), str)
            and org["code"].strip()
        ):
            out.append(org)
    return out


def _columns_for(datasource_id: Any, by_ds: dict[int, list]) -> list:
    return by_ds.get(datasource_id, [])


def read_registry_records(repo: Optional[Path] = None) -> list[dict]:
    """Read + structurally validate the sibling registry; return per-source
    reconciled records.

    Raises honestly (FileNotFoundError / json.JSONDecodeError / ValueError)
    when the sibling repo or its registry file is missing/malformed: a column
    row pointing at an unknown ``datasource_id`` is file corruption, not a
    unit-level fact, and fails the whole load (no partial truth).
    """
    path = registry_path(repo)
    payload = _load_sections(path)
    sources = payload["sources"]
    columns = payload["datasource_columns"]
    scraws = payload["scraw_configs"]
    orgs = _index_orgs(payload["organizations"], path)

    # Structural: unique identities, required source fields present.
    ids = [s.get("id") for s in sources]
    names = [s.get("name") for s in sources]
    for s in sources:
        missing = [f for f in _SOURCE_REQUIRED if s.get(f) in (None, "")]
        if missing:
            raise ValueError(
                f"{path}: source missing required field(s) {missing}: "
                f"{s.get('name') or s!r}"
            )
    if len(set(ids)) != len(ids):
        raise ValueError(f"{path}: duplicate source 'id' values")
    if len(set(names)) != len(names):
        raise ValueError(f"{path}: duplicate source 'name' values")

    by_ds: dict[int, list] = defaultdict(list)
    name_by_id = {s["id"]: str(s["name"]) for s in sources}
    for c in columns:
        if not isinstance(c, dict):
            raise ValueError(f"{path}: datasource_columns row must be a mapping")
        ds_id = c.get("datasource_id")
        if not _is_present(ds_id):
            raise ValueError(
                f"{path}: datasource_columns row missing 'datasource_id': {c!r}"
            )
        if ds_id not in name_by_id:
            raise ValueError(
                f"{path}: datasource_columns row {c.get('table_name')!r}."
                f"{c.get('column_name')!r} references unknown source id {ds_id!r}"
            )
        if not _is_present(c.get("column_name")):
            raise ValueError(
                f"{path}: datasource_columns row for source {ds_id!r} missing "
                "'column_name'"
            )
        if c.get("table_name") != name_by_id[ds_id]:
            raise ValueError(
                f"{path}: datasource_columns row table_name {c.get('table_name')!r} "
                f"does not match source name {name_by_id[ds_id]!r} (id={ds_id!r})"
            )
        by_ds[ds_id].append(c)

    scraw_by_name = {
        s["name"]: s for s in scraws if isinstance(s, dict) and s.get("name")
    }

    records: list[dict] = []
    for s in sources:
        name = str(s["name"])
        config = s.get("config") if isinstance(s.get("config"), dict) else {}
        cols = _columns_for(s["id"], by_ds)
        col_rows = [
            {f: c.get(f) for f in _COLUMN_FIELDS}
            for c in cols
            if isinstance(c, dict) and c.get("column_name")
        ]
        bound_orgs = [o for o in orgs if name.startswith(o["code"].lower() + "_")]
        org = bound_orgs[0] if len(bound_orgs) == 1 else None
        scraw = scraw_by_name.get(name)
        records.append(
            {
                "source_id": s["id"],
                "source_name": name,
                "label": str(s.get("label") or ""),
                "url": str(s["url"]),
                "description": str(s.get("description") or ""),
                "category": str(s.get("category") or ""),
                "category_label": str(s.get("category_label") or ""),
                "config_type": str(config.get("type") or ""),
                "seed_url": str(config.get("seed_url") or ""),
                "n_archives": len(config.get("archives") or []),
                "columns": col_rows,
                "n_columns": len(col_rows),
                "n_primary_keys": sum(
                    1 for r in col_rows if r["is_primary_key"] == 1
                ),
                "pk_column_names": [
                    r["column_name"] for r in col_rows if r["is_primary_key"] == 1
                ],
                "has_date_column": any(
                    r["column_name"] == "date" and r["column_type"] == "date"
                    for r in col_rows
                ),
                "org_code": org["code"] if org else None,
                "org_name_zh": (org.get("name_zh") or None) if org else None,
                "org_name_en": (org.get("name_en") or None) if org else None,
                "org_type": (org.get("metadata") or {}).get("type") if org else None,
                "scraw_name": str(scraw["name"]) if scraw else None,
                "scraw_url": str(scraw.get("url") or "") if scraw else None,
                "source_file": str(path),
            }
        )
    return records


def record_to_unit(record: dict) -> dict:
    """Map one reconciled registry record to ``upsert_knowledge_unit`` kwargs."""
    pk = "、".join(record["pk_column_names"]) or "(none)"
    org = (
        f"{record['org_name_zh']}（{record['org_code']}，{record['org_type']}）"
        if record["org_code"]
        else "（未绑定机关）"
    )
    body = (
        f"公文目录抓取源 {record['source_name']}：{record['label']}。"
        f"主办机关 {org}；类别 {record['category']}；入口 {record['url']}；"
        f"登记列 {record['n_columns']} 个（主键 {pk}，含 date 列: "
        f"{record['has_date_column']}）；抓取配置配对 {record['scraw_name']}。"
        f"公文正文不在 registry（源注册表只含目录元数据与列 schema），"
        f"本单元只登记这些可对账的事实。"
    )
    attrs = {k: v for k, v in record.items() if k != "source_file"}
    return {
        "kind": KIND,
        "namespace": NAMESPACE,
        "external_key": record["source_name"],
        "body": body,
        "tags": {"record_type": "source-registry-entry"},
        "attrs": attrs,
        "tier": "silver",
        "source_path": record.get("source_file"),
        "provenance": {
            "source_repo": "fd-cn-gov (read-only sibling checkout)",
            "file": REGISTRY_REL.as_posix(),
            "adapter": "packs/gov/adapters.py",
        },
    }


def load_gov_registry(conn: Any) -> int:
    """Upsert every registry source as a knowledge unit; return the count.

    Idempotent: re-running upserts the same ``(kind, namespace, source_name)``
    identities and returns the same count. Raises as-is when the sibling repo
    is missing/unreadable (never invents data).
    """
    path = registry_path()
    sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
    count = 0
    for record in read_registry_records():
        unit = record_to_unit(record)
        unit["provenance"] = {**unit["provenance"], "registry_sha256": sha256}
        upsert_knowledge_unit(conn, **unit)
        count += 1
    return count
