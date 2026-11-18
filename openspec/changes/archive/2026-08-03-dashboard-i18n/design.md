## Context

仪表板是最近新增的页面（`src/web/routes/dashboard.py` + `src/web/templates/dashboard.html`），所有文本都是硬编码中文。现有 i18n 系统通过 `LOCALES` 字典（`src/web/i18n.py`）提供中英文翻译，模板通过 `{{ t.section.key }}` 访问翻译字符串，`_locale_context` 处理器自动注入 `t` 变量到每个模板。

## Goals / Non-Goals

**Goals:**
- 仪表板页面支持中英文切换（通过现有 `?lang=en` / `?lang=zh` 开关）
- 复用现有 i18n 模式，不引入新机制

**Non-Goals:**
- 不修改其他页面的 i18n
- 不添加新语言

## Decisions

### D1: 在 LOCALES 中添加 dashboard 区块

在 `LOCALES["zh"]` 和 `LOCALES["en"]` 中各添加：
- `nav.dashboard`: 导航链接文本（"仪表板" / "Dashboard"）
- `dashboard` 区块: 包含 h1、stats 卡片标签、表格表头、版本对比标题等约 15 个字符串

### D2: 模板使用 {{ t.dashboard.xxx }}

将 `dashboard.html` 中所有硬编码中文替换为 `{{ t.dashboard.xxx }}`，与现有页面（如 `clauses_list.html`）的模式一致。

## Risks / Trade-offs

无风险。纯添加翻译字符串，不改变功能逻辑。
