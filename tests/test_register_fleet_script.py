"""迁移脚本 register_fleet.py 的守门行为（add-fleet-execution-loop §2.5）。

脚本是这次切换里唯一「机器读历史、人做决定」的交界，所以它必须守住三件事：

- **不自动登记**：``--from-observed`` 只打印。把「见过的一串字」变成「身份」正是
  这个 change 要拆掉的东西，脚本不能自己做这个替换。
- **不发明凭据**：``--apply`` 没拿到**现有** token 就拒绝。现场登记凭证会把正在
  跑的舰队当场切断，而且一个编出来的 hash 谁也进不来。
- **迁移计数把 NULL 单列**：列还不存在时写入的行没有任何判定可读，它们是货真价实
  的遗留，但不能伪装成某个 verdict——否则人会以为「只是少改了一个字段」。
"""

from __future__ import annotations

import importlib.util
import hashlib
from pathlib import Path

import pytest

from src.bench import distribution, proposals, templates, workspaces
from src.bench.promotion import SENSITIVITY_LEVELS
from src.bench.tiers import TIERS

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "register_fleet.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("register_fleet_script", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def conn(empty_db):  # noqa: F811 - provided by tests/conftest.py
    from src.eval.store import ensure_schema

    ensure_schema(db_path=empty_db)
    schema = {
        "entity_types": ["company"],
        "concept_structures": {},
        "relationship_kinds": ["belongs_to"],
        "tier_vocabulary": list(TIERS),
        "sensitivity_vocabulary": list(SENSITIVITY_LEVELS),
        "corpus_declaration": {},
    }
    templates.create_template(conn=empty_db, name="tpl", schema=schema, created_by="t")
    workspaces.instantiate_domain(
        conn=empty_db, key="legal", name="法律域", template_name="tpl",
        template_version=None, created_by="t",
    )
    yield empty_db


def _borrowed(conn):
    """main() 的 finally 会 close 连接；测试里这条连接归 fixture，包一层不让它被关。"""
    from src.eval.db import _BorrowedConn

    return _BorrowedConn(conn)


def _submit(conn, source, key):
    proposals.submit(
        conn, domain_key="legal", source=source, kind="company", external_key=key,
        body="b", evidence={"quote": "q-" + key}, submitted_by=source,
        via="in_process",
    )


# --------------------------------------------------------------- --legacy


def test_legacy_says_none_when_everything_passes(conn, capsys, monkeypatch):
    monkeypatch.delenv("BENCH_SUBMITTER_MODE", raising=False)
    script = _load_script()
    monkeypatch.setattr(script, "_connect", lambda: _borrowed(conn))
    assert script.main(["--legacy"]) == 0
    assert "legacy sources: none" in capsys.readouterr().out


def test_a_row_written_before_the_column_is_reported_as_unknown(conn, capsys):
    """NULL verdict 不能装成某个具体结论，也不能被漏掉。"""
    conn.execute(
        "INSERT INTO domain_proposals (domain_id, source, kind, external_key, body, evidence, "
        "evidence_digest, state, submitted_by, sources) "
        "SELECT id, 'extract:qwen:2025-10', 'company', 'lg-1', 'b', '{}'::jsonb, 'd1', "
        "'pending', 'extract:qwen:2025-10', '[\"extract:qwen:2025-10\"]'::jsonb FROM domains"
    )
    conn.commit()

    script = _load_script()
    monkeyio = pytest.MonkeyPatch()
    monkeyio.setattr(script, "_connect", lambda: _borrowed(conn))
    try:
        assert script.main(["--legacy"]) == 0
    finally:
        monkeyio.undo()

    out = capsys.readouterr().out
    assert "extract:qwen:2025-10" in out
    assert "(历史行·无判定)" in out
    assert "1 行没有判定" in out


# ------------------------------------------------------- --from-observed


