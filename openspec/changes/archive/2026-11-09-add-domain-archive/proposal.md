## Why

域只能建、不能撤。`workspaces` 里没有任何删除或归档域的路径（全仓 grep 不到
`DELETE FROM domains`，也没有软删列），于是：

- **建错一个域就永久挂在名录里**。试验性的子域、拼错 key 的域、内容已废弃的域，都会一直占着运营台的一行。
- 这让「以后快速填充很多细分域」变成单向冒进：每建一个域都要先想清楚，因为撤不回来。

在鼓励用户大量建域之前，必须先让建域变成可撤的动作。

## What Changes

- `domains` 增加 `archived_at`（可空时间戳，纯增量）。
- 新增归档 / 恢复两个动作：归档后该域从名录、缺口矩阵、切换器里消失，但数据（成员、订阅、单元、运行）**一律保留**，恢复即回到原样。
- 归档不让 key 可复用：`UNIQUE(key)` 不变，避免「同名新域继承旧域的引用」这种混淆。
- 归档是平台管理员动作（与建域同一道门）；恢复同权限。
- 名录与缺口矩阵默认只看在役域；管理员可切「含已归档」查看。

## Capabilities

### New Capabilities

- `domain-lifecycle`: 域的退场契约——归档是软退场（数据保留、检索不可达、名录隐藏）、key 不复用、归档/恢复同日可逆。

### Modified Capabilities

- `domain-estate-console`: 名录与缺口矩阵默认只统计在役域，并提供「含已归档」视图与管理入口。

## Impact

- 代码：`workspace_store` 增列，`workspaces` 增 `archive_domain` / `restore_domain` / `list_domains(include_archived=)`，`estate` 与名录路由跟随，admin 域页加入口。
- 数据：仅新增一列；现有域 `archived_at IS NULL` 即在役，零迁移风险。
- 风险：归档域若仍被 `library_subscriptions` / `rubrics` 引用，这些行保持原状（不级联），恢复后引用完好；归档域**不会**被检索到，因为它不在域树的可达集合里（检索按 domain_path 解析，归档域不进名录因而没人能进）。
