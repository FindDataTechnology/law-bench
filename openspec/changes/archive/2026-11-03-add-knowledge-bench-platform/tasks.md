## 1. P0 · 合流与奠基

- [x] 1.1 造 donor 白名单：对 law-bench-server 拷贝的 `contracts/`、`paper/`、README 差异逐文件列示审查，明确「无凭据文件」（`.env`、`ssh-config.json`、`.git` 及任何 config/密钥永不在列）；清单落档于本 change 根 `donor-whitelist.md`，每行含审阅结论（verify: 清单文件存在且逐行有结论）
- [x] 1.2 按白名单拷入正身仓，单提交（verify: `git show --stat HEAD` 仅含白名单路径，无凭据形态文件）
- [x] 1.3 law-bench-server 标记为只读供体（目录内注记：不再迭代，仅资产来源）（verify: 注记文件存在）
- [x] 1.4 确立基线：合流提交后跑全量 pytest，存档基线输出（verify: 基线全绿且输出文件留档，供 2.2 对比断言口径）

## 2. P0 · 内核抽取（知识单元泛化）

- [x] 2.1 知识单元 `kind` 幂等加列 + 存量回填 `clause`（verify: schema 幂等自建测试过；存量条款行 kind 计数 = 条款总数）
- [x] 2.2 建 `src/bench` 内核包：语料库/评测/复核/组装/导出读写面按 kind 泛化，内核不含法律常量（verify: 既有 pytest 全绿且断言口径与 1.4 基线一致，未改任何既有断言）
- [x] 2.3 `law_catalog`、`clause_seeds`、法律引用组件迁入 `packs/legal`，经域包声明接入（verify: 法律全链 组装→评测→复核→MCP 工具→公共 API 行为等价；MCP 37 工具面只增不减）
- [x] 2.4 CI 内核领域无关断言：法律常量在 `src/bench` 源码树零命中（verify: 扫描脚本入 CI 且通过）
- [x] 2.5 数据通道：评测运行加通道字段（text/data）+ 确定性校验器注册表接口（verify: 样例数据对象评测全程未调 judge 且 verdict 落库；注入限流/模型故障不影响数据通道结果）
- [x] 2.6 真值守卫从 finetune 导出器扩展到全平台导出面（verify: bronze/silver 按 ground-truth/reward 用途请求被单点守卫拒绝（新增测试）；既有 finetune 守卫测试不回归）

## 3. P0 · 开源切分

- [x] 3.1 内部仓 law-bench-internal 承接内部资产与柏讯连接器骨架（verify: 内部仓测试绿；公共仓源码对内部模块引用零命中）
- [x] 3.2 公共仓 CI 泄露扫描 fail-closed：内部仓路径引用/凭据形态/客户数据样本令构建失败（verify: 注入违规样本 CI 失败并逐条指明，移除后恢复绿）
- [x] 3.3 公共仓 README/文档能力宣称与可运行面对齐，内部专属能力标注「内部」（verify: 能力表逐条核验记录）

## 4. P1 · 双域验证与判官校准

