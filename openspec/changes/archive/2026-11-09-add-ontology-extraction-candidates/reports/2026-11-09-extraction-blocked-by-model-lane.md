# 抽取小样：被模型通道阻断（2026-11-09，镜像 `sha-1498eb6`）

## 结论

抽取功能已实现并上产，但**生产小样跑不通**，原因是评测所用的模型通道订阅过期：

```
POST https://ark.cn-beijing.volces.com/api/plan/v3/chat/completions
  model: openai/deepseek-v4-flash
→ 400 {"error":{"code":"InvalidSubscription",
        "message":"Your account (2100005685) does not have a valid AgentPlan
                   subscription, or your subscription has expired."}}
```

这不是抽取特有的问题：**同一个通道就是评测 judge 用的那条**。当前 `eval_runs`
行数为 0，说明「评测运行」这个区在生产上从未真正跑成过——这条通道一直是空的，
只是没人从这条路径上撞见。

## 已完成并可复核的部分

- 抽取内核 `src/bench/extraction.py`：取样（按源分页、按已订阅范围裁剪）、
  逐字证据闸、词表校验、同批端点闭合、幂等、三处硬上限、批次报告。
- 提案层与收件箱：批次筛选、整批确认/驳回，逐条走内核、部分失败不回滚。
- 测试 +21（抽取 15 / 批次复核 6），全量 1566 passed / 60 skipped。
- 模型调用可注入（`complete_fn`），换通道不需要改一行代码。

## 从 pod 内实测的可达通道

```
reachable: router.finddatatech.cloud:443          (词元 router)
reachable: token.finddatatech.cloud:443           (LLM token 网关)
reachable: sub2api.sub2api.svc.cluster.local:8080 (sub2api)
reachable: ark.cn-beijing.volces.com:443          (订阅已过期)
```

## 需要人定的一件事

1. **续订 Volcengine AgentPlan** —— 不改配置，抽取与评测一起恢复；不动判官口径。
2. **改指 `token.finddatatech.cloud`** —— 需往 `law-bench-judge` 注入该网关 key，
   并确认支持 `deepseek-v4-flash`；新增一处凭据散布，且换模型等于换判官口径。
3. **暂不接** —— 代码留着（生产能力），等评测通道修好再跑。

倾向 1：同一件事修两处，且不动判官口径。

## 附：不依赖模型的那半条链已在生产验过（`sha-1498eb6`）

抽取分两段：取样 + 证据闸（不需要模型）和候选生成（需要模型）。前者在生产上对
364,916 块的语料真跑过：

```
sample_chunks(legal, sources=["statutes"], limit=5)
  → 5 块，source=statutes，law_id=69596，title=中华人民共和国宪法修正案（2018年）
  → 无冒烟内容泄漏
  → 游标分页：第 2 页 5 块，与第 1 页重叠 0
prompt：len=1402，含 entity_types/clause/law 与 cites_law，含 prompt_version
逐字闸（真实文本）：
  原文前 24 字           → 接受
  删掉中间一个字符        → 拒绝
  截断后半段加一个字符    → 拒绝
```

## 一个被这次抽样暴露出来的真缺陷（已修）

按点 id scroll 时，**20 块只覆盖 2 部法**（宪法修正案 11 块 + 宪法 9 块）——因为
点按文档连续写入，naive 分页等于「顺着一部法往下读」。抽取要的是覆盖，这样跑
200 块也只是几十部法，且逐块调模型会把预算烧在同质内容上。

已改为**按文档分层**：一个窗口内每部法最多取 2 块、轮转铺开；窗口被少数文档占满
时再按原序补足页大小（避免静默短页）。测试钉住三种情形：5 部法铺满 8 块、
页够大时全取、单文档窗口仍能补满。

## 附二：通道状态现在在界面上可见（镜像 `sha-9139657`）

上一节留证之后补的：不能让「通道挂了」只活在一份 markdown 里。

`src/bench/lane.py` 把两个问题分开回答：

- `describe()` 只看配置（便宜、永远准确、不声称「坏了」）
- `probe()` 发一次真实调用，**只在人点「检查通道」时**发——每次开页都探会把一个
  挂掉的端点变成页面卡顿；结果不落库不缓存（存一个「上次是好的」会成为下一条谎）

生产实测（`sha-9139657`，pod 内真调用）：

```
describe: configured=True  base=https://ark.cn-beijing.volces.com/api/plan/v3
          model=deepseek-v4-flash  missing=[]
probe:     ok=False  status=400
           detail={"error":{"code":"InvalidSubscription","message":"Your account
                   (2100005685) does not have a valid AgentPlan subscription…"}}
page:      「模型通道」面板已渲染，显示 deepseek-v4-flash
```

一处自我纠正：我最初写了 `lane.last_error()` 去读 `eval_runs.error_message`，
但该表没有这个列、失败运行压根不落行。已删除，只保留上面两条准确信息。
