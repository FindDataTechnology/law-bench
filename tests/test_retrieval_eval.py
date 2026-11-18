"""text-retrieval 域包迁入验收（OpenSpec add-knowledge-bench-platform P3 6.1）。

三件事：
  1. pack.yaml 过内核 validate_pack（必填字段、components 路径真实、name==目录名）。
  2. **等价双跑**：以 importlib 加载**未经修改的**原仓
     ``fd-text-core/fd_text_core/eval/{dataset,runner}.py``（独立包名
     ``fdtext_legacy``，不触发原包 __init__——其 import 链要 psycopg_pool，
     本机 law-bench 环境没有），在同一进程内对同一输入与迁入实现逐值对比：
     数据集指纹 / 契约解析 / nDCG / run_eval 全链（检索后端注入同一个确定性
     stub）/ 配置指纹 / compare_with_previous。断言**逐值相等（零漂移）**。
     原仓缺失时相应测试 skip——不造数、不假称比过。
  3. 趋势落库腿（本仓合成集 + 确定性 ranked fixture）：同数据集跑两次 →
     eval_runs 两行（channel='data'、unit_kind='retrieval'、双指纹入 summary、
     variant 隔离）→ 读回「上次」喂回原件同款纯函数判趋势 ok；改 k → not_comparable。

无法双跑的腿（如实，见 pack README）：真实检索执行（hybrid_search 需原仓
PG+S3+嵌入凭据）、原仓 store.py 的 SQL 腿（原表 DDL 0006/0008）。本测试比的是
**尺子本身**（同一检索输出喂两把尺子逐值相等），不是复刻历史跑分数字。

零 LLM、零网络、零原仓写入。
"""
from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
import os
import re
import sys
import types
from pathlib import Path

import pytest

from src.bench.packs import load_pack, validate_pack
from src.eval.store import ensure_schema

REPO_ROOT = Path(__file__).resolve().parents[1]
PACK_DIR = REPO_ROOT / "packs" / "text-retrieval"
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "retrieval"
FIXTURE_DATASETS = FIXTURES / "datasets"

# 原仓（只读真源）：与 adapters.py 的同名常量口径一致，环境变量可覆盖。
FD_TEXT_CORE = Path(os.environ.get("FD_TEXT_CORE_REPO", "/Users/chengsishi/finddata/fd-text-core"))
LEGACY_SRC = FD_TEXT_CORE / "fd_text_core"
LEGACY_DATASETS = LEGACY_SRC / "eval" / "datasets"
LEGACY_AVAILABLE = (LEGACY_SRC / "eval" / "runner.py").is_file()

requires_legacy = pytest.mark.skipif(
    not LEGACY_AVAILABLE,
    reason=f"原仓尺子不可读（{LEGACY_SRC} 不存在）——双跑腿 skip，不造数",
)

adapters = importlib.import_module("packs.text-retrieval.adapters")
scorer = importlib.import_module("packs.text-retrieval.scorer")

LEGACY_PKG = "fdtext_legacy"


