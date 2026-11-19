"""质量比：六项全部从库里反算，没有一个来自智能体自评（任务 3）。

为什么需要它：四柱判据是"有没有"（单位数 > 0），而智能体最擅长的就是把"有没有"
变成"有"。灌 10,000 条同义条款，缺口一样会消失。所以缺口消失**不等于**质量达标，
这六个比率就是"达标"的可核对口径。

每一项都给出分子、分母与算法，且分母为 0 时回报 ``None`` 而不是 0——"没有可算的
东西"和"算出来是零"是两件事，混在一起就又变成了一句好听的假话。
"""

from __future__ import annotations

from typing import Any, Optional

from . import keys


def _ratio(numerator: int, denominator: int) -> Optional[float]:
    return round(numerator / denominator, 4) if denominator else None


#: 映射算"已复核"的置信下限。低置信的行要人去复核，在复核之前它不能算覆盖率——
#: 否则覆盖率会被"先挂一条 0.3 凑数"刷高，而那正是质量比要防的事。
#: 0.8 与 spec 里的场景一致（confidence=0.4 视为待复核）。
CROSSWALK_CONFIDENCE_THRESHOLD = 0.8


def crosswalk_coverage(
    conn: Any, *, namespace: str,
    threshold: float = CROSSWALK_CONFIDENCE_THRESHOLD,
) -> dict:
    """映射覆盖率：至少有一条已复核 crosswalk 的实体 / 全部活实体。

    **按实体计，不按映射行计。** 给一个实体挂十条映射与挂一条，对该实体的贡献
    应当相同——按行计会让覆盖率被"多挂几条"刷高，而那正是质量比要防的事
    （同 `缺口关闭不等于质量达标`）。

    "已复核"的口径来自 `crosswalk.is_confirmed`：缺 confidence 视为未复核，
    与写入口用的是同一个判据。
    """
    from . import crosswalk as crosswalk_mod

    entities = {
        r["external_key"]
        for r in conn.execute(
            "SELECT external_key FROM knowledge_units "
            "WHERE namespace = %s AND (tags->>'deleted') IS NULL "
            "  AND kind <> 'crosswalk'",
            (namespace,),
        ).fetchall()
    }
    mapped: set[str] = set()
    for row in conn.execute(
        "SELECT external_key, attrs FROM knowledge_units "
        "WHERE namespace = %s AND kind = 'crosswalk' AND (tags->>'deleted') IS NULL",
        (namespace,),
    ).fetchall():
        attrs = row["attrs"] or {}
        if not crosswalk_mod.is_confirmed(attrs, threshold=threshold):
            continue
        mapped.add(row["external_key"])

    covered = entities & mapped
    return _metric(
        _ratio(len(covered), len(entities)),
        len(covered),
        len(entities),
        "至少有一条已复核映射的实体 / 全部活实体（分母按实体，不按映射行数）",
        gaps=sorted(entities - mapped)[:20],
    )


def crosswalk_gaps(
    conn: Any, *, namespace: str, max_age_days: Optional[float] = None
) -> dict:
    """两类映射缺口，分开计数。

    - `stale`：三态证据没齐（或 ok 却没证据）。问的是"这个外部系统还通不通"。
    - `unconfirmed`：缺 confidence。问的是"这条断言有没有人看过"。

    合并成一个数会让值班的人无法决定该做什么——前者要重验对接，后者要找人看。
    """
    from . import crosswalk as crosswalk_mod

    stale, unconfirmed = [], []
    for row in conn.execute(
        "SELECT external_key, attrs FROM knowledge_units "
        "WHERE namespace = %s AND kind = 'crosswalk' AND (tags->>'deleted') IS NULL",
        (namespace,),
    ).fetchall():
        attrs = row["attrs"] or {}
        # Missing *or expired*: "checked once, in March" is not a live connection.
        # ``max_age_days=None`` means the domain declared no expiry — nothing is
        # then treated as stale, which is honest rather than silently assuming.
        missing = crosswalk_mod.effective_missing_states(
            attrs.get("connectivity"), max_age_days=max_age_days
        )
        # Only rows that *claim* connectivity can be stale; a crosswalk with no
        # connectivity block at all is simply unverified, not overdue.
        if attrs.get("connectivity") is not None and missing:
            stale.append({"key": row["external_key"], "missing": missing})
        if not crosswalk_mod.is_confirmed(attrs, threshold=None):
            unconfirmed.append(row["external_key"])
    return {
        "stale": stale,
        "unconfirmed": sorted(unconfirmed),
    }


