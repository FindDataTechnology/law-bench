"""符合性适配器：本仓的五个端口跑在一次性 PG 库上（add-law-bench-conformance-adapter）。

**为什么是 PG 而不是内存**：本仓的端口就是 psycopg + PG 方言（JSONB、`RETURNING`、
`now()`）。用内存沙箱检查不到这些映射，闸门就成了「检查内核自带的内存端口」，那是
假绿。所以每个沙箱开一个一次性库（`law_bench_gate_<pid>_<n>`），跑 `ensure_schema`，
用完在进程退出时删掉。

**作用域**：内核按 `scope_id` 调用端口，这一面的作用域就是域键。沙箱给每个没见过
的作用域**现造模板 + 域**（`mint`），因此一个连接可以服务套件里的
`scope-a`/`scope-b`/`scope-fold`… 生产调用不带 `mint`，未知域键照旧报错。

**清理**：`AdapterSpec.sandbox()` 没有 teardown 钩子，所以一次性库登记在
`atexit` 里统一删。历史上本机见过 8 个 `law_bench_test_*` 残留（含
`law_bench_test_81541_212`），正是中断时没人清的结果——这里显式收尾。

用法::

    python scripts/ontology_gate.py --adapter law-bench-internal
"""

from __future__ import annotations

import atexit
import itertools
import os
import sys
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse, urlunparse

# 本仓有两套导入根：``src``（``import bench``）与**仓根**（``import src.bench``）。
# ``src/eval/store.py`` 用的是后者（``from src.settings import DEFAULT_DB``），所以
# 两个根都必须可用——只加 ``src`` 会让 ``eval.store`` 在 `src.settings` 上炸。
_REPO_ROOT = Path(__file__).resolve().parents[2]
for _root in (str(_REPO_ROOT), str(_REPO_ROOT / "src")):
    if _root not in sys.path:
        sys.path.insert(0, _root)

import psycopg  # noqa: E402
from fd_ontology_kernel.kernel import Kernel  # noqa: E402
from psycopg.rows import dict_row  # noqa: E402

from . import kernel_ports, templates, workspaces  # noqa: E402
from .kernel_ports import DECLARATION  # noqa: E402

try:  # pragma: no cover - 取决于本模块被加载成 bench.* 还是 src.bench.*
    from src.eval.store import ensure_schema
except ImportError:  # pragma: no cover
    from eval.store import ensure_schema  # type: ignore[no-redef]

#: 沙箱域模板：覆盖三种实体（含条款，好让「条款父键」断言真正执行而不是被跳过）。
SANDBOX_SCHEMA: dict[str, Any] = {
    "entity_types": ["company", "indicator", "clause"],
    "concept_structures": {},
    "relationship_kinds": ["belongs_to", "cites"],
    "tier_vocabulary": ["raw", "bronze", "silver", "gold"],
    "sensitivity_vocabulary": ["public", "internal", "confidential"],
    "corpus_declaration": {},
}

_counter = itertools.count(1)
_created: list[str] = []


def _base_dsn() -> str:
    """与 ``eval.db._dsn`` **同一份**解析（env + ``.env``），不另立一套。

    只读 ``os.environ`` 会漏掉 ``.env``：从仓根跑闸门时它就退到我猜的默认串，
    而默认串的口令是错的，于是闸门报「连不上库」而不是「没配库」——一份凭据两个
    读者，迟早各说各话。``_dsn()`` 缺配置时抛 ``ConfigError``，正是要的行为。
    """
    from src.eval.db import _dsn

    return _dsn()


def _with_db(dsn: str, db_name: str) -> str:
    parts = urlparse(dsn)
    return urlunparse(parts._replace(path=f"/{db_name}"))


def _maint_dsn() -> str:
    return _with_db(_base_dsn(), "postgres")


def _create_db(name: str) -> str:
    conn = psycopg.connect(_maint_dsn())
    conn.autocommit = True
    try:
        conn.execute(f'CREATE DATABASE {name}')
    finally:
        conn.close()
    _created.append(name)
    atexit.register(_drop_db, name)
    return _with_db(_base_dsn(), name)


def _drop_db(name: str) -> None:
    """删一次性库（幂等；已经被删过就跳过）。

    必须 ``WITH (FORCE)``：``AdapterSpec.sandbox()`` 没有 teardown 钩子，沙箱连接
    会活到进程结束。普通 ``DROP DATABASE`` 遇到活动连接直接失败（实测留下
    ``law_bench_gate_<pid>_<n>`` 残壳），收尾就成了空话。
    """
    try:
        conn = psycopg.connect(_maint_dsn())
    except Exception:  # noqa: BLE001 - 收尾失败不该掩盖原本的失败
        return
    conn.autocommit = True
    try:
        conn.execute(f'DROP DATABASE IF EXISTS {name} WITH (FORCE)')
        if name in _created:
            _created.remove(name)
    except Exception:  # noqa: BLE001
        pass
    finally:
        conn.close()


def _apply_schema(conn: Any) -> None:
    """在**沙箱连接**上建表，复用 ``eval.store.ensure_schema``（不复制 DDL）。

    注意这里传的是**连接对象**，不是 DSN。``ensure_schema`` 内部走
    ``eval.db.connect(db_path)``，而 ``connect()`` 只认「传进来的是不是活连接」，
    其余一律 ``_open_fresh()``——它**不接收** DSN，从 env 重新解析。所以
    ``ensure_schema(dsn)`` 只会在 env 指向的默认库上跑一遍幂等 DDL，沙箱库仍然是
    空的（实测报 ``relation "ontology_templates" does not exist``）；传连接就对，
    这也正是 ``tests/conftest.py`` 的 ``empty_db`` 用法。

    复用而不是复制 DDL 的理由：内核表还在长（``LIBRARY_SCHEMA`` 就在
    ``WORKSPACE_SCHEMA`` 之后追加列）。复制一份，上游加表时闸门会静默漏检。
    """
    ensure_schema(db_path=conn)


def _mint(conn: Any, scope_id: str) -> Mapping[str, Any]:
    """给一个没见过的沙箱作用域现造模板 + 域。"""
    template_name = f"gate-{scope_id}"
    template = templates.create_template(
        conn, name=template_name, schema=SANDBOX_SCHEMA, created_by="conformance-gate"
    )
    return workspaces.instantiate_domain(
        conn,
        key=scope_id,
        name=f"Gate {scope_id}",
        template_name=template_name,
        template_version=template.get("version"),
        created_by="conformance-gate",
    )


def _sandbox() -> Kernel:
    import tempfile  # noqa: F401 - 保持与内核沙箱同一「可丢弃」语义的注释锚点

    name = f"law_bench_gate_{os.getpid()}_{next(_counter)}"
    dsn = _create_db(name)
    conn = psycopg.connect(dsn, row_factory=dict_row)
    _apply_schema(conn)

    seed_scope = "gate-seed"
    seed = _mint(conn, seed_scope)
    conn.commit()

    def mint(scope_id: str) -> Mapping[str, Any]:
        domain = _mint(conn, scope_id)
        conn.commit()
        return domain

    return kernel_ports.kernel_for(conn, domain=seed, mint=mint)


def build():
    """``adapters.json`` 点名的工厂。"""
    from fd_ontology_kernel.conformance.spec import AdapterSpec

    return AdapterSpec(
        name="law-bench-internal",
        system=DECLARATION.system,
        declaration=DECLARATION,
        sandbox=_sandbox,
        notes=(
            "domain authoring surface (key-addressed, shape 2); one throwaway PG "
            "database per sandbox, dropped at exit"
        ),
    )
