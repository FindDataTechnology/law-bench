## 1. Schema: `prompts` table

- [x] 1.1 Append `CREATE TABLE IF NOT EXISTS prompts (...)` to `SCHEMA` in `scripts/extract_harbor_rules.py` with columns: `id` PK, `name TEXT NOT NULL UNIQUE`, `contract_type TEXT NOT NULL`, `purpose TEXT NOT NULL`, `content TEXT NOT NULL`, `source TEXT NOT NULL`, `description TEXT`, `created_at TEXT NOT NULL`
- [x] 1.2 Extend `print_summary` in `extract_harbor_rules.py` to also report the `prompts` row count (so seeders/extraction show prompts alongside rubrics)
- [x] 1.3 Verify `create_schema()` creates the `prompts` table on a fresh DB and that re-running `extract_harbor_rules.py` leaves existing `rubrics`/`criteria` counts unchanged (additive only)

## 2. Prompt manage layer (`src/eval/manage.py`)

- [x] 2.1 Add `_get_prompt`/`_get_prompt_by_name` helpers mirroring the rubric helpers
- [x] 2.2 Add `list_prompts()` (name, contract_type, purpose, source) and `get_prompt(name)` (full fields incl. content)
- [x] 2.3 Add `create_prompt(name, contract_type, purpose, content, description)` - validates non-empty name/content, raises `ConflictError` on duplicate name, inserts with `source='local'`
- [x] 2.4 Add `update_prompt(prompt_id, name, contract_type, purpose, content, description)` - raises `NotFoundError`/`ConflictError` as appropriate
- [x] 2.5 Add `delete_prompt(prompt_id)` - raises `NotFoundError` if missing; cascades nothing (no child table)
- [x] 2.6 Confirm no `HarborReadOnlyError` path is added (prompts are always `source=local` and fully editable)

## 3. Prompt web API (`src/web/routes/api.py` + `src/web/models.py`)

- [x] 3.1 Add Pydantic models `PromptCreate` (name, contract_type, purpose, content, description?) and `PromptUpdate` (same) to `src/web/models.py`
- [x] 3.2 Add `GET /api/prompts` (list) and `GET /api/prompts/{name}` (detail) delegating to `manage`
- [x] 3.3 Add `POST /api/prompts` (201), `PATCH /api/prompts/{name}`, `DELETE /api/prompts/{name}` delegating to `manage`; confirm `ManageError` subclasses map to 400/404/409 via the existing `app.py` handlers

## 4. Prompt web UI (`src/web/routes/pages.py` + templates)

- [x] 4.1 Add HTML routes: `GET /prompts` (list); `GET /prompts/new`; `GET /prompts/{name}` (detail); `GET /prompts/{name}/edit` - define `/prompts/new` before `/{name}` so "new" is not captured as a name
- [x] 4.2 Add POST handlers for create/update/delete mirroring the rubric flows (use `_flash` for `ManageError`)
- [x] 4.3 Create `templates/prompts_list.html`, `templates/prompt_detail.html`, `templates/prompt_form.html` mirroring the rubric templates (form collects name/contract_type/purpose/description/content; content as a textarea)
- [x] 4.4 Add a `Prompts` nav link to `templates/base.html` alongside the `Rubrics` link
- [x] 4.5 Smoke-test the UI: create a prompt via the form, view it, edit its content, delete it - each flow redirects correctly and flashes errors on invalid input

## 5. Chinese per-class rubrics seed (`scripts/seed_contract_rubrics.py`)