def _metric(value: Optional[float], numerator: int, denominator: int, how: str,
            gaps: Optional[list] = None) -> dict:
    return {
        "value": value,
        "numerator": numerator,
        "denominator": denominator,
        "how": how,
        **({"gaps": gaps} if gaps else {}),
    }


def grounding(conn: Any, *, namespace: str) -> dict:
    """接地率：有 ``defines`` 关系的概念 / 全部活概念。

    分子按关系的起点算，因为 ``defines`` 的方向就是"概念 → 文档"（方向错了会被
    抽取的关系规则拒掉，所以这里不必再猜方向）。
    """
    concepts = {
        r["external_key"]
        for r in conn.execute(
            "SELECT external_key FROM knowledge_units "
            "WHERE namespace = %s AND kind = 'concept' AND (tags->>'deleted') IS NULL",
            (namespace,),
        ).fetchall()
    }
    grounded = set()
    for row in conn.execute(
        "SELECT external_key FROM knowledge_units "
        "WHERE namespace = %s AND kind = 'defines' AND (tags->>'deleted') IS NULL",
        (namespace,),
    ).fetchall():
        frm, _, rest = (row["external_key"] or "").partition("->")
        if frm in concepts:
            grounded.add(frm)
    return _metric(
        _ratio(len(concepts & grounded), len(concepts)),
        len(concepts & grounded), len(concepts),
        "有 defines 关系的概念 / 全部活概念",
        gaps=sorted(concepts - grounded)[:20],
    )


def evidence(conn: Any, *, namespace: str) -> dict:
    """证据率：带可回源依据的单位 / 全部活单位，并按类型列出缺口。

    可回源的依据只有两种形态：``attrs.evidence``（逐字引用 + 块号）或
    ``attrs.chunk_id``（语料块）。别的一律不算——"有 attrs"不等于"有依据"。
    """
    rows = conn.execute(
        "SELECT kind, COUNT(*) AS n, "
        "       COUNT(*) FILTER (WHERE attrs ? 'evidence' OR attrs ? 'chunk_id') AS with_ev "
        "FROM knowledge_units WHERE namespace = %s AND (tags->>'deleted') IS NULL "
        "GROUP BY kind ORDER BY kind",
        (namespace,),
    ).fetchall()
    total = sum(r["n"] for r in rows)
    with_ev = sum(r["with_ev"] for r in rows)
    gaps = [
        {"kind": r["kind"], "missing": r["n"] - r["with_ev"]}
        for r in rows
        if r["n"] - r["with_ev"] > 0
    ]
    return _metric(
        _ratio(with_ev, total), with_ev, total,
        "带 attrs.evidence 或 attrs.chunk_id 的活单位 / 全部活单位",
        gaps=gaps,
    )


def referential_integrity(conn: Any, *, namespace: str) -> dict:
    """参照完整：两端都在活单位上的关系 / 全部活关系。

    关系键的形状是 ``<from>-><kind>:<to>``；任何一端不存在就是悬空——悬空关系
    在图上表现为一个不存在的节点，比"少一条关系"更误导人。
    """
    live = {
        r["external_key"]
        for r in conn.execute(
            "SELECT external_key FROM knowledge_units "
            "WHERE namespace = %s AND (tags->>'deleted') IS NULL",
            (namespace,),
        ).fetchall()
    }
    rels = [
        r["external_key"]
        for r in conn.execute(
            "SELECT external_key FROM knowledge_units "
            "WHERE namespace = %s AND (tags->>'deleted') IS NULL "
            # A crosswalk is NOT an edge: it asserts a mapping *about* an
            # entity and must never be counted as a relationship. Its keys
            # usually lack "->" so the LIKE below skips them by luck — but
            # "by luck" is not a rule, and a key that happened to contain an
            # arrow would silently pollute this ratio.
            "  AND kind <> 'crosswalk' "
            "AND external_key LIKE '%%->%%'",
            (namespace,),
        ).fetchall()
    ]
    dangling = []
    for rel in rels:
        frm, _, rest = (rel or "").partition("->")
        to = rest.split(":", 1)[1] if ":" in rest else ""
        if frm not in live or to not in live:
            dangling.append(rel)
    return _metric(
        _ratio(len(rels) - len(dangling), len(rels)),
        len(rels) - len(dangling), len(rels),
        "两端都是活单位的关系 / 全部活关系",
        gaps=dangling[:20],
    )


