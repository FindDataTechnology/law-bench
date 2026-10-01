# law-bench Web 使用说明

> 面向通过浏览器使用 law-bench Web 控制台的同学。这套 Web 是 `src/web` 这个 FastAPI
> 应用提供的服务端渲染管理界面，用来**管理评测规则 / 提示词 / 条款库 / 合同模板，查看
> 法律法规与评测仪表板**。合同**生成**的 JSON 接口见
> [api_instruction.md](api_instruction.md)，本文只讲浏览器里的页面怎么用。

## 1. 访问地址

- **远端（日常用这个）**：`http://<retired-america-box-ip>:30820`
- **本地开发**：`uv run uvicorn src.web.app:app --port 8010` -> `http://127.0.0.1:8010`
- 打开首页 `/` 会自动跳到 **评分规则** 页（`/rubrics`）。
- 无需登录。右上角可切换中文 / 英文（`?lang=zh` / `?lang=en`，选择会记到 cookie）。
- 交互式 API 文档（JSON 接口）：`/api/docs`。

## 2. 顶部导航总览

| 导航 | 地址 | 用途 |
|------|------|------|
| 评分规则 | `/rubrics` | 管理 rubric（评分规则）及其 criterion，含 harbor 重新提取 |
| 提示词 | `/prompts` | 管理合同生成 prompt（CRUD） |
| 对比 | `/compare` | 选多个 prompt 跑对比评测，看 criteria×prompts 矩阵 |
| 法律法规 | `/law-info` | 按合同类型看豆包 / DeepSeek 的法律调研原文（左右对照） |
| 法规索引 | `/law-references` | 全类型聚合的法律法规索引，可按来源/类型过滤 |
| 合同模板 | `/contracts` | 浏览 43 种合同母版模板、slot、法条，下载**母版** docx/pdf；详情页可**生成合同模板**（7 模式） |
| 条款库 | `/clauses` | 条款的浏览/搜索/抽取/CRUD/标签审核，下载**组装后**合同 |
| 仪表板 | `/dashboard` | pipeline 评测通过率统计、分类型明细、版本对比、最近运行 |
| 搜索 | `/search` | 条款片段 RAG 语义检索 |

下面按导航顺序逐个讲。

## 3. 评分规则（`/rubrics`）

管理「用哪几条标准、每条怎么判」的评分规则。每个 rubric 属于一个合同类型，版本号
`contract_<type>_v<N>`（如 `contract_sale_v3`）。

**列表页**：每行显示名称、来源（`harbor` / `local`）、上下文、criterion 数量。

- **新建**：点「新建」，填 `name`（如 `contract_sale_v4`）、`context`（填 `contract`）、
  `description`，下方可一次填多条 criterion（每条 = `name` + `description` + `guidance`，
  `guidance` 写「PASS if … / FAIL if …」的判定标准）。空名的行会被忽略。
- **详情页** `/rubrics/{name}`：
  - 顶部是 rubric 元信息（可「编辑」改名/上下文/描述，或「删除」）。
  - 下方是有序 criterion 列表：每条可**就地编辑** name/description/guidance、**上移/下移**
    调顺序、**删除**。也能在末尾**新增 criterion**。
  - 操作成功会回跳并显示绿色 flash 提示；失败显示红色 flash（如重名冲突、harbor 只读）。
- **harbor 重新提取**：列表页有「重新提取 harbor」按钮，会跑抽取脚本、刷新 harbor 来源
  的 rubric。harbor 来源的 rubric **只读**，不能改（会报 403）。

> 提示：rubric 名字必须符合 `contract_<type>_v<N>` 才会被系统认作「某类型的第 N 版」，
> 生成/评测时会自动取最大 N 的那个。

## 4. 提示词（`/prompts`）

管理合同**生成**用的 prompt 模板。

**列表页**：每行显示 name、contract_type、purpose、source、prompt_type、描述。

- **新建** `/prompts/new`：填 `name`、`contract_type`（如 `sale`）、`purpose`（用途标签）、
  `content`（prompt 正文）、可选 `description` / `prompt_type`。
- **详情** `/prompts/{name}`：看完整记录含 `content` 正文。
- **编辑** / **删除**：在详情页操作。

> prompt 的 `content` 是给起草器（drafter）的指令文本，`contract_type` 决定它属于哪类合同。
> 「对比」功能会按类型把 prompt 串起来用。

## 5. 对比（`/compare`）

把多个 prompt 在**固定条件**下各起草一份合同，再用 rubric 评判，对比谁更好。

**列表页**：最近的对比运行记录。

- **新建对比** `/compare/new`：
  - 选 `contract_type`、`rubric_name`、写 `task_desc`（原始起草需求，会作为 judge 输入）。
  - 勾选 **≥2 个 prompt**（同类型）。
  - `mode` 默认 `drafter-only`（只起草器，不跑自愈）；`n_drafts` 每个 prompt 起草几份。
  - 点「运行对比」——**同步执行**，prompt 多 / n_drafts 大时会要几分钟，浏览器别关。
