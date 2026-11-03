#!/usr/bin/env python3
"""Seed the per-class Chinese contract evaluation rubrics.

Two sets are seeded in one idempotent pass:

1. The 19 《民法典》典型有名合同 (买卖、供用电水气热力、赠与、借款、保证、租赁、
   融资租赁、保理、承揽、建设工程、运输、技术、保管、仓储、委托、物业服务、行纪、
   中介、合伙). Type-specific criteria are drawn from each type's 民法典
   mandatory-clause set.
2. The 22 practical (中国合同分类法 Part 2) contract types that are NOT already
   covered by the 民法典 19 (公司设立、股权转让、增资、并购、股权激励、对赌、股权
   代持、房产买卖、房屋租赁、劳动合同、劳务派遣、知识产权许可、特许经营、房地产
   开发、保险、信托、私募基金、软件开发、影视剧制作、演艺经纪、PPP、旅游). Their
   type-specific criteria are drawn from each type's governing statute beyond 民法典
   (公司法、劳动合同法、保险法、信托法、城市房地产管理法、商业特许经营管理条例、
   旅游法, …). Types that 1:1 duplicate a 民法典 type are intentionally skipped.

Each rubric = the 4 shared base criteria + 4-6 type-specific criteria; all criteria
are written in Chinese (description = the check, guidance = PASS if … / FAIL if …).

Note: 中国合同分类法's D门类 and K类 are NOT seeded - chinese_contracts_class.md
is incomplete (Part 2 cuts off mid-category C; D/K have no details). A future
change can extend the catalog once sourced.

Idempotent: re-running upserts by (name, source='local') and never duplicates.
Harbor rubrics (source LIKE 'harbor:%') and the sample local rubric
(`contract_drafting_v1`) are never touched - upsert matches on source='local' only.

Reuses `upsert_local_rubric` from seed_sample_local_rubric and the schema helpers
from extract_harbor_rules so the schema has one source of truth.

Run:
    uv run python scripts/seed_contract_rubrics.py
"""

from __future__ import annotations

import argparse
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from extract_harbor_rules import DEFAULT_DB, create_schema, print_summary, project_root
from seed_sample_local_rubric import upsert_local_rubric


# 4 shared base criteria - apply to every contract type. Chinese check/guidance.
BASE_CRITERIA: list[dict[str, str]] = [
    {
        "name": "party_identification",
        "description": "是否清晰识别全部合同主体，载明完整法律名称与角色（甲方/乙方）？",
        "guidance": "PASS if 每一方均以完整法律主体名称列明并标注角色；FAIL if 任一主体未列明、表述含糊或仅以代词指代。",
    },
    {
        "name": "governing_law_present",
        "description": "是否明确约定适用法律（如中华人民共和国法律）？",
        "guidance": "PASS if 适用法律条款明确列明管辖法域；FAIL if 缺失或仅作隐含约定。",
    },
    {
        "name": "clause_completeness",
        "description": "是否具备该类合同的必备条款（如违约责任、争议解决、合同期限等）？",
        "guidance": "PASS if 该合同类型标准必备条款齐备；FAIL if 任一必备条款缺失。",
    },
    {
        "name": "legal_citation_accuracy",
        "description": "法条引用是否准确且现行有效（如《民法典》条文序号）？",
        "guidance": "PASS if 所引法律真实存在且条文序号准确；FAIL if 引用系编造、已废止或序号错误。",
    },
]


def _c(name: str, description: str, guidance: str) -> dict[str, str]:
    return {"name": name, "description": description, "guidance": guidance}


def _rubric(type_key: str, description: str, extra: list[dict[str, str]]) -> dict:
    return {
        "name": f"contract_{type_key}_v1",
        "context": "contract",
        "description": description,
        "criteria": BASE_CRITERIA + extra,
    }


def _v2_rubric(v1: dict, citation: str) -> dict:
    """Law-refined v2 variant of a baseline (v1) rubric.

    Same v1 criteria (4 shared base + type-specific) plus one
    ``legal_basis_citation`` criterion whose guidance cites the governing
    statutes/interpretations from the law_info survey. Named
    ``contract_<type>_v2`` so the v1 rubric is untouched.
    """
    legal_basis = _c(
        "legal_basis_citation",
        "是否引用该合同类型现行有效的核心法律法规与司法解释？",
        f"PASS if 引用现行有效的核心法律法规与司法解释（{citation}）；FAIL if 未引用、引用已废止法规或法释文号错误。",
    )
    return {
        "name": v1["name"].replace("_v1", "_v2"),
        "context": v1["context"],
        "description": f"{v1['description']}（法律精修版）",
        "criteria": v1["criteria"] + [legal_basis],
    }