def review_lag(conn: Any, *, domain_key: str, threshold_hours: float = 24.0) -> dict:
    """评审时滞：待确认提案的条数、平均与最老年龄；超阈值即为缺口。

    这是唯一一项不需要语料的比率——它衡量的是"人跟不跟得上"，而团队一上线，
    先饱和的一定是这里。
    """
    row = conn.execute(
        "SELECT COUNT(*) AS n, "
        "       COALESCE(AVG(EXTRACT(EPOCH FROM (now() - submitted_at)) / 3600), 0) AS avg_h, "
        "       COALESCE(MAX(EXTRACT(EPOCH FROM (now() - submitted_at)) / 3600), 0) AS max_h "
        "FROM domain_proposals WHERE domain_id = "
        "(SELECT id FROM domains WHERE key = %s) AND state = 'pending'",
        (domain_key,),
    ).fetchone()
    n, avg_h, max_h = int(row["n"]), float(row["avg_h"]), float(row["max_h"])
    return {
        "value": round(avg_h, 2) if n else None,
        "numerator": n,
        "denominator": None,
        "how": "待确认提案的平均年龄（小时）；最老一条另列",
        "pending": n,
        "oldest_hours": round(max_h, 2) if n else None,
        "threshold_hours": threshold_hours,
        "over_threshold": bool(n and max_h > threshold_hours),
    }


def key_hygiene(conn: Any, *, domain_key: str, namespace: str) -> dict:
    """键卫生：能被本域规则继续归名的活键 / 全部活键（越低越好）。

    归名现在会发生在写入口，但历史数据可能仍留着未归名形态；这项比率让"还有多少
    脏键"可数。域未注册规则时回报 ``None`` 并在 ``how`` 里说明，不假装是 0。
    """
    rules = keys.rules_for(domain_key)
    live = [
        r["external_key"]
        for r in conn.execute(
            "SELECT external_key FROM knowledge_units "
            "WHERE namespace = %s AND (tags->>'deleted') IS NULL",
            (namespace,),
        ).fetchall()
    ]
    if not rules or not live:
        return {
            "value": None, "numerator": 0, "denominator": len(live),
            "how": ("该域未注册归名规则（不归名，安全默认）" if not rules
                    else "没有活单位"),
        }
    foldable = 0
    examples = []
    for key in live:
        folded, _applied = keys.fold(key, rules)
        if (folded or "").strip() and folded != key:
            foldable += 1
            if len(examples) < 10:
                examples.append({"key": key, "folds_to": folded})
    return _metric(
        _ratio(foldable, len(live)), foldable, len(live),
        "还能被本域规则继续归名的活键 / 全部活键（应为 0）",
        gaps=examples,
    )


def judge_health(*, probed: Optional[dict] = None) -> dict:
    """判官通道健康：只认实探结果。

    刻意不从配置或历史成功推断——配置齐全但上游 400 的那次事故，就是"看起来健康"
    的典型。没有实探就报"未探"，不报通过。
    """
    if not probed:
        return {"value": None, "numerator": 0, "denominator": 0,
                "how": "本轮未实探（配置齐全不等于可用）", "probed": False}
    ok = bool(probed.get("ok"))
    return {
        "value": 1.0 if ok else 0.0,
        "numerator": 1 if ok else 0,
        "denominator": 1,
        "how": "一次真实调用的结果",
        "probed": True,
        "status": probed.get("status"),
        "detail": (probed.get("detail") or "")[:200],
    }