def test_observed_lists_unregistered_and_registered_side_by_side(conn, capsys):
    distribution.register_consumer(
        conn, name="known-fleet", domains=["legal"],
        token_hash=hashlib.sha256(b"t").hexdigest(), created_by="t",
        kind="fleet", fleet_ref="fleet_known",
    )
    _submit(conn, "fleet:fleet_known/p1", "k1")
    conn.execute(
        "INSERT INTO domain_proposals (domain_id, source, kind, external_key, body, evidence, "
        "evidence_digest, state, submitted_by, sources) "
        "SELECT id, 'fleet:credential-probe/post_probe', 'company', 'probe-1', 'b', "
        "'{}'::jsonb, 'd2', 'pending', 'probe', '[\"fleet:credential-probe/post_probe\"]'::jsonb "
        "FROM domains"
    )
    conn.commit()

    script = _load_script()
    mp = pytest.MonkeyPatch()
    mp.setattr(script, "_connect", lambda: _borrowed(conn))
    try:
        assert script.main(["--from-observed"]) == 0
    finally:
        mp.undo()

    out = capsys.readouterr().out
    assert "fleet_known" in out and "已登记" in out
    assert "credential-probe" in out and "未登记" in out
    # 这句是脚本的要害：它明说这份清单不能直接 apply。
    assert "不是一份可以直接 apply 的清单" in out
    assert conn.execute("SELECT count(*) AS n FROM distribution_consumers").fetchone()["n"] == 1


def test_observed_surfaces_machine_registrations_that_have_no_fleet_ref(conn, capsys):
    """产库那种形态：老登记是 `machine` 档、没有 fleet_ref，按 ref 一律显示「未登记」。

    不替人推断「哪条 machine 就是哪支舰队」，但必须把「给它的 token 即可原地升级」
    这条路摆出来——否则读到「未登记」的人下一步一定是去要一枚新凭据。
    """
    _machine(conn)  # name=ontology-fleet-win, kind=machine
    # 历史行直接插：这正是「变更之前写入、当时还没有校验」的那种行。
    conn.execute(
        "INSERT INTO domain_proposals (domain_id, source, kind, external_key, body, evidence, "
        "evidence_digest, state, submitted_by, sources) "
        "SELECT id, 'fleet:fleet_1794335712751_wfa3ww/p1', 'company', 'k-machine', 'b', "
        "'{}'::jsonb, 'd-machine', 'pending', 'fleet:fleet_1794335712751_wfa3ww/p1', "
        "'[\"fleet:fleet_1794335712751_wfa3ww/p1\"]'::jsonb FROM domains"
    )
    conn.commit()

    script = _load_script()
    mp = pytest.MonkeyPatch()
    mp.setattr(script, "_connect", lambda: _borrowed(conn))
    try:
        assert script.main(["--from-observed"]) == 0
    finally:
        mp.undo()

    out = capsys.readouterr().out
    assert "fleet_1794335712751_wfa3ww" in out and "未登记" in out
    assert "1 条 `machine` 档登记" in out
    assert "ontology-fleet-win" in out
    assert "原地升级" in out and "不要吊销重登" in out


# ------------------------------------------------------------- --apply


def test_apply_without_the_existing_token_refuses(conn, capsys, monkeypatch):
    monkeypatch.delenv("BENCH_FLEET_TOKEN", raising=False)
    script = _load_script()
    monkeypatch.setattr(script, "_connect", lambda: _borrowed(conn))

    assert script.main(["--fleet-ref", "fleet_new", "--domains", "legal", "--apply"]) == 1
    err = capsys.readouterr().err
    assert "will not invent one" in err
    assert conn.execute("SELECT count(*) AS n FROM distribution_consumers").fetchone()["n"] == 0


def test_apply_refuses_a_ref_that_is_already_live(conn, capsys, monkeypatch):
    distribution.register_consumer(
        conn, name="already", domains=["legal"],
        token_hash=hashlib.sha256(b"t").hexdigest(), created_by="t",
        kind="fleet", fleet_ref="fleet_dup",
    )
    monkeypatch.setenv("BENCH_FLEET_TOKEN", "some-token")
    script = _load_script()
    monkeypatch.setattr(script, "_connect", lambda: _borrowed(conn))

    assert script.main(["--fleet-ref", "fleet_dup", "--domains", "legal", "--apply"]) == 1
    assert "already registered" in capsys.readouterr().err


