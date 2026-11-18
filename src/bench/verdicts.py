"""评测结论台账的词汇表与判定（eval-verdict-ledger 内核）。

本模块只管三件事，且三件都是纯判断，不含任何一条产品线的门槛与阈值：

1. **闭集**：四道门、三种结局、被评对象与尺子的种类。写入未知值即拒，不映射到
   "差不多"的那个。六条线各自的门（all-pass 二值、两臂盲评、降幅拦截、分层校准、
   golden 重放、规则求值）今天都存在，缺的只是共同的词汇表。
2. **可比性**：一条结论能不能与它的基线相比，只取决于尺子 digest 是否相等。
   不等 = 口径已迁移，本条按"立基线"处理。任何换算系数都是编造。
3. **判官可信度**：`provisional` 由判官的校准结论行推导，不设配置位——配置说
   "已校准"而实际没有，正是这个机制要消灭的漂移。换 gold 集（digest 变）之后
   旧校准不再算数，判官自动退回未校准，这是期望行为而非故障。

刻意**不**做的事：本模块不知道 `no-worse` 怎么算、`regression` 的阈值是多少。
一旦它开始替各线判定，六条线都要来改这里，这个 change 三个月内会变成需要协调
六个仓的巨型改动。

唯一的写操作是 :func:`register_retest`——它不是判定，而是把「晋升之后要再测一次」
登记成一张既有工单。闭环今天断在末尾：评测→提案→人批→新版本之后就没有下文，
「这个改动到底有没有用」永远没有答案，下一次改动又从头凭感觉来。
"""

from __future__ import annotations

import re
from typing import Any, Callable, Optional

#: 四道门（闭集）。各线保住自己的判定实现，只把结果归到这四个标签之一。
GATES: frozenset[str] = frozenset({"no-worse", "regression", "all-pass", "calibrated"})

#: 三种结局。"inconclusive" 是 NEW 语义：判不出来（样本不足、车道不通、校验器
#: 未执行、超时）必须记它，MUST NOT 折成 fail 或 pass。
OUTCOMES: frozenset[str] = frozenset({"pass", "fail", "inconclusive"})

#: 判官校准结论所用的门。
CALIBRATION_GATE = "calibrated"

#: 校准结论的被评对象种类：判官自身。
JUDGE_SUBJECT_KIND = "judge"

#: 本体模板作为被评对象（change add-layered-ontology-templates）。
#:
#: 种类**不是闭集**——`docs/evaluation-system.md` 把它定义为「任意」，
#: 且生产里已有 `judge`（校准）与 `knowledge-units`（数据检查）两种取值。
#: 把集合关上会打死既有写入路径，而收益只是让一个字符串早一点报错。
#: 这里登记常量是为了让「模板升版门」不必在代码里散落字符串字面量。
TEMPLATE_SUBJECT_KIND = "template"


def verdict_problem(
    *,
    subject_kind: Optional[str],
    subject_key: Optional[str],
    subject_version: Optional[str],
    ruler_kind: Optional[str],
    ruler_key: Optional[str],
    ruler_digest: Optional[str],
    gate: Optional[str],
    outcome: Optional[str],
    baseline_run_id: Optional[int] = None,
    require_identity: bool = True,
) -> Optional[str]:
    """Return a human-readable refusal, or ``None`` when the verdict is well-formed.

    Pure: no DB, no clock, no LLM. Every write path can call it before inserting,
    and every test can call it directly.

    ``require_identity=False`` relaxes the subject/ruler requirement for the
    legacy writers that predate the ledger (a run that is not a verdict at all).
    Those callers still get gate/outcome validation when they supply those
    fields.
    """
    if gate is not None and gate not in GATES:
        return f"gate '{gate}' 不在闭集内：{sorted(GATES)}"
    if outcome is not None and outcome not in OUTCOMES:
        return f"outcome '{outcome}' 不在闭集内：{sorted(OUTCOMES)}"

    def _blank(v: Optional[str]) -> bool:
        return v is None or (isinstance(v, str) and not v.strip())

    if not require_identity:
        return None

    missing = [
        name
        for name, value in (
            ("subject_kind", subject_kind),
            ("subject_key", subject_key),
            ("subject_version", subject_version),
            ("ruler_kind", ruler_kind),
            ("ruler_key", ruler_key),
            ("ruler_digest", ruler_digest),
        )
        if _blank(value)
    ]
    if missing:
        return f"评测结论缺少身份字段：{', '.join(missing)}（版本与 digest 留空会让两次评测无法区分）"

    if baseline_run_id is not None and baseline_run_id <= 0:
        return f"baseline_run_id 非法：{baseline_run_id}"
    return None