# --------------------------------------------------------------------------- #
# 原尺只读 harness：以独立包名加载未修改的原仓 dataset.py / runner.py
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def legacy():
    """真实原件（内存级 harness；原仓文件零改动、原包 __init__ 不执行）。"""
    saved = {k: v for k, v in sys.modules.items() if k.startswith(LEGACY_PKG + ".") or k == LEGACY_PKG}
    top = types.ModuleType(LEGACY_PKG)
    top.__path__ = [str(LEGACY_SRC)]
    sys.modules[LEGACY_PKG] = top

    eval_pkg = types.ModuleType(f"{LEGACY_PKG}.eval")
    eval_pkg.__path__ = [str(LEGACY_SRC / "eval")]
    sys.modules[f"{LEGACY_PKG}.eval"] = eval_pkg
    top.eval = eval_pkg

    def _load(name: str, path: Path):
        spec = importlib.util.spec_from_file_location(f"{LEGACY_PKG}.eval.{name}", path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)
        setattr(eval_pkg, name, mod)
        return mod

    # runner 的 `from ..embedding import Embedder` 经 top.__path__ 加载真实
    # embedding.py（纯 stdlib）；`from .dataset import Dataset` 命中已注册模块。
    dataset_mod = _load("dataset", LEGACY_SRC / "eval" / "dataset.py")
    runner_mod = _load("runner", LEGACY_SRC / "eval" / "runner.py")

    # run_eval 内部 `from ..querylib import hybrid_search`：注册 stub 模块，
    # 由每个双跑测试注入同一个确定性检索替身（原件代码本身未改一字）。
    querylib_stub = types.ModuleType(f"{LEGACY_PKG}.querylib")
    querylib_stub.hybrid_search = None
    sys.modules[f"{LEGACY_PKG}.querylib"] = querylib_stub
    top.querylib = querylib_stub

    # compute_config_fingerprint 内部 `from ..verticals.registry import get`：
    # stub 的 get 行为由测试设定（KeyError=原件「未注册垂域」分支，或返回描述符）。
    vert_pkg = types.ModuleType(f"{LEGACY_PKG}.verticals")
    vert_reg = types.ModuleType(f"{LEGACY_PKG}.verticals.registry")

    def _get_missing(domain: str):
        raise KeyError(domain)

    vert_reg.get = _get_missing
    sys.modules[f"{LEGACY_PKG}.verticals"] = vert_pkg
    sys.modules[f"{LEGACY_PKG}.verticals.registry"] = vert_reg
    vert_pkg.registry = vert_reg

    ns = types.SimpleNamespace(
        dataset=dataset_mod, runner=runner_mod, querylib=querylib_stub, registry=vert_reg
    )
    yield ns

    for key in [k for k in sys.modules if k == LEGACY_PKG or k.startswith(LEGACY_PKG + ".")]:
        sys.modules.pop(key, None)
    sys.modules.update(saved)


# --------------------------------------------------------------------------- #
# 确定性检索替身（两把尺子共用同一个函数对象，度量输入逐 id 相同）
# --------------------------------------------------------------------------- #


def _sha_order(pool, *keys) -> list:
    seed = "|".join(str(x) for x in keys)
    return sorted(pool, key=lambda d: hashlib.sha256(f"{seed}|{d}".encode()).hexdigest())


def make_chain_search_stub(ds, *, degraded_vector: bool = True):
    """按 qrels 池造确定性伪检索输出：三通道各自 sha 排序、首文档重复进位
    （切块形态，nDCG 必须去重保首现）、第一条查询 keyword 通道刻意漏检。"""

    plan: dict = {}
    for idx, q in enumerate(ds.queries):
        gids = sorted({g.doc_id for g in q.grades()})
        pool = sorted(set(gids) | {g + 1000 for g in gids} | {g + 2000 for g in gids})
        per_ch = {}
        for ch in ("keyword", "vector", "hybrid"):
            ids = _sha_order(pool, ch, q.q)
            ids = [ids[0], ids[0]] + ids[1:6]  # 同一文档的多个切块
            if idx == 0 and ch == "keyword" and q.max_grade_ids():
                top = q.max_grade_ids()[0]
                ids = [x for x in ids if x != top]  # 漏检一条，让 hits 通道间有差
            per_ch[ch] = ids
        plan[(q.q, "ids")] = per_ch
    degraded = ["vector: embedding upstream unavailable"] if degraded_vector else []

    def search(domain, q, *, embedder=None, limit=10, channels="keyword"):
        ids = plan[(q, "ids")][channels][:limit]
        deg = list(degraded) if channels == "vector" else []
        return {"results": [{"document_id": i} for i in ids], "degraded": deg}

    return search


def _check_expects_stub(_dataset):
    """两侧同一个在库校验回调（原件 check_expects_exist 需其 PG，无法直连双跑；
    注入点与返回形态照原件契约，证明的是「缺失逐条入报告而非静默」这条腿同构）。"""
    return [{"q": "标注失效样例", "expect_doc_id": None, "expect_doc_ids": [987654]}]


