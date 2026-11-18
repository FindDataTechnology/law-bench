"""Deterministic checkers for kind='fact' + the first data-QA goldset.

Registration happens at import time: importing this module installs the
checkers below into ``src.bench.data_checks.register_checker`` for kind
``'fact'`` (the kind packs/finance-data actually ingests). Every checker is
pure and deterministic — no LLM, no network, no filesystem.

Checker semantics follow the sibling repos' discipline:

- **fd-data-quality ``CONTRACTS.md``** (重灌契约): 值域校验、键唯一/一致、
  格式校验先行 —— 在本包里对应 fact 单元的字段契约（band 词表、方向一致、
  sha256 格式、长度锚点为正、doc_id 身份对账、日期格式、金额锚点可解析）。
- **dashboards ``data_plane.finalize``** (出片闸门): 声明值必须与实际数据
  对账一致，否则 FATAL —— :func:`build_data_qa_goldset` 把这个判据改写成
  首批「数据 QA 金集题目」：每题 = 对某条 fact 的期望检查点（声明值，
  来自 gold-v9 真值）+ 判定函数引用名（对实际单元求值）。

Note: gold-v9 has no amount fields, so the amount-anchor checker passes with
``None`` today; it pins the contract "如有金额字段则必须可解析为数值或 None"
so future gold extensions fail loudly instead of silently.

The band vocabulary here must stay in sync with adapters.py (both mirror
``fd_sentiment.models.BANDS`` in the read-only sibling repo); the test suite
pins them against real data.
"""

from __future__ import annotations

import datetime as _dt
import re
from typing import Any, Callable

from src.bench.data_checks import CheckResult, register_checker

from .adapters import BAND_TO_DIRECTION, BANDS, KIND, NAMESPACE

# --- vocabularies (fd-data-quality contract style: explicit allowed sets) ----

ALLOWED_DIRECTIONS = ("bearish", "neutral", "bullish")

_SHA256_RE = re.compile(r"[0-9a-f]{64}")

# --- checker helpers ---------------------------------------------------------


def _attr(unit: dict, name: str) -> Any:
    return (unit.get("attrs") or {}).get(name)


# --- deterministic checkers (kind='fact') ------------------------------------


def check_band_vocabulary(unit: dict) -> CheckResult:
    """强度档位值域：expected_band 必须落在五档词表内。"""
    band = _attr(unit, "expected_band")
    ok = band in BANDS
    detail = f"expected_band={band!r} allowed={list(BANDS)}"
    return CheckResult(name="band-vocabulary", passed=ok, detail=detail)


def check_band_direction_consistency(unit: dict) -> CheckResult:
    """方向对账：direction 必须在方向词表内且与档位推出的方向一致。

    dashboards finalize 判据的直系改写：两个声明字段（band、direction）
    互相矛盾即 FAIL，不允许「声明与数据打架」的单元过闸。
    """
    band = _attr(unit, "expected_band")
    direction = _attr(unit, "direction")
    implied = BAND_TO_DIRECTION.get(band)
    ok = direction in ALLOWED_DIRECTIONS and implied is not None and direction == implied
    detail = f"band={band!r} direction={direction!r} (band implies {implied!r})"
    return CheckResult(name="band-direction-consistency", passed=ok, detail=detail)


def check_text_fingerprint_sha256(unit: dict) -> CheckResult:
    """原文指纹格式：text_sha256 必须是 64 位小写十六进制。"""
    fp = _attr(unit, "text_sha256")
    ok = isinstance(fp, str) and bool(_SHA256_RE.fullmatch(fp))
    detail = f"text_sha256={'64-hex' if ok else repr(fp)}"
    return CheckResult(name="text-fingerprint-sha256", passed=ok, detail=detail)


def check_text_chars_positive(unit: dict) -> CheckResult:
    """文本非空锚点：text_chars 必须是正整数（原文长度 ≥1，非占位）。"""
    n = _attr(unit, "text_chars")
    ok = isinstance(n, int) and not isinstance(n, bool) and n > 0
    detail = f"text_chars={n!r} (need int > 0)"
    return CheckResult(name="text-chars-positive", passed=ok, detail=detail)


def check_doc_id_identity(unit: dict) -> CheckResult:
    """身份对账：attrs.doc_id 非空且与 upsert 键 external_key 一致。"""
    doc_id = _attr(unit, "doc_id")
    ok = isinstance(doc_id, str) and doc_id != "" and doc_id == unit.get("external_key")
    detail = f"doc_id={doc_id!r} external_key={unit.get('external_key')!r}"
    return CheckResult(name="doc-id-identity", passed=ok, detail=detail)


def check_as_of_iso_date(unit: dict) -> CheckResult:
    """日期格式：as_of 必须是可解析的 ISO 日期（YYYY-MM-DD）。"""
    as_of = _attr(unit, "as_of")
    ok = isinstance(as_of, str)
    if ok:
        try:
            _dt.date.fromisoformat(as_of)
        except ValueError:
            ok = False
    detail = f"as_of={as_of!r} (need ISO date)"
    return CheckResult(name="as-of-iso-date", passed=ok, detail=detail)


def check_amount_anchor_parseable(unit: dict) -> CheckResult:
    """金额锚点契约：如存在金额字段（amount_yi，亿元）必须可解析为数值。

    gold-v9 无金额字段，当前所有单元该值为 None（通过）；本 checker 钉住
    fd-data-quality 式契约「有则必须可解析」，未来金集补金额锚点时，
    坏类型的值会被显式 FAIL 而不是静默混入。
    """
    val = _attr(unit, "amount_yi")
    ok = val is None or (isinstance(val, (int, float)) and not isinstance(val, bool))
    detail = f"amount_yi={val!r} (need number or None)"
    return CheckResult(name="amount-anchor-parseable", passed=ok, detail=detail)


