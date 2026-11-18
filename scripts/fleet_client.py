#!/usr/bin/env python3
"""Reference client for the bench **fleet machine surface** — no session, one token.

Why this file exists: the machine surface has six endpoints, and the only thing
that made 壹座 (paas) integration hard was that nobody could see the whole
sequence in one place. This is that place. It is deliberately dependency-free
(stdlib only) so it can be vendored or read as a spec, and every command maps to
exactly one documented endpoint — no hidden retries, no invented fields.

The surface (all on the **origin workbench**, not the public pod):

    GET  /api/v1/distribution/{domain}/work-orders
    POST /api/v1/distribution/{domain}/work-orders/{id}/claim
    POST /api/v1/distribution/{domain}/work-orders/{id}/complete
    POST /api/v1/distribution/{domain}/runs
    GET  /api/v1/distribution/{domain}/runs?runner_ref=…
    POST /api/v1/distribution/{domain}/proposals
    GET  /api/v1/distribution/{domain}/proposals/outcomes?source=…

One round of work, in order:

    export LAWBENCH_BASE_URL=https://lawbench.finddatatech.cloud
    export BENCH_FLEET_TOKEN=…          # the fleet's existing token; never printed
    export BENCH_FLEET_REF=fleet_…      # the bare id after "fleet:" in your source

    scripts/fleet_client.py orders   --domain legal
    scripts/fleet_client.py claim    --domain legal --task-id 12
    scripts/fleet_client.py run      --domain legal --post post_x --round 1 \\
        --role concept --outcome ok --counts '{"drafts": 2}' --task-id 12
    scripts/fleet_client.py submit   --domain legal --post post_x --kind company \\
        --external-key corp-1 --body "第一家主体" --evidence '{"url": "https://e.test/1"}'
    scripts/fleet_client.py outcomes --domain legal --post post_x
    scripts/fleet_client.py complete --domain legal --task-id 12 --note "2 条草案"

Exit codes: 0 accepted, 1 refused by the server (printed with its reason),
2 configuration/transport problem (nothing was accepted; safe to fix and retry).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Optional

DEFAULT_BASE_URL = "https://lawbench.finddatatech.cloud"
PREFIX = "/api/v1/distribution"


class Refused(Exception):
    """The server answered 4xx with a reason. Retrying unchanged will not help."""


class Unreachable(Exception):
    """No answer (DNS/TLS/timeout/5xx). Nothing was accepted."""


class Client:
    def __init__(self, *, base_url: str, token: str, dry_run: bool = False) -> None:
        self.base_url = base_url.rstrip("/")
        self._token = token
        self.dry_run = dry_run

    # -- transport ---------------------------------------------------------
    def _call(
        self, method: str, path: str, *, body: Optional[dict] = None,
        query: Optional[dict] = None,
    ) -> Any:
        url = f"{self.base_url}{path}"
        if query:
            url += "?" + urllib.parse.urlencode(
                {k: v for k, v in query.items() if v is not None}
            )
        data = None if body is None else json.dumps(body).encode("utf-8")
        if self.dry_run:
            # Print the shape, never the credential.
            print(json.dumps(
                {
                    "method": method, "url": url,
                    "headers": {"X-Consumer-Token": "<redacted>"},
                    "body": body,
                },
                ensure_ascii=False, indent=2,
            ))
            return None
        request = urllib.request.Request(url, data=data, method=method)
        request.add_header("X-Consumer-Token", self._token)
        if data is not None:
            request.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", "replace")
            try:
                detail = json.loads(raw).get("detail") or raw
            except Exception:  # noqa: BLE001 - 非 JSON 错误体照样要报出来
                detail = raw
            if exc.code >= 500:
                raise Unreachable(f"HTTP {exc.code}: {detail}") from exc
            if exc.code == 404:
                # 404 与 401/403 是**两种完全不同的处置**，而它们的形状都是「报错」：
                #   404 = 这条路由根本不在这片镜像上（对端还没滚到含机器面的片，或
                #         base-url 指到了公开 pod —— 公开面刻意不挂机器面）；
                #   401/403 = 路由在、凭据不对（换 token/登记）。
                # 混成一句 "HTTP 404" 会让人去查凭据，白查一轮。实测过：故意打一个不存在的
                # 前缀得到的就是裸 `HTTP 404: Not Found`。所以这里把**该面未上线**写进消息，
                # 并把确认动作一起给出来。
                raise Refused(
                    f"HTTP 404: 该面未上线（{method} {path} 在 {self.base_url} 上不存在）"
                    f"—— 先确认对端已滚到含机器面的片（origin 上 `register_fleet.py --schema` "
                    f"应 8/8 且机器面回 401/403），并确认 base-url 指的不是公开 pod；"
                    f"原始响应：{detail}"
                ) from exc
            raise Refused(f"HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise Unreachable(str(exc.reason)) from exc

    # -- endpoints ---------------------------------------------------------
    def orders(self, domain: str) -> Any:
        return self._call("GET", f"{PREFIX}/{domain}/work-orders")

    def claim(self, domain: str, task_id: int) -> Any:
        return self._call("POST", f"{PREFIX}/{domain}/work-orders/{task_id}/claim")

    def complete(
        self, domain: str, task_id: int, *, note: Optional[str],
        artifact_refs: Optional[list],
    ) -> Any:
        body: dict = {}
        if note:
            body["note"] = note
        if artifact_refs is not None:
            body["artifact_refs"] = artifact_refs
        return self._call(
            "POST", f"{PREFIX}/{domain}/work-orders/{task_id}/complete", body=body
        )

    def record_run(self, domain: str, *, runner_ref: str, **fields: Any) -> Any:
        body = {"runner_ref": runner_ref, **fields}
        return self._call("POST", f"{PREFIX}/{domain}/runs", body=body)

    def read_runs(self, domain: str, *, runner_ref: str) -> Any:
        return self._call(
            "GET", f"{PREFIX}/{domain}/runs", query={"runner_ref": runner_ref}
        )

    def submit(self, domain: str, *, source: str, **fields: Any) -> Any:
        body = {"source": source, **fields}
        return self._call("POST", f"{PREFIX}/{domain}/proposals", body=body)

    def outcomes(self, domain: str, *, source: str) -> Any:
        return self._call(
            "GET", f"{PREFIX}/{domain}/proposals/outcomes", query={"source": source}
        )


def _json_arg(raw: Optional[str], *, what: str) -> Any:
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(f"{what} 必须是 JSON（例如 '{{\"drafts\": 2}}'）：{exc}")


def _config(args) -> tuple[str, str, str]:
    base = (os.environ.get("LAWBENCH_BASE_URL") or DEFAULT_BASE_URL).strip()
    token = (os.environ.get("BENCH_FLEET_TOKEN") or "").strip()
    fleet_ref = (os.environ.get("BENCH_FLEET_REF") or args.fleet_ref or "").strip()
    if not token:
        raise SystemExit(
            "缺 BENCH_FLEET_TOKEN。用该舰队**现有**的那枚——脚本不会、也不该发明凭据。"
        )
    if not fleet_ref:
        raise SystemExit(
            "缺 BENCH_FLEET_REF（形如 fleet_1794335712751_wfa3ww，"
            "即 source 里 `fleet:` 之后、`/` 之前那一段）。"
        )
    return base, token, fleet_ref


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--base-url", help=f"default: $LAWBENCH_BASE_URL or {DEFAULT_BASE_URL}")
    ap.add_argument("--fleet-ref", help="default: $BENCH_FLEET_REF")

    # ``--dry-run`` （以及 base-url / fleet-ref）在子命令**前后**都要能写：运维会随手
    # 把它放在末尾，argparse 默认只认父级位置，那会让一条只读的预演变成一次真请求。
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--dry-run", action="store_true", default=argparse.SUPPRESS,
        help="print the request instead of sending it (token redacted)",
    )
    common.add_argument("--base-url", default=argparse.SUPPRESS)
    common.add_argument("--fleet-ref", default=argparse.SUPPRESS)

    ap.add_argument("--dry-run", action="store_true",
                    help="print the request instead of sending it (token redacted)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("orders", help="list the work orders addressed to me", parents=[common])
    p.add_argument("--domain", required=True)

    p = sub.add_parser("claim", help="claim one work order", parents=[common])
    p.add_argument("--domain", required=True)
    p.add_argument("--task-id", type=int, required=True)

    p = sub.add_parser("complete", help="close a claimed work order", parents=[common])
    p.add_argument("--domain", required=True)
    p.add_argument("--task-id", type=int, required=True)
    p.add_argument("--note")
    p.add_argument("--artifact-refs", help="JSON array")

    p = sub.add_parser("run", help="write back one round's outcome", parents=[common])
    p.add_argument("--domain", required=True)
    p.add_argument("--post", required=True, help="post id segment of your source")
    p.add_argument("--round", required=True, help="round number in runner_ref")
    p.add_argument("--role", required=True)
    p.add_argument("--outcome", required=True, help="ok | thin | failed | stopped")
    p.add_argument("--counts", help="JSON object")
    p.add_argument("--remaining", type=int)
    p.add_argument("--detail")
    p.add_argument("--task-id", type=int)
    p.add_argument("--artifact-refs", help="JSON array")

    p = sub.add_parser("runs", help="read back a round you wrote", parents=[common])
    p.add_argument("--domain", required=True)
    p.add_argument("--post", required=True)
    p.add_argument("--round", required=True)

    p = sub.add_parser("submit", help="file one proposal as yourself", parents=[common])
    p.add_argument("--domain", required=True)
    p.add_argument("--post", required=True)
    p.add_argument("--kind", required=True)
    p.add_argument("--external-key", required=True)
    p.add_argument("--body", required=True)
    p.add_argument("--evidence", required=True, help="JSON object")
    p.add_argument("--impact", default="")

    p = sub.add_parser("outcomes", help="read what happened to your proposals", parents=[common])
    p.add_argument("--domain", required=True)
    p.add_argument("--post", required=True)

    args = ap.parse_args(argv)
    base, token, fleet_ref = _config(args)
    if args.base_url:
        base = args.base_url
    client = Client(base_url=base, token=token, dry_run=args.dry_run)

    source = f"fleet:{fleet_ref}/{args.post}" if getattr(args, "post", None) else None
    runner_ref = (
        f"{source}#{args.round}" if source and getattr(args, "round", None) else None
    )

    try:
        if args.cmd == "orders":
            result = client.orders(args.domain)
        elif args.cmd == "claim":
            result = client.claim(args.domain, args.task_id)
        elif args.cmd == "complete":
            result = client.complete(
                args.domain, args.task_id, note=args.note,
                artifact_refs=_json_arg(args.artifact_refs, what="--artifact-refs"),
            )
        elif args.cmd == "run":
            fields: dict = {"role": args.role, "outcome": args.outcome}
            for key, value in (
                ("counts", _json_arg(args.counts, what="--counts")),
                ("artifact_refs", _json_arg(args.artifact_refs, what="--artifact-refs")),
                ("remaining", args.remaining),
                ("detail", args.detail),
                ("task_id", args.task_id),
            ):
                if value is not None:
                    fields[key] = value
            result = client.record_run(args.domain, runner_ref=runner_ref, **fields)
        elif args.cmd == "runs":
            result = client.read_runs(args.domain, runner_ref=runner_ref)
        elif args.cmd == "submit":
            result = client.submit(
                args.domain, source=source, kind=args.kind,
                external_key=args.external_key, body=args.body,
                evidence=_json_arg(args.evidence, what="--evidence"),
                impact=args.impact,
            )
        elif args.cmd == "outcomes":
            result = client.outcomes(args.domain, source=source)
        else:  # pragma: no cover - argparse 已保证不可达
            raise SystemExit(f"未知命令 {args.cmd!r}")
    except Refused as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 1
    except Unreachable as exc:
        print(f"unreachable: {exc}", file=sys.stderr)
        return 2

    if result is not None:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