- **详情** `/compare/{id}`：展示 **criteria × prompts 矩阵**（每格是 PASS/FAIL 或 k/N 通过率），
  客户端 `app.js` 渲染并和 `/api/compare/{id}` 对账。单条草案正文（`draft_text`）按需懒加载。

> 大规模对比建议走 CLI（`python -m src.eval.compare`），Web 适合中小规模。

## 6. 法律法规（`/law-info`）

按合同类型查看法律调研原文。

- **列表**：列出有调研数据的合同类型（标注来源：doubao / deepseek）。
- **详情** `/law-info/{type}`：**左右对照**展示豆包和 DeepSeek 两份调研 markdown（服务端渲染）。
  写「签约提示」「合规建议」时来这里取材。

## 7. 法规索引（`/law-references`）

跨所有合同类型聚合的法律法规索引。

- 按**类别**分组展示（如法律、行政法规、部门规章…），每条法规标注出现在哪些合同类型、哪些来源。
- 顶部可按 `source`（来源）和 `contract_type`（合同类型）**过滤**。
- 适合「某部法到底关联了哪几类合同」这类反查。

## 8. 合同模板（`/contracts`）

浏览 43 种合同的**母版模板**。

- **列表**：全部合同类型（key + 中文名）。
- **详情** `/contracts/{type}`：
  - 模板正文（markdown 渲染，含 `{{slot}}` 占位符）。
  - slot 清单 + 每个 slot 的填空说明（label / description / example / required）。
  - 该类型相关法律法规，按类别分组。
  - **下载母版**：`/contracts/{type}/download/docx` 或 `/pdf`，导出的是**纯母版骨架**
    （不走标签组装，没有 tagged/custom 条款覆盖）。

> ⚠️ 想要「按场景+立场组装后」的合同，去 **条款库** 详情页下载（见第 9 节），不是这里。
> 这里下载的是空壳模板。

### 8.1 生成合同模板（详情页面板）

`/contracts/{type}` 详情页底部有「生成合同模板」面板，提供 **7 种生成模式**（单选）：

| 模式 | 名称 | 行为 | 同步/异步 |
|------|------|------|----------|
| A | 母版骨架 | 只读，直接给母版 docx/pdf 下载链接（等同上方下载按钮，不发请求） | — |
| B | 标签组装 | 按 scenario+stance 组装一份合同，同步返回下载链接 | 同步 |
| C | 存储 MinIO | 组装后上传 MinIO + 落库，同步返回 artifact 下载链接 | 同步 |
| D | 批量组装 | 跨多组 tag 批量组装，同步返回每组的下载链接 | 同步 |
| E | 自愈流水线 | 异步跑「生成→填充→评价→自愈」循环，写 clauses 表与 pipeline_runs | 异步 |
| F | 自动拒绝 | 在 E 基础上把反复不合格的 custom 条款标记为 rejected | 异步 |
| G | LLM 重生成 | 用 LLM 重写该类型母版正文，直接改写全局 `contracts.json` | 异步 |

**共享参数**（所有模式）：立场 `stance`、业务场景 `scenario`、输出格式 `format`、自定义条款 id `custom_clause_ids`。
- D 额外：`tag_combinations`（JSON 数组）或勾选「枚举全部组合」`enumerate_all`。
- E/F 额外：`rubric`、`max_iterations`、`task_desc`、`temperature`。

**同步模式（A/B/C/D）**：点「生成」后直接返回结果与下载链接。
**异步模式（E/F/G）**：提交前弹**确认框**（会改写数据），确认后返回 `job_id`，面板每 3 秒轮询
`GET /api/generation-jobs/{id}`，终态（completed/failed）停止并展示摘要；约 10 分钟轮询上限，
超时请刷新页面查看 job 状态。异步接口详情见 [api_instruction.md](api_instruction.md) 的「合同生成模式接口」一节。

## 9. 条款库（`/clauses`）⭐

最常用、功能最全的模块。管理 base / tagged / custom 三类条款。

### 9.1 列表页 `/clauses`

- 顶部：条款总条数 + **按类型统计表**（每类的 base / tagged / custom 条数、场景数）。
- **搜索**：输入 `q` 做全文检索，可叠加通用标签维度过滤（stance 等）。
- **抽取**：「抽取条款」按钮触发一个小批量语料抽取（最多 50 份），跑完回显
  `新增/跳过/失败/总条款数`。**全量抽取请走 CLI**，Web 只做增量。

### 9.2 类型详情页 `/clauses/{type}`

- 按**规范章节顺序**（当事人→鉴于→合同标的→价款及支付→履行期限→权利义务→违约责任→争议解决→附则→签署信息）分组展示条款。
- 过滤：`scenario`（业务场景下拉）、`category`（base/tagged/custom）、`q`（全文）。
- 每条条款渲染 markdown 正文，显示标签。
- **组装下载**：`/clauses/{type}/generate?format=pdf&scenario=...&stance=...`
  —— 这是**标签驱动组装**（custom>tagged>base + 一致性校验）后渲染的合同，带占位符。
  支持 docx / pdf。

### 9.3 条款 CRUD

- **新建** `/clauses/{type}/new`：选 category、填 section（默认「附则」）、写 body（markdown）、
  勾标签维度。保存后该条标记 `manual=true`，**重新抽取不会覆盖**。