def test_dry_run_writes_nothing(conn, capsys, monkeypatch):
    monkeypatch.setenv("BENCH_FLEET_TOKEN", "some-token")
    script = _load_script()
    monkeypatch.setattr(script, "_connect", lambda: _borrowed(conn))

    assert script.main(["--fleet-ref", "fleet_new", "--domains", "legal"]) == 0
    assert "dry run" in capsys.readouterr().out
    assert conn.execute("SELECT count(*) AS n FROM distribution_consumers").fetchone()["n"] == 0


def test_apply_registers_a_fleet_bound_to_its_domain(conn, monkeypatch):
    monkeypatch.setenv("BENCH_FLEET_TOKEN", "some-token")
    script = _load_script()
    monkeypatch.setattr(script, "_connect", lambda: _borrowed(conn))

    assert script.main([
        "--fleet-ref", "fleet_new", "--name", "new-fleet", "--domains", "legal", "--apply",
    ]) == 0

    row = distribution.list_consumers(conn)[0]
    assert (row["kind"], row["fleet_ref"], row["domains"]) == ("fleet", "fleet_new", ["legal"])

    # 登记之后这条来源立刻可以提交了——严格档不报错本身就是判据，
    # 落库的 verdict 再确认一次。
    proposals.submit(
        conn, domain_key="legal", source="fleet:fleet_new/post_1", kind="company",
        external_key="k9", body="b", evidence={"quote": "q"},
        submitted_by="fleet:fleet_new/post_1", via="in_process",
    )
    verdict = conn.execute(
        "SELECT submitter_verdict FROM domain_proposals WHERE external_key = 'k9'"
    ).fetchone()["submitter_verdict"]
    assert verdict == "ok"


# ------------------------------------- --apply 撞上既有登记：原地升级，不重登记


def _machine(conn, *, name="ontology-fleet-win", token=b"win-token", domains=("legal",)):
    return distribution.register_consumer(
        conn, name=name, domains=list(domains),
        token_hash=hashlib.sha256(token).hexdigest(), created_by="before-the-change",
    )


def test_apply_promotes_the_registration_that_already_holds_the_token(
    conn, capsys, monkeypatch
):
    """产库那条 `ontology-fleet-win` 就是这种形态：真舰队，但登记在 machine 档。

    `register_consumer` 只会新建，撞 name/token_hash 两条唯一约束；吊销重登记又会
    换掉 token，把还在跑的舰队切断。所以脚本必须走原地升级：只动 kind / fleet_ref。
    """
    before = _machine(conn)
    monkeypatch.setenv("BENCH_FLEET_TOKEN", "win-token")
    script = _load_script()
    monkeypatch.setattr(script, "_connect", lambda: _borrowed(conn))

    assert script.main([
        "--fleet-ref", "fleet_1794335712751_wfa3ww",
        "--domains", "legal", "--apply",
    ]) == 0
    out = capsys.readouterr().out
    assert "promoted" in out and "凭据未变" in out

    after = distribution.list_consumers(conn)[0]
    assert (after["id"], after["name"]) == (before["id"], before["name"])
    assert after["token_hash"] == before["token_hash"]  # 凭据一个字没改
    assert after["created_by"] == "before-the-change"
    assert (after["kind"], after["fleet_ref"], after["domains"]) == (
        "fleet", "fleet_1794335712751_wfa3ww", ["legal"],
    )

    # 升级后这条来源在严格档里立刻可提交——这才是升级的全部意义。
    _submit(conn, "fleet:fleet_1794335712751_wfa3ww/post_1", "k-promoted")
    verdict = conn.execute(
        "SELECT submitter_verdict FROM domain_proposals WHERE external_key = 'k-promoted'"
    ).fetchone()["submitter_verdict"]
    assert verdict == "ok"


