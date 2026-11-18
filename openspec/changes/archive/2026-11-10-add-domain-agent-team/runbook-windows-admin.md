# Runbook：在 windows-admin 上起「执行面 + 记忆面」

> 目标主机：windows-admin（tailnet `100.64.0.5`，Win32-OpenSSH 10.4，LTSC 2021 / build 19044）
> 本文件是**给有登录权限的人**执行的步骤单；我（智能体）目前进不去那台机器，所以每条都写成可复制粘贴的形式。
> 未验证项都标了「待确认」，不要当成已确认。
>
> **0.1–0.5 待 windows-admin 权限另开 change 复跑。** 本 change 里这五条已关闭为「推迟」（不是做完）：
> 执行面（壹座）与记忆面（永忆）都未在生产落地；1–10 的岗位验收不依赖它们。

## 0. 前置事实（已在别处核实 / 待核实）

| 项 | 状态 |
|---|---|
| 无容器运行时（Docker Desktop 装不上） | 已确认 → 两个服务都是**原生 Node 进程** |
| 盘位：C 剩 ~12.5G / D 剩 ~51.7G | 已确认 → **装到 D 盘** |
| tailnet 延迟 ~2s（走中继） | 已确认 → 只部署与观察，不做交互开发 |
| 主机 Node 版本 | **待确认**（两个服务都要求 ≥22；永忆 ≥22.5） |
| 该机是否已装壹座 | **待确认** |

## 1. 装 Node（若未装或 < 22.5）

```powershell
# 官方 MSI，x64；装到 D 盘可选，默认即可（Node 本体不大）
winget install OpenJS.NodeJS.LTS
node -v    # 必须 >= v22.5.0
npm -v
```

> 永忆用 Node 内置 SQLite+FTS（依赖只有 `yaml`），**不需要** Visual Studio Build Tools；这条路是为无容器主机特意省事的。

## 2. 记忆面：永忆（fd-memory）

```powershell
# 1) 代码放到数据盘
mkdir D:\apps
cd D:\apps
git clone <repo> fd-memory      # 或直接拷贝开发机上的目录
cd fd-memory

# 2) 构建
npm ci
npm run build                   # tsc → dist/

# 3) 数据目录放到 D 盘（SQLite 会一直长）
New-Item -ItemType Directory -Force D:\apps\yongyi-data

# 4) 启动（前台跑一次，先确认健康）
$env:FD_MEMORY_DATA='D:\apps\yongyi-data'
node dist\index.js serve --port 4000
# 另开一个窗口：
curl http://127.0.0.1:4000/healthz
# → {"status":"ok","service":"fd-memory"}
```

令牌三级（platform → person → deployment），**凭据只落本机 0600，不入库不入仓**：

```powershell
$BOOT = (node dist\index.js token mint --kind platform --namespace '*' --label bootstrap | ConvertFrom-Json).token
# 人根：给「域+岗位」各铸一枚，命名空间按 (域, 岗位) 划分
curl -sX POST http://127.0.0.1:4000/admin/mint -H "authorization: Bearer $BOOT" `
  -H "content-type: application/json" -d '{\"namespace\":\"d/legal/concept\"}'
```

开机自启（与这台机 RustFS 的做法一致）：

```powershell
$act = New-ScheduledTaskAction -Execute "node" -Argument "D:\apps\fd-memory\dist\index.js serve --port 4000" -WorkingDirectory "D:\apps\fd-memory"
$trg = New-ScheduledTaskTrigger -AtStartup
Register-ScheduledTask -TaskName "YongYi Memory" -Action $act -Trigger $trg -RunLevel Highest -User loadtree
```

崩溃自拉（计划任务只管启动，不管进程死掉）：装 NSSM 或用 `while ($true) { node ...; Start-Sleep 5 }` 的 wrapper 脚本挂成任务。

## 3. 执行面：壹座（paas / platform 1.3.27）

```powershell
cd D:\apps
git clone <repo> platform
cd platform
npm install                     # 首次较慢；确保在 D 盘执行
```

`.env`（**先看鉴权口径再启动**）：

```ini
PORT=3000
# 选择一：open access（本机/内网自用；trace 里没有"谁"，只有"哪个岗位"）
AUTH_MODE=
# 选择二：用 aloadtree@gmail.com 登录（要有网：Logto 的 discovery+JWKS 在启动期必须可达，
#          不可达则后端直接起不来——这是踩过的坑）
# AUTH_MODE=logto
# LOGTO_ENDPOINT=https://auth.finddatatech.cloud
# LOGTO_APP_ID=...
# LOGTO_APP_SECRET=...
```

```powershell
npm start                       # headless launcher（scripts/start.js）→ 守护 server.js
curl http://127.0.0.1:3000/healthz
```

> 用 `logto` 之前先 `curl -s -o NUL https://auth.finddatatech.cloud/oidc/.well-known/openid-configuration` 确认可达；不可达就先用空 `AUTH_MODE` 起来，别把服务卡在启动期。

开机自启同上（任务名 `Yizuo Platform`，`Argument "D:\apps\platform\scripts\start.js"`）。

## 4. 接线：把 `team_*` 工具挂进壹座

1. 先起 `team` MCP 服务（本地进程，绑 127.0.0.1，端口自定；实现见 change 的 §13 工具契约）。
2. 壹座 → 设置 → MCP → 添加（**本地 MCP 不需要连市场，也就不需要 registry 令牌**）：
   ```json
   {"name":"lawbench-team","url":"http://127.0.0.1:<port>/mcp","transport":"streamable-http"}
   ```
3. 为每个岗位建一个 pack agent（persona），只挂该岗位允许的工具。
4. 定时：`/tasks` 新建 cron —— 巡检 15 分钟、质检 1 小时、结构每日、概念夜间窗口。

## 5. 验收（四条，缺一条不算通）

| # | 做法 | 期望 |
|---|---|---|
| 1 | 发一个空跑回合（只调 `team_estate`） | `/trace` 里能看到该工具调用与参数摘要 |
| 2 | 停掉永忆，再发同一回合 | 工具**成功**；捕获失败被单独上报（记忆不是业务链路） |
| 3 | 岗位 agent 试着找 `confirm` 类工具 | 工具面上根本不存在 |
| 4 | 重启主机 | 两个服务各自起来，`healthz` 都 200 |

## 6. 回滚

```powershell
Stop-ScheduledTask -TaskName "Yizuo Platform","YongYi Memory"
# 数据保留：D:\apps\yongyi-data（记忆）、壹座自身的数据目录
```

## 7. 尚未解决

- 开发机到该机的 SSH 仍被拒（`loadtree`/`Administrator`/`admin` 全部 publickey 失败；`tailscale ssh` 未在该节点启用）。上面所有步骤因此需要**有权限的人**执行，或者先补一条公钥。
- 该机是否已装过壹座/Node 版本未知；所以第 1、3 步可能只需确认，不需重装。
