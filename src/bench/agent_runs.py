"""运行台账：每轮智能体运行的账本（change ``add-domain-agent-team``，任务 2）。

要回答的不是"智能体说了什么"，而是三个可核对的事实：**哪一轮、跑到哪、成没成**。
所以这里只存可复算的东西——输入摘要、计数、剩余量、产物引用——不存推理文本：
一旦存了，后来者就会把它当证据，而推理不是证据。

四态与它们的后果（这是模块存在的全部理由）：

```
 ok       产出可用            进复核
 thin     有产出但薄          升级给人，**不重跑**（换量只会把噪声放大）
 failed   前提缺失/闸门拒绝    报告原话，不重试
 stopped  不变量触发（不收敛）  停下等人，不带病继续
```

只有"读类失败且无副作用"允许自动重试——由 :func:`may_retry` 判定，调用方不得
自己发明更宽松的口径。
"""

from __future__ import annotations

from typing import Any, Optional

from . import agent_ids, submitters, workspaces

#: 结局词表。``running`` 只是"还没收尾"，不是结论。
OUTCOMES = ("running", "ok", "thin", "failed", "stopped")

#: 允许自动重试的结局：只有 failed，且仅限无副作用的读类。
_RETRYABLE = ("failed",)


def may_retry(outcome: str, *, read_only: bool) -> bool:
    """这一轮能不能自动重来一次。

    写类永不自动重试：写了一半再重跑，是最难解释的一种状态；``thin`` 也不重试，
    因为"料不够"不是重跑能解决的，加量只会放大人眼要看的噪声。
    """
    return outcome in _RETRYABLE and read_only


def should_stop(previous_remaining: Optional[int], current_remaining: Optional[int]) -> bool:
    """分批任务的进度不变量：剩余量不下降就停。

    实测过两次"批次永不收敛"（每次都重写同一批、remaining 永远不变），所以这条
    不变量要能被机械判定，而不是靠人盯着看。
    """
    if previous_remaining is None or current_remaining is None:
        return False
    return current_remaining >= previous_remaining


def start(
    conn: Any,
    *,
    role: str,
    domain_key: str,
    task_id: Optional[int] = None,
    run_key: Optional[str] = None,
    input_digest: Optional[str] = None,
) -> dict:
    """开一轮。``role`` 必须是智能体身份（人不需要台账，人的轨迹在事件流里）。"""
    if not agent_ids.is_agent(role):
        raise ValueError(
            "运行台账只记智能体的轮次；人类操作留在 authoring_events 里"
        )
    if workspaces.get_domain(conn, domain_key=domain_key) is None:
        raise ValueError(f"domain {domain_key!r} not found")
    row = conn.execute(
        "INSERT INTO domain_agent_runs "
        "(role, domain_key, task_id, run_key, input_digest, origin) "
        "VALUES (%s, %s, %s, %s, %s, 'kernel') "
        "RETURNING id, role, domain_key, task_id, run_key, outcome, input_digest, "
        "          counts, remaining, artifact_refs, detail, started_at, ended_at, "
        "          origin, runner_ref",
        (role, domain_key, task_id, run_key, input_digest),
    ).fetchone()
    conn.commit()
    return dict(row)


def finish(
    conn: Any,
    *,
    run_id: int,
    outcome: str,
    counts: Optional[dict] = None,
    remaining: Optional[int] = None,
    artifact_refs: Optional[list] = None,
    detail: Optional[str] = None,
    verdict_run_ids: Optional[list] = None,
) -> dict:
    """收尾一轮，写入结局与计数，以及本轮产出的评测结论 id。

    ``verdict_run_ids`` 缺省 = 本轮没有产出结论，落空数组而不是猜一个「最近的」
    ——links-to-nothing 和 links-to-the-wrong-thing 是两种不同的谎，后者更坏。

    重复收尾是幂等的：已结束的轮次不会被改写（否则"结局"就不可信了）。
    """
    if outcome not in OUTCOMES or outcome == "running":
        raise ValueError(
            f"结局必须是 {[o for o in OUTCOMES if o != 'running']} 之一（running 只是未收尾）"
        )
    current = get(conn, run_id=run_id)
    if current is None:
        raise ValueError(f"run {run_id} not found")
    if current["outcome"] != "running":
        return current  # 已收尾：不改写
    row = conn.execute(
        "UPDATE domain_agent_runs SET outcome = %s, counts = %s::jsonb, remaining = %s, "
        "artifact_refs = %s::jsonb, detail = %s, verdict_run_ids = %s::jsonb, "
        "ended_at = now() "
        "WHERE id = %s AND outcome = 'running' "
        "RETURNING id, role, domain_key, task_id, run_key, outcome, input_digest, "
        "          counts, remaining, artifact_refs, detail, started_at, ended_at, "
        "          origin, runner_ref, verdict_run_ids",
        (
            outcome,
            _json(counts or {}),
            remaining,
            _json(artifact_refs or []),
            detail,
            _json(verdict_run_ids or []),
            run_id,
        ),
    ).fetchone()
    conn.commit()
    return dict(row)