- **编辑** `/clauses/{type}/clauses/{id}`：改 body / category / 标签，右侧实时预览渲染效果。
  可删除。
- 写条款时 body 里可以放 `{{slot}}` 占位符，组装时会保留并给出填空说明。

### 9.4 标签审核 `/clauses/review`

- 列出**待审核**的标签维度。
- 每条可**逐维度**审核（approved / rejected），或**整条批量审核**（review-all）。
- ⚠️ 一条 custom 条款**所有标签维度都是 `approved`** 才算「可组装（assembly-ready）」，
  否则组装时会被排除。改完标签记得来这里过一遍。

## 10. 仪表板（`/dashboard`）

pipeline 评测的统计看板（只读）。

- **总览**：总运行数、全通过数、平均通过率、覆盖的合同类型数。
- **分类型明细**：每个类型取**最优一次运行**（通过率最高），显示 rubric、通过条数/总条数、
  是否全通过、迭代轮次、得分、通过率、时间。
- **版本对比**：v1 / v2 / v3 各版本的运行数、平均通过率、全通过数——看 rubric 升版的效果。
- **最近 10 次运行**：时间倒序的流水。

> 数据来自 `pipeline_runs` 表（由 `pipeline_run` MCP / CLI 产生）。Web 只看，不在 Web 跑 pipeline。

## 11. 搜索（`/search`）

条款片段的 RAG 语义检索。

- 输入自然语言查询（中英文都行），返回排序后的条款片段（top 10）。
- 后端是 Elasticsearch / OpenRouter embedding；**后端不可用时返回 503**，不影响其他页面。

## 12. 语言切换

右上角 `中文 | English`。点切换会带 `?lang=zh`/`?lang=en` 跳转并写 cookie，之后访问默认用该语言。
模板里的标签（rubric/prompt 等字段名、flash 提示）都会跟着本地化；JSON 接口不受影响。

## 13. 常见操作流程（cookbook）

### 想生成一份「农产品买卖、偏买方」的合同

1. 去 **条款库** `/clauses`，确认 `sale` 类型下 `scenario=农产品买卖` 有 tagged 条款、
   且相关 custom 条款在 **标签审核** 里已 approved。
2. 进 `sale` 类型详情页 `/clauses/sale`，选 `scenario=农产品买卖`、（组装下载链接里）
   `stance=pro_a`、`format=pdf`，下载即可。
3. 下载的是**带 `{{slot}}` 占位符**的组装正文，需要后续填空（或交给生成 Agent，见
   [api_instruction.md](api_instruction.md)）。

### 想新增一条「违约责任」的 custom 条款

1. **条款库** -> 进对应类型详情页 -> 点「新建条款」。
2. category 选 `custom`，section 选「违约责任」，写 body，标签里勾 `stance`（如 `pro_a`）。
3. 保存后去 **标签审核** `/clauses/review` 把新条款的标签维度 approve 掉，否则组装时不生效。

### 想新建一版评分规则

1. **评分规则** -> 「新建」，name 填 `contract_<type>_v<新N>`，context 填 `contract`。
2. 填若干 criterion（每条 name + description + guidance）。
3. 保存后进详情页可继续增删调序。系统会自动把这版当作该类型最新 rubric。

### 想对比两个 prompt 谁起草得好

1. 先在 **提示词** 里确保有 ≥2 个同类型的 prompt。
2. **对比** -> 「新建」，选类型 + rubric + 写任务描述 + 勾选要对比的 prompt -> 运行。
3. 运行完进详情页看矩阵：哪条 criterion 哪个 prompt 通过了，一目了然。

## 14. 注意事项

1. **母版 vs 组装**：`/contracts/.../download` 下的是**母版空壳**；`/clauses/{type}/generate`
   下的是**组装后**合同。别下错。
2. **custom 条款必须审核才生效**：新建/改标签后要去 `/clauses/review` approve，否则组装时被排除。
3. **harbor rubric 只读**：来源是 harbor 的 rubric 不能在 Web 改，要改只能本地新建一版。
4. **大操作走 CLI**：全量条款抽取、大规模 prompt 对比，Web 会超时，用 CLI
   （`python -m src.clauses` / `python -m src.eval.compare`）。
5. **生成带占位符**：Web 下载的合同正文里 `{{slot}}` 是**原样保留**的，不会自动填值。
   填值是 Agent / 人工的活。
6. **flash 提示**：每次写操作后页面顶部会弹绿（成功）/红（失败）提示，红色时按提示信息修正。
7. **数据在远端库**：远端 `http://<retired-america-box-ip>:30820` 连的是生产 PostgreSQL + MinIO，
   在 Web 上的增删改**直接生效**，没有「草稿态」，操作前确认清楚。

---

*页面源码：`src/web/routes/`（`pages.py` / `contracts.py` / `clauses.py` / `law_info.py` /
`dashboard.py` / `search.py`），模板：`src/web/templates/`。所有页面都是对 `src.*` 服务层
的薄封装，数据问题查服务层；JSON 接口镜像见 `/api/docs`。*
