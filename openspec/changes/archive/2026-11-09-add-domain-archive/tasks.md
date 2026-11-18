## 1. 存储与模型

- [x] 1.1 `domains` 增 `archived_at TIMESTAMPTZ`（可空，纯增量）；验证＝在旧形状库上重放 schema 不报错，现有域 `archived_at IS NULL`
- [x] 1.2 `workspaces.archive_domain(conn, domain_key, actor)`：只写时间戳，返回更新后的行；已归档时幂等；验证＝单测：归档两次不报错、时间戳不漂移
- [x] 1.3 `workspaces.restore_domain(...)`：只清空时间戳；验证＝单测：恢复后 `archived_at IS NULL`，其它列逐列不变

## 2. 读侧过滤

- [x] 2.1 `list_domains(include_archived=False)`：默认排除归档域；`user_id` 版同样过滤；验证＝单测：归档一个域后默认列表少一条，`include_archived=True` 又出现
- [x] 2.2 缺口矩阵与域切换器跟随（都经 `list_domains`）；验证＝单测：归档后矩阵行数减一、切换器不含该域
- [x] 2.3 检索不可达：归档域的 path 不在任何可达域集合里；验证＝单测：归档子域后 `effective_sources(该 path)` 仍可解析（数据未动），但名录已无它

## 3. key 不复用

- [x] 3.1 建域时若 key 属于已归档域，拒绝并提示「已归档，需恢复或换 key」；验证＝单测：归档后同名建域被拒，报错文案含 `archived`

## 4. 界面

- [x] 4.1 `/d` 增加「含已归档」切换；已归档行标注徽章与「恢复」按钮（admin）；验证＝页面测试：归档后默认不可见、切换后可见且带徽章
- [x] 4.2 admin 域管理页给每个域一个「归档」按钮（admin 门）；验证＝页面测试：非 admin 看不到按钮、POST 被拒

## 5. 收口

- [x] 5.1 `openspec validate add-domain-archive --strict`；全量 pytest 不回归（基线 1637）
- [x] 5.2 验收报告：归档→名录消失→数据仍在→恢复→原样，一条可复核的闭环
