"""参数化跑分器（迁入自 fd-text-core）：nDCG / hit@k / MRR + 双指纹 + 跨次回归判定。

真源（只读）：``/Users/chengsishi/finddata/fd-text-core/fd_text_core/eval/runner.py``
与 ``.../eval/store.py``（落库腿，表 DDL 见 migrations/versions/0006_eval_runs.py、
0008_eval_ndcg_variant.py）。迁入即单一真源；等价双跑（tests/test_retrieval_eval.py）
确认零漂移前，原仓尺子仍是行为基准——口径同 finance-data 包「迁入 ≠ 取代」。

指标全部是纯函数：给定 ranked 结果 + 分级相关性 qrels 即出分，零网络、零
embedding、零 LLM。与原件的唯一结构性差异：原跑分器内部硬调
``querylib.hybrid_search``（度量与被度量同路径，原仓 design D5）；本平台没有
那套检索引擎，故 **检索后端以 ``search`` 回调注入**——注入点即原调用点，
跑分/聚合/指纹/对比逻辑逐行照迁、不改语义。注入的必须是「被测检索的真实
输出」，否则「检索变好」与「stub 变好」分不清（同 design D5 的精神）。

双指纹（design D3，照实迁入）：
  · 数据集指纹 = 标注集文件字节的 sha256 前 16 位（adapters.compute_fingerprint）
  · 配置指纹   = 影响检索结果的引擎侧配置（embedding 模型/维度/RRF 参数与环境
    变量 + 垂域切块策略描述符）的 sha256 前 16 位。只存分数无法回答「这次比
    上次低，是检索变差还是换了模型/切块策略」；两指纹（加 k 与 variant）相同
    才判回归，任一不同即「不可直接比较」，不静默比较两个不可比数字。
  原仓配置指纹读其 verticals registry；本平台没有该注册表，故策略段以
  ``vertical`` 描述符注入（None = 原件的 KeyError 分支 ``strategy=<unregistered>``）。

落库腿（trend）照 ``src/bench/calibration.run_calibration`` 的风格：一次跑分 =
一行 ``eval_runs``（``channel='data'``（确定性通道）、``unit_kind='retrieval'``）
+ 每通道一条 criteria 诊断行；双指纹、k、variant、n 以机器可读片段嵌入
summary，读回腿（:func:`latest_retrieval_run` / :func:`previous_from_run`）把它们
还原成原件 ``compare_with_previous`` 消费的 previous 行形态——趋势判定用的
仍是同一个纯函数，不是复刻。
"""
from __future__ import annotations

import hashlib
import os
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from src.eval.store import store_result
from src.settings import DEFAULT_DB

CHANNELS = ("keyword", "vector", "hybrid")

#: 落库腿的 rubric 前缀（eval_suites 声明的 suite id；趋势按
#: ``rubric_name = f"{RUBRIC_PREFIX}:{domain}"`` 查询）
RUBRIC_PREFIX = "text-retrieval-ndcg"


def ndcg_at_k(ranked_ids: list, grades: tuple, k: int) -> float:
    """nDCG@k（分级相关性）。

    DCG  = Σ (2^g_i - 1) / log2(i + 1)，i 从 1 起；
    IDCG = 标注等级降序铺满 k 的理想值；nDCG = DCG / IDCG。

    **按 document_id 去重保首现**：检索返回切块（chunk），同一文档可有多个
    切块进前 k；不去重则该文档的增益被重复计入，nDCG 会超过 1（实现期实测
    抓到：gov hybrid 报 2.1005——nDCG 的取值域 [0,1] 是硬约束，超界即算错）。
    文档的「排名」= 其任一相关切块的最优位次，与 hit/MRR 的判定口径一致。

    IDCG=0 只可能发生在标注不含任何相关文档时——契约强制每条至少一篇
    grade=2，故此处防御性返回 0.0（宁可显 0 也不抛，指标层不制造中断）。
    """
    gmap = {g.doc_id: g.grade for g in grades}
    seen: set = set()
    ranked_docs: list = []
    for did in ranked_ids:
        if did not in seen:
            seen.add(did)
            ranked_docs.append(did)

    dcg = 0.0
    for i, did in enumerate(ranked_docs[:k], start=1):
        g = gmap.get(did, 0)
        if g:
            dcg += (2**g - 1) / _log2(i + 1)
    ideal = sorted((g.grade for g in grades), reverse=True)[:k]
    idcg = sum((2**g - 1) / _log2(i + 1) for i, g in enumerate(ideal, start=1))
    if idcg <= 0:
        return 0.0
    return dcg / idcg