- [ ] 4.1 判官结构性误读修复（对照 `docs/evaluation-system.md` 自认缺陷清单）（verify: 修后判官在既有 gold 上校准，结构性误读用例清零，all_pass 回到合理区间）
- [x] 4.2 judge 校准运行机器：按置信分档的准确率矩阵 + 单调性，随模型+提示词版本留痕（verify: 对现行判官产出校准报告落库可查）
- [x] 4.3 gold 信号源声明闸：未通过校准的 judge 不得被域包声明为 gold 信号源（verify: 声明被拒路径测试，拒绝信息指明「judge 未通过校准」）
- [x] 4.4 政务域包：gov 语料适配器 + KG 车道验收判据迁入 + rubric 包（verify: gov 知识单元 入库→评测 真跑记录）（scoping：registry 实为源注册表 11 源非逐件公文，load_gov_registry 入库 11→run_data_eval 88 criteria 全 PASS；复核腿对确定性 checker 不适用[无判官 verdict 可盲标]故不勾；zhengxin 盘上无本地指标文件[仅远程 MCP]如实略过；KG 判据在 fd-text-core/kg_graph_checks.py 找到，四条硬判据①③④降级为 checker、②需文号实例 registry 无→如实不迁，见 packs/gov/README.md）
- [x] 4.5 金融数据域包：fd-sentiment gold-v9 尺子迁入 + fd-data-quality baselines 接入 + 首批数据 QA 金集（从 dashboards 对账/finalize 判据改写）（verify: 数据通道真跑——对账判据与 QA 金集评测出分且落库）
- [x] 4.6 双域等价复核：迁入的尺子与原仓对同输入双跑零漂移（verify: 双跑对比记录零差异）（finance 尺子已证：packs BAND_TO_DIRECTION vs fd-sentiment evaluate._BAND_SIGN 全 105 条金集双跑零漂移，tests/test_pack_equivalence.py；gov KG 判据为语义蒸馏非 1:1 可双跑 scorer[原脚本需 live FalkorDB]→该域等价性暂不适用，如实记录）

## 5. P2 · 柏讯贯通

- [x] 5.1 wire 实体/关系单向拉取同步：wire 主键源、知验台零身份存储（verify: 同步后身份键与 wire 全等；重复同步幂等无新增行）（scoping：sync_graph external_key=源 id、双跑零写、unchanged 不 bump；wire api 实查=graph 端点 console Bearer 验 Logto ID token，端点域名+mesh 三处全 401 可达、生产凭据无（造 token 需写生产 Logto 库=禁）→真拉 deferred 如实记录于 packs/gov README 与 wire-connector/README.md；内部连接器 client/sync 已就位 selfcheck 全过）
- [x] 5.2 升格流水线（bronze 机器预标注 → silver → gold 人工核验）接入复核工作流（verify: 真实 wire 实体抽样走完全流程，审核人留痕可查）（scoping：promote_unit 单向相邻晋升、gold 必带 reviewer 路由恒取 session 身份 body 带 reviewer 键直接 400、provenance 逐跃迁留痕；真实抽样随 5.1 真拉 deferred，fixture 全链测试覆盖）
- [x] 5.3 gold 回写带档（sensitivity/tier），幂等键 = wire 实体键（verify: 回写成功路径 + 注入失败路径（网络断），知验台侧状态如实不误标「已回写」）（scoping：run_writeback 成功才记 written_back+回执、抛错批次续跑不假标、重跑按 wire 键幂等跳过；**wire 契约缺口**：实体无 tier/sensitivity 一等公民字段（现以 column_notes._bench 元数据袋承载）、关系无更新面→连接器如实拒绝——wire 侧需求已在两处 README 记录）
- [x] 5.4 图谱展示接线：工厂内视图在 bench 工作台，客户面归 wire 控制台（verify: 两端同源抽样对账口径一致）（scoping：工厂视图=/promotion/queue 计数+分页+回写状态装饰（任意登录可读）；客户面=wire 控制台既有实体图谱端点，知验台零第二份身份存储故天然同源；抽样对账腿随真拉 deferred，口径一致性由 promotion 键=源 id 设计保证）

## 6. P3 · 全生态秤与飞轮

