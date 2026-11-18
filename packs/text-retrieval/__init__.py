"""text-retrieval 域包：迁入的文本检索评测尺（数据重尺子）。

真源（只读，一个字节不改）：
  · 契约层 ``/Users/chengsishi/finddata/fd-text-core/fd_text_core/eval/dataset.py``
  · 跑分层 ``/Users/chengsishi/finddata/fd-text-core/fd_text_core/eval/runner.py``
  · 持久层 ``/Users/chengsishi/finddata/fd-text-core/fd_text_core/eval/store.py``
    （原表 DDL：migrations/versions/0006_eval_runs.py、0008_eval_ndcg_variant.py）

迁入 = 逻辑复制进本包，**不 import fd_text_core 包**（零跨仓代码依赖）；
标注集数据文件也不复制进本仓（正文数据留在原仓，运行时只读引用或由调用方
传入目录，见 adapters.py）。等价双跑与「哪些腿无法双跑」见本目录 README.md。
"""

from .adapters import (
    Dataset,
    DatasetError,
    Grade,
    Query,
    compute_fingerprint,
    dataset_path,
    list_datasets,
    load_all,
    load_dataset,
)
from .scorer import (
    CHANNELS,
    EvalReport,
    compare_with_previous,
    compute_config_fingerprint,
    latest_retrieval_run,
    list_retrieval_trend,
    ndcg_at_k,
    previous_from_run,
    run_eval,
    store_retrieval_run,
)

__all__ = [
    "CHANNELS",
    "Dataset",
    "DatasetError",
    "EvalReport",
    "Grade",
    "Query",
    "compare_with_previous",
    "compute_config_fingerprint",
    "compute_fingerprint",
    "dataset_path",
    "latest_retrieval_run",
    "list_datasets",
    "list_retrieval_trend",
    "load_all",
    "load_dataset",
    "ndcg_at_k",
    "previous_from_run",
    "run_eval",
    "store_retrieval_run",
]