def _log2(x: float) -> float:
    from math import log2

    return log2(x)


@dataclass
class EvalReport:
    """一次跑分的完整结果（字段与原件逐一对应）。"""

    domain: str
    k: int
    dataset_fingerprint: str
    config_fingerprint: str
    judgment_strength: str
    how_targets_chosen: str
    n_queries: int
    summary: dict = field(default_factory=dict)  # channel -> {hits, mrr, ndcg, hit@k}
    by_intent: dict = field(default_factory=dict)
    rows: list = field(default_factory=list)
    degraded: list = field(default_factory=list)
    missing_expects: list = field(default_factory=list)
    variant: str = "default"

    @property
    def saturated(self) -> bool:
        """本集对重排类改进是否有区分度。

        判据：全部查询的最高等级文档在三通道（至少 hybrid）皆居首位
        ⇔ MRR 达到理论上限。此时集合对重排无区分度——如实标注，**但不判
        FAIL**：回归守门集就该饱和（目标必须居首），把它标成失败会诱导人
        为数字好看而弱化守门集。
        """
        if self.degraded:
            return False
        hyb = self.summary.get("hybrid", {})
        return bool(
            self.n_queries > 0
            and hyb.get("hits", 0) == self.n_queries
            and hyb.get("mrr", 0.0) >= 1.0
        )

    @property
    def hybrid_not_worse(self) -> Optional[bool]:
        """混合通道不低于任一单通道（spec 的验收线）。缺向量时返回 None。"""
        if self.degraded:
            return None
        hyb = self.summary.get("hybrid", {})
        for ch in ("keyword", "vector"):
            other = self.summary.get(ch, {})
            if hyb.get("hits", 0) < other.get("hits", 0):
                return False
            if hyb.get("mrr", 0.0) < other.get("mrr", 0.0):
                return False
        return True

    def to_dict(self) -> dict:
        return {
            "domain": self.domain,
            "k": self.k,
            "variant": self.variant,
            "dataset_fingerprint": self.dataset_fingerprint,
            "config_fingerprint": self.config_fingerprint,
            "judgment_strength": self.judgment_strength,
            "how_targets_chosen": self.how_targets_chosen,
            "n_queries": self.n_queries,
            "summary": self.summary,
            "by_intent": self.by_intent,
            "rows": self.rows,
            "degraded": self.degraded,
            "missing_expects": self.missing_expects,
            "hybrid_not_worse": self.hybrid_not_worse,
            "saturated": self.saturated,
        }


def compute_config_fingerprint(
    domain: str,
    *,
    vertical: Any = None,
    env: Optional[dict] = None,
) -> str:
    """配置指纹：影响检索结果的引擎侧配置（与原件逐段同格式）。

    ``vertical`` 为垂域描述符（需带 .strategy/.cjk/.t2s/.tsv_config，对应原件
    registry.get(domain) 的返回物）；None = 原件查不到垂域的 KeyError 分支
    （``strategy=<unregistered>``）。``env`` 缺省 os.environ——指纹读的是
    进程真实配置，两边同进程即可逐值对比。
    """
    env = os.environ if env is None else env
    parts = [
        f"embedding_model={env.get('FDTEXT_EMBEDDING_MODEL', 'Qwen/Qwen3-Embedding-8B')}",
        f"embedding_dim={env.get('FDTEXT_EMBEDDING_DIM', '1024')}",
        f"provider_only={env.get('FDTEXT_EMBEDDING_PROVIDER_ONLY', '')}",
        f"rrf_k={env.get('FDTEXT_RRF_K', '60')}",
        # 融合权重入指纹：改权重必须与「检索退化」可区分（change
        # fusion-weight-vector-tilt 的 D2——否则同一指纹下指标变了无法归因）。
        f"rrf_w_keyword={env.get('FDTEXT_RRF_W_KEYWORD', '1.0')}",
        f"rrf_w_vec={env.get('FDTEXT_RRF_W_VEC', '2.0')}",
    ]
    if vertical is None:
        parts.append("strategy=<unregistered>")
    else:
        strat = vertical.strategy
        parts += [
            f"strategy={type(strat).__name__}",
            f"strategy_params={sorted((k, str(x)) for k, x in vars(strat).items() if not k.startswith('_'))}",
            f"cjk={vertical.cjk}",
            f"t2s={vertical.t2s}",
            f"tsv_config={vertical.tsv_config}",
        ]
    joined = "|".join(parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]


