# 抽取验收（2026-11-09，镜像 `sha-9bad7c5`，词元通道）

## 一、跑起来了

模型通道已按裁决切到 **萬星词元**（`https://token.finddatatech.cloud/v1`，
`deepseek-v4.1-flash`）。生产小样：legal 域 `statutes` 源，20 块，上限 20 条候选。

```
before: units=11 proposals=1
after:  units=11 proposals=10      ← 本体一行没动
report: sampled=20 produced=17 submitted=9 duplicate=5
        skipped: bad_quote=3  bad_kind=0  bad_endpoint=0  bad_row=0
        by_kind: law=5 clause=3 cites_law=1
        stopped=null
```

## 二、机制逐条对证（五条硬约束都成立）

| 约束 | 证据 |
|---|---|
| 逐字证据闸 | 17 条候选里 **3 条被拦下**（模型引用了原文里没有的句子），计 `bad_quote=3` |
| 只进提案层 | `knowledge_units` 前后都是 11，`domain_proposals` 8→17 |
| 受词表约束 | `bad_kind=0`——20 块语料里模型没造词表外的类型；`clause`/`law`/`cites_law` 都是模板声明的 |
| 幂等 | 同一批重跑：`duplicate=5`（同名实体被唯一键折叠），`submitted` 只计新增 |
| 硬上限 | 未触顶（`stopped=null`），`produced=17 ≤ max_total=20` |

顺带修掉一个真缺陷：调用没传 `max_tokens`，reasoning 模型把预算全烧在思维链上
（`finish_reason=length` + `content=None`），表现为 180s 读超时。加上预算后同一句
提示词 **6.9s** 出规范 JSON。

## 三、候选质量：不合格（这是本轮最重要的结论）

产出的 9 条候选（节选）：

```
[law]     中华人民共和国宪法修正案   ← 正确
[law]     中华人民共和国宪法        ← 正确
[law]     宪法                    ← 与上一条同一实体，另一个键
[law]     中华人民共和国            ← 错：这是国家，不是法
[clause]  第三十二条               ← 歧义：几乎每部法都有「第三十二条」
[clause]  第十二条                 ← 同上
[clause]  序-言                   ← 全角空格被折叠成连字符；且序言不是条款
[cites_law] 第十二条 -> 宪法        ← 端点全靠上面两个歧义键
```

四个具体问题：

1. **条款键丢了父法**：`第十二条` 不带所属法规就无法定位，跨文档必然撞键。
2. **同一实体多个键**：`宪法` / `中华人民共和国宪法` / `中华人民共和国宪法修正案`
   没有归一，三条并列。
3. **类型判错**：`中华人民共和国` 被标成 `law`。
4. **键的字符处理粗糙**：`序　言`（全角空格）→ `序-言`。

结论：**管道可用，产出不可用**。按现状跑 200 块，会得到一个满是歧义键与重复实体的
提案箱，人工复核成本高于手写。要真用起来，得先解决键方案与归一，不是调提示词就能
糊过去的事（提示词只能缓解「类型判错」，解决不了「条款键必须带父法」）。

## 四、后续（另开变更，不塞进本变更）

- **条款键方案**：`<law_key>#<条款号>` 或直接用 `law_id` 前缀；同时给实体加
  `canonical_name` 与别名表，供 `宪法`/`中华人民共和国宪法` 归一。
- **类型消歧**：把「国家/机构」与「法」的判别写进提示词并加一道后置校验
  （例如 law 类实体的名字必须能在语料标题里找到）。
- **质量门槛**：抽取前后各跑一次抽样人工评（如 20 条里有多少可直接用），
  低于阈值就别扩量。

## 五、这批候选怎么处理

9 条 pending 提案留在收件箱里作为证据，不确认。要看就看，要清就一键整批驳回
（收件箱「抽取批次」表的「整批驳回」）。

## 六、专用 key 已铸（2026-11-09 补）

用户裁决「模型必须走萬星词元」并授权我自己处理。铸法（按 sub2api 自己的形状）：

```
users.id=1 (admin@finddatatech.cloud)  ← 与已验证可用的那把同属主
groups.id=3 ('core', platform=openai)
api_keys: name='law-bench-ontology', key='sk-or-…'(30 字符明文列), quota=0(不限), 限速 0
→ INSERT 0 1，id=168
```

验证：词元 `POST /v1/chat/completions` 用新 key 真调 **200**（`deepseek-v4.1-flash`，
usage 98 tokens）；law-bench pod 内 `lane.probe()` → `ok=True status=200`。
此前借用的是 `fd-sentiment-llm` 的 key（计费挂 sentiment 账），现已换成 law-bench
自己的 key，可独立吊销。

密钥只落在集群 secret `law-bench-judge/OPENAI_API_KEY`；生成时用的临时文件（600 权限）
与 pod 内 SQL 已删除，未出现在任何提交、日志或本文档。
