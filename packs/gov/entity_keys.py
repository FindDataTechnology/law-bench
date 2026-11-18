"""政务公开线的键规则：哪些写法是同一份公文。

内核（``src.bench.keys``）只提供机制——归名、条款寻址、按序应用规则；本模块提供
**这个词表**：哪些前缀是发文主体的称谓而不是标题的一部分。

为什么单独一个文件：不注册就没有归名。``packs.legal`` 的规则只对 ``legal`` 域
生效，政务线若沿用默认（空规则），同一份《自然资源部关于……的公告》在目录里、
在本体里、在抽取结果里会各有一个键——三个键就是三个人。

与法律线不同，政务线的分歧主要不在「法」的前缀，而在**发文主体 vs 标题**：
标题常以机关名开头（「中华人民共和国财政部令第110号--……」），机关名是主体，
不是文档身份的一部分。
"""

from __future__ import annotations

from src.bench.keys import FoldRule, register_rules

#: 主体称谓前缀：去掉后同一份公文只剩标题本体。
PREFIX_RULES: tuple[FoldRule, ...] = (
    FoldRule("drop-prc", "prefix", "中华人民共和国"),
    FoldRule("drop-china", "prefix", "中国"),
)

#: 有序规则表。
RULES: tuple[FoldRule, ...] = PREFIX_RULES

#: 注册在本模块末尾（与 legal 包同一条纪律：规则必须先定义完再交给内核，
#: 否则 pack 导入时 NameError，而错误发生在 import 期最不容易被发现的地方）。
register_rules("gov", RULES)
