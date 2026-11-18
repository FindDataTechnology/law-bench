## 1. 取样：按源分页取块（可复现）

- [x] 1.1 `extraction.sample_chunks(conn, domain_path, sources, limit, cursor)`：按 `source_key` 分层、`(law_id, chunk_no)` 稳定排序分页，返回 `{chunk_id, law_id, title, chunk_no, text, source_key}`；验证＝单测：同一游标两次调用返回同一批（顺序稳定），跨页不重叠
- [x] 1.2 取样排除冒烟内容（复用 `ontology_import.is_smoke` 的判定口径，按块文本判定）；验证＝单测：含「冒烟」/`smoke` 的块不出现在取样结果里
- [x] 1.3 取样只走已订阅范围（`libraries.effective_sources`），越界源被拒；验证＝单测：未订阅的源出现在参数里时报错并列出可用源

## 2. 逐字证据闸

- [x] 2.1 `extraction.verify_quote(quote, chunk_text)`：空白归一化后做子串查找，返回布尔与归一化后的片段；验证＝单测：完全一致 / 多空格 / 换行差异 通过；改写一词 / 截断到半个词 不通过
- [x] 2.2 收集被丢弃的候选并分类计数（`bad_quote` / `bad_kind` / `bad_endpoint` / `duplicate`）；验证＝单测：构造四类坏候选，报告里四类各计 1

## 3. 候选生成（模型 → 候选，纯函数边界）

- [x] 3.1 `extraction.build_prompt(domain_schema, chunks)`：把词表与块文本拼成提示词，提示词带版本号常量；验证＝单测：输出包含全部 `entity_types` 与 `relationship_kinds`，且版本号出现在串里
- [x] 3.2 `extraction.parse_candidates(raw_text)`：解析模型输出为候选列表（容忍代码围栏与 JSON 前后的解释文字），字段缺失的行标记为坏行而不是整体失败；验证＝单测：给带 ```json 围栏、带前后说明、以及一行缺字段的三种输入，分别得到 解析成功 / 解析成功 / 该行坏
- [x] 3.3 `extraction.normalize_entity_key(title, kind)`：外部键生成规则（去空白、长度上限、非法字符替换），保证同名实体稳定同键；验证＝单测：同一实体两种写法（含空格/全半角）产出同一键

## 4. 提交提案（不写本体）

- [x] 4.1 `extraction.run(...)`：取样 → 生成 → 逐条校验 → `proposals.submit()`，返回报告 `{sampled, produced, submitted, skipped: {...}, stopped}`；验证＝单测：一次运行后 `knowledge_units` 行数不变、`domain_proposals` 增加相应条数
- [x] 4.2 `source` 记 `extract:<model>:<prompt_version>`，`evidence` 含 `chunk_id`/`quote`/`library`/`source_key`/`batch`，`impact` 写入被引原文；验证＝单测：断言这三处字段齐全
- [x] 4.3 幂等：同一批重复运行「新增」为 0，重复项计入 `duplicate`；验证＝单测：连跑两次，第二次 `submitted=0`
- [x] 4.4 三处上限（块数/每块候选/总候选）与触顶报告；验证＝单测：把总上限设成 3，跑一批 10 块的语料，报告 `stopped="cap"` 且 `produced<=3`

## 5. 复核：按批次筛选与批量确认

- [x] 5.1 收件箱支持 `?batch=` 筛选（读 `evidence->>'batch'`）；验证＝单测：两批候选混合时按批次只看到对应那批
- [x] 5.2 `POST /d/{domain}/inbox/batch`：对选中批次执行批量确认或批量驳回，逐条走提案确认路径，逐条报告；验证＝单测：批量确认 3 条里含 1 条非法，得 2 成功 1 失败且不回滚
- [x] 5.3 单条确认后本体变化有事件、其余候选仍在 pending；验证＝单测：确认 1 条后 `knowledge_units` +1、`authoring_events` +1、pending 数 -1

## 6. 收口

- [x] 6.1 `openspec validate add-ontology-extraction-candidates --strict` 通过
- [x] 6.2 全量 pytest 不回归（基线 1545 passed / 60 skipped）
- [x] 6.3 生产小样：通道切到萬星词元后跑通（20 块 `statutes`，sampled=20/produced=17/submitted=9/duplicate=5/bad_quote=3），本体零变化。**同时发现候选质量不合格**（条款键丢父法、同实体多键、类型判错），已记 `reports/2026-11-09-extraction-acceptance.md`，后续另开变更
- [x] 6.4 验收报告：`reports/2026-11-09-extraction-acceptance.md`（五条约束逐条对证 + 产量分布 + 质量评估 + 三项后续）
