#!/usr/bin/env python3
"""Initialize industry standard reference table with governing statutes."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

load_dotenv()

from psycopg.types.json import Jsonb
from src.eval.db import connect
from src.eval.store import ensure_schema


INDUSTRY_STANDARD_REFERENCE = [
    # Company Equity Category
    ("company_formation", "中华人民共和国公司法（2023 修订）", None),
    ("equity_transfer", "中华人民共和国公司法（2023 修订）", None),
    ("capital_increase", "中华人民共和国公司法（2023 修订）", None),
    ("merger_acquisition", "中华人民共和国公司法（2023 修订）\n中华人民共和国反垄断法\n上市公司收购管理办法", None),
    ("equity_incentive", "上市公司股权激励管理办法\n证券法", None),
    ("vam_agreement", "全国法院民商事审判工作会议纪要（九民纪要）\n最高人民法院关于审理外商投资企业纠纷案件若干问题的规定", None),
    ("equity_holding_in_trust", "中华人民共和国信托法\n最高人民法院关于适用<中华人民共和国公司法>若干问题的规定", None),

    # Real Estate Category
    ("real_estate_sale", "中华人民共和国城市房地产管理法\n商品房销售管理办法\n最高人民法院关于审理商品房买卖合同纠纷案件适用法律若干问题的解释（2020 修正）", None),
    ("real_estate_lease", "中华人民共和国城市房地产管理法\n商品房屋租赁管理办法\n最高人民法院关于审理城镇房屋租赁合同纠纷案件具体应用法律若干问题的解释（法释〔2009〕11 号）", None),
    ("real_estate_development", "中华人民共和国城市房地产管理法\n城市房地产开发经营管理条例", None),

    # Labor Relations Category
    ("employment", "中华人民共和国劳动合同法（2012 修正）\n中华人民共和国劳动法（2018 修正）\n劳动合同法实施条例\n最高人民法院关于审理劳动争议案件适用法律的解释", None),
    ("labor_dispatch", "中华人民共和国劳动合同法（第五章第二节劳务派遣 第 57-67 条）\n劳务派遣暂行规定（人社部令第 22 号）\n劳动合同法实施条例", None),

    # IP Rights Category
    ("ip_license", "中华人民共和国专利法\n中华人民共和国商标法\n中华人民共和国著作权法\n最高人民法院关于审理技术合同纠纷案件适用法律若干问题的解释（法释〔2004〕20 号）", None),
    ("software_development", "中华人民共和国民法典（合同编第二十章技术合同第 843-887 条）\n计算机软件保护条例", None),

    # Financial Services Category
    ("insurance", "中华人民共和国保险法（2015 修正）\n保险法司法解释（二）（法释〔2013〕14 号）\n保险法司法解释（三）（法释〔2015〕21 号）\n保险法司法解释（四）（法释〔2018〕13 号）", None),
    ("trust", "中华人民共和国信托法\n信托公司管理办法（国家金融监督管理总局令 2025 年第 8 号）", None),
    ("private_equity_fund", "中华人民共和国证券投资基金法（第十章非公开募集基金第 88-94 条）\n私募投资基金监督管理条例（国务院令第 762 号）\n私募投资基金监督管理暂行办法（证监会令第 105 号）", None),

    # Other Categories
    ("franchise", "商业特许经营管理条例（国务院令第 485 号）\n商业特许经营信息披露管理办法\n商业特许经营备案管理办法", None),
    ("film_production", "中华人民共和国著作权法（2021 修订）\n电影产业促进法", None),
    ("talent_agency", "中华人民共和国民法典\n营业性演出管理条例\n文化和旅游部关于规范演出经纪行为加强演员管理促进演出市场健康有序发展的通知（文旅市场发〔2021〕101 号）", None),
    ("ppp_project", "中华人民共和国政府采购法\n基础设施和公用事业特许经营管理办法（发改委等六部委第 17 号令，2024 年施行）\n最高人民法院关于审理行政协议案件若干问题的规定（法释〔2019〕17 号）", None),
    ("tourism_service", "中华人民共和国旅游法（第五章旅游服务合同第 57-75 条）\n旅行社条例\n最高人民法院关于审理旅游纠纷案件适用法律若干问题的规定", None),
]

CORE_CLAUSE_MAPPINGS = [
    # Company equity category core clauses
    ("company_formation", Jsonb([
        "股东出资方式、数额与实缴期限",
        "公司章程的制定与必备条款",
        "设立中公司的费用与债务承担",
        "公司登记办理义务与违约后果"
    ])),
    ("equity_transfer", Jsonb([
        "转让价款与支付方式",
        "其他股东同意程序及优先购买权处理",
        "股权转让变更登记",
        "瑕疵担保责任"
    ])),
    ("capital_increase", Jsonb([
        "原股东优先认缴出资权",
        "增资估值、认购价款与溢价处理",
        "注册资本变更登记与章程修订",
        "新股东权利与公司治理安排",
        "交割先决条件与交割安排"
    ])),
    ("merger_acquisition", Jsonb([
        "交易对价确定方式",
        "交割安排与过渡期义务",
        "陈述与保证",
        "申报与审批程序"
    ])),
    ("equity_incentive", Jsonb([
        "激励对象资格确认",
        "授予数量与价格",
        "成熟条件与行权安排",
        "离职回购机制"
    ])),
    ("vam_agreement", Jsonb([
        "业绩承诺指标设定",
        "补偿计算方式",
        "回购触发条件与价格",
        "协议效力约定"
    ])),
    ("equity_holding_in_trust", Jsonb([
        "代持股权详细信息",
        "实际出资人权利义务",
        "名义股东义务",
        "显名化条件"
    ])),

    # Real estate category
    ("real_estate_sale", Jsonb([
        "房屋基本信息与产权状况",
        "预售许可证号",
        "价款及支付安排",
        "交付时间标准",
        "面积差异处理",
        "产权登记过户"
    ])),
    ("real_estate_lease", Jsonb([
        "租赁房屋基本情况",
        "租赁期限",
        "租金及支付方式",
        "维修义务",
        "登记备案",
        "优先承租权"
    ])),
    ("real_estate_development", Jsonb([
        "土地使用权取得方式",
        "规划许可与施工许可",
        "开发建设期限",
        "竣工验收标准"
    ])),

    # Labor relations
    ("employment", Jsonb([
        "工作内容与地点",
        "劳动合同期限与试用期",
        "劳动报酬",
        "社会保险缴纳",
        "工作时间与休息休假",
        "合同解除条件"
    ])),
    ("labor_dispatch", Jsonb([
        "派遣岗位与期限",
        "同工同酬保障",
        "派遣资质要求",
        "退回情形"
    ])),

    # IP rights
    ("ip_license", Jsonb([
        "许可权利类型与范围",
        "许可是否独占/排他",
        "许可期限与地域",
        "许可费用与支付",
        "质量监督与保密"
    ])),
    ("software_development", Jsonb([
        "开发内容与功能要求",
        "交付成果与验收标准",
        "知识产权归属",
        "维护服务范围"
    ])),

    # Financial services
    ("insurance", Jsonb([
        "保险标的与保险金额",
        "保险责任与免责条款",
        "如实告知义务",
        "理赔程序"
    ])),
    ("trust", Jsonb([
        "信托财产范围",
        "受益人权益",
        "受托人职责",
        "信托终止清算"
    ])),
    ("private_equity_fund", Jsonb([
        "合格投资者确认",
        "基金管理人与托管人",
        "投资范围与限制",
        "退出机制"
    ])),

    # Others
    ("franchise", Jsonb([
        "特许经营活动内容",
        "经营资源提供",
        "加盟费及费用",
        "冷静期条款",
        "区域保护"
    ])),
    ("film_production", Jsonb([
        "投资份额与比例",
        "署名权安排",
        "发行与收益分配",
        "审查合规责任"
    ])),
    ("talent_agency", Jsonb([
        "经纪业务范围",
        "合作期限",
        "分成比例",
        "解约条件"
    ])),
    ("ppp_project", Jsonb([
        "项目内容与合作模式",
        "投融资结构与付费机制",
        "风险分担",
        "移交安排"
    ])),
    ("tourism_service", Jsonb([
        "行程安排与标准",
        "旅游费用明细",
        "安全责任",
        "违约处理"
    ])),
]


def main():
    """Initialize industry standards reference data."""
    db_path = None

    conn = connect(db_path)
    try:
        cur = conn.execute("""
            CREATE TABLE IF NOT EXISTS industry_standard_references (
                id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                contract_type TEXT NOT NULL UNIQUE,
                governing_statutes TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)

        print(f"Created table: {cur.rowcount} rows affected")

        now = conn.execute("SELECT NOW()").fetchone()["now"]

        for contract_type, statutes, _ in INDUSTRY_STANDARD_REFERENCE:
            try:
                cur = conn.execute("""
                    INSERT INTO industry_standard_references (contract_type, governing_statutes, created_at, updated_at)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (contract_type) DO UPDATE SET
                        governing_statutes = EXCLUDED.governing_statutes,
                        updated_at = EXCLUDED.updated_at
                """, (contract_type, statutes, now, now))

                status = "Inserted/Updated" if cur.rowcount > 0 else "Skipped"
                print(f"[{status}] {contract_type}: {statutes.split(chr(10))[0][:50]}...")

            except Exception as e:
                print(f"[ERROR] Failed to insert {contract_type}: {e}")
                raise

        conn.commit()

        # Create core clause mappings table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS core_clauses (
                id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                contract_type TEXT NOT NULL,
                core_mandatory_clauses JSONB NOT NULL DEFAULT '[]'::jsonb,
                FOREIGN KEY (contract_type) REFERENCES industry_standard_references(contract_type) ON DELETE CASCADE,
                UNIQUE(contract_type)
            )
        """)

        for contract_type, clauses in CORE_CLAUSE_MAPPINGS:
            try:
                cur = conn.execute("""
                    INSERT INTO core_clauses (contract_type, core_mandatory_clauses)
                    VALUES (%s, %s)
                    ON CONFLICT (contract_type) DO UPDATE SET
                        core_mandatory_clauses = EXCLUDED.core_mandatory_clauses
                """, (contract_type, clauses))

                status = "Inserted/Updated" if cur.rowcount > 0 else "Skipped"
                print(f"[{status}] {contract_type}: core clauses mapped")

            except Exception as e:
                print(f"[ERROR] Failed to map clauses for {contract_type}: {e}")
                raise

        conn.commit()
        print("\n✓ Successfully initialized industry standard reference tables!")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
