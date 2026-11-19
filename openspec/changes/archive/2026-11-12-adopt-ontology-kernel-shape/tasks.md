# Tasks — adopt-ontology-kernel-shape

换底的实现工作记在 `establish-ontology-kernel` 的 5.1–5.7（同一批改动，未提交前在
本仓工作树里）。本 change 只补发布面的形状/契约声明，并核对其余三个能力无需增量。

## 1. 发布面形状声明

- [x] 1.1 `src/bench/kernel_ports.py` 的 `DECLARATION` 声明 `system="law-bench-internal"`、`kernel_contract="1.0"`、`manifest_shape=2`（键寻址），并随 `Kernel` 构造交给内核校验；验证：把形状改成 9 时构造抛 `ShapeDeclarationMissing`
- [x] 1.2 `distribution.canonical_digest` 委托内核 `digest_of`，`canonical_manifest` 委托内核 `canonical_payload(shape=2)`；验证：`pytest tests/test_distribution_kernel.py` 22 条全绿，且内核 golden 6 例逐字节一致

## 2. 复核点名的三个能力

- [x] 2.1 `ontology-authoring`：已有「写入 SHALL 经内核的授权写路径……SHALL NOT 存在绕过内核的直写路径」——无需增量；验证：`grep -c 内核 openspec/specs/ontology-authoring/spec.md` ≥ 2
- [x] 2.2 `ontology-key-scheme`：已有「内核在落单位与收提案时 SHALL 用该域注册的规则归名」——无需增量
- [x] 2.3 `ontology-extraction`：已有「生成后先过键与归一」的关卡链——无需增量

## 3. 未做（明确登记）

- [x] 3.1 本仓接入符合性闸门这件事**已拆成独立 change**：工作区根 `openspec/changes/add-law-bench-conformance-adapter/`（`--strict` 通过，含「端口必须能在一个连接上服务多个作用域」的要求与四条场景）。阻塞原因：`kernel_for(conn, *, domain)` 把内核钉在一个域上，而套件要求单沙箱服务多作用域；且改端口前必须先能跑本仓带库验收测试（`.env` 指向 `localhost:15432` 端口转发）。**本 change 不含该实现**，在此之前本仓 CI 只跑自己的验收测试