def test_promotion_dry_run_reports_the_upgrade_and_writes_nothing(conn, capsys, monkeypatch):
    _machine(conn)
    monkeypatch.setenv("BENCH_FLEET_TOKEN", "win-token")
    script = _load_script()
    monkeypatch.setattr(script, "_connect", lambda: _borrowed(conn))

    assert script.main(["--fleet-ref", "fleet_win", "--domains", "legal"]) == 0
    out = capsys.readouterr().out
    assert "would PROMOTE" in out and "dry run" in out
    row = distribution.list_consumers(conn)[0]
    assert (row["kind"], row["fleet_ref"]) == ("machine", None)


def test_promoting_twice_says_nothing_to_change(conn, capsys, monkeypatch):
    _machine(conn)
    monkeypatch.setenv("BENCH_FLEET_TOKEN", "win-token")
    script = _load_script()
    monkeypatch.setattr(script, "_connect", lambda: _borrowed(conn))
    args = ["--fleet-ref", "fleet_win", "--domains", "legal", "--apply"]

    assert script.main(args) == 0
    capsys.readouterr()
    assert script.main(args) == 0
    assert "nothing to change" in capsys.readouterr().out
    assert conn.execute("SELECT count(*) AS n FROM distribution_consumers").fetchone()["n"] == 1


def test_promotion_refuses_a_name_that_is_not_the_stored_one(conn, capsys, monkeypatch):
    """拿不出别的凭据却要改名——那不是升级，是拿这枚 token 冒充另一条登记。"""
    _machine(conn)
    monkeypatch.setenv("BENCH_FLEET_TOKEN", "win-token")
    script = _load_script()
    monkeypatch.setattr(script, "_connect", lambda: _borrowed(conn))

    assert script.main([
        "--fleet-ref", "fleet_win", "--name", "somebody-else",
        "--domains", "legal", "--apply",
    ]) == 1
    assert "属于登记" in capsys.readouterr().err
    assert distribution.list_consumers(conn)[0]["kind"] == "machine"


def test_promotion_refuses_to_change_domains_silently(conn, capsys, monkeypatch):
    _machine(conn, domains=("legal",))
    monkeypatch.setenv("BENCH_FLEET_TOKEN", "win-token")
    script = _load_script()
    monkeypatch.setattr(script, "_connect", lambda: _borrowed(conn))

    assert script.main([
        "--fleet-ref", "fleet_win", "--domains", "knowledge", "--apply",
    ]) == 1
    assert "--set-domains" in capsys.readouterr().err
    assert distribution.list_consumers(conn)[0]["domains"] == ["legal"]

    # 加了 --set-domains 才改，而且改的是同一条行（id 不变）。
    before_id = distribution.list_consumers(conn)[0]["id"]
    assert script.main([
        "--fleet-ref", "fleet_win", "--domains", "knowledge", "--set-domains", "--apply",
    ]) == 0
    row = distribution.list_consumers(conn)[0]
    assert (row["id"], row["kind"], row["domains"]) == (before_id, "fleet", ["knowledge"])


def test_promotion_refuses_a_revoked_registration(conn, capsys, monkeypatch):
    _machine(conn)
    distribution.revoke_consumer(conn, name="ontology-fleet-win")
    monkeypatch.setenv("BENCH_FLEET_TOKEN", "win-token")
    script = _load_script()
    monkeypatch.setattr(script, "_connect", lambda: _borrowed(conn))

    assert script.main(["--fleet-ref", "fleet_win", "--domains", "legal", "--apply"]) == 1
    assert "已吊销" in capsys.readouterr().err
    assert distribution.list_consumers(conn)[0]["kind"] == "machine"


def test_promotion_refuses_a_fleet_ref_another_registration_already_claims(
    conn, capsys, monkeypatch
):
    distribution.register_consumer(
        conn, name="taken", domains=["legal"],
        token_hash=hashlib.sha256(b"other").hexdigest(), created_by="t",
        kind="fleet", fleet_ref="fleet_win",
    )
    _machine(conn)
    monkeypatch.setenv("BENCH_FLEET_TOKEN", "win-token")
    script = _load_script()
    monkeypatch.setattr(script, "_connect", lambda: _borrowed(conn))

    assert script.main(["--fleet-ref", "fleet_win", "--domains", "legal", "--apply"]) == 1
    assert "占用" in capsys.readouterr().err
    kinds = {c["name"]: c["kind"] for c in distribution.list_consumers(conn)}
    assert kinds == {"taken": "fleet", "ontology-fleet-win": "machine"}


