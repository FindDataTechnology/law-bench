"""参考客户端 `scripts/fleet_client.py` 的契约（add-fleet-execution-loop §2.8 的伴生件）。

这个脚本是壹座侧接入时**唯一要照抄的东西**，所以它自己不能是唯一没被测过的一段：

- 每个子命令必须打到**一个**已文档化的端点，路径与载荷逐字对齐契约；
- `source` / `runner_ref` 必须由 `fleet_ref` + `post` 拼出来（不能让人手写前缀，
  手写就是冒用的入口）；
- 4xx 与「网络没通」必须分开退出（1 / 2）：前者重试无用，后者重试可能就好了；
- 凭据永不出现在输出里——dry-run 也只打 `<redacted>`。

用一个假传输层断言「发了什么」，不依赖真网络。
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "fleet_client.py"


def _load():
    spec = importlib.util.spec_from_file_location("fleet_client_script", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("BENCH_FLEET_TOKEN", "secret-token")
    monkeypatch.setenv("BENCH_FLEET_REF", "fleet_win")
    monkeypatch.setenv("LAWBENCH_BASE_URL", "https://bench.test")
    monkeypatch.delenv("BENCH_SUBMITTER_MODE", raising=False)


def _capture(mod, monkeypatch):
    sent: list[dict] = []

    def fake_call(self, method, path, *, body=None, query=None):
        sent.append({"method": method, "path": path, "body": body, "query": query})
        return {"ok": True}

    monkeypatch.setattr(mod.Client, "_call", fake_call)
    return sent


def test_orders_hits_the_documented_path(monkeypatch, capsys):
    mod = _load()
    sent = _capture(mod, monkeypatch)
    assert mod.main(["orders", "--domain", "legal"]) == 0
    assert sent == [
        {"method": "GET", "path": "/api/v1/distribution/legal/work-orders",
         "body": None, "query": None}
    ]
    assert json.loads(capsys.readouterr().out) == {"ok": True}


def test_claim_and_complete_use_the_task_id_in_the_path(monkeypatch):
    mod = _load()
    sent = _capture(mod, monkeypatch)
    mod.main(["claim", "--domain", "legal", "--task-id", "12"])
    mod.main(["complete", "--domain", "legal", "--task-id", "12", "--note", "done"])
    assert sent[0]["path"].endswith("/work-orders/12/claim")
    assert sent[1]["path"].endswith("/work-orders/12/complete")
    assert sent[1]["body"] == {"note": "done"}


def test_runner_ref_is_derived_from_the_fleet_ref_not_typed_by_hand(monkeypatch):
    mod = _load()
    sent = _capture(mod, monkeypatch)
    assert mod.main([
        "run", "--domain", "legal", "--post", "post_x", "--round", "3",
        "--role", "concept", "--outcome", "ok", "--counts", '{"drafts": 2}',
        "--task-id", "12",
    ]) == 0
    body = sent[0]["body"]
    assert body["runner_ref"] == "fleet:fleet_win/post_x#3"
    assert body["counts"] == {"drafts": 2} and body["task_id"] == 12


def test_submit_derives_the_source_and_passes_evidence(monkeypatch):
    mod = _load()
    sent = _capture(mod, monkeypatch)
    assert mod.main([
        "submit", "--domain", "legal", "--post", "post_x", "--kind", "company",
        "--external-key", "corp-1", "--body", "主体", "--evidence", '{"url": "https://e.test/1"}',
    ]) == 0
    body = sent[0]["body"]
    assert body["source"] == "fleet:fleet_win/post_x"
    assert body["evidence"] == {"url": "https://e.test/1"}


def test_outcomes_asks_for_exactly_its_own_source(monkeypatch):
    mod = _load()
    sent = _capture(mod, monkeypatch)
    mod.main(["outcomes", "--domain", "legal", "--post", "post_x"])
    assert sent[0]["path"].endswith("/proposals/outcomes")
    assert sent[0]["query"] == {"source": "fleet:fleet_win/post_x"}


def test_a_refusal_exits_1_and_prints_the_servers_reason(monkeypatch, capsys):
    """403 重试无用，必须与「网络没通」分开——否则舰队会无限重试它治不好的错。"""
    mod = _load()

    def refuse(self, method, path, *, body=None, query=None):
        raise mod.Refused("HTTP 403: 机器面只能以自己的身份提交")

    monkeypatch.setattr(mod.Client, "_call", refuse)
    assert mod.main(["orders", "--domain", "legal"]) == 1
    err = capsys.readouterr().err
    assert "refused" in err and "只能以自己的身份提交" in err


def test_a_404_says_the_face_is_not_deployed(monkeypatch, capsys):
    """404 必须被读成「该面未上线」，不能只是一句裸 `HTTP 404`。

    两种 4xx 的处置完全不同，而它们的形状都是「报错」：
      404      = 这条路由不在这片镜像上（对端没滚到含机器面的片，或 base-url 指到公开 pod）；
      401/403  = 路由在、凭据不对（换 token / 登记）。
    混成一句会让人去查凭据——白查一轮，而这正是本 change 要消掉的那类歧义。
    这里走**真实** `_call`（只把 urlopen 换成抛 404），所以断言的是判据本身，不是桩。
    """
    import urllib.error

    mod = _load()
    client = mod.Client(base_url="https://bench.test", token="t")

    def not_found(request, timeout=None):
        raise urllib.error.HTTPError(
            request.full_url, 404, "Not Found", {}, __import__("io").BytesIO(b'{"detail":"Not Found"}')
        )

    monkeypatch.setattr(mod.urllib.request, "urlopen", not_found)
    with pytest.raises(mod.Refused) as exc:
        client.orders("legal")
    msg = str(exc.value)
    assert "该面未上线" in msg, msg
    assert "--schema" in msg, msg          # 给出确认动作，而不是只报错
    assert "404" in msg

    # 401/403 不能被改写成「未上线」——那会把「换 help 凭据」误导成「等部署」。
    def forbidden(request, timeout=None):
        raise urllib.error.HTTPError(
            request.full_url, 403, "Forbidden", {}, __import__("io").BytesIO(b'{"detail":"token not registered"}')
        )

    monkeypatch.setattr(mod.urllib.request, "urlopen", forbidden)
    with pytest.raises(mod.Refused) as exc2:
        client.orders("legal")
    assert "该面未上线" not in str(exc2.value)


def test_unreachable_exits_2(monkeypatch, capsys):
    mod = _load()

    def dead(self, method, path, *, body=None, query=None):
        raise mod.Unreachable("timed out")

    monkeypatch.setattr(mod.Client, "_call", dead)
    assert mod.main(["orders", "--domain", "legal"]) == 2
    assert "unreachable" in capsys.readouterr().err


def test_dry_run_prints_the_request_but_never_the_token(monkeypatch, capsys):
    mod = _load()
    assert mod.main([
        "submit", "--domain", "legal", "--post", "p", "--kind", "company",
        "--external-key", "k", "--body", "b", "--evidence", '{"q": 1}', "--dry-run",
    ]) == 0
    out = capsys.readouterr().out
    assert "<redacted>" in out and "secret-token" not in out
    assert "/api/v1/distribution/legal/proposals" in out
    assert '"source": "fleet:fleet_win/p"' in out


def test_missing_token_or_ref_is_a_config_error_not_a_request(monkeypatch, capsys):
    mod = _load()
    monkeypatch.delenv("BENCH_FLEET_TOKEN", raising=False)
    with pytest.raises(SystemExit) as exc:
        mod.main(["orders", "--domain", "legal"])
    assert "BENCH_FLEET_TOKEN" in str(exc.value)

    monkeypatch.setenv("BENCH_FLEET_TOKEN", "t")
    monkeypatch.delenv("BENCH_FLEET_REF", raising=False)
    with pytest.raises(SystemExit) as exc:
        mod.main(["orders", "--domain", "legal"])
    assert "BENCH_FLEET_REF" in str(exc.value)
