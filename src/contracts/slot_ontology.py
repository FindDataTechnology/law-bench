"""Slot ontology for contract clauses.

A *slot* is a ``{{name}}`` placeholder. The corpus uses ~7600 distinct slot
names, but only ~270 high-frequency *concepts* (address, phone, name, agent,
legal_rep, bank, account, seal, sign, delivery_date, ...), each with systematic
role-prefix variants (``party_a_address`` / ``seller_address`` / ``buyer_address``
/ ``lessor_address`` ...).

This module is the single source of truth for the canonical concept names, the
variant aliases that map to them, and a slot instruction (label / description /
example / required) for each. It powers two things:

1. **Normalization on write** - :func:`canonicalize_slot` rewrites a variant
   slot name to its canonical form so the corpus stays name-consistent (no
   ``{{seller_name}}`` vs ``{{party_a}}`` for the same concept).
2. **Instruction coverage** - :func:`instruction_for_slot` returns an
   instruction for any known slot, so the coherence gate's "every slot must be
   instructed" check passes for real contracts.

The 12 core slots (``REQUIRED_SLOTS``) keep the hand-written instructions from
:mod:`src.contracts.slots`; extended concepts carry registry instructions here.
The long tail of single-occurrence slots is intentionally not covered - if such
a slot appears without a clause-declared instruction, the coherence gate
surfaces it as data debt.
"""

from __future__ import annotations

import re

from src.contracts.slots import (
    default_slot_instructions,
    latin_to_chinese_map,
    required_slots_for_type,
    REQUIRED_SLOTS,
)

_SLOT_RE = re.compile(r"\{\{(\w+)\}\}")

# ---------------------------------------------------------------------------
# Concept registry
# ---------------------------------------------------------------------------
# Each entry: canonical_name -> {label, description, example, required, aliases}
# `aliases` lists other slot names (role-prefixed or synonym) that map here.
# Role-prefixed variants (seller_X, buyer_X, lessor_X, ...) are ALSO resolved by
# the role-alias table below, so they need not be enumerated per concept.

_CONCEPTS: dict[str, dict] = {
    # --- party identity (core) ---
    "party_a": {"label": "甲方名称", "description": "合同甲方（通常为标的提供方/服务方）的全称或姓名", "example": "北京甲科技有限公司", "required": True,
                "aliases": ["甲方名称", "出卖人", "卖方", "甲方"]},
    "party_b": {"label": "乙方名称", "description": "合同乙方的全称或姓名", "example": "北京乙贸易有限公司", "required": True,
                "aliases": ["乙方名称", "买受人", "买方", "乙方"]},
    # --- party contact / identity details (role-prefixed: party_a_address etc.) ---
    "address": {"label": "联系地址", "description": "当事人的联系地址或住所地", "example": "北京市朝阳区xx路xx号", "required": False, "aliases": []},
    "phone": {"label": "联系电话", "description": "当事人的联系电话", "example": "010-12345678", "required": False, "aliases": ["telephone", "tel", "mobile", "contact_phone"]},
    "email": {"label": "电子邮箱", "description": "当事人的电子邮箱", "example": "contact@example.com", "required": False, "aliases": ["e_mail", "mail"]},
    "zip": {"label": "邮政编码", "description": "当事人的邮政编码", "example": "100000", "required": False, "aliases": ["postal_code", "postcode", "zip_code"]},
    "contact": {"label": "联系方式", "description": "当事人的联系方式", "example": "010-12345678", "required": False, "aliases": ["contact_info", "contact_method"]},
    "agent": {"label": "委托代理人", "description": "当事人的委托代理人姓名", "example": "王某某", "required": False, "aliases": ["authorized_agent", "representative_agent", "agent_name"]},
    "legal_rep": {"label": "法定代表人", "description": "当事人的法定代表人姓名", "example": "李某某", "required": False, "aliases": ["legal_representative", "rep", "representative", "legal_person"]},
    "bank": {"label": "开户银行", "description": "当事人的开户银行名称", "example": "中国工商银行北京xx支行", "required": False, "aliases": ["bank_name", "opening_bank"]},
    "account": {"label": "银行账号", "description": "当事人的银行账号", "example": "6222xxxxxxxxxxxx", "required": False, "aliases": ["account_number", "account_name", "bank_account"]},
    "credit_code": {"label": "统一社会信用代码", "description": "当事人的统一社会信用代码/工商登记注册号", "example": "91110000XXXXXXXXXX", "required": False, "aliases": ["credit_code_no", "social_credit_code", "tax_id", "tax_number"]},
    "id_number": {"label": "证件号码", "description": "当事人的身份证件号码", "example": "110101199001011234", "required": False, "aliases": ["id", "id_no", "identity_number"]},
    "id_type": {"label": "证件类型", "description": "当事人的证件类型", "example": "居民身份证", "required": False, "aliases": []},
    "seal": {"label": "印章", "description": "当事人盖章/公章", "example": "（公章）", "required": False, "aliases": ["seal_name"]},
    "sign": {"label": "签字", "description": "当事人签字", "example": "（签字）", "required": False, "aliases": ["signature"]},
    # --- subject / commercial terms ---
    "subject": {"label": "合同标的", "description": "本合同的具体标的、事宜或范围描述", "example": "买卖合同的具体标的与内容", "required": True, "aliases": ["subject_name", "project_name", "target"]},
    "quantity": {"label": "数量", "description": "标的物数量", "example": "100", "required": False, "aliases": ["amount_quantity", "subject_quantity"]},
    "unit_price": {"label": "单价", "description": "标的物单价", "example": "1000", "required": False, "aliases": ["price", "unit_amount"]},
    "total_amount": {"label": "总价款", "description": "标的物总价款（数字）", "example": "100000", "required": False, "aliases": ["total_price", "sum_amount"]},
    "amount": {"label": "价款金额", "description": "合同价款或费用金额（数字）", "example": "100000", "required": True, "aliases": ["price_amount", "fee"]},
    "deposit_amount": {"label": "定金/保证金", "description": "定金或保证金数额", "example": "10000", "required": False, "aliases": ["deposit", "earnest_money", "guarantee_deposit"]},
    "payment_method": {"label": "付款方式", "description": "价款支付方式", "example": "银行转账", "required": False, "aliases": ["pay_method", "payment"]},
    # --- term / delivery ---
    "term_start": {"label": "履行起始日期", "description": "合同履行开始日期", "example": "2026-01-01", "required": True, "aliases": ["start_date", "effective_date"]},
    "term_end": {"label": "履行结束日期", "description": "合同履行结束日期", "example": "2026-12-31", "required": False, "aliases": ["end_date", "expiry_date", "term_end_month"]},
    "delivery_date": {"label": "交付日期", "description": "标的物交付日期", "example": "2026-06-30", "required": False, "aliases": ["deliver_date", "delivery_time"]},
    "delivery_location": {"label": "交付地点", "description": "标的物交付地点", "example": "北京市朝阳区xx仓库", "required": False, "aliases": ["delivery_place", "delivery_point", "deliver_location"]},
    "delivery_method": {"label": "交付方式", "description": "标的物交付方式", "example": "汽运", "required": False, "aliases": ["deliver_method"]},
    # --- breach / dispute ---
    "penalty": {"label": "违约金", "description": "违约金数额或计算方式", "example": "合同价款的10%", "required": False, "aliases": ["penalty_amount", "liquidated_damages", "breach_penalty"]},
    "penalty_rate": {"label": "违约金比例", "description": "违约金比例", "example": "10%", "required": False, "aliases": ["breach_ratio", "penalty_ratio"]},
    "jurisdiction": {"label": "争议解决方式", "description": "争议解决方式及管辖/仲裁机构", "example": "提交原告所在地人民法院诉讼解决", "required": False, "aliases": ["dispute_resolution_method", "dispute_resolution"]},
    "arbitration_commission": {"label": "仲裁委员会", "description": "约定的仲裁委员会名称", "example": "北京仲裁委员会", "required": False, "aliases": ["arbitration", "arb_commission"]},
    # --- signing ---
    "sign_date": {"label": "签署日期", "description": "合同签署日期", "example": "2026-01-01", "required": True, "aliases": ["sign_date_a", "sign_date_b", "signing_date", "date"]},
    "sign_location": {"label": "签署地点", "description": "合同签署地点", "example": "北京市朝阳区", "required": False, "aliases": ["sign_place", "signing_location"]},
    "sign_month": {"label": "签署月份", "description": "合同签署月份", "example": "1", "required": False, "aliases": []},
    "sign_day": {"label": "签署日", "description": "合同签署日（日）", "example": "15", "required": False, "aliases": []},
    "contract_copies": {"label": "合同份数", "description": "合同一式几份", "example": "一式两份", "required": False, "aliases": ["copies", "copy_count", "contract_copy"]},
    "quality_standard": {"label": "质量标准", "description": "标的物质量标准", "example": "符合国家标准GB/T xxx", "required": False, "aliases": ["quality", "quality_requirement"]},
}

