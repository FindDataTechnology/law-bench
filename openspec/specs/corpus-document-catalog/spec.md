# corpus-document-catalog Specification

## Purpose
目录回答「这个库里有什么可取材」，且区分两种空：库不可达与库确实没有。它存在的理由是选材时只有一个「空列表」可看，而「连不上」与「没东西」的处置方向相反——前者该等，后者该换源。文档结构由来源自述，换一个库不改代码。

## Requirements

### Requirement: 目录按文档列出可取材范围

系统 SHALL 提供一个域内的语料文档目录，把该域订阅来源里的语料按**文档**（不是按语料块）列出，每行至少包含：标题、来源、类别/类型、发布日、状态、语料块数、以及「是否已在本体」。目录 SHALL 支持按来源过滤、按标题检索与分页，并 SHALL 返回该过滤条件下的文档总数。

#### Scenario: 法律域可见法规文档
- **WHEN** 有 `law-library` 订阅的成员打开 `/d/legal/library`
- **THEN** 他看到的是一份文档清单（如「中华人民共和国宪法」「常州市地下管线管理条例」），而不是 364,916 条语料块

#### Scenario: 已取入的文档被标注
- **WHEN** 某文档的规范名已存在对应的 `law` 单位
- **THEN** 目录该行标注「已取入」，而不是让用户重复取一次

### Requirement: 目录是存储的派生，且区分不可达与空

目录 SHALL 实时派生自语料存储，MUST NOT 落第二份文档表。存储不可达时 SHALL 返回明确的错误（含存储侧原话），MUST NOT 以空列表或零计数呈现。来源未声明文档结构时 SHALL 明确报「该来源未声明文档结构」，MUST NOT 静默跳过。

#### Scenario: 库不可达
- **WHEN** Qdrant 不可达
- **THEN** 目录显示错误与原因，`total` 不显示为 0

#### Scenario: 来源缺文档映射
- **WHEN** 某来源的 `ingest_rule` 没有 `document` 映射
- **THEN** 该来源在目录里报「未声明文档结构」，不出现 0 篇文档的假空态

### Requirement: 文档结构由来源自述

「怎么从某来源的存储里读出文档 id、标题、正文、顺序」SHALL 由该来源登记的 `ingest_rule.document` 声明；内核代码 MUST NOT 写死任何领域的字段名。

#### Scenario: 换一个库不改代码
- **WHEN** 新增一个正文表形式的来源（外接 pgvector 表），声明自己的 `document` 映射
- **THEN** 它出现在同一张目录里，不需要改内核代码

#### Scenario: 内核无领域词
- **WHEN** 运行内核领域闸（`scripts/check_kernel_domain_free.py`）
- **THEN** 通过：目录模块不含任何领域词汇
