## Why

仪表板页面（`/dashboard`）目前所有 UI 文本都是硬编码中文，没有接入现有的 i18n 系统（`src/web/i18n.py` 的 `LOCALES` 字典 + Jinja `{{ t.xxx }}` 模式）。其他所有页面（评分规则、提示词、条款库等）都已支持中英文切换，仪表板是唯一缺失的页面。

## What Changes

- 在 `src/web/i18n.py` 的 `LOCALES["zh"]` 和 `LOCALES["en"]` 中添加 `nav.dashboard` 导航链接文本
- 在 `LOCALES["zh"]` 和 `LOCALES["en"]` 中添加 `dashboard` 区块，包含仪表板所有 UI 字符串（标题、总览卡片标签、表格表头、版本对比标题等）
- 更新 `src/web/templates/dashboard.html`，将硬编码中文替换为 `{{ t.dashboard.xxx }}` 和 `{{ t.nav.dashboard }}`
- 更新 `src/web/templates/base.html` 导航链接，使用 `{{ t.nav.dashboard }}` 替代硬编码"仪表板"

## Capabilities

### New Capabilities
<!-- None -->

### Modified Capabilities
- `web-i18n`: 在 LOCALES 字典中添加 dashboard 导航和页面翻译字符串，支持中英文切换

## Impact

- **修改文件**: `src/web/i18n.py`（添加翻译字符串）、`src/web/templates/dashboard.html`（使用 i18n 变量）、`src/web/templates/base.html`（导航链接 i18n）
- **无新依赖**: 复用现有 i18n 基础设施
- **向后兼容**: 默认中文，不影响现有功能