# --- role prefix synonyms -> canonical party_a / party_b ----------------------
# Applied to role-prefixed compound slots, e.g. seller_address -> party_a_address
# for sale. A role maps to party_a or party_b per contract type; types not listed
# fall back to the generic ROLE_TO_PARTY map (seller/lessor/licensor/employer/
# principal -> party_a; buyer/lessee/licensee/employee -> party_b).
_ROLE_TO_PARTY_A = {"seller", "出卖人", "卖方", "供货", "供货方", "订货", "收购", "销售",
                    "lessor", "出租人", "licensor", "许可方", "employer", "用人单位", "甲方",
                    "principal", "委托人", "bailor", "寄存人", "consignor", "发货人",
                    "licensor_a", "seller_a", "a"}
_ROLE_TO_PARTY_B = {"buyer", "买受人", "买方", "lessee", "承租人", "licensee", "被许可方",
                    "employee", "劳动者", "乙方", "agent", "受托人", "bailee", "保管人",
                    "consignee", "收货人", "buyer_b", "b", "licensee_b"}

_ROLE_PREFIXES = sorted(
    set(_ROLE_TO_PARTY_A) | set(_ROLE_TO_PARTY_B)
    | {"party_a", "party_b", "party_c", "party_d", "seller_a", "seller_b", "buyer_a", "buyer_b"},
    key=len, reverse=True,
)


def _strip_role(slot: str) -> tuple[str | None, str]:
    """Return (role, rest) if slot is role-prefixed, else (None, slot)."""
    for r in _ROLE_PREFIXES:
        if slot == r:
            return r, ""
        if slot.startswith(r + "_"):
            return r, slot[len(r) + 1:]
    return None, slot


def _role_to_canonical(role: str | None, contract_type: str | None) -> str | None:
    if role is None:
        return None
    if role in ("party_a", "seller_a"):
        return "party_a"
    if role in ("party_b", "buyer_b"):
        return "party_b"
    if role in _ROLE_TO_PARTY_A:
        return "party_a"
    if role in _ROLE_TO_PARTY_B:
        return "party_b"
    return None


# Stems that mean "the party's name" -> resolve to the bare party slot.
_NAME_STEMS = {"name", "names", "full_name", "company_name", "unit_name", "entity_name"}