def test_a_name_taken_by_another_credential_is_refused_before_anything_is_written(
    conn, capsys, monkeypatch
):
    """库里叫这个名字的那条不是这枚 token 的——dry run 也得当场拒绝。

    一份「会说会登记」的 dry run 比没有 dry run 更坏：人会照着它去按 --apply。
    """
    _machine(conn)
    monkeypatch.setenv("BENCH_FLEET_TOKEN", "different-token")
    script = _load_script()
    monkeypatch.setattr(script, "_connect", lambda: _borrowed(conn))
    args = ["--fleet-ref", "fleet_win", "--name", "ontology-fleet-win", "--domains", "legal"]

    assert script.main(args) == 1
    assert "已被 id=" in capsys.readouterr().err
    assert script.main(args + ["--apply"]) == 1
    assert len(distribution.list_consumers(conn)) == 1


# ------------------------------------------------ --schema（§6.2 的核对面）


def test_schema_says_all_present_on_a_booted_database(conn, capsys, monkeypatch):
    """`ensure_schema` 跑过的库＝本变更之后的形状：六列两索引都在。"""
    script = _load_script()
    monkeypatch.setattr(script, "_connect", lambda: _borrowed(conn))

    assert script.main(["--schema"]) == 0
    out = capsys.readouterr().out
    for column in ("assignee_kind", "assignee_ref", "kind", "fleet_ref", "origin", "runner_ref"):
        assert f"✓ " in out and column in out
    assert "distribution_consumers_fleet_ref_uk" in out
    assert "domain_agent_runs_runner_ref_key" in out
    assert "六列两索引都在" in out


def test_schema_goes_red_on_a_database_without_the_change(empty_db, capsys, monkeypatch):
    """没有这张表也能判：缺项必须逐条 ✗ 且 EXIT=1。

    这条测试同时钉住「判据能红」——只验正例的话，一个恒返回 0 的检查也会全绿。
    """
    script = _load_script()
    monkeypatch.setattr(script, "_connect", lambda: _borrowed(empty_db))

    assert script.main(["--schema"]) == 1
    captured = capsys.readouterr()
    assert captured.out.count("✗") == 8          # 六列 + 两索引
    assert "还没有本变更的 schema" in captured.err
    assert "crash-loop" in captured.err          # 修法要指明，不然只会去手补列


def test_schema_checks_the_shape_of_the_partial_indexes(conn, capsys, monkeypatch):
    """索引「在」不算数：少了 UNIQUE 或少了 WHERE 列，等于没约束住。"""
    conn.execute("DROP INDEX distribution_consumers_fleet_ref_uk")
    conn.commit()
    script = _load_script()
    monkeypatch.setattr(script, "_connect", lambda: _borrowed(conn))

    assert script.main(["--schema"]) == 1
    assert "distribution_consumers_fleet_ref_uk" in capsys.readouterr().out


# ------------------------------------------------- 计数怎么读（不是「数到 0」）


