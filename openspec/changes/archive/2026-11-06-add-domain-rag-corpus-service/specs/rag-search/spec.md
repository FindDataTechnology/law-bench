# rag-search Specification（delta）

## Purpose

既有 `rag-search` 七需求（MinIO 语料源、OpenRouter 嵌入、ES 向量库、摄取管线、语义检索 API、检索页、CrewAI 检索工具）在新能力 `rag-corpus-service` 域化后，全部保留为 **legal 域实例**的行为；本 delta 仅增可选 `domain` 参数与索引归属声明。

## ADDED Requirements

### Requirement: 域归属与兼容缺省

`/api/search` 与检索页 SHALL 支持可选 `domain` 参数：缺省（缺参）SHALL 解析到 legal 域语料（既有 `SEARCH_INDEX_NAME` 环境变量继续作为 legal 索引名的权威来源，行为逐字兼容）；带参数时行为归 `rag-corpus-service` 域化检索契约。

#### Scenario: 缺参逐字兼容
- **WHEN** 既有调用方不带 `domain` 参数请求 `/api/search`
- **THEN** 响应结构与内容来源与升级前一致（legal 索引），零可观测变化
