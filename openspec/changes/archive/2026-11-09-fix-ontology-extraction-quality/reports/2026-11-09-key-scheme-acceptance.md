# 键方案验收（2026-11-09，镜像 `sha-8fb1f3d`，词元 `deepseek-v4.1-flash`）

## 一、同一批语料，新旧口径对照

同一命令（legal 域 `statutes` 源、20 块、每块上限 4、总上限 20），只换了代码：

| | 旧口径（`sha-9bad7c5`） | 新口径（`sha-8fb1f3d`） |
|---|---|---|
| produced / submitted | 17 / 9 | 14 / 6 |
| 可用率 | 0.529 | **0.429（低产，已标记）** |
| 裸条款号键 | 有（`第十二条`、`第三十二条`） | **0** |
| 国家名冒充 law | 有（`中华人民共和国`） | **0**（`type_mismatch=1` 拦下） |
| 同实体多写法 | 三条并列 | `normalised=3` 折叠 |
| 结构名当条款 | `序-言` | `not_clause=1` 拒 |
| 键形态 | 混杂 | 全部可寻址 |

新口径产出的键（生产实取）：

```
[law   ] 宪法修正案
[clause] 宪法修正案#第12条 / #第18条 / #第1条 / #第3条 / #第4条
```

`中华人民共和国宪法修正案` 归一成 `宪法修正案`（去掉国家名前缀），条款全部带父法。
**注意它没有和 `宪法` 合并** —— 修正案是另一份文档，这正是归一的边界。

## 二、八类拒绝原因确实可分辨

```
bad_quote=2      模型编造引用（逐字闸）
not_clause=1     「序言」冒充条款
type_mismatch=1  「中华人民共和国」不是块标题所指的那份法
normalised=3     同实体另一种写法，已折叠
duplicate=1      幂等命中（上一批已有）
missing_parent=0 bad_kind=0 bad_endpoint=0
```

这组数字直接告诉你该做什么：`bad_quote` 高 → 修提示词；`not_clause`/`type_mismatch`
高 → 修口径；全是 `duplicate` → 这批语料已经抽过了。

## 三、可用率 0.429，判为低产

阈值 0.5（`EXTRACT_MIN_USABLE_RATE` 可覆盖）。**低产不等于不能跑**，它说的是
「先别扩量」：14 条候选里 6 条可用，其余 8 条的拒绝原因都是**口径层面可解释的**
（编造引用 2、结构名 1、类型误判 1、折叠 3、幂等 1），不是「模型胡说」。

要真扩量到 36 万块，还差两件事（不属于本变更）：

1. **语料结构决定了产出的类型**：`statutes` 分块基本是「法名 + 第N条 + 条文」，
   所以抽出来的必然是法规与条款；想要概念类实体（如「违约责任」），得换语料面
   （司法解释、裁判要旨、条文释义），或跨块聚合上下文。
2. **抽样只覆盖了 20 块**：`sampled=20` 里 2 部法，簇在宪法系列。扩量时才看得出
   分布是否均衡——报告里的 `by_kind` 与拒绝分布就是给这件事用的。

## 四、机制侧的验证

- 内核禁词闸：`src/bench/keys.py` 无任何域词汇；域规则在 `packs/legal/entity_keys.py`，
  由 pack 导入时注册进内核注册表（`keys.register_rules`），内核只问「这个域有哪些规则」。
  我第一版直接 `from packs.legal import ...`，被 `test_kernel_imports_no_pack` 逮住。
- 归一不做模糊：`宪法` 与 `宪法修正案` 明确不合并（`DOCUMENT_SUFFIXES` 显式列出）。
- 手写导入同规：`kind=clause` 的键必须带 `#父法`，不许绕过抽取的键规则。

## 五、收尾：旧批次已驳、冒烟单元已软删（2026-11-09）

```
before: sample-statutes-2026-11-09   pending 16
        keyscheme-statutes-2026-11-09 pending 6
after : sample-statutes-2026-11-09   rejected 16   ← 走真实批量驳回路由（lead 闸 + admin 直通）
        keyscheme-statutes-2026-11-09 pending  6   ← 留给人复核
legal 域的 live 单元：[]（smoke-clause-001 已软删，可恢复）
```

estate 现在如实报缺口：

```
legal ontology: {declared_types: 2, curated_units: 0, smoke_units: 1}  gaps: ['ontology']
```

`curated_units=0` 是对的——本体的真实内容仍是空的。这条从「看起来有 1 条」
变成「0 条 + 1 条测试数据」，是这一路修下来最该有的诚实状态。