def test_legacy_output_says_the_counter_never_reaches_zero(conn, capsys):
    """历史行不会消失，所以「等它变 0」是错判据——命令必须自己说清怎么读。"""
    distribution.register_consumer(
        conn, name="fleet-a", domains=["legal"],
        token_hash=hashlib.sha256(b"a").hexdigest(), created_by="t",
        kind="fleet", fleet_ref="fleet_a",
    )
    _submit(conn, "fleet:fleet_a/p1", "k1")
    conn.execute(
        "INSERT INTO domain_proposals (domain_id, source, kind, external_key, body, evidence, "
        "evidence_digest, state, submitted_by, sources) "
        "SELECT id, 'fleet:credential-probe/post_probe', 'company', 'probe-1', 'b', "
        "'{}'::jsonb, 'd2', 'pending', 'probe', '[\"fleet:credential-probe/post_probe\"]'::jsonb "
        "FROM domains"
    )
    conn.execute(
        "UPDATE domain_proposals SET submitter_verdict = 'unregistered' "
        "WHERE source = 'fleet:credential-probe/post_probe'"
    )
    conn.commit()

    script = _load_script()
    mp = pytest.MonkeyPatch()
    mp.setattr(script, "_connect", lambda: _borrowed(conn))
    try:
        assert script.main(["--legacy"]) == 0
    finally:
        mp.undo()

    out = capsys.readouterr().out
    assert "不要**等它变成 0" in out or "不要" in out
    assert "历史行不会消失" in out
    # 探针这类历史来源必须被单列出来，让人判断「还有没有客户端在跑」。
    assert "credential-probe" in out
    assert "现在**再提交会被拒" in out


def test_legacy_says_clear_when_nothing_would_be_refused(conn, capsys):
    distribution.register_consumer(
        conn, name="fleet-a", domains=["legal"],
        token_hash=hashlib.sha256(b"a").hexdigest(), created_by="t",
        kind="fleet", fleet_ref="fleet_a",
    )
    _submit(conn, "fleet:fleet_a/p1", "k1")   # 已登记、判定 ok
    script = _load_script()
    mp = pytest.MonkeyPatch()
    mp.setattr(script, "_connect", lambda: _borrowed(conn))
    try:
        assert script.main(["--legacy"]) == 0
    finally:
        mp.undo()
    assert "legacy sources: none" in capsys.readouterr().out


# ------------------------------ --promote-by-name（明文丢失时的升级路径，11-14 实况）


def test_promote_by_name_upgrades_without_needing_the_credential(conn, capsys, monkeypatch):
    """产库那条登记的真实处境：真舰队，凭据明文只在登记那一刻显示过一次。

    `distribution_pull_events` 全表只有创建后 10 秒那一条探针 ⇒ 明文确实不可得。
    升级不动 token_hash，所以「拿不出凭据」在这里不构成风险——这条测试钉住三件事：
    dry run 不写、apply 只动 kind/fleet_ref、原持有方的凭据照旧可用。
    """
    before = _machine(conn)
    script = _load_script()
    monkeypatch.setattr(script, "_connect", lambda: _borrowed(conn))
    args = ["--promote-by-name", "--fleet-ref", "fleet_1794335712751_wfa3ww",
            "--name", "ontology-fleet-win"]

    assert script.main(args) == 0
    assert "would promote in place" in capsys.readouterr().out
    assert distribution.list_consumers(conn)[0]["kind"] == "machine"  # dry run 没写

    assert script.main(args + ["--apply"]) == 0
    out = capsys.readouterr().out
    assert "promoted" in out and "凭据未变" in out

    after = distribution.list_consumers(conn)[0]
    assert (after["id"], after["name"]) == (before["id"], before["name"])
    assert after["token_hash"] == before["token_hash"]  # 升级不动凭据
    assert (after["kind"], after["fleet_ref"], after["domains"]) == (
        "fleet", "fleet_1794335712751_wfa3ww", ["legal"],
    )
    # 原持有方照旧能按 token 被认出来
    assert distribution.get_consumer_by_token_hash(
        conn, token_hash=hashlib.sha256(b"win-token").hexdigest()
    )["name"] == "ontology-fleet-win"


def test_promote_by_name_refuses_a_revoked_registration(conn, capsys, monkeypatch):
    _machine(conn)
    distribution.revoke_consumer(conn, name="ontology-fleet-win")
    script = _load_script()
    monkeypatch.setattr(script, "_connect", lambda: _borrowed(conn))
    rc = script.main(["--promote-by-name", "--fleet-ref", "fleet_x",
                      "--name", "ontology-fleet-win", "--apply"])
    assert rc == 1
    assert "已吊销" in capsys.readouterr().err
    assert distribution.list_consumers(conn)[0]["kind"] == "machine"


