# wire-integration Specification（delta）

## ADDED Requirements

### Requirement: 连接器不是常驻同步通道

连接器 SHALL 以**一次性 seed 导入**与**单向标注回写**两种操作使用，MUST NOT 被部署为持续镜像 wire 的常驻同步通道。

「常驻同步」的判据不是有没有定时器，而是**知验台是否依赖 wire 的持续变化**：若知验台的创作、评审或发布流程会因 wire 停止变化而停滞或报故障，则该部署已构成常驻同步，违反本要求。

本要求与 `bench-wire-seam` 的两层权威边界配套：wire 是本地层（权威在客户），知验台发布的域本体是共享层（权威在平台），两层之间只经 crosswalk 连接。

#### Scenario: 一次性导入后长期无变化
- **WHEN** 对 wire 图谱执行一次 seed 导入，此后 wire 三十天无任何变化
- **THEN** 知验台的升格、创作、评审与发布流程照常运转，不产生同步停滞告警

#### Scenario: 常驻镜像被识别
- **WHEN** 某部署配置了定时拉取 wire 图谱并依赖其持续到达来推进知验台流程
- **THEN** 该部署被判定为常驻同步通道，须改为一次性导入

## MODIFIED Requirements

### Requirement: 真实同步幂等

真实拉取的**幂等性** SHALL 与 hermetic 链相同：同步后知验台侧身份键与 wire 全等（wire 为 seed 原料身份参照，零第二份身份存储）；重复同步零新增行、unchanged 不 bump 更新时间。

幂等 SHALL 只对**重复导入同一份输入**成立，MUST NOT 被引申为「必须持续同步」。持续同步不是本能力的要求，其部署形态受「连接器不是常驻同步通道」约束。

#### Scenario: 首次真实拉取
- **WHEN** 对 scope 客户（drillcust001）执行 `sync_now()`
- **THEN** wire 图谱节点/边入库，身份键与 wire 逐条全等，同步报告（created/updated/unchanged）留档

#### Scenario: 重复同步零漂移
- **WHEN** 紧接重跑 `sync_now()`
- **THEN** created/updated 为空集，unchanged 覆盖全量，无新增行

#### Scenario: 幂等不等于持续同步
- **WHEN** 有人主张「因为幂等，所以可以定时常驻跑」
- **THEN** 该推论不成立；常驻部署须按「连接器不是常驻同步通道」判定