def run_eval(
    dataset,
    *,
    search: Callable,
    k: int = 10,
    channels: tuple = CHANNELS,
    embedder: Any = None,
    check_expects: Optional[Callable] = None,
    vertical: Any = None,
    env: Optional[dict] = None,
) -> EvalReport:
    """对一个标注集跑分。检索调用只经注入的 ``search``，本函数不碰库表与 SQL。

    ``search`` 的调用形态与原件对 ``querylib.hybrid_search`` 完全一致：
    ``search(domain, query, embedder=..., limit=k, channels=<单通道名>)`` 返回
    ``{"results": [{"document_id": ...}, ...], "degraded": [...]}``。
    ``check_expects`` 由调用方注入（原件为 store.check_expects_exist，需 DB；
    本平台侧对应 data_checks 通道的在库校验）：默认 None 即跳过在库校验，
    使本函数保持零 DB 依赖、可离线跑。缺失逐条报告而非静默当作未命中——
    语料重建会让 expect_doc_id 失效，静默处理会把「标注失效」伪装成
    「检索变差」。
    """
    if search is None:
        raise ValueError(
            "run_eval 需要注入 search 后端（度量与被度量必须同路径，原件 design D5）；"
            "本包不自带检索引擎，也不 import fd-text-core"
        )

    cfg_fp = compute_config_fingerprint(dataset.domain, vertical=vertical, env=env)
    report = EvalReport(
        domain=dataset.domain,
        k=k,
        dataset_fingerprint=dataset.fingerprint,
        config_fingerprint=cfg_fp,
        judgment_strength=dataset.judgment_strength,
        how_targets_chosen=dataset.how_targets_chosen,
        n_queries=len(dataset.queries),
        missing_expects=(check_expects(dataset) if check_expects else []),
        variant=dataset.variant,
    )

    rows: list = []
    for q in dataset.queries:
        top_ids = q.max_grade_ids()  # 最高等级（分级下可并列）
        row: dict = {
            "q": q.q,
            "intent": q.intent,
            # 二值形态保留原字段名（既有报告消费方的兼容面）
            "expect": q.expect_doc_id,
            "expect_ids": list(top_ids),
            "graded": q.graded,
        }
        for ch in channels:
            res = search(dataset.domain, q.q, embedder=embedder, limit=k, channels=ch)
            for d in res.get("degraded") or []:
                if d not in report.degraded:
                    report.degraded.append(d)
            ids = [x.get("document_id") for x in res["results"]]
            # 命中判据：任一最高等级文档进前 k；排名取其中最优者
            ranks = [ids.index(t) + 1 for t in top_ids if t in ids]
            row[ch] = min(ranks) if ranks else None
            row[f"{ch}_ndcg"] = round(ndcg_at_k(ids, q.grades(), k), 4)
        rows.append(row)
    report.rows = rows

    summary: dict = {}
    for ch in channels:
        ranks = [r[ch] for r in rows if r.get(ch)]
        ndcgs = [r[f"{ch}_ndcg"] for r in rows]
        summary[ch] = {
            "hits": len(ranks),
            "hit@k": f"{len(ranks)}/{len(rows)}",
            "mrr": round(sum(1.0 / r for r in ranks) / max(1, len(rows)), 4),
            "ndcg": round(sum(ndcgs) / max(1, len(ndcgs)), 4),
        }
    report.summary = summary

    by_intent: dict = defaultdict(lambda: {"total": 0, "hits": {ch: 0 for ch in channels}})
    for r in rows:
        b = by_intent[r["intent"]]
        b["total"] += 1
        for ch in channels:
            if r.get(ch):
                b["hits"][ch] += 1
    report.by_intent = {k2: v for k2, v in by_intent.items()}
    return report