def test_promote_by_name_refuses_a_name_it_cannot_find(conn, capsys, monkeypatch):
    script = _load_script()
    monkeypatch.setattr(script, "_connect", lambda: _borrowed(conn))
    rc = script.main(["--promote-by-name", "--fleet-ref", "fleet_x", "--name", "nope", "--apply"])
    assert rc == 1
    assert "没有名为" in capsys.readouterr().err


# ------------------------------------------- --rotate-token（明文丢失后的补凭据）


def test_rotate_token_replaces_the_digest_and_prints_the_value_once(conn, capsys, monkeypatch):
    before = _machine(conn)
    monkeypatch.setenv("BENCH_NEW_FLEET_TOKEN", "lbc_brand-new-value")
    script = _load_script()
    monkeypatch.setattr(script, "_connect", lambda: _borrowed(conn))

    assert script.main(["--rotate-token", "--name", "ontology-fleet-win",
                        "--token-env", "BENCH_NEW_FLEET_TOKEN", "--apply"]) == 0
    out = capsys.readouterr().out

    # 明文只出现一次，且 id/name/domains 一个字没动
    assert out.count("lbc_brand-new-value") == 1
    after = distribution.list_consumers(conn)[0]
    assert (after["id"], after["name"], after["domains"]) == (
        before["id"], before["name"], before["domains"],
    )
    assert after["token_hash"] != before["token_hash"]
    # 新值能认人，旧值认不到
    assert distribution.get_consumer_by_token_hash(
        conn, token_hash=hashlib.sha256(b"lbc_brand-new-value").hexdigest()
    ) is not None
    assert distribution.get_consumer_by_token_hash(
        conn, token_hash=hashlib.sha256(b"win-token").hexdigest()
    ) is None


def test_rotate_token_dry_run_never_prints_a_credential(conn, capsys, monkeypatch):
    """还没写库的值不该出现在输出里：dry run 打印明文等于把「没签发的凭据」发出去。"""
    before = _machine(conn)
    monkeypatch.setenv("BENCH_NEW_FLEET_TOKEN", "lbc_should-not-leak")
    script = _load_script()
    monkeypatch.setattr(script, "_connect", lambda: _borrowed(conn))

    assert script.main(["--rotate-token", "--name", "ontology-fleet-win",
                        "--token-env", "BENCH_NEW_FLEET_TOKEN"]) == 0
    out = capsys.readouterr().out
    assert "would rotate" in out
    assert "lbc_should-not-leak" not in out
    assert distribution.list_consumers(conn)[0]["token_hash"] == before["token_hash"]


def test_rotate_token_refuses_a_value_that_belongs_to_another_registration(conn, capsys, monkeypatch):
    _machine(conn)
    distribution.register_consumer(
        conn, name="other", domains=["legal"],
        token_hash=hashlib.sha256(b"taken").hexdigest(), created_by="t",
    )
    monkeypatch.setenv("BENCH_NEW_FLEET_TOKEN", "taken")
    script = _load_script()
    monkeypatch.setattr(script, "_connect", lambda: _borrowed(conn))

    rc = script.main(["--rotate-token", "--name", "ontology-fleet-win",
                      "--token-env", "BENCH_NEW_FLEET_TOKEN", "--apply"])
    assert rc == 1
    assert "已经属于登记" in capsys.readouterr().err


def test_rotate_token_is_idempotent_on_the_current_value(conn, capsys, monkeypatch):
    before = _machine(conn)
    monkeypatch.setenv("BENCH_NEW_FLEET_TOKEN", "win-token")
    script = _load_script()
    monkeypatch.setattr(script, "_connect", lambda: _borrowed(conn))

    assert script.main(["--rotate-token", "--name", "ontology-fleet-win",
                        "--token-env", "BENCH_NEW_FLEET_TOKEN", "--apply"]) == 0
    assert "不写库" in capsys.readouterr().out
    assert distribution.list_consumers(conn)[0]["token_hash"] == before["token_hash"]