class FakeStrategy:
    def __init__(self):
        self.window = 512
        self.overlap = 64
        self._private = "不计入"


class FakeVertical:
    """与原件 registry.get(domain) 返回物同形的描述符。"""

    def __init__(self):
        self.strategy = FakeStrategy()
        self.cjk = True
        self.t2s = False
        self.tsv_config = "cjk"


# --------------------------------------------------------------------------- #
# 1) pack 清单过内核 validate_pack
# --------------------------------------------------------------------------- #


class TestPackManifest:
    def test_validate_pack_clean(self):
        manifest = load_pack("text-retrieval")
        assert validate_pack(manifest, directory="text-retrieval") == []

    def test_manifest_fields_are_honest(self):
        manifest = load_pack("text-retrieval")
        assert manifest["name"] == "text-retrieval"
        assert manifest["version"] == "0.1.0"
        assert manifest["kinds"] == ["retrieval-query"]
        assert manifest["eval_suites"] == ["text-retrieval-ndcg"]
        assert isinstance(manifest["description"], str) and manifest["description"]
        for comp in manifest["components"]:
            assert comp["type"] in ("module", "data", "db_seed")
            assert (REPO_ROOT / comp["path"]).exists(), comp["path"]
        # 不声明 gold_judge：本尺零 LLM，不假称有金判据
        assert "gold_judge" not in manifest


class TestPackIsSelfContained:
    def test_pack_never_imports_fd_text_core(self):
        """迁入即包内实现：运行时不得 import 原仓代码（路径常量只作只读数据源）。"""
        for fname in ("__init__.py", "adapters.py", "scorer.py"):
            text = (PACK_DIR / fname).read_text(encoding="utf-8")
            hits = re.findall(r"^\s*(?:from|import)\s+\S*fd_text_core\S*", text, re.M)
            assert not hits, f"{fname} imports the sibling repo: {hits}"


# --------------------------------------------------------------------------- #
# 2) 等价双跑（原件只读加载，同一输入逐值相等）
# --------------------------------------------------------------------------- #

REAL_SETS = (
    ("gov", "default"),
    ("gov", "hard"),
    ("papers", "default"),
    ("screenplay", "default"),
)