def ruler_digest_of(payload: dict) -> str:
    """The ruler's digest, computed by the ONE kernel implementation.

    Delegates to the same canonical-JSON/digest recipe the distribution surface
    uses, so a rubric published through the distribution face and a verdict that
    names that rubric can never disagree about what "the same ruler" means. The
    import is lazy on purpose: ``src.bench.distribution`` pulls in the whole
    publish graph, and this module is imported by low-level write paths.
    """
    from .distribution import canonical_digest

    return canonical_digest(payload)


def judge_subject_key(judge_model: str, prompt_version: Optional[str]) -> str:
    """The stable subject key for "this judge (model + prompt version)".

    Same shape as the calibration meta row's rubric name so the two can be
    cross-read without a mapping table: ``<model>@<prompt_version>``. A missing
    prompt version is written as ``@-`` rather than dropped, because "same model,
    different prompt" IS a different judge.
    """
    return f"{judge_model}@{prompt_version or '-'}"


#: Prefix the calibration writer uses on ``eval_runs.rubric_name``. Kept here so
#: the writer and the derived-trust reader share one literal instead of two.
CALIBRATION_RUBRIC_PREFIX = "judge-calibration:"


def rubric_ruler(
    rubric_name: str, db_path: Any = None, criteria: Optional[list[dict]] = None
) -> dict:
    """The ruler identity for one rubric: ``{kind, key, digest}``.

    The digest is computed over the rubric's *content* (name + ordered criteria
    id/title/guidance) by the shared canonical-digest kernel — the same recipe
    the distribution face uses — so a rubric published there and a verdict that
    names it here can never disagree about "the same ruler". Editing one
    criterion changes the digest, which is exactly the point: the old scores are
    then honestly incomparable rather than silently averaged with the new ones.

    ``criteria`` may be passed pre-loaded (the compare loop evaluates N×M drafts
    against one rubric — re-reading the rubric per draft would be N×M queries
    for a value that cannot change mid-run).

    Raises ``KeyError`` for an unknown rubric and ``ValueError`` for one with no
    criteria — both are caller bugs and must not become an unlabeled verdict.
    """
    if criteria is None:
        from src.eval.rubric import load_criteria

        criteria = load_criteria(
            rubric_name, **({"db_path": db_path} if db_path is not None else {})
        )
    payload = {
        "name": rubric_name,
        "criteria": [
            {"id": c["id"], "title": c["title"], "guidance": c["match_criteria"]}
            for c in criteria
        ],
    }
    return {"kind": "rubric", "key": rubric_name, "digest": ruler_digest_of(payload)}


def text_subject(contract_text: str, *, kind: str = "contract") -> dict:
    """A subject address for an object whose identity IS its text.

    A drafted contract has no version of its own, so its content hash is the
    version — the same contract re-evaluated is the same subject (comparable),
    an edited one is not (`subject_version` moves). Never returns an empty
    version: an unversioned subject cannot support a trend line.
    """
    import hashlib

    body = contract_text if isinstance(contract_text, str) else str(contract_text or "")
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    return {"subject_kind": kind, "subject_key": f"sha256:{digest[:16]}",
            "subject_version": f"sha256:{digest}"}


def score_outcome(all_pass: bool, *, n_total: int, n_invalid: int) -> str:
    """Three-state outcome for an all-pass-style rubric run.

    The interesting case is invalid rows (the judge could not be trusted on that
    criterion). ``all_pass`` already refuses to be True when any row is invalid;
    here the distinction is *how much* went unjudged:

    - **every** row invalid → nothing was actually judged → ``inconclusive``.
      Recording that as ``fail`` would blame the contract for a broken judge.
    - some invalid, rest passed/failed → ``fail`` (there is a real verdict in
      the mix, and it is not all-pass).
    - no invalid rows → ``pass`` / ``fail`` by ``all_pass``.
    """
    if n_total + n_invalid > 0 and n_total == 0:
        return "inconclusive"
    return "pass" if all_pass else "fail"


def gold_set_ruler(records: list[dict], *, key: str = "gold") -> dict:
    """The ruler identity for the gold set a calibration ran against.

    Order-insensitive on purpose: the same pairs listed in a different order are
    the same gold set, and a digest that flipped on reordering would make two
    otherwise-identical calibrations incomparable. Each record is reduced to the
    verdict pair plus its confidence (the only fields the gate reads).
    """
    normalized = sorted(
        (
            (
                bool(r.get("judge_verdict")),
                bool(r.get("human_verdict")),
                None if r.get("confidence") is None else round(float(r["confidence"]), 6),
                r.get("confidence_source"),
            )
            for r in records
        ),
        key=repr,
    )
    payload = {
        "key": key,
        "records": [
            {
                "judge": j,
                "human": h,
                "confidence": c,
                "confidence_source": s,
            }
            for (j, h, c, s) in normalized
        ],
    }
    return {"kind": "gold-set", "key": key, "digest": ruler_digest_of(payload)}


