## Why

`image-delivery` 现状写的是「推默认分支即由本仓 GitHub Actions 出片」。2026-11-11 实测这条线**没有在跑**：

- `gh api repos/FindDataTechnology/law-bench/actions/workflows` → `total_count: 0`；`gh run list` 空。`github/main` 落后 gitee `origin/main` **277 笔**——照 spec 推 github 既不会构建，还会把 277 笔一次性推上公开仓。
- 线上镜像 tag `sha-75d95bd` 在 `law-bench` 与 `law-bench-internal` 的历史里**都查不到**：`fd-build-snapshot` 的 tag 是**快照仓 commit 短 sha**，真源 sha 只写在 `BUILD-INFO.json` 与 commit message 里。
- 真正的阻塞：真源是私有仓，而 `FindDataTechnology` 的私有 CI 额度已耗尽（2006/2000），它的 Actions 停摆；同时本仓的测试闸门有 7 条**环境假设**（兄弟仓绝对路径、soffice、pgpass），在任何干净 runner 上都必红——即使额度恢复也出不了片。

所以要么照 spec 干（不可能），要么把「额度耗尽时的替代通道」写成契约。

## What Changes

- 新增一条替代通道契约：把源码快照推到**另一个账号下的私有**镜像仓出片；快照目标仓必须与源仓同可见性，**禁止**为省额度改用公开仓（那等于公开源码）。
- 明确「抬头工作流用本仓自己的 `.github/workflows/image.yml`」，不得沿用通用平台的镜像工作流（它的冒烟闸按另一产品的 3000 端口/`/api/config`/必需 env 判定，对本镜像必然失败——实测首跑即挂）。
- 明确两条溯源判据：快照仓 `BUILD-INFO.json` 的 `baseCommit`（真源 commit）与 hkccr/ccr 两侧 digest 一致；**不得**拿镜像 label 当构建源判据（label 继承自基础镜像）。
- 明确「出片闸门不得依赖开发机环境」：兄弟仓缺失、soffice 缺失时 skip 并写原因；不得依赖家目录绝对路径或 pgpass/trust 认证。

## Capabilities

### New Capabilities

（无新增能力——只是把已有交付通道的真实形态补进契约。）

### Modified Capabilities

- `image-delivery`: 出片触发方式补上「私有额度耗尽时的私有快照仓通道」，并把「测试闸门的环境中立性」写成要求。

## Impact

- 契约：`image-delivery` 一条 MODIFIED（含新增场景）。
- 代码：无（工作流与工具已就位；本轮已实跑出片 `sha-afb4e71` 并滚版验证）。
- 运维：新增出片仓 `law-ai-official/law-bench-images`（private），`BUILD-INFO.json` 记录真源 sha。
- 回滚：契约层面回退本条 requirement；镜像层面回滚 tag 到 `sha-75d95bd`。