@requires_legacy
class TestEquivalenceDualRun:
    def test_dataset_fingerprint_zero_drift(self, legacy):
        """双指纹之一：数据集指纹 = 文件字节 sha256 前 16 位，逐文件相等。"""
        for domain, variant in REAL_SETS:
            path = legacy.dataset.dataset_path(domain, variant)
            assert adapters.compute_fingerprint(path) == legacy.dataset.compute_fingerprint(path), path

    def test_dataset_contract_parsing_zero_drift(self, legacy):
        """契约解析：真实四份标注集逐条比对（含分级 qrels、why 兜底文案、指纹）。"""
        for domain, variant in REAL_SETS:
            theirs = legacy.dataset.load_dataset(domain, variant=variant)
            ours = adapters.load_dataset(domain, variant=variant)
            for attr in (
                "domain", "fingerprint", "how_targets_chosen", "judgment_strength",
                "note", "variant",
            ):
                assert getattr(ours, attr) == getattr(theirs, attr), (domain, variant, attr)
            assert len(ours.queries) == len(theirs.queries)
            for a, b in zip(ours.queries, theirs.queries):
                assert (a.q, a.intent, a.why, a.expect_doc_id, a.graded) == (
                    b.q, b.intent, b.why, b.expect_doc_id, b.graded
                )
                assert [(g.doc_id, g.grade, g.why) for g in a.grades()] == [
                    (g.doc_id, g.grade, g.why) for g in b.grades()
                ]
                assert a.max_grade_ids() == b.max_grade_ids()

    def test_rejection_contract_zero_drift(self, legacy, tmp_path):
        """「拒绝比静默跑分负责」这条腿：不合契约的文件两侧报错逐字相等。"""
        broken_domain = tmp_path / "brokendemo"
        broken_domain.mkdir()
        bad = {"_provenance": {"judgment_strength": "strong"}, "queries": []}
        broken_file = broken_domain / "annotated_queries.json"
        broken_file.write_text(json.dumps(bad, ensure_ascii=False), encoding="utf-8")
        legacy.dataset.DATASETS_DIR = tmp_path  # 内存级指路，不改原仓一字
        try:
            with pytest.raises(ValueError) as t_old:
                legacy.dataset.load_dataset("brokendemo")
            with pytest.raises(ValueError) as t_new:
                adapters.load_dataset("brokendemo", datasets_dir=tmp_path)
        finally:
            legacy.dataset.DATASETS_DIR = LEGACY_DATASETS
        # 同一类契约违例：类名与报错文本逐字相等（迁入实现是原仓同名 DatasetError，
        # 两把尺子在 harness 里是两个模块对象，类型同一性比不了名字+值）
        assert type(t_old.value).__name__ == type(t_new.value).__name__ == "DatasetError"
        assert isinstance(t_old.value, adapters.DatasetError) is False  # 原件类，非同物
        assert str(t_old.value) == str(t_new.value)
        assert str(broken_file) in str(t_new.value) and "how_targets_chosen" in str(t_new.value)

    def test_ndcg_zero_drift_on_real_qrels(self, legacy):
        """nDCG@k 纯函数：真实 gov/hard 分级 qrels × 确定性排列（含切块重复、
        截断、k 边界、空标注）逐 case float 相等。"""
        theirs_ds = legacy.dataset.load_dataset("gov", variant="hard")
        ours_ds = adapters.load_dataset("gov", variant="hard")
        cases = 0
        for t_q, o_q in zip(theirs_ds.queries, ours_ds.queries):
            pool = sorted({g.doc_id for g in o_q.grades()} | {500, 501, 502})
            for tag in ("ideal", "swapped", "dup", "miss"):
                ranked = list(_sha_order(pool, tag, o_q.q))
                if tag == "ideal":
                    gs = sorted(o_q.grades(), key=lambda g: -g.grade)
                    ranked = [g.doc_id for g in gs] + ranked
                if tag == "swapped" and len(ranked) > 1:
                    ranked = [ranked[1], ranked[0]] + ranked[2:]
                if tag == "dup":
                    ranked = ranked[:1] + ranked  # 首文档切块重复
                if tag == "miss":
                    top = o_q.max_grade_ids()[0]
                    ranked = [x for x in ranked if x != top] + [900 + len(ranked)]
                for k in (1, 3, 5, 10, 50):
                    v_old = legacy.runner.ndcg_at_k(list(ranked), t_q.grades(), k)
                    v_new = scorer.ndcg_at_k(list(ranked), o_q.grades(), k)
                    assert v_old == v_new, (o_q.q, tag, k, v_old, v_new)
                    assert 0.0 <= v_new <= 1.0
                    cases += 1
        # 边界：空标注 IDCG=0 防御分支（契约外调用，两侧同样返 0.0 不抛）
        assert legacy.runner.ndcg_at_k([1, 2, 3], (), 5) == scorer.ndcg_at_k([1, 2, 3], (), 5) == 0.0
        assert cases > 300

    def test_run_eval_full_chain_zero_drift(self, legacy):
        """跑分全链（除真实检索执行）：同一个确定性 search stub 注入两侧
        `hybrid_search` 位，整份 EvalReport.to_dict() 逐值相等。"""
        theirs_ds = legacy.dataset.load_dataset("gov", variant="hard")
        ours_ds = adapters.load_dataset("gov", variant="hard")
        vertical = FakeVertical()
        stub = make_chain_search_stub(ours_ds)

        # 原件经 ..querylib 拿检索替身；垂域描述符经 ..verticals.registry 注入
        legacy.querylib.hybrid_search = stub
        legacy.registry.get = lambda domain: vertical
        try:
            rep_old = legacy.runner.run_eval(
                theirs_ds, k=10, embedder=None, check_expects=_check_expects_stub
            )
        finally:
            legacy.querylib.hybrid_search = None
            legacy.registry.get = None

        rep_new = scorer.run_eval(
            ours_ds, search=stub, k=10, embedder=None,
            check_expects=_check_expects_stub, vertical=vertical,
        )
        d_old, d_new = rep_old.to_dict(), rep_new.to_dict()
        assert d_old == d_new
        # 逐段点名断言（防整份 dict 「相等但没内容」）
        assert d_new["dataset_fingerprint"] == theirs_ds.fingerprint
        assert d_new["config_fingerprint"] == rep_old.config_fingerprint
        assert len(d_new["rows"]) == len(theirs_ds) == 18
        assert d_new["summary"]["hybrid"]["ndcg"] > 0  # 真实 qrels 上的真实数字
        assert d_new["degraded"] == ["vector: embedding upstream unavailable"]
        assert d_new["missing_expects"] == _check_expects_stub(None)
        assert d_new["hybrid_not_worse"] is None  # degraded 下如实不可判
        assert d_new["saturated"] is False

        # 干净一轮（无 degraded）：验收线/饱和判定两把尺子同值
        stub2 = make_chain_search_stub(ours_ds, degraded_vector=False)
        legacy.querylib.hybrid_search = stub2
        legacy.registry.get = lambda domain: vertical
        try:
            rep_old2 = legacy.runner.run_eval(theirs_ds, k=10, embedder=None)
        finally:
            legacy.querylib.hybrid_search = None
            legacy.registry.get = None
        rep_new2 = scorer.run_eval(ours_ds, search=stub2, k=10, embedder=None, vertical=vertical)
        assert rep_old2.to_dict() == rep_new2.to_dict()
        assert rep_old2.hybrid_not_worse == rep_new2.hybrid_not_worse
        assert rep_old2.saturated == rep_new2.saturated

    def test_config_fingerprint_zero_drift(self, legacy, monkeypatch):
        """双指纹之二：配置指纹——未注册分支 / 注入同一 vertical / env 联动。"""
        # (a) 原件 KeyError 分支 ≡ 本包 vertical=None
        legacy.registry.get = _raise = lambda d: (_ for _ in ()).throw(KeyError(d))
        fp_old_a = legacy.runner.compute_config_fingerprint("gov")
        fp_new_a = scorer.compute_config_fingerprint("gov")
        assert fp_old_a == fp_new_a and re.fullmatch(r"[0-9a-f]{16}", fp_new_a)

        # (b) 同一垂域描述符喂两侧
        vertical = FakeVertical()
        legacy.registry.get = lambda d: vertical
        fp_old_b = legacy.runner.compute_config_fingerprint("gov")
        fp_new_b = scorer.compute_config_fingerprint("gov", vertical=vertical)
        assert fp_old_b == fp_new_b
        assert fp_old_b != fp_old_a  # 策略段确实参与指纹

        # (c) 改 RRF 参数 → 两侧同步变化且仍相等（趋势可归因的根）
        monkeypatch.setenv("FDTEXT_RRF_K", "42")
        fp_old_c = legacy.runner.compute_config_fingerprint("gov")
        fp_new_c = scorer.compute_config_fingerprint("gov", vertical=vertical)
        assert fp_old_c == fp_new_c and fp_old_c != fp_old_b
        # (d) 本包显式 env 映射 == 读同一 os.environ
        assert scorer.compute_config_fingerprint(
            "gov", vertical=vertical, env=dict(os.environ)
        ) == fp_new_c

    def test_compare_with_previous_zero_drift(self, legacy):
        """趋势判定纯函数：no_baseline / 四种不可比 / 回归 / ok 各场景输出相等。"""
        ours_ds = adapters.load_dataset("gov", variant="hard")
        stub = make_chain_search_stub(ours_ds, degraded_vector=False)
        rep = scorer.run_eval(ours_ds, search=stub, k=10)
        base_prev = {
            "dataset_fingerprint": rep.dataset_fingerprint,
            "config_fingerprint": rep.config_fingerprint,
            "k": rep.k,
            "variant": rep.variant,
        }
        for ch, s in rep.summary.items():
            base_prev[f"{ch}_hits"] = s["hits"]
            base_prev[f"{ch}_mrr"] = s["mrr"]
            base_prev[f"{ch}_ndcg"] = s["ndcg"]

        scenarios = {
            "no_baseline": None,
            "ok": dict(base_prev),
            "dataset_changed": {**base_prev, "dataset_fingerprint": "0123456789abcdef"},
            "config_changed": {**base_prev, "config_fingerprint": "fedcba9876543210"},
            "k_changed": {**base_prev, "k": rep.k + 5},
            "variant_changed": {**base_prev, "variant": "legacy-default"},
            "regression": {**base_prev, "hybrid_hits": rep.summary["hybrid"]["hits"] + 3},
            "ndcg_backfill_rows": {  # 0006 时代旧行无 *_ndcg 列
                **{k: v for k, v in base_prev.items() if not k.endswith("_ndcg")}
            },
        }
        for name, prev in scenarios.items():
            out_old = legacy.runner.compare_with_previous(rep, json.loads(json.dumps(prev)) if prev else prev)
            out_new = scorer.compare_with_previous(rep, json.loads(json.dumps(prev)) if prev else prev)
            assert out_old == out_new, name
        # 场景内容如实命中（不是全都 no_baseline 的假相等）
        assert scorer.compare_with_previous(rep, None)["status"] == "no_baseline"
        assert (
            scorer.compare_with_previous(rep, scenarios["regression"])["status"] == "regression"
        )
        assert (
            scorer.compare_with_previous(rep, scenarios["dataset_changed"])["status"]
            == "not_comparable"
        )
        assert scorer.compare_with_previous(rep, scenarios["ok"])["status"] == "ok"