def _canonical_concept(rest: str) -> str | None:
    """Map a concept stem (after role stripped) to its canonical concept name."""
    if rest in _CONCEPTS:
        return rest
    for canon, meta in _CONCEPTS.items():
        if rest in meta.get("aliases", []):
            return canon
    return None


def canonicalize_slot(slot: str, contract_type: str | None = None) -> str:
    """Rewrite a variant slot name to its canonical form.

    Examples (sale): ``seller_name`` -> ``party_a``, ``buyer_address`` ->
    ``party_b_address``, ``legal_representative`` -> ``legal_rep``,
    ``party_a_legal_representative`` -> ``party_a_legal_rep``,
    ``party_a_tax_id`` -> ``party_a_credit_code``. Unknown slots are returned
    unchanged.
    """
    s = slot.strip()
    if s in REQUIRED_SLOTS:
        return s
    # full-form (non-role) synonym: legal_representative -> legal_rep
    for canon, meta in _CONCEPTS.items():
        if s in meta.get("aliases", []):
            return canon
    if s in _CONCEPTS:
        return s
    # role-prefixed compound: seller_address, party_a_phone, party_a_tax_id
    role, rest = _strip_role(s)
    if role is not None and rest:
        canon_role = _role_to_canonical(role, contract_type)
        if canon_role is None:
            return s  # unknown role - leave unchanged
        if rest in _NAME_STEMS:
            return canon_role  # party_a_name -> party_a
        concept = _canonical_concept(rest)
        if concept:
            return f"{canon_role}_{concept}"
    return s


def instruction_for_slot(slot: str, contract_type: str | None = None) -> dict | None:
    """Return a slot instruction dict for ``slot`` (canonicalized), or None.

    Returns the **Latin canonical** name so DB writes and the coherence gate
    stay name-consistent. The Chinese display render is a separate output step
    (:func:`render_body_chinese` / :func:`render_instructions_chinese`).
    """
    canon = canonicalize_slot(slot, contract_type)
    # core slots: defer to the hand-written default instructions
    core = {i["name"]: i for i in default_slot_instructions("")}
    if canon in core:
        return dict(core[canon])
    if canon in _CONCEPTS:
        m = _CONCEPTS[canon]
        return {"name": canon, "label": m["label"], "description": m["description"],
                "example": m["example"], "required": m["required"]}
    # role-prefixed concept (party_a_address): instruction from the concept stem
    role, rest = _strip_role(canon)
    if rest and rest in _CONCEPTS:
        m = _CONCEPTS[rest]
        side = _role_to_canonical(role, contract_type)
        label = f"{'甲方' if side == 'party_a' else '乙方'}{m['label']}" if side else m["label"]
        return {"name": canon, "label": label, "description": m["description"],
                "example": m["example"], "required": m["required"]}
    return None


def normalize_body_slots(body: str, contract_type: str | None = None) -> str:
    """Rewrite every ``{{slot}}`` in ``body`` to its canonical form."""
    if not body:
        return body
    return _SLOT_RE.sub(lambda m: "{{" + canonicalize_slot(m.group(1), contract_type) + "}}", body)


def normalize_instruction_names(instructions: list[dict], contract_type: str | None = None) -> list[dict]:
    """Rewrite each instruction's ``name`` to its canonical slot name (keeps labels)."""
    out = []
    for ins in instructions or []:
        canon = canonicalize_slot(ins.get("name", ""), contract_type)
        out.append({**ins, "name": canon})
    return out


# ---------------------------------------------------------------------------
# Chinese render pass (assembly-time)
# ---------------------------------------------------------------------------
# The DB clause corpus carries Latin canonical slots ({{party_a}}, {{amount}},
# {{party_a_address}}, ...). The user wants every *generated* (assembled)
# contract to carry Chinese slot names. Rather than migrate the corpus, we
# render Latin -> Chinese at assembly time: ``render_body_chinese`` rewrites
# the assembled body, ``render_instructions_chinese`` remaps instruction names
# to match the rendered Chinese tokens so the coherence gate
# (slot name == instruction name) still passes.
#
# Canonicalization stays Latin (so DB writes + variant/role-prefix logic +
# the existing tests are untouched); the Chinese form is a *display render*
# layered on top.

# --- 4th-tier domain glossary + compositional Chinese fallback ----------------
# Concepts (tier 2/3) and per-type manifests (tier 1) cover the high-frequency
# party / commercial / delivery slots. The corpus still carries ~2000 lower-
# frequency domain slots (inspection_days, breach_liability, copies_per_party,
# payment_time, ...). Rather than hand-author each, we translate the atomic
# underscore-separated *parts* (days->天数, payment->付款, penalty->违约金) and
# compose them: inspection_days -> 检验天数, payment_time -> 付款时间. A small
# _LATIN_CN_GLOSSARY overrides the handful of stems whose composition would
# read in the wrong order or has an opaque root (copies_per_party -> 每方份数,
# force_majeure -> 不可抗力). Stems with an unknown part stay Latin (the
# acceptable single-occurrence tail).

_SKIP_PARTS = {
    "", "in", "or", "and", "of", "to", "is", "has", "the", "for", "with",
    "as", "by", "on", "at", "from", "into", "any", "all", "an", "not",
    "a", "b", "c", "d",  # bare role markers (party_a -> party, a)
}

