#!/usr/bin/env python3
"""Seed the per-contract-type generation (drafting) prompts.

Two sets are seeded in one idempotent pass:

1. The 19 《民法典》典型有名合同 types - `draft_<type>` prompts mirroring the
   per-class 民法典 rubric themes.
2. The 22 practical (中国合同分类法 Part 2, non-overlapping) types - `draft_<type>`
   prompts mirroring the per-type practical rubric themes, with type-specific
   drafting instructions drawn from each type's governing statute beyond 民法典.

One `draft_<type>` prompt per type, `purpose = 'drafting'`, `contract_type`
matching the rubric type key (loose coupling - no FK). Each prompt's `content`
is a Chinese drafting instruction tailored to that type's mandatory clauses.

Note: 中国合同分类法's D门类 and K类 are NOT seeded (chinese_contracts_class.md
is incomplete - Part 2 cuts off mid-category C; D/K have no details).

Idempotent: upserts by `name` (UNIQUE) - UPDATE if present, else INSERT with
`source = 'local'`. Re-running never duplicates and never touches `rubrics` or
`criteria`. Note: re-running WILL overwrite a prompt edited through the UI -
same trade-off as seed_contract_rubrics.py / seed_sample_local_rubric.py.

Reuses the schema helpers from extract_harbor_rules so the schema has one
source of truth.

Run:
    uv run python scripts/seed_contract_prompts.py
"""

from __future__ import annotations

import argparse
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from extract_harbor_rules import DEFAULT_DB, create_schema, print_summary, project_root


def upsert_local_prompt(conn, prompt: dict, now_iso: str) -> int:
    """Upsert a local prompt by `name` (UNIQUE). Returns the prompt id.

    Single-row upsert (no child table): UPDATE the existing row if the name is
    taken, else INSERT. `source` is always 'local'.
    """
    row = conn.execute(
        "SELECT id FROM prompts WHERE name = %s", (prompt["name"],)
    ).fetchone()
    if row:
        pid = row["id"]
        conn.execute(
            "UPDATE prompts SET contract_type = %s, purpose = %s, content = %s, "
            "prompt_type = %s, description = %s WHERE id = %s",
            (
                prompt["contract_type"],
                prompt["purpose"],
                prompt["content"],
                prompt.get("prompt_type", "baseline"),
                prompt.get("description"),
                pid,
            ),
        )
    else:
        cur = conn.execute(
            "INSERT INTO prompts (name, contract_type, purpose, content, source, "
            "prompt_type, description, created_at) VALUES (%s, %s, %s, %s, 'local', %s, %s, %s) RETURNING id",
            (
                prompt["name"],
                prompt["contract_type"],
                prompt["purpose"],
                prompt["content"],
                prompt.get("prompt_type", "baseline"),
                prompt.get("description"),
                now_iso,
            ),
        )
        pid = cur.fetchone()["id"]
    return pid


def _p(type_key: str, description: str, content: str) -> dict:
    return {
        "name": f"draft_{type_key}",
        "contract_type": type_key,
        "purpose": "drafting",
        "description": description,
        "content": content.strip(),
        "prompt_type": "baseline",
    }


def _v2_prompt(v1: dict, citation: str) -> dict:
    """Law-refined v2 variant of a baseline prompt.

    Same baseline mandatory-clause body, prepended with an explicit 【法律依据】
    clause naming the governing statutes/interpretations/article ranges drawn
    from the law_info survey. ``prompt_type = law-refined``. The baseline v1
    row is untouched (different ``name``).
    """
    return {
        "name": f"{v1['name']}_v2",
        "contract_type": v1["contract_type"],
        "purpose": v1["purpose"],
        "description": f"{v1['description']}（法律精修版）",
        "content": f"【法律依据】依据{citation}。\n\n{v1['content']}",
        "prompt_type": "law-refined",
    }