# --------------------------------------------------------------------------- #
# 3) 趋势落库腿（本仓合成集；不依赖原仓）
# --------------------------------------------------------------------------- #


@pytest.fixture
def retrieval_db(empty_db):
    ensure_schema(db_path=empty_db)
    yield empty_db


def _search_from_ranked_fixture():
    ranked = json.loads(
        (FIXTURES / "ranked" / "textdemo_default_ranked.json").read_text(encoding="utf-8")
    )

    def search(domain, q, *, embedder=None, limit=10, channels="keyword"):
        ids = ranked.get(channels, {}).get(q, [])[:limit]
        return {"results": [{"document_id": i} for i in ids], "degraded": []}

    return search


def _search_sha_from_grades(dataset):
    """难题集（hard）没有 ranked fixture：按 qrels 池造确定性排序（仅落库腿自测用，
    不参与双跑数字）。"""

    def search(domain, q, *, embedder=None, limit=10, channels="keyword"):
        match = next(x for x in dataset.queries if x.q == q)
        pool = sorted({g.doc_id for g in match.grades()} | {900, 901, 902, 903})
        ids = _sha_order(pool, channels, q)[:limit]
        return {"results": [{"document_id": i} for i in ids], "degraded": []}

    return search


class TestTrendStoreLeg:
    def test_two_runs_land_eval_runs_and_trend_queryable(self, retrieval_db):
        conn = retrieval_db
        ds = adapters.load_dataset("textdemo", datasets_dir=FIXTURE_DATASETS)
        search = _search_from_ranked_fixture()

        # —— 第一次：无历史 → no_baseline，放行 ——
        r1 = scorer.run_eval(ds, search=search, k=10)
        assert r1.dataset_fingerprint == ds.fingerprint
        c1 = scorer.compare_with_previous(r1, None)
        assert c1["status"] == "no_baseline"
        s1 = scorer.store_retrieval_run(conn, r1, comparison=c1, db_path=conn)
        assert isinstance(s1["run_id"], int)

        # —— 第二次：同数据集同后端 → 双指纹复现、趋势 ok ——
        r2 = scorer.run_eval(ds, search=search, k=10)
        prev1 = scorer.latest_retrieval_run(conn, "textdemo", variant="default")
        assert prev1 is not None
        assert prev1["dataset_fingerprint"] == r1.dataset_fingerprint
        assert prev1["config_fingerprint"] == r1.config_fingerprint
        assert prev1["k"] == r1.k and prev1["variant"] == "default"
        prev_row = scorer.previous_from_run(prev1)
        for ch in r1.summary:  # 读回行与原始 summary 逐值相等（落库无损）
            assert prev_row[f"{ch}_hits"] == r1.summary[ch]["hits"]
            assert prev_row[f"{ch}_mrr"] == r1.summary[ch]["mrr"]
            assert prev_row[f"{ch}_ndcg"] == r1.summary[ch]["ndcg"]
        c2 = scorer.compare_with_previous(r2, prev_row)
        assert c2["status"] == "ok"
        s2 = scorer.store_retrieval_run(conn, r2, comparison=c2, db_path=conn)

        # —— eval_runs 行诚实标注既有列 ——
        rows = conn.execute(
            "SELECT id, rubric_name, channel, unit_kind, variant_label, judge_model, "
            "       summary, score, max_score, all_pass, n_criteria, n_passed "
            "FROM eval_runs ORDER BY id"
        ).fetchall()
        assert [r["id"] for r in rows] == [s1["run_id"], s2["run_id"]]
        for r in rows:
            assert r["rubric_name"] == "text-retrieval-ndcg:textdemo"
            assert r["channel"] == "data"  # 确定性通道，零 LLM 不冒充 text
            assert r["unit_kind"] == "retrieval"
            assert r["variant_label"] == "default"
            assert r["judge_model"] is None
            assert r["n_criteria"] == 3
            assert 0.0 <= r["score"] <= 1.0 and r["max_score"] == 1.0
            assert f"dataset_fingerprint={ds.fingerprint}" in r["summary"]
            assert re.search(r"config_fingerprint=[0-9a-f]{16}", r["summary"])
        assert rows[0]["all_pass"] == 1 and rows[1]["all_pass"] == 1

        crits = conn.execute(
            "SELECT run_id, criterion_id, title, verdict, reasoning "
            "FROM eval_criteria_results ORDER BY id"
        ).fetchall()
        assert len(crits) == 6
        assert {c["criterion_id"] for c in crits} == {
            "channel:keyword", "channel:vector", "channel:hybrid"
        }
        for c in crits:
            assert re.search(r"hits=\d+/\d+ mrr=[\d.]+ ndcg=[\d.]+", c["reasoning"])

        # —— 趋势可查（新→旧，双指纹随行）——
        trend = scorer.list_retrieval_trend(conn, "textdemo", variant="default")
        assert [t["run_id"] for t in trend] == [s2["run_id"], s1["run_id"]]
        assert all(t["dataset_fingerprint"] == ds.fingerprint for t in trend)
        assert all(t["config_fingerprint"] == r1.config_fingerprint for t in trend)

    def test_changed_k_is_not_comparable_and_lands(self, retrieval_db):
        conn = retrieval_db
        ds = adapters.load_dataset("textdemo", datasets_dir=FIXTURE_DATASETS)
        search = _search_from_ranked_fixture()
        r1 = scorer.run_eval(ds, search=search, k=10)
        scorer.store_retrieval_run(conn, r1, comparison=scorer.compare_with_previous(r1, None), db_path=conn)

        r5 = scorer.run_eval(ds, search=search, k=5)  # 同 stub，limit 截断生效
        prev = scorer.previous_from_run(scorer.latest_retrieval_run(conn, "textdemo"))
        c = scorer.compare_with_previous(r5, prev)
        assert c["status"] == "not_comparable"
        assert any("k 已变" in ch for ch in c["changes"])
        s = scorer.store_retrieval_run(conn, r5, comparison=c, db_path=conn)
        assert s["all_pass"] is False  # 不可判「未回归」即不放行（诚实）
        trend = scorer.list_retrieval_trend(conn, "textdemo", variant="default")
        assert len(trend) == 2

    def test_variant_isolation(self, retrieval_db):
        """守门集/难题集两套评测面不可互比（原件 variant 隔离口径）。"""
        conn = retrieval_db
        ds_d = adapters.load_dataset("textdemo", datasets_dir=FIXTURE_DATASETS, variant="default")
        rd = scorer.run_eval(ds_d, search=_search_from_ranked_fixture(), k=10)
        scorer.store_retrieval_run(conn, rd, comparison=scorer.compare_with_previous(rd, None), db_path=conn)

        ds_h = adapters.load_dataset("textdemo", datasets_dir=FIXTURE_DATASETS, variant="hard")
        rh = scorer.run_eval(ds_h, search=_search_sha_from_grades(ds_h), k=10)
        prev_h = scorer.previous_from_run(  # 「上次」若跨变体取 → 必须 not_comparable
            scorer.latest_retrieval_run(conn, "textdemo", variant="default")
        )
        c_cross = scorer.compare_with_previous(rh, prev_h)
        assert c_cross["status"] == "not_comparable"
        assert any("变体已变" in ch for ch in c_cross["changes"])
        scorer.store_retrieval_run(conn, rh, comparison=scorer.compare_with_previous(rh, None), db_path=conn)

        assert scorer.latest_retrieval_run(conn, "textdemo", variant="hard")["variant"] == "hard"
        assert scorer.latest_retrieval_run(conn, "textdemo", variant="default")["run_id"] == (
            scorer.list_retrieval_trend(conn, "textdemo", variant="default")[0]["run_id"]
        )
        assert len(scorer.list_retrieval_trend(conn, "textdemo", variant="hard")) == 1

    def test_store_requires_honest_comparison(self, retrieval_db):
        ds = adapters.load_dataset("textdemo", datasets_dir=FIXTURE_DATASETS)
        r = scorer.run_eval(ds, search=_search_from_ranked_fixture(), k=10)
        with pytest.raises(ValueError, match="comparison"):
            scorer.store_retrieval_run(retrieval_db, r, comparison={"status": "whatever"}, db_path=retrieval_db)