def all_metrics(
    conn: Any, *, domain_key: str, namespace: Optional[str] = None,
    probed: Optional[dict] = None, review_threshold_hours: float = 24.0,
    template_readiness: Optional[dict] = None,
) -> dict:
    """六项一起算。``namespace`` 缺省等于域 key（根系域的路径就是 key）。

    ``template_readiness`` 是第七项，但它不由本模块计算——可评性问的是
    "锚定模板声明的尺子解析得到吗"，那是模板与 rubric 之间的查询，不是语料
    统计。调用方把 ``template_readiness.readiness()`` 的结果传进来，本函数
    只负责让它与其余六项同形呈现。
    """
    ns = namespace or domain_key
    out = {
        "grounding": grounding(conn, namespace=ns),
        "evidence": evidence(conn, namespace=ns),
        "referential": referential_integrity(conn, namespace=ns),
        "review_lag": review_lag(conn, domain_key=domain_key,
                                 threshold_hours=review_threshold_hours),
        "key_hygiene": key_hygiene(conn, domain_key=domain_key, namespace=ns),
        "judge": judge_health(probed=probed),
        # 映射覆盖率：第八项。同模板可评性一样，它统计的对象不是语料而是
        # "本体与外部世界的缝"，所以单独算、单独呈现。
        "crosswalk": crosswalk_coverage(conn, namespace=ns),
    }
    if template_readiness is not None:
        out["template"] = _template_metric(template_readiness)
    return out


def _template_metric(readiness: dict) -> dict:
    """模板可评性：已解析 / 已声明。

    分母为 0 时报 ``value=None`` 而不是 0.0 或 1.0——"一条尺子都没声明"
    与"声明的全解析不到"是两件事，前者连比都没得比，把两者渲染成同一个百分比
    会让人以为模板没问题。
    """
    declared = int(readiness.get("declared") or 0)
    resolved = int(readiness.get("resolved") or 0)
    metric = _metric(
        _ratio(resolved, declared),
        resolved,
        declared,
        "锚定模板声明的尺子中可解析的比例（分母 0 = 模板未声明尺子）",
        gaps=list(readiness.get("missing") or [])[:20],
    )
    metric["undeclared"] = declared == 0
    return metric


# ── 阈值与方向（策略只写在这里，派单与矩阵都读它）────────────────────────────

#: 每项比率是"越高越好"还是"越低越好"。方向写错，减分就会变成加分。
HIGHER_IS_BETTER: dict[str, bool] = {
    "grounding": True,
    "evidence": True,
    "referential": True,
    "key_hygiene": False,   # 还能继续归名的键越少越好
    "crosswalk": True,      # 覆盖率越高越好
}

#: 达标线。这些值是策略，不是测量结果——所以集中一处，谁要改都得看见彼此。
QUALITY_THRESHOLDS: dict[str, float] = {
    "grounding": 0.5,      # 一半以上概念悬空 = 有量无骨
    "evidence": 0.9,       # 依据是复核唯一抓手
    "referential": 1.0,    # 悬空关系零容忍
    "key_hygiene": 0.0,    # 能归名的键就该已归名
    # 一半以上实体没有任何已复核映射 = 本体与外部世界没有缝。刻意不设 1.0：
    # 不是每个实体都值得映射，逼到 100% 只会让人挂低质量的行来凑数。
    "crosswalk": 0.5,
}

#: 评审时滞阈值（小时）；另算，因为它衡量的是"人跟不跟得上"，不是内容质量。
REVIEW_LAG_HOURS = 24.0


def below_threshold(name: str, metric: dict) -> Optional[bool]:
    """这一项是否不达标。``None`` = 无物可算（不算不达标，也不算达标）。"""
    value = metric.get("value")
    if value is None:
        return None
    floor = QUALITY_THRESHOLDS.get(name)
    if floor is None:
        return None
    return value < floor if HIGHER_IS_BETTER[name] else value > floor