_PARTS_CN: dict[str, str] = {
    # people / roles
    "party": "方", "person": "人", "people": "人员", "payer": "付款方",
    "payee": "收款方", "carrier": "承运人", "buyer": "买方", "seller": "卖方",
    "agent": "代理人", "representative": "代表", "signer": "签署人",
    "guardian": "监护人", "manager": "负责人", "supervisor": "监理",
    "director": "董事", "shareholder": "股东", "employer": "用人单位",
    "employee": "劳动者", "worker": "工人", "witness": "见证人",
    "receiver": "接收人", "sender": "发送人", "consignee": "收货人",
    "inspector": "检验人", "operator": "运营方", "owner": "所有权人",
    "holder": "持有人", "debtor": "债务人", "creditor": "债权人",
    "officer": "官员", "staff": "人员", "legal": "法定", "labor": "劳务",
    # money / commercial
    "amount": "金额", "payment": "付款", "penalty": "违约金", "fee": "费用",
    "fees": "费用", "price": "价格", "cost": "成本", "costs": "费用",
    "expense": "费用", "expenses": "费用", "deposit": "定金", "rent": "租金",
    "tax": "税", "freight": "运费", "charge": "费用", "charges": "费用",
    "salary": "工资", "wages": "工资", "reward": "奖励", "compensation": "补偿",
    "damages": "赔偿金", "investment": "投资", "capital": "资本", "equity": "股权",
    "fund": "资金", "interest": "利息", "principal": "本金", "balance": "余额",
    "invoice": "发票", "subsidy": "补贴", "premium": "保费", "rebate": "返利",
    "refund": "退款", "prepay": "预付", "prepayment": "预付款", "advance": "预付",
    "installment": "分期款", "down": "首", "lump": "一次性", "settlement": "结算",
    "loan": "贷款", "bond": "保证金", "tariff": "关税", "value": "价值",
    # quantities / measures
    "quantity": "数量", "count": "数量", "counts": "数量", "number": "编号",
    "numbers": "编号", "num": "数字", "numeric": "数字", "unit": "单位",
    "rate": "费率", "rates": "费率", "ratio": "比例", "ratios": "比例",
    "percent": "百分比", "percentage": "百分比", "proportion": "比例",
    "share": "份额", "shares": "份额", "total": "总", "sum": "合计",
    "area": "面积", "areas": "面积", "volume": "体积", "weight": "重量",
    "capacity": "容量", "scale": "规模", "size": "规模", "measurement": "计量",
    "mileage": "里程", "distance": "距离", "height": "高度", "width": "宽度",
    "length": "长度", "depth": "深度", "page": "页", "pages": "页数",
    "pct": "比例",
    # time / dates
    "date": "日期", "dates": "日期", "day": "日", "days": "天数",
    "month": "月", "months": "月数", "year": "年", "years": "年数",
    "term": "期限", "terms": "约定", "period": "期", "periods": "期",
    "start": "起始", "end": "结束", "begin": "开始", "finish": "完成",
    "time": "时间", "hour": "小时", "hours": "小时", "minute": "分钟",
    "minutes": "分钟", "deadline": "期限", "schedule": "进度",
    "schedules": "进度", "duration": "期间", "cycle": "周期",
    "delivery": "交付", "acceptance": "验收", "completion": "竣工",
    "inspection": "检验", "inspections": "检验", "review": "审查",
    "reviews": "审查", "audit": "审计", "verify": "核实",
    "notice": "通知", "notices": "通知", "notify": "通知", "cure": "催告",
    "grace": "宽限", "delay": "延误", "delays": "延误", "overdue": "逾期",
    "late": "逾期", "early": "提前", "renewal": "续期", "renew": "续签",
    "expiration": "届满", "expiry": "届满", "termination": "终止",
    "cancel": "取消", "effective": "生效", "valid": "有效", "validity": "有效期",
    "reply": "答复", "response": "响应", "responses": "响应", "confirm": "确认",
    "approval": "批准", "approve": "批准", "consent": "同意", "application": "申请",
    # subject / goods / works
    "subject": "标的", "goods": "货物", "product": "产品", "products": "产品",
    "material": "材料", "materials": "材料", "equipment": "设备", "device": "设备",
    "vehicle": "车辆", "cargo": "货物", "item": "项目", "items": "项目",
    "content": "内容", "contents": "内容", "service": "服务", "services": "服务",
    "work": "工程", "works": "工程", "project": "项目", "projects": "项目",
    "business": "业务", "land": "土地", "property": "物业", "building": "建筑",
    "buildings": "建筑", "premises": "房屋", "room": "房间", "plant": "厂房",
    "warehouse": "仓库", "brand": "品牌", "model": "型号", "specification": "规格",
    "spec": "规格", "specs": "规格", "type": "类型", "types": "类型",
    "category": "类别", "categories": "类别", "grade": "等级", "class": "类别",
    "variety": "品种", "species": "品种", "origin": "产地", "source": "来源",
    "sources": "来源", "quality": "质量", "standard": "标准", "standards": "标准",
    "requirements": "要求", "requirement": "要求", "technology": "技术",
    "technical": "技术", "process": "工艺", "processing": "加工",
    "packaging": "包装", "warranty": "质保", "transport": "运输",
    # places / locations
    "location": "地点", "locations": "地点", "place": "地点", "address": "地址",
    "site": "现场", "station": "站", "stations": "站", "port": "港口",
    "ports": "港口", "departure": "出发", "arrival": "到达", "destination": "目的地",
    "boundary": "边界", "boundaries": "边界", "province": "省", "city": "市",
    "district": "区", "county": "县", "region": "地区", "territory": "区域",
    "scope": "范围", "scopes": "范围", "route": "路线",
    # legal / dispute / authority
    "jurisdiction": "管辖", "court": "法院", "courts": "法院", "litigation": "诉讼",
    "arbitration": "仲裁", "mediation": "调解", "dispute": "争议", "disputes": "争议",
    "breach": "违约", "default": "违约", "liability": "责任", "liabilities": "责任",
    "obligation": "义务", "obligations": "义务", "duty": "义务", "duties": "义务",
    "right": "权利", "rights": "权利", "remedy": "救济", "waiver": "豁免",
    "license": "许可证", "licenses": "许可证", "permit": "许可证", "permits": "许可证",
    "certification": "认证", "certificate": "证书", "certificates": "证书",
    "cert": "证", "registration": "登记", "filing": "备案", "record": "记录",
    "records": "记录", "notary": "公证", "institution": "机构", "authority": "机关",
    "authorities": "机关", "commission": "委员会", "committee": "委员会",
    "agency": "机构", "agencies": "机构", "organization": "机构", "org": "机构",
    "consequence": "后果", "consequences": "后果", "resolution": "解决",
    "evidence": "证据", "proof": "证明",
    # documents / signing
    "contract": "合同", "contracts": "合同", "agreement": "协议",
    "agreements": "约定", "clause": "条款", "clauses": "条款", "copy": "份数",
    "copies": "份数", "attachment": "附件", "attachments": "附件", "exhibit": "附件",
    "appendix": "附录", "signature": "签字", "seal": "盖章", "stamp": "盖章",
    "document": "文件", "documents": "文件", "report": "报告", "reports": "报告",
    "list": "清单", "lists": "清单",
    # modifiers / numerals / forms
    "other": "其他", "additional": "补充", "special": "特殊", "first": "第一",
    "second": "第二", "third": "第三", "fourth": "第四", "annual": "年度",
    "monthly": "月度", "daily": "每日", "weekly": "每周", "max": "最高",
    "min": "最低", "upper": "上限", "lower": "下限", "fixed": "固定",
    "actual": "实际", "estimated": "估算", "provisional": "暂定", "original": "原件",
    "big": "大写", "small": "小写", "words": "大写", "cn": "大写", "chinese": "大写",
    "written": "大写", "method": "方式", "methods": "方式", "mode": "方式",
    "option": "选项", "options": "选项", "condition": "条件", "conditions": "条件",
    "purpose": "目的", "use": "使用", "usage": "使用", "change": "变更",
    "changes": "变更", "modification": "修改", "adjustment": "调整",
    "transfer": "转让", "transfers": "转让", "name": "名称", "names": "名称",
    "no": "号码", "code": "代码", "codes": "代码", "id": "证件", "phone": "电话",
    "email": "邮箱", "fax": "传真", "position": "职务", "role": "角色",
    "department": "部门", "nationality": "国籍", "remark": "备注", "remarks": "备注",
    "note": "备注", "notes": "备注", "description": "描述", "detail": "明细",
    "details": "明细", "opinion": "意见", "form": "形式", "forms": "形式",
    "plan": "计划", "plans": "计划", "status": "状态", "result": "结果",
    "results": "结果", "level": "等级", "phase": "阶段", "stage": "阶段",
    "group": "组", "batch": "批次", "contact": "联系", "confidential": "保密",
    "info": "信息",
    # --- extended domain parts (close the surviving-Latin tail) ---
    # people / roles
    "sign": "签署", "rep": "代表人", "bank": "银行", "account": "账户",
    "pay": "支付", "receive": "收取", "provide": "提供", "obtain": "获取",
    "provider": "提供方", "bearer": "承担方", "company": "公司", "student": "学生",
    "vessel": "船舶", "regulator": "监管", "manufacturer": "制造商",
    "guardian": "监护人", "office": "办事处",
    # money / commercial
    "storage": "存储", "insurance": "保险", "credit": "信用", "guarantee": "保证",
    "revenue": "收入", "profit": "利润", "asset": "资产", "return": "退还",
    # quantities / measures
    "threshold": "阈值", "frequency": "频次", "meter": "仪表", "floor": "楼层",
    "density": "密度", "mu": "亩", "plot": "地块", "pool": "池",
    # time / process
    "loading": "装载", "conclusion": "竣工", "preparation": "准备", "voyage": "航次",
    "outbound": "出库", "rework": "返工", "terminate": "终止", "move": "搬入",
    "failure": "故障", "handling": "处理",
    # subject / goods / works
    "data": "数据", "grain": "粮食", "ticket": "票据", "waybill": "运单",
    "package": "包装", "quarantine": "检疫", "facility": "设施", "defect": "缺陷",
    "production": "生产", "design": "设计", "construction": "施工",
    "improvement": "改造", "disposal": "处置", "maintenance": "维护",
    "operation": "运营", "energy": "能源", "cloud": "云", "infrastructure": "基础设施",
    # places / locations
    "physical": "实物", "ground": "地面", "parking": "停车", "local": "当地",
    "reg": "登记", "south": "南", "east": "东", "west": "西", "north": "北",
    # legal / dispute / authority
    "objection": "异议", "risk": "风险", "grounds": "理由", "responsibility": "责任",
    "restricted": "限制", "restrictions": "限制", "ownership": "所有权",
    "limit": "限额", "cap": "上限", "provision": "提供", "franchise": "特许",
    "unified": "统一", "social": "社会", "permission": "许可", "complaint": "投诉",
    "ip": "知识产权",
    # modifiers / forms
    "per": "每", "each": "每", "free": "免费", "final": "最终", "base": "基本",
    "estimate": "估算", "word": "大写", "accommodation": "住宿", "nights": "晚",
    "guide": "导游", "pricing": "定价", "arrangement": "安排", "training": "培训",
    "bidding": "招标", "sub": "分", "tech": "技术", "safety": "安全",
    "calculation": "计算", "target": "目标", "text": "文本", "exception": "例外",
    "basis": "依据", "saving": "节能", "agree": "同意", "allow": "允许",
    "remaining": "剩余", "loss": "损失", "zipcode": "邮编", "postal": "邮政",
    "repair": "维修", "performance": "性能",
    # --- 2nd extension: medium-frequency parts still blocking composition ---
    "card": "卡", "support": "支持", "update": "更新", "access": "访问",
    "availability": "可用性", "distribution": "分配", "recovery": "回收",
    "registered": "注册", "procedure": "程序", "matters": "事项",
    "communication": "通讯", "issuer": "签发方", "parties": "各方",
    "inspect": "检验", "confidentiality": "保密性", "damage": "损害",
    "directors": "董事", "billing": "账单", "funding": "资金",
    "accuracy": "准确性", "completeness": "完整性", "algorithm": "算法",
    "fix": "修复", "revoke": "撤销", "hotel": "酒店", "flight": "航班",
    "train": "列车", "attraction": "景点", "lien": "留置",
    "milestone": "里程碑", "subcontracting": "分包", "allowed": "允许",
    "express": "快递", "perform": "履行", "cases": "情形",
    # --- 3rd extension: the actual high-occurrence blocking parts ---
    # people / roles / parties
    "government": "政府", "user": "用户", "recipient": "受款方",
    "belonging": "归属", "hold": "持有", "mortgagee": "抵押权人",
    "insurer": "保险人", "handler": "操作员", "students": "学生",
    "maker": "决策人", "members": "成员", "appointer": "委派人",
    "supervisors": "监理方", "leader": "负责人", "receiving": "受方",
    # money / commercial / energy
    "electricity": "电", "heat": "供暖", "steam": "蒸汽", "water": "水",
    "gas": "燃气", "carbon": "碳", "pv": "光伏", "supply": "供应",
    "liquidated": "违约", "capitalized": "资本化", "sharing": "分担",
    "visa": "签证", "reduction": "减少", "times": "次数", "benefit": "收益",
    "transaction": "交易", "mortgaged": "抵押", "escrow": "共管",
    "reserve": "准备金", "dividend": "分红", "valuation": "估值",
    "money": "资金", "receivables": "应收款", "post": "投后",
    "subsidy_dup": "补贴", "talent": "人才",
    # quantities / measures / attributes
    "measure": "措施", "measures": "措施", "valuable": "贵重",
    "basic": "基本", "net": "净", "intensity": "强度", "forest": "林地",
    "install": "安装", "multiplier": "倍数", "threshold_dup": "阈值",
    "single": "单次", "full": "满", "load": "载", "less": "减",
    "fluctuation": "波动", "range": "区间", "inventory": "库存",
    "exemption": "免除", "correction": "整改", "progress": "进度",
    "ton": "吨", "tonnage": "吨位", "draft": "吃水", "displacement": "排量",
    "engine": "发动机", "vin": "车架号", "box": "箱", "coverage": "覆盖",
    "extra": "额外", "inner": "内部", "above": "地上", "underground": "地下",
    "avg": "平均", "coefficient": "系数", "baseline": "基准",
    # time / process / state
    "before": "前", "after": "后", "effect": "生效", "subsequent": "后续",
    "birth": "出生", "winter": "冬季", "cancellation": "取消",
    "handover": "交接", "survival": "成活", "drawing": "图纸",
    "am": "上午", "pm": "下午", "prior": "事先", "execution": "执行",
    "paid": "已付", "included": "含", "online": "线上", "classroom": "课堂",
    "theory": "理论", "driving": "驾驶", "simulation": "模拟",
    "probation": "试用", "leave": "请假", "out": "出", "trial": "试",
    "correct": "整改", "settle": "结算", "extend": "延期",
    "reduction_dup": "减少",
    # subject / goods / works / places
    "leased": "租赁", "decoration": "装修", "green": "绿化",
    "installation": "安装", "facility_dup": "设施", "mortgage": "抵押",
    "chemicals": "化学品", "gift": "赠品", "waste": "废物",
    "ship": "船", "car": "汽车", "railway": "铁路", "sea": "海运",
    "river": "水运", "discharging": "卸货", "discharge": "卸货",
    "despatch": "速遣", "demurrage": "滞期", "inbound": "入库",
    "outbound_dup": "出库", "designated": "指定", "exclusive": "独家",
    "layout": "布局", "orientation": "朝向", "sublease": "转租",
    "disposal_dup": "处置", "center": "中心", "grid": "并网",
    "hotline": "热线", "road": "道路", "structure": "结构",
    "garbage": "垃圾", "survey": "勘察", "function": "功能",
    "enterprise": "企业", "commercial": "商业", "tenant": "承租人",
    "landlord": "出租人", "approval": "批准", "government_dup": "政府",
    "nominal": "名义", "purchase": "购买", "waterproof": "防水",
    "qualification": "资质", "workload": "工作量", "currency": "币种",
    "symbol": "符号", "hatch": "舱", "flag": "船旗", "empty": "空载",
    "gross": "毛", "crane": "吊机", "entrustment": "委托",
    "unqualified": "不合格", "plate": "牌", "passport": "护照",
    "adult": "成人", "child": "儿童", "meal": "餐", "trip": "行程",
    "traveling": "旅行", "tour": "旅游",
    # legal / dispute / authority / docs
    "supervision": "监督", "punishment": "处罚", "supplementary": "补充",
    "unauthorized": "未授权", "violation": "违规", "subcontract": "分包",
    "whistleblower": "举报", "decision": "决策", "assets": "资产",
    "title": "权属", "dedicated": "专用", "line": "线路",
    "reason": "原因", "alt": "备用", "amt": "金额", "color": "颜色",
    "interior": "内饰", "calc": "计算", "defective": "不合格",
    "need": "需", "needs": "需", "care": "照护", "success": "成功",
    "dispose": "处分", "read": "抄表", "add": "加", "body": "机构",
    "law": "法律", "authorization": "授权", "regulation": "法规",
    "telephone": "电话", "proprietary": "专有", "resource": "资源",
    "corporate": "公司", "logo": "标识", "mobile": "手机",
    "patent": "专利", "trademark": "商标", "rectification": "整改",
    "telegram": "电报", "bearing": "承担", "instruction": "指令",
    "board": "董事会", "it": "信息", "professional": "专业",
    "contingency": "应急", "authorized": "授权", "emergency": "应急",
    "history": "病史", "gender": "性别", "priority": "优先",
    "scheme": "方案", "evaluation": "评估", "dividend_dup": "分红",
    "admin": "配套", "assets_dup": "资产",
    # modifiers / forms / misc
    "division": "划分", "entity": "主体", "unable": "不能",
    "three": "三", "stop": "停工", "entrust": "委托", "same": "同",
    "om": "运维", "adjust": "调整", "channel": "渠道",
    "output": "产出", "normal": "正常", "minimum": "最低",
    "difference": "差", "approving": "审批", "leader_dup": "负责人",
    "criteria": "标准", "deliver": "交付", "prepare": "准备",
    "stages": "阶段", "held": "持有", "currency_dup": "币种",
    "manual": "手动", "include": "包含", "exclude": "不含",
    "meal_dup": "餐", "working": "工作", "enrollment": "招生",
    "soil": "土壤", "increase": "增加", "km": "公里",
    "new": "新", "key": "关键", "dept": "部门", "vertical": "竖向",
    "top": "顶", "bottom": "底", "planar": "平面", "diff": "差",
    "existing": "现有", "confirmation": "确认", "pollution": "污染",
    "industry": "行业", "classification": "分类", "next": "下次",
    "interval": "间隔", "afforestation": "造林", "insured": "承保",
    "far": "容积", "build": "建", "invest": "投资",
    # --- 4th extension: the residual tail (occ>=2 + meaningful singles) ---
    "submit": "提交", "medical": "医疗", "accessories": "配件",
    "packing": "包装", "marketing": "营销", "dispatch": "调度",
    "hot": "热水", "supplier": "供应商", "procurement": "采购",
    "rule": "规则", "rules": "规则", "core": "核心",
    "limitations": "限制", "partial": "部分", "cny": "人民币",
    "connection": "并网", "installed": "装机", "guaranteed": "保证",
    "point": "点", "usable": "可用", "issue": "问题",
    "assistance": "协助", "includes": "含", "major": "重大",
    "way": "方式", "apply": "申请", "repayment": "还款",
    "crops": "作物", "machinery": "机械", "consumption": "消耗",
    "budget": "预算", "allowance": "津贴", "related": "相关",
    "predicted": "预测", "blood": "血型", "allergy": "过敏",
    "policy": "政策", "high": "高", "low": "低",
    "tuition": "学费", "pickup": "接送", "icp": "备案",
    "course": "课程", "relationship": "关系", "relation": "关系",
    "school": "学校", "teacher": "教师", "consultant": "顾问",
    "session": "次", "weighting": "权重", "acceptor": "承兑人",
    "article": "条", "bid": "竞价", "preparer": "编制人",
    "renovation": "装修", "media": "媒体", "rush": "加急",
    "broadcast": "广播", "discount": "折扣", "alternative": "备选",
    "wisdom": "智慧", "url": "网址", "lumpsum": "一次性",
    "formula": "公式", "retention": "保留", "addr": "地址",
    "array": "阵列", "gov": "政府", "edu": "教育",
    "outlender": "外借方", "lawyer": "律师", "drafter": "起草人",
    "buyout": "回购", "buyback": "回购", "recourse": "追索",
    "underlying": "基础", "formation": "成立", "contribution": "出资",
    "table": "表", "voting": "表决", "exercised": "行使",
    "subscription": "认购", "investor": "投资人", "incentive": "激励",
    "repurchase": "回购", "cash": "现金", "annualized": "年化",
    "listing": "挂牌", "system": "制度", "grantback": "回授",
    "planned": "计划", "planning": "规划", "object": "标的物",
    "belong": "归属", "beneficiary": "受益人", "liquidation": "清算",
    "deduction": "扣除", "handback": "交回", "customer": "客户",
    "circumstance": "情形", "takeover": "接管", "derivative": "衍生",
    "four": "四", "two": "二", "one": "一", "nature": "性质",
    "facilities": "设施", "main": "主", "occupied": "已占用",
    "leveling": "平整", "retransfer": "再转让", "financing": "融资",
    "exercising": "行使", "waiving": "放弃", "cooperator": "合作方",
    "obligor": "义务人", "reforestation": "再造林",
    # --- 5th extension: final 16 survivors ---
    "lease": "租赁", "reasons": "原因", "excl": "不含", "incl": "含",
    "pre": "预", "sale": "售", "co2": "二氧化碳",
}

