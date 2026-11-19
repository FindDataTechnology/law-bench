# gov-concept-layer Specification

## Purpose
政务域把概念当作本体实体接进来，并与公文建立依据关系：概念接地、悬空概念不算接地、反向关系被拒，v1 锚点仍然拒绝概念（旧域的形状不因新域而被改写）。接地率的读数必须区分「没有」与「空」——这两种在读数上都是一片零，而处置方向相反。

## Requirements

### Requirement: 政务概念作为本体实体

系统 SHALL 允许政务域（`gov`）的本体容纳 `concept` 类实体，且概念的键不带父文档（按归一名取键）；概念的语料面 SHALL 是该域已订阅的政务公开全文。

#### Scenario: 政务域接受概念候选
- **WHEN** 一个 `kind='concept'` 的候选提交到已切到 v2 模板的 `gov` 域
- **THEN** 词表闸放行，候选按提案层规则进箱，不直接写入本体

#### Scenario: v1 锚点仍然拒绝概念
- **WHEN** 同一个概念候选提交到仍钉 `gov-domain` v1 的域
- **THEN** 词表闸以 `bad_kind` 拒绝，并说明 v1 未声明 `concept`

### Requirement: 概念与公文的依据关系

系统 SHALL 提供 `defines` 关系把概念连到承载它的公文，方向固定为 **概念 → 公文**；反向提交 SHALL 被拒。

#### Scenario: 概念接地
- **WHEN** 一条概念以 `defines` 指向一份已在本体的公文，且该公文正文里逐字出现这条概念名
- **THEN** 该概念计入接地分子，`quality.grounding(namespace='gov')` 的分母与分子同时增加

#### Scenario: 悬空概念不被算作接地
- **WHEN** 概念已入本体但没有任何 `defines` 关系
- **THEN** 它只进分母，接地率因此下降；缺口清单里点名该概念

#### Scenario: 反向关系被拒
- **WHEN** 提交 `defines` 的 `from` 不是概念（例如公文 → 概念）
- **THEN** 提案层拒绝并说明方向要求

### Requirement: 接地率的读数必须区分「没有」与「空」

政务域的 `grounding` 在概念数为 0 时 SHALL 报 `None`（无分母），不得报 `0.0` 或 `1.0`。

#### Scenario: 没有概念时的读数
- **WHEN** 政务域一条活概念都没有
- **THEN** `grounding` 返回 `value=None` 且 `denominator=0`，缺口说明写「本域还没有概念」，不写「接地良好」

#### Scenario: 有概念之后的读数
- **WHEN** 政务域有 N 条活概念、其中 M 条有 `defines`
- **THEN** `grounding.value == M/N`，`gaps` 列出未接地的概念
