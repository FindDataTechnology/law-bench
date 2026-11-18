"""Deterministic checkers for kind='gov-fact' (政务 registry facts).

Registration happens at import time: importing this module installs the
checkers below into ``src.bench.data_checks.register_checker`` for kind
``'gov-fact'``. Every checker is pure and deterministic — no LLM, no network,
no filesystem.

**KG 车道验收判据迁移（v1 降级实现）**：四条硬判据源文件已找到并落地在
``/Users/chengsishi/finddata/fd-text-core/scripts/kg_graph_checks.py``（配套
``kg_statute_repair_names.py`` 的脏文号判据；注意它在 fd-text-core，不在
fd-legal-kg）。原脚本连 FalkorDB 图查询（网络依赖），无法在本平台离线跑；
本包提炼其中**确定性判据的语义**，降级为对 registry「元数据图」
（sources→datasource_columns→organizations→scraw_configs 的引用关系）的
逐单元对账：

- 判据①「分裂节点清零」→ 身份唯一/格式：external_key 与 source_name 同一、
  snake_case 形态（:func:`check_identity_format`）。
- 判据③「规模统计」→ 覆盖度对账：登记的列数必须与实际列 schema 逐一对得上、
  每源恰一个主键、每源必有 date 列（:func:`check_column_coverage`、
  :func:`check_primary_key_exists`、:func:`check_date_anchor_present`）。
- 判据④「脏值清零」→ 受控词表 + 引用可解：category/type/列类型/语义类型必须
  落在 registry 实际词表内（:func:`check_category_vocabulary`），机关绑定与
  抓取配置配对必须可解析（:func:`check_organization_binding`、
  :func:`check_scraw_pairing`）。
- 判据②「同名不同文号实体可分（113/71 口径）」不迁移：registry 无文号实例，
  没有可比对的对象，v1 如实略过（README 同注）。

Vocabularies below mirror the real ``registry.json`` values (verified
2026-11-03); a new category/type in the sibling repo fails loudly until
consciously added here — the fd-data-quality value-domain contract.
"""

from __future__ import annotations

import re
import urllib.parse
from typing import Any

from src.bench.data_checks import CheckResult, register_checker

from .adapters import KIND

# --- vocabularies (from real registry.json values; extend consciously) ------

CATEGORIES = {"网页抓取": "Web Scraw"}
CONFIG_TYPES = {"scraw"}
COLUMN_TYPES = {"string", "date"}
SEMANTIC_TYPES = {"category", "date", "identifier", "title", "url"}
_ORG_CODE_RE = re.compile(r"^[A-Z][A-Z0-9]{1,11}$")
_SOURCE_NAME_RE = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)+$")

_PLACEHOLDERS = {"", "-", "?", "N/A", "n/a", "TODO", "待定", "未知"}


def _attr(unit: dict, name: str) -> Any:
    return (unit.get("attrs") or {}).get(name)


def _is_nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and value.strip() not in _PLACEHOLDERS


# --- deterministic checkers (kind='gov-fact') --------------------------------


def check_identity_format(unit: dict) -> CheckResult:
    """判据①迁移（分裂/唯一）：external_key 必须是真实稳定键 source_name 本身，
    且 source_name 为小写 snake_case、source_id 为正整数、label/description
    非空非占位。"""
    key = unit.get("external_key")
    name = _attr(unit, "source_name")
    sid = _attr(unit, "source_id")
    ok = (
        isinstance(name, str)
        and key == name
        and bool(_SOURCE_NAME_RE.fullmatch(name or ""))
        and name.endswith("_archive")
        and isinstance(sid, int)
        and not isinstance(sid, bool)
        and sid > 0
        and _is_nonempty_str(_attr(unit, "label"))
        and _is_nonempty_str(_attr(unit, "description"))
    )
    detail = (
        f"external_key={key!r} source_name={name!r} source_id={sid!r} "
        "(need snake_case *_archive == key, id > 0, non-placeholder label/description)"
    )
    return CheckResult(name="identity-format", passed=ok, detail=detail)


def check_url_https_format(unit: dict) -> CheckResult:
    """入口 URL 形态：url/seed_url 必须是带主机的 https 绝对地址（公文源强制
    https；seed_url 是源注册表对抓取入口的声明值）。"""
    url = _attr(unit, "url")
    seed = _attr(unit, "seed_url")
    ok = True
    for value in (url, seed):
        if not isinstance(value, str):
            ok = False
            break
        parsed = urllib.parse.urlsplit(value)
        if parsed.scheme != "https" or not parsed.netloc or " " in value:
            ok = False
            break
    detail = f"url={url!r} seed_url={seed!r} (need https URLs with host)"
    return CheckResult(name="url-https-format", passed=ok, detail=detail)


