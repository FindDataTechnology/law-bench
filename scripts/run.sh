#!/usr/bin/env bash
# Run the contract drafting crew, routing Ark directly (bypassing the macOS
# system proxy) and disabling CrewAI's OpenTelemetry telemetry.
#
# Why: Python's `requests`/litellm pick up the macOS *system* network proxy
# (127.0.0.1:7892) even with no env vars set, and route the Ark LLM call
# through it. When that proxy is down the call fails with "Connection error".
# Ark (ark.cn-beijing.volces.com) is directly reachable, so we bypass the
# proxy for it. Telemetry is disabled to avoid noisy retry backoff when the
# telemetry endpoint is unreachable.
#
# Usage:
#   bash scripts/run.sh "你的合同起草需求" [output.md]
#   bash scripts/run.sh "起草一份服务协议，甲方是科技公司，乙方是个人顾问" output/draft.md
set -euo pipefail

export no_proxy=ark.cn-beijing.volces.com
export NO_PROXY=ark.cn-beijing.volces.com
export OTEL_SDK_DISABLED=true

exec uv run python main.py "$@"