def comparable(
    current_digest: Optional[str], baseline_digest: Optional[str]
) -> dict:
    """Whether ``current`` may be compared against its baseline.

    Three outcomes,三态分开（和结局三态同一个纪律）：

    - ``no-baseline``   — 首次评测，只立基线。**不构成本次改动变好的证据。**
    - ``comparable``    — 同一把尺子，可以算差、可以进同一条趋势。
    - ``ruler-migrated``— digest 不同：口径已迁移，本条按立基线处理，
      不以旧分数作对照，也不发明换算系数。

    A missing digest on either side is treated as ``ruler-migrated``: an unlabeled
    ruler is not evidence of the same ruler.
    """
    if baseline_digest is None:
        return {"status": "no-baseline", "comparable": False}
    if current_digest is None or current_digest != baseline_digest:
        return {"status": "ruler-migrated", "comparable": False}
    return {"status": "comparable", "comparable": True}


def provisional(
    judge_model: Optional[str],
    prompt_version: Optional[str],
    *,
    fetch_latest: Optional[Callable[[str], Optional[dict]]] = None,
    db_path: Any = None,
) -> bool:
    """Is this judge's verdict provisional (i.e. the judge is not calibrated)?

    Derived, never configured. The answer comes from the judge's most recent
    ``calibrated`` verdict: ``outcome == 'pass'`` → calibrated; anything else
    (fail / inconclusive / no record at all) → provisional.

    ``fetch_latest`` is an injected seam for tests; the default reads the ledger
    through :func:`src.eval.store.list_verdicts`. Non-judge channels (no model
    recorded) are not provisional — the flag is about judge trust, and a
    deterministic checker has no judge to distrust.
    """
    if not judge_model:
        return False
    subject_key = judge_subject_key(judge_model, prompt_version)

    if fetch_latest is None:
        def fetch_latest(key: str) -> Optional[dict]:  # type: ignore[misc]
            from src.eval.store import list_verdicts

            rows = list_verdicts(
                subject_kind=JUDGE_SUBJECT_KIND,
                subject_key=key,
                limit=100,
                **({"db_path": db_path} if db_path is not None else {}),
            )
            # list_verdicts is newest-first; the first calibration row wins.
            for row in rows:
                if row.get("gate") == CALIBRATION_GATE:
                    return row
            return None

    latest = fetch_latest(subject_key)
    if latest is None:
        return True
    return latest.get("outcome") != "pass"


#: Work-order target kind for "this version must be re-measured after a change".
RETEST_TARGET_KIND = "verdict-retest"


def register_retest(
    conn: Any,
    *,
    domain_key: str,
    subject_kind: str,
    subject_key: str,
    subject_version: str,
    baseline_run_id: Optional[int],
    created_by: str,
    assignee: str = "kernel:eval",
) -> dict:
    """A promotion/version was shipped: register the round that must re-measure it.

    **It does not run anything.** Evaluation costs real money (judge lane, human
    gold), so an automatic trigger would make one promotion an unbounded cost.
    The same discipline as ``fleet-owner-iteration``'s "notice the new version,
    never migrate": the retest is *registered*, readable, and impossible to
    quietly drop; whether and when to run it stays a human/scheduler decision.

    It is also not allowed to block a promotion: the caller calls this AFTER the
    promotion succeeded, and a failure here must not unwind the promotion. That
    is why this returns the work order instead of raising on a booking problem
    the caller cannot act on mid-promotion — a missing domain is a caller bug
    (raise), a duplicate is not (return the existing one).

    Dedup keys on ``subject_version`` in ``target_key``: shipping the same
    version twice does not book the same retest twice, and a NEW version is a
    new, honestly distinct obligation.
    """
    from . import authoring

    domain = conn.execute(
        "SELECT id FROM domains WHERE key = %s",
        (domain_key,),
    ).fetchone()
    if domain is None:
        raise ValueError(f"domain {domain_key!r} not found")

    target_key = f"{subject_kind}:{subject_key}@{subject_version}"
    existing = conn.execute(
        "SELECT id, assignee, title, detail, target_kind, target_key, status "
        "FROM authoring_tasks WHERE domain_id = %s AND target_kind = %s "
        "  AND target_key = %s AND status <> 'cancelled' "
        "ORDER BY id DESC LIMIT 1",
        (domain["id"], RETEST_TARGET_KIND, target_key),
    ).fetchone()
    if existing is not None:
        return dict(existing)

    baseline_note = (
        f"基线结论 #{baseline_run_id}（复测结论必须引用它；机器可读片段 baseline={baseline_run_id}）"
        if baseline_run_id is not None
        else "改动前没有基线结论：本轮为立基线，不构成进步证据"
    )
    return authoring.authoring_create_task(
        conn,
        domain_id=domain["id"],
        assignee=assignee,
        title=f"复测：{subject_key}@{subject_version[:12]}",
        detail=(
            f"对象 {subject_kind}:{subject_key} 发布了新版本。"
            f"{baseline_note}。本工单只登记义务，不自动执行评测——"
            "评测有成本，何时跑由人来定（沿 fleet-owner-iteration「跟新只提示不迁移」）。"
        ),
        target_kind=RETEST_TARGET_KIND,
        target_key=target_key,
        created_by=created_by,
        assignee_kind="kernel-role",
        assignee_ref="eval",
    )