- [x] 5.1 Create `scripts/seed_contract_rubrics.py` reusing `DEFAULT_DB`, `create_schema`, `print_summary`, `project_root` from `extract_harbor_rules` and the `upsert_local_rubric` shape from `seed_sample_local_rubric`
- [x] 5.2 Define the 4 shared base criteria (party_identification, governing_law_present, clause_completeness, legal_citation_accuracy) in Chinese as a constant
- [x] 5.3 Author the 19 rubric dicts (`contract_<type>_v1`), each = base + 4-6 type-specific Chinese criteria, per the criteria-theme map: sale(买卖: 标的物所有权转移/风险转移时点/检验期间/瑕疵担保/所有权保留), utilities(供水电气热: 中止供应通知/计量与价格/连续供应义务), gift(赠与: 任意撤销/法定撤销/交付与登记/附义务赠与), loan(借款: 利率上限LPR四倍/利息支付/提前还款/借款用途), guarantee(保证: 保证方式/保证期间/保证范围/主合同变更影响), lease(租赁: 租期≤20年/租金与支付/优先承租权/维修义务/转租限制), financing_lease(融资租赁: 租赁物所有权与登记/租金构成/瑕疵与维修/期满归属), factoring(保理: 应收账款转让通知/有-无追索权/应收账款描述/回购反转让), work(承揽: 工作成果交付与验收/材料提供与风险/定作人指示协助/留置权), construction(建设工程: 工程范围与工期/竣工验收/工程款支付结算/质量保修/优先受偿权), transport(运输: 运输标的与运到期限/客票托运单/灭失毁损赔偿/免责事由), technology(技术: 技术成果权属/保密/后续改进/开发风险分担/价款使用费), bailment(保管: 保管物交付与返还/保管期间/赔偿责任有偿无偿/危险告知), warehousing(仓储: 仓单/储存期间/提取与验收/危险物告知/赔偿限额), entrustment(委托: 委托事务与权限/转委托/报告义务/费用与报酬/任意解除权), property_service(物业服务: 服务内容与标准/收费/业主解聘权/交接/专项维修资金), brokerage(行纪: 行纪人自有名义/价格差额补偿/买受出卖义务/报酬), intermediation(中介: 报告媒介义务/如实报告/报酬支付条件/费用承担), partnership(合伙: 出资/利润分配与亏损分担/合伙事务执行/入伙退伙/解散清算)
- [x] 5.4 Implement the idempotent seed loop (upsert each rubric by name+source='local'); print a summary (rubric name + criterion count)
- [x] 5.5 Run `uv run python scripts/seed_contract_rubrics.py` and verify via `python -m src.eval.run --list-rubrics` (or `sqlite3`) that 19 new `contract_<type>_v1` rubrics appear and harbor + `contract_drafting_v1` rows are untouched

## 6. Generation prompts seed (`scripts/seed_contract_prompts.py`)

- [x] 6.1 Create `scripts/seed_contract_prompts.py` reusing `DEFAULT_DB`, `create_schema`, `print_summary`, `project_root` from `extract_harbor_rules`
- [x] 6.2 Add `upsert_local_prompt(conn, prompt, now_iso)` matching by `name` (UNIQUE) - `UPDATE` if present, else `INSERT` with `source='local'` (single-row upsert; no child rows)
- [x] 6.3 Author the 19 per-type drafting prompt dicts (`draft_<type>`, `purpose='drafting'`, `contract_type=<type>`), each `content` a Chinese drafting instruction tailored to that type's mandatory clauses (mirroring the rubric themes)
- [x] 6.4 Implement the idempotent seed loop; print a summary (prompt name + contract_type)
- [x] 6.5 Run `uv run python scripts/seed_contract_prompts.py`; verify 19 prompts in `prompts` table and `rubrics`/`criteria` counts unchanged

## 7. Tests

- [x] 7.1 Extend `tests/test_manage.py` with prompt CRUD cases: create, duplicate-name conflict, get/not-found, update, delete; assert `source='local'` and uniqueness
- [x] 7.2 Add a test that harbor re-extraction (or `create_schema` re-run) leaves `prompts` rows untouched
- [x] 7.3 Add web-route tests for `/api/prompts` (list, create 201, conflict 409, not-found 404) mirroring any existing rubric API tests
- [x] 7.4 Run `uv run pytest` and confirm all green

## 8. Validation

- [x] 8.1 Re-run both seed scripts; confirm idempotency (row counts unchanged, no duplicates, harbor rubrics and `contract_drafting_v1` untouched)
- [x] 8.2 Confirm `_templates_reference()` and `src/crew.py` are unchanged (no crew runtime change)
- [x] 8.3 Run `openspec validate chinese-rubrics-and-prompt-management` and confirm `openspec status --change chinese-rubrics-and-prompt-management` reports all artifacts done