def check_category_vocabulary(unit: dict) -> CheckResult:
    """判据④迁移（脏值清零）·受控词表：category 落在已验证词表且 label 映射一致、
    config.type ∈ CONFIG_TYPES。"""
    category = _attr(unit, "category")
    label = _attr(unit, "category_label")
    ctype = _attr(unit, "config_type")
    ok = (
        category in CATEGORIES
        and label == CATEGORIES.get(category)
        and ctype in CONFIG_TYPES
    )
    detail = (
        f"category={category!r}/{label!r} (allowed {sorted(CATEGORIES.items())}) "
        f"config_type={ctype!r} (allowed {sorted(CONFIG_TYPES)})"
    )
    return CheckResult(name="category-vocabulary", passed=ok, detail=detail)


def check_organization_binding(unit: dict) -> CheckResult:
    """机关引用可解：每源必须恰好绑定一个机关（源名以 <code 小写>_ 起头），
    且 code 为大写形态、中文名非空。"""
    code = _attr(unit, "org_code")
    name = _attr(unit, "source_name")
    name_zh = _attr(unit, "org_name_zh")
    ok = (
        isinstance(code, str)
        and bool(_ORG_CODE_RE.fullmatch(code))
        and isinstance(name, str)
        and name.startswith(code.lower() + "_")
        and _is_nonempty_str(name_zh)
    )
    detail = f"org_code={code!r} source_name={name!r} org_name_zh={name_zh!r}"
    return CheckResult(name="organization-binding", passed=ok, detail=detail)


def check_column_coverage(unit: dict) -> CheckResult:
    """判据③迁移（规模/覆盖度对账）：登记的列清单与声明列数一致、非空，
    每列字段完整且类型落在受控词表、列名在源内唯一、is_nullable ∈ {0,1}。"""
    columns = _attr(unit, "columns")
    n_columns = _attr(unit, "n_columns")
    if not isinstance(columns, list) or not columns:
        ok = False
    else:
        ok = n_columns == len(columns)
        seen: set[str] = set()
        for col in columns:
            if not isinstance(col, dict):
                ok = False
                break
            cname = col.get("column_name")
            if (
                not _is_nonempty_str(cname)
                or cname in seen
                or col.get("column_type") not in COLUMN_TYPES
                or col.get("semantic_type") not in SEMANTIC_TYPES
                or col.get("is_nullable") not in (0, 1)
            ):
                ok = False
                break
            seen.add(cname)
    n = len(columns) if isinstance(columns, list) else None
    detail = f"n_columns={n_columns!r} len(columns)={n!r} vocab={sorted(COLUMN_TYPES)}/{sorted(SEMANTIC_TYPES)}"
    return CheckResult(name="column-coverage", passed=ok, detail=detail)


def check_primary_key_exists(unit: dict) -> CheckResult:
    """判据③迁移 · 主键存在性：每源恰好一个 is_primary_key=1 的列（真实 registry
    全部以 url 为主键）。"""
    n_pk = _attr(unit, "n_primary_keys")
    pk_names = _attr(unit, "pk_column_names")
    ok = n_pk == 1 and isinstance(pk_names, list) and len(pk_names) == 1
    detail = f"n_primary_keys={n_pk!r} pk_column_names={pk_names!r}"
    return CheckResult(name="primary-key-exists", passed=ok, detail=detail)


def check_date_anchor_present(unit: dict) -> CheckResult:
    """日期列锚点：每源必须声明名为 date、类型 date 的列（公文目录=日期目录；
    registry 无逐件日期实例，列 schema 是唯一的日期锚点，如实核验它）。"""
    has_date = _attr(unit, "has_date_column")
    ok = has_date is True
    detail = f"has_date_column={has_date!r} (need True: a 'date' column typed 'date')"
    return CheckResult(name="date-anchor-present", passed=ok, detail=detail)


def check_scraw_pairing(unit: dict) -> CheckResult:
    """判据④迁移 · 抓取配置配对可解且一致：scraw_configs 与 sources 按 name 1:1，
    配对行的 url 必须与源 url 相同（声明值与实际登记对账，dashboards finalize
    式闸门）。"""
    name = _attr(unit, "source_name")
    url = _attr(unit, "url")
    scraw_name = _attr(unit, "scraw_name")
    scraw_url = _attr(unit, "scraw_url")
    ok = (
        scraw_name is not None
        and scraw_name == name
        and scraw_url == url
    )
    detail = f"source={name!r} url={url!r} paired scraw={scraw_name!r}/{scraw_url!r}"
    return CheckResult(name="scraw-pairing", passed=ok, detail=detail)


# Registration happens at import time (task 4.4 contract: 模块 import 即注册).
register_checker(KIND, "identity-format", check_identity_format)
register_checker(KIND, "url-https-format", check_url_https_format)
register_checker(KIND, "category-vocabulary", check_category_vocabulary)
register_checker(KIND, "organization-binding", check_organization_binding)
register_checker(KIND, "column-coverage", check_column_coverage)
register_checker(KIND, "primary-key-exists", check_primary_key_exists)
register_checker(KIND, "date-anchor-present", check_date_anchor_present)
register_checker(KIND, "scraw-pairing", check_scraw_pairing)
