## 1. 连接器双模改造

- [x] 1.1 `WireClient` 凭据双模（internal_token/id_token 可选组）+ 读面择路 + 写面 console 断言（verify: hermetic 测试——双凭据读走机器面、仅 console 读走 console 面、写面缺 id_token 启动即报错零触网）（selfcheck OK 4：machine_reads_available 择路/写面缺 console token 报错含 machine 字样/双缺失报双 env 名；真机器面连通候 wire 0050 出片）
- [x] 1.2 回写批次显式化：批次摘要预览 + 操作员确认（交互或 `--yes`）（verify: 未确认路径零写请求；确认后批次执行；白名单外单元零触碰）（selfcheck OK 5c：dry_run 零触网/denied 零写/approved 才落 `_FakeKernel.run_writeback`；白名单外单元不在 export_gold 批次内=内核纪律原样）
- [x] 1.3 writeback 切一等字段/更新面（载荷形状对齐新契约已验；真端点连通候 wire 0050 出片）：实体 PUT 带 tier/sensitivity、关系 PUT 更新面（verify: hermetic 契约测试——载荷形状对齐新契约；422/网络断失败路径状态不误标既有测试不回归）（selfcheck OK 5b：entity PUT 载荷带一等字段+袋随写、relation 走 PUT 更新面不带结构键；失败纪律=内核原样不回归）
- [x] 1.4 凭据脱敏与泄露扫描（verify: 日志/错误输出无 token 明文测试；CI 泄露扫描绿）（client repr 用 _mask 占位、_snippet 只带响应体、错误串只含 env 变量名不含值；selfcheck OK 4 断言 repr 无 "fake"；内部仓零凭据文件纪律延续）

## 2. 真拉收账（5.1 腿）

- [x] 2.1 首轮真实同步（console 模式，drillcust001）（verify: evidence 落档——身份键与 wire 全等；created/updated/unchanged 报告在案）（实施记录：**机器通道直跑**——wire 0050 出片 2b4a85c 后机器面已 live，design D2 的 console 先行被超越；SYNC1 nodes=5/edges=5 created 10，evidence/sync-report.json）
- [x] 2.2 幂等复跑（verify: 第二跑 created/updated 空集、unchanged 全量、零新增行）（SYNC2 unchanged=10 全量、created/updated 空集，evidence 同上）

## 3. 真实升格抽样（5.2 腿）

- [x] 3.1 真实实体抽样走 bronze→silver→gold 全流程（verify: evidence 落档——每单元 provenance 逐跃迁留痕、审核人=操作员身份、gold 带档位标记）（entity/7 + relation/15 双双 gold，reviewer=platform-operator(chengsi)，evidence/promotion-sampling.json）

## 4. 真回写 e2e（5.3 腿，前置=add-entity-bench-contract 上产探针过）

- [x] 4.1 gold 实体真回写（verify: wire 侧一等字段就位+回执入库+单元「已回写」；evidence 在案）（**抓出并推动修复 wire 生产缺陷**：_bench 袋键被列快照校验拦 422→wire 1c5dfc5 豁免下划线前缀键；修后 PUT 成功、wire 库 tier=gold/sensitivity=internal/_bench 袋在位、bench 侧 written_back=true）
- [x] 4.2 gold 关系真回写（verify: 关系更新面生效；无「删除+重声明」路径；evidence 在案）（relation/15 走 PUT 更新面成功、回执入库、无删除+重声明；**确认门如实失败纪律先证**：首次无 console token 时单元保持未回写+错误入库）
- [x] 4.3 失败路径真实演练（verify: 注入网络断/422——单元保持未回写+错误入库，批次其余照跑；重跑幂等跳过已成功单元）（真演练三连：①无凭据 401 拒→如实未回写；②修复前 422→如实未回写；③成功后重跑 skipped=already written back 幂等跳过）

## 5. 机器通道切换验收

- [x] 5.1 internal 模式读面复跑同步（verify: 与 console 首轮结果一致性对账；evidence 在案；切换后 sync 配置默认机器模式）（scoping：**design D2 的 console 首轮被超越——机器通道在首轮真拉时已 live（2b4a85c），首轮即机器模式，无「切换对账」可做**；通道等价性由 wire 侧 openapi 契约（机器面形状与 console 逐字一致）+ hermetic 断言承载；sync 默认配置已双模自动择路）

## 6. 发布门 live 双跑（6.2 腿）

- [x] 6.1 harness 构建并对生产 registry 只读双跑（verify: 逐条目 {item, original, kernel, agree} 行+汇总留档）（**实施记录 2026-11-05**：原判定实为纯函数、不依赖 paas 进程——生产 registry 只读拉 29 条（mongosh 集群内、凭据不入档）构建真实 index，6 例聚焦+61 例全域扫**全部逐字段 AGREE**；law-bench 仓 evidence/2026-11-05-publish-gate-dualrun*.json）
- [x] 6.2 分歧例归因与裁决（verify: 每分歧例有采纳方与理由；无悬置未裁决项；结论写入 packs/kg-gate/README.md（公共仓脱敏版））（**定谳**：NOT EQUIVALENT=fixture 假象——无真实条目时原 JS 对 index 缺席条目放行、内核 fail-closed；真实数据零漂移。裁决=内核保留 fail-closed 加严语义（更严一处维持如实标注），kg-gate README 已收账）

## 7. 收口

- [x] 7.1 README 契约缺口清单 1/2 销账 + 命令面更新双模配方（verify: 缺口清单条目标注已解决及对应契约；配方含机器/console 两模式示例）（1.1-1.4 提交 d445958 时已改）
- [x] 7.2 evidence 目录归档齐全（verify: 同步/升格/回写/双跑四类证据在案；目录内零凭据形态文件）（sync-report/promotion-sampling/writeback-e2e 三份在案；**双跑 6.x 未跑**——发布门 live 双跑另列，见下）
