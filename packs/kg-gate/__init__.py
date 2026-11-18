"""kg-gate 域包：KG 车道验收判据（对导入图快照）+ 市场发布门判定内核。

真源只读：``fd-text-core/scripts/kg_graph_checks.py``（四条硬判据的确定性
算法）、``paas/lib/publish-tool-gate.js`` + ``paas/registry-bridge.js`` +
finddata 根仓 ``scripts/export_surface_commercial.py``（发布门判定）。
快照/规则单元见 ``adapters.py``，判读在 ``checks.py``，离线/后置边界与
``packs/gov`` 降级判据的关系在 ``README.md``。
"""