def get(conn: Any, *, run_id: int) -> Optional[dict]:
    row = conn.execute(
        "SELECT id, role, domain_key, task_id, run_key, outcome, input_digest, "
        "       counts, remaining, artifact_refs, detail, started_at, ended_at, "
        "       origin, runner_ref, verdict_run_ids "
        "FROM domain_agent_runs WHERE id = %s",
        (run_id,),
    ).fetchone()
    return dict(row) if row else None


def list_runs(
    conn: Any,
    *,
    domain_key: str,
    role: Optional[str] = None,
    origin: Optional[str] = None,
    runner_ref: Optional[str] = None,
    limit: int = 50,
) -> list[dict]:
    """The domain's ledger, newest first.

    ``origin`` filters kernel rounds from fleet write-backs; ``runner_ref`` answers
    the submitter's own question ("did this round of mine land?"). Neither takes
    part in ordering — the ledger is one timeline, and a fleet that sorted last
    because of its source would be invisible exactly when it is late.
    """
    sql = (
        "SELECT id, role, domain_key, task_id, run_key, outcome, input_digest, "
        "       counts, remaining, artifact_refs, detail, started_at, ended_at, "
        "       origin, runner_ref, verdict_run_ids "
        "FROM domain_agent_runs WHERE domain_key = %s"
    )
    params: list[Any] = [domain_key]
    if role:
        sql += " AND role = %s"
        params.append(role)
    if origin:
        sql += " AND origin = %s"
        params.append(origin)
    if runner_ref:
        sql += " AND runner_ref = %s"
        params.append(runner_ref)
    sql += " ORDER BY started_at DESC LIMIT %s"
    params.append(max(1, min(int(limit or 50), 500)))
    return [dict(r) for r in conn.execute(sql, tuple(params)).fetchall()]


def record_external_run(
    conn: Any,
    *,
    runner_ref: str,
    role: str,
    domain_key: str,
    outcome: str,
    counts: Optional[dict] = None,
    remaining: Optional[int] = None,
    artifact_refs: Optional[list] = None,
    detail: Optional[str] = None,
    task_id: Optional[int] = None,
    verdict_run_ids: Optional[list] = None,
) -> tuple[dict, bool]:
    """Record a fleet round's outcome — ``(run, created)``.

    Idempotent on ``runner_ref``: a replay returns the existing row untouched
    and reports ``created=False``. The check is an *existence lookup*, not a
    unique constraint — ``run_key`` is legitimately null for some kernel rounds,
    and nulls do not collide in a unique index, so a constraint here would look
    like protection without being any.

    ``origin`` is always ``fleet``; ``run_key`` mirrors ``runner_ref`` so the
    ledger answers "which fleet round was this" from one column as well.
    """
    if outcome not in OUTCOMES or outcome == "running":
        raise ValueError(
            f"结局必须是 {[o for o in OUTCOMES if o != 'running']} 之一（running 只是未收尾）"
        )
    ref = (runner_ref or "").strip()
    if not ref:
        raise ValueError("runner_ref is required")
    if submitters.classify_source(ref)[0] != submitters.PREFIX_FLEET:
        raise ValueError(
            "runner_ref 必须形如 "
            f"{submitters.SHAPES[submitters.PREFIX_FLEET]}#<round>；got {runner_ref!r}"
        )
    if workspaces.get_domain(conn, domain_key=domain_key) is None:
        raise ValueError(f"domain {domain_key!r} not found")

    existing = get_by_runner_ref(conn, runner_ref=ref)
    if existing is not None:
        return existing, False

    # 存在性检查有 TOCTOU 窗口：两个重试可以同时查不到、同时插入。部分唯一索引
    # （`domain_agent_runs_runner_ref_key`，只覆盖 runner_ref 非空的行）是兜底，
    # 撞上它说明这一轮确实已经被别人写进去了——回读那一行、照旧报「已存在」，
    # 而不是把唯一性冲突抛给调用方当故障去重试。
    try:
        row = conn.execute(
            "INSERT INTO domain_agent_runs "
            "(role, domain_key, task_id, run_key, outcome, counts, remaining, "
            " artifact_refs, detail, origin, runner_ref, verdict_run_ids, ended_at) "
            "VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s::jsonb, %s, 'fleet', %s, "
            "        %s::jsonb, now()) "
            "RETURNING id, role, domain_key, task_id, run_key, outcome, input_digest, "
            "          counts, remaining, artifact_refs, detail, started_at, ended_at, "
            "          origin, runner_ref, verdict_run_ids",
            (
                role,
                domain_key,
                task_id,
                ref,
                outcome,
                _json(counts or {}),
                remaining,
                _json(artifact_refs or []),
                detail,
                ref,
                _json(verdict_run_ids or []),
            ),
        ).fetchone()
        conn.commit()
    except Exception as exc:  # noqa: BLE001 - 只兜唯一性冲突，其余照抛
        if type(exc).__name__ != "UniqueViolation":
            raise
        try:
            conn.rollback()
        except Exception:  # noqa: BLE001 - 回滚失败也不该掩盖原始冲突
            pass
        winner = get_by_runner_ref(conn, runner_ref=ref)
        if winner is None:  # 理论上不可达：冲突了却查不到行，说明不是这条索引
            raise
        return winner, False
    return dict(row), True