def ledger_kwargs(
    result: dict,
    *,
    gate: str,
    db_path: Any = None,
    is_provisional: Optional[bool] = None,
) -> dict:
    """``store_result`` keyword args for one evaluation result.

    One place that turns a result dict into ledger columns, so ``src/eval/run.py``
    and ``src/eval/compare.py`` cannot drift from each other or from
    :func:`verdict_problem`.

    Raises ``ValueError`` when the result carries no identity: a verdict with no
    subject/ruler version is exactly the thing this change exists to stop, and
    letting it into the ledger silently would re-create the status quo under a
    new column name. Producers that are not verdicts must not call this.

    ``is_provisional`` lets a caller that writes many verdicts in one run (the
    compare loop: one per draft) resolve the judge's trust ONCE. A judge's
    calibration cannot change mid-run, so re-reading it per draft is pure
    round-trip cost.
    """
    subject = result.get("verdict_subject") or {}
    ruler = result.get("verdict_ruler") or {}
    outcome = result.get("verdict_outcome")
    kwargs = {
        "subject_kind": subject.get("subject_kind"),
        "subject_key": subject.get("subject_key"),
        "subject_version": subject.get("subject_version"),
        "ruler_kind": ruler.get("kind"),
        "ruler_key": ruler.get("key"),
        "ruler_digest": ruler.get("digest"),
        "gate": gate,
        "outcome": outcome,
        "provisional": (
            provisional(result.get("judge_model"), None, db_path=db_path)
            if is_provisional is None
            else is_provisional
        ),
    }
    problem = verdict_problem(
        subject_kind=kwargs["subject_kind"], subject_key=kwargs["subject_key"],
        subject_version=kwargs["subject_version"], ruler_kind=kwargs["ruler_kind"],
        ruler_key=kwargs["ruler_key"], ruler_digest=kwargs["ruler_digest"],
        gate=kwargs["gate"], outcome=kwargs["outcome"],
    )
    if problem is not None:
        raise ValueError(f"拒绝写入评测结论：{problem}")
    return kwargs


def find_open_retest(
    conn: Any, *, domain_key: str, subject_kind: str, subject_key: str
) -> Optional[dict]:
    """The open retest obligation for a subject, if one was booked.

    Used by the retest write path (task 5.2) to pick up the promotion-time
    baseline. Returns the newest non-cancelled, non-done obligation — a done
    retest is history, not a pending candidate.
    """
    domain = conn.execute(
        "SELECT id FROM domains WHERE key = %s", (domain_key,)
    ).fetchone()
    if domain is None:
        return None
    row = conn.execute(
        "SELECT id, assignee, title, detail, target_kind, target_key, status "
        "FROM authoring_tasks WHERE domain_id = %s AND target_kind = %s "
        "  AND target_key LIKE %s AND status IN ('pending','in_progress') "
        "ORDER BY id DESC LIMIT 1",
        (domain["id"], RETEST_TARGET_KIND, f"{subject_kind}:{subject_key}@%"),
    ).fetchone()
    return dict(row) if row else None


def baseline_for_retest(
    conn: Any, *, domain_key: str, subject_kind: str, subject_key: str
) -> Optional[int]:
    """The promotion-time baseline a retest must cite, or ``None``.

    Reads it back off the retest obligation's ``target_key`` (which carries the
    version it was booked for) and the ledger row for that version. Returning
    ``None`` means "no baseline was recorded at promotion time" — the caller
    must then treat the retest as establishing a baseline, never as progress.
    """
    obligation = find_open_retest(
        conn, domain_key=domain_key, subject_kind=subject_kind, subject_key=subject_key
    )
    if obligation is None:
        return None
    # The baseline id rides the detail as a machine-readable fragment, the same
    # convention ``calibration.run_calibration`` uses for ``n=`` /
    # ``monotonic=``: the detail is written for humans, but one anchored token in
    # it is the structured hand-off, so the read side never guesses from prose.
    match = re.search(r"baseline=(\d+)", obligation.get("detail") or "")
    return int(match.group(1)) if match else None
