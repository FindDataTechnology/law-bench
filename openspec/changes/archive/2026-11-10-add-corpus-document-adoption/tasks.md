# Tasks — add-corpus-document-adoption

## 1. 存储侧读取（内核，域无关）

- [x] 1.1 `library_sources.ingest_rule.document` 解析：`{id, title, text, order, kind?, doc_filter?}`；缺映射抛具名错误
- [x] 1.2 `corpus_catalog.documents(conn, *, library_key, source_key, offset, limit, q)`：Qdrant facet/scroll 派生文档清单 + 总数；外接表来源走 SQL `GROUP BY`
- [x] 1.3 `corpus_catalog.document_chunks(...)`：按 `order` 取回一份文档的全部块（有上限，超限如实报）
- [x] 1.4 不可达/未声明映射的错误分类与文案（错误 ≠ 空）
- [x] 1.5 内核领域闸通过（`scripts/check_kernel_domain_free.py`）

## 2. 确定性条款切分（内核）

- [x] 2.1 `split_clauses(chunks, *, order_field)`：按 `keys.clause_no()` 切分，正文逐字
- [x] 2.2 跨块拼接 + `truncated` 标记（拼不全不假装完整）
- [x] 2.3 切不出条款返回 `no_clause_headers` 原因
- [x] 2.4 章节/序言/目录不被当条款（复用既有规则，测试覆盖）

## 3. 取用写路径（经内核）

- [x] 3.1 `corpus_catalog.adopt_document(...)`：建 `law` 单位，键按域归一，`attrs.corpus` + 证据
- [x] 3.2 `corpus_catalog.adopt_clauses(...)`：批量 `<law_key>#<N>`，`MAX_ADOPT_CLAUSES=200`，事务性，被拒整批回滚
- [x] 3.3 幂等：重复取不产生第二条，返回既有单位
- [x] 3.4 词表外类型被内核拒，错误信息带允许词表

## 4. 页面与路由

- [x] 4.1 `GET /d/{key}/library`：来源/文档/分页/搜索；已取入标注；错误态与空态分开
- [x] 4.2 `POST /d/{key}/library/adopt`（文档）、`POST /d/{key}/library/clauses`（条款）
- [x] 4.3 权限：只读角色看不到取用按钮；写需 `cap.can_write`
- [x] 4.4 域内导航加入「语料库」入口
- [x] 4.5 i18n 词条（zh/en）与空态文案

## 5. 数据登记（生产）

- [x] 5.1 为 `law-library` 七个来源补 `ingest_rule.document` 映射（幂等 UPDATE，可回滚）
- [x] 5.2 生产实测：目录可见文档（statutes 468 篇，民法典 355 块→1208 条）、总数与库一致；取入 4 部法 + 其条款；重复取幂等（nothing_new）
- [x] 5.3 生产实测：取条款后抽一次概念，`bad_endpoint` 不再因条款缺失而计（探针产出 concept + defines→民法典#第585条 双 pending，bad_endpoint=0；探针提案已以理由驳回）

## 6. 验证与收口

- [x] 6.1 单测：目录（含错误/空态/未声明映射）、切分（跨块/截断/无条款）、取用（幂等/上限/回滚）
- [x] 6.2 全量回归绿（基线 1647 passed / 60 skipped）
- [x] 6.3 `openspec validate add-corpus-document-adoption --strict`
- [x] 6.4 上产：build → relay → 部署 → 生产闭环实测
- [x] 6.5 归档 change 并更新蓝图台账 C6
