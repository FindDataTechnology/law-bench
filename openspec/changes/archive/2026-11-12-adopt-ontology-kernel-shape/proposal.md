# adopt-ontology-kernel-shape

## Why

本能力面（知验台）的机制已经在 `establish-ontology-kernel` 第 5 阶段换底到共享内核：
`src/bench/keys.py` 成为内核 re-export 壳、`authoring.py` 是内核写路径的 adapter、
`distribution.canonical_digest` 委托 `fd_ontology_kernel.manifest.digest_of`、
`ledger` 的投影交内核纯函数。

复核三个点名的能力规格时发现：**它们已经写着"经内核"**，不需要再改——
`ontology-authoring` 要求"写入 SHALL 经内核的授权写路径……SHALL NOT 存在绕过内核的直写路径"；
`ontology-key-scheme` 要求"内核在落单位与收提案时 SHALL 用该域注册的规则归名"；
`ontology-extraction` 要求"生成后先过键与归一"。这些是换底时一并写进去的。

**真正缺的只有一条**：发布面没有记下**它说的是哪一种 manifest 形状**。发布的对端是
外部消费者，形状是它们唯一的解释依据；不记形状，就等于让消费者猜。

## What Changes

- `knowledge-distribution` 的「版本化发布」补充：规范化与 digest 配方由共享内核持有
  （一面一份实现会让两个面在"同一内容"上判定不一致，跨面比对随即失去意义）；
  发布的 manifest 为**键寻址形状（形状 2）**；本面 SHALL 声明它遵循的内核契约版本与
  manifest 形状，声明不受支持时 SHALL 被拒而不是猜。
- 不改：发布流程、changelog 语义、消费者登记与拉取面、词表执法锚点。

## Impact

- 受影响规格：`knowledge-distribution`（一个要求）。
- 迁移：无。已发布的 manifest 内容与 digest 均不变（换底前后逐字节一致，golden 钉住）。
- 不做：不给本仓加符合性适配器（本仓内核按域绑定 scope，套件要求单沙箱服务多
  scope，是设计题不是接线题——见 `establish-ontology-kernel` 任务 8.6）。
