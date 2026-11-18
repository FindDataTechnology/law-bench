#!/usr/bin/env bash
# 一键刷新法规目录副本并重跑引法解析（flk 增量后的例行操作，~5 分钟）。
# 用法: scripts/refresh_law_catalog.sh /path/to/laws_export.jsonl
# 详见 docs/law-catalog-runbook.md。前提: database_url 指向目标库;
# 条文级解析需 LAW_API_KEY + LAW_SEARCH_ENABLED=true（缺省时跳过该步）。
set -euo pipefail
cd "$(dirname "$0")/.."

EXPORT="${1:?用法: refresh_law_catalog.sh <laws_export.jsonl 路径>}"
PY="${PYTHON:-.venv/Scripts/python.exe}"
[ -x "$PY" ] || PY=python

echo "== 1/3 导入目录（全量替换，幂等） =="
"$PY" scripts/import_law_catalog.py --file "$EXPORT" --seed-aliases

echo "== 2/3 名称级解析 + 审计报告 =="
"$PY" scripts/law_citation_audit.py

if [ -n "${LAW_API_KEY:-}" ] && [ "${LAW_SEARCH_ENABLED:-}" = "true" ]; then
  echo "== 3/3 条文级解析 =="
  "$PY" scripts/resolve_article_citations.py
else
  echo "== 3/3 跳过条文级解析（LAW_API_KEY/LAW_SEARCH_ENABLED 未配置）=="
fi
echo "刷新完成。报告: docs/law_citation_audit_report.md"
