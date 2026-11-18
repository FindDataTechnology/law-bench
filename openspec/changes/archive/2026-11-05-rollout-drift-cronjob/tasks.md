## 1. 家务收账

- [x] 1.1 审 `tests/test_kg_gate.py` 未提交 diff（verify: diff 逐块归类——迁移收尾/实验残留，结论记录在提交信息）
- [x] 1.2 家务单提交：归档移动（archive/2026-11-03-add-knowledge-bench-platform/）+ 新 spec（openspec/specs/bench-platform/）+ test_kg_gate.py 按审计结论（verify: 提交后工作树干净；`openspec list --specs` 含 bench-platform）

## 2. 钉版

- [x] 2.1 镜像内验证 `scripts/drift_check.py` 在场（现役 sha-6916bd9 线，docker/skopeo 直验）（verify: 验证命令与输出留档）
- [x] 2.2 `deploy/cheap-box/drift-cronjob.yaml` image tag 钉版到验证过的构建并提交（verify: yaml 内无 sha-ba0a6c9 占位残留；diff 仅 tag 一处）

## 3. 上产与首跑

- [x] 3.1 secret 存在性预检 + 手动 kubectl apply（context cheap-ts，cheap4/cheap6）（verify: `kubectl get cronjob -n law-bench law-bench-drift-check` 在册；envFrom 引用的 secret 键齐）（实施记录：apply 报 unchanged+AGE 36h——11-03 深夜已被 apply 过；db/judge 键齐实测）
- [x] 3.2 手动触发首跑并断言语义（verify: Job 完成；≥2 条同 judge+version meta 运行→meta/drift 行落库且 exit 一致；不足→not_comparable 如实，无假落库；证据留档）（实施记录：Succeeded/not_comparable——生产库无 v2-structure 校准运行如实退出 0；调度两连坑=taint 拦+DiskPressure 条件驱逐→定案无 node pin，见 design D1a）
- [x] 3.3 runbook 注记：cheap-box README 加季度首日查 Job 一行 + tag 跟随部署 bump 更新的提醒（verify: README diff 在案）
