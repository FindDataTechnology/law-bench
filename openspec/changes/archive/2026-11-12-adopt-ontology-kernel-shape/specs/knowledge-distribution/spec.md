## MODIFIED Requirements

### Requirement: 版本化发布

领域负责人（或平台管理员）SHALL 可将其成员域的本体内容发布为不可变版本快照：单调发布版本号、digest（规范 JSON 的 sha256，键序归一、排除生成时间戳）、全量 manifest（模板版本锚定、实体与关系全量、排除软删项）；同 digest 重复发布 SHALL 幂等（静默返回既有版本，不产生新行）；快照发布后 SHALL 不可改写不可删除；变更事件流与发布流水 SHALL 可对账（发布的每条内容可回指其事件史）。

规范形态（条目键集、排序键、类型归一）与 digest 配方 SHALL 由共享内核持有，本面 MUST NOT 再有一份自己的实现——两面各写一遍，一旦对「同一内容」判定不一致，跨面比对即失去意义。发布的 manifest SHALL 为**键寻址形状**（条目以 `kind` + `external_key` 寻址、关系以两端键寻址），形状版本与所遵循的内核契约版本 SHALL 随发布物一并声明；声明不受支持时系统 SHALL 拒绝而不是猜测。形状版本 SHALL 位于载荷之外，MUST NOT 进入 digest——否则每次引入形状都会作废已发布的所有 digest。

#### Scenario: 发布产生可拉取版本

- **WHEN** 领域负责人对其域执行发布且域内有词表内实体与关系
- **THEN** 产生新发布版本（版本号单调、digest 稳定、manifest 含实体与关系全量并锚定模板版本），软删项不出现在 manifest

#### Scenario: 同内容重复发布幂等

- **WHEN** 内容零变更时再次执行发布
- **THEN** 返回既有版本与既有 digest，不产生新快照行

#### Scenario: 空域发布拒绝

- **WHEN** 对没有任何词表内内容的域执行发布
- **THEN** 发布被拒并报明域内无内容，不产生空版本

#### Scenario: 换底不改已发布 digest

- **WHEN** 对换底前落库的任一发布快照按 manifest 重算 digest
- **THEN** 重算值与库中 digest 逐字节相等（等价测试 `tests/test_distribution_kernel.py` 22 条 + 内核 golden 6 例钉住）

#### Scenario: 形状未声明或不受支持即拒

- **WHEN** 适配方声明的 manifest 形状不在内核支持的集合内（当前支持 1=id 寻址、2=键寻址）
- **THEN** 内核在构造时即拒绝并报明「声明不受支持」，而不是按默认形状猜着跑
