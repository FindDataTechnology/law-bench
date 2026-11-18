"""gov domain pack: 政务公开线。

两件事，互不依赖：

- **键规则**（``entity_keys``）——公文标题怎么归名。导入即注册，所以目录、本体、
  抽取读同一份规则；没有它，同一份公告在三个地方会是三个键。
- **公文爬虫 registry 的确定性事实**（``adapters`` / ``checks``，``kind='gov-fact'``）
  ——只读地对账同级仓 ``fd-cn-gov`` 的源注册表（sources / datasource_columns /
  scraw_configs / organizations），不复制数据、不引 LLM、不联网。

两者都只在本模块被导入时生效：没导入就是「什么都不做」，这是安全默认。
"""

from packs.gov import entity_keys  # noqa: F401  (registration side effect)

__all__ = ["entity_keys"]