# Registration happens at import time (task 4.5 contract: 模块 import 即注册).
register_checker(KIND, "band-vocabulary", check_band_vocabulary)
register_checker(KIND, "band-direction-consistency", check_band_direction_consistency)
register_checker(KIND, "text-fingerprint-sha256", check_text_fingerprint_sha256)
register_checker(KIND, "text-chars-positive", check_text_chars_positive)
register_checker(KIND, "doc-id-identity", check_doc_id_identity)
register_checker(KIND, "as-of-iso-date", check_as_of_iso_date)
register_checker(KIND, "amount-anchor-parseable", check_amount_anchor_parseable)


# --- data-QA goldset: dashboards finalize 判据改写的首批题目 -----------------


def _judge(name: str) -> Callable[[Callable[[dict, dict], bool]], Callable[[dict, dict], bool]]:
    def deco(fn: Callable[[dict, dict], bool]) -> Callable[[dict, dict], bool]:
        JUDGE_FUNCS[name] = fn
        return fn

    return deco


# judge name -> fn(unit_dict, question_dict) -> bool
JUDGE_FUNCS: dict[str, Callable[[dict, dict], bool]] = {}


@_judge("band-equals")
def judge_band_equals(unit: dict, question: dict) -> bool:
    return _attr(unit, "expected_band") == question.get("expected")


@_judge("direction-equals")
def judge_direction_equals(unit: dict, question: dict) -> bool:
    return _attr(unit, "direction") == question.get("expected")


@_judge("text-fingerprint-format")
def judge_text_fingerprint_format(unit: dict, question: dict) -> bool:
    fp = _attr(unit, "text_sha256")
    return isinstance(fp, str) and bool(_SHA256_RE.fullmatch(fp))


@_judge("text-chars-equals")
def judge_text_chars_equals(unit: dict, question: dict) -> bool:
    return _attr(unit, "text_chars") == question.get("expected")


def _question(qid: str, unit_key: str, field: str, expected: Any, judge: str, text: str) -> dict:
    return {
        "qid": f"qa-{qid}",
        "kind": KIND,
        "namespace": NAMESPACE,
        "unit_key": unit_key,
        "field": field,
        "question": text,
        "expected": expected,
        "judge": judge,
        "origin": "fd-sentiment gold-v9 真值；判据风格改写自 dashboards data_plane.finalize 对账闸门",
    }


def build_data_qa_goldset(records: list[dict]) -> list[dict]:
    """把首批「数据 QA 金集题目」做成结构化 dict 列表。

    ``records`` are the parsed gold items as returned by
    ``packs.finance-data.adapters.read_gold_records``. Questions are derived
    deterministically from the records' own truth (never invented):

    - one band question per distinct ``expected_band`` (first-seen record),
    - one direction question per distinct derived direction,
    - fingerprint-format and text-length questions on the first record.

    Each question targets one fact (``unit_key`` = the unit's external_key),
    carries the expected value, and names its judgment function in
    :data:`JUDGE_FUNCS` — the dashboards finalize discipline (declared value
    must reconcile with actual data) turned into executable QA items.
    """
    if not records:
        raise ValueError("build_data_qa_goldset: records must be non-empty")
    questions: list[dict] = []
    seen_bands: set[str] = set()
    seen_directions: set[str] = set()
    for rec in records:
        doc_id, band = rec["doc_id"], rec["expected_band"]
        if band not in seen_bands:
            seen_bands.add(band)
            questions.append(
                _question(
                    f"band-{band}",
                    doc_id,
                    "expected_band",
                    band,
                    "band-equals",
                    f"样本 {doc_id}（gold-v9 人工标注）的强度档位应为 {band}",
                )
            )
        direction = BAND_TO_DIRECTION.get(band)
        if direction in ALLOWED_DIRECTIONS and direction not in seen_directions:
            seen_directions.add(direction)
            questions.append(
                _question(
                    f"direction-{direction}",
                    doc_id,
                    "direction",
                    direction,
                    "direction-equals",
                    f"样本 {doc_id} 的方向（三分类）应为 {direction}",
                )
            )
    first = records[0]
    questions.append(
        _question(
            f"fingerprint-{first['doc_id']}",
            first["doc_id"],
            "text_sha256",
            first["text_sha256"],
            "text-fingerprint-format",
            f"样本 {first['doc_id']} 的原文指纹应为 64 位小写 sha256"
            f"（登记值 {str(first['text_sha256'])[:12]}…）",
        )
    )
    questions.append(
        _question(
            f"text-chars-{first['doc_id']}",
            first["doc_id"],
            "text_chars",
            first["text_chars"],
            "text-chars-equals",
            f"样本 {first['doc_id']} 的原文长度锚点应为 {first['text_chars']} 字符",
        )
    )
    return questions


def evaluate_goldset(questions: list[dict], units_by_key: dict[str, dict]) -> list[dict]:
    """Run each question's named judge against its unit; return verdicts."""
    verdicts: list[dict] = []
    for q in questions:
        try:
            judge = JUDGE_FUNCS[q["judge"]]
            unit = units_by_key[q["unit_key"]]
        except KeyError as exc:  # unknown judge / missing unit: fail loudly
            raise KeyError(f"data-QA question {q.get('qid')!r}: {exc}") from exc
        verdicts.append({**q, "passed": bool(judge(unit, q))})
    return verdicts
