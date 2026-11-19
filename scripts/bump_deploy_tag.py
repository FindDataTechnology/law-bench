#!/usr/bin/env python3
"""Bump the production image tag in ``deploy/`` — the ONE action that ships.

ArgoCD watches the **gitee** mirror's `deploy/*.yaml` and self-heals the live
namespace to match it. That means shipping is already explicit: nothing rolls
until a manifest's image tag changes. This script is that step, and only that
step — it edits files, and prints the export+push commands you run next. It
never pushes, never talks to the cluster.

Why it is not in ``image.yml``: GitHub Actions can only push back to GitHub
(``github.token``), and the ArgoCD source is gitee. A workflow that *looked*
like it shipped but could not reach the gitee mirror would be worse than no
automation — green check, unchanged production.

Why per-service and not "replace every tag": the four manifests deliberately
pin different versions (the public replica trails the main app, the MCP servers
pin an older build). A blind global substitution would roll services nobody
asked to roll.

Usage::

    uv run python scripts/bump_deploy_tag.py --tag sha-923a647 --dry-run
    uv run python scripts/bump_deploy_tag.py --tag sha-923a647 --only law-bench
    uv run python scripts/bump_deploy_tag.py --tag sha-923a647        # all listed

Exit codes: 0 changed (or already there), 1 the tag does not exist in the
registry, 2 the target file/service is unknown.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEPLOY_DIR = REPO_ROOT / "deploy"

#: Deployment name → manifest. Every law-template consumer, so a bump can never
#: silently miss one that exists. ``--only`` selects a subset by this name.
TARGETS = {
    "law-bench": "deployment.yaml",
    "law-bench-mcp": "mcp-deployment.yaml",
    "law-bench-mcp-assistant": "assistant-mcp-deployment.yaml",
    "law-bench-public": "law-bench-public.yaml",
}

_IMAGE_RE = re.compile(r"(image:\s*\S*law-template:)(sha-[0-9a-f]{7})\b")


def _tag_exists(tag: str, *, registry: str, namespace: str, image: str) -> bool:
    """Ask the registry whether this tag was minted. Never assume."""
    ref = f"{registry}/{namespace}/{image}:{tag}"
    try:
        out = subprocess.run(
            ["docker", "buildx", "imagetools", "inspect", ref],
            capture_output=True, text=True, timeout=60,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        # No docker here is not a reason to refuse an edit the human asked for;
        # say so and let them decide.
        print(f"  ! 无法校验 {ref}（docker 不可用）；跳过存在性检查")
        return True
    if out.returncode != 0:
        print(f"  ! 镜像不存在：{ref}")
        return False
    return True


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--tag", required=True, help="immutable tag to ship, e.g. sha-923a647")
    p.add_argument("--only", action="append", default=None,
                   help=f"limit to these deployments (repeatable): {sorted(TARGETS)}")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--skip-registry-check", action="store_true")
    p.add_argument("--registry", default="ccr.ccs.tencentyun.com")
    p.add_argument("--namespace", default="law-bench")
    p.add_argument("--image", default="law-template")
    args = p.parse_args(argv)

    if not re.fullmatch(r"sha-[0-9a-f]{7}", args.tag):
        print(f"不是不可变 tag：{args.tag!r}（要 sha-<7 位十六进制>）", file=sys.stderr)
        return 2

    selected = args.only or list(TARGETS)
    unknown = [s for s in selected if s not in TARGETS]
    if unknown:
        print(f"未知目标：{unknown}；可选 {sorted(TARGETS)}", file=sys.stderr)
        return 2

    if not args.skip_registry_check and not _tag_exists(
        args.tag, registry=args.registry, namespace=args.namespace, image=args.image
    ):
        print("镜像 tag 不存在，拒绝改写清单（先让 image.yml 铸出这个 tag）",
              file=sys.stderr)
        return 1

    changes: list[tuple[Path, str, str, int]] = []
    for name in selected:
        path = DEPLOY_DIR / TARGETS[name]
        text = path.read_text(encoding="utf-8")
        matches = _IMAGE_RE.findall(text)
        if not matches:
            continue
        old_tags = sorted({m[1] for m in matches})
        if old_tags == [args.tag]:
            print(f"  = {name} 已经是 {args.tag}，跳过")
            continue
        new_text, n = _IMAGE_RE.subn(lambda m: m.group(1) + args.tag, text)
        changes.append((path, text, new_text, n))
        print(f"  → {name}: {'/'.join(old_tags)} → {args.tag}（{n} 处）")

    if not changes:
        print("没有需要改的清单。")
        return 0

    if args.dry_run:
        print("\nDRY-RUN — 未写入。")
        return 0

    for path, _old, new_text, _n in changes:
        path.write_text(new_text, encoding="utf-8")

    print("\n已改。下一步（这两步是上产本身，脚本不代做）：")
    print("  git -C law-bench-internal add deploy/ && "
          f"git -C law-bench-internal commit -m 'deploy(law-bench): 上产 {args.tag}'")
    print("  ./scripts/sync_public_from_internal.sh --execute   # 导出到发布面")
    print("  git -C law-bench push origin main                  # gitee → ArgoCD 自动同步")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
