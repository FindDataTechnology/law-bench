#!/usr/bin/env python3
"""Deterministic slot-value bank for synthetic template instantiation.

Fills ``{{槽位名}}`` placeholders (CJK or ASCII) in ``contract_artifacts``
master-template bodies with realistic, deterministic values so the curated
clause assemblies can serve as Drafter-A silver SFT pairs.

Design (see openspec/changes/expand-drafter-a-silver/design.md D2):

- ``EXPLICIT``: hand-curated per-slot-name value lists (head of the frequency
  distribution, >=8 variants each).
- ``CATEGORY_RULES`` + ``CATEGORY_POOL``: ordered keyword rules mapping a slot
  name to a value category (party/date/amount/...) — carries the long tail
  (2,588 distinct names over 395 rows; an all-explicit table is infeasible).
- A slot name is *missing* when neither table resolves it; callers MUST drop
  the whole row (never partially fill).
- Determinism: values are drawn from ``random.Random(int(sha256(body), 16))``
  iterating sorted slot names, so the same body yields byte-identical fills
  on every run/platform (Mersenne Twister + integer seed is stable).

Stdlib only — these scripts must run without the project venv (litellm fails
to build on some dev machines).
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import random
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from common import SLOT_RE  # noqa: E402  (single shared placeholder syntax)

# ---------------------------------------------------------------------------
# explicit per-name values (frequency head; >=8 variants each)
# ---------------------------------------------------------------------------

EXPLICIT: dict[str, list[str]] = {
    # parties & representatives
    "甲方名称": [
        "晟华科技有限公司", "恒基建设集团有限公司", "瑞丰贸易有限公司",
        "中科智联信息技术有限公司", "万恒实业发展有限公司", "博远文化传媒有限公司",
        "天泽环保科技有限公司", "启元生物科技有限公司", "宏图教育科技有限公司",
        "安捷物流股份有限公司",
    ],
    "乙方名称": [
        "铭泰精密制造有限公司", "华信电子科技有限公司", "东方国泰商贸有限公司",
        "蓝天文化传媒有限公司", "佳成建筑装饰工程有限公司", "锐维软件技术有限公司",
        "汇金投资管理有限公司", "绿源农产品有限公司", "拓普机械设备有限公司",
        "雅居房地产开发有限公司",
    ],
    "甲方法定代表人": [
        "张伟明", "李建国", "王志强", "刘德海", "陈永康",
        "赵立诚", "周文斌", "吴国栋", "郑少华", "孙嘉铭",
    ],
    "乙方法定代表人": [
        "杨春晖", "林淑芬", "黄振宇", "徐丽娟", "何俊杰",
        "高鹏飞", "罗美玲", "梁国雄", "宋晓东", "唐明远",
    ],
    "甲方委托代理人": [
        "马晓峰", "冯雅琴", "董文杰", "蒋一鸣", "沈若男",
        "潘俊涛", "汪丽华", "钟启文", "谢东升", "雷海燕",
    ],
    "乙方委托代理人": [
        "贺志远", "施婉君", "曹俊豪", "严雪梅", "龚振邦",
        "程思琪", "陆建辉", "韩雪莹", "傅文博", "彭静怡",
    ],
    "甲方义务": [
        "按约定交付标的物并保证质量符合国家标准",
        "按时支付全部合同款项，不得无故拖延",
        "提供完成本项目所需的全套资料与技术支持",
        "对提供资料的真实性、完整性、合法性负责",
        "指派专人负责项目对接与日常沟通协调",
        "妥善保管对方提供的保密信息，不得外泄",
        "配合完成验收工作并及时出具书面确认",
        "依法缴纳因履行本合同产生的各项税费",
    ],
    "乙方义务": [
        "按约定时间完成全部工作内容并交付成果",
        "严格按照国家行业标准和操作规程施工",
        "指派具有相应资质的人员提供服务",
        "对工作成果承担质量瑕疵担保责任",
        "及时向甲方通报履约进展与重大事项",
        "妥善使用并按时归还甲方提供的设备资料",
        "对履约过程中知悉的商业秘密承担保密义务",
        "负责工作现场的安全管理与事故防范",
    ],
    # dispute resolution
    "争议解决方式": [
        "提交甲方所在地有管辖权的人民法院诉讼解决",
        "提交乙方所在地有管辖权的人民法院诉讼解决",
        "提交合同签订地有管辖权的人民法院诉讼解决",
        "提交标的物所在地有管辖权的人民法院诉讼解决",
        "提交本地仲裁委员会仲裁解决",
        "提交中国国际经济贸易仲裁委员会仲裁解决",
        "双方协商解决；协商不成的，提交仲裁委员会仲裁",
        "双方协商解决；协商不成的，向人民法院提起诉讼",
    ],
    "仲裁委员会": [
        "北京仲裁委员会", "上海仲裁委员会", "深圳国际仲裁院",
        "广州仲裁委员会", "武汉仲裁委员会", "成都仲裁委员会",
        "杭州仲裁委员会", "南京仲裁委员会", "西安仲裁委员会", "重庆仲裁委员会",
    ],
    # core deal slots
    "合同标的": [
        "智能化仓储管理系统一套（含软硬件及实施服务）",
        "商用中央空调设备一批（规格型号详见附件）",
        "标准厂房钢结构工程（建筑面积详见施工图）",
        "有机农产品一批（品种、数量详见供货清单）",
        "企业信息化咨询 services（范围详见工作说明书）".replace(" services", "服务"),
        "精密数控机床五台（型号及技术参数详见附件）",
        "商业物业装修改造工程（范围以设计图纸为准）",
        "软件开发与运维服务（模块清单详见需求说明书）",
    ],
    "价款金额": [
        "人民币壹佰贰拾万元整（¥1,200,000.00）",
        "人民币捌拾陆万元整（¥860,000.00）",
        "人民币叁佰伍拾万元整（¥3,500,000.00）",
        "人民币肆拾捌万元整（¥480,000.00）",
        "人民币贰拾陆万伍仟元整（¥265,000.00）",
        "人民币玖拾柒万叁仟元整（¥973,000.00）",
        "人民币壹佰玖拾捌万元整（¥1,980,000.00）",
        "人民币陆拾壹万捌仟元整（¥618,000.00）",
    ],
    "违约金": [
        "合同总价的百分之十（10%）",
        "合同总价的百分之五（5%）",
        "人民币拾万元整",
        "人民币伍万元整",
        "每日按合同总价的千分之一累计计算",
        "每逾期一日按未付金额的万分之五计算",
        "合同总价的百分之二十（20%）",
        "人民币贰拾万元整",
    ],
    # dating
    "签署日期": [
        "2026年3月15日", "2026年5月8日", "2026年7月22日", "2026年9月10日",
        "2026年11月3日", "2027年1月18日", "2027年4月26日", "2027年6月30日",
    ],
    "履行起始日期": [
        "2026年4月1日", "2026年6月10日", "2026年8月15日", "2026年10月1日",
        "2027年1月5日", "2027年3月20日", "2027年5月18日", "2027年8月9日",
    ],
    "履行结束日期": [
        "2027年3月31日", "2027年6月30日", "2027年12月31日", "2028年3月31日",
        "2026年12月31日", "2028年6月30日", "2029年3月31日", "2026年9月30日",
    ],
    "天数": ["15", "30", "45", "60", "90", "10", "20", "7"],
    # payment & shipping
    "付款方式": [
        "银行转账（分期支付，具体节点见付款计划）",
        "银行转账（验收合格后一次性付清）",
        "银行承兑汇票结算",
        "预付30%，交付后支付60%，质保金10%期满付清",
        "按月度结算，次月10日前支付上月款项",
        "电汇至指定账户，货到验收合格后七日内付款",
        "预付50%，余款于交付验收后十五日内付清",
        "按工程进度节点分段支付",
    ],
    "交付方式": [
        "乙方送货至甲方指定地点并承担运输费用",
        "甲方自提，运输费用由甲方承担",
        "物流托运，运费由乙方承担",
        "现场交付并完成安装调试",
        "电子交付（线上系统传输）与纸质交付并行",
        "分批交付，批次计划另行约定",
        "乙方代办托运，保险费由乙方承担",
        "货交第一承运人即视为完成交付",
    ],
    "签署地点": [
        "北京市朝阳区", "上海市浦东新区", "深圳市福田区", "广州市天河区",
        "杭州市西湖区", "成都市高新区", "武汉市江汉区", "南京市建邺区",
    ],
}

# ---------------------------------------------------------------------------
# category pools (long tail; >=8 variants each)
# ---------------------------------------------------------------------------

CATEGORY_POOL: dict[str, list[str]] = {
    "party": [
        "晟华科技有限公司", "恒基建设集团有限公司", "瑞丰贸易有限公司",
        "中科智联信息技术有限公司", "万恒实业发展有限公司", "博远文化传媒有限公司",
        "天泽环保科技有限公司", "启元生物科技有限公司", "张伟明", "李淑华",
    ],
    "person": [
        "张伟明", "李建国", "王志强", "刘德海", "陈永康",
        "林淑芬", "黄振宇", "徐丽娟", "何俊杰", "罗美玲",
    ],
    "date": [
        "2026年3月15日", "2026年5月8日", "2026年7月22日", "2026年9月10日",
        "2026年11月3日", "2027年1月18日", "2027年4月26日", "2027年6月30日",
    ],
    "month": ["2026年3月", "2026年6月", "2026年9月", "2026年12月",
              "2027年3月", "2027年6月", "2027年9月", "2027年12月"],
    "year": ["2026年", "2027年", "2028年", "2029年", "2030年", "2031年", "2032年", "2033年"],
    "amount": [
        "人民币壹佰贰拾万元整（¥1,200,000.00）",
        "人民币捌拾陆万元整（¥860,000.00）",
        "人民币叁佰伍拾万元整（¥3,500,000.00）",
        "人民币肆拾捌万元整（¥480,000.00）",
        "人民币贰拾陆万伍仟元整（¥265,000.00）",
        "人民币玖拾柒万叁仟元整（¥973,000.00）",
        "人民币壹拾捌万陆仟元整（¥186,000.00）",
        "人民币陆拾壹万捌仟元整（¥618,000.00）",
    ],
    "amount_upper": [
        "人民币壹佰贰拾万元整", "人民币捌拾陆万元整", "人民币叁佰伍拾万元整",
        "人民币肆拾捌万元整", "人民币贰拾陆万伍仟元整", "人民币玖拾柒万叁仟元整",
        "人民币壹拾捌万陆仟元整", "人民币陆拾壹万捌仟元整",
    ],
    "percent": ["5%", "10%", "15%", "20%", "30%", "50%", "80%", "95%"],
    "ratio_precise": ["0.5%", "1%", "2%", "3%", "5‰", "1‰", "8%", "12%"],
    "days": ["7", "10", "15", "30", "45", "60", "90", "120"],
    "hours": ["4", "8", "12", "24", "48", "72", "2", "6"],
    "months_count": ["3", "6", "12", "18", "24", "36", "48", "60"],
    "years_count": ["1", "2", "3", "5", "8", "10", "15", "20"],
    "location": [
        "北京市朝阳区建国路88号", "上海市浦东新区世纪大道100号", "深圳市福田区深南大道6013号",
        "广州市天河区体育西路103号", "杭州市西湖区文三路90号", "成都市高新区天府大道北段1700号",
        "武汉市江汉区建设大道568号", "南京市建邺区江东中路369号",
    ],
    "city": ["北京", "上海", "广州", "深圳", "杭州", "成都", "武汉", "南京"],
    "phone": [
        "010-88886666", "021-58881234", "0755-82889999", "020-38885566",
        "0571-87663322", "028-85229911", "027-85776633", "025-84445522",
    ],
    "email": [
        "legal@shenghua-tech.com", "contract@hengji-group.com", "admin@ruifeng-trade.com",
        "service@zhongke-ai.com", "ops@wanheng-ind.com", "info@boyuan-media.com",
        "support@tianze-env.com", "hr@qiyuan-bio.com",
    ],
    "postal": ["100020", "200120", "518000", "510620", "310012", "610041", "430022", "210019"],
    "bank": [
        "中国工商银行北京朝阳支行", "中国建设银行上海浦东支行", "中国银行深圳福田支行",
        "中国农业银行广州天河支行", "招商银行杭州西湖支行", "交通银行成都锦江支行",
        "中信银行武汉江岸支行", "民生银行南京建邺支行",
    ],
    "account": [
        "0200 0012 3456 7890 012", "3100 5678 1234 5678 901", "4560 9876 5432 1098 765",
        "6228 4800 1234 5678 901", "6214 8500 9876 5432 109", "4367 4200 2468 1357 902",
        "6229 9100 1122 3344 556", "6217 2800 5566 7788 990",
    ],
    "code": [
        "91110108MA01X2Y3Z4", "91310115MA1K3P5Q7R", "91440300MA5E7G9H1K",
        "11440100MA3C5D7F9H", "91330106MA2B4D6F8J", "91510100MA7F9H1K3M",
        "91420100MA6D8F0H2L", "91320100MA4E6G8I0N",
    ],
    "doc_number": [
        "SH-2026-0315-001", "HJ-2026-0508-012", "RF-2026-0722-003",
        "ZK-2026-0910-021", "WH-2026-1103-007", "BY-2027-0118-015",
        "TZ-2027-0426-002", "QY-2027-0630-019",
    ],
    "count": ["2", "3", "4", "5", "6", "8", "10", "12"],
    "measure": [
        "120平方米", "350平方米", "800平方米", "1,200平方米",
        "2,600平方米", "5,800平方米", "10,500平方米", "320平方米",
    ],
    "weight": ["50吨", "120吨", "300吨", "500吨", "800吨", "1,200吨", "2,000吨", "75吨"],
    "area_land": [
        "1.2公顷", "3.5公顷", "6.8公顷", "12公顷",
        "35公顷", "68公顷", "120公顷", "2.6公顷",
    ],
    "institution": [
        "北京市朝阳区市场监督管理局", "上海市浦东新区人民法院", "深圳市福田区人民法院",
        "广州市天河区市场监督管理局", "杭州仲裁委员会", "成都市不动产登记中心",
        "武汉市公证处", "南京市建邺区人民法院",
        "北京仲裁委员会", "上海仲裁委员会", "深圳国际仲裁院", "中国国际经济贸易仲裁委员会",
    ],
    "method": [
        "按照国家有关标准和行业惯例执行",
        "双方另行协商确定并签订书面补充协议",
        "以双方书面确认的方案为准",
        "按本合同附件约定的方式执行",
        "符合国家标准GB/T相关规范",
        "由双方代表现场共同确认",
        "书面通知对方后按通知内容执行",
        "依法律法规规定的程序办理",
    ],
    "standard": [
        "符合国家标准及行业规范要求",
        "达到设计文件和验收规范规定的标准",
        "符合GB/T 19001质量管理体系要求",
        "满足招标文件约定的技术标准",
        "符合国家强制性标准要求",
        "按双方确认的样品标准执行",
        "达到优良等级标准",
        "符合现行有效的行业标准",
    ],
    "text": [
        "双方另行协商确定",
        "以双方书面确认的内容为准",
        "按国家有关规定执行",
        "详见本合同附件约定",
        "无另行约定事项",
        "由双方友好协商解决",
        "按行业惯例执行",
        "以书面补充协议为准",
    ],
    "boolean_consent": [
        "经对方书面同意",
        "未经对方书面同意，不得实施",
        "可以，但须提前书面通知对方",
        "不允许",
        "经双方协商一致后实施",
        "须事先取得对方书面授权",
        "在合同约定的范围内允许",
        "不允许，否则承担违约责任",
    ],
    "currency": ["人民币", "美元（USD）", "欧元（EUR）", "日元（JPY）",
                 "港币（HKD）", "英镑（GBP）", "澳元（AUD）", "新加坡元（SGD）"],
    "orientation": ["南北朝向", "坐北朝南", "东西朝向", "坐东朝西",
                    "东南朝向", "西南朝向", "南北通透", "坐南朝北"],
    "layout": ["两室一厅一卫", "三室两厅两卫", "一室一厅一卫", "四室两厅三卫",
               " Loft复式", "开间", "三室一厅一卫", "两室两厅一卫"],
    "yes_no_rich": [
        "包含在本合同价款内", "不包含，另行计费", "包含，无额外费用",
        "不含，由对方承担", "包含于附件报价单", "不包含",
        "包含", "不含，据实结算",
    ],
    "goods": [
        "智能化仓储管理系统一套", "商用中央空调设备一批", "精密数控机床五台",
        "有机农产品一批（品种数量详见供货清单）", "钢结构标准厂房工程",
        "教学管理系统软件（模块详见需求书）", "商用冷藏设备八台",
        "红木办公家具一批（规格详见附件）",
    ],
    "title": [
        "总经理", "副总经理", "财务总监", "部门经理", "项目经理",
        "法务总监", "行政主管", "销售总监", "技术总监", "执行董事",
    ],
    "grade": ["一级", "优等品", "合格品", "特级", "甲级", "乙级", "一等品", "二等品"],
    "relation": ["父子", "母女", "配偶", "兄弟", "姐妹", "祖孙", "叔侄", "翁婿"],
    "unit": ["人民币元", "平方米", "吨", "件", "台", "套", "月", "次"],
    "volume": ["120立方米", "60立方米", "350立方米", "18立方米",
               "88立方米", "240立方米", "45立方米", "500立方米"],
    "seal": ["（加盖公章）", "（盖章）", "（合同专用章）", "（签字并盖章）",
             "（公章）", "（财务专用章）", "（骑缝章）", "（单位盖章）"],
    "multiplier": ["1.5倍", "2倍", "3倍", "5倍", "1.2倍", "2.5倍", "4倍", "10倍"],
    "distance": ["5万公里", "10万公里", "15万公里", "20万公里",
                 "30万公里", "2万公里", "8万公里", "12万公里"],
    "color": ["黑色", "白色", "深灰色", "银色", "蓝色", "红色", "米色", "棕色"],
}

# ---------------------------------------------------------------------------
# classification rules — first match wins. (category, keywords)
# Order is load-bearing: specific date/number shapes before generic text.
# ---------------------------------------------------------------------------

CATEGORY_RULES: list[tuple[str, tuple[str, ...]]] = [
    # money-adjacent first (they contain 数/率/比 traps). Bare 费 is safe here
    # because 费率 was already consumed by ratio_precise above.
    ("amount_upper", ("大写",)),
    ("ratio_precise", ("费率", "千分", "万分", "利率", "罚息", "复利", "区间", "波动")),
    ("percent", ("百分比", "比例", "占比", "百分点", "密度")),
    ("multiplier", ("倍数", "倍率")),
    ("amount", ("金额", "价款", "总价", "单价", "租金", "报酬", "费用", "违约金",
                "定金", "首付款", "贷款", "投资", "补偿", "税金", "余额", "成本",
                "收益", "资金", "款额", "总价款", "总价", "余款", "货款", "保险费",
                "保证金", "佣金", "补贴", "溢价", "对价", "费", "价格", "价值",
                "注册资本", "限额", "上限", "下限", "数额", "合计", "出资", "资本")),
    # durations / counts (before generic date: 天数 ends with 数 not 日)
    ("hours", ("小时",)),
    ("days", ("天数", "天前", "日期前", "日之前", "时限", "宽限", "响应", "修复", "到达")),
    ("days", ("行前",)),  # 行前N天 travel slots expect a day count
    ("months_count", ("月数", "期间")),
    ("years_count", ("年数",)),
    # dates
    ("month", ("月份", "起始月", "结束月", "月$")),
    ("year", ("合同年", "签署年", "年度", "年$")),
    ("date", ("日期", "之日", "起始", "结束", "到期", "到期日", "交付日", "付款日",
              "签署日", "日$", "当日", "时间")),
    # contact / identity
    ("email", ("邮箱", "邮件", "EMAIL", "email")),
    ("phone", ("电话", "传真", "联系方式", "投诉热线", "热线")),
    ("postal", ("邮编", "邮政")),
    ("account", ("账号", "账户", "卡号", "收款码")),
    ("bank", ("开户", "银行$", "银行名称")),
    ("code", ("信用代码", "证件号码", "证号", "编号", "代码", "号码", "许可证",
              "资质号", "批文号", "登记号", "证件", "证卡", "序列号", "串号", "车架",
              "车牌", "IMEI", "执照")),
    ("doc_number", ("合同编号", "运单", "航班", "车次", "票号", "航次")),
    # quantity / measure
    ("area_land", ("土地面积", "占地面积", "公顷", "亩")),
    ("distance", ("公里", "里程")),
    ("measure", ("面积", "容积率", "规模", "高度", "误差", "排量")),
    ("volume", ("体积",)),
    ("weight", ("重量", "吨位", "满载", "减载")),
    ("count", ("份数", "数量", "次数", "总数", "人数", "台数", "件数", "笔数",
               "容量", "页数", "批次")),
    # institutions & parties (goods/product names routed BEFORE this)
    ("institution", ("委员会", "法院", "机关", "登记处", "公证", "监管局", "管理局",
                     "机构", "仲裁", "管辖")),
    ("party", ("甲方$", "乙方$", "丙方$", "当事人$", "许可方$", "受让方$", "转让方$",
               "委托方$", "受托方$", "买方$", "卖方$", "出租方$", "承租方$",
               "收取方$", "支付方$", "承担方$", "提供方$", "接收方$", "持有方$",
               "受益方$", "监督方$", "运营方$", "访问方$", "归属方$", "签署方$",
               "见证人$", "监护人$", "负责人$", "联系人$", "批准方$", "备案方$",
               "违约方$", "终止方$", "通知方$", "补偿方$", "成本方$", "支持方$",
               "服务方$", "供应方$", "需求方$", "获取方$", "所有权人$", "持有人$",
               "代理人$", "代表人$", "国籍", "方$", "公司", "角色", "主体", "部门",
               "政府", "办事处", "法定代表", "代表$", "董事", "官员", "监理")),
    # goods & specs (before generic party 名称 rule: 产品/货物名称 ≠ 当事人)
    ("goods", ("产品名称", "材料名称", "货物名称", "标的物名称", "设备名称", "材料", "物品",
               "服务项目", "项目名称", "工程名称", "品种", "型号", "规格",
               "酒店名称", "景点", "品牌", "制造商", "租赁物")),
    # any other *名称 slot left is an entity of some kind
    ("party", ("名称", "人名")),
    # places (before signature rule: 签署地点 is a place, 签署人 a person)
    ("location", ("地点", "地址", "住所", "位置", "所在地", "现场", "场所", "边界",
                  "站$", "站", "目的地", "口岸", "路段", "区域$", "区域", "产地",
                  "港口")),
    ("city", ("市$", "省$", "区$", "城市", "县$")),
    ("currency", ("币种", "货币")),
    ("orientation", ("朝向",)),
    ("layout", ("布局", "户型")),
    ("color", ("颜色", "内饰")),
    ("party", ("签字", "签署", "人$")),  # signature lines get a person name
    ("seal", ("印章", "盖章")),
    ("unit", ("单位$", "计量单位")),
    ("title", ("职务",)),
    ("grade", ("等级", "级别", "类别")),
    ("relation", ("关系",)),
    ("boolean_consent", ("同意", "允许", "是否", "准许", "可否")),
    ("yes_no_rich", ("包含", "含有", "需含", "税含", "含税")),
    ("standard", ("标准", "要求", "规范", "等级标准", "质量", "检验", "验收", "质保期", "资质")),
    ("method", ("方式", "方法", "办法", "程序", "流程", "进度", "条件", "选项",
                "类型", "模式", "渠道", "手续", "途径", "运输", "包装", "维修",
                "保养", "配备", "供应", "调试", "安装", "装卸", "设施", "排污",
                "排烟", "操作", "处理", "更换")),
    ("text", ("范围", "内容", "清单", "项目", "信息", "描述", "意见", "说明",
              "义务", "责任", "权利", "目的", "用途", "约定", "措施", "限制",
              "条款", "事项", "情形", "后果", "定义", "期限$", "期$", "周期",
              "频次", "阈值", "指标", "结构", "要素", "方案", "策略", "口径",
              "标签", "分类", "来源", "形式", "载体", "工具", "系统$", "平台",
              "服务", "工程", "缺陷", "不合格", "保险", "使用", "阶段", "划分",
              "租赁", "备注", "安排", "承担", "债权", "终止", "保证", "目标",
              "奖励", "处罚", "授权", "许可", "楼层", "单元", "层高", "承重",
              "披露", "成色", "状况", "车况", "套餐", "耗材", "预装", "清除",
              "备用", "线路", "成果", "工作量", "资料", "数据", "声明", "指令",
              "归属", "协助", "功能", "清运", "增减", "损害", "情况", "联运",
              "自备")),
    ("text", ("抵押", "质押", "停车$", "贵重", "晚$", "住宿晚", "禁止", "承诺",
              "保密", "知识产权", "所有权", "处分", "转租", "装修", "续期",
              "免费$", "例外", "其他", "特殊", "行前", "晚")),
]

# ---------------------------------------------------------------------------
# contract type zh names + stance wording
# ---------------------------------------------------------------------------

# Read the committed registry directly (stdlib json; scripts must not import
# src.* because the project venv may be unavailable). Kept in sync by design:
# a new type falls back to the raw key until this map is extended.
_REGISTRY_PATH = (
    pathlib.Path(__file__).resolve().parents[2]
    / "src" / "eval" / "seed" / "law_info" / "contract_types.json"
)


def _load_type_zh() -> dict[str, str]:
    try:
        with _REGISTRY_PATH.open(encoding="utf-8") as fh:
            return {entry["key"]: entry["zh"] for entry in json.load(fh)}
    except (OSError, ValueError, KeyError, TypeError):
        return {}


CONTRACT_TYPE_ZH: dict[str, str] = _load_type_zh()

STANCE_ZH: dict[str, str] = {
    "pro_a": "立场侧重维护甲方利益",
    "pro_b": "立场侧重维护乙方利益",
    "pro_buyer": "立场侧重维护买方利益",
    "pro_seller": "立场侧重维护卖方利益",
    # balanced: omitted by design — it is the neutral default
}


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

def _matches(name: str, keyword: str) -> bool:
    """Keyword match: ``kw$`` anchors to name end, otherwise substring."""
    if keyword.endswith("$"):
        stem = keyword[:-1]
        return name == stem or name.endswith(stem)
    return keyword in name


FALLBACK_CATEGORY = "text"
# The census over the 2026-08-24 snapshot found 2,588 distinct slot names with
# a long idiosyncratic tail (~180 names appear in 1-3 templates each: 碎屏险,
# 充电桩, 车架号...). Hand-curating every one is infeasible, so names that
# survive every category rule draw from the generic legal-filler pool instead
# of dropping the row. Fallback usage is reported per export for audit.


def classify(slot_name: str) -> str | None:
    """Return the value category for a slot name, or None if unclassifiable.

    Strips a trailing digit run first (百分比1 / 金额2 / 通知方1 → stem form),
    then walks the ordered category rules. Pure-ASCII names (exchange_name)
    fall back to the party category — they are identifier-like entities.
    """
    stem = re.sub(r"\d+$", "", slot_name)
    for name in (slot_name, stem):
        for category, keywords in CATEGORY_RULES:
            if any(_matches(name, kw) for kw in keywords):
                return category
    if slot_name.isascii():
        return "party"
    return None


def value_for(slot_name: str, rng: random.Random) -> str:
    """Draw a deterministic-in-context value for one slot name.

    Unclassifiable names draw from the generic legal-filler pool (see
    FALLBACK_CATEGORY) — a row is never dropped for an unknown name alone.
    """
    if slot_name in EXPLICIT:
        return rng.choice(EXPLICIT[slot_name])
    category = classify(slot_name) or FALLBACK_CATEGORY
    return rng.choice(CATEGORY_POOL[category])


def pick_values(body: str) -> tuple[dict[str, str], list[str]]:
    """Pick a value for every placeholder in ``body``.

    Returns ``(values, fallback_names)``: ``values`` maps slot name → value
    for every placeholder; ``fallback_names`` lists names that had no category
    rule and drew a generic legal filler (surfaced for export audit). Seeded
    by the body's sha256 so the same body always yields the same fill.
    """
    names = sorted(set(SLOT_RE.findall(body)))
    rng = random.Random(int(hashlib.sha256(body.encode("utf-8")).hexdigest()[:16], 16))
    values: dict[str, str] = {}
    fallback: list[str] = []
    for name in names:
        values[name] = value_for(name, rng)
        if name not in EXPLICIT and classify(name) is None:
            fallback.append(name)
    return values, fallback


def instantiate(body: str) -> tuple[str, dict[str, str], list[str]]:
    """Fill every placeholder in ``body``; returns (filled, values, fallback).

    No ``{{...}}`` placeholder remains in ``filled``. ``fallback`` lists names
    that drew generic legal fillers (audit signal, not an error).
    """
    values, fallback = pick_values(body)

    def _sub(m: re.Match) -> str:
        return values[m.group(1)]

    filled = SLOT_RE.sub(_sub, body)
    return filled, values, fallback


def synth_task_desc(contract_type: str | None, scenario: str | None,
                    stance: str | None) -> str:
    """Deterministically synthesize a drafting request from artifact metadata."""
    zh = CONTRACT_TYPE_ZH.get(contract_type or "", contract_type or "合同")
    task = f"请起草一份{zh}"
    if scenario:
        task += f"（业务场景：{scenario}）"
    stance_zh = STANCE_ZH.get(stance or "")
    if stance_zh:
        task += f"，{stance_zh}"
    task += "，条款结构完整、用语规范、符合中国法律。"
    return task