_LATIN_CN_GLOSSARY: dict[str, str] = {
    # composition reads in the wrong order, or has an opaque root.
    "copies_per_party": "每方份数",
    "each_party_copies": "每方份数",
    "force_majeure": "不可抗力",
    "force_majeure_days": "不可抗力期限",
    "force_majeure_notice_days": "不可抗力通知期限",
    "force_majeure_notify_days": "不可抗力通知期限",
    "force_majeure_report_days": "不可抗力报告期限",
    "force_majeure_proof_days": "不可抗力举证期限",
    "force_majeure_duration_days": "不可抗力持续天数",
    "force_majeure_notice_hours": "不可抗力通知小时",
    "force_majeure_handling": "不可抗力处理",
    "days_before_start_1": "行前1天", "days_before_start_2": "行前2天",
    "days_before_start_3": "行前3天", "days_before_start_4": "行前4天",
    "days_before_start_5": "行前5天", "days_before_start_6": "行前6天",
    "sign_party_a": "甲方签署", "sign_party_b": "乙方签署",
    "legal_representative": "法定代表人",
    "advance_notice_days": "提前通知期限",
    "advance_booking_days": "提前预订天数",
    # opaque compounds: numeric day-tiers + legal/odd tokens
    "cooling_off_days": "冷静期天数",
    "river2_fee": "水运2费用",
    "penalty_rate_14to7": "14至7天违约金费率",
    "penalty_rate_6to4": "6至4天违约金费率",
    "penalty_rate_6to4_outbound": "6至4天出库违约金费率",
    "penalty_rate_3to1": "3至1天违约金费率",
    "penalty_rate_3to1_outbound": "3至1天出库违约金费率",
    "penalty_rate_29to15": "29至15天违约金费率",
}


