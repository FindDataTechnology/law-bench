## Why

`image-delivery` 现在断言：「The legacy Jenkins→Harbor channel SHALL remain available as the standing fallback（Jenkins jobs preserved）」。

2026-11-11 实测这条兜底**不存在**：

- 四个 kube context（`cheap` / `cheap-ts` / `tencent` / `xinru`）与 `zihan` 里全都没有 jenkins 命名空间中的工作负载；
- `cheap-ts` 的 `jenkins` 命名空间是空的（`No resources found`）；
- 入口机 `103.236.89.212` 上 `:31000` 无监听；
- 雷池里 `jenkins.finddatatech.cloud` 站点仍指向上游 `172.22.222.1:8080`，而 Caddy 已经没有该域的路由 → 回空 `200`。

也就是说：契约承诺了一个找不到的兜底，而今天主通道（GitHub Actions）真的因为私有额度耗尽（2006/2000）停摆过一次——那一刻按契约去找 Jenkins 会扑空。这属于「声明 ≠ 存在」：把已经不在的东西写成约束，比不写更坏，因为它会让人在故障时省掉本该做的判断（例如"那就走私有快照仓"）。

## What Changes

- 把该 requirement 改成如实描述：**主通道 + 私有快照仓通道**，并明确「Harbor 里已有的镜像 tag 仍可用于回滚」（这一半是真的，镜像还在 registry 里），但**不再声称有可用的 Jenkins 作业可重出片**。
- 明确回滚的两条真路径：① 清单翻回 Harbor/TCR 上已存在的 tag（不需重建）；② 用快照仓重出片。
- 附一条运维事实进 spec 的说明：`jenkins.finddatatech.cloud` 是退役入口（雷池站点仍在，Caddy 无路由，回空 200），`.env` 里的 `JENKINS_URL` 与仓里的 `Jenkinsfile` 属历史遗留。

## Capabilities

### Modified Capabilities

- `image-delivery`: 回滚/兜底要求改成「已有 tag 翻回」+「快照仓重出片」，删除对不存在的 Jenkins 通道的承诺。

## Impact

- 契约：`image-delivery` 一条 MODIFIED。
- 代码：无（`Jenkinsfile` 保留，但不再被契约承诺；如确认永久废弃可另开 change 删除）。
- 风险：若将来重建 Jenkins，需要把这条 requirement 再改回去——这比现在让人相信一个不存在的兜底要安全得多。
