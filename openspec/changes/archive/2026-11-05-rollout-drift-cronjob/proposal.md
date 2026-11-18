## Why

add-knowledge-bench-platform 任务 6.3 建成 meta-eval 季度漂移检测全件（`scripts/drift_check.py` + 34 hermetic 测 + `deploy/cheap-box/drift-cronjob.yaml` 清单），但清单是「MANIFEST ARTIFACT ONLY」——未 apply、未上产，漂移检测目前不存在于生产。benf-platform spec 的 meta-eval requirement（「评测套件的漂移检测 SHALL 为一等运行记录」）已在 spec 层承诺，本变更兑现部署侧最后一公里。另收账：law-bench 公共仓归档移动+新 spec 未提交的家务状态（工作树 D + ??）。

## What Changes

- 上产 drift CronJob（`law-bench-drift-check`，namespace `law-bench`，季度 03:00 UTC Jan/Apr/Jul/Oct day 1）：
  - image tag 钉版到**确认包含 `scripts/drift_check.py`** 的构建（现役 sha-6916bd9 线；钉前镜像内验证，清单头注明的 sha-ba0a6c9 仅为样式占位必须替换）；
  - 手动 kubectl apply 上产（cheap-box 子目录被 ArgoCD 明确排除在同步范围外——`argocd/application.yaml`「top-level *.yaml only」——无 selfHeal 冲突，也不吃 GitOps 自动滚）；
  - 首跑验证：手动触发一次（`kubectl create job --from=cronjob/...`），确认脚本跑通、exit 语义如实（有基线→落库对比记录；无基线→not_comparable 不造假落库）。
- 部署面配置核对：envFrom secrets（law-bench-db 的 database_url / law-bench-judge 的 EVAL_MODEL，secretKeyRef 不内联明文）、dnsPolicy/nodeSelector cheap-7 样式对齐现役 manifests。
- 家务收账：归档移动（`openspec/changes/archive/2026-11-03-add-knowledge-bench-platform/`）、新 spec（`openspec/specs/bench-platform/`）与 `tests/test_kg_gate.py` 修改提交入库（先审 diff 内容再提交）。
- 非目标：judge 校准本身的调度（calibrate_judge_live 的人工触发流程不变）；drift 阈值政策调整；4.1 判官修复线。

## Capabilities

### New Capabilities

（无——零 spec 级行为变更：meta-eval/漂移检测的契约已在 bench-platform spec 在案，本变更纯部署兑现与家务收账。`.openspec.yaml` 已设 `skip_specs: true`。）

### Modified Capabilities

（无）

## Impact

- **集群**：cheap 簇 law-bench namespace 新增一个 CronJob 资源（零 LLM 调用、纯确定性算术，资源占用极小；concurrencyPolicy Forbid）。
- **仓库**：`deploy/cheap-box/drift-cronjob.yaml` tag 钉版提交；家务提交（openspec 归档移动+spec+一处测试修改）。
- **运维**：drift 判定 exit 1 → Job Failed 即报警语义；DB 内 meta/drift 运行记录可查。
- **不破坏**：现役 origin pod / mcp pod / 出片链（Gitee→internal 合并→relay→ArgoCD）零改动。