# Per-type drafting prompts. Two sets: 19 民法典 types + 22 practical (中国合同
# 分类法 Part 2, non-overlapping) types. content = Chinese drafting instructions.
PROMPTS: list[dict] = [
    _p("sale", "买卖合同起草提示词",
       """起草一份买卖合同。须包含：标的物名称、规格、数量与质量标准；价款与支付方式（含定金、尾款节点）；交付时间、地点与方式；所有权转移时点（交付或登记）；毁损灭失风险自交付时转移（或另有约定）；检验期间与质量异议通知方式；瑕疵担保责任及修理/更换/退货/减价救济；违约责任与争议解决。如分期付款，可约定所有权保留并办理登记。"""),
    _p("utilities_supply", "供用电水气热力合同起草提示词",
       """起草一份供用（电/水/气/热力）合同。须包含：供应人与用户信息；供应标的与质量标准；计量方式、单价及结算周期；连续供应义务；中止供应的事由与事先通知义务及合理期限；用户缴费义务与违约责任；争议解决。"""),
    _p("gift", "赠与合同起草提示词",
       """起草一份赠与合同。须包含：赠与人、受赠人信息；赠与财产的名称、数量与状况；交付或登记办理安排（不动产须办登记）；赠与人任意撤销权的条件（交付前、非公证/公益除外）；法定撤销事由与一年除斥期间；如附义务，载明所附义务（不超过赠与财产价值）；违约责任。"""),
    _p("loan", "借款合同起草提示词",
       """起草一份借款合同。须包含：借款人、贷款人信息；借款币种与金额；借款用途及挪用后果；利率（不得超过合同成立时一年期LPR的四倍）；利息支付方式与周期；借款期限与还款方式；提前还款的条件与利息处理；违约责任与争议解决。"""),
    _p("guarantee", "保证合同起草提示词",
       """起草一份保证合同。须包含：保证人、债权人、债务人信息；被担保的主债权种类与数额；保证方式（一般保证或连带责任保证，未约定推定一般保证）；保证范围（主债权及利息、违约金、损害赔偿、实现债权费用）；保证期间与起算时点；主合同变更须经保证人同意及后果；违约责任。"""),
    _p("lease", "租赁合同起草提示词",
       """起草一份租赁合同。须包含：出租人、承租人信息；租赁物名称、数量、用途；租赁期限（不得超过20年，超过部分无效）；租金数额、支付方式与周期；交付与返还状态；维修义务（原则上出租人）；承租人优先承租权（同等条件下）；转租须经出租人同意；违约责任与争议解决。"""),
    _p("financing_lease", "融资租赁合同起草提示词",
       """起草一份融资租赁合同。须包含：出租人、承租人、出卖人信息；租赁物名称、规格与选定；租金构成（购买成本与利润）及支付周期；租赁物所有权归出租人并办理登记（对抗第三人）；租赁物瑕疵与维修责任（多由承租人负担）；期满租赁物归属（留购/续租/返还）；违约责任。"""),
    _p("factoring", "保理合同起草提示词",
       """起草一份保理合同。须包含：保理人、应收账款债权人信息；应收账款描述（金额、基础交易、债务人）；有追索权或无追索权类型；应收账款转让通知债务人的安排；保理服务内容（资金融通/管理/催收/付款担保）；回购或反转让的触发情形与对价；违约责任。"""),
    _p("work", "承揽合同起草提示词",
       """起草一份承揽合同。须包含：定作人、承揽人信息；工作成果名称、规格与技术要求；材料提供方与毁损风险负担；交付时间、地点与验收标准/期限；报酬数额与支付方式；定作人指示变更与协助义务；承揽人留置权（报酬未付时）；违约责任。"""),
    _p("construction", "建设工程合同起草提示词",
       """起草一份建设工程合同。须包含：发包人、承包人信息；工程范围与工期；工程价款与支付节点（预付/进度/结算）及结算方式；竣工验收标准、程序与期限；质量保修范围与保修期；承包人工程价款优先受偿权及行使期限；违约责任与争议解决。"""),
    _p("transport", "运输合同起草提示词",
       """起草一份运输合同。须包含：承运人、旅客/托运人信息；运输标的（货物描述或旅客）与起运地、目的地；运到期限；运费与支付方式；客票/托运单等运输凭证；货物灭失毁损的赔偿标准与限额；承运人免责事由（不可抗力、货物自身性质等）；违约责任。"""),
    _p("technology", "技术合同起草提示词",
       """起草一份技术（开发/转让/咨询/服务）合同。须包含：项目名称与内容；技术成果权属（专利申请权/所有权）归属；保密范围、期限与违约责任；后续改进成果的归属与分享；技术开发风险分担（如适用）；价款或使用费及支付方式；验收标准；违约责任。"""),
    _p("bailment", "保管合同起草提示词",
       """起草一份保管合同。须包含：保管人、寄存人信息；保管物名称、数量与状况；交付与返还时点及状态；保管期间；保管费（有偿/无偿）及支付；赔偿责任标准（有偿重于无偿）；危险保管物的告知义务；违约责任。"""),
    _p("warehousing", "仓储合同起草提示词",
       """起草一份仓储合同。须包含：保管人、存货人信息；仓储物名称、数量与状况；储存期间；入库验收与出库提取程序；仓单签发及必要记载事项；危险物品告知与处置；损害赔偿范围与限额；仓储费及支付；违约责任。"""),
    _p("entrustment", "委托合同起草提示词",
       """起草一份委托合同。须包含：委托人、受托人信息；委托事务范围与代理权限；转委托须经同意及责任承担；受托人报告进度与结果的义务；费用预付/垫付与报酬及支付方式；委托人或受托人的任意解除权及赔偿后果；违约责任。"""),
    _p("property_service", "物业服务合同起草提示词",
       """起草一份物业服务合同。须包含：物业服务人与业主（或业主大会）信息；服务事项、标准与质量要求；物业费项目、标准与收缴方式；服务期限；业主解聘权与程序及提前通知期限；服务终止时的资料、财物交接义务；专项维修资金的筹集与使用；违约责任。"""),
    _p("brokerage", "行纪合同起草提示词",
       """起草一份行纪合同。须包含：委托人、行纪人信息；委托贸易的商品、数量与价格区间；行纪人以自己名义从事贸易及法律后果；低于指定价格卖出或高于指定价格买入的差额补偿或利益归属；行纪人自买自卖的情形与价格条件；报酬数额与支付条件；违约责任。"""),
    _p("intermediation", "中介合同起草提示词",
       """起草一份中介合同。须包含：委托人、中介人信息；中介服务内容（报告订约机会或提供媒介服务）；中介人如实报告重要事项的义务及隐瞒责任；报酬数额与支付条件（以促成合同成立为条件）；未促成时中介活动费用的承担；违约责任。"""),
    _p("partnership", "合伙合同起草提示词",
       """起草一份合伙合同。须包含：合伙人信息；合伙目的与事业；出资方式（货币/实物/劳务等）与数额；利润分配与亏损分担比例；合伙事务执行人与决策/表决规则；入伙的同意条件与退伙的结算方式；解散事由与清算程序；违约责任。"""),

    # --- 中国合同分类法 Part 2 (practical, non-overlapping) ----------------- #

    _p("company_formation", "公司设立合同起草提示词",
       """起草一份公司设立合同（发起人协议）。须包含：发起人信息；拟设公司名称、住所与经营范围；注册资本、各股东出资方式（货币/非货币）、认缴数额与实缴期限；公司章程制定安排及组织机构、表决规则等必备条款；设立中公司的费用与债务承担；公司登记办理义务、期限及逾期后果；违约责任与争议解决。"""),
    _p("equity_transfer", "股权转让合同起草提示词",
       """起草一份股权转让合同。须包含：出让方、受让方信息；标的公司基本情况；转让股权比例与权属状况（无质押/冻结）；其他股东放弃优先购买权或依法通知的安排；转让价款、支付节点与方式；工商变更登记办理方与期限；出让方权属瑕疵担保；公司及其他股东同意程序；违约责任与争议解决。"""),
    _p("capital_increase", "增资扩股协议起草提示词",
       """起草一份增资扩股协议。须包含：原股东、新股东（投资人）与公司信息；增资后估值、认购价款及计入注册资本与资本公积的比例；原股东优先认缴权的行使与放弃；注册资本变更登记与章程修订安排；新股东表决权、分红权及董事会席位等权利安排；交割先决条件与交割安排；违约责任与争议解决。"""),
    _p("merger_acquisition", "公司并购协议起草提示词",
       """起草一份公司并购协议。须包含：收购方、出让方与标的公司信息；交易结构（股权/资产收购）与标的范围；对价、支付方式与对价调整机制（如交割审计）；交割先决条件、交割日与交割义务；过渡期经营约束与竞业限制；反垄断/经营者集中申报等审批安排（如适用）；陈述与保证及违约赔偿；违约责任与争议解决。"""),
    _p("equity_incentive", "股权激励协议起草提示词",
       """起草一份股权激励协议。须包含：公司（授予方）与激励对象信息；激励标的（股权/期权）与授予数量及来源；成熟期、成熟比例与条件；行权价格、行权窗口与方式；离职/违约等情形下的回购价格与丧失条件；激励对象的竞业限制与保密义务；股权登记/代持安排；违约责任与争议解决。"""),
    _p("vam_agreement", "估值调整（对赌）协议起草提示词",
       """起草一份估值调整（对赌）协议。须包含：投资方、创始股东（义务方）与公司信息；业绩承诺指标、计算口径与审计安排；未达标时的股权/现金补偿计算与方式；回购触发情形（如未按期上市）与回购价格计算；对赌相对方（股东vs公司）及对公司履行的效力风险提示；估值调整的顺序与方式；违约责任与争议解决。"""),
    _p("equity_holding_in_trust", "股权代持协议起草提示词",
       """起草一份股权代持协议。须包含：实际出资人（隐名股东）与名义股东信息；代持股权的标的公司、比例与出资归属；分红、表决等权利由实际出资人享有的安排；显名（变更登记）的条件、费用与协助义务；名义股东的保密与配合义务；代持对第三人的效力风险提示（名义股东处分/强制执行等）；违约责任与争议解决。"""),
    _p("real_estate_sale", "房产买卖合同起草提示词",
       """起草一份房产买卖合同。须包含：买卖双方信息；标的房产坐落、面积、权属状况及他项权利；预售商品房时预售许可证号；房价款、付款节点与方式；面积差异处理（退补/解除）；过户登记办理方、期限与税费分担；交付标准、时间及逾期责任；违约责任与争议解决。"""),
    _p("real_estate_lease", "房屋租赁合同起草提示词",
       """起草一份房屋租赁合同。须包含：出租人、承租人信息；租赁房屋坐落、面积与约定用途；租赁登记备案安排；租期、租金、押金及退还条件；维修责任与承租人改造限制；租赁期内房屋转让时承租人继续承租的权利（买卖不破租赁）；承租人优先购买权与期满优先承租权；违约责任与争议解决。"""),
    _p("employment", "劳动合同起草提示词",
       """起草一份劳动合同。须包含：用人单位与劳动者信息；合同期限类型（固定/无固定/以任务）与试用期（不超法定上限）；工作岗位、地点与职责；工资标准、工时制度与社保缴纳；保密义务与竞业限制（含经济补偿）；解除情形与通知程序；经济补偿与代通知金的法定情形；违约责任与争议解决。"""),
    _p("labor_dispatch", "劳务派遣合同起草提示词",
       """起草一份劳务派遣合同（用工单位与派遣单位）。须包含：派遣单位（须具法定资质）与用工单位信息；被派遣劳动者岗位及三性（临时性/辅助性/替代性）属性；同工同酬及薪酬标准；派遣期限与用工总量法定比例；用工单位退回条件；三方权利义务；用工单位给劳动者造成损害时的连带责任；违约责任与争议解决。"""),
    _p("ip_license", "知识产权许可合同起草提示词",
       """起草一份知识产权许可合同。须包含：许可方与被许可方信息；许可的知识产权标的、权属及有效状态；许可地域、期限、方式与独占/排他/普通许可类型；许可费、计算方式与支付节点；许可人对质量监督及维持权利有效的义务；后续改进成果归属与回授；终止后停止使用及资料返还；违约责任与争议解决。"""),
    _p("franchise", "特许经营（加盟）合同起草提示词",
       """起草一份特许经营（加盟）合同。须包含：特许人与被特许人信息；特许经营资源与特许人两店一年资质；特许经营备案安排；信息披露义务的内容与时间；被特许人单方解除的冷静期；区域保护范围与竞业限制；特许经营费、期限（不少于法定下限）与续展条件；违约责任与争议解决。"""),
    _p("real_estate_development", "房地产开发合同起草提示词",
       """起草一份房地产开发合作合同。须包含：合作各方信息；土地取得方式与权属；规划条件与用途及变更约定；建设标准、工期与质量责任；竣工验收标准与交付安排；开发成本分担与支付节点；风险负担与不可抗力安排；收益分配；违约责任与争议解决。"""),
    _p("insurance", "保险合同起草提示词",
       """起草一份保险合同。须包含：投保人、保险人与被保险人/受益人信息；保险标的或被保险人；保险责任范围与责任起止时间；保险费与保险金额；投保人如实告知义务及未尽后果；免责条款（须提示说明）；出险通知、理赔程序与时限；合同解除与争议解决。"""),
    _p("trust", "信托合同起草提示词",
       """起草一份信托合同。须包含：委托人、受托人与受益人信息；信托财产范围与交付方式；信托财产独立于受托人固有财产的提示；信托目的与期限；受托人管理义务、报酬与费用；受益人范围、受益权及变更安排；信托终止情形与清算后财产归属；违约责任与争议解决。"""),
    _p("private_equity_fund", "私募基金合同起草提示词",
       """起草一份私募基金合同。须包含：基金管理人、投资者与托管人信息；合格投资者认定安排；基金类型（公司/合伙/契约）与组织形式；投资范围、策略与限制；管理人与托管人职责；管理费、业绩报酬、收益分配与存续期；退出方式与清算分配安排；信息披露义务；违约责任与争议解决。"""),
    _p("software_development", "软件开发合同起草提示词",
       """起草一份软件开发合同。须包含：委托方与开发方信息；开发范围、需求规格与里程碑；交付物、验收标准与期限；价款与里程碑支付；软件著作权归属与许可安排；需求变更程序与费用调整；质量保证期与维护服务；保密义务；违约责任与争议解决。"""),
    _p("film_production", "影视剧合作制作合同起草提示词",
       """起草一份影视剧合作制作合同。须包含：合作各方信息；投资份额与权利比例；制作分工、周期与质量；署名安排与著作权归属；发行方、发行范围与许可方式；收益分配比例、计算与结算周期；内容审查与合规责任；违约责任与争议解决。"""),
    _p("talent_agency", "演艺经纪合同起草提示词",
       """起草一份演艺经纪合同。须包含：经纪公司与艺人信息；经纪事务（演出/代言/宣传等）范围；分成比例、计算与结算周期；经纪期限与独家/非独家约定；经纪人投入与艺人配合义务；艺人肖像、作品使用与归属；解约条件与违约责任；违约责任与争议解决。"""),
    _p("ppp_project", "PPP项目合同起草提示词",
       """起草一份PPP项目合同。须包含：政府方与社会资本方（项目公司）信息；项目范围与资产权属；风险分担原则；付费/回报机制（政府付费/使用者付费/可行性缺口补助）；合作期/特许经营期及起算；产出标准、绩效考核与付费挂钩；期满移交范围、资产状态与程序；政府方协助义务与监管安排；违约责任与争议解决。"""),
    _p("tourism_service", "旅游服务合同起草提示词",
       """起草一份旅游服务合同。须包含：旅行社与旅游者信息；行程、交通、住宿与游览安排；旅游费用、包含/不含项目及退费规则；安全保障义务与风险提示；旅行社/旅游者违约责任与退费标准；转团/拼团须经书面同意及责任承担；旅游投诉途径与争议解决。"""),
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
        for prompt in PROMPTS:
            pid = upsert_local_prompt(conn, prompt, now_iso)
            print(f"  upserted {prompt['name']:24} [{prompt['contract_type']:18}] (prompt_id={pid})")
        # Law-refined v2 variants: baseline content + a 【法律依据】 citation
        # clause grounded in the law_info survey. Baseline v1 is untouched
        # (the v2 names differ from the v1 names).
        n_v2 = 0
        for prompt in PROMPTS:
            citation = LAW_REFINED_CITATIONS.get(prompt["contract_type"])
            if not citation:
                continue
            v2 = _v2_prompt(prompt, citation)
            pid = upsert_local_prompt(conn, v2, now_iso)
            print(f"  upserted {v2['name']:28} [{v2['contract_type']:18}] (prompt_id={pid})")
            n_v2 += 1
        conn.commit()
        print(f"\nSeeded {len(PROMPTS)} baseline + {n_v2} law-refined drafting prompts into {args.db}")
        print_summary(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
