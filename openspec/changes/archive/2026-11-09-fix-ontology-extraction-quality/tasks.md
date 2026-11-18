## 1. 键的构造与归一

- [x] 1.1 `slug(text)`：去全角空格/书名号/标点，折叠空白为 `-`，长度上限；验证＝单测：`中华人民共和国 宪法（2018年修正文本）` → 稳定 slug，同输入两次一致
- [x] 1.2 `canonical(name)`：按 D3 规则链归一（去国家名前缀 → 去尾随括号修饰），返回 `(canonical, applied_rules)`；验证＝单测：`宪法`/`中华人民共和国宪法` 同键；`中华人民共和国宪法修正案` 与前者**不同**键
- [x] 1.3 `clause_no(text)`：只认 `第<数字>条`，中文数字转阿拉伯；验证＝单测：`第十二条`→`12`、`第一百二十三条`→`123`；`序言`/`第二章`/`第三节`/`目录` → None
- [x] 1.4 `clause_key(law_key, n)` = `f"{law_key}#第{n}条"`；验证＝单测：不同 law_key 同 n 得到不同键

## 2. 法规类标题校验

- [x] 2.1 `law_name_matches(name, title)`：两边都按 1.2 归一，要求「去修饰后精确相等」；验证＝单测：`中华人民共和国` vs `中华人民共和国宪法修正案（2018年）` → False；`中华人民共和国宪法` vs `中华人民共和国宪法（2018年修正文本）` → True
- [x] 2.2 校验失败计入 `type_mismatch`，不进入提案；验证＝单测：一条误判候选被拒且计数 +1

## 3. 抽取接入这四道关

- [x] 3.1 `run()` 在逐字校验之后依次执行：条款父法解析 → 条款号合法 → 别名归一 → 法规标题校验；任一步拒即计入对应计数键；验证＝单测：四类坏候选各 1 条，四个计数各 +1
- [x] 3.2 条款候选的父法从 chunk 的 `title` 取（缺失时从 `law_id` 兜底并在 attrs 标注 `parent_source`）；验证＝单测：title 存在时用 title，缺失时用 law_id 且 attrs 有标注
- [x] 3.3 归一后的重复在同一批内折叠，计入 `duplicate`；验证＝单测：同批两种写法只提交一条
- [x] 3.4 报告新增 `usable_rate` 与 `low_yield`（阈值默认 0.5，可用 `EXTRACT_MIN_USABLE_RATE` 覆盖）；验证＝单测：produced=4/submitted=1 → low_yield=True

## 4. 页面与批次可见

- [x] 4.1 收件箱批次表显示可用率与「低产」标记；验证＝页面测试：低产批次出现标记
- [x] 4.2 本体区单位列表对条款类显示 `law_key#条款号` 而不是裸号；验证＝页面测试：导入一条条款后列表显示带父法的键

## 5. 与导入对齐

- [x] 5.1 `ontology_import.plan()` 的键校验复用同一套 `canonical`/`clause_no`：手写导入也不再接受裸条款号；验证＝单测：导入一条 `kind=clause, key=第十二条` 被拒并说明缺父法

## 6. 收口

- [x] 6.1 `openspec validate fix-ontology-extraction-quality --strict` 通过
- [x] 6.2 全量 pytest 不回归（基线 1582 passed / 60 skipped）
- [x] 6.3 生产复跑同一批 20 块（`sha-8fb1f3d`）：裸条款号 0 / 国家名冒充 law 0 / 归一折叠 3 / 结构名拒 1；可用率 0.529→0.429 且判低产（拒绝原因均口径可解释，非模型胡说）。见 `reports/2026-11-09-key-scheme-acceptance.md`
- [x] 6.4 验收报告：`reports/2026-11-09-key-scheme-acceptance.md`（八类拒绝计数、新旧对照、扩量还差两件事：换语料面 + 抽样均衡）