def compare_with_previous(report: EvalReport, previous: Optional[dict]) -> dict:
    """本次 vs 上次的对比判定（纯函数，不碰库——由调用方取出 previous 行传入）。

    两指纹都相同才判回归；任一不同则明确「不可直接比较」并列出变化项——
    静默比较两个不可比数字会让趋势图误导人（design D3）。
    """
    if not previous:
        return {"status": "no_baseline", "message": "无历史运行，本次为基线"}

    changed = []
    if previous.get("dataset_fingerprint") != report.dataset_fingerprint:
        changed.append(
            f"标注集已变（{previous.get('dataset_fingerprint')} -> {report.dataset_fingerprint}）"
        )
    if previous.get("config_fingerprint") != report.config_fingerprint:
        changed.append(
            f"检索配置已变（{previous.get('config_fingerprint')} -> {report.config_fingerprint}）"
        )
    if previous.get("k") != report.k:
        changed.append(f"k 已变（{previous.get('k')} -> {report.k}）")
    # 两个变体（守门集/难题集）不可互比：混比会让「换了评测面」伪装成趋势
    prev_variant = previous.get("variant") or "default"
    if prev_variant != report.variant:
        changed.append(f"评测变体已变（{prev_variant} -> {report.variant}）")
    if changed:
        return {
            "status": "not_comparable",
            "message": "配置或标注集已变，指标不可直接比较",
            "changes": changed,
        }

    regressions = []
    for ch in CHANNELS:
        prev_hits = int(previous.get(f"{ch}_hits") or 0)
        prev_mrr = float(previous.get(f"{ch}_mrr") or 0.0)
        now = report.summary.get(ch, {})
        if now.get("hits", 0) < prev_hits:
            regressions.append(
                f"{ch}: 命中 {prev_hits} -> {now.get('hits')}（降 {prev_hits - now.get('hits', 0)}）"
            )
        if now.get("mrr", 0.0) < prev_mrr:
            regressions.append(f"{ch}: MRR {prev_mrr} -> {now.get('mrr')}")
        prev_ndcg = previous.get(f"{ch}_ndcg")
        if prev_ndcg is not None and now.get("ndcg", 0.0) < float(prev_ndcg):
            regressions.append(f"{ch}: nDCG {prev_ndcg} -> {now.get('ndcg')}")
    if regressions:
        return {"status": "regression", "message": "检出回归", "details": regressions}
    return {"status": "ok", "message": "与上次相比无回归"}


# --------------------------------------------------------------------------- #
# 趋势落库腿（law-bench 形态：eval_runs + criteria 行，照 calibration 的写法；
# 原件的 eval_runs 专用表（migrations 0006/0008）在本平台由这张通用尺子表承接，
# 双指纹/k/variant 以机器可读片段入 summary，读回后喂给上面同一个纯函数判趋势）
# --------------------------------------------------------------------------- #

# 机器可读 summary 片段（writer: store_retrieval_run; reader: latest_retrieval_run）
_DATASET_FP_RE = re.compile(r"(?:^|\s)dataset_fingerprint=([0-9a-f]{6,64})")
_CONFIG_FP_RE = re.compile(r"(?:^|\s)config_fingerprint=([0-9a-f]{6,64})")
_K_RE = re.compile(r"(?:^|\s)k=(\d+)")
_N_RE = re.compile(r"(?:^|\s)n=(\d+)")
_VARIANT_RE = re.compile(r"(?:^|\s)variant=([^\s;]+)")
_STRENGTH_RE = re.compile(r"(?:^|\s)judgment_strength=([^\s;]+)")
_STATUS_RE = re.compile(r"(?:^|\s)comparison=([a-z_]+)")
# criteria reasoning 形态："hits=<h>/<n> mrr=<m> ndcg=<d>"
_CRIT_METRICS_RE = re.compile(
    r"hits=(\d+)/(\d+) mrr=([0-9]*\.?[0-9]+) ndcg=([0-9]*\.?[0-9]+)"
)


