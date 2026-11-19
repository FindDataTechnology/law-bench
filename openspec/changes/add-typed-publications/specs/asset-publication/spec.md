# asset-publication Specification

## Purpose

本体之外的知识资产（尺子、金集）也要能被发布成一个带 digest 的不可变版本：只有快照可比，两次评测的分数才有意义。种类由 pack 注册，内核只管版本、digest、不可变性与拉取——它不认识任何行业，也不新增第二份 digest 实现。

## ADDED Requirements

### Requirement: 发布种类由 pack 注册

系统 SHALL 以注册制支持多种可发布资产，MUST NOT 在内核里枚举行业种类。

每个种类 SHALL 由 pack 声明一份**条目投影**：从该域的书架上取哪些条目、每条以什么键寻址、投影出哪些字段、按什么键排序。投影契约 SHALL 与既有资产目录的 provider 契约同形（自包含 SELECT + 展示名），使「书架上的东西」与「能发布的东西」用同一套词汇。

未注册的种类 SHALL 在发布与拉取两处都被拒绝并列出已注册种类，MUST NOT 返回空清单充当成功。

#### Scenario: 未注册种类被拒

- **WHEN** 请求发布或拉取一个未注册的资产种类
- **THEN** 拒绝并列出已注册种类，不产生发布行

#### Scenario: 新种类不需要改内核

- **WHEN** 一个 pack 登记了新的资产种类及其条目投影
- **THEN** 该域可发布该种类，内核代码零改动

### Requirement: digest 只有一份实现

条目投影产出的内容 SHALL 交给既有的规范序列化内核计算 digest（键序归一、排除生成时间戳）；MUST NOT 为新种类各自实现一份 digest 逻辑。

投影形状版本 SHALL 位于载荷之外、不进入 digest——否则每次引入新形状都会作废已发布的所有 digest。

#### Scenario: 同一内容两种入口得同一 digest

- **WHEN** 同一份资产内容分别经发布入口与直接调用规范序列化计算
- **THEN** 两次得到的 digest 逐字节相等

#### Scenario: 形状版本不进 digest

- **WHEN** 只用同一内容、把投影形状版本从 1 升到 2
- **THEN** digest 不变，且载荷里声明的形状版本随之改变

### Requirement: 发布是不可变且幂等的

每次发布 SHALL 产生单调递增的版本号，并相对上一版本产生变更日志（新增 / 删除 / 变更，变更含字段级摘要）；首版 SHALL 记为初始清单。

同 digest 重复发布 SHALL 幂等：返回既有版本，MUST NOT 产生新行。已发布版本 SHALL 不可改写、不可删除。

#### Scenario: 重复发布幂等
- **WHEN** 内容零变更时再次发布同一种类
- **THEN** 返回既有版本与既有 digest，不产生新行

#### Scenario: 空内容发布被拒
- **WHEN** 该域书架上该种类没有任何条目
- **THEN** 发布被拒并报明「该种类无可发布内容」，不产生空版本

### Requirement: 按种类的机器拉取面

系统 SHALL 提供按种类拉取已发布版本的机器通道：`GET /api/v1/distribution/{domain_key}/{kind}`，头 `X-Consumer-Token`，支持指定版本或缺省最新。

鉴权 SHALL 三态如实区分：无凭据 401；令牌未登记或已吊销 403（报明）；令牌有效但域不在绑定范围 403（报明）。拉取面 MUST NOT 依赖 Logto 交互会话。

每次成功拉取 SHALL 留下只增的拉取足迹（消费者、域、种类、版本、时间），失败与未匹配 MUST NOT 留足迹。

#### Scenario: 拉取最新尺子
- **WHEN** 绑定该域的消费者拉取其 `rubric` 最新版
- **THEN** 返回域、种类、版本、digest、形状版本与条目全量，并留下一条拉取足迹

#### Scenario: 越域拉取被拒
- **WHEN** 消费者拉取其未绑定域的任一已注册种类
- **THEN** 403 并报明「域不在绑定范围」，且不留拉取足迹

#### Scenario: 失败不写足迹
- **WHEN** 令牌已吊销的消费者请求拉取
- **THEN** 403 且拉取足迹不新增行

### Requirement: 发布不等于归属

发布某资产 SHALL NOT 改变它在任何域书架上的归属：归属是目录语义，发布是版本语义。解除归属 MUST NOT 影响已发布版本的可用性与 digest；发布某资产 MUST NOT 自动把它归属到其它域。

#### Scenario: 解除归属不动已发布版本
- **WHEN** 某尺子被归到域 A 与域 B，A 发布了它，随后 A 解除归属
- **THEN** A 的已发布版本仍可按版本号与 digest 拉取，内容与 digest 不变

#### Scenario: 发布不扩散归属
- **WHEN** 域 A 发布了某尺子
- **THEN** 该尺子不会出现在域 B 的书架上，除非显式归属