# Per-class rubrics. Two sets: 19 民法典 typical types + 22 practical (中国合同
# 分类法 Part 2, non-overlapping) types. Type-specific criteria from each type's
# governing statute (民法典 for set 1; 公司法/劳动合同法/保险法/… for set 2).
RUBRICS: list[dict] = [
    _rubric("sale", "买卖合同评价规则：标的物所有权转移、风险转移、检验与瑕疵担保。",
        [
            _c("ownership_transfer", "是否约定标的物所有权转移的时点（交付或登记）？",
               "PASS if 所有权转移时点明确（交付时或另有约定）；FAIL if 未约定导致权属不清。"),
            _c("risk_transfer_point", "是否明确标的物毁损灭失风险的转移时点？",
               "PASS if 风险自交付时转移（或约定其他时点）并载明；FAIL if 风险负担约定缺失。"),
            _c("inspection_period", "是否约定检验期间与质量异议期限？",
               "PASS if 检验期间及异议通知方式明确；FAIL if 未约定检验期导致视为合格不明。"),
            _c("defect_warranty", "是否约定质量瑕疵担保责任与救济方式？",
               "PASS if 瑕疵担保责任及修理/更换/退货/减价等救济明确；FAIL if 瑕疵救济缺失。"),
            _c("ownership_retention", "所有权保留条款是否合法且表述清晰（如分期付款）？",
               "PASS if 所有权保留约定清晰且经登记可对抗第三人（如适用）；FAIL if 约定模糊或损害买受人法定权利。"),
        ]),
    _rubric("utilities_supply", "供用电、水、气、热力合同评价规则：中止供应、计量与连续供应义务。",
        [
            _c("suspension_notice", "是否约定中止供应的事由与事先通知义务？",
               "PASS if 中止供应须事先通知并载明合理期限；FAIL if 可任意中止且无通知义务。"),
            _c("metering_and_pricing", "是否明确计量方式、价格与结算周期？",
               "PASS if 计量方法、单价及结算周期清晰；FAIL if 计量或计价约定不明。"),
            _c("continuous_supply", "是否约定连续供应义务与中断赔偿责任？",
               "PASS if 供应人负连续供应义务并约定中断时的责任；FAIL if 连续性义务及责任缺失。"),
        ]),
    _rubric("gift", "赠与合同评价规则：撤销权、交付登记与附义务赠与。",
        [
            _c("arbitrary_revocation", "是否界定赠与人任意撤销权的行使条件与除外情形？",
               "PASS if 任意撤销权条件（交付前、非公证/公益）表述正确；FAIL if 撤销条件违法或缺失。"),
            _c("statutory_revocation", "是否列明法定撤销权的事由（如受赠人侵害赠与人）？",
               "PASS if 法定撤销事由与一年除斥期间载明；FAIL if 法定撤销事由遗漏。"),
            _c("delivery_or_registration", "是否明确赠与物交付或登记的办理安排？",
               "PASS if 需登记的赠与（如不动产）约定登记办理；FAIL if 应登记而未约定登记。"),
            _c("conditional_gift", "附义务赠与是否载明所附义务及其限度？",
               "PASS if 所附义务清晰且不超过赠与财产价值；FAIL if 义务约定不清或显失公平。"),
        ]),
    _rubric("loan", "借款合同评价规则：利率上限、利息支付与借款用途。",
        [
            _c("interest_rate_cap", "利率是否未超过司法保护上限（合同成立时一年期LPR的四倍）？",
               "PASS if 约定利率≤LPR四倍；FAIL if 超过司法保护上限（高利贷风险）。"),
            _c("interest_payment", "是否明确利息支付方式与周期？",
               "PASS if 利率、付息周期与方式清晰；FAIL if 利息支付约定不明。"),
            _c("early_repayment", "是否约定提前还款的条件与利息计算？",
               "PASS if 提前还款的通知与利息处理明确；FAIL if 提前还款规则缺失。"),
            _c("loan_purpose", "是否约定借款用途及挪用后果？",
               "PASS if 借款用途明确并约定违约后果；FAIL if 用途不明或无挪用约束。"),
        ]),
    _rubric("guarantee", "保证合同评价规则：保证方式、期间、范围与主合同变更。",
        [
            _c("guarantee_type", "是否明确保证方式（一般保证或连带责任保证）？",
               "PASS if 保证方式明确约定（未约定推定一般保证）；FAIL if 方式不清导致争议。"),
            _c("guarantee_period", "是否约定保证期间及其起算？",
               "PASS if 保证期间长度与起算时点明确；FAIL if 保证期间缺失（视为法定）。"),
            _c("guarantee_scope", "是否明确保证范围（主债权、利息、违约金、损害赔偿、实现债权费用）？",
               "PASS if 保证范围列明完整；FAIL if 范围约定不全。"),
            _c("master_contract_change", "是否约定主合同变更对保证责任的影响？",
               "PASS if 主合同变更须经保证人同意及后果载明；FAIL if 变更影响未约定。"),
        ]),
    _rubric("lease", "租赁合同评价规则：租期上限、租金、优先承租权与维修义务。",
        [
            _c("lease_term_cap", "租赁期限是否≤20年（超过部分无效）？",
               "PASS if 约定租期≤20年；FAIL if 约定超过20年（超过部分无效）。"),
            _c("rent_and_payment", "是否明确租金数额、支付方式与周期？",
               "PASS if 租金、付租周期与支付方式清晰；FAIL if 租金或支付约定不明。"),
            _c("priority_renewal", "是否约定承租人优先承租权（同等条件下）？",
               "PASS if 期满续租的优先权及条件载明；FAIL if 优先承租权缺失。"),
            _c("maintenance_duty", "是否明确维修义务的承担方？",
               "PASS if 维修义务归属明确（原则上出租人）；FAIL if 维修责任约定不明。"),
            _c("subletting_restriction", "是否约定转租的限制与同意要件？",
               "PASS if 转租须经出租人同意及后果载明；FAIL if 转租规则缺失。"),
        ]),
    _rubric("financing_lease", "融资租赁合同评价规则：所有权登记、租金构成与期满归属。",
        [
            _c("ownership_and_registration", "是否明确租赁物所有权归属与登记安排？",
               "PASS if 所有权归出租人并约定登记（对抗第三人）；FAIL if 权属或登记约定不清。"),
            _c("rent_composition", "是否明确租金构成（含购买成本与利润）及支付？",
               "PASS if 租金构成与支付周期清晰；FAIL if 租金构成不明。"),
            _c("defect_and_maintenance", "是否约定租赁物瑕疵与维修责任的承担？",
               "PASS if 瑕疵担保与维修责任归属明确（多由承租人负担）；FAIL if 责任约定不明。"),
            _c("end_of_term_ownership", "是否约定期满租赁物的归属？",
               "PASS if 期满归属（留购/续租/返还）明确；FAIL if 期满归属未约定。"),
        ]),
    _rubric("factoring", "保理合同评价规则：应收账款转让通知、追索权与回购。",
        [
            _c("assignment_notice", "是否约定应收账款转让通知债务人的安排？",
               "PASS if 转让通知主体与方式明确；FAIL if 通知安排缺失（对债务人不生效）。"),
            _c("recourse_type", "是否明确有追索权或无追索权保理类型？",
               "PASS if 追索权类型清晰界定；FAIL if 追索权约定不明。"),
            _c("receivables_description", "应收账款的描述是否清晰可识别？",
               "PASS if 应收账款金额、基础交易与债务人列明；FAIL if 标的应收账款描述不清。"),
            _c("buyback_or_retransfer", "是否约定回购或反转让的情形与对价？",
               "PASS if 回购/反转让触发情形与对价明确；FAIL if 回购安排缺失。"),
        ]),
    _rubric("work", "承揽合同评价规则：成果交付验收、材料提供与留置权。",
        [
            _c("delivery_and_acceptance", "是否约定工作成果的交付与验收标准？",
               "PASS if 交付时间、地点与验收标准/期限明确；FAIL if 验收约定缺失。"),
            _c("materials_and_risk", "是否明确材料提供方与毁损风险负担？",
               "PASS if 材料（承揽人/定作人提供）及风险归属载明；FAIL if 材料与风险约定不明。"),
            _c("instructions_and_assistance", "是否约定定作人的指示与协助义务？",
               "PASS if 定作人指示变更与协助义务载明；FAIL if 协助义务缺失。"),
            _c("lien_right", "是否约定承揽人对工作成果的留置权？",
               "PASS if 报酬未付时的留置权及实现方式载明；FAIL if 留置权约定缺失。"),
        ]),
    _rubric("construction", "建设工程合同评价规则：工程范围、竣工验收、结算与保修。",
        [
            _c("scope_and_schedule", "是否明确工程范围与工期？",
               "PASS if 工程范围、工期及延期责任明确；FAIL if 范围或工期约定不明。"),
            _c("completion_acceptance", "是否约定竣工验收程序与标准？",
               "PASS if 竣工验收标准、程序与期限载明；FAIL if 验收约定缺失。"),
            _c("payment_and_settlement", "是否约定工程款支付节点与结算方式？",
               "PASS if 预付/进度/结算款节点与结算方式清晰；FAIL if 付款节点不明。"),
            _c("quality_warranty", "是否约定质量保修范围与保修期？",
               "PASS if 保修范围、保修期与责任载明；FAIL if 保修条款缺失。"),
            _c("priority_of_payment", "是否提示承包人工程价款优先受偿权？",
               "PASS if 优先受偿权及行使期限（合理期限）载明；FAIL if 优先权约定缺失。"),
        ]),
    _rubric("transport", "运输合同评价规则：运输标的、运到期限与赔偿免责。",
        [
            _c("subject_and_deadline", "是否明确运输标的与运到期限？",
               "PASS if 货物/旅客描述与运到期限明确；FAIL if 标的或期限约定不明。"),
            _c("ticket_or_waybill", "是否约定客票/托运单等运输凭证？",
               "PASS if 运输凭证的出具与效力载明；FAIL if 凭证约定缺失。"),
            _c("loss_or_damage_compensation", "是否约定货物灭失毁损的赔偿标准？",
               "PASS if 赔偿限额/计算方式与归责原则载明；FAIL if 赔偿约定不明。"),
            _c("exemptions", "是否列明承运人免责事由？",
               "PASS if 法定免责事由（不可抗力、货物自身性质等）载明；FAIL if 免责事由缺失。"),
        ]),
    _rubric("technology", "技术合同评价规则：成果权属、保密、后续改进与风险分担。",
        [
            _c("result_ownership", "是否明确技术成果的权属归属？",
               "PASS if 技术成果权属（专利申请权/所有权）明确；FAIL if 权属约定不明。"),
            _c("confidentiality", "是否约定保密义务与期限？",
               "PASS if 保密范围、期限与违约责任载明；FAIL if 保密条款缺失。"),
            _c("subsequent_improvement", "是否约定后续改进成果的归属与分享？",
               "PASS if 后续改进的权属与分享方式明确；FAIL if 改进归属未约定。"),
            _c("development_risk", "技术开发是否约定风险分担？",
               "PASS if 开发失败风险的分担与通知义务载明；FAIL if 风险分担缺失（技术开发合同）。"),
            _c("price_or_royalty", "是否明确价款或使用费及支付方式？",
               "PASS if 价款/使用费数额与支付方式清晰；FAIL if 报酬约定不明。"),
        ]),
    _rubric("bailment", "保管合同评价规则：保管物交付返还、期间与赔偿责任。",
        [
            _c("delivery_and_return", "是否约定保管物的交付与返还？",
               "PASS if 交付、返还时点与状态明确；FAIL if 交付返还约定不明。"),
            _c("custody_period", "是否约定保管期间？",
               "PASS if 保管期间及起止明确；FAIL if 期间约定不明。"),
            _c("liability_paid_vs_free", "是否有偿保管是否明确赔偿责任标准？",
               "PASS if 有偿/无偿保管的责任轻重区分并载明；FAIL if 赔偿责任标准缺失。"),
            _c("danger_notice", "是否约定危险保管物的告知义务？",
               "PASS if 危险保管物（易燃易爆等）的告知义务载明；FAIL if 危险告知缺失。"),
        ]),
    _rubric("warehousing", "仓储合同评价规则：仓单、储存期间与赔偿限额。",
        [
            _c("warehouse_receipt", "是否约定仓单的签发与记载事项？",
               "PASS if 仓单签发及必要记载事项载明；FAIL if 仓单约定缺失。"),
            _c("storage_period", "是否明确储存期间？",
               "PASS if 储存期间及起止明确；FAIL if 储存期间约定不明。"),
            _c("extraction_and_inspection", "是否约定提取与验收安排？",
               "PASS if 入库验收与出库提取的程序载明；FAIL if 验收提取约定缺失。"),
            _c("dangerous_goods_notice", "是否约定危险物品的告知与处理？",
               "PASS if 危险物品告知义务及处置载明；FAIL if 危险品告知缺失。"),
            _c("compensation_limit", "是否约定赔偿范围与限额？",
               "PASS if 损害赔偿计算与限额明确；FAIL if 赔偿约定不明。"),
        ]),
    _rubric("entrustment", "委托合同评价规则：事务权限、转委托、报告与任意解除。",
        [
            _c("affairs_and_authority", "是否明确委托事务范围与权限？",
               "PASS if 委托事务范围与代理权限清晰；FAIL if 事务或权限约定不明。"),
            _c("sub_entrustment", "是否约定转委托的条件？",
               "PASS if 转委托须经同意及责任承担载明；FAIL if 转委托规则缺失。"),
            _c("reporting_duty", "是否约定受托人的报告义务？",
               "PASS if 报告进度与结果的义务载明；FAIL if 报告义务缺失。"),
            _c("expenses_and_remuneration", "是否明确费用与报酬？",
               "PASS if 费用预付/垫付与报酬及支付方式清晰；FAIL if 费用报酬约定不明。"),
            _c("arbitrary_termination", "是否提示委托人或受托人的任意解除权？",
               "PASS if 任意解除权及赔偿后果载明；FAIL if 解除权约定缺失。"),
        ]),
    _rubric("property_service", "物业服务合同评价规则：服务标准、收费、解聘与交接。",
        [
            _c("service_scope_and_standard", "是否明确服务内容与标准？",
               "PASS if 服务事项、标准与质量要求载明；FAIL if 服务标准约定不明。"),
            _c("fees", "是否约定收费项目、标准与收缴方式？",
               "PASS if 物业费项目、标准与收缴方式清晰；FAIL if 收费约定不明。"),
            _c("owner_termination_right", "是否提示业主的解聘权与程序？",
               "PASS if 业主解聘程序与提前通知期限载明；FAIL if 解聘权约定缺失。"),
            _c("handover", "是否约定服务终止时的交接义务？",
               "PASS if 资料、财物交接义务与期限载明；FAIL if 交接约定缺失。"),
            _c("special_repair_fund", "是否涉及专项维修资金的筹集与使用？",
               "PASS if 专项维修资金使用范围与程序载明（如适用）；FAIL if 应约定而未约定。"),
        ]),
    _rubric("brokerage", "行纪合同评价规则：自有名义、价格差额与买受出卖义务。",
        [
            _c("own_name_trade", "是否明确行纪人以自己名义从事贸易？",
               "PASS if 行纪人自有名义交易及法律后果载明；FAIL if 名义约定不明。"),
            _c("price_difference", "是否约定低于指定价格卖出或高于指定价格买入的差额补偿？",
               "PASS if 价格差额的补偿或利益归属载明；FAIL if 差额规则缺失。"),
            _c("buy_or_sell_obligation", "是否约定行纪人买受/出卖义务的触发情形？",
               "PASS if 行纪人自买自卖的情形与价格条件载明；FAIL if 买受出卖规则缺失。"),
            _c("remuneration", "是否明确报酬及支付条件？",
               "PASS if 报酬数额与支付条件清晰；FAIL if 报酬约定不明。"),
        ]),
    _rubric("intermediation", "中介合同评价规则：报告媒介义务、如实报告与报酬条件。",
        [
            _c("report_or_intermediation_duty", "是否明确报告订约机会或媒介服务的义务？",
               "PASS if 报告/媒介服务内容明确；FAIL if 服务义务约定不明。"),
            _c("truthful_report", "是否约定如实报告义务？",
               "PASS if 如实报告重要事项及隐瞒责任载明；FAIL if 如实报告义务缺失。"),
            _c("remuneration_condition", "是否明确报酬支付条件（促成合同成立）？",
               "PASS if 报酬以促成合同成立为条件并载明；FAIL if 报酬条件约定不明。"),
            _c("expense_bearing", "是否约定中介活动费用的承担？",
               "PASS if 中介费用承担方明确（未促成时）；FAIL if 费用承担约定缺失。"),
        ]),
    _rubric("partnership", "合伙合同评价规则：出资、利润亏损分担与解散清算。",
        [
            _c("capital_contribution", "是否明确合伙人的出资方式与数额？",
               "PASS if 出资方式（货币/实物/劳务等）与数额载明；FAIL if 出资约定不明。"),
            _c("profit_and_loss_sharing", "是否约定利润分配与亏损分担比例？",
               "PASS if 利润分配与亏损分担比例明确；FAIL if 分配比例约定不明。"),
            _c("partnership_affairs", "是否约定合伙事务的执行与决策？",
               "PASS if 事务执行人及表决/决策规则载明；FAIL if 事务执行约定不明。"),
            _c("admission_and_withdrawal", "是否约定入伙与退伙的条件？",
               "PASS if 入伙同意条件与退伙结算方式载明；FAIL if 入伙退伙规则缺失。"),
            _c("dissolution_and_liquidation", "是否约定解散事由与清算方式？",
               "PASS if 解散事由与清算程序载明；FAIL if 清算约定缺失。"),
        ]),

    # --- 中国合同分类法 Part 2 (practical, non-overlapping) ----------------- #

    _rubric("company_formation", "公司设立合同评价规则：出资、章程、设立责任与登记。",
        [
            _c("capital_contribution", "是否明确股东出资方式、数额与实缴期限？",
               "PASS if 出资方式（货币/非货币）与各股东认缴数额及实缴期限载明；FAIL if 出资约定不明或非货币出资未评估。"),
            _c("articles_of_association", "是否约定公司章程的制定与必备条款？",
               "PASS if 章程制定安排及组织机构、表决规则等必备条款载明；FAIL if 章程条款缺失。"),
            _c("pre_incorporation_liability", "是否约定设立中公司的费用与债务承担？",
               "PASS if 设立费用与债务的承担主体及责任载明；FAIL if 设立责任约定不明。"),
            _c("registration", "是否约定公司登记办理义务与违约后果？",
               "PASS if 登记办理方、期限及逾期后果载明；FAIL if 登记义务缺失。"),
        ]),
    _rubric("equity_transfer", "股权转让合同评价规则：优先购买权、变更登记与瑕疵担保。",
        [
            _c("preemptive_right", "是否处理其他股东的优先购买权？",
               "PASS if 其他股东放弃优先购买权或依法通知的安排载明；FAIL if 优先购买权未处理（转让存在效力风险）。"),
            _c("transfer_price_and_payment", "是否明确转让价款与支付方式？",
               "PASS if 转让对价、支付节点与方式清晰；FAIL if 对价约定不明。"),
            _c("registration_change", "是否约定工商变更登记的办理？",
               "PASS if 变更登记办理方与期限载明；FAIL if 变更登记约定缺失。"),
            _c("equity_defect_warranty", "是否约定转让股权的权属瑕疵担保？",
               "PASS if 出让方对权属完整、无质押/冻结的担保载明；FAIL if 瑕疵担保缺失。"),
            _c("consent_procedure", "是否约定公司及其他股东同意的程序？",
               "PASS if 同意程序与文件载明；FAIL if 同意程序缺失。"),
        ]),
    _rubric("capital_increase", "增资扩股协议评价规则：优先认缴、估值、变更登记与股东权利。",
        [
            _c("preemptive_subscription", "是否处理原股东优先认缴出资权？",
               "PASS if 原股东优先认缴权的行使与放弃安排载明；FAIL if 优先认缴权未处理。"),
            _c("valuation_and_amount", "是否明确增资估值、认购价款与溢价处理？",
               "PASS if 增资后估值、认购价款及计入注册资本与资本公积的比例载明；FAIL if 估值或价款约定不明。"),
            _c("registration_change", "是否约定注册资本变更登记与章程修订？",
               "PASS if 变更登记与章程修订安排载明；FAIL if 变更登记缺失。"),
            _c("shareholder_rights", "是否约定新股东权利与公司治理安排？",
               "PASS if 新股东表决权、分红权及董事会席位等载明；FAIL if 股东权利约定不明。"),
            _c("conditions_precedent", "是否约定交割先决条件与交割安排？",
               "PASS if 交割先决条件与交割时点载明；FAIL if 交割条件缺失。"),
        ]),
    _rubric("merger_acquisition", "公司并购协议评价规则：交易对价、交割、过渡期与申报。",
        [
            _c("transaction_structure", "是否明确交易结构（股权/资产收购）与标的范围？",
               "PASS if 交易结构与标的范围清晰；FAIL if 交易结构约定不明。"),
            _c("purchase_price_and_adjustment", "是否约定对价、支付方式与对价调整机制？",
               "PASS if 对价、支付节点及对价调整（如交割审计）载明；FAIL if 对价机制不明。"),
            _c("conditions_precedent_and_closing", "是否约定交割先决条件与交割安排？",
               "PASS if 交割先决条件、交割日与交割义务载明；FAIL if 交割条件缺失。"),
            _c("transition_period", "是否约定过渡期义务与竞业限制？",
               "PASS if 过渡期经营约束与竞业限制载明；FAIL if 过渡期义务缺失。"),
            _c("regulatory_filing", "是否涉及反垄断/经营者集中申报等审批安排？",
               "PASS if 适用时申报义务与责任分配载明；FAIL if 应申报而未约定。"),
            _c("representations_and_warranties", "是否约定陈述与保证及赔偿？",
               "PASS if 陈述保证与违约赔偿安排载明；FAIL if 陈述保证缺失。"),
        ]),
    _rubric("equity_incentive", "股权激励协议评价规则：授予、成熟、行权与回购。",
        [
            _c("grant_subject_and_amount", "是否明确激励标的与授予数量？",
               "PASS if 激励股权/期权数量及来源载明；FAIL if 激励标的约定不明。"),
            _c("vesting_schedule", "是否约定成熟期与成熟条件？",
               "PASS if 成熟期、成熟比例与条件载明；FAIL if 成熟安排缺失。"),
            _c("exercise_price_and_window", "是否约定行权价格与行权窗口？",
               "PASS if 行权价格、窗口期与方式载明；FAIL if 行权规则缺失。"),
            _c("buyback_and_forfeiture", "是否约定回购与丧失情形？",
               "PASS if 离职/违约等情形下的回购价格与丧失条件载明；FAIL if 回购安排缺失。"),
            _c("non_compete_and_confidentiality", "是否约定竞业限制与保密义务？",
               "PASS if 激励对象的竞业限制与保密义务载明；FAIL if 竞业保密缺失。"),
        ]),
    _rubric("vam_agreement", "估值调整（对赌）协议评价规则：业绩/上市对赌、补偿、回购与效力。",
        [
            _c("performance_targets", "是否明确业绩承诺指标与计算口径？",
               "PASS if 业绩指标、计算方式与审计安排载明；FAIL if 业绩目标约定不明。"),
            _c("compensation_mechanism", "是否约定未达标时的补偿方式？",
               "PASS if 股权/现金补偿的计算与方式载明；FAIL if 补偿机制缺失。"),
            _c("buyback_obligation", "是否约定回购触发情形与回购价格？",
               "PASS if 回购情形（如未上市）与回购价格计算载明；FAIL if 回购安排缺失。"),
            _c("counterparty_and_validity", "是否注意对赌相对方（股东vs公司）对效力的影响？",
               "PASS if 对赌相对方及对公司履行的效力风险有提示；FAIL if 未区分对赌相对方。"),
            _c("adjustment_mechanism", "是否约定估值调整的机制与顺序？",
               "PASS if 调整顺序与方式载明；FAIL if 调整机制约定不明。"),
        ]),
    _rubric("equity_holding_in_trust", "股权代持协议评价规则：代持关系、实际出资人、显名与风险。",
        [
            _c("nominee_relationship", "是否明确代持关系与双方权利义务？",
               "PASS if 代持关系、实际出资人（隐名）与名义股东的权利义务载明；FAIL if 代持关系约定不明。"),
            _c("actual_contributor", "是否明确实际出资与出资归属？",
               "PASS if 出资由实际出资人提供及归属载明；FAIL if 出资归属不明。"),
            _c("beneficial_rights", "是否约定分红、表决等实际权利的行使？",
               "PASS if 分红、表决等权利由实际出资人享有的安排载明；FAIL if 权利归属约定不明。"),
            _c("transfer_to_name", "是否约定显名（变更登记）的条件与费用？",
               "PASS if 显名登记的条件、费用与协助义务载明；FAIL if 显名安排缺失。"),
            _c("risk_disclosure", "是否提示代持对第三人的效力风险？",
               "PASS if 名义股东处分/强制执行等风险有提示；FAIL if 风险提示缺失。"),
        ]),
    _rubric("real_estate_sale", "房产买卖合同评价规则：产权登记、预售许可、面积差异与过户。",
        [
            _c("property_description", "是否明确标的房产坐落、面积与权属状况？",
               "PASS if 房产位置、面积、权属及是否设定他项权利载明；FAIL if 标的描述不明。"),
            _c("pre_sale_permit", "是否涉及商品房预售许可？",
               "PASS if 预售商品房时预售许可证号载明；FAIL if 应载明预售许可而缺失（合同效力风险）。"),
            _c("price_and_payment", "是否明确价款、付款方式与节点？",
               "PASS if 房款、付款节点与方式清晰；FAIL if 价款约定不明。"),
            _c("area_discrepancy", "是否约定面积差异处理方式？",
               "PASS if 面积误差处理（退补/解除）载明；FAIL if 面积差异规则缺失。"),
            _c("transfer_registration", "是否约定过户登记办理与税费承担？",
               "PASS if 过户登记办理方、期限与税费分担载明；FAIL if 过户约定缺失。"),
            _c("delivery_standard", "是否约定交付标准与时间？",
               "PASS if 交付标准、时间及逾期责任载明；FAIL if 交付约定不明。"),
        ]),
    _rubric("real_estate_lease", "房屋租赁合同评价规则：登记备案、买卖不破租赁与优先承租。",
        [
            _c("premises_and_use", "是否明确租赁房屋与用途？",
               "PASS if 房屋坐落、面积与约定用途载明；FAIL if 标的或用途不明。"),
            _c("record_filing", "是否约定租赁登记备案？",
               "PASS if 登记备案安排载明（虽不当然影响效力）；FAIL if 备案约定缺失。"),
            _c("sale_breaks_lease", "是否提示买卖不破租赁？",
               "PASS if 租赁期内房屋转让时承租人继续承租的权利载明；FAIL if 未提示买卖不破租赁。"),
            _c("preemption_and_renewal", "是否约定承租人优先购买权与优先承租权？",
               "PASS if 优先购买权与期满优先承租权载明；FAIL if 优先权缺失。"),
            _c("maintenance_and_modification", "是否约定维修义务与改造限制？",
               "PASS if 维修责任与承租人改造的限制载明；FAIL if 维修改造约定不明。"),
            _c("term_and_deposit", "是否明确租期、租金与押金？",
               "PASS if 租期、租金、押金及退还条件载明；FAIL if 期限租金约定不明。"),
        ]),
    _rubric("employment", "劳动合同评价规则：期限、试用期、工时、解除与经济补偿。",
        [
            _c("term_and_probation", "是否约定合同期限与试用期？",
               "PASS if 期限类型（固定/无固定/以任务）与试用期及长度（不超法定上限）载明；FAIL if 试用期违法或缺失。"),
            _c("position_and_workplace", "是否明确工作岗位、地点与职责？",
               "PASS if 岗位、地点与职责载明；FAIL if 工作内容约定不明。"),
            _c("compensation_and_hours", "是否约定工资、工时与社保？",
               "PASS if 工资标准、工时制度与社保缴纳载明；FAIL if 报酬或社保约定缺失。"),
            _c("termination_grounds", "是否约定解除条件与程序？",
               "PASS if 解除情形与通知程序载明（符合法定解除条件）；FAIL if 解除约定违法或缺失。"),
            _c("severance", "是否提示经济补偿与代通知金？",
               "PASS if 法定经济补偿与代通知金情形载明；FAIL if 经济补偿未提示。"),
            _c("confidentiality_and_non_compete", "是否约定保密与竞业限制？",
               "PASS if 保密义务与竞业限制（含补偿）载明；FAIL if 竞业限制未约定补偿。"),
        ]),
    _rubric("labor_dispatch", "劳务派遣合同评价规则：派遣资质、三性岗位、同工同酬与连带责任。",
        [
            _c("dispatch_qualification", "是否确认派遣单位具备法定资质？",
               "PASS if 派遣单位行政许可资质载明；FAIL if 派遣资质缺失（效力风险）。"),
            _c("three_nature_positions", "是否约定岗位符合临时性/辅助性/替代性？",
               "PASS if 岗位的三性属性载明；FAIL if 未确认岗位性质。"),
            _c("equal_pay", "是否约定同工同酬？",
               "PASS if 同工同酬及薪酬标准载明；FAIL if 同工同酬约定缺失。"),
            _c("tripartite_relationship", "是否明确三方关系与用工单位退回条件？",
               "PASS if 派遣单位、用工单位与劳动者三方权利义务及退回条件载明；FAIL if 三方关系约定不明。"),
            _c("joint_liability", "是否提示用工单位的连带责任？",
               "PASS if 用工单位给劳动者造成损害时的连带责任载明；FAIL if 连带责任未提示。"),
            _c("term_cap", "是否约定派遣期限符合法定比例？",
               "PASS if 派遣期限不超过用工总量法定比例载明；FAIL if 比例约束缺失。"),
        ]),
    _rubric("ip_license", "知识产权许可合同评价规则：许可范围、排他性、费用与质量监督。",
        [
            _c("licensed_subject", "是否明确许可标的与权属？",
               "PASS if 许可的知识产权标的、权属及有效状态载明；FAIL if 标的或权属不明。"),
            _c("scope_and_exclusivity", "是否约定许可范围与排他性？",
               "PASS if 许可地域、期限、方式与独占/排他/普通许可类型载明；FAIL if 许可范围约定不明。"),
            _c("license_fee", "是否约定许可费用与支付方式？",
               "PASS if 许可费、计算方式与支付节点载明；FAIL if 费用约定不明。"),
            _c("quality_control", "是否约定质量监督与维持义务？",
               "PASS if 许可人对质量监督及许可方维持权利有效的义务载明；FAIL if 质量监督缺失。"),
            _c("improvement_and_grantback", "是否约定后续改进的归属与回授？",
               "PASS if 改进成果归属与回授安排载明；FAIL if 改进归属未约定。"),
            _c("termination_and_reversion", "是否约定终止后停止使用与返还？",
               "PASS if 终止后停止使用及资料返还载明；FAIL if 终止后安排缺失。"),
        ]),
    _rubric("franchise", "特许经营（加盟）合同评价规则：备案、冷静期、信息披露与区域保护。",
        [
            _c("franchisor_qualification", "是否确认特许人具备两店一年等资质？",
               "PASS if 特许人经营资源与两店一年资质载明；FAIL if 特许人资质缺失。"),
            _c("record_filing", "是否约定特许经营备案？",
               "PASS if 备案安排载明；FAIL if 备案约定缺失。"),
            _c("information_disclosure", "是否约定信息披露义务？",
               "PASS if 特许人信息披露的内容与时间载明；FAIL if 信息披露缺失。"),
            _c("cooling_off_period", "是否约定被特许人单方解除的冷静期？",
               "PASS if 冷静期及单方解除权载明；FAIL if 冷静期缺失。"),
            _c("territory_protection", "是否约定区域保护与竞业限制？",
               "PASS if 区域保护范围与竞业限制载明；FAIL if 区域保护约定不明。"),
            _c("fees_and_duration", "是否明确特许费、期限与续展？",
               "PASS if 特许经营费、期限（不少于法定下限）与续展条件载明；FAIL if 费用期限约定不明。"),
        ]),
    _rubric("real_estate_development", "房地产开发合同评价规则：土地取得、规划、建设与竣工验收。",
        [
            _c("land_acquisition", "是否明确土地取得方式与权属？",
               "PASS if 土地出让/转让方式与权属载明；FAIL if 土地取得约定不明。"),
            _c("planning_requirements", "是否约定规划条件与用途？",
               "PASS if 规划条件、用途及变更约定载明；FAIL if 规划约定缺失。"),
            _c("construction_obligations", "是否约定建设标准、工期与质量？",
               "PASS if 建设标准、工期与质量责任载明；FAIL if 建设义务约定不明。"),
            _c("completion_acceptance", "是否约定竣工验收与交付？",
               "PASS if 竣工验收标准与交付安排载明；FAIL if 验收交付缺失。"),
            _c("cost_and_payment", "是否明确开发成本与支付节点？",
               "PASS if 成本分担与支付节点载明；FAIL if 成本约定不明。"),
            _c("risk_allocation", "是否约定开发风险与不可抗力分担？",
               "PASS if 风险负担与不可抗力安排载明；FAIL if 风险分担缺失。"),
        ]),
    _rubric("insurance", "保险合同评价规则：如实告知、保险责任、免责与理赔。",
        [
            _c("insured_subject", "是否明确保险标的/被保险人？",
               "PASS if 保险标的或被保险人载明；FAIL if 标的约定不明。"),
            _c("disclosure_duty", "是否约定投保人如实告知义务？",
               "PASS if 如实告知义务及未尽后果载明；FAIL if 告知义务缺失。"),
            _c("coverage_and_liability", "是否明确保险责任范围与起止？",
               "PASS if 保险责任、责任起止时间载明；FAIL if 责任范围不明。"),
            _c("exclusions", "是否明确免责条款并作提示说明？",
               "PASS if 免责条款载明并尽提示说明义务；FAIL if 免责条款未提示（效力风险）。"),
            _c("premium_and_sum_insured", "是否约定保险费与保险金额？",
               "PASS if 保险费、保险金额载明；FAIL if 费率保额约定不明。"),
            _c("claims_process", "是否约定理赔程序与时效？",
               "PASS if 出险通知、理赔程序与时限载明；FAIL if 理赔约定缺失。"),
        ]),
    _rubric("trust", "信托合同评价规则：信托财产独立、受托人义务与终止清算。",
        [
            _c("trust_property", "是否明确信托财产的范围与交付？",
               "PASS if 信托财产范围、交付方式载明；FAIL if 信托财产约定不明。"),
            _c("property_independence", "是否提示信托财产独立于受托人固有财产？",
               "PASS if 信托财产独立性载明；FAIL if 独立性未提示。"),
            _c("beneficiary", "是否明确受益人与受益权？",
               "PASS if 受益人范围、受益权及变更安排载明；FAIL if 受益人约定不明。"),
            _c("fiduciary_duties", "是否约定受托人义务与报酬？",
               "PASS if 受托人管理义务、报酬及费用载明；FAIL if 受托人义务约定不明。"),
            _c("termination_and_distribution", "是否约定信托终止与清算分配？",
               "PASS if 终止情形与清算后财产归属载明；FAIL if 终止清算缺失。"),
            _c("purpose_and_duration", "是否明确信托目的与期限？",
               "PASS if 信托目的、期限载明；FAIL if 目的期限约定不明。"),
        ]),
    _rubric("private_equity_fund", "私募基金合同评价规则：募集、管理、托管、退出与合格投资者。",
        [
            _c("qualified_investor", "是否确认投资者符合合格投资者要求？",
               "PASS if 合格投资者认定安排载明；FAIL if 合格投资者认定缺失。"),
            _c("fund_structure", "是否明确基金类型与组织形式？",
               "PASS if 基金类型（公司/合伙/契约）与组织形式载明；FAIL if 基金结构约定不明。"),
            _c("management_and_custody", "是否约定管理人与托管人职责？",
               "PASS if 管理人管理职责与托管人托管职责载明；FAIL if 管理/托管职责不明。"),
            _c("investment_scope", "是否约定投资范围与限制？",
               "PASS if 投资范围、策略与限制载明；FAIL if 投资范围约定不明。"),
            _c("fees_and_terms", "是否明确管理费、收益分配与存续期？",
               "PASS if 管理费、业绩报酬、收益分配与存续期载明；FAIL if 费用分配约定不明。"),
            _c("exit_and_liquidation", "是否约定退出与清算安排？",
               "PASS if 退出方式与清算分配安排载明；FAIL if 退出清算缺失。"),
        ]),
    _rubric("software_development", "软件开发合同评价规则：交付验收、知识产权归属与维护。",
        [
            _c("development_scope", "是否明确开发范围、需求与里程碑？",
               "PASS if 开发范围、需求规格与里程碑载明；FAIL if 需求约定不明。"),
            _c("delivery_and_acceptance", "是否约定交付与验收标准？",
               "PASS if 交付物、验收标准与期限载明；FAIL if 验收约定缺失。"),
            _c("ip_ownership", "是否约定成果知识产权归属？",
               "PASS if 软件著作权归属与许可安排载明；FAIL if 权属约定不明。"),
            _c("payment_and_milestone", "是否约定价款与里程碑支付？",
               "PASS if 价款、支付节点与方式载明；FAIL if 价款约定不明。"),
            _c("warranty_and_maintenance", "是否约定质量保证与维护服务？",
               "PASS if 质保期与维护服务安排载明；FAIL if 维护约定缺失。"),
            _c("change_management", "是否约定需求变更管理？",
               "PASS if 变更程序与费用调整载明；FAIL if 变更管理缺失。"),
        ]),
    _rubric("film_production", "影视剧合作制作合同评价规则：投资、署名、发行与收益分配。",
        [
            _c("investment_and_sharing", "是否明确投资份额与权利比例？",
               "PASS if 各方投资额与权利份额载明；FAIL if 投资份额约定不明。"),
            _c("production_obligations", "是否约定制作职责与周期？",
               "PASS if 制作分工、周期与质量载明；FAIL if 制作义务约定不明。"),
            _c("credits_and_ownership", "是否约定署名权与著作权归属？",
               "PASS if 署名安排与著作权归属载明；FAIL if 署名权属约定不明。"),
            _c("distribution_and_license", "是否约定发行与许可安排？",
               "PASS if 发行方、发行范围与许可方式载明；FAIL if 发行约定缺失。"),
            _c("revenue_allocation", "是否约定收益分配与结算？",
               "PASS if 收益分配比例、计算与结算周期载明；FAIL if 收益分配约定不明。"),
            _c("censorship_compliance", "是否约定审查合规责任？",
               "PASS if 内容审查与合规责任载明；FAIL if 审查合规缺失。"),
        ]),
    _rubric("talent_agency", "演艺经纪合同评价规则：经纪范围、分成、期限与解约。",
        [
            _c("agency_scope", "是否明确经纪事务范围？",
               "PASS if 经纪事务（演出/代言/宣传等）范围载明；FAIL if 经纪范围约定不明。"),
            _c("commission_and_sharing", "是否约定分成比例与结算？",
               "PASS if 分成比例、计算与结算周期载明；FAIL if 分成约定不明。"),
            _c("term_and_exclusivity", "是否约定经纪期限与独家性？",
               "PASS if 经纪期限与独家/非独家约定载明；FAIL if 期限独家约定不明。"),
            _c("rights_and_obligations", "是否约定双方权利义务与宣传投入？",
               "PASS if 经纪人投入与艺人配合义务载明；FAIL if 权利义务约定不明。"),
            _c("termination_and_breach", "是否约定解约条件与违约责任？",
               "PASS if 解约条件与违约责任载明；FAIL if 解约约定缺失。"),
            _c("ip_and_image", "是否约定肖像/作品使用与归属？",
               "PASS if 艺人肖像、作品使用与归属载明；FAIL if 肖像作品约定不明。"),
        ]),
    _rubric("ppp_project", "PPP项目合同评价规则：风险分担、付费机制、特许经营期与移交。",
        [
            _c("risk_allocation", "是否约定风险分担框架？",
               "PASS if 各类风险的分担原则载明；FAIL if 风险分担约定不明。"),
            _c("payment_mechanism", "是否明确付费/回报机制？",
               "PASS if 政府付费/使用者付费/可行性缺口补助机制载明；FAIL if 回报机制约定不明。"),
            _c("concession_period", "是否约定特许经营期与起算？",
               "PASS if 合作期/特许经营期及起算载明；FAIL if 期限约定不明。"),
            _c("performance_standards", "是否约定产出/服务标准与考核？",
               "PASS if 产出标准、绩效考核与付费挂钩载明；FAIL if 绩效标准缺失。"),
            _c("handback", "是否约定期满移交与资产状态？",
               "PASS if 移交范围、资产状态与程序载明；FAIL if 移交约定缺失。"),
            _c("government_obligations", "是否约定政府方义务与监管？",
               "PASS if 政府方协助义务与监管安排载明；FAIL if 政府义务约定不明。"),
        ]),
    _rubric("tourism_service", "旅游服务合同评价规则：行程、费用、安全、违约与转团。",
        [
            _c("itinerary", "是否明确行程安排与游览内容？",
               "PASS if 行程、交通、住宿与游览安排载明；FAIL if 行程约定不明。"),
            _c("fees_and_inclusions", "是否明确旅游费用与包含项目？",
               "PASS if 费用、包含/不含项目及退费规则载明；FAIL if 费用约定不明。"),
            _c("safety_obligations", "是否约定安全保障与风险提示？",
               "PASS if 安全保障义务与风险提示载明；FAIL if 安全义务缺失。"),
            _c("default_and_refund", "是否约定违约责任与退费？",
               "PASS if 旅行社/旅游者违约责任与退费标准载明；FAIL if 违约退费约定不明。"),
            _c("sub_contracting", "是否约定转团/拼团的限制？",
               "PASS if 转团须经书面同意及责任承担载明；FAIL if 转团规则缺失。"),
            _c("dispute_resolution", "是否约定争议解决与投诉？",
               "PASS if 争议解决与旅游投诉途径载明；FAIL if 争议解决缺失。"),
        ]),
    _rubric("service", "服务合同评价规则：服务内容、标准、费用、期限与验收。",
        [
            _c("service_scope", "是否明确服务内容与范围？",
               "PASS if 服务项目、内容、范围载明；FAIL if 服务内容约定不明。"),
            _c("service_standards", "是否约定服务标准与质量要求？",
               "PASS if 服务标准、质量要求、验收标准载明；FAIL if 服务标准缺失。"),
            _c("service_fees", "是否明确服务费用与支付方式？",
               "PASS if 服务费用、支付方式、支付时间载明；FAIL if 费用约定不明。"),
            _c("service_period", "是否约定服务期限与交付时间？",
               "PASS if 服务期限、交付时间、进度安排载明；FAIL if 期限约定不明。"),
            _c("acceptance_and_delivery", "是否约定服务验收与交付？",
               "PASS if 验收标准、交付方式、验收程序载明；FAIL if 验收交付约定缺失。"),
            _c("confidentiality_and_ip", "是否约定保密义务与知识产权？",
               "PASS if 保密义务、知识产权归属载明；FAIL if 保密知识产权约定不明。"),
        ]),
    _rubric("land_transfer", "土地流转合同评价规则：土地信息、流转方式、期限、费用与用途。",
        [
            _c("land_information", "是否明确土地基本信息？",
               "PASS if 土地位置、面积、四至、权属载明；FAIL if 土地信息约定不明。"),
            _c("transfer_method", "是否明确流转方式？",
               "PASS if 流转方式（出租/转让/入股等）载明；FAIL if 流转方式约定不明。"),
            _c("transfer_period", "是否约定流转期限？",
               "PASS if 流转期限、起止日期载明；FAIL if 期限约定不明。"),
            _c("transfer_fees", "是否明确流转费用与支付？",
               "PASS if 流转费用、支付方式、支付时间载明；FAIL if 费用约定不明。"),
            _c("land_use_restrictions", "是否约定土地用途与限制？",
               "PASS if 土地用途、使用限制、保护义务载明；FAIL if 用途限制约定不明。"),
            _c("rights_and_obligations", "是否约定双方权利义务？",
               "PASS if 流转双方权利义务、违约责任载明；FAIL if 权利义务约定缺失。"),
        ]),
]


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--db", type=Path, default=project_root() / DEFAULT_DB)
    args = ap.parse_args()

    from src.eval.db import connect
    from src.eval.law_refined_citations import LAW_REFINED_CITATIONS

    conn = connect()
    try:
        create_schema(conn)
        now_iso = datetime.now(timezone.utc).isoformat()
        for rubric in RUBRICS:
            rid = upsert_local_rubric(conn, rubric, now_iso)
            print(f"  upserted {rubric['name']:34} -> {len(rubric['criteria'])} criteria (rubric_id={rid})")
        # Law-refined v2 variants: v1 criteria + a legal_basis_citation
        # criterion citing the governing statutes from the law_info survey.
        # v1 rubrics are untouched (the v2 names differ from the v1 names).
        n_v2 = 0
        for rubric in RUBRICS:
            type_key = rubric["name"][len("contract_"):-len("_v1")]
            citation = LAW_REFINED_CITATIONS.get(type_key)
            if not citation:
                continue
            v2 = _v2_rubric(rubric, citation)
            rid = upsert_local_rubric(conn, v2, now_iso)
            print(f"  upserted {v2['name']:34} -> {len(v2['criteria'])} criteria (rubric_id={rid})")
            n_v2 += 1
        conn.commit()
        print(f"\nSeeded {len(RUBRICS)} baseline (v1) + {n_v2} law-refined (v2) contract rubrics into {args.db}")
        print_summary(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