def store_retrieval_run(
    conn: Any,
    report: EvalReport,
    *,
    comparison: dict,
    db_path: Any = DEFAULT_DB,
) -> dict:
    """把一次检索跑分落进 ``eval_runs``（趋势可查、双指纹随行）。

    落库风格照 :func:`src.bench.calibration.run_calibration`：一次跑分 = 一行
    run 级记录 + 每通道一条诊断 criteria 行。诚实标注：

    - ``channel='data'``（本尺是确定性度量，零 LLM——不是 'text' 判分通道），
      ``unit_kind='retrieval'``（如实）。
    - ``rubric_name = f'text-retrieval-ndcg:{domain}'``，``variant`` 入
      ``variant_label`` 列（守门集/难题集是两套评测面，趋势查询按 variant 隔离，
      与原件 ``latest_previous`` 同口径）。
    - ``score`` = hybrid nDCG（无 hybrid 通道时取第一个已跑通道），``max_score``=1.0。
    - 每通道 criteria 行 verdict：全部查询该通道满命中记 pass，否则 fail——
      **这是诊断行不是闸门**（难题集上近邻挤位本就常见，fail 不等于退化）。
    - run 级 ``all_pass`` = 本次对比判定为 ``no_baseline`` 或 ``ok``；
      ``regression``/``not_comparable`` 记 False（趋势不可判「未回归」即不放行）。
    - 双指纹、k、variant、n、judgment_strength、comparison 状态以机器可读片段
      嵌入 summary（本模块 reader 的私有格式，逐值可逆）。

    ``conn`` 只为与内核其他入口的调用形态对称；写入走
    :func:`src.eval.store.store_result`（``db_path`` 可为活连接）。
    返回 ``{"run_id", "rubric", "all_pass", "comparison"}``。
    """
    status = comparison.get("status")
    if status not in ("no_baseline", "ok", "regression", "not_comparable"):
        raise ValueError(f"comparison 缺合法 status，实得 {comparison!r}")

    channels_used = [ch for ch in CHANNELS if ch in report.summary]
    n = report.n_queries
    criteria_results = []
    for ch in channels_used:
        s = report.summary[ch]
        hits = int(s.get("hits", 0))
        passed = n > 0 and hits == n
        criteria_results.append(
            {
                "id": f"channel:{ch}",
                "title": ch,
                "verdict": "pass" if passed else "fail",
                "reasoning": (
                    f"hits={hits}/{n} mrr={s.get('mrr', 0.0)} ndcg={s.get('ndcg', 0.0)}"
                ),
            }
        )

    score_ch = "hybrid" if "hybrid" in report.summary else (channels_used[0] if channels_used else None)
    score = float(report.summary.get(score_ch, {}).get("ndcg", 0.0)) if score_ch else 0.0
    all_pass = status in ("no_baseline", "ok")

    summary = (
        f"retrieval-eval: n={n} k={report.k} variant={report.variant} "
        f"dataset_fingerprint={report.dataset_fingerprint} "
        f"config_fingerprint={report.config_fingerprint} "
        f"judgment_strength={report.judgment_strength} "
        f"comparison={status}; {comparison.get('message', '')}"
    )
    rubric_name = f"{RUBRIC_PREFIX}:{report.domain}"
    run_id = store_result(
        {
            "rubric": rubric_name,
            "score": score,
            "max_score": 1.0,
            "all_pass": all_pass,
            "n_criteria": len(criteria_results),
            "n_passed": sum(1 for c in criteria_results if c["verdict"] == "pass"),
            "summary": summary,
            "judge_model": None,  # 本尺零 LLM：judge 列如实留空
            "criteria_results": criteria_results,
        },
        task_desc=(
            f"domain={report.domain} k={report.k} n_queries={n} "
            f"channels={','.join(channels_used)} degraded={len(report.degraded)}"
        ),
        db_path=db_path,
        variant_label=report.variant,
        channel="data",
        unit_kind="retrieval",
    )
    return {"run_id": run_id, "rubric": rubric_name, "all_pass": all_pass, "comparison": comparison}