def _role_prefixed(cn: str, role: str | None, contract_type: str | None) -> str:
    """Prefix 甲方/乙方 when ``role`` maps to a known side, else return bare."""
    side = _role_to_canonical(role, contract_type) if role else None
    if side == "party_a":
        return f"甲方{cn}"
    if side == "party_b":
        return f"乙方{cn}"
    return cn


def _compose_cn(stem: str) -> str:
    """Compose a Chinese name from a stem's underscore-separated parts.

    Returns ``""`` when any alpha part is unknown so the caller leaves the
    slot Latin rather than emit a mixed-script name. Digits stay literal.
    """
    out: list[str] = []
    for p in stem.split("_"):
        if p in _SKIP_PARTS:
            continue
        if p in _PARTS_CN:
            out.append(_PARTS_CN[p])
        elif p.isdigit():
            out.append(p)
        else:
            return ""
    return "".join(out)


def _chinese_name(canon: str, contract_type: str | None, l2c: dict[str, str]) -> str:
    """Map a Latin canonical slot to its Chinese display name.

    Precedence (highest -> lowest): per-type manifest ``latin`` bridge (per-type
    names like 借款金额) -> role-prefixed attribute via the concept label
    (甲方联系地址) -> bare concept label (联系地址) -> curated domain glossary
    -> compositional fallback over underscore-separated parts
    (inspection_days -> 检验天数, party_a_duty -> 甲方义务). Returns ``canon``
    unchanged when no Chinese mapping is known (unknown single-occurrence slots
    stay Latin).
    """
    if canon in l2c:
        return l2c[canon]
    # role-prefixed attribute: party_a_address -> 甲方联系地址
    role, rest = _strip_role(canon)
    if rest and rest in _CONCEPTS:
        m = _CONCEPTS[rest]
        side = _role_to_canonical(role, contract_type)
        if side == "party_a":
            return f"甲方{m['label']}"
        if side == "party_b":
            return f"乙方{m['label']}"
        return m["label"]
    # bare concept: address -> 联系地址, legal_rep -> 法定代表人
    if canon in _CONCEPTS:
        return _CONCEPTS[canon]["label"]
    # curated domain glossary (4th tier): wrong-order composition or opaque root.
    if canon in _LATIN_CN_GLOSSARY:
        return _LATIN_CN_GLOSSARY[canon]
    if rest and rest in _LATIN_CN_GLOSSARY:
        return _role_prefixed(_LATIN_CN_GLOSSARY[rest], role, contract_type)
    # compositional fallback (5th tier): translate underscore parts and join
    # (inspection_days -> 检验天数, party_a_duty -> 甲方义务). A bare role label
    # (employer, consignee, buyer, seller: `rest` is empty after _strip_role)
    # composes from the canon itself and is returned un-prefixed — the label
    # alone is the party name (用人单位, not 甲方用人单位).
    stem = rest or canon
    composed = _compose_cn(stem)
    if composed:
        return _role_prefixed(composed, role, contract_type) if rest else composed
    return canon