- [x] 6.1 fd-text-core 检索评测迁入为 eval-suite（verify: 双指纹趋势在新址产出，与旧址最后基线一致）（scoping：迁入 packs/text-retrieval/，指标为纯函数+双指纹=数据集文件字节sha25前16+配置env/垂域sha25前16；等价双跑做到**全链层**——importlib 载未修改原仓 dataset/runner、同进程同输入 EvalReport.to_dict() 逐值相等、四集数据集指纹相等、nDCG 300+ case float 全等；不可双跑腿=真实检索执行与 store.py SQL（需原仓 PG/S3/嵌入凭据），故证的是尺子本身零漂移非复现历史跑分。详见 packs/text-retrieval/README.md）
- [x] 6.2 KG 车道验收判据与市场发布门迁入（verify: 迁移后发布门读数与迁移前一致）（scoping：迁入 packs/kg-gate/。KG 四硬判据全离线可验+零漂移（吃真实图统计快照 JSON、判据输出==原仓 decision 函数逐值等），脏名复用原 is_dirty_name 本体；判据脚本在 fd-text-core/scripts/kg_graph_checks.py **为未跟踪文件**、fd-legal-kg 无——已如实记录。**市场发布门 live 双跑已闭环（2026-11-05）**：真 registry 数据（29 条双跑 67/67 逐字段 AGREE）证明此前 NOT EQUIVALENT 判定是 fixture 假象（registry 未 seed 真实条目时原逻辑仍放行、内核 fail-closed）——证据 `evidence/2026-11-05-publish-gate-dualrun{,-focused}.json`、README 已更新。详见 packs/kg-gate/README.md）
- [x] 6.3 meta-eval 常态化：季度漂移检测入调度（verify: 漂移检测作业真跑一次并落库）（scoping：`scripts/drift_check.py`=纯确定性比较作业（同 judge+version 最近两次 meta 运行 diff，agree 跌幅>阈值或单调翻转判 drift 退出码1=CronJob Failed 报警；无基线 not_comparable 不落库不造假）；`tests/test_drift_check.py` 34 hermetic 测全绿；`deploy/cheap-box/drift-cronjob.yaml`=清单工件[镜像/secret/风格照 deploy/deployment.yaml+mcp-deployment.yaml]，**未 kubectl apply**、是否上产线待主线拍板、tag 须先钉含脚本构建。真跑证据=本地 dev PG 文件模式+DB模式各跑一次并清理残留）
- [x] 6.4 微调飞轮按域包导出 Judge/Drafter 数据集（verify: 导出物四层 tier 抽检合规；守卫拒绝用例仍被拒）（scoping：`src/bench/flywheel.py` 领域无关导出机（labeled purpose 全池先过 assert_not_ground_truth 失败即中止不写文件、warmup 走 filter_by_tier 默认 floor=silver、每行带 tier+provenance 回指 unit、幂等字节一致）+ `scripts/finetune/export_by_pack.py` CLI（pack.yaml 校验 kind、适配器 pack:kind>kind>默认、法律 clause 适配器）；`tests/test_flywheel_export.py` 16 测全绿含 common.re-export 到 tiers 的 object-identity 未破证。`export_dataset.py` 未改）

## 7. 收口

- [x] 7.1 三域冒烟：法律 + 政务 + 金融各跑一轮 评测→复核→（法律）组装 全链（verify: 三域冒烟记录留档）
- [x] 7.2 specs 对账：逐 Requirement 核对其 Scenario 有对应已完成任务且验证证据在案（verify: 对账记录，防「实现了却没勾」档案教训）

<!-- 4.1 未勾：活体校准已跑通全链（产库 v4-validity-pilot 108 对金对导出 → scripts/calibrate_judge_live.py 真判官重判 → run_calibration 落库）。四模型横评：词元 lane 实际可服务判官仅 deepseek-v4.1-flash（一致率 60.2%，较历史 36.5% +23.7pt，单调性过）与 glm-5.3-flash（13.9%）；kimi-k3/glm-5.2/deepseek-v4-pro 等在 /v1/models 挂名但无上游账号（Service temporarily unavailable），glm-4.6 为 deepeval 解析不兼容。分歧单向（判官过严 43:0），0.80 gold 线未过 → 闸正确拒绝任何现行判官作 gold 信号源，packs/legal 如实不声明。解禁路径（需拍板）：①词元绑更强判官上游 ②判官阈值政策调整 ③维持 silver-only。4.1 的 80% gold 线决策由用户挂起（2026-11-03 口头：人工金标本身 κ=0.522 不稳、这块后置）。4.4 政务包与 4.6 双域等价复核已完成（scoping 见各行）。 -->