class TestPackOfflineDataset:
    """包内实现可独立运转（不依赖原仓）：合成集解析、契约拒绝、单文件入口。"""

    def test_fixture_datasets_load(self):
        ds = adapters.load_dataset("textdemo", datasets_dir=FIXTURE_DATASETS)
        assert len(ds) == 12 and ds.judgment_strength == "strong"
        hard = adapters.load_dataset("textdemo", datasets_dir=FIXTURE_DATASETS, variant="hard")
        assert all(q.graded for q in hard.queries)
        assert all(any(g.grade == 2 for g in q.grades()) for q in hard.queries)

    def test_load_dataset_file_entry(self):
        path = FIXTURE_DATASETS / "textdemo" / "annotated_queries.json"
        ds = adapters.load_dataset_file(path)
        assert ds.domain == "textdemo"
        assert ds.fingerprint == adapters.compute_fingerprint(path)

    def test_rejects_missing_provenance(self, tmp_path):
        d = tmp_path / "noprov"
        d.mkdir()
        (d / "annotated_queries.json").write_text(
            json.dumps({"queries": [{"q": "x", "intent": "i", "why": "w", "expect_doc_id": 1}]}),
            encoding="utf-8",
        )
        with pytest.raises(adapters.DatasetError, match="how_targets_chosen"):
            adapters.load_dataset("noprov", datasets_dir=tmp_path)

    def test_run_eval_requires_injected_search(self):
        ds = adapters.load_dataset("textdemo", datasets_dir=FIXTURE_DATASETS)
        with pytest.raises(ValueError, match="search"):
            scorer.run_eval(ds, search=None, k=10)