def get_by_runner_ref(conn: Any, *, runner_ref: str) -> Optional[dict]:
    """The round already recorded under ``runner_ref``, if any."""
    row = conn.execute(
        "SELECT id, role, domain_key, task_id, run_key, outcome, input_digest, "
        "       counts, remaining, artifact_refs, detail, started_at, ended_at, "
        "       origin, runner_ref, verdict_run_ids "
        "FROM domain_agent_runs WHERE runner_ref = %s ORDER BY id DESC LIMIT 1",
        ((runner_ref or "").strip(),),
    ).fetchone()
    return dict(row) if row else None


def summary(conn: Any, *, domain_key: str) -> dict:
    """按结局分组 + 最近一轮：值班长一眼要看的两件事。"""
    rows = conn.execute(
        "SELECT outcome, COUNT(*) AS n FROM domain_agent_runs WHERE domain_key = %s "
        "GROUP BY outcome",
        (domain_key,),
    ).fetchall()
    by_outcome = {r["outcome"]: r["n"] for r in rows}
    last = conn.execute(
        "SELECT id, role, outcome, started_at, ended_at, detail FROM domain_agent_runs "
        "WHERE domain_key = %s ORDER BY started_at DESC LIMIT 1",
        (domain_key,),
    ).fetchone()
    return {"by_outcome": by_outcome, "last": dict(last) if last else None}


def verdicts_for_run(conn: Any, *, run_id: int, db_path: Any = None) -> list[dict]:
    """The verdict rows this round produced (add-eval-verdict-ledger 4.2).

    往返的另一半：本函数读出本轮指向的结论，:func:`run_for_verdict` 读出产出某条
    结论的那一轮。两处都只按 id 查，不复制对方的内容。

    空列表意味着「本轮没产出结论」——这是实话，不是故障。指向的结论行若已被清理，
    该条如实少一条而**不是**补一个占位：编造一条结论比少一条更难发现。
    """
    run = get(conn, run_id=run_id)
    if run is None:
        return []
    ids = run.get("verdict_run_ids") or []
    if not ids:
        return []
    from src.eval.store import get_run

    out = []
    for verdict_id in ids:
        try:
            out.append(get_run(int(verdict_id), db_path=conn))
        except KeyError:
            continue  # 结论行已不存在：如实少一条，不编造占位
    return out


def run_for_verdict(conn: Any, *, verdict_run_id: int) -> Optional[dict]:
    """The round that produced a given verdict, or None (4.2, reverse direction).

    ``None`` is honest here: a verdict written by a path that is not a ledger
    round (a CLI one-shot, a compare cell) has no round to point at, and
    inventing "the most recent round" would attach evidence to the wrong work.
    """
    row = conn.execute(
        "SELECT id, role, domain_key, task_id, run_key, outcome, input_digest, "
        "       counts, remaining, artifact_refs, detail, started_at, ended_at, "
        "       origin, runner_ref, verdict_run_ids "
        "FROM domain_agent_runs "
        "WHERE verdict_run_ids @> %s::jsonb ORDER BY id DESC LIMIT 1",
        (_json([int(verdict_run_id)]),),
    ).fetchone()
    return dict(row) if row else None


def _json(value: Any) -> str:
    import json

    return json.dumps(value, ensure_ascii=False)
