# Design — rollout-drift-cronjob

## Context

- 全件已在库：`scripts/drift_check.py`（纯确定性：同 judge+version 最近两次 meta 运行 diff，agree 跌幅>阈值或单调翻转=drift exit 1；无基线 not_comparable 不落库不造假）+ `deploy/cheap-box/drift-cronjob.yaml`（样式镜像 deploy/deployment.yaml 与 mcp-deployment.yaml：envFrom 双 secret、dnsPolicy+dnsConfig、nodeSelector cheap-7、imagePullSecrets）。
- 上产路径事实：ArgoCD application scope=`deploy` 顶层 `*.yaml` only，子目录（含 cheap-box/）不递归——cheap-box 件不吃 GitOps，按 cheap-box README runbook 手动 kubectl（cheap4/cheap6 操作；kubectl context 用 `cheap-ts`，`cheap` context 11-04 起被并发会话改本地隧道址）。
- image tag 纪律：清单头注明 sha-ba0a6c9 系样式占位，**必须**钉到含 `scripts/drift_check.py` 的构建。9de7e6e（脚本入库）之后的部署 bump 线：sha-5d4bcb8 → sha-c505f0c → sha-6916bd9（现役）。
- 家务现状：工作树含归档移动（D + ?? archive/2026-11-03-...）+ 新 spec `openspec/specs/bench-platform/`（??）+ `tests/test_kg_gate.py`（M）未提交。

## Decisions

**D1 手动 apply，不迁入 ArgoCD 监听范围。** 备选「把 cronjob.yaml 提到 deploy/ 顶层吃 GitOps 自动滚」被否：顶层文件是现役服务面（selfHeal 直改回卷），把季度作业混进服务滚动面会放大每次出片的爆炸半径；cheap-box 已是既定「人工决策区」。代价=升级须手动（季度件可接受），写进 runbook。**实施修正（2026-11-05 上产实测）**：cronjob 首次 apply 显示 "unchanged"+AGE 36h——11-03 深夜某会话已按同一 manifest apply 过；本腿的实际工作转为「首跑验证 + 调度可达性修复」。

**D1a 调度可达性两连坑（首跑实测，改清单）：**
1. `disk-pressure:NoSchedule` taint 拦调度 → 试过 toleration 放行；
2. toleration 只免 taint 调度、不免 kubelet DiskPressure **节点条件驱逐**——pod 起来即被 Evicted。
   定案：**无 node pin**（原 cheap-7 pin 注释自证「风格延续非硬要求」——无卷挂载、tcr-pull 任意节点拉镜像、DB 远程），自然落无 taint 节点；toleration 撤销（不放宽到会驱逐自己的节点）。

**D3 首跑验证用 Job 手动触发，语义断言如实分叉。** 实测：`drift-check-manual-verify` **Succeeded**，输出 `not_comparable`（生产库无 v2-structure 校准运行——4.1 活体校准只落本地/dev 库），退出 0、零造假落库。真实对比从生产库存有两条同 judge+version 校准运行起自动生效。

**D4 家务提交独立单提交，test_kg_gate.py diff 先审。** 归档移动+spec 入库是 openspec archive 的标准产物；test_kg_gate.py 的 M 状态来源待审（6.2 迁移期产物或并发实验残留）——审后归类：属迁移收尾则随单提交，属残留则还原。不与 cronjob 钉版混提交。**实施记录（2026-11-05）**：diff 审明=paas 仓 11-03 移入 finddata 后的路径跟进（两处字符串），随家务单提交（f16989c）。

## Risks / Trade-offs

- [季度 03:00 UTC 无人在场，Job 失败静默] → exit 1=Job Failed 语义 + DB 内 drift 记录可查；Cheap 簇无告警管道的现状下，把「季度首日查 Job 状态」写进 runbook（cheap-box README 一行）。
- [secret 缺键导致 pod 起不来] → 清单 envFrom 引用现役同名 secret（law-bench-db/law-bench-judge），apply 前 `kubectl get secret` 先验存在性；EVAL_MODEL 走 secretKeyRef 不内联。
- [镜像内脚本与库内脚本版本漂移] → D2 验证钉的是「含脚本」的最新现役 tag；后续出片线照常带走新脚本，CronJob tag 跟随下一次部署 bump 更新（runbook 注记）。

## Migration Plan

1. 审 test_kg_gate.py diff → 家务单提交（归档移动+spec+测试）。
2. 镜像验证脚本在场 → 钉版 drift-cronjob.yaml → 提交。
3. secret 存在性预检 → 手动 apply（context cheap-ts）→ CronJob 在册。
4. 手动触发 Job → 语义断言（D3）→ 首跑证据留档（runbook 附录或本 change 归档记录）。
5. 回滚：`kubectl delete cronjob law-bench-drift-check` 即净退（无数据依赖，落库行无害保留）。

## Open Questions

（无——上产路径、钉版纪律、验证语义均钉死；drift 阈值与 judge 修复线不属本变更。）