def _parse_run_row(row: dict, crits: list) -> dict:
    """把一行 eval_runs（+criteria 行）还原成结构化 run 记录。"""
    summary = row["summary"] or ""
    missing = [
        name
        for name, rx in (
            ("dataset_fingerprint", _DATASET_FP_RE),
            ("config_fingerprint", _CONFIG_FP_RE),
            ("k", _K_RE),
            ("n", _N_RE),
            ("variant", _VARIANT_RE),
        )
        if not rx.search(summary)
    ]
    if missing:
        raise ValueError(
            f"eval_runs 行 {row['id']} 的 summary 缺机器可读片段 {missing}（writer 是 "
            "packs/text-retrieval/scorer.store_retrieval_run；混入外来行请点名来源）"
        )

    strength_m = _STRENGTH_RE.search(summary)
    status_m = _STATUS_RE.search(summary)
    channels: dict = {}
    for c in crits:
        m = _CRIT_METRICS_RE.search(c["reasoning"] or "")
        if not m or not (c["criterion_id"] or "").startswith("channel:"):
            continue
        ch = c["title"]
        channels[ch] = {
            "hits": int(m.group(1)),
            "total": int(m.group(2)),
            "mrr": float(m.group(3)),
            "ndcg": float(m.group(4)),
            "verdict": c["verdict"],
        }
    return {
        "run_id": row["id"],
        "rubric_name": row["rubric_name"],
        "score": row["score"],
        "all_pass": bool(row["all_pass"]),
        "created_at": row["created_at"],
        "k": int(_K_RE.search(summary).group(1)),
        "n_queries": int(_N_RE.search(summary).group(1)),
        "variant": _VARIANT_RE.search(summary).group(1),
        "dataset_fingerprint": _DATASET_FP_RE.search(summary).group(1),
        "config_fingerprint": _CONFIG_FP_RE.search(summary).group(1),
        "judgment_strength": strength_m.group(1) if strength_m else "",
        "comparison_status": status_m.group(1) if status_m else "",
        "channels": channels,
    }


def latest_retrieval_run(
    conn: Any, domain: str, *, variant: str = "default"
) -> Optional[dict]:
    """取同一（域, 变体）最近一次落库跑分（趋势对比的「上次」行）。

    按 variant 隔离：守门集与难题集的数字不可互比——跨变体取「上次」会把
    「换了评测面」伪装成趋势（与原件 store.latest_previous 同口径）。
    """
    row = conn.execute(
        "SELECT id, rubric_name, summary, score, all_pass, created_at FROM eval_runs "
        "WHERE rubric_name = %s AND channel = 'data' AND unit_kind = 'retrieval' "
        "  AND variant_label = %s "
        "ORDER BY id DESC LIMIT 1",
        (f"{RUBRIC_PREFIX}:{domain}", variant),
    ).fetchone()
    if row is None:
        return None
    crits = conn.execute(
        "SELECT criterion_id, title, verdict, reasoning FROM eval_criteria_results "
        "WHERE run_id = %s ORDER BY ordinal",
        (row["id"],),
    ).fetchall()
    return _parse_run_row(dict(row), [dict(c) for c in crits])


def list_retrieval_trend(
    conn: Any, domain: str, *, variant: str = "default", limit: int = 20
) -> list:
    """趋势查询：某域某变体的历次跑分（新→旧），双指纹随行可查。"""
    rows = conn.execute(
        "SELECT id, rubric_name, summary, score, all_pass, created_at FROM eval_runs "
        "WHERE rubric_name = %s AND channel = 'data' AND unit_kind = 'retrieval' "
        "  AND variant_label = %s "
        "ORDER BY id DESC LIMIT %s",
        (f"{RUBRIC_PREFIX}:{domain}", variant, limit),
    ).fetchall()
    return [
        _parse_run_row(dict(r), [])  # 趋势列表不逐行取 criteria（reader 允许空 criteria）
        for r in rows
    ]


def previous_from_run(parsed: Optional[dict]) -> Optional[dict]:
    """把 :func:`latest_retrieval_run` 的记录还原成原件 ``compare_with_previous``
    消费的 previous 行形态（列名即原件 eval_runs 字段：``{ch}_hits/_mrr/_ndcg``）。
    趋势判定因此跑在同一个纯函数上，不存在复刻实现的漂移面。"""
    if parsed is None:
        return None
    prev = {
        "dataset_fingerprint": parsed["dataset_fingerprint"],
        "config_fingerprint": parsed["config_fingerprint"],
        "k": parsed["k"],
        "variant": parsed["variant"],
    }
    for ch, s in parsed["channels"].items():
        prev[f"{ch}_hits"] = s["hits"]
        prev[f"{ch}_mrr"] = s["mrr"]
        prev[f"{ch}_ndcg"] = s["ndcg"]
    return prev
