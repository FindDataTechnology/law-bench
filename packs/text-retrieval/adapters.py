"""标注查询集契约（迁入自 fd-text-core，原尺只读真源见下）。

真源：``/Users/chengsishi/finddata/fd-text-core/fd_text_core/eval/dataset.py``。
迁入即单一真源；原仓为该尺的历史真源，直至其入口 deprecation（见 README.md，
口径同 finance-data 包「迁入 ≠ 取代」——等价双跑完成前，原仓尺子仍是行为基准）。

契约的存在理由（原仓 design D2）：**命中数字的意义取决于标注口径**。
「目标文档为何唯一可判定」不写下来，读者无法判断 hit@k 达标是真达标还是
标注集太容易。故契约要求两层：
  · 每条查询有 ``why``（这条为何这样标注）
  · 数据集级 ``_provenance.how_targets_chosen``（目标如何选定、为何可判定）
缺任一项即拒绝该数据集并指明缺什么——**拒绝比静默跑出好看的数字更负责**。

与原件的两点差异（均为平台边界，不改语义）：
  · 原仓把标注集目录硬编码为包内 ``eval/datasets``；本包改为**显式传入
    ``datasets_dir``**（测试/包内 fixture 用），默认值只作**只读路径引用**，
    本包运行时不 import fd_text_core 任何代码，指标层（scorer.py）也不依赖
    任何数据集目录。
  · 标注集**正文数据不复制进本仓**（硬约束）：真实三域标注集留在原仓，
    仓内只有 ``tests/fixtures/retrieval/`` 的合成集。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union

# 原仓路径常量：仅用于「默认读取哪份只读标注集」，不参与任何代码 import。
# 覆盖顺序：显式 datasets_dir > FD_TEXT_CORE_DATASETS_DIR > <FD_TEXT_CORE_REPO 或
# 下述默认路径>/fd_text_core/eval/datasets。机器上没有原仓时显式传目录即可
# （如 tests/fixtures/retrieval/datasets），默认不依赖。
DEFAULT_FD_TEXT_CORE_REPO = "/Users/chengsishi/finddata/fd-text-core"

# 域名形态：与引擎的 domain 取值一致（小写字母数字与连字符）
_DOMAIN_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


class DatasetError(ValueError):
    """标注集不合契约（点名缺哪条、缺什么字段，不泛泛报错）。"""


def _resolve_datasets_dir(explicit: Union[str, Path, None] = None) -> Path:
    """解析标注集目录（只读）。见模块 docstring 的覆盖顺序。"""
    if explicit is not None:
        return Path(explicit)
    direct = os.environ.get("FD_TEXT_CORE_DATASETS_DIR")
    if direct:
        return Path(direct)
    repo = Path(os.environ.get("FD_TEXT_CORE_REPO", DEFAULT_FD_TEXT_CORE_REPO))
    return repo / "fd_text_core" / "eval" / "datasets"


@dataclass(frozen=True)
class Grade:
    """一条分级相关性标注：某文档对某查询的相关度等级（2=所求，1=相关）。"""

    doc_id: int
    grade: int
    why: str


@dataclass(frozen=True)
class Query:
    """一条标注查询。

    两种标注形态并存（契约向后兼容是硬要求——改既有集会变指纹、断历史趋势）：
      · 二值：单 ``expect_doc_id``（既有三域标注集形态，语义与指纹均不变）
      · 分级：``expect`` 列表（难题集形态，供 nDCG 与「近邻干扰」度量）
    二值查询在指标层等价于单条 grade=2 的分级查询。
    """

    q: str
    intent: str
    why: str
    expect_doc_id: Optional[int] = None
    expect: tuple = ()

    @property
    def graded(self) -> bool:
        return bool(self.expect)

    def grades(self) -> tuple:
        """归一为分级形态（二值 → 单条 grade=2），指标层统一消费。"""
        if self.expect:
            return self.expect
        assert self.expect_doc_id is not None
        return (Grade(doc_id=self.expect_doc_id, grade=2, why=self.why),)

    def max_grade_ids(self) -> tuple:
        """最高等级文档 id（hit/MRR 的判据；分级下可有多个并列）。"""
        gs = self.grades()
        top = max(g.grade for g in gs)
        return tuple(g.doc_id for g in gs if g.grade == top)


@dataclass(frozen=True)
class Dataset:
    """一个垂域的标注查询集。"""

    domain: str
    fingerprint: str
    how_targets_chosen: str
    # 判定强度：目标可判定性的自评（strong=目标唯一可判，weak=主题可能重叠）
    # 报告里如实呈现，不把弱判定的域与强判定的域并列成「谁更好」（design D2）
    judgment_strength: str
    note: str
    queries: tuple
    variant: str = "default"  # default=回归守门集 / hard=分级难题集（进指纹与对比）

    def __len__(self) -> int:
        return len(self.queries)


def compute_fingerprint(path: Union[str, Path]) -> str:
    """数据集指纹 = 文件字节的 sha256 前 16 位。

    用文件字节而非解析后结构：标注集是人工维护的 JSON，格式变化（如缩进/顺序）
    也算「内容变了」——宁可多报「不可直接比较」也不能漏报（design D3）。
    """
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:16]


def dataset_path(
    domain: str,
    variant: str = "default",
    *,
    datasets_dir: Union[str, Path, None] = None,
) -> Path:
    if not _DOMAIN_RE.match(domain or ""):
        raise DatasetError(f"非法垂域名: {domain!r}（应形如 gov / screenplay）")
    name = (
        "annotated_queries.json"
        if variant == "default"
        else f"annotated_queries_{variant}.json"
    )
    return _resolve_datasets_dir(datasets_dir) / domain / name


def list_datasets(
    variant: str = "default",
    *,
    datasets_dir: Union[str, Path, None] = None,
) -> list:
    """枚举已有标注集的垂域（无目录或空目录返回空列表，不是错误）。"""
    root = _resolve_datasets_dir(datasets_dir)
    if not root.is_dir():
        return []
    return sorted(
        p.name
        for p in root.iterdir()
        if p.is_dir() and dataset_path(p.name, variant, datasets_dir=root).is_file()
    )


def _parse_graded(item: dict, where: str, problems: list) -> tuple:
    """解析分级形态 expect 列表；问题追加到 problems（不抛，聚合后一次报）。"""
    raw = item.get("expect")
    if not isinstance(raw, list) or not raw:
        problems.append(f"{where} 的 expect 应为非空数组")
        return ()
    grades: list = []
    for j, g in enumerate(raw):
        gw = f"{where} 的 expect[{j}]"
        if not isinstance(g, dict):
            problems.append(f"{gw} 应为对象")
            continue
        did = g.get("doc_id")
        grade = g.get("grade")
        gwhy = str(g.get("why") or "").strip()
        if not isinstance(did, int) or isinstance(did, bool):
            problems.append(f"{gw} 的 doc_id 应为整数，实得 {did!r}")
            continue
        if grade not in (1, 2):
            problems.append(f"{gw} 的 grade 应为 1 或 2（所求=2/相关=1），实得 {grade!r}")
            continue
        if not gwhy:
            problems.append(f"{gw} 缺 why（该文档为何是此等级）")
            continue
        grades.append(Grade(doc_id=did, grade=grade, why=gwhy))
    if grades and not any(g.grade == 2 for g in grades):
        problems.append(f"{where} 无 grade=2 文档（无「所求」则该条不可判）")
    return tuple(grades)


def _validate_and_build(raw, path: Path, domain: str, *, min_queries: int, variant: str) -> Dataset:
    """校验并构建 Dataset（校验语义与原件逐条一致）。"""
    if not isinstance(raw, dict):
        raise DatasetError(f"标注集 {path} 顶层应为对象，实得 {type(raw).__name__}")

    prov = raw.get("_provenance") or {}
    if not isinstance(prov, dict):
        raise DatasetError(f"标注集 {path} 的 _provenance 应为对象")
    how = str(prov.get("how_targets_chosen") or "").strip()
    if not how:
        raise DatasetError(
            f"标注集 {path} 缺标注口径：_provenance.how_targets_chosen 为空｜"
            "没有口径则『命中即正确』不成立，命中数字无意义（design D2）"
        )
    strength = str(prov.get("judgment_strength") or "").strip()
    if strength not in ("strong", "medium", "weak"):
        raise DatasetError(
            f"标注集 {path} 的 _provenance.judgment_strength 须为 strong/medium/weak"
            f"，实得 {strength!r}｜该字段使报告能如实呈现判定强度（design D2）"
        )

    items = raw.get("queries")
    if not isinstance(items, list) or not items:
        raise DatasetError(f"标注集 {path} 的 queries 应为非空数组")

    queries: list = []
    problems: list = []
    for i, item in enumerate(items):
        where = (
            f"queries[{i}]（q={item.get('q')!r}）" if isinstance(item, dict) else f"queries[{i}]"
        )
        if not isinstance(item, dict):
            problems.append(f"{where} 应为对象")
            continue
        q = str(item.get("q") or "").strip()
        why = str(item.get("why") or "").strip()
        intent = str(item.get("intent") or "").strip()
        if not q:
            problems.append(f"{where} 缺 q（查询文本）")
        if not intent:
            problems.append(f"{where} 缺 intent（意图分类）")

        if "expect" in item:
            grades = _parse_graded(item, where, problems)
            if q and intent and grades:
                queries.append(
                    Query(
                        q=q,
                        intent=intent,
                        why=why or f"分级标注（{len(grades)} 篇）",
                        expect=grades,
                    )
                )
            continue

        did = item.get("expect_doc_id")
        if not why:
            problems.append(f"{where} 缺 why（判定依据）")
        if not isinstance(did, int) or isinstance(did, bool):
            problems.append(f"{where} 的 expect_doc_id 应为整数，实得 {did!r}")
        if q and why and intent and isinstance(did, int) and not isinstance(did, bool):
            queries.append(Query(q=q, expect_doc_id=did, intent=intent, why=why))

    if problems:
        raise DatasetError(
            f"标注集 {path} 有 {len(problems)} 处不合契约：\n  - " + "\n  - ".join(problems)
        )
    if len(queries) < min_queries:
        raise DatasetError(
            f"标注集 {path} 仅 {len(queries)} 条查询，低于要求的 {min_queries} 条｜"
            "样本太少则指标无统计意义"
        )

    return Dataset(
        domain=domain,
        fingerprint=compute_fingerprint(path),
        how_targets_chosen=how,
        judgment_strength=strength,
        note=str(prov.get("note") or "").strip(),
        queries=tuple(queries),
        variant=variant,
    )


def load_dataset(
    domain: str,
    *,
    min_queries: int = 10,
    variant: str = "default",
    datasets_dir: Union[str, Path, None] = None,
) -> Dataset:
    """加载并校验一个垂域的标注集。不合契约即 DatasetError（指明缺什么）。"""
    path = dataset_path(domain, variant, datasets_dir=datasets_dir)
    if not path.is_file():
        raise DatasetError(
            f"垂域 {domain}（variant={variant}）无标注集：{path} 不存在｜"
            "修复=按契约新增该文件（见 text-retrieval-eval spec 的标注查询集要求）"
        )
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise DatasetError(f"标注集 {path} 不是合法 JSON：{exc}") from exc
    return _validate_and_build(raw, path, domain, min_queries=min_queries, variant=variant)


def load_dataset_file(
    path: Union[str, Path],
    *,
    domain: Optional[str] = None,
    min_queries: int = 10,
    variant: str = "default",
) -> Dataset:
    """直接从单个标注集文件加载（fixture/自定义目录的便利入口）。

    domain 缺省取父目录名，与原件「datasets/<domain>/annotated_queries*.json」
    的目录布局一致。校验、指纹、报错语义与 :func:`load_dataset` 完全相同。
    """
    path = Path(path)
    if not path.is_file():
        raise DatasetError(f"标注集文件不存在：{path}")
    if domain is None:
        domain = path.parent.name
    if not _DOMAIN_RE.match(domain or ""):
        raise DatasetError(f"非法垂域名: {domain!r}（应形如 gov / screenplay）")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise DatasetError(f"标注集 {path} 不是合法 JSON：{exc}") from exc
    return _validate_and_build(raw, path, domain, min_queries=min_queries, variant=variant)


def load_all(
    *,
    min_queries: int = 10,
    variant: str = "default",
    datasets_dir: Union[str, Path, None] = None,
) -> list:
    """加载全部已交付的标注集（某个域不合契约即抛错，不静默跳过）。"""
    return [
        load_dataset(d, min_queries=min_queries, variant=variant, datasets_dir=datasets_dir)
        for d in list_datasets(variant, datasets_dir=datasets_dir)
    ]