def render_body_chinese(body: str, contract_type: str | None = None) -> str:
    """Render every ``{{slot}}`` in ``body`` to its Chinese display name.

    Applied at assembly time (after the body is assembled from clause bodies)
    so the final generated contract carries Chinese slot names. Each slot is
    canonicalized first (variant/role-prefix -> Latin concept), then mapped to
    the per-type Chinese name. Slots with no Chinese mapping (unknown
    single-occurrence slots) are left unchanged so their clause-declared
    instructions still match.
    """
    if not body:
        return body
    l2c = latin_to_chinese_map(contract_type) if contract_type else {}
    return _SLOT_RE.sub(
        lambda m: "{{" + _chinese_name(canonicalize_slot(m.group(1), contract_type), contract_type, l2c) + "}}",
        body,
    )


def render_instructions_chinese(
    instructions: list[dict], contract_type: str | None = None
) -> list[dict]:
    """Remap each instruction's ``name`` to its Chinese display name.

    Mirrors :func:`render_body_chinese` so the instruction names match the
    Chinese body slots after the render pass. Instructions whose name has no
    Chinese mapping keep their original (Latin) name so they still match any
    body slot that was likewise left unchanged. Dedupes by the rendered name
    (two Latin concepts may collapse to one Chinese name within a type).
    """
    if not instructions:
        return instructions
    l2c = latin_to_chinese_map(contract_type) if contract_type else {}
    out: list[dict] = []
    seen: set[str] = set()
    for ins in instructions:
        canon = canonicalize_slot(ins.get("name", ""), contract_type)
        cn = _chinese_name(canon, contract_type, l2c)
        if cn in seen:
            continue
        seen.add(cn)
        out.append({**ins, "name": cn})
    return out


__all__ = [
    "canonicalize_slot",
    "instruction_for_slot",
    "normalize_body_slots",
    "normalize_instruction_names",
    "render_body_chinese",
    "render_instructions_chinese",
]


