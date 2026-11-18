#!/usr/bin/env python3
"""Register curated legal skills into the AI Gateway & Registry skills catalog.

Mirrors register_mcp_gateway.py: stdlib-only, Logto M2M client_credentials auth,
actions register/show/remove. Skills are URL references to upstream SKILL.md files;
the gateway parses the agentskills.io frontmatter, discovers companion resources
(references/scripts/templates) and detects upstream content drift by hash.

Usage (on cheap1, from the gateway compose env):
    export LOGTO_M2M_APP_ID=$(grep '^LOGTO_M2M_CLIENT_ID=' /opt/mcp-gateway-registry/.env | cut -d= -f2-)
    export LOGTO_M2M_CLIENT_SECRET=$(grep '^LOGTO_M2M_CLIENT_SECRET=' /opt/mcp-gateway-registry/.env | cut -d= -f2-)
    python3 register_skills_gateway.py show
    python3 register_skills_gateway.py register                  # all curated skills
    python3 register_skills_gateway.py register --repo legalskill/legalskill
    python3 register_skills_gateway.py register --visibility group
    python3 register_skills_gateway.py register --dry-run
    python3 register_skills_gateway.py remove <skill-name>
    python3 register_skills_gateway.py remove --repo THUYRan/Legal-Skills-Chinese
    python3 register_skills_gateway.py remove --visibility group

Credentials: LOGTO_M2M_APP_ID / LOGTO_M2M_CLIENT_SECRET from the environment, or
parsed from /root/.mcp_logto_creds when present (america-era path). The M2M
management calls additionally require the gateway's `idp_m2m_clients` Mongo
mapping for the M2M client (see deploy/cheap-box/README.md). No secret material
lives in this file or the repo.

Catalog curation (license-driven visibility):
  - permissive-license skills (CC BY-SA, MIT, repo-level MIT) -> public
  - skills whose SKILL.md declares CC-BY-NC / CC-BY-NC-SA, or whose repo declares
    CC BY-NC-ND -> group-restricted to registry-admins; public promotion requires
    the author's written authorization; NC-ND skills are served verbatim (no
    modified distribution) (see deploy/cheap-box/mcp-gateway-skills.md).
"""

import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

GATEWAY = os.environ.get("MCP_GATEWAY_URL", "https://mcp.finddatatech.cloud")
RESOURCE = os.environ.get("MCP_GATEWAY_RESOURCE", "https://mcp.finddatatech.cloud/api")
TOKEN_URL = os.environ.get("LOGTO_TOKEN_URL", "https://auth.finddatatech.cloud/oidc/token")
CREDS_FILE = "/root/.mcp_logto_creds"

# Generated from the three source repos (see change catalog-legal-skills-in-gateway);
# originally 85 skills = 66 public + 19 CC-BY-NC(-SA) restricted, pinned 2026-08-30.
# 2026-09-18 restore on the cheap gateway (change restore-legal-skills-catalog):
#   - 'contract-review' -> 'pa1nrui1-contract-review' (name held on the gateway by an
#     unrelated paste.rs-based entry; collision guard must not overwrite it)
#   - 'industry-research-report' -> 'legal-industry-report' (upstream dir renamed)
#   - excluded: 'paddle-ocr' (upstream merged into legal-ocr), 'weekly-legal-briefing'
#     (deleted upstream)
#   - extended with 38 THUYRan/Legal-Skills-Chinese skills (CC BY-NC-ND, all group)
#     -> 121 skills = 65 public + 56 CC-BY-NC(-SA/ND) restricted.
# 57 Chinese-named skills registered under translated English slugs (metadata.name_zh
# keeps the original) because the gateway requires lowercase-alphanumeric names.
CATALOG = [
 {
  "name": "legalskill-legal-consultation",
  "description": "为律师、法务提供法条检索、法规查询、案例研究、判例检索、指导案例查找、司法解释解读、合同审查与专业研判，为普通公众提供法律咨询、案件分析和维权指导。适用于普通用户描述日常纠纷、追问法律后果或寻求行动策略，即使用户未使用法律术语，常见说法如欠钱不还、被起诉、打官司、合同违约、离婚、抚养权、抚养费、探视权、家暴、彩礼、遗产继承、劳动纠纷、工伤、加班费、年终奖、竞业限制、违法解除、违法辞退、裁员、被辞退、经济补偿、年休假、交通事故、车祸、租房押金不退、消费者投诉、公司股权争议、合伙纠纷、股权代持、股东知情权、拆迁补偿、行政处罚、行政复议、知识产权侵权、商标侵权、专利纠纷、著作权纠纷、商业秘密、不正当竞争、房屋买卖纠纷、物业纠纷、邻里纠纷、名誉权侵权、隐私泄露、网络暴力、医疗事故、医疗纠纷、保险合同纠纷、人身损害、被人打了、食品安全、产品责任等，或问\"怎么办\"\"能不能告\"\"会不会坐牢\"\"能赔多少\"\"胜算大吗\"\"有什么风险\"\"要赔多少钱\"\"会不会被拘留\"\"会不会判刑\"\"能不能缓刑\"\"怎么应诉\"\"如何反诉\"\"如何上诉\"\"打官司要多久\"\"证据不足怎么办\"\"对方不履行怎么办\"\"律师费多少\"\"仲裁和诉讼哪个好\"\"要不要请律师\"\"自己辩护行不行\"\"调解书有法律效力吗\"\"强制执行怎么申请\"\"被列入失信名单怎么办\"\"被当成老赖怎么办\"\"对方转移财产怎么办\"\"判决后不执行怎么办\"\"取保候审要什么条件\"\"能不能不起诉\"等。也覆盖律师、法务的高频专业任务：按案号查案例、按裁判要旨找类案、法条沿革追溯、法条效力核实、合同条款分析与漏洞审查、违约赔偿计算、劳动关系认定、竞业限制审查、裁判口径对比与各地裁判标准差异分析、合规审查、诉讼风险评估、仲裁策略设计、调解方案拟订、强制执行与财产保全分析、刑事报案可行性初评、证据链梳理、庭审准备提纲、再审申请、执行异议、破产债权申报等。用户上传合同、判决书、起诉状、答辩状、仲裁申请书、执行申请书、律师函等法律文件时自动触发分析，支持多轮追问与策略细化。不适用于出具正式法律意见书、代写法律文书、代理出庭、学术写作或非中文法律检索。",
  "license": "CC BY-SA 4.0",
  "skill_md_url": "https://raw.githubusercontent.com/legalskill/legalskill/main/skill/legalskill-legal-consultation/SKILL.md",
  "repository_url": "https://github.com/legalskill/legalskill",
  "version": None,
  "visibility": "public",
  "allowed_groups": [],
  "tags": [
   "legal",
   "chinese-law",
   "legalskill"
  ],
  "metadata": {
   "author": "LegalSkill 社区（律锥）",
   "source_repo": "legalskill/legalskill",
   "skill_dir": "legalskill-legal-consultation"
  }
 },
 {
  "name": "tencent-ima-copilot-legal-consultation",
  "description": "以资深律师分阶段办案思维，结合 RAG 法律知识库检索，为用户提供法律问题初步诊断与行动策略。当用户描述法律纠纷、咨询\"怎么办\"\"能不能告\"\"会不会坐牢\"、询问欠钱不还/被起诉/打官司/维权/赔偿/工伤/交通事故/租房纠纷/遗产继承/离婚/合同纠纷/消费者权益/公司劳动争议等场景，或要求分析合同/侵权/劳动/家事/行政/公司股权问题，或上传法律文件时触发。不适用于出具正式法律意见书、代写文书或替代律师出庭。支持分层精读策略、多轮换词搜索、结构化引用清单（含效力状态标注）、快速/专家双模式。内置反幻觉保障机制（绝对溯源+时效性验证+幻觉自检清单），确保法条引用可溯源、案例裁判经核验、失效法条自动标注。",
  "license": "CC BY-SA 4.0",
  "skill_md_url": "https://raw.githubusercontent.com/legalskill/legalskill/main/skill/tencent-ima-copilot-legal-consultation/SKILL.md",
  "repository_url": "https://github.com/legalskill/legalskill",
  "version": None,
  "visibility": "public",
  "allowed_groups": [],
  "tags": [
   "legal",
   "chinese-law",
   "legalskill"
  ],
  "metadata": {
   "author": "LegalSkill 社区（律锥）",
   "source_repo": "legalskill/legalskill",
   "skill_dir": "tencent-ima-copilot-legal-consultation"
  }
 },
 {
  "name": "case-dashboard",
  "description": "律师案件看板。本地零依赖看板服务（案件总览、任务三态看板、期限预警、进度写回）＋周研判分析。当用户说\"打开看板/dashboard/案件面板/看下案件进度/给我案件周报研判\"时使用。案件状态写入与上下文管理用 case-progress（/progress 命令也归它）。不要用于：案件实体分析、文书起草、法律研究。",
  "license": "CC-BY-NC",
  "skill_md_url": "https://raw.githubusercontent.com/cat-xierluo/legal-skills/main/skills/case-dashboard/SKILL.md",
  "repository_url": "https://github.com/cat-xierluo/legal-skills",
  "version": "0.1.0",
  "visibility": "group",
  "allowed_groups": [
   "registry-admins"
  ],
  "tags": [
   "legal",
   "chinese-law",
   "cat-xierluo"
  ],
  "metadata": {
   "author": "杨卫薪（执业律师）",
   "source_repo": "cat-xierluo/legal-skills",
   "skill_dir": "case-dashboard"
  }
 },
 {
  "name": "case-progress",
  "description": "案件进度与状态台账管理。案件 case.yaml 的唯一写入引擎（新增任务、推进任务、登记期限、更新案件阶段、校验、存量迁移），Agent 会话的进度加载与写回契约，以及案件进度监控对账。当用户或 Agent 需要\"更新案件进度/推进任务/登记期限/更新案件阶段/同步案件状态/校验或迁移案件数据/查看案件结构化状态\"时使用。不要用于：看板展示与周研判（用 case-dashboard）、案件建档初始化（用 new-case）。",
  "license": "CC-BY-NC",
  "skill_md_url": "https://raw.githubusercontent.com/cat-xierluo/legal-skills/main/skills/case-progress/SKILL.md",
  "repository_url": "https://github.com/cat-xierluo/legal-skills",
  "version": "0.1.0",
  "visibility": "group",
  "allowed_groups": [
   "registry-admins"
  ],
  "tags": [
   "legal",
   "chinese-law",
   "cat-xierluo"
  ],
  "metadata": {
   "author": "杨卫薪（执业律师）",
   "source_repo": "cat-xierluo/legal-skills",
   "skill_dir": "case-progress"
  }
 },
 {
  "name": "code2patent",
  "description": "从已开发代码项目中提取技术实现证据，围绕候选专利方案生成算法/软件类说明书式技术交底书，并以“权利要求布局卡 → 发明专利初稿”两步法继续生成接近可申报版的中国发明专利起草材料。触发场景包括：读取代码仓库后撰写技术交底书、将人工总结的专利方案映射到具体实现、从代码中挖掘可专利技术方案、为专利代理师准备权利要求布局和发明专利初稿。",
  "license": "CC-BY-NC",
  "skill_md_url": "https://raw.githubusercontent.com/cat-xierluo/legal-skills/main/skills/code2patent/SKILL.md",
  "repository_url": "https://github.com/cat-xierluo/legal-skills",
  "version": "1.6.0",
  "visibility": "group",
  "allowed_groups": [
   "registry-admins"
  ],
  "tags": [
   "legal",
   "chinese-law",
   "cat-xierluo"
  ],
  "metadata": {
   "author": "杨卫薪（执业律师）",
   "source_repo": "cat-xierluo/legal-skills",
   "skill_dir": "code2patent"
  }
 },
 {
  "name": "contract-copilot",
  "description": "合同起草与审查助手。基于分层分析与四步流程，输出可执行的风险清单、起草骨架、修改建议、推荐措辞和审查意见书，支持批注与修订两种文档处理方式。用户通过飞书或其他 IM 对话发送合同文件并要求审查或起草时，也应使用本 skill，并优先沿原会话回传修订版和审查报告。",
  "license": "CC-BY-NC",
  "skill_md_url": "https://raw.githubusercontent.com/cat-xierluo/legal-skills/main/skills/contract-copilot/SKILL.md",
  "repository_url": "https://github.com/cat-xierluo/legal-skills",
  "version": "1.6.3",
  "visibility": "group",
  "allowed_groups": [
   "registry-admins"
  ],
  "tags": [
   "legal",
   "chinese-law",
   "cat-xierluo"
  ],
  "metadata": {
   "author": "杨卫薪（执业律师）",
   "source_repo": "cat-xierluo/legal-skills",
   "skill_dir": "contract-copilot"
  }
 },
 {
  "name": "court-sms",
  "description": "本技能应在用户收到法院短信（文书送达、立案通知、开庭提醒等）时使用，自动提取案号、当事人、下载链接，下载文书并归档到对应案件目录。会落盘敏感诉讼数据到本地，请确认目标位置私密。",
  "license": "MIT",
  "skill_md_url": "https://raw.githubusercontent.com/cat-xierluo/legal-skills/main/skills/court-sms/SKILL.md",
  "repository_url": "https://github.com/cat-xierluo/legal-skills",
  "version": "1.5.1",
  "visibility": "public",
  "allowed_groups": [],
  "tags": [
   "legal",
   "chinese-law",
   "cat-xierluo"
  ],
  "metadata": {
   "author": "杨卫薪（执业律师）",
   "source_repo": "cat-xierluo/legal-skills",
   "skill_dir": "court-sms"
  }
 },
 {
  "name": "elements-complaint-generator",
  "description": "Use when converting 律师已写好的常规起诉状(md/docx)或对话描述为符合最高法 67 类官方要素式起诉状示范文本格式的 Word 文档(法〔2025〕82 号,2025-07-14 全国推广)。适用于民间借贷/离婚纠纷/机动车事故/劳动争议等所有 67 类民事/商事/行政/知产案由的要素式起诉状/答辩状生成。",
  "license": "MIT",
  "skill_md_url": "https://raw.githubusercontent.com/cat-xierluo/legal-skills/main/skills/elements-complaint-generator/SKILL.md",
  "repository_url": "https://github.com/cat-xierluo/legal-skills",
  "version": "0.13.4",
  "visibility": "public",
  "allowed_groups": [],
  "tags": [
   "legal",
   "chinese-law",
   "cat-xierluo"
  ],
  "metadata": {
   "author": "杨卫薪（执业律师）",
   "source_repo": "cat-xierluo/legal-skills",
   "skill_dir": "elements-complaint-generator"
  }
 },
 {
  "name": "legal-industry-report",
  "description": "输入一个行业（可选区域与业务方向），输出一份可交付的精排 A4 PDF 行业法律调研报告。设计风格采用律所蓝皮书体例（深蓝主色 + 白色页面 + 衬线大标题 + 顶部品牌带），内置 report-profile.md 个性化配置（律所抬头 / 配色 / 主办律师 / 封面变体 / 联系方式），数据源来自企查查 MCP（企业名录 + 司法/经营风险标签）+ 网络检索（政策文件、产业园名录、产业链结构）。建议在用户说\"做一份行业调研报告 / 见客户前先了解下 XX 行业 / 这周要去 XX 行业跑客户帮我准备背景资料 / 开拓新行业之前知己知彼\"时使用；不要用于：客户名下的具体法律意见、对单一企业的尽调（用 opc-legal-counsel）、按周推送的对外研报（用 weekly-legal-briefing）。",
  "license": "CC-BY-NC",
  "skill_md_url": "https://raw.githubusercontent.com/cat-xierluo/legal-skills/main/skills/legal-industry-report/SKILL.md",
  "repository_url": "https://github.com/cat-xierluo/legal-skills",
  "version": "0.7.0",
  "visibility": "group",
  "allowed_groups": [
   "registry-admins"
  ],
  "tags": [
   "legal",
   "chinese-law",
   "cat-xierluo"
  ],
  "metadata": {
   "author": "杨卫薪（执业律师）",
   "source_repo": "cat-xierluo/legal-skills",
   "skill_dir": "industry-research-report"
  }
 },
 {
  "name": "legal-case-analysis",
  "description": "本技能应在用户需要基于案件材料、咨询材料、合同资料、证据材料或检索结果进行法律分析、案件研判、风险评估、诉讼策略、刑事案件研判与审查起诉分析、非诉风险判断、客户说明或法律分析报告时使用。它是法律任务的前置分析引擎，不要求每次都生成正式报告。不要用于：单纯 OCR、单纯法条案例检索、单纯 Word 排版转换、仅需包装服务方案且无需新增法律分析的文档生成。",
  "license": "CC-BY-NC",
  "skill_md_url": "https://raw.githubusercontent.com/cat-xierluo/legal-skills/main/skills/legal-case-analysis/SKILL.md",
  "repository_url": "https://github.com/cat-xierluo/legal-skills",
  "version": "1.0.0",
  "visibility": "group",
  "allowed_groups": [
   "registry-admins"
  ],
  "tags": [
   "legal",
   "chinese-law",
   "cat-xierluo"
  ],
  "metadata": {
   "author": "杨卫薪（执业律师）",
   "source_repo": "cat-xierluo/legal-skills",
   "skill_dir": "legal-case-analysis"
  }
 },
 {
  "name": "legal-harness-init",
  "description": "面向法律工作者初始化或增量治理 AGENTS.md/CLAUDE.md：识别当前 AI harness，区分用户级、项目级和团队级指令，生成最小法律安全基线，安全合并受管区块，并在新会话中验证权限、保密、信息缺口和回溯行为。用户明确提到法律工作且要配置 harness、AGENTS.md、CLAUDE.md、agent 协作规则或 AI 使用基线时使用。不要用于合同审查、案件分析、文书起草、项目脚手架或 Skill 开发。",
  "license": "MIT",
  "skill_md_url": "https://raw.githubusercontent.com/cat-xierluo/legal-skills/main/skills/legal-harness-init/SKILL.md",
  "repository_url": "https://github.com/cat-xierluo/legal-skills",
  "version": "0.5.2",
  "visibility": "public",
  "allowed_groups": [],
  "tags": [
   "legal",
   "chinese-law",
   "cat-xierluo"
  ],
  "metadata": {
   "author": "杨卫薪（执业律师）",
   "source_repo": "cat-xierluo/legal-skills",
   "skill_dir": "legal-harness-init"
  }
 },
 {
  "name": "legal-ocr",
  "description": "本技能应在用户需要 OCR、扫描识别、图片文字识别、文档识别，或将 PDF、图片、Office 文档、URL 转换为 Markdown 时使用。检测到法律材料时可进行保守的法律术语与文书结构优化。不要用于法律事实判断、补写缺失内容、语义改写、印章深度识别或图表实体分析。",
  "license": "MIT",
  "skill_md_url": "https://raw.githubusercontent.com/cat-xierluo/legal-skills/main/skills/legal-ocr/SKILL.md",
  "repository_url": "https://github.com/cat-xierluo/legal-skills",
  "version": "1.5.0",
  "visibility": "public",
  "allowed_groups": [],
  "tags": [
   "legal",
   "chinese-law",
   "cat-xierluo"
  ],
  "metadata": {
   "author": "杨卫薪（执业律师）",
   "source_repo": "cat-xierluo/legal-skills",
   "skill_dir": "legal-ocr"
  }
 },
 {
  "name": "legal-proposal-generator",
  "description": "根据案件材料或沟通记录生成各类法律服务文档（诉讼方案、咨询报告、非诉方案、建议书、沟通报告、结案汇报、案件分析摘要等）。本技能应在用户需要将案件材料、咨询记录或沟通内容整理为专业法律文档时使用。",
  "license": "CC-BY-NC",
  "skill_md_url": "https://raw.githubusercontent.com/cat-xierluo/legal-skills/main/skills/legal-proposal-generator/SKILL.md",
  "repository_url": "https://github.com/cat-xierluo/legal-skills",
  "version": "0.3.2",
  "visibility": "group",
  "allowed_groups": [
   "registry-admins"
  ],
  "tags": [
   "legal",
   "chinese-law",
   "cat-xierluo"
  ],
  "metadata": {
   "author": "杨卫薪（执业律师）",
   "source_repo": "cat-xierluo/legal-skills",
   "skill_dir": "legal-proposal-generator"
  }
 },
 {
  "name": "legal-qa-extractor",
  "description": "从律师与客户沟通记录中提取有价值的法律问答对，生成结构化知识库内容。本技能应在用户需要整理客户咨询记录、从对话中提取可复用法律知识、创建问答知识库、或准备内容营销素材时使用。支持严格客户信息脱敏处理。",
  "license": "CC-BY-NC",
  "skill_md_url": "https://raw.githubusercontent.com/cat-xierluo/legal-skills/main/skills/legal-qa-extractor/SKILL.md",
  "repository_url": "https://github.com/cat-xierluo/legal-skills",
  "version": "1.0.0",
  "visibility": "group",
  "allowed_groups": [
   "registry-admins"
  ],
  "tags": [
   "legal",
   "chinese-law",
   "cat-xierluo"
  ],
  "metadata": {
   "author": "杨卫薪（执业律师）",
   "source_repo": "cat-xierluo/legal-skills",
   "skill_dir": "legal-qa-extractor"
  }
 },
 {
  "name": "legal-text-format",
  "description": "将法律文本（法律条文或法律案例）转换为规范的 Markdown 格式，删除推广冗余信息。本技能应在用户需要处理法律条文（如民法典、刑法等）、整理法律案例（如最高法典型案例、裁判文书等）、或从粘贴文本中格式化法律文档时使用。注意：本技能只负责格式化和内容清理，不包含内容抓取能力。内容获取应由其他 skill（如 wechat-article-fetch）完成，AI 会自动判断技能协作顺序。内置 archive 机制，所有结果自包含存储在 skill 目录内。",
  "license": "CC-BY-NC",
  "skill_md_url": "https://raw.githubusercontent.com/cat-xierluo/legal-skills/main/skills/legal-text-format/SKILL.md",
  "repository_url": "https://github.com/cat-xierluo/legal-skills",
  "version": "1.2.1",
  "visibility": "group",
  "allowed_groups": [
   "registry-admins"
  ],
  "tags": [
   "legal",
   "chinese-law",
   "cat-xierluo"
  ],
  "metadata": {
   "author": "杨卫薪（执业律师）",
   "source_repo": "cat-xierluo/legal-skills",
   "skill_dir": "legal-text-format"
  }
 },
 {
  "name": "legal-visualization",
  "description": "Legal Visualization。面向法律业务场景的法律图解与图表生成技能；当用户要求把案件材料、合同材料、合规事项、交易安排、证据链、诉讼流程、时间轴、法律关系、客户汇报、法律服务方案或律师团队工作整理成关系图、流程图、时间轴、证据链、风险图、路线图、PNG/SVG/PDF/.drawio 时使用；也兼容“法律可视化”“案件事实图”“法律关系图”等说法。先按受众、任务动词和路由规则筛选场景，再生成可交付图片，并保留 draw.io 源文件作为可编辑底稿。本技能不用于事实核验，也不替代法律结论判断。",
  "license": "CC-BY-NC",
  "skill_md_url": "https://raw.githubusercontent.com/cat-xierluo/legal-skills/main/skills/legal-visualization/SKILL.md",
  "repository_url": "https://github.com/cat-xierluo/legal-skills",
  "version": "0.8.2",
  "visibility": "group",
  "allowed_groups": [
   "registry-admins"
  ],
  "tags": [
   "legal",
   "chinese-law",
   "cat-xierluo"
  ],
  "metadata": {
   "author": "杨卫薪（执业律师）",
   "source_repo": "cat-xierluo/legal-skills",
   "skill_dir": "legal-visualization"
  }
 },
 {
  "name": "litigation-analysis",
  "description": "诉讼分析工具 - 判决书深度分析，生成上诉/再审决策支持",
  "license": "CC-BY-NC",
  "skill_md_url": "https://raw.githubusercontent.com/cat-xierluo/legal-skills/main/skills/litigation-analysis/SKILL.md",
  "repository_url": "https://github.com/cat-xierluo/legal-skills",
  "version": "1.3.2",
  "visibility": "group",
  "allowed_groups": [
   "registry-admins"
  ],
  "tags": [
   "legal",
   "chinese-law",
   "cat-xierluo"
  ],
  "metadata": {
   "author": "杨卫薪（执业律师）",
   "source_repo": "cat-xierluo/legal-skills",
   "skill_dir": "litigation-analysis"
  }
 },
 {
  "name": "new-case",
  "description": "将案件/咨询/商标/专利材料整理成标准化目录结构。支持诉讼案件（12目录）、潜在项目/咨询（2目录）、商标案件（按业务子类型选 2 个模板：注册 7 目录含独立商标注册证/异议复审无效 8 目录含独立商标注册证）、专利案件（按业务子类型选 3 个模板：申请 7 目录/复审无效 8 目录/检索其他 4 目录，目录顺序按项目进展）四种预设。本技能应在用户需要创建新案件、初始化案件目录结构、整理咨询材料、接收商标/专利新业务、或通过参数和自然语言指定案件编号、委托人、案件类型等信息快速创建案件时使用。不要用于：单独生成法律文书、进行法律研究、证据分析等非案件初始化任务。",
  "license": "CC-BY-NC",
  "skill_md_url": "https://raw.githubusercontent.com/cat-xierluo/legal-skills/main/skills/new-case/SKILL.md",
  "repository_url": "https://github.com/cat-xierluo/legal-skills",
  "version": "1.4.0",
  "visibility": "group",
  "allowed_groups": [
   "registry-admins"
  ],
  "tags": [
   "legal",
   "chinese-law",
   "cat-xierluo"
  ],
  "metadata": {
   "author": "杨卫薪（执业律师）",
   "source_repo": "cat-xierluo/legal-skills",
   "skill_dir": "new-case"
  }
 },
 {
  "name": "opc-legal-counsel",
  "description": "面向 OPC（One Person Company，一人公司 / 单人创业者 + AI 协同）和小微企业经营场景的法律业务分诊与判断技能。用户咨询主体选择、公私分离、联合创始人、融资与激励、合同履约、财税风险、AI 产品、数据与知识产权、用工、监管或争议时使用。负责识别主矛盾、联动风险、行动优先级和升级边界；凡涉及现行法条、效力状态、期限、税率、备案名录、地方政策、办理口径或平台规则，生成结构化检索任务并交由可用法律数据库、MCP 或官方来源核验，不以内置知识冒充最新规则。不要用于替代正式法律意见、深度合同批注、诉讼文书、商标申请、专利分析或纯法规检索。",
  "license": "CC-BY-NC",
  "skill_md_url": "https://raw.githubusercontent.com/cat-xierluo/legal-skills/main/skills/opc-legal-counsel/SKILL.md",
  "repository_url": "https://github.com/cat-xierluo/legal-skills",
  "version": "1.0.2",
  "visibility": "group",
  "allowed_groups": [
   "registry-admins"
  ],
  "tags": [
   "legal",
   "chinese-law",
   "cat-xierluo"
  ],
  "metadata": {
   "author": "杨卫薪（执业律师）",
   "source_repo": "cat-xierluo/legal-skills",
   "skill_dir": "opc-legal-counsel"
  }
 },
 {
  "name": "patent-analysis",
  "description": "面向中国发明和实用新型专利的结构化初步分析工具。本技能应在用户需要拆解或解释权利要求、比较专利保护范围、进行产品侵权比对、等同分析、稳定性与无效风险分析、FTO、规避设计、专利价值评估或制作专利分析图表时使用。不要用于：代替专利律师或专利代理师出具正式意见、仅下载/OCR专利、撰写专利申请文件，或在未确认法域与有效权利要求时给出确定性结论；外观设计近似判断需另行采用专门方法并人工复核。",
  "license": "CC-BY-NC",
  "skill_md_url": "https://raw.githubusercontent.com/cat-xierluo/legal-skills/main/skills/patent-analysis/SKILL.md",
  "repository_url": "https://github.com/cat-xierluo/legal-skills",
  "version": "2.2.0",
  "visibility": "group",
  "allowed_groups": [
   "registry-admins"
  ],
  "tags": [
   "legal",
   "chinese-law",
   "cat-xierluo"
  ],
  "metadata": {
   "author": "杨卫薪（执业律师）",
   "source_repo": "cat-xierluo/legal-skills",
   "skill_dir": "patent-analysis"
  }
 },
 {
  "name": "patent-download",
  "description": "专利 PDF 批量下载工具。当用户需要下载专利全文 PDF、查询专利信息、批量导出专利文件时使用。支持多平台（Google Patents 优先），自动处理申请号和公告号格式。",
  "license": "MIT",
  "skill_md_url": "https://raw.githubusercontent.com/cat-xierluo/legal-skills/main/skills/patent-download/SKILL.md",
  "repository_url": "https://github.com/cat-xierluo/legal-skills",
  "version": "2.7.1",
  "visibility": "public",
  "allowed_groups": [],
  "tags": [
   "legal",
   "chinese-law",
   "cat-xierluo"
  ],
  "metadata": {
   "author": "杨卫薪（执业律师）",
   "source_repo": "cat-xierluo/legal-skills",
   "skill_dir": "patent-download"
  }
 },
 {
  "name": "pdf-organizer",
  "description": "当需要整理法律 PDF 时使用：检测文字层，生成页面索引、整理草稿和下游交接文件，按内容拆分、合并或直接重命名 OCR 后双层扫描件并规范命名；可做旋转与倾斜校正，不做 OCR 或压缩。",
  "license": "MIT",
  "skill_md_url": "https://raw.githubusercontent.com/cat-xierluo/legal-skills/main/skills/pdf-organizer/SKILL.md",
  "repository_url": "https://github.com/cat-xierluo/legal-skills",
  "version": "0.5.0",
  "visibility": "public",
  "allowed_groups": [],
  "tags": [
   "legal",
   "chinese-law",
   "cat-xierluo"
  ],
  "metadata": {
   "author": "杨卫薪（执业律师）",
   "source_repo": "cat-xierluo/legal-skills",
   "skill_dir": "pdf-organizer"
  }
 },
 {
  "name": "trademark-assistant",
  "description": "面向中国商标申请的类别规划、可注册性初筛及申请材料准备技能。基于尼斯分类（国际商标分类），引用中国法律法规。本技能应在接到商标咨询、需要结构化输出建议与风险分级、或需要准备申请材料时使用。不要用于：替代正式法律意见、承诺注册成功率、处理复杂商标争议案件。",
  "license": "CC-BY-NC",
  "skill_md_url": "https://raw.githubusercontent.com/cat-xierluo/legal-skills/main/skills/trademark-assistant/SKILL.md",
  "repository_url": "https://github.com/cat-xierluo/legal-skills",
  "version": "1.7.2",
  "visibility": "group",
  "allowed_groups": [
   "registry-admins"
  ],
  "tags": [
   "legal",
   "chinese-law",
   "cat-xierluo"
  ],
  "metadata": {
   "author": "杨卫薪（执业律师）",
   "source_repo": "cat-xierluo/legal-skills",
   "skill_dir": "trademark-assistant"
  }
 },
 {
  "name": "yuandian-law-search",
  "description": "元典检索机制感知型法律研究中间层。本技能应在需要查询中国法律法规或案例，或用户提供案件事实、争议焦点、既有法律分析报告并要求制定检索策略、查找正反类案、生成可追溯检索报告时使用；先做轻量案件研判与查询矩阵，再按向量、关键词和结构化字段调用元典 API 或 MCP。不要用于替代完整证据审查、诉讼方案或正式法律意见。",
  "license": "MIT",
  "skill_md_url": "https://raw.githubusercontent.com/cat-xierluo/legal-skills/main/skills/yuandian-law-search/SKILL.md",
  "repository_url": "https://github.com/cat-xierluo/legal-skills",
  "version": "1.8.9",
  "visibility": "public",
  "allowed_groups": [],
  "tags": [
   "legal",
   "chinese-law",
   "cat-xierluo"
  ],
  "metadata": {
   "author": "杨卫薪（执业律师）",
   "source_repo": "cat-xierluo/legal-skills",
   "skill_dir": "yuandian-law-search"
  }
 },
 {
  "name": "china-legal-skills",
  "description": "Chinese legal workflow skills for lawyers, legal counsel, litigation, criminal defense, labor disputes, bankruptcy, contract review, compliance, legal research, and legal document drafting.",
  "license": "MIT (repo-level)",
  "skill_md_url": "https://raw.githubusercontent.com/pa1nrui1/legal-skills/main/SKILL.md",
  "repository_url": "https://github.com/pa1nrui1/legal-skills",
  "version": None,
  "visibility": "public",
  "allowed_groups": [],
  "tags": [
   "legal",
   "chinese-law",
   "pa1nrui1"
  ],
  "metadata": {
   "author": "潘睿（执业律师）",
   "source_repo": "pa1nrui1/legal-skills",
   "skill_dir": "pa1nrui1-legal-skills"
  }
 },
 {
  "name": "law-to-markdown",
  "description": "将法条/规范文件（.txt/.docx/.pdf）转为 Markdown。适用于用户要求“法条转 markdown”“pdf/docx 转 markdown”。处理 .pdf/.docx 时先检查是否已安装 mineru-ocr skill；未安装先引导安装，安装后优先用 mineru-ocr；仅在用户明确同意时再用本地回退方案。",
  "license": "MIT (repo-level)",
  "skill_md_url": "https://raw.githubusercontent.com/pa1nrui1/legal-skills/main/skills/legal/law-to-markdown/SKILL.md",
  "repository_url": "https://github.com/pa1nrui1/legal-skills",
  "version": None,
  "visibility": "public",
  "allowed_groups": [],
  "tags": [
   "legal",
   "chinese-law",
   "pa1nrui1"
  ],
  "metadata": {
   "author": "潘睿（执业律师）",
   "source_repo": "pa1nrui1/legal-skills",
   "skill_dir": "law-to-markdown"
  }
 },
 {
  "name": "first-instance-criminal-defense",
  "description": "刑事辩护一审阶段工作Skill，覆盖法院审判阶段的委托衔接、补充阅卷、会见、庭前会议、调查取证、非法证据排除、法庭发问质证举证辩论、认罪认罚、庭后工作与上诉评估。当用户提及\"一审阶段\"、\"刑事一审\"、\"开庭辩护\"、\"庭前会议\"、\"非法证据排除\"、\"刑事庭审\"等关键词时触发使用。",
  "license": "MIT (repo-level)",
  "skill_md_url": "https://raw.githubusercontent.com/pa1nrui1/legal-skills/main/skills/legal/%E4%B8%80%E5%AE%A1%E9%98%B6%E6%AE%B5%E8%BE%A9%E6%8A%A4/SKILL.md",
  "repository_url": "https://github.com/pa1nrui1/legal-skills",
  "version": None,
  "visibility": "public",
  "allowed_groups": [],
  "tags": [
   "legal",
   "chinese-law",
   "pa1nrui1"
  ],
  "metadata": {
   "author": "潘睿（执业律师）",
   "source_repo": "pa1nrui1/legal-skills",
   "skill_dir": "一审阶段辩护",
   "name_zh": "一审阶段辩护",
   "registration_note": "gateway requires lowercase-alphanumeric names; Chinese name kept in name_zh"
  }
 },
 {
  "name": "second-instance-criminal-defense",
  "description": "刑事辩护二审阶段工作Skill，覆盖上诉审委托接案、一审材料衔接、阅卷审查、会见策略、争取开庭、书面辩护意见、二审庭审、不开庭审理沟通、裁判分析及发回重审衔接。当用户提及\"二审\"、\"上诉\"、\"抗诉\"、\"争取开庭\"、\"发回重审\"、\"二审辩护\"等关键词时触发使用。",
  "license": "MIT (repo-level)",
  "skill_md_url": "https://raw.githubusercontent.com/pa1nrui1/legal-skills/main/skills/legal/%E4%BA%8C%E5%AE%A1%E9%98%B6%E6%AE%B5%E8%BE%A9%E6%8A%A4/SKILL.md",
  "repository_url": "https://github.com/pa1nrui1/legal-skills",
  "version": None,
  "visibility": "public",
  "allowed_groups": [],
  "tags": [
   "legal",
   "chinese-law",
   "pa1nrui1"
  ],
  "metadata": {
   "author": "潘睿（执业律师）",
   "source_repo": "pa1nrui1/legal-skills",
   "skill_dir": "二审阶段辩护",
   "name_zh": "二审阶段辩护",
   "registration_note": "gateway requires lowercase-alphanumeric names; Chinese name kept in name_zh"
  }
 },
 {
  "name": "product-legal-compliance",
  "description": "中国境内产品法务与产品合规 Skill。用于产品上线、功能合规、默认开启、客户 Logo/客户案例展示、PRD/页面流程/用户协议/隐私政策/帮助中心审查、产品材料合规审查、高合规行业产品深度评估、营销文案产品场景初筛等任务。适用于用户询问“这个功能能不能做”“能不能把客户 logo 放官网”“产品材料是否合法合规”“医疗/金融/教育/AI/平台类产品是否能上线”等问题。",
  "license": "MIT (repo-level)",
  "skill_md_url": "https://raw.githubusercontent.com/pa1nrui1/legal-skills/main/skills/legal/%E4%BA%A7%E5%93%81%E6%B3%95%E5%8A%A1/SKILL.md",
  "repository_url": "https://github.com/pa1nrui1/legal-skills",
  "version": None,
  "visibility": "public",
  "allowed_groups": [],
  "tags": [
   "legal",
   "chinese-law",
   "pa1nrui1"
  ],
  "metadata": {
   "author": "潘睿（执业律师）",
   "source_repo": "pa1nrui1/legal-skills",
   "skill_dir": "产品法务",
   "name_zh": "产品法务",
   "registration_note": "gateway requires lowercase-alphanumeric names; Chinese name kept in name_zh"
  }
 },
 {
  "name": "investigation-stage-criminal-defense",
  "description": "刑事辩护侦查阶段工作Skill，涵盖会见全流程、案件法律分析与量刑预判、批捕时间节点管理、法律文书生成、执业风险防范等完整辩护工作规范",
  "license": "MIT (repo-level)",
  "skill_md_url": "https://raw.githubusercontent.com/pa1nrui1/legal-skills/main/skills/legal/%E4%BE%A6%E6%9F%A5%E9%98%B6%E6%AE%B5%E8%BE%A9%E6%8A%A4/SKILL.md",
  "repository_url": "https://github.com/pa1nrui1/legal-skills",
  "version": "1.0.0",
  "visibility": "public",
  "allowed_groups": [],
  "tags": [
   "legal",
   "chinese-law",
   "pa1nrui1"
  ],
  "metadata": {
   "author": "潘睿（执业律师）",
   "source_repo": "pa1nrui1/legal-skills",
   "skill_dir": "侦查阶段辩护",
   "name_zh": "侦查阶段辩护",
   "registration_note": "gateway requires lowercase-alphanumeric names; Chinese name kept in name_zh"
  }
 },
 {
  "name": "creditors-meeting",
  "description": "系统化支持债权人会议的筹备、召开、表决、纪要全流程工作，覆盖管理人、债权人代理、债务人代理三角色。支持第一次及后续多次债权人会议。当用户发送客户编号并提及\"债权人会议\"、\"召开会议\"、\"准备会议\"、\"会议通知\"、\"会议议程\"、\"会议纪要\"等指令时触发使用。",
  "license": "MIT (repo-level)",
  "skill_md_url": "https://raw.githubusercontent.com/pa1nrui1/legal-skills/main/skills/legal/%E5%80%BA%E6%9D%83%E4%BA%BA%E4%BC%9A%E8%AE%AE/SKILL.md",
  "repository_url": "https://github.com/pa1nrui1/legal-skills",
  "version": "1.0.0",
  "visibility": "public",
  "allowed_groups": [],
  "tags": [
   "legal",
   "chinese-law",
   "pa1nrui1"
  ],
  "metadata": {
   "author": "潘睿（执业律师）",
   "source_repo": "pa1nrui1/legal-skills",
   "skill_dir": "债权人会议",
   "name_zh": "债权人会议",
   "registration_note": "gateway requires lowercase-alphanumeric names; Chinese name kept in name_zh"
  }
 },
 {
  "name": "creditor-claim-filing-review",
  "description": "破产债权管理全流程Skill，覆盖债权申报、审查、编制债权表全流程。适用于管理人（R1）、债权人代理（R2）、债务人代理（R3）三种角色。当用户发送客户编号并提及\"债权申报\"、\"债权审查\"、\"编制债权表\"、\"申报债权\"等指令时触发使用。",
  "license": "MIT (repo-level)",
  "skill_md_url": "https://raw.githubusercontent.com/pa1nrui1/legal-skills/main/skills/legal/%E5%80%BA%E6%9D%83%E7%94%B3%E6%8A%A5%E4%B8%8E%E5%AE%A1%E6%9F%A5/SKILL.md",
  "repository_url": "https://github.com/pa1nrui1/legal-skills",
  "version": None,
  "visibility": "public",
  "allowed_groups": [],
  "tags": [
   "legal",
   "chinese-law",
   "pa1nrui1"
  ],
  "metadata": {
   "author": "潘睿（执业律师）",
   "source_repo": "pa1nrui1/legal-skills",
   "skill_dir": "债权申报与审查",
   "name_zh": "债权申报与审查",
   "registration_note": "gateway requires lowercase-alphanumeric names; Chinese name kept in name_zh"
  }
 },
 {
  "name": "criminal-defense-coordinator",
  "description": "刑事辩护专业流程编排 Skill，负责根据刑事诉讼阶段和特殊标签进行专业路由、 阶段转换提示、关键期限提示和下一步工作建议。当用户提及\"刑事案件\"、 \"刑事辩护\"、\"刑辩\"等关键词，或需要跨阶段协调刑事辩护工作时触发。 事项建档、路径、文件读取、来源披露、OCR 校正和缺口归档由「法律工作总控」统一处理。",
  "license": "MIT (repo-level)",
  "skill_md_url": "https://raw.githubusercontent.com/pa1nrui1/legal-skills/main/skills/legal/%E5%88%91%E4%BA%8B%E8%BE%A9%E6%8A%A4%E6%80%BB%E8%B0%83%E5%BA%A6/SKILL.md",
  "repository_url": "https://github.com/pa1nrui1/legal-skills",
  "version": None,
  "visibility": "public",
  "allowed_groups": [],
  "tags": [
   "legal",
   "chinese-law",
   "pa1nrui1"
  ],
  "metadata": {
   "author": "潘睿（执业律师）",
   "source_repo": "pa1nrui1/legal-skills",
   "skill_dir": "刑事辩护总调度",
   "name_zh": "刑事辩护总调度",
   "registration_note": "gateway requires lowercase-alphanumeric names; Chinese name kept in name_zh"
  }
 },
 {
  "name": "preliminary-legal-analysis",
  "description": "基于\"六来源体系\"、请求权基础6步法与要件审判九步法融合框架，进行系统性法律分析，按总控当前事项记录和复盘台账衔接，生成法律服务建议书Word文档。当用户发送客户编号并提及\"初步法律分析\"、\"法律分析\"、\"请求权分析\"等指令时触发使用。",
  "license": "MIT (repo-level)",
  "skill_md_url": "https://raw.githubusercontent.com/pa1nrui1/legal-skills/main/skills/legal/%E5%88%9D%E6%AD%A5%E6%B3%95%E5%BE%8B%E5%88%86%E6%9E%90/SKILL.md",
  "repository_url": "https://github.com/pa1nrui1/legal-skills",
  "version": None,
  "visibility": "public",
  "allowed_groups": [],
  "tags": [
   "legal",
   "chinese-law",
   "pa1nrui1"
  ],
  "metadata": {
   "author": "潘睿（执业律师）",
   "source_repo": "pa1nrui1/legal-skills",
   "skill_dir": "初步法律分析",
   "name_zh": "初步法律分析",
   "registration_note": "gateway requires lowercase-alphanumeric names; Chinese name kept in name_zh"
  }
 },
 {
  "name": "labor-arbitration-case-management",
  "description": "劳动争议仲裁程序全流程管理Skill，覆盖仲裁前置强制检测、仲裁时效计算、一裁终局自动判断、仲裁申请书/答辩书生成（W/E双角色）、仲裁请求清单、仲裁→诉讼衔接路由（L9五分支）、仲裁策略报告和用人单位仲裁前风险敞口评估。当用户发送客户编号并提及\"仲裁申请\"、\"仲裁答辩\"、\"仲裁策略\"、\"仲裁时效\"、\"公司仲裁风险\"、\"风险敞口\"等指令时触发使用。",
  "license": "MIT (repo-level)",
  "skill_md_url": "https://raw.githubusercontent.com/pa1nrui1/legal-skills/main/skills/legal/%E5%8A%B3%E5%8A%A8%E4%BA%89%E8%AE%AE%E4%BB%B2%E8%A3%81%E7%A8%8B%E5%BA%8F%E7%AE%A1%E7%90%86/SKILL.md",
  "repository_url": "https://github.com/pa1nrui1/legal-skills",
  "version": None,
  "visibility": "public",
  "allowed_groups": [],
  "tags": [
   "legal",
   "chinese-law",
   "pa1nrui1"
  ],
  "metadata": {
   "author": "潘睿（执业律师）",
   "source_repo": "pa1nrui1/legal-skills",
   "skill_dir": "劳动争议仲裁程序管理",
   "name_zh": "劳动争议仲裁程序管理",
   "registration_note": "gateway requires lowercase-alphanumeric names; Chinese name kept in name_zh"
  }
 },
 {
  "name": "labor-dispute-evidence-system",
  "description": "劳动争议案件证据管理专属Skill，覆盖举证责任倒置规则、按12类争议类型自动生成证据收集清单、证据效力三级评估、四类特殊保护自动检测、规章制度合法性审查三要件、劳动者代理证据完整性检查和用人单位争议/合规证据清单。输出举证责任分配表、证据收集清单、特殊保护检测报告、公司端事实与制度证据缺口表。当用户发送客户编号并提及\"举证责任\"、\"劳动争议证据\"、\"证据清单\"、\"特殊保护\"、\"员工手册证据\"、\"公司端证据\"等指令时触发使用。",
  "license": "MIT (repo-level)",
  "skill_md_url": "https://raw.githubusercontent.com/pa1nrui1/legal-skills/main/skills/legal/%E5%8A%B3%E5%8A%A8%E4%BA%89%E8%AE%AE%E8%AF%81%E6%8D%AE%E4%BD%93%E7%B3%BB/SKILL.md",
  "repository_url": "https://github.com/pa1nrui1/legal-skills",
  "version": "1.0.0",
  "visibility": "public",
  "allowed_groups": [],
  "tags": [
   "legal",
   "chinese-law",
   "pa1nrui1"
  ],
  "metadata": {
   "author": "潘睿（执业律师）",
   "source_repo": "pa1nrui1/legal-skills",
   "skill_dir": "劳动争议证据体系",
   "name_zh": "劳动争议证据体系",
   "registration_note": "gateway requires lowercase-alphanumeric names; Chinese name kept in name_zh"
  }
 },
 {
  "name": "labor-dispute-litigation",
  "description": "劳动争议诉讼专业流程编排 Skill。整合17个子Skill：复用14个现有通用Skill + 3个劳动争议专属Skill（劳动争议仲裁程序管理、劳动关系认定与经济补偿计算、劳动争议证据体系）。用于判断劳动争议阶段（协商→调解→仲裁→一审→二审，L0-L15/LM系列）、识别W/E代理角色、区分劳动者代理、用人单位争议代理和用人单位日常劳动合规任务、推荐下一步子Skill、提示关键节点确认和期限；事项建档、路径、文件读取、来源披露、OCR 校正和缺口归档由「法律工作总控」统一处理。",
  "license": "MIT (repo-level)",
  "skill_md_url": "https://raw.githubusercontent.com/pa1nrui1/legal-skills/main/skills/legal/%E5%8A%B3%E5%8A%A8%E4%BA%89%E8%AE%AE%E8%AF%89%E8%AE%BC/SKILL.md",
  "repository_url": "https://github.com/pa1nrui1/legal-skills",
  "version": None,
  "visibility": "public",
  "allowed_groups": [],
  "tags": [
   "legal",
   "chinese-law",
   "pa1nrui1"
  ],
  "metadata": {
   "author": "潘睿（执业律师）",
   "source_repo": "pa1nrui1/legal-skills",
   "skill_dir": "劳动争议诉讼",
   "name_zh": "劳动争议诉讼",
   "registration_note": "gateway requires lowercase-alphanumeric names; Chinese name kept in name_zh"
  }
 },
 {
  "name": "labor-relation-severance-calculator",
  "description": "劳动争议案件核心分析工具，覆盖劳动关系三性从属分析、12类争议自动分类、工时制度定性、工资工时问答、经济补偿计算引擎（N/N+1/2N判断+月工资基数+三层封顶）、加班费三档计算、双倍工资计算。当用户发送客户编号并提及\"劳动关系认定\"、\"经济补偿\"、\"补偿计算\"、\"加班费计算\"、\"工资工时\"、\"发薪日\"、\"特殊工时\"等指令时触发使用。",
  "license": "MIT (repo-level)",
  "skill_md_url": "https://raw.githubusercontent.com/pa1nrui1/legal-skills/main/skills/legal/%E5%8A%B3%E5%8A%A8%E5%85%B3%E7%B3%BB%E8%AE%A4%E5%AE%9A%E4%B8%8E%E7%BB%8F%E6%B5%8E%E8%A1%A5%E5%81%BF%E8%AE%A1%E7%AE%97/SKILL.md",
  "repository_url": "https://github.com/pa1nrui1/legal-skills",
  "version": None,
  "visibility": "public",
  "allowed_groups": [],
  "tags": [
   "legal",
   "chinese-law",
   "pa1nrui1"
  ],
  "metadata": {
   "author": "潘睿（执业律师）",
   "source_repo": "pa1nrui1/legal-skills",
   "skill_dir": "劳动关系认定与经济补偿计算",
   "name_zh": "劳动关系认定与经济补偿计算",
   "registration_note": "gateway requires lowercase-alphanumeric names; Chinese name kept in name_zh"
  }
 },
 {
  "name": "pa1nrui1-contract-review",
  "description": "基于张海燕四步审查法+何力/常金光三观分析法，对合同进行深度审查。支持企业核验、多语言自动检测、Mermaid业务流程图、二段式审核意见、合同概览、客户可读合同编号、业务摘要、22类合同专项审查、续约提醒和 Word 修订模式审核红线稿。飞书正式交付物必须包含问题卡片列表和业务流程图；用户选择修订模式时，以原合同为只读来源，先生成 redline-plan.json，再运行 scripts/redline/apply_redline_plan.py 生成带真实修订痕迹和批注的 Word 审核修订稿，并完成红线 QA。其他记录保存为本地 Markdown。",
  "license": "MIT (repo-level)",
  "skill_md_url": "https://raw.githubusercontent.com/pa1nrui1/legal-skills/main/skills/legal/%E5%90%88%E5%90%8C%E5%AE%A1%E6%9F%A5/SKILL.md",
  "repository_url": "https://github.com/pa1nrui1/legal-skills",
  "version": None,
  "visibility": "public",
  "allowed_groups": [],
  "tags": [
   "legal",
   "chinese-law",
   "pa1nrui1"
  ],
  "metadata": {
   "author": "潘睿（执业律师）",
   "source_repo": "pa1nrui1/legal-skills",
   "skill_dir": "合同审查",
   "name_zh": "合同审查",
   "registration_note": "gateway requires lowercase-alphanumeric names; Chinese name kept in name_zh. Renamed from 'contract-review' (2026-09-18): the cheap gateway already holds a same-name entry (owner aloadtree, paste.rs upstream) that the collision guard must not overwrite"
  }
 },
 {
  "name": "contract-drafting",
  "description": "合同起草、生成合同、拟定协议、写合同、根据交易安排形成合同文本、多轮修订和最终版归档的唯一入口。基于三观四步法与用户可选配置的本地合同模板库，支持有模板时定制化起草、无模板时独立起草；输出合同草案，并同步生成客户可读合同编号、合同概览、业务摘要、版本记录、修订历史和续约提醒信息。",
  "license": "MIT (repo-level)",
  "skill_md_url": "https://raw.githubusercontent.com/pa1nrui1/legal-skills/main/skills/legal/%E5%90%88%E5%90%8C%E8%B5%B7%E8%8D%89/SKILL.md",
  "repository_url": "https://github.com/pa1nrui1/legal-skills",
  "version": None,
  "visibility": "public",
  "allowed_groups": [],
  "tags": [
   "legal",
   "chinese-law",
   "pa1nrui1"
  ],
  "metadata": {
   "author": "潘睿（执业律师）",
   "source_repo": "pa1nrui1/legal-skills",
   "skill_dir": "合同起草",
   "name_zh": "合同起草",
   "registration_note": "gateway requires lowercase-alphanumeric names; Chinese name kept in name_zh"
  }
 },
 {
  "name": "engagement-contract-management",
  "description": "协助律师完成委托合同签订和案件归档。签订阶段覆盖收费方式确认、授权范围确认、全套委托文书生成；归档阶段覆盖诉讼跟踪记录表生成和客户档案更新。当用户发送客户编号并提及\"签订合同\"、\"案件建档\"等指令时触发使用。",
  "license": "MIT (repo-level)",
  "skill_md_url": "https://raw.githubusercontent.com/pa1nrui1/legal-skills/main/skills/legal/%E5%A7%94%E6%89%98%E5%90%88%E5%90%8C%E7%AE%A1%E7%90%86/SKILL.md",
  "repository_url": "https://github.com/pa1nrui1/legal-skills",
  "version": None,
  "visibility": "public",
  "allowed_groups": [],
  "tags": [
   "legal",
   "chinese-law",
   "pa1nrui1"
  ],
  "metadata": {
   "author": "潘睿（执业律师）",
   "source_repo": "pa1nrui1/legal-skills",
   "skill_dir": "委托合同管理",
   "name_zh": "委托合同管理",
   "registration_note": "gateway requires lowercase-alphanumeric names; Chinese name kept in name_zh"
  }
 },
 {
  "name": "prosecution-review-stage-defense",
  "description": "覆盖审查起诉阶段辩护律师全部工作职责的专业技能模块，包括阅卷权、会见权、调查取证权、 证据核实权、意见表达权、非法证据排除申请权、控告申诉权等七类核心权利的行使指导， 以及法律文书生成、量刑预判、与检察机关沟通策略等全流程工作规范。",
  "license": "MIT (repo-level)",
  "skill_md_url": "https://raw.githubusercontent.com/pa1nrui1/legal-skills/main/skills/legal/%E5%AE%A1%E6%9F%A5%E8%B5%B7%E8%AF%89%E9%98%B6%E6%AE%B5%E8%BE%A9%E6%8A%A4/SKILL.md",
  "repository_url": "https://github.com/pa1nrui1/legal-skills",
  "version": None,
  "visibility": "public",
  "allowed_groups": [],
  "tags": [
   "legal",
   "chinese-law",
   "pa1nrui1"
  ],
  "metadata": {
   "author": "潘睿（执业律师）",
   "source_repo": "pa1nrui1/legal-skills",
   "skill_dir": "审查起诉阶段辩护",
   "name_zh": "审查起诉阶段辩护",
   "registration_note": "gateway requires lowercase-alphanumeric names; Chinese name kept in name_zh"
  }
 },
 {
  "name": "trial-report-generator",
  "description": "从已有案件材料（起诉状、答辩状、庭审纪要、法律分析等）中提取要素，生成法院内部审理报告Word文书初稿。按总控当前事项记录和复盘台账衔接。当用户发送客户编号并提及\"审理报告\"等指令时触发使用。",
  "license": "MIT (repo-level)",
  "skill_md_url": "https://raw.githubusercontent.com/pa1nrui1/legal-skills/main/skills/legal/%E5%AE%A1%E7%90%86%E6%8A%A5%E5%91%8A/SKILL.md",
  "repository_url": "https://github.com/pa1nrui1/legal-skills",
  "version": None,
  "visibility": "public",
  "allowed_groups": [],
  "tags": [
   "legal",
   "chinese-law",
   "pa1nrui1"
  ],
  "metadata": {
   "author": "潘睿（执业律师）",
   "source_repo": "pa1nrui1/legal-skills",
   "skill_dir": "审理报告",
   "name_zh": "审理报告",
   "registration_note": "gateway requires lowercase-alphanumeric names; Chinese name kept in name_zh"
  }
 },
 {
  "name": "advertising-compliance-review",
  "description": "广告合规审核技能，用于审核广告素材是否符合中国广告法及相关法规。适用场景：(1) 用户提交广告文案、广告素材要求合规审核时；(2) 用户提到\"广告审核\"\"广告合规\"\"广告法审查\"等关键词时；(3) 用户要求检查广告内容是否存在违法违规风险时；(4) 用户提交房地产、食品、医疗、药品、互联网等行业广告要求专项审核时。审核依据涵盖《广告法》《反不正当竞争法》及行业专项法规。",
  "license": "MIT (repo-level)",
  "skill_md_url": "https://raw.githubusercontent.com/pa1nrui1/legal-skills/main/skills/legal/%E5%B9%BF%E5%91%8A%E5%90%88%E8%A7%84%E5%AE%A1%E6%A0%B8/SKILL.md",
  "repository_url": "https://github.com/pa1nrui1/legal-skills",
  "version": None,
  "visibility": "public",
  "allowed_groups": [],
  "tags": [
   "legal",
   "chinese-law",
   "pa1nrui1"
  ],
  "metadata": {
   "author": "潘睿（执业律师）",
   "source_repo": "pa1nrui1/legal-skills",
   "skill_dir": "广告合规审核",
   "name_zh": "广告合规审核",
   "registration_note": "gateway requires lowercase-alphanumeric names; Chinese name kept in name_zh"
  }
 },
 {
  "name": "pretrial-preparation",
  "description": "庭前准备。基于起诉状、法律分析、诉讼可视化、案例汇编、质证意见等前置文档，自动归纳争议焦点，生成争点导向型庭审提纲、质证攻防矩阵、举证策略规划表、开庭陈述提纲、法庭辩论提纲、代理词和诉讼法律服务方案。当用户发送客户编号并提及\"庭前准备\"、\"庭审提纲\"、\"代理词\"、\"诉讼方案\"等指令时触发使用。",
  "license": "MIT (repo-level)",
  "skill_md_url": "https://raw.githubusercontent.com/pa1nrui1/legal-skills/main/skills/legal/%E5%BA%AD%E5%89%8D%E5%87%86%E5%A4%87/SKILL.md",
  "repository_url": "https://github.com/pa1nrui1/legal-skills",
  "version": None,
  "visibility": "public",
  "allowed_groups": [],
  "tags": [
   "legal",
   "chinese-law",
   "pa1nrui1"
  ],
  "metadata": {
   "author": "潘睿（执业律师）",
   "source_repo": "pa1nrui1/legal-skills",
   "skill_dir": "庭前准备",
   "name_zh": "庭前准备",
   "registration_note": "gateway requires lowercase-alphanumeric names; Chinese name kept in name_zh"
  }
 },
 {
  "name": "trial-and-post-trial-work",
  "description": "系统化支持庭审前检查提醒、庭审纪要记录、庭审复盘分析、庭后代理词撰写、补充材料管理、与当事人和法官沟通等全流程工作。当用户发送客户编号并提及\"开庭\"、\"庭审\"、\"庭后\"、\"代理词\"、\"复盘\"、\"庭审纪要\"、\"法官沟通\"等指令时触发使用。",
  "license": "MIT (repo-level)",
  "skill_md_url": "https://raw.githubusercontent.com/pa1nrui1/legal-skills/main/skills/legal/%E5%BA%AD%E5%AE%A1%E4%B8%8E%E5%BA%AD%E5%90%8E%E5%B7%A5%E4%BD%9C/SKILL.md",
  "repository_url": "https://github.com/pa1nrui1/legal-skills",
  "version": "1.1.0",
  "visibility": "public",
  "allowed_groups": [],
  "tags": [
   "legal",
   "chinese-law",
   "pa1nrui1"
  ],
  "metadata": {
   "author": "潘睿（执业律师）",
   "source_repo": "pa1nrui1/legal-skills",
   "skill_dir": "庭审与庭后工作",
   "name_zh": "庭审与庭后工作",
   "registration_note": "gateway requires lowercase-alphanumeric names; Chinese name kept in name_zh"
  }
 },
 {
  "name": "wechat-article-to-markdown",
  "description": "将法律文本（法律条文或法律案例）转换为规范的 Markdown 格式，删除推广冗余信息。本技能应在用户需要处理法律条文（如民法典、刑法等）、整理法律案例（如最高法典型案例、裁判文书等）、或从粘贴文本中格式化法律文档时使用。注意：本技能只负责格式化和内容清理，不包含内容抓取能力。内容获取应由其他 skill（如 wechat-article-fetch）完成，AI 会自动判断技能协作顺序。",
  "license": "CC-BY-NC-SA-4.0",
  "skill_md_url": "https://raw.githubusercontent.com/pa1nrui1/legal-skills/main/skills/legal/%E5%BE%AE%E4%BF%A1%E6%96%87%E7%AB%A0%E8%BD%AC%E6%8D%A2%E4%B8%BAmarkdown/SKILL.md",
  "repository_url": "https://github.com/pa1nrui1/legal-skills",
  "version": None,
  "visibility": "group",
  "allowed_groups": [
   "registry-admins"
  ],
  "tags": [
   "legal",
   "chinese-law",
   "pa1nrui1"
  ],
  "metadata": {
   "author": "潘睿（执业律师）",
   "source_repo": "pa1nrui1/legal-skills",
   "skill_dir": "微信文章转换为markdown",
   "name_zh": "微信文章转换为markdown",
   "registration_note": "gateway requires lowercase-alphanumeric names; Chinese name kept in name_zh"
  }
 },
 {
  "name": "juvenile-criminal-cases",
  "description": "未成年人刑事案件专项辩护Skill，覆盖未成年人刑事案件的教育感化挽救原则、社会调查、不逮捕申请、附条件不起诉、犯罪记录封存、不公开审理、法定代理人到场和信息保护等工作。当用户提及\"未成年人\"、\"少年犯\"、\"社会调查\"、\"附条件不起诉\"、\"犯罪记录封存\"、\"不公开审理\"等关键词时触发使用。",
  "license": "MIT (repo-level)",
  "skill_md_url": "https://raw.githubusercontent.com/pa1nrui1/legal-skills/main/skills/legal/%E6%9C%AA%E6%88%90%E5%B9%B4%E4%BA%BA%E6%A1%88%E4%BB%B6/SKILL.md",
  "repository_url": "https://github.com/pa1nrui1/legal-skills",
  "version": None,
  "visibility": "public",
  "allowed_groups": [],
  "tags": [
   "legal",
   "chinese-law",
   "pa1nrui1"
  ],
  "metadata": {
   "author": "潘睿（执业律师）",
   "source_repo": "pa1nrui1/legal-skills",
   "skill_dir": "未成年人案件",
   "name_zh": "未成年人案件",
   "registration_note": "gateway requires lowercase-alphanumeric names; Chinese name kept in name_zh"
  }
 },
 {
  "name": "case-intake-and-engagement",
  "description": "刑事辩护案件承接与委托Skill。协助律师完成刑事案件的初次接待、案件评估、风险告知、委托手续办理及案件信息采集，生成标准化委托文书并建立案件档案。当用户发送客户编号并提及\"刑事案件承接\"、\"刑事委托\"、\"刑事接案\"等指令时触发使用。",
  "license": "MIT (repo-level)",
  "skill_md_url": "https://raw.githubusercontent.com/pa1nrui1/legal-skills/main/skills/legal/%E6%A1%88%E4%BB%B6%E6%89%BF%E6%8E%A5%E4%B8%8E%E5%A7%94%E6%89%98/SKILL.md",
  "repository_url": "https://github.com/pa1nrui1/legal-skills",
  "version": None,
  "visibility": "public",
  "allowed_groups": [],
  "tags": [
   "legal",
   "chinese-law",
   "pa1nrui1"
  ],
  "metadata": {
   "author": "潘睿（执业律师）",
   "source_repo": "pa1nrui1/legal-skills",
   "skill_dir": "案件承接与委托",
   "name_zh": "案件承接与委托",
   "registration_note": "gateway requires lowercase-alphanumeric names; Chinese name kept in name_zh"
  }
 },
 {
  "name": "case-materials-to-legal-docs",
  "description": "根据案件材料或沟通记录生成各类法律服务文档（诉讼方案、咨询报告、非诉方案、建议书、沟通报告等）。本技能应在用户需要将案件材料、咨询记录或沟通内容整理为专业法律文档时使用。",
  "license": "CC-BY-NC-SA-4.0",
  "skill_md_url": "https://raw.githubusercontent.com/pa1nrui1/legal-skills/main/skills/legal/%E6%A1%88%E4%BB%B6%E6%9D%90%E6%96%99%E7%94%9F%E6%88%90%E4%B8%93%E4%B8%9A%E6%96%87%E6%A1%A3/SKILL.md",
  "repository_url": "https://github.com/pa1nrui1/legal-skills",
  "version": None,
  "visibility": "group",
  "allowed_groups": [
   "registry-admins"
  ],
  "tags": [
   "legal",
   "chinese-law",
   "pa1nrui1"
  ],
  "metadata": {
   "author": "潘睿（执业律师）",
   "source_repo": "pa1nrui1/legal-skills",
   "skill_dir": "案件材料生成专业文档",
   "name_zh": "案件材料生成专业文档",
   "registration_note": "gateway requires lowercase-alphanumeric names; Chinese name kept in name_zh"
  }
 },
 {
  "name": "client-communication-records",
  "description": "制作民商事诉讼案件沟通记录文档，依据《诉讼精细化》手册要求，采用对话式笔录格式记录与客户首次深度沟通的内容，最终生成Word格式的案件沟通记录。当用户发送客户编号并提及\"案件沟通记录\"、\"制作沟通记录\"或类似指令时触发使用。",
  "license": "MIT (repo-level)",
  "skill_md_url": "https://raw.githubusercontent.com/pa1nrui1/legal-skills/main/skills/legal/%E6%A1%88%E4%BB%B6%E6%B2%9F%E9%80%9A%E8%AE%B0%E5%BD%95/SKILL.md",
  "repository_url": "https://github.com/pa1nrui1/legal-skills",
  "version": None,
  "visibility": "public",
  "allowed_groups": [],
  "tags": [
   "legal",
   "chinese-law",
   "pa1nrui1"
  ],
  "metadata": {
   "author": "潘睿（执业律师）",
   "source_repo": "pa1nrui1/legal-skills",
   "skill_dir": "案件沟通记录",
   "name_zh": "案件沟通记录",
   "registration_note": "gateway requires lowercase-alphanumeric names; Chinese name kept in name_zh"
  }
 },
 {
  "name": "case-discussion-outline",
  "description": "AI自动完成的深度案件分析工具，整合前序材料进行四维度自问自答分析、三方模拟法庭演练，最终生成案件提纲。当用户提及\"案件讨论\"、\"案件提纲\"、\"案件分析\"、\"模拟法庭\"、\"案件研讨\"等指令时触发使用。立案完成后主动提醒律师执行。",
  "license": "MIT (repo-level)",
  "skill_md_url": "https://raw.githubusercontent.com/pa1nrui1/legal-skills/main/skills/legal/%E6%A1%88%E4%BB%B6%E8%AE%A8%E8%AE%BA%E4%B8%8E%E6%8F%90%E7%BA%B2/SKILL.md",
  "repository_url": "https://github.com/pa1nrui1/legal-skills",
  "version": "1.0.0",
  "visibility": "public",
  "allowed_groups": [],
  "tags": [
   "legal",
   "chinese-law",
   "pa1nrui1"
  ],
  "metadata": {
   "author": "潘睿（执业律师）",
   "source_repo": "pa1nrui1/legal-skills",
   "skill_dir": "案件讨论与提纲",
   "name_zh": "案件讨论与提纲",
   "registration_note": "gateway requires lowercase-alphanumeric names; Chinese name kept in name_zh"
  }
 },
 {
  "name": "death-penalty-defense",
  "description": "死刑案件及死缓案件刑事辩护专项Skill，覆盖可能判处死刑案件识别、一审保命辩护、二审强制开庭、被害人和解、死刑复核辩护、死刑案件证据标准和被害人代理注意事项。当用户提及\"死刑\"、\"死缓\"、\"死刑立即执行\"、\"死刑复核\"、\"核准死刑\"等关键词时触发使用。",
  "license": "MIT (repo-level)",
  "skill_md_url": "https://raw.githubusercontent.com/pa1nrui1/legal-skills/main/skills/legal/%E6%AD%BB%E5%88%91%E6%A1%88%E4%BB%B6/SKILL.md",
  "repository_url": "https://github.com/pa1nrui1/legal-skills",
  "version": None,
  "visibility": "public",
  "allowed_groups": [],
  "tags": [
   "legal",
   "chinese-law",
   "pa1nrui1"
  ],
  "metadata": {
   "author": "潘睿（执业律师）",
   "source_repo": "pa1nrui1/legal-skills",
   "skill_dir": "死刑案件",
   "name_zh": "死刑案件",
   "registration_note": "gateway requires lowercase-alphanumeric names; Chinese name kept in name_zh"
  }
 },
 {
  "name": "civil-first-instance-litigation",
  "description": "民事一审诉讼与破产案件专业流程编排 Skill。整合25个子Skill：民事诉讼14个（法律咨询助手、案件沟通记录、初步法律分析、委托合同管理、法规案例检索、调查取证与证据管理、立案管理、诉讼可视化、案件讨论与提纲、诉讼文书起草、庭前准备、庭审与庭后工作、调解与和解、诉讼分析工具、结案归档）+ 破产案件10个（破产法律分析、破产申请与受理、管理人工作、财产调查与管理、债权申报与审查、债权人会议、重整程序、破产和解程序、破产清算、破产文书生成）。用于判断民事/破产案件阶段（S0-S16/SM/BP系列）、推荐下一步子Skill、提示关键节点确认和期限；事项建档、路径、文件读取、来源披露、OCR 校正和缺口归档由「法律工作总控」统一处理。",
  "license": "MIT (repo-level)",
  "skill_md_url": "https://raw.githubusercontent.com/pa1nrui1/legal-skills/main/skills/legal/%E6%B0%91%E4%BA%8B%E4%B8%80%E5%AE%A1%E8%AF%89%E8%AE%BC/SKILL.md",
  "repository_url": "https://github.com/pa1nrui1/legal-skills",
  "version": None,
  "visibility": "public",
  "allowed_groups": [],
  "tags": [
   "legal",
   "chinese-law",
   "pa1nrui1"
  ],
  "metadata": {
   "author": "潘睿（执业律师）",
   "source_repo": "pa1nrui1/legal-skills",
   "skill_dir": "民事一审诉讼",
   "name_zh": "民事一审诉讼",
   "registration_note": "gateway requires lowercase-alphanumeric names; Chinese name kept in name_zh"
  }
 },
 {
  "name": "civil-judgment-drafting",
  "description": "一审普通程序民事判决书生成工具。从已有案件材料（起诉状、答辩状、庭审纪要、法律分析等）提取要素，生成符合法院文书样式标准的Word判决书初稿。按总控当前事项记录和复盘台账衔接。当用户发送客户编号并提及\"判决书\"、\"民事判决书\"、\"起草判决书\"、\"模拟判决书\"等指令时触发使用。",
  "license": "MIT (repo-level)",
  "skill_md_url": "https://raw.githubusercontent.com/pa1nrui1/legal-skills/main/skills/legal/%E6%B0%91%E4%BA%8B%E5%88%A4%E5%86%B3%E4%B9%A6/SKILL.md",
  "repository_url": "https://github.com/pa1nrui1/legal-skills",
  "version": None,
  "visibility": "public",
  "allowed_groups": [],
  "tags": [
   "legal",
   "chinese-law",
   "pa1nrui1"
  ],
  "metadata": {
   "author": "潘睿（执业律师）",
   "source_repo": "pa1nrui1/legal-skills",
   "skill_dir": "民事判决书",
   "name_zh": "民事判决书",
   "registration_note": "gateway requires lowercase-alphanumeric names; Chinese name kept in name_zh"
  }
 },
 {
  "name": "legal-wiki-lookup",
  "description": "按罪名/领域/关键词检索 Wiki 知识页，返回知识卡片或全文内容。 支持刑事罪名知识、民事领域知识、案例知识页的查询与交叉引用跳转。 当用户提及\"查Wiki\"、\"知识库查询\"、\"查罪名\"、\"查法律知识\"、\"wiki查询\"等关键词时触发。",
  "license": "MIT (repo-level)",
  "skill_md_url": "https://raw.githubusercontent.com/pa1nrui1/legal-skills/main/skills/legal/%E6%B3%95%E5%BE%8BWiki%E7%9F%A5%E8%AF%86%E5%BA%93%E6%9F%A5%E8%AF%A2/SKILL.md",
  "repository_url": "https://github.com/pa1nrui1/legal-skills",
  "version": None,
  "visibility": "public",
  "allowed_groups": [],
  "tags": [
   "legal",
   "chinese-law",
   "pa1nrui1"
  ],
  "metadata": {
   "author": "潘睿（执业律师）",
   "source_repo": "pa1nrui1/legal-skills",
   "skill_dir": "法律Wiki知识库查询",
   "name_zh": "法律Wiki知识库查询",
   "registration_note": "gateway requires lowercase-alphanumeric names; Chinese name kept in name_zh"
  }
 },
 {
  "name": "legal-consultation-assistant",
  "description": "协助律师处理微信渠道法律咨询和线下咨询，提供口语化回复建议、智能反问引导、软性销售植入，并在用户明确要求或总控确认需要时更新复盘台账。支持客户编号识别、咨询入口路由、线下咨询事实补全等功能。",
  "license": "MIT (repo-level)",
  "skill_md_url": "https://raw.githubusercontent.com/pa1nrui1/legal-skills/main/skills/legal/%E6%B3%95%E5%BE%8B%E5%92%A8%E8%AF%A2%E5%8A%A9%E6%89%8B/SKILL.md",
  "repository_url": "https://github.com/pa1nrui1/legal-skills",
  "version": None,
  "visibility": "public",
  "allowed_groups": [],
  "tags": [
   "legal",
   "chinese-law",
   "pa1nrui1"
  ],
  "metadata": {
   "author": "潘睿（执业律师）",
   "source_repo": "pa1nrui1/legal-skills",
   "skill_dir": "法律咨询助手",
   "name_zh": "法律咨询助手",
   "registration_note": "gateway requires lowercase-alphanumeric names; Chinese name kept in name_zh"
  }
 },
 {
  "name": "legal-workflow-controller",
  "description": "legal 文件夹通用入口 Skill。用于法律咨询、案件办理、合同、产品法务、监管合规、诉讼、刑辩、劳动争议、破产、合规、文书、检索等任务的语义路由、案件隔离、来源披露、文件读取复查、法规/Wiki 校验、OCR 校正、缺口提示和合同偏好学习。用户提出任何法律工作请求、客户编号、案件材料处理、法律文书生成或需要自动匹配 legal 子 Skill 时触发。",
  "license": "MIT (repo-level)",
  "skill_md_url": "https://raw.githubusercontent.com/pa1nrui1/legal-skills/main/skills/legal/%E6%B3%95%E5%BE%8B%E5%B7%A5%E4%BD%9C%E6%80%BB%E6%8E%A7/SKILL.md",
  "repository_url": "https://github.com/pa1nrui1/legal-skills",
  "version": None,
  "visibility": "public",
  "allowed_groups": [],
  "tags": [
   "legal",
   "chinese-law",
   "pa1nrui1"
  ],
  "metadata": {
   "author": "潘睿（执业律师）",
   "source_repo": "pa1nrui1/legal-skills",
   "skill_dir": "法律工作总控",
   "name_zh": "法律工作总控",
   "registration_note": "gateway requires lowercase-alphanumeric names; Chinese name kept in name_zh"
  }
 },
 {
  "name": "legal-doc-pre-release-review",
  "description": "在法律业务 Skill 生成正文或要素式字段后、法律文书模板与导出生成本地 Word 前触发。用于审查 draft.html/preflight-meta.json 或 complaint-data.json/fill-plan.json、读取复查摘要、法规校验摘要、来源边界和用户确认记录，决定是否可以进入正式 DOCX 导出；发现问题后必须闭环推进到业务 Skill 整改、用户确认或材料读取流程。",
  "license": "MIT (repo-level)",
  "skill_md_url": "https://raw.githubusercontent.com/pa1nrui1/legal-skills/main/skills/legal/%E6%B3%95%E5%BE%8B%E6%96%87%E4%B9%A6%E5%87%BA%E7%A8%BF%E5%89%8D%E5%AE%A1%E6%9F%A5/SKILL.md",
  "repository_url": "https://github.com/pa1nrui1/legal-skills",
  "version": None,
  "visibility": "public",
  "allowed_groups": [],
  "tags": [
   "legal",
   "chinese-law",
   "pa1nrui1"
  ],
  "metadata": {
   "author": "潘睿（执业律师）",
   "source_repo": "pa1nrui1/legal-skills",
   "skill_dir": "法律文书出稿前审查",
   "name_zh": "法律文书出稿前审查",
   "registration_note": "gateway requires lowercase-alphanumeric names; Chinese name kept in name_zh"
  }
 },
 {
  "name": "legal-doc-templates-export",
  "description": "统一处理法律工作中最终需要输出本地 Word（.docx）的文书、报告、清单、笔录、意见书、函件、合同和正式交付文件。由法律工作总控强制路由调用；业务 Skill 负责正文和法律判断，本 Skill 负责选择格式 profile、接收语义 HTML 或要素式填充数据、导出 DOCX、结构体检和兜底模板。",
  "license": "MIT (repo-level)",
  "skill_md_url": "https://raw.githubusercontent.com/pa1nrui1/legal-skills/main/skills/legal/%E6%B3%95%E5%BE%8B%E6%96%87%E4%B9%A6%E6%A8%A1%E6%9D%BF%E4%B8%8E%E5%AF%BC%E5%87%BA/SKILL.md",
  "repository_url": "https://github.com/pa1nrui1/legal-skills",
  "version": None,
  "visibility": "public",
  "allowed_groups": [],
  "tags": [
   "legal",
   "chinese-law",
   "pa1nrui1"
  ],
  "metadata": {
   "author": "潘睿（执业律师）",
   "source_repo": "pa1nrui1/legal-skills",
   "skill_dir": "法律文书模板与导出",
   "name_zh": "法律文书模板与导出",
   "registration_note": "gateway requires lowercase-alphanumeric names; Chinese name kept in name_zh"
  }
 },
 {
  "name": "legal-writing-deai-polish",
  "description": "检测并去除文章中的AI化表述模式，用于写作润色、文本优化、去AI腔。",
  "license": "MIT (repo-level)",
  "skill_md_url": "https://raw.githubusercontent.com/pa1nrui1/legal-skills/main/skills/legal/%E6%B3%95%E5%BE%8B%E6%96%87%E7%AB%A0quai%E5%91%B3%E9%81%93/SKILL.md",
  "repository_url": "https://github.com/pa1nrui1/legal-skills",
  "version": None,
  "visibility": "public",
  "allowed_groups": [],
  "tags": [
   "legal",
   "chinese-law",
   "pa1nrui1"
  ],
  "metadata": {
   "author": "潘睿（执业律师）",
   "source_repo": "pa1nrui1/legal-skills",
   "skill_dir": "法律文章quai味道",
   "name_zh": "法律文章quai味道",
   "registration_note": "gateway requires lowercase-alphanumeric names; Chinese name kept in name_zh"
  }
 },
 {
  "name": "statute-case-retrieval",
  "description": "基于三层检索法进行系统性法律法规与案例检索，与前序\"初步法律分析\"请求权路径联动，输出法官版《法律法规及案例汇编》和律师版《法规案例检索报告》双文档，按总控当前事项记录和复盘台账衔接。当用户发送客户编号并提及\"检索法规案例\"、\"法规汇编\"、\"案例检索\"等指令时触发使用。",
  "license": "MIT (repo-level)",
  "skill_md_url": "https://raw.githubusercontent.com/pa1nrui1/legal-skills/main/skills/legal/%E6%B3%95%E8%A7%84%E6%A1%88%E4%BE%8B%E6%A3%80%E7%B4%A2/SKILL.md",
  "repository_url": "https://github.com/pa1nrui1/legal-skills",
  "version": None,
  "visibility": "public",
  "allowed_groups": [],
  "tags": [
   "legal",
   "chinese-law",
   "pa1nrui1"
  ],
  "metadata": {
   "author": "潘睿（执业律师）",
   "source_repo": "pa1nrui1/legal-skills",
   "skill_dir": "法规案例检索",
   "name_zh": "法规案例检索",
   "registration_note": "gateway requires lowercase-alphanumeric names; Chinese name kept in name_zh"
  }
 },
 {
  "name": "special-criminal-procedures",
  "description": "刑事特殊程序辩护与代理Skill，覆盖违法所得没收程序、精神病人强制医疗程序、再审申诉程序的启动条件、材料审查、听证或开庭准备、文书生成和与各刑事阶段Skill衔接。当用户提及\"违法所得没收\"、\"强制医疗\"、\"精神病鉴定\"、\"再审\"、\"申诉\"、\"生效判决错误\"等关键词时触发使用。",
  "license": "MIT (repo-level)",
  "skill_md_url": "https://raw.githubusercontent.com/pa1nrui1/legal-skills/main/skills/legal/%E7%89%B9%E6%AE%8A%E7%A8%8B%E5%BA%8F/SKILL.md",
  "repository_url": "https://github.com/pa1nrui1/legal-skills",
  "version": None,
  "visibility": "public",
  "allowed_groups": [],
  "tags": [
   "legal",
   "chinese-law",
   "pa1nrui1"
  ],
  "metadata": {
   "author": "潘睿（执业律师）",
   "source_repo": "pa1nrui1/legal-skills",
   "skill_dir": "特殊程序",
   "name_zh": "特殊程序",
   "registration_note": "gateway requires lowercase-alphanumeric names; Chinese name kept in name_zh"
  }
 },
 {
  "name": "employer-labor-compliance",
  "description": "公司端劳动用工合规 Skill。用于用人单位日常劳动合规、员工手册/规章制度/劳动合同更新、工资工时问答、内部劳动政策起草，以及公司在解除、调岗、降薪、处罚、员工投诉或仲裁前的风险预判。用户提到公司劳动合规、员工手册、规章制度、薪酬制度、考勤制度、加班费、发薪日、特殊工时、劳动合同修改、内部政策起草、辞退员工风险、员工投诉公司、调岗降薪等场景时触发。",
  "license": "MIT (repo-level)",
  "skill_md_url": "https://raw.githubusercontent.com/pa1nrui1/legal-skills/main/skills/legal/%E7%94%A8%E4%BA%BA%E5%8D%95%E4%BD%8D%E5%8A%B3%E5%8A%A8%E5%90%88%E8%A7%84/SKILL.md",
  "repository_url": "https://github.com/pa1nrui1/legal-skills",
  "version": None,
  "visibility": "public",
  "allowed_groups": [],
  "tags": [
   "legal",
   "chinese-law",
   "pa1nrui1"
  ],
  "metadata": {
   "author": "潘睿（执业律师）",
   "source_repo": "pa1nrui1/legal-skills",
   "skill_dir": "用人单位劳动合规",
   "name_zh": "用人单位劳动合规",
   "registration_note": "gateway requires lowercase-alphanumeric names; Chinese name kept in name_zh"
  }
 },
 {
  "name": "regulatory-monitoring",
  "description": "中国境内重点监管动态监测与客户合规影响评估 Skill。用于监管动态、新规更新、政策变化、行业监管、法规政策分级、客户合规缺口核查、政策制度修改建议、整改清单、监管合规简报等任务。适用于用户要求监测某行业、某客户、某产品或某主题的法律法规、监管政策、部门规章、规范性文件、征求意见稿、执法动态，并判断新规要求、客户现有合规文件缺口和整改方案。",
  "license": "MIT (repo-level)",
  "skill_md_url": "https://raw.githubusercontent.com/pa1nrui1/legal-skills/main/skills/legal/%E7%9B%91%E7%AE%A1%E5%90%88%E8%A7%84%E7%9B%91%E6%B5%8B/SKILL.md",
  "repository_url": "https://github.com/pa1nrui1/legal-skills",
  "version": None,
  "visibility": "public",
  "allowed_groups": [],
  "tags": [
   "legal",
   "chinese-law",
   "pa1nrui1"
  ],
  "metadata": {
   "author": "潘睿（执业律师）",
   "source_repo": "pa1nrui1/legal-skills",
   "skill_dir": "监管合规监测",
   "name_zh": "监管合规监测",
   "registration_note": "gateway requires lowercase-alphanumeric names; Chinese name kept in name_zh"
  }
 },
 {
  "name": "bankruptcy-reconciliation",
  "description": "提供破产和解程序全流程支持，覆盖从和解申请、协议草案编制、债权人会议表决、协议效力确认到执行监督及转清算的完整流程。适用《企业破产法》第95-99条。当用户发送客户编号并提及\"破产和解\"、\"和解协议\"、\"和解程序\"等指令时触发使用。",
  "license": "MIT (repo-level)",
  "skill_md_url": "https://raw.githubusercontent.com/pa1nrui1/legal-skills/main/skills/legal/%E7%A0%B4%E4%BA%A7%E5%92%8C%E8%A7%A3%E7%A8%8B%E5%BA%8F/SKILL.md",
  "repository_url": "https://github.com/pa1nrui1/legal-skills",
  "version": "1.0.0",
  "visibility": "public",
  "allowed_groups": [],
  "tags": [
   "legal",
   "chinese-law",
   "pa1nrui1"
  ],
  "metadata": {
   "author": "潘睿（执业律师）",
   "source_repo": "pa1nrui1/legal-skills",
   "skill_dir": "破产和解程序",
   "name_zh": "破产和解程序",
   "registration_note": "gateway requires lowercase-alphanumeric names; Chinese name kept in name_zh"
  }
 },
 {
  "name": "bankruptcy-document-generator",
  "description": "基于《破产程序法律文书样式》中的165份文书模板（106份法院文书+59份管理人文书），按需生成各类破产程序文书。本Skill作为破产文书的统一生成工具，供其他破产Skill调用。当用户发送客户编号并提及\"破产文书\"/\"生成XX通知\"/\"生成XX报告\"/\"生成XX裁定\"等指令时触发使用。",
  "license": "MIT (repo-level)",
  "skill_md_url": "https://raw.githubusercontent.com/pa1nrui1/legal-skills/main/skills/legal/%E7%A0%B4%E4%BA%A7%E6%96%87%E4%B9%A6%E7%94%9F%E6%88%90/SKILL.md",
  "repository_url": "https://github.com/pa1nrui1/legal-skills",
  "version": None,
  "visibility": "public",
  "allowed_groups": [],
  "tags": [
   "legal",
   "chinese-law",
   "pa1nrui1"
  ],
  "metadata": {
   "author": "潘睿（执业律师）",
   "source_repo": "pa1nrui1/legal-skills",
   "skill_dir": "破产文书生成",
   "name_zh": "破产文书生成",
   "registration_note": "gateway requires lowercase-alphanumeric names; Chinese name kept in name_zh"
  }
 },
 {
  "name": "bankruptcy-legal-analysis",
  "description": "基于《企业破产法》及司法解释，进行破产案件的系统性法律分析，支持管理人、债权人代理、债务人代理三种角色视角，生成标准化破产法律分析报告Word文档。当用户发送客户编号并提及\"破产法律分析\"、\"破产分析\"指令时触发使用，或在破产案件流程中自动衔接（BP1→BP2）。",
  "license": "MIT (repo-level)",
  "skill_md_url": "https://raw.githubusercontent.com/pa1nrui1/legal-skills/main/skills/legal/%E7%A0%B4%E4%BA%A7%E6%B3%95%E5%BE%8B%E5%88%86%E6%9E%90/SKILL.md",
  "repository_url": "https://github.com/pa1nrui1/legal-skills",
  "version": None,
  "visibility": "public",
  "allowed_groups": [],
  "tags": [
   "legal",
   "chinese-law",
   "pa1nrui1"
  ],
  "metadata": {
   "author": "潘睿（执业律师）",
   "source_repo": "pa1nrui1/legal-skills",
   "skill_dir": "破产法律分析",
   "name_zh": "破产法律分析",
   "registration_note": "gateway requires lowercase-alphanumeric names; Chinese name kept in name_zh"
  }
 },
 {
  "name": "bankruptcy-liquidation",
  "description": "覆盖破产清算程序全流程，从宣告破产到程序终结。主要为R1（管理人）工作，R2/R3参与监督。当用户发送客户编号并提及\"破产清算\"、\"财产变价\"、\"财产分配\"、\"终结程序\"等指令时触发使用。",
  "license": "MIT (repo-level)",
  "skill_md_url": "https://raw.githubusercontent.com/pa1nrui1/legal-skills/main/skills/legal/%E7%A0%B4%E4%BA%A7%E6%B8%85%E7%AE%97/SKILL.md",
  "repository_url": "https://github.com/pa1nrui1/legal-skills",
  "version": "1.0.0",
  "visibility": "public",
  "allowed_groups": [],
  "tags": [
   "legal",
   "chinese-law",
   "pa1nrui1"
  ],
  "metadata": {
   "author": "潘睿（执业律师）",
   "source_repo": "pa1nrui1/legal-skills",
   "skill_dir": "破产清算",
   "name_zh": "破产清算",
   "registration_note": "gateway requires lowercase-alphanumeric names; Chinese name kept in name_zh"
  }
 },
 {
  "name": "bankruptcy-filing-acceptance",
  "description": "覆盖破产申请全流程，包括申请书起草、附件准备、提交跟踪、受理后初步工作。当用户发送客户编号并提及\"破产申请\"、\"重整申请\"、\"和解申请\"等指令时触发使用。",
  "license": "MIT (repo-level)",
  "skill_md_url": "https://raw.githubusercontent.com/pa1nrui1/legal-skills/main/skills/legal/%E7%A0%B4%E4%BA%A7%E7%94%B3%E8%AF%B7%E4%B8%8E%E5%8F%97%E7%90%86/SKILL.md",
  "repository_url": "https://github.com/pa1nrui1/legal-skills",
  "version": "1.0.0",
  "visibility": "public",
  "allowed_groups": [],
  "tags": [
   "legal",
   "chinese-law",
   "pa1nrui1"
  ],
  "metadata": {
   "author": "潘睿（执业律师）",
   "source_repo": "pa1nrui1/legal-skills",
   "skill_dir": "破产申请与受理",
   "name_zh": "破产申请与受理",
   "registration_note": "gateway requires lowercase-alphanumeric names; Chinese name kept in name_zh"
  }
 },
 {
  "name": "case-filing-management",
  "description": "系统化指引民事一审立案全流程，包括立案材料核查、管辖权预检、立案方式选择、诉讼费计算、举证期限管理等。当用户发送客户编号并提及\"立案\"、\"去立案\"、\"立案准备\"、\"立案材料\"、\"网上立案\"等指令时触发使用。",
  "license": "MIT (repo-level)",
  "skill_md_url": "https://raw.githubusercontent.com/pa1nrui1/legal-skills/main/skills/legal/%E7%AB%8B%E6%A1%88%E7%AE%A1%E7%90%86/SKILL.md",
  "repository_url": "https://github.com/pa1nrui1/legal-skills",
  "version": "1.0.0",
  "visibility": "public",
  "allowed_groups": [],
  "tags": [
   "legal",
   "chinese-law",
   "pa1nrui1"
  ],
  "metadata": {
   "author": "潘睿（执业律师）",
   "source_repo": "pa1nrui1/legal-skills",
   "skill_dir": "立案管理",
   "name_zh": "立案管理",
   "registration_note": "gateway requires lowercase-alphanumeric names; Chinese name kept in name_zh"
  }
 },
 {
  "name": "simplified-summary-procedure",
  "description": "刑事辩护简易程序、速裁程序及普通程序简化审理分支Skill，重点处理认罪认罚案件中的程序适用审查、量刑协商、庭审简化、权利保障和时间节点管理。作为一审阶段辩护的分支，当用户提及\"简易程序\"、\"速裁程序\"、\"认罪认罚\"、\"快速审理\"、\"当庭宣判\"等关键词时触发使用。",
  "license": "MIT (repo-level)",
  "skill_md_url": "https://raw.githubusercontent.com/pa1nrui1/legal-skills/main/skills/legal/%E7%AE%80%E6%98%93%E9%80%9F%E8%A3%81%E7%A8%8B%E5%BA%8F/SKILL.md",
  "repository_url": "https://github.com/pa1nrui1/legal-skills",
  "version": None,
  "visibility": "public",
  "allowed_groups": [],
  "tags": [
   "legal",
   "chinese-law",
   "pa1nrui1"
  ],
  "metadata": {
   "author": "潘睿（执业律师）",
   "source_repo": "pa1nrui1/legal-skills",
   "skill_dir": "简易速裁程序",
   "name_zh": "简易速裁程序",
   "registration_note": "gateway requires lowercase-alphanumeric names; Chinese name kept in name_zh"
  }
 },
 {
  "name": "bankruptcy-administrator-tasks",
  "description": "R1（管理人）专属Skill，覆盖管理人受理后的全部初期工作职责，包括印章与账户管理、财产接管、内部事务管理、合同处理、聘用工作人员、管理人团队管理及报酬方案制定。当用户发送客户编号并提及\"管理人接管\"、\"开始接管\"、\"接管工作\"等指令时触发使用。",
  "license": "MIT (repo-level)",
  "skill_md_url": "https://raw.githubusercontent.com/pa1nrui1/legal-skills/main/skills/legal/%E7%AE%A1%E7%90%86%E4%BA%BA%E5%B7%A5%E4%BD%9C/SKILL.md",
  "repository_url": "https://github.com/pa1nrui1/legal-skills",
  "version": "1.0.0",
  "visibility": "public",
  "allowed_groups": [],
  "tags": [
   "legal",
   "chinese-law",
   "pa1nrui1"
  ],
  "metadata": {
   "author": "潘睿（执业律师）",
   "source_repo": "pa1nrui1/legal-skills",
   "skill_dir": "管理人工作",
   "name_zh": "管理人工作",
   "registration_note": "gateway requires lowercase-alphanumeric names; Chinese name kept in name_zh"
  }
 },
 {
  "name": "case-closure-archive",
  "description": "在判决/调解完成后，系统化完成案卷归档、案件总结、客户移交、费用结算等结案工作。当用户发送客户编号并提及\"归档\"、\"结案\"、\"案件总结\"、\"办案小结\"、\"案卷移交\"、\"费用结算\"等指令时触发使用。",
  "license": "MIT (repo-level)",
  "skill_md_url": "https://raw.githubusercontent.com/pa1nrui1/legal-skills/main/skills/legal/%E7%BB%93%E6%A1%88%E5%BD%92%E6%A1%A3/SKILL.md",
  "repository_url": "https://github.com/pa1nrui1/legal-skills",
  "version": "1.0.0",
  "visibility": "public",
  "allowed_groups": [],
  "tags": [
   "legal",
   "chinese-law",
   "pa1nrui1"
  ],
  "metadata": {
   "author": "潘睿（执业律师）",
   "source_repo": "pa1nrui1/legal-skills",
   "skill_dir": "结案归档",
   "name_zh": "结案归档",
   "registration_note": "gateway requires lowercase-alphanumeric names; Chinese name kept in name_zh"
  }
 },
 {
  "name": "litigation-analysis-tool",
  "description": "诉讼分析工具 - 支持文件夹批量处理，判决书深度分析，生成上诉/再审决策支持",
  "license": "CC-BY-NC-SA-4.0",
  "skill_md_url": "https://raw.githubusercontent.com/pa1nrui1/legal-skills/main/skills/legal/%E8%AF%89%E8%AE%BC%E5%88%86%E6%9E%90%E5%B7%A5%E5%85%B7/SKILL.md",
  "repository_url": "https://github.com/pa1nrui1/legal-skills",
  "version": None,
  "visibility": "group",
  "allowed_groups": [
   "registry-admins"
  ],
  "tags": [
   "legal",
   "chinese-law",
   "pa1nrui1"
  ],
  "metadata": {
   "author": "潘睿（执业律师）",
   "source_repo": "pa1nrui1/legal-skills",
   "skill_dir": "诉讼分析工具",
   "name_zh": "诉讼分析工具",
   "registration_note": "gateway requires lowercase-alphanumeric names; Chinese name kept in name_zh"
  }
 },
 {
  "name": "litigation-visualization",
  "description": "基于Mermaid语法生成诉讼可视化图表（法律关系图、时间轴图、争点树、要件分析图、攻防对抗图、证据链图谱），按总控当前事项记录和复盘台账衔接，生成诉讼可视化报告Word文档（法官版+律师版）。当用户发送客户编号并提及\"可视化\"、\"诉讼可视化\"、\"制作图表\"等指令时触发使用。",
  "license": "MIT (repo-level)",
  "skill_md_url": "https://raw.githubusercontent.com/pa1nrui1/legal-skills/main/skills/legal/%E8%AF%89%E8%AE%BC%E5%8F%AF%E8%A7%86%E5%8C%96/SKILL.md",
  "repository_url": "https://github.com/pa1nrui1/legal-skills",
  "version": None,
  "visibility": "public",
  "allowed_groups": [],
  "tags": [
   "legal",
   "chinese-law",
   "pa1nrui1"
  ],
  "metadata": {
   "author": "潘睿（执业律师）",
   "source_repo": "pa1nrui1/legal-skills",
   "skill_dir": "诉讼可视化",
   "name_zh": "诉讼可视化",
   "registration_note": "gateway requires lowercase-alphanumeric names; Chinese name kept in name_zh"
  }
 },
 {
  "name": "litigation-document-drafting",
  "description": "基于\"六来源体系\"和请求权基础分析，起草起诉状、答辩状、代理词、质证意见、保全申请书等诉讼文书。整合《法律文书汇编》（郑州市律师协会2023年度优秀法律文书汇编）格式标准，按总控当前事项记录和复盘台账衔接。当用户发送客户编号并提及\"起诉状\"、\"答辩状\"、\"代理词\"、\"质证\"、\"保全\"等指令时触发使用。",
  "license": "MIT (repo-level)",
  "skill_md_url": "https://raw.githubusercontent.com/pa1nrui1/legal-skills/main/skills/legal/%E8%AF%89%E8%AE%BC%E6%96%87%E4%B9%A6%E8%B5%B7%E8%8D%89/SKILL.md",
  "repository_url": "https://github.com/pa1nrui1/legal-skills",
  "version": None,
  "visibility": "public",
  "allowed_groups": [],
  "tags": [
   "legal",
   "chinese-law",
   "pa1nrui1"
  ],
  "metadata": {
   "author": "潘睿（执业律师）",
   "source_repo": "pa1nrui1/legal-skills",
   "skill_dir": "诉讼文书起草",
   "name_zh": "诉讼文书起草",
   "registration_note": "gateway requires lowercase-alphanumeric names; Chinese name kept in name_zh"
  }
 },
 {
  "name": "litigation-case-management",
  "description": "民事、刑事及劳动争议诉讼共用的案件运营管理 Skill。用于案件更新、传票/开庭通知/举证通知/应诉通知/裁判文书处理、期限台账、飞书日历提醒、事实时间线和程序时间线维护、飞书思维导图同步、案件简报、诉讼案件总览、案件组合状态、案件关闭与结案归档检查。案件隔离、建档、材料读取复查、来源披露、OCR 校正、缺口归档和法规核验由法律工作总控统一处理。",
  "license": "MIT (repo-level)",
  "skill_md_url": "https://raw.githubusercontent.com/pa1nrui1/legal-skills/main/skills/legal/%E8%AF%89%E8%AE%BC%E6%A1%88%E4%BB%B6%E7%AE%A1%E7%90%86/SKILL.md",
  "repository_url": "https://github.com/pa1nrui1/legal-skills",
  "version": None,
  "visibility": "public",
  "allowed_groups": [],
  "tags": [
   "legal",
   "chinese-law",
   "pa1nrui1"
  ],
  "metadata": {
   "author": "潘睿（执业律师）",
   "source_repo": "pa1nrui1/legal-skills",
   "skill_dir": "诉讼案件管理",
   "name_zh": "诉讼案件管理",
   "registration_note": "gateway requires lowercase-alphanumeric names; Chinese name kept in name_zh"
  }
 },
 {
  "name": "evidence-collection-management",
  "description": "基于请求权要件分析进行证据缺口评估，系统化指引证据收集、调查取证、证人管理和财产保全全流程，生成取证方案、各类申请文书和调查笔录。当用户发送客户编号并提及\"调查取证\"、\"证据收集\"、\"财产保全\"、\"调查令\"、\"证人出庭\"、\"补充材料\"、\"取证方案\"等指令时触发使用。",
  "license": "MIT (repo-level)",
  "skill_md_url": "https://raw.githubusercontent.com/pa1nrui1/legal-skills/main/skills/legal/%E8%B0%83%E6%9F%A5%E5%8F%96%E8%AF%81%E4%B8%8E%E8%AF%81%E6%8D%AE%E7%AE%A1%E7%90%86/SKILL.md",
  "repository_url": "https://github.com/pa1nrui1/legal-skills",
  "version": "1.0.0",
  "visibility": "public",
  "allowed_groups": [],
  "tags": [
   "legal",
   "chinese-law",
   "pa1nrui1"
  ],
  "metadata": {
   "author": "潘睿（执业律师）",
   "source_repo": "pa1nrui1/legal-skills",
   "skill_dir": "调查取证与证据管理",
   "name_zh": "调查取证与证据管理",
   "registration_note": "gateway requires lowercase-alphanumeric names; Chinese name kept in name_zh"
  }
 },
 {
  "name": "mediation-and-settlement",
  "description": "提供调解与和解全流程支持，包括可行性分析、调解方案起草、调解书/和解协议审查、撤诉管理等功能。当用户发送客户编号并提及\"调解\"、\"和解\"、\"撤诉\"、\"调解方案\"、\"调解书\"等指令时触发使用。",
  "license": "MIT (repo-level)",
  "skill_md_url": "https://raw.githubusercontent.com/pa1nrui1/legal-skills/main/skills/legal/%E8%B0%83%E8%A7%A3%E4%B8%8E%E5%92%8C%E8%A7%A3/SKILL.md",
  "repository_url": "https://github.com/pa1nrui1/legal-skills",
  "version": "1.0.0",
  "visibility": "public",
  "allowed_groups": [],
  "tags": [
   "legal",
   "chinese-law",
   "pa1nrui1"
  ],
  "metadata": {
   "author": "潘睿（执业律师）",
   "source_repo": "pa1nrui1/legal-skills",
   "skill_dir": "调解与和解",
   "name_zh": "调解与和解",
   "registration_note": "gateway requires lowercase-alphanumeric names; Chinese name kept in name_zh"
  }
 },
 {
  "name": "asset-investigation-management",
  "description": "R1（管理人）专属Skill，覆盖破产程序中的财产全面调查、可撤销/无效行为追回、财产管理方案编制。当用户发送客户编号并提及\"财产调查\"、\"财产清查\"、\"可撤销行为\"、\"追回财产\"、\"财产管理方案\"等指令时触发使用。",
  "license": "MIT (repo-level)",
  "skill_md_url": "https://raw.githubusercontent.com/pa1nrui1/legal-skills/main/skills/legal/%E8%B4%A2%E4%BA%A7%E8%B0%83%E6%9F%A5%E4%B8%8E%E7%AE%A1%E7%90%86/SKILL.md",
  "repository_url": "https://github.com/pa1nrui1/legal-skills",
  "version": "1.0.0",
  "visibility": "public",
  "allowed_groups": [],
  "tags": [
   "legal",
   "chinese-law",
   "pa1nrui1"
  ],
  "metadata": {
   "author": "潘睿（执业律师）",
   "source_repo": "pa1nrui1/legal-skills",
   "skill_dir": "财产调查与管理",
   "name_zh": "财产调查与管理",
   "registration_note": "gateway requires lowercase-alphanumeric names; Chinese name kept in name_zh"
  }
 },
 {
  "name": "bankruptcy-reorganization",
  "description": "破产重整程序全流程管理。覆盖重整申请与受理、重整期间管理、重整计划草案编制、债权分组表决、法院强制批准、重整计划执行与监督等全部环节。适用于管理人（R1）、债权人代理（R2）、债务人代理（R3）三类角色。当用户发送客户编号并提及\"重整\"、\"重整计划\"、\"重整程序\"等指令时触发使用。",
  "license": "MIT (repo-level)",
  "skill_md_url": "https://raw.githubusercontent.com/pa1nrui1/legal-skills/main/skills/legal/%E9%87%8D%E6%95%B4%E7%A8%8B%E5%BA%8F/SKILL.md",
  "repository_url": "https://github.com/pa1nrui1/legal-skills",
  "version": None,
  "visibility": "public",
  "allowed_groups": [],
  "tags": [
   "legal",
   "chinese-law",
   "pa1nrui1"
  ],
  "metadata": {
   "author": "潘睿（执业律师）",
   "source_repo": "pa1nrui1/legal-skills",
   "skill_dir": "重整程序",
   "name_zh": "重整程序",
   "registration_note": "gateway requires lowercase-alphanumeric names; Chinese name kept in name_zh"
  }
 },
 {
  "name": "food-label-compliance",
  "description": "预包装食品标签合规审核技能，用于审核食品标签是否符合 GB 7718（预包装食品标签通则）和 GB 28050（预包装食品营养标签通则）。适用场景：(1) 用户提交食品标签图片、文字或文档要求合规审核时；(2) 用户提到\"食品标签审核\"\"标签合规\"\"营养标签审查\"\"GB 7718\"\"GB 28050\"等关键词时；(3) 用户要求检查食品标签是否存在缺项、错误或违规风险时。支持 2011 版和 2025 版标准。",
  "license": "MIT (repo-level)",
  "skill_md_url": "https://raw.githubusercontent.com/pa1nrui1/legal-skills/main/skills/legal/%E9%A2%84%E5%8C%85%E8%A3%85%E9%A3%9F%E5%93%81%E6%A0%87%E7%AD%BE%E5%90%88%E8%A7%84/SKILL.md",
  "repository_url": "https://github.com/pa1nrui1/legal-skills",
  "version": None,
  "visibility": "public",
  "allowed_groups": [],
  "tags": [
   "legal",
   "chinese-law",
   "pa1nrui1"
  ],
  "metadata": {
   "author": "潘睿（执业律师）",
   "source_repo": "pa1nrui1/legal-skills",
   "skill_dir": "预包装食品标签合规",
   "name_zh": "预包装食品标签合规",
   "registration_note": "gateway requires lowercase-alphanumeric names; Chinese name kept in name_zh"
  }
 },
 # --- THUYRan/Legal-Skills-Chinese (change restore-legal-skills-catalog, 2026-09-18):
 # 38 lawyer-verified Chinese legal-reasoning skills (检索→推理→论证→文书). The repo
 # README declares CC BY-NC-ND 4.0 repo-wide -> every entry below is group-restricted
 # to registry-admins and must be served verbatim (ND: no modified distribution).
 # Curated catalog total after this block: 121 = 65 public + 56 group.
 {
  "name": "legal-abductive-reasoning",
  "description": "法律溯因推理（Abductive Reasoning）技能，用于在证据不完整、事实模糊时生成并评估最合理的解释性假设。结合米尔五法（求同、求异、求同求异、剩余、共变）进行结构化因果推断。当用户需要\"提出可能的法律解释\"、\"生成辩护/起诉假设\"、\"评估证据的多种解读\"或\"基于不完整事实推断最佳解释\"时触发。适用于案例分析、证据评估、规则适用争议、因果关系推断等场景。",
  "license": "CC BY-NC-ND 4.0 (repo-level)",
  "skill_md_url": "https://raw.githubusercontent.com/THUYRan/Legal-Skills-Chinese/main/skills/Legal-Abductive-Reasoning/SKILL.md",
  "repository_url": "https://github.com/THUYRan/Legal-Skills-Chinese",
  "version": None,
  "visibility": "group",
  "allowed_groups": [
   "registry-admins"
  ],
  "tags": [
   "legal",
   "chinese-law",
   "thuyran"
  ],
  "metadata": {
   "author": "Legal-Skills-Chinese 项目团队（执业法律专业人员手写验证）",
   "source_repo": "THUYRan/Legal-Skills-Chinese",
   "skill_dir": "Legal-Abductive-Reasoning",
   "fm_name": "legal-abductive-reasoning",
   "license_note": "repo README declares CC BY-NC-ND 4.0; some skill files mention MIT - treat all as NC-ND until the author grants per-file clarification"
  }
 },
 {
  "name": "normative-meaning-argumentation",
  "description": "分析法律规范的目的、价值导向，以及事实应如何进入规范评价，判断涵摄的限度，需要适当区别于法律解释中的规范目的解释。",
  "license": "CC BY-NC-ND 4.0 (repo-level)",
  "skill_md_url": "https://raw.githubusercontent.com/THUYRan/Legal-Skills-Chinese/main/skills/Normative-Meaning-Argumentation/SKILL.md",
  "repository_url": "https://github.com/THUYRan/Legal-Skills-Chinese",
  "version": None,
  "visibility": "group",
  "allowed_groups": [
   "registry-admins"
  ],
  "tags": [
   "legal",
   "chinese-law",
   "thuyran"
  ],
  "metadata": {
   "author": "Legal-Skills-Chinese 项目团队（执业法律专业人员手写验证）",
   "source_repo": "THUYRan/Legal-Skills-Chinese",
   "skill_dir": "Normative-Meaning-Argumentation",
   "fm_name": "normative-meaning-argumentation",
   "license_note": "repo README declares CC BY-NC-ND 4.0; some skill files mention MIT - treat all as NC-ND until the author grants per-file clarification"
  }
 },
 {
  "name": "administrative-value-judgment",
  "description": "辅助中国大陆行政机关法律工作人员，根据一段行政案情，按行政法基本原则进行价值判断、利益衡量，并形成倾向性裁量结论。",
  "license": "CC BY-NC-ND 4.0 (repo-level)",
  "skill_md_url": "https://raw.githubusercontent.com/THUYRan/Legal-Skills-Chinese/main/skills/administrative-value-judgment/SKILL.md",
  "repository_url": "https://github.com/THUYRan/Legal-Skills-Chinese",
  "version": None,
  "visibility": "group",
  "allowed_groups": [
   "registry-admins"
  ],
  "tags": [
   "legal",
   "chinese-law",
   "thuyran"
  ],
  "metadata": {
   "author": "Legal-Skills-Chinese 项目团队（执业法律专业人员手写验证）",
   "source_repo": "THUYRan/Legal-Skills-Chinese",
   "skill_dir": "administrative-value-judgment",
   "fm_name": "administrative-value-judgment",
   "license_note": "repo README declares CC BY-NC-ND 4.0; some skill files mention MIT - treat all as NC-ND until the author grants per-file clarification"
  }
 },
 {
  "name": "analogical-reasoning",
  "description": "当AI智能体需要处理以下情形时触发本技能： 1. 当前案件/问题在现行法律中没有直接、明确的规定（法律漏洞）； 2. 需要参考已有判例、相似案件或相近法律规范来推导当前问题的处理方案； 3. 用户明确要求\"参照\"\"比照\"\"类推适用\"某一规范或案例； 4. 在法律论证中需要以\"相似案件相似处理\"（Like cases should be treated alike）原则支撑结论； 5. 需要评估两个或多个案件/规范之间的相似性与差异性，以判断能否进行类比； 6. 在合同解释、侵权责任认定、行政处罚裁量等场景中，需要借助类似情形的处理经验形成论证。 本技能的核心是：识别相似性基础（tertium comparationis），论证类比的正当性，并在此基础上得出合理的法律结论。",
  "license": "CC BY-NC-ND 4.0 (repo-level)",
  "skill_md_url": "https://raw.githubusercontent.com/THUYRan/Legal-Skills-Chinese/main/skills/analogical-reasoning/SKILL.md",
  "repository_url": "https://github.com/THUYRan/Legal-Skills-Chinese",
  "version": None,
  "visibility": "group",
  "allowed_groups": [
   "registry-admins"
  ],
  "tags": [
   "legal",
   "chinese-law",
   "thuyran"
  ],
  "metadata": {
   "author": "Legal-Skills-Chinese 项目团队（执业法律专业人员手写验证）",
   "source_repo": "THUYRan/Legal-Skills-Chinese",
   "skill_dir": "analogical-reasoning",
   "fm_name": "analogical-reasoning",
   "license_note": "repo README declares CC BY-NC-ND 4.0; some skill files mention MIT - treat all as NC-ND until the author grants per-file clarification"
  }
 },
 {
  "name": "argument-chain-construction",
  "description": "当AI智能体需要将法律推理结果组织为完整、自洽、有说服力的论证结构时触发此技能。 典型触发场景包括但不限于： - 撰写法律意见书、代理词、辩护词、答辩状等法律文书中的论证部分 - 回答用户提出的复杂法律问题，需要多步骤推理并呈现结论 - 对争议焦点进行系统性分析，需要构建从事实到法律到结论的完整推理路径 - 反驳对方观点时，需要构建替代性论证链条 - 对多个法律问题进行综合分析，需要确保各论证之间逻辑一致、互不矛盾 - 在法律研究备忘录中呈现分析结论 触发信号关键词：论证、分析、推理、为什么、证明、理由、论述、阐述观点、法律分析",
  "license": "CC BY-NC-ND 4.0 (repo-level)",
  "skill_md_url": "https://raw.githubusercontent.com/THUYRan/Legal-Skills-Chinese/main/skills/argument-chain-construction/SKILL.md",
  "repository_url": "https://github.com/THUYRan/Legal-Skills-Chinese",
  "version": None,
  "visibility": "group",
  "allowed_groups": [
   "registry-admins"
  ],
  "tags": [
   "legal",
   "chinese-law",
   "thuyran"
  ],
  "metadata": {
   "author": "Legal-Skills-Chinese 项目团队（执业法律专业人员手写验证）",
   "source_repo": "THUYRan/Legal-Skills-Chinese",
   "skill_dir": "argument-chain-construction",
   "fm_name": "argument-chain-construction",
   "license_note": "repo README declares CC BY-NC-ND 4.0; some skill files mention MIT - treat all as NC-ND until the author grants per-file clarification"
  }
 },
 {
  "name": "argument-strength-evaluation",
  "description": "当AI智能体完成一段法律推理或论证后，需要对该推理结论进行自我评估，判断论证的整体强度与置信度，识别并标注推理链条中的薄弱环节。 触发条件包括但不限于： - 完成法律分析后需要给出结论可靠性评级 - 用户明确要求评估某一论证的说服力或可靠性 - 存在多个竞争性法律解释需要比较论证强度 - 推理过程中涉及不确定因素（事实不明、法律空白、争议观点）需要标注 - 为决策者提供风险提示，说明结论的局限性 - 对己方或对方的法律论证进行攻防强度评估 - 在法律意见书、备忘录等文书中需要附加置信度说明",
  "license": "CC BY-NC-ND 4.0 (repo-level)",
  "skill_md_url": "https://raw.githubusercontent.com/THUYRan/Legal-Skills-Chinese/main/skills/argument-strength-evaluation/SKILL.md",
  "repository_url": "https://github.com/THUYRan/Legal-Skills-Chinese",
  "version": None,
  "visibility": "group",
  "allowed_groups": [
   "registry-admins"
  ],
  "tags": [
   "legal",
   "chinese-law",
   "thuyran"
  ],
  "metadata": {
   "author": "Legal-Skills-Chinese 项目团队（执业法律专业人员手写验证）",
   "source_repo": "THUYRan/Legal-Skills-Chinese",
   "skill_dir": "argument-strength-evaluation",
   "fm_name": "argument-strength-evaluation",
   "license_note": "repo README declares CC BY-NC-ND 4.0; some skill files mention MIT - treat all as NC-ND until the author grants per-file clarification"
  }
 },
 {
  "name": "billing-and-litigation-budget",
  "description": "当用户需要统计、管理律师工时、专家费用、调查费用，控制诉讼成本、向客户出具工时单或费用单时使用此技能。 典型触发场景包括但不限于： - 提到\"工作小时\"\"专家费用\"\"调查费用\"\"办案成本\"\"工时单\"\"费用单\"\"预算\"\"成本控制\"等关键词 - 询问某一律师的工作小时、某一案件的办案费用或诉讼成本时 - 用户要求交付律师工作时长总结或办案工时单、办案费用单，用于交付客户或申请报销时 - 需要对某一案件或常法服务进行预算编制、预算执行监控或预算偏差分析时 - 需要评估诉讼成本与预期收益，进行诉讼经济性分析时",
  "license": "CC BY-NC-ND 4.0 (repo-level)",
  "skill_md_url": "https://raw.githubusercontent.com/THUYRan/Legal-Skills-Chinese/main/skills/billing-and-litigation-budget/SKILL.md",
  "repository_url": "https://github.com/THUYRan/Legal-Skills-Chinese",
  "version": None,
  "visibility": "group",
  "allowed_groups": [
   "registry-admins"
  ],
  "tags": [
   "legal",
   "chinese-law",
   "thuyran"
  ],
  "metadata": {
   "author": "Legal-Skills-Chinese 项目团队（执业法律专业人员手写验证）",
   "source_repo": "THUYRan/Legal-Skills-Chinese",
   "skill_dir": "billing-and-litigation-budget",
   "fm_name": "billing-and-litigation-budget",
   "license_note": "repo README declares CC BY-NC-ND 4.0; some skill files mention MIT - treat all as NC-ND until the author grants per-file clarification"
  }
 },
 {
  "name": "case-lifecycle-planning",
  "description": "案件全周期规划技能。当用户需要规划案件准备时间线、创建或询问案件准备时间节点、生成案件诉讼路线图和关键时间一览表时触发。典型触发关键词：\"案件准备\"\"案件准备规划\"\"案件准备时间线\"\"规划案件准备节奏\"\"排开庭\"。不处理案件向律师的分配，也不处理与案件管理无关的一般性编程任务。",
  "license": "CC BY-NC-ND 4.0 (repo-level)",
  "skill_md_url": "https://raw.githubusercontent.com/THUYRan/Legal-Skills-Chinese/main/skills/case-lifecycle-planning/SKILL.md",
  "repository_url": "https://github.com/THUYRan/Legal-Skills-Chinese",
  "version": None,
  "visibility": "group",
  "allowed_groups": [
   "registry-admins"
  ],
  "tags": [
   "legal",
   "chinese-law",
   "thuyran"
  ],
  "metadata": {
   "author": "Legal-Skills-Chinese 项目团队（执业法律专业人员手写验证）",
   "source_repo": "THUYRan/Legal-Skills-Chinese",
   "skill_dir": "case-lifecycle-planning",
   "fm_name": "case-lifecycle-planning",
   "license_note": "repo README declares CC BY-NC-ND 4.0; some skill files mention MIT - treat all as NC-ND until the author grants per-file clarification"
  }
 },
 {
  "name": "case-retrieval",
  "description": "当用户需要查找与当前法律问题相关的类似案例、相关判决、裁判规则时触发此技能。典型触发场景包括：用户明确要求查找类似案例或判例；需要通过既往裁判支撑法律论点；进行案件预判需要参考同类判决；撰写法律文书需要引用权威案例；分析某一法律问题的司法实践趋势；对比不同法院、不同时期对同一问题的裁判立场。关键词包括但不限于：类似案例、相关判决、判例检索、裁判规则、同类案件、指导性案例、典型案例、司法观点、裁判要旨等。",
  "license": "CC BY-NC-ND 4.0 (repo-level)",
  "skill_md_url": "https://raw.githubusercontent.com/THUYRan/Legal-Skills-Chinese/main/skills/case-retrieval/SKILL.md",
  "repository_url": "https://github.com/THUYRan/Legal-Skills-Chinese",
  "version": None,
  "visibility": "group",
  "allowed_groups": [
   "registry-admins"
  ],
  "tags": [
   "legal",
   "chinese-law",
   "thuyran"
  ],
  "metadata": {
   "author": "Legal-Skills-Chinese 项目团队（执业法律专业人员手写验证）",
   "source_repo": "THUYRan/Legal-Skills-Chinese",
   "skill_dir": "case-retrieval",
   "fm_name": "case-retrieval",
   "license_note": "repo README declares CC BY-NC-ND 4.0; some skill files mention MIT - treat all as NC-ND until the author grants per-file clarification"
  }
 },
 {
  "name": "conflict-resolution",
  "description": "当AI智能体在法律推理过程中遇到以下情形时触发本技能：(1)多个法律条文均可适用于同一事实（法条竞合）；(2)不同证据之间存在矛盾或不一致（证据矛盾）；(3)案件存在多个争议焦点需要确定审理或分析顺序（争点优先级排序）；(4)不同法律渊源（法律、法规、司法解释、地方性法规等）对同一问题作出不同规定（法源冲突）；(5)当事人主张与法律适用之间存在张力需要协调。本技能是法律推理的核心枢纽能力，几乎所有复杂法律分析都会涉及某种形式的冲突解决。",
  "license": "CC BY-NC-ND 4.0 (repo-level)",
  "skill_md_url": "https://raw.githubusercontent.com/THUYRan/Legal-Skills-Chinese/main/skills/conflict-resolution/SKILL.md",
  "repository_url": "https://github.com/THUYRan/Legal-Skills-Chinese",
  "version": None,
  "visibility": "group",
  "allowed_groups": [
   "registry-admins"
  ],
  "tags": [
   "legal",
   "chinese-law",
   "thuyran"
  ],
  "metadata": {
   "author": "Legal-Skills-Chinese 项目团队（执业法律专业人员手写验证）",
   "source_repo": "THUYRan/Legal-Skills-Chinese",
   "skill_dir": "conflict-resolution",
   "fm_name": "conflict-resolution",
   "license_note": "repo README declares CC BY-NC-ND 4.0; some skill files mention MIT - treat all as NC-ND until the author grants per-file clarification"
  }
 },
 {
  "name": "counterfactual-reasoning",
  "description": "当需要评估'如果某一事实/行为/条件不存在或发生改变，法律结果将如何不同'时触发此技能。典型触发场景包括：因果关系认定（若无该行为，损害是否仍会发生）、过错与责任比例划分、损害赔偿范围确定、合同违约损失计算、行政行为合法性假设检验、刑事因果关系中断判断、立法影响评估等。核心方法是构建一个与现实世界仅在目标变量上不同的'反事实世界'，比较两个世界的结果差异，从而得出目标变量对结果的贡献程度。",
  "license": "CC BY-NC-ND 4.0 (repo-level)",
  "skill_md_url": "https://raw.githubusercontent.com/THUYRan/Legal-Skills-Chinese/main/skills/counterfactual-reasoning/SKILL.md",
  "repository_url": "https://github.com/THUYRan/Legal-Skills-Chinese",
  "version": None,
  "visibility": "group",
  "allowed_groups": [
   "registry-admins"
  ],
  "tags": [
   "legal",
   "chinese-law",
   "thuyran"
  ],
  "metadata": {
   "author": "Legal-Skills-Chinese 项目团队（执业法律专业人员手写验证）",
   "source_repo": "THUYRan/Legal-Skills-Chinese",
   "skill_dir": "counterfactual-reasoning",
   "fm_name": "counterfactual-reasoning",
   "license_note": "repo README declares CC BY-NC-ND 4.0; some skill files mention MIT - treat all as NC-ND until the author grants per-file clarification"
  }
 },
 {
  "name": "deductive-reasoning",
  "description": "基于形式逻辑执行严密的法律演绎推理。当用户要求\"分析案件逻辑\"、\"验证法律推理\"、\"提取三段论\"、\"梳理案件事实与法条的关系\"或\"判断法律论证的有效性\"时使用本技能。 为用户提供基于形式逻辑的法律推理框架，将非结构化的法律规范与案件事实转化为有效、可检验、可复现的演绎论证链条（P-F-C）。",
  "license": "CC BY-NC-ND 4.0 (repo-level)",
  "skill_md_url": "https://raw.githubusercontent.com/THUYRan/Legal-Skills-Chinese/main/skills/deductive-reasoning/SKILL.md",
  "repository_url": "https://github.com/THUYRan/Legal-Skills-Chinese",
  "version": None,
  "visibility": "group",
  "allowed_groups": [
   "registry-admins"
  ],
  "tags": [
   "legal",
   "chinese-law",
   "thuyran"
  ],
  "metadata": {
   "author": "Legal-Skills-Chinese 项目团队（执业法律专业人员手写验证）",
   "source_repo": "THUYRan/Legal-Skills-Chinese",
   "skill_dir": "deductive-reasoning",
   "fm_name": "deductive-reasoning",
   "license_note": "repo README declares CC BY-NC-ND 4.0; some skill files mention MIT - treat all as NC-ND until the author grants per-file clarification"
  }
 },
 {
  "name": "dispute-and-performance-risk",
  "description": "当用户提交合同文本、交易安排、商业协议或法律关系描述，需要评估其中可能产生法律纠纷或违约风险时触发此技能。 典型触发场景包括但不限于： - 用户要求审查合同并指出潜在风险 - 用户询问某项交易安排是否存在履约障碍 - 用户描述合同执行中的困难，需要判断是否构成违约 - 用户要求对合同条款进行风险评级 - 用户提供两方或多方之间的协议，要求识别可能的争议焦点 - 用户描述已发生的履约偏差，需要评估法律后果 - 合同审查、尽职调查、交易谈判等场景中需要前瞻性风险识别 此技能聚焦于\"是否会产生法律纠纷\"和\"是否存在违约风险\"两大核心问题， 输出结构化的风险清单与应对建议。",
  "license": "CC BY-NC-ND 4.0 (repo-level)",
  "skill_md_url": "https://raw.githubusercontent.com/THUYRan/Legal-Skills-Chinese/main/skills/dispute-and-performance-risk/SKILL.md",
  "repository_url": "https://github.com/THUYRan/Legal-Skills-Chinese",
  "version": None,
  "visibility": "group",
  "allowed_groups": [
   "registry-admins"
  ],
  "tags": [
   "legal",
   "chinese-law",
   "thuyran"
  ],
  "metadata": {
   "author": "Legal-Skills-Chinese 项目团队（执业法律专业人员手写验证）",
   "source_repo": "THUYRan/Legal-Skills-Chinese",
   "skill_dir": "dispute-and-performance-risk",
   "fm_name": "dispute-and-performance-risk",
   "license_note": "repo README declares CC BY-NC-ND 4.0; some skill files mention MIT - treat all as NC-ND until the author grants per-file clarification"
  }
 },
 {
  "name": "dispute-issue-identification",
  "description": "争议焦点识别是指在法律要素提取之后，从法律事实中提取争议焦点，进一步将案件关系转化为法律关系问题。 能够排除无争议事项，能够有效围绕当事人争议的事实、证据和法律适用等焦点问题进行后续分析。 通过事实调查、证据审查等梳理再次确定争议焦点，可更加深入和靠近争议焦点的本质，将案件剖析的更加充分和透彻。",
  "license": "CC BY-NC-ND 4.0 (repo-level)",
  "skill_md_url": "https://raw.githubusercontent.com/THUYRan/Legal-Skills-Chinese/main/skills/dispute-issue-identification/SKILL.md",
  "repository_url": "https://github.com/THUYRan/Legal-Skills-Chinese",
  "version": None,
  "visibility": "group",
  "allowed_groups": [
   "registry-admins"
  ],
  "tags": [
   "legal",
   "chinese-law",
   "thuyran"
  ],
  "metadata": {
   "author": "Legal-Skills-Chinese 项目团队（执业法律专业人员手写验证）",
   "source_repo": "THUYRan/Legal-Skills-Chinese",
   "skill_dir": "dispute-issue-identification",
   "fm_name": "dispute-issue-identification",
   "license_note": "repo README declares CC BY-NC-ND 4.0; some skill files mention MIT - treat all as NC-ND until the author grants per-file clarification"
  }
 },
 {
  "name": "evidence-argument-chain",
  "description": "当需要将案件中的多项证据与法律论证主张进行系统性对应挂钩时触发此技能。 典型触发场景包括：准备诉讼文书（起诉状、答辩状、代理词）时需要构建完整的证据-主张对应关系； 庭审前整理证据目录并明确每项证据的证明目的；对方提出反驳后需要重新组织证据链以回应； 案件涉及多个争议焦点，需要将证据分组归类到不同论证主张下； 需要评估现有证据是否足以支撑全部主张，识别证据链中的薄弱环节和缺口。 本技能的核心是建立\"主张→要件→证据→证明力评估\"的完整映射关系，确保每个法律主张都有充分的证据支撑， 每项证据都有明确的证明目的，整体论证链条逻辑严密、层次清晰。",
  "license": "CC BY-NC-ND 4.0 (repo-level)",
  "skill_md_url": "https://raw.githubusercontent.com/THUYRan/Legal-Skills-Chinese/main/skills/evidence-argument-chain/SKILL.md",
  "repository_url": "https://github.com/THUYRan/Legal-Skills-Chinese",
  "version": None,
  "visibility": "group",
  "allowed_groups": [
   "registry-admins"
  ],
  "tags": [
   "legal",
   "chinese-law",
   "thuyran"
  ],
  "metadata": {
   "author": "Legal-Skills-Chinese 项目团队（执业法律专业人员手写验证）",
   "source_repo": "THUYRan/Legal-Skills-Chinese",
   "skill_dir": "evidence-argument-chain",
   "fm_name": "evidence-argument-chain",
   "license_note": "repo README declares CC BY-NC-ND 4.0; some skill files mention MIT - treat all as NC-ND until the author grants per-file clarification"
  }
 },
 {
  "name": "evidence-evaluation",
  "description": "当需要对案件中的证据材料进行真实性、合法性、关联性（证据\"三性\"）及证明力评估时触发此技能。 典型触发场景包括但不限于： - 当事人或代理人提交证据后，需要判断该证据能否被法庭采纳 - 对方当事人对己方证据提出质证意见，需要进行回应和分析 - 需要对全案证据进行综合评判，确定待证事实是否成立 - 需要判断证据是否达到相应的证明标准（如高度盖然性、排除合理怀疑等） - 需要识别证据链中的薄弱环节并提出补强建议 - 电子数据、鉴定意见、证人证言等特殊证据形式的效力判断 - 非法证据排除的识别与论证",
  "license": "CC BY-NC-ND 4.0 (repo-level)",
  "skill_md_url": "https://raw.githubusercontent.com/THUYRan/Legal-Skills-Chinese/main/skills/evidence-evaluation/SKILL.md",
  "repository_url": "https://github.com/THUYRan/Legal-Skills-Chinese",
  "version": None,
  "visibility": "group",
  "allowed_groups": [
   "registry-admins"
  ],
  "tags": [
   "legal",
   "chinese-law",
   "thuyran"
  ],
  "metadata": {
   "author": "Legal-Skills-Chinese 项目团队（执业法律专业人员手写验证）",
   "source_repo": "THUYRan/Legal-Skills-Chinese",
   "skill_dir": "evidence-evaluation",
   "fm_name": "evidence-evaluation",
   "license_note": "repo README declares CC BY-NC-ND 4.0; some skill files mention MIT - treat all as NC-ND until the author grants per-file clarification"
  }
 },
 {
  "name": "formal-legal-consequence",
  "description": "当需要根据已确认的法律事实、已识别的法律关系和已匹配的法律规范，推导出具体的法律后果（包括但不限于民事责任类型与范围、损害赔偿金额计算、刑事刑期确定、行政处罚种类与幅度、合同效力状态等）时，触发本技能。 典型触发场景包括： - 用户询问\"我能获得多少赔偿\"\"对方要承担什么责任\" - 用户询问\"这个行为会判几年\"\"罚款多少\" - 需要从法律构成要件满足情况推导出具体法律效果 - 需要计算具体赔偿数额、刑期范围、违约金数额等量化结果 - 需要综合考虑加重、减轻、免除等调整因素后得出最终法律后果 本技能是法律推理链条的终端环节，将抽象的法律规范转化为具体的、可操作的法律结论。",
  "license": "CC BY-NC-ND 4.0 (repo-level)",
  "skill_md_url": "https://raw.githubusercontent.com/THUYRan/Legal-Skills-Chinese/main/skills/formal-legal-consequence/SKILL.md",
  "repository_url": "https://github.com/THUYRan/Legal-Skills-Chinese",
  "version": None,
  "visibility": "group",
  "allowed_groups": [
   "registry-admins"
  ],
  "tags": [
   "legal",
   "chinese-law",
   "thuyran"
  ],
  "metadata": {
   "author": "Legal-Skills-Chinese 项目团队（执业法律专业人员手写验证）",
   "source_repo": "THUYRan/Legal-Skills-Chinese",
   "skill_dir": "formal-legal-consequence",
   "fm_name": "formal-legal-consequence",
   "license_note": "repo README declares CC BY-NC-ND 4.0; some skill files mention MIT - treat all as NC-ND until the author grants per-file clarification"
  }
 },
 {
  "name": "inductive-reasoning",
  "description": "当需要从一个或多个具体案例、判决、事实模式中提炼、总结出一般性法律规则、裁判规则或法律原则时，触发此技能。典型触发场景包括：用户要求从系列案例中归纳裁判要旨、从个案中提炼可推广的法律命题、从多个事实模式中识别共同法律规则、构建类案检索的裁判规则摘要、以及从实务判例中总结司法适用标准。",
  "license": "CC BY-NC-ND 4.0 (repo-level)",
  "skill_md_url": "https://raw.githubusercontent.com/THUYRan/Legal-Skills-Chinese/main/skills/inductive-reasoning/SKILL.md",
  "repository_url": "https://github.com/THUYRan/Legal-Skills-Chinese",
  "version": None,
  "visibility": "group",
  "allowed_groups": [
   "registry-admins"
  ],
  "tags": [
   "legal",
   "chinese-law",
   "thuyran"
  ],
  "metadata": {
   "author": "Legal-Skills-Chinese 项目团队（执业法律专业人员手写验证）",
   "source_repo": "THUYRan/Legal-Skills-Chinese",
   "skill_dir": "inductive-reasoning",
   "fm_name": "inductive-reasoning",
   "license_note": "repo README declares CC BY-NC-ND 4.0; some skill files mention MIT - treat all as NC-ND until the author grants per-file clarification"
  }
 },
 {
  "name": "internal-compliance-risk-identification",
  "description": "当需要对企业内部的合规管理体系进行系统性审查，识别制度缺漏、流程缺陷和数据隐私合规风险时触发此技能。 典型触发场景包括但不限于： - 企业委托律师或合规顾问进行内部合规风险评估 - 企业拟上市、并购或接受监管检查前进行合规自查 - 发生合规事件后，需要排查管理体系中的系统性缺陷 - 企业建立或更新合规管理体系时，需要评估现有制度与法律法规的匹配度 - 用户要求审查企业内部规章制度、核心业务流程或隐私政策协议的合规性 本技能覆盖三大审查维度：制度体系完整性审查、业务流程控制有效性审查、个人信息保护合规性审查。",
  "license": "CC BY-NC-ND 4.0 (repo-level)",
  "skill_md_url": "https://raw.githubusercontent.com/THUYRan/Legal-Skills-Chinese/main/skills/internal-compliance-risk-identification/SKILL.md",
  "repository_url": "https://github.com/THUYRan/Legal-Skills-Chinese",
  "version": None,
  "visibility": "group",
  "allowed_groups": [
   "registry-admins"
  ],
  "tags": [
   "legal",
   "chinese-law",
   "thuyran"
  ],
  "metadata": {
   "author": "Legal-Skills-Chinese 项目团队（执业法律专业人员手写验证）",
   "source_repo": "THUYRan/Legal-Skills-Chinese",
   "skill_dir": "internal-compliance-risk-identification",
   "fm_name": "internal-compliance-risk-identification",
   "license_note": "repo README declares CC BY-NC-ND 4.0; some skill files mention MIT - treat all as NC-ND until the author grants per-file clarification"
  }
 },
 {
  "name": "judgment-document-generation",
  "description": "根据案件事实描述，协调调用8个原子能力，生成格式规范、论证严密的完整刑事判决书。涵盖事实认定、法律适用、量刑推理及文书输出全流程。",
  "license": "CC BY-NC-ND 4.0 (repo-level)",
  "skill_md_url": "https://raw.githubusercontent.com/THUYRan/Legal-Skills-Chinese/main/skills/judgment-document-generation/SKILL.md",
  "repository_url": "https://github.com/THUYRan/Legal-Skills-Chinese",
  "version": None,
  "visibility": "group",
  "allowed_groups": [
   "registry-admins"
  ],
  "tags": [
   "legal",
   "chinese-law",
   "thuyran"
  ],
  "metadata": {
   "author": "Legal-Skills-Chinese 项目团队（执业法律专业人员手写验证）",
   "source_repo": "THUYRan/Legal-Skills-Chinese",
   "skill_dir": "judgment-document-generation",
   "fm_name": "judgment-document-generation",
   "license_note": "repo README declares CC BY-NC-ND 4.0; some skill files mention MIT - treat all as NC-ND until the author grants per-file clarification"
  }
 },
 {
  "name": "judicial-value-judgment",
  "description": "辅助法官在权利冲突、法律不确定、比例原则审查和裁量说理场景中，进行结构化、可审查、可论证的司法价值判断。 本 Skill 用于辅助法官在疑难案件中识别法律价值冲突、确定裁量边界、展开价值衡量，并形成可用于裁判说理的分析框架，不替代法官作出最终裁判，而是帮助法官将价值判断转化为有事实基础、规范基础和论证结构的司法推理过程。",
  "license": "CC BY-NC-ND 4.0 (repo-level)",
  "skill_md_url": "https://raw.githubusercontent.com/THUYRan/Legal-Skills-Chinese/main/skills/judicial-value-judgment/SKILL.md",
  "repository_url": "https://github.com/THUYRan/Legal-Skills-Chinese",
  "version": None,
  "visibility": "group",
  "allowed_groups": [
   "registry-admins"
  ],
  "tags": [
   "legal",
   "chinese-law",
   "thuyran"
  ],
  "metadata": {
   "author": "Legal-Skills-Chinese 项目团队（执业法律专业人员手写验证）",
   "source_repo": "THUYRan/Legal-Skills-Chinese",
   "skill_dir": "judicial-value-judgment",
   "fm_name": "judicial-value-judgment",
   "license_note": "repo README declares CC BY-NC-ND 4.0; some skill files mention MIT - treat all as NC-ND until the author grants per-file clarification"
  }
 },
 {
  "name": "legal-article-retrieval",
  "description": "生成标准化法律检索报告，适用于案例检索、法条检索、类案分析等法律研究场景。当用户需要进行行业或专业分析、预测裁判结果、复核法律依据的有效性、确认请求、抗辩主张的法律依据、分析司法实践倾向等任务时使用。支持诉讼方案评估、庭审准备、合规审查、法律培训等各类法律实务场景。",
  "license": "CC BY-NC-ND 4.0 (repo-level)",
  "skill_md_url": "https://raw.githubusercontent.com/THUYRan/Legal-Skills-Chinese/main/skills/legal-article-retrieval/SKILL.md",
  "repository_url": "https://github.com/THUYRan/Legal-Skills-Chinese",
  "version": None,
  "visibility": "group",
  "allowed_groups": [
   "registry-admins"
  ],
  "tags": [
   "legal",
   "chinese-law",
   "thuyran"
  ],
  "metadata": {
   "author": "Legal-Skills-Chinese 项目团队（执业法律专业人员手写验证）",
   "source_repo": "THUYRan/Legal-Skills-Chinese",
   "skill_dir": "legal-article-retrieval",
   "fm_name": "legal-article-retrieval",
   "license_note": "repo README declares CC BY-NC-ND 4.0; some skill files mention MIT - treat all as NC-ND until the author grants per-file clarification"
  }
 },
 {
  "name": "legal-concept-comprehension",
  "description": "当用户要求解释、辨析、拆解或理解某个法律概念时触发此技能。 典型触发场景包括但不限于： - 用户直接询问\"什么是XX\"\"如何理解XX\" - 用户要求比较两个法律概念的异同（如\"不当得利与无因管理的区别\"） - 用户给出具体事实，询问是否构成某法律概念（如\"甲误将钱转给乙，是否构成不当得利？\"） - 用户在法律分析、文书写作、合同审查中遇到不熟悉的术语 - 用户要求拆解某概念的构成要件或分析其法律效果 本技能是法律分析的基础单元，为法律规则适用、案件分析、法律文书写作等提供概念基础。",
  "license": "CC BY-NC-ND 4.0 (repo-level)",
  "skill_md_url": "https://raw.githubusercontent.com/THUYRan/Legal-Skills-Chinese/main/skills/legal-concept-comprehension/SKILL.md",
  "repository_url": "https://github.com/THUYRan/Legal-Skills-Chinese",
  "version": None,
  "visibility": "group",
  "allowed_groups": [
   "registry-admins"
  ],
  "tags": [
   "legal",
   "chinese-law",
   "thuyran"
  ],
  "metadata": {
   "author": "Legal-Skills-Chinese 项目团队（执业法律专业人员手写验证）",
   "source_repo": "THUYRan/Legal-Skills-Chinese",
   "skill_dir": "legal-concept-comprehension",
   "fm_name": "legal-concept-comprehension",
   "license_note": "repo README declares CC BY-NC-ND 4.0; some skill files mention MIT - treat all as NC-ND until the author grants per-file clarification"
  }
 },
 {
  "name": "legal-document-formatting",
  "description": "基于中国人民法院裁判文书制作规范，起草完整的民事判决书或刑事判决书。当用户要求\"起草判决书\"、\"生成裁判文书\"、\"写民事判决书\"、\"写刑事判决书\"、\"根据案卷写文书\"或提供案卷材料要求输出裁判文书时使用本技能，在起草各段落时自主调用原子技能（如争议焦点识别、法条检索、演绎推理、证据效力评估等）。",
  "license": "CC BY-NC-ND 4.0 (repo-level)",
  "skill_md_url": "https://raw.githubusercontent.com/THUYRan/Legal-Skills-Chinese/main/skills/legal-document-formatting/SKILL.md",
  "repository_url": "https://github.com/THUYRan/Legal-Skills-Chinese",
  "version": None,
  "visibility": "group",
  "allowed_groups": [
   "registry-admins"
  ],
  "tags": [
   "legal",
   "chinese-law",
   "thuyran"
  ],
  "metadata": {
   "author": "Legal-Skills-Chinese 项目团队（执业法律专业人员手写验证）",
   "source_repo": "THUYRan/Legal-Skills-Chinese",
   "skill_dir": "legal-document-formatting",
   "fm_name": "legal-document-formatting",
   "license_note": "repo README declares CC BY-NC-ND 4.0; some skill files mention MIT - treat all as NC-ND until the author grants per-file clarification"
  }
 },
 {
  "name": "legal-document-summarization",
  "description": "当需要对判决书、裁定书、调解书、仲裁裁决书、行政处罚决定书等法律文书进行结构化摘要时触发此技能。 典型触发场景包括但不限于： - 用户要求对一份法律文书做摘要、提炼要点或生成裁判要旨 - 用户需要将多份法律文书转化为可对比、可检索的标准化摘要 - 用户要求提取案件信息、争议焦点、法律依据或说理过程 - 用户需要为案例研究、诉讼分析、教学备课准备摘要材料 - 用户要求区分不同文书类型（判决/裁定/调解/仲裁/行政处罚）的摘要重点 本技能的核心价值：在忠实于原文的基础上，将冗长法律文书转化为简明、客观、结构化的摘要，突出核心内容，避免复述全文和主观评价。",
  "license": "CC BY-NC-ND 4.0 (repo-level)",
  "skill_md_url": "https://raw.githubusercontent.com/THUYRan/Legal-Skills-Chinese/main/skills/legal-document-summarization/SKILL.md",
  "repository_url": "https://github.com/THUYRan/Legal-Skills-Chinese",
  "version": None,
  "visibility": "group",
  "allowed_groups": [
   "registry-admins"
  ],
  "tags": [
   "legal",
   "chinese-law",
   "thuyran"
  ],
  "metadata": {
   "author": "Legal-Skills-Chinese 项目团队（执业法律专业人员手写验证）",
   "source_repo": "THUYRan/Legal-Skills-Chinese",
   "skill_dir": "legal-document-summarization",
   "fm_name": "legal-document-summarization",
   "license_note": "repo README declares CC BY-NC-ND 4.0; some skill files mention MIT - treat all as NC-ND until the author grants per-file clarification"
  }
 },
 {
  "name": "legal-element-extraction",
  "description": "当需要从案件描述、当事人陈述、聊天记录、媒体报道等非结构化文本中提取具有法律意义的事实时触发此技能。 典型触发场景包括但不限于： - 用户提供一段日常语言的案件描述，要求提取法律事实 - 用户要求将口语化、情绪化的叙事转化为法律分析可用的事实结构 - 用户要求区分案件叙述中的\"客观事实\"\"主观判断\"和\"法律评价\" - 用户要求将提取的事实对应到特定法律关系的构成要件 - 用户要求整理案件时间轴或制作事实梳理表 - 用户要求将生活语言转化为法律语言（如\"他一直拖着不还\"→\"履行期限届满后未履行\"） 本技能的核心价值：将混杂的生活叙事整理为可进入法律推理的事实结构，是法律分析的前置步骤。",
  "license": "CC BY-NC-ND 4.0 (repo-level)",
  "skill_md_url": "https://raw.githubusercontent.com/THUYRan/Legal-Skills-Chinese/main/skills/legal-element-extraction/SKILL.md",
  "repository_url": "https://github.com/THUYRan/Legal-Skills-Chinese",
  "version": None,
  "visibility": "group",
  "allowed_groups": [
   "registry-admins"
  ],
  "tags": [
   "legal",
   "chinese-law",
   "thuyran"
  ],
  "metadata": {
   "author": "Legal-Skills-Chinese 项目团队（执业法律专业人员手写验证）",
   "source_repo": "THUYRan/Legal-Skills-Chinese",
   "skill_dir": "legal-element-extraction",
   "fm_name": "legal-element-extraction",
   "license_note": "repo README declares CC BY-NC-ND 4.0; some skill files mention MIT - treat all as NC-ND until the author grants per-file clarification"
  }
 },
 {
  "name": "legal-interpretation-argument",
  "description": "当法律推理过程中遇到以下情形时触发本技能： （1）法条文本含义模糊、存在多种理解可能； （2）法条适用于具体案件事实时产生争议； （3）需要论证某一法条应当/不应当适用于特定情形； （4）当事人双方对同一法条的理解存在分歧； （5）法条之间存在表面冲突，需要通过解释协调； （6）新型案件事实无法直接对应既有法条文本； （7）需要对裁判文书中的法律适用进行分析或质疑。 本技能的核心是运用文义解释、体系解释、目的解释等法律解释方法，对关键法条进行严谨的解释论证，得出合理、可辩护的法律含义，并以规范化的方式呈现解释过程与结论。",
  "license": "CC BY-NC-ND 4.0 (repo-level)",
  "skill_md_url": "https://raw.githubusercontent.com/THUYRan/Legal-Skills-Chinese/main/skills/legal-interpretation-argument/SKILL.md",
  "repository_url": "https://github.com/THUYRan/Legal-Skills-Chinese",
  "version": None,
  "visibility": "group",
  "allowed_groups": [
   "registry-admins"
  ],
  "tags": [
   "legal",
   "chinese-law",
   "thuyran"
  ],
  "metadata": {
   "author": "Legal-Skills-Chinese 项目团队（执业法律专业人员手写验证）",
   "source_repo": "THUYRan/Legal-Skills-Chinese",
   "skill_dir": "legal-interpretation-argument",
   "fm_name": "legal-interpretation-argument",
   "license_note": "repo README declares CC BY-NC-ND 4.0; some skill files mention MIT - treat all as NC-ND until the author grants per-file clarification"
  }
 },
 {
  "name": "legal-judgment-prediction",
  "description": "根据案件事实描述，综合调用8个原子能力，预测罪名、适用法条、刑期及量刑情节，输出结构化预测报告及置信度评估。",
  "license": "CC BY-NC-ND 4.0 (repo-level)",
  "skill_md_url": "https://raw.githubusercontent.com/THUYRan/Legal-Skills-Chinese/main/skills/legal-judgment-prediction/SKILL.md",
  "repository_url": "https://github.com/THUYRan/Legal-Skills-Chinese",
  "version": None,
  "visibility": "group",
  "allowed_groups": [
   "registry-admins"
  ],
  "tags": [
   "legal",
   "chinese-law",
   "thuyran"
  ],
  "metadata": {
   "author": "Legal-Skills-Chinese 项目团队（执业法律专业人员手写验证）",
   "source_repo": "THUYRan/Legal-Skills-Chinese",
   "skill_dir": "legal-judgment-prediction",
   "fm_name": "legal-judgment-prediction",
   "license_note": "repo README declares CC BY-NC-ND 4.0; some skill files mention MIT - treat all as NC-ND until the author grants per-file clarification"
  }
 },
 {
  "name": "legal-norm-validity-check",
  "description": "当AI智能体在法律推理过程中检索到具体法律条文后，需要对该法条进行效力验证时触发此技能。 触发条件包括但不限于： 1. 智能体引用任何法律条文作为推理依据前； 2. 用户提供法条要求分析其适用性时； 3. 多个法律规范可能存在冲突需要判断优先适用时； 4. 法律文件的时间效力存疑（可能已被修订、废止）时； 5. 需要确认某规范性文件是否具有法律约束力时； 6. 跨层级、跨区域法律规范适用产生疑问时。 本技能确保智能体引用的每一条法律规范均为现行有效、层级正确、与上位法及同位法无冲突， 从而保障法律推理结论的可靠性和权威性。",
  "license": "CC BY-NC-ND 4.0 (repo-level)",
  "skill_md_url": "https://raw.githubusercontent.com/THUYRan/Legal-Skills-Chinese/main/skills/legal-norm-validity-check/SKILL.md",
  "repository_url": "https://github.com/THUYRan/Legal-Skills-Chinese",
  "version": None,
  "visibility": "group",
  "allowed_groups": [
   "registry-admins"
  ],
  "tags": [
   "legal",
   "chinese-law",
   "thuyran"
  ],
  "metadata": {
   "author": "Legal-Skills-Chinese 项目团队（执业法律专业人员手写验证）",
   "source_repo": "THUYRan/Legal-Skills-Chinese",
   "skill_dir": "legal-norm-validity-check",
   "fm_name": "legal-norm-validity-check",
   "license_note": "repo README declares CC BY-NC-ND 4.0; some skill files mention MIT - treat all as NC-ND until the author grants per-file clarification"
  }
 },
 {
  "name": "legal-risk-assessment",
  "description": "从许可资质、监管法规遵循及历史处罚记录四个维度评估企业面临的监管处罚风险。",
  "license": "CC BY-NC-ND 4.0 (repo-level)",
  "skill_md_url": "https://raw.githubusercontent.com/THUYRan/Legal-Skills-Chinese/main/skills/legal-risk-assessment/SKILL.md",
  "repository_url": "https://github.com/THUYRan/Legal-Skills-Chinese",
  "version": None,
  "visibility": "group",
  "allowed_groups": [
   "registry-admins"
  ],
  "tags": [
   "legal",
   "chinese-law",
   "thuyran"
  ],
  "metadata": {
   "author": "Legal-Skills-Chinese 项目团队（执业法律专业人员手写验证）",
   "source_repo": "THUYRan/Legal-Skills-Chinese",
   "skill_dir": "legal-risk-assessment",
   "fm_name": "legal-risk-assessment",
   "license_note": "repo README declares CC BY-NC-ND 4.0; some skill files mention MIT - treat all as NC-ND until the author grants per-file clarification"
  }
 },
 {
  "name": "legal-terminology",
  "description": "当AI智能体在生成、审查或修改任何法律文本（包括但不限于合同、诉状、法律意见书、裁判文书、法规释义、法律备忘录等）时，需要确保其中使用的法律术语措辞准确、无歧义、符合法律文体要求。该技能在以下场景触发： 1. 起草或修改法律文书时，需要选择正确的法律术语； 2. 审查法律文本时，发现术语使用不规范、混淆或存在歧义； 3. 将日常用语转化为法律规范表达时； 4. 翻译或对照中外法律术语时； 5. 用户明确要求对法律文本进行术语规范化处理时； 6. 对法律概念进行精确定义或解释时。 本技能是法律写作的基础原子能力，贯穿所有法律文本生产环节。",
  "license": "CC BY-NC-ND 4.0 (repo-level)",
  "skill_md_url": "https://raw.githubusercontent.com/THUYRan/Legal-Skills-Chinese/main/skills/legal-terminology/SKILL.md",
  "repository_url": "https://github.com/THUYRan/Legal-Skills-Chinese",
  "version": None,
  "visibility": "group",
  "allowed_groups": [
   "registry-admins"
  ],
  "tags": [
   "legal",
   "chinese-law",
   "thuyran"
  ],
  "metadata": {
   "author": "Legal-Skills-Chinese 项目团队（执业法律专业人员手写验证）",
   "source_repo": "THUYRan/Legal-Skills-Chinese",
   "skill_dir": "legal-terminology",
   "fm_name": "legal-terminology",
   "license_note": "repo README declares CC BY-NC-ND 4.0; some skill files mention MIT - treat all as NC-ND until the author grants per-file clarification"
  }
 },
 {
  "name": "multi-document-summarization",
  "description": "当需要对多份相关文档进行综合分析、提取共同观点、识别冲突并生成统一概览时触发此技能。 典型触发场景包括但不限于： - 用户上传多份判决书、裁定书，要求总结类案裁判要旨 - 用户提供多个合同文本，要求归纳条款异同和关键差异 - 用户提供多份法律法规、司法解释，要求梳理规范演变和适用要点 - 用户提供多个证据材料、调查笔录，要求整合事实脉络 - 用户提供多篇学术论文、研究报告，要求提炼研究共识和分歧 - 用户要求对比多份法律意见书的观点差异 本技能的核心价值：不是简单压缩单篇文档，而是构建跨文档的关联分析，识别共性与差异，生成新的综合性洞见。",
  "license": "CC BY-NC-ND 4.0 (repo-level)",
  "skill_md_url": "https://raw.githubusercontent.com/THUYRan/Legal-Skills-Chinese/main/skills/multi-document-summarization/SKILL.md",
  "repository_url": "https://github.com/THUYRan/Legal-Skills-Chinese",
  "version": None,
  "visibility": "group",
  "allowed_groups": [
   "registry-admins"
  ],
  "tags": [
   "legal",
   "chinese-law",
   "thuyran"
  ],
  "metadata": {
   "author": "Legal-Skills-Chinese 项目团队（执业法律专业人员手写验证）",
   "source_repo": "THUYRan/Legal-Skills-Chinese",
   "skill_dir": "multi-document-summarization",
   "fm_name": "multi-document-summarization",
   "license_note": "repo README declares CC BY-NC-ND 4.0; some skill files mention MIT - treat all as NC-ND until the author grants per-file clarification"
  }
 },
 {
  "name": "other-legal-retrieval",
  "description": "当智能体需要检索法律条文、司法解释、典型案例之外的辅助性法律信息时触发此技能。具体包括但不限于：立法背景资料（草案说明、审议报告、立法机关答记者问）、监管案例与行政处罚决定、地方指导意见与会议纪要、部门规章的起草说明与政策解读、行业标准与技术规范、法律实施情况报告、人大常委会执法检查报告、白皮书与政策文件、学术通说与权威教材观点、域外法律比较资料等。当用户问题涉及'为什么这样规定''立法目的是什么''实践中监管部门怎么处理''地方上有什么特殊规定''行业惯例是什么'等语境时，应当触发本技能。",
  "license": "CC BY-NC-ND 4.0 (repo-level)",
  "skill_md_url": "https://raw.githubusercontent.com/THUYRan/Legal-Skills-Chinese/main/skills/other-legal-retrieval/SKILL.md",
  "repository_url": "https://github.com/THUYRan/Legal-Skills-Chinese",
  "version": None,
  "visibility": "group",
  "allowed_groups": [
   "registry-admins"
  ],
  "tags": [
   "legal",
   "chinese-law",
   "thuyran"
  ],
  "metadata": {
   "author": "Legal-Skills-Chinese 项目团队（执业法律专业人员手写验证）",
   "source_repo": "THUYRan/Legal-Skills-Chinese",
   "skill_dir": "other-legal-retrieval",
   "fm_name": "other-legal-retrieval",
   "license_note": "repo README declares CC BY-NC-ND 4.0; some skill files mention MIT - treat all as NC-ND until the author grants per-file clarification"
  }
 },
 {
  "name": "strategic-risk-prioritization",
  "description": "当法律分析中存在多个可能的结论、风险点或争议焦点时，需要对这些风险按照发生概率和影响程度进行系统化排序，以帮助决策者聚焦最关键的风险并合理分配资源。该技能在以下场景触发：(1)法律尽职调查中发现多项合规风险需要排序；(2)诉讼策略制定中需要评估多个不利结论的可能性与后果；(3)交易结构设计中需要识别并排列关键法律障碍；(4)合同审查中发现多个风险条款需要确定修改优先级；(5)监管合规评估中需要对多项违规风险进行分级管理；(6)任何需要在有限资源下对法律风险进行战略性取舍的场景。",
  "license": "CC BY-NC-ND 4.0 (repo-level)",
  "skill_md_url": "https://raw.githubusercontent.com/THUYRan/Legal-Skills-Chinese/main/skills/strategic-risk-prioritization/SKILL.md",
  "repository_url": "https://github.com/THUYRan/Legal-Skills-Chinese",
  "version": None,
  "visibility": "group",
  "allowed_groups": [
   "registry-admins"
  ],
  "tags": [
   "legal",
   "chinese-law",
   "thuyran"
  ],
  "metadata": {
   "author": "Legal-Skills-Chinese 项目团队（执业法律专业人员手写验证）",
   "source_repo": "THUYRan/Legal-Skills-Chinese",
   "skill_dir": "strategic-risk-prioritization",
   "fm_name": "strategic-risk-prioritization",
   "license_note": "repo README declares CC BY-NC-ND 4.0; some skill files mention MIT - treat all as NC-ND until the author grants per-file clarification"
  }
 },
 {
  "name": "structured-element-extraction",
  "description": "当AI智能体需要对一个法律问题、案件事实、法律条文或法律关系进行系统性分析时，首先必须将其分解为结构化的要素清单。该技能在以下场景触发： - 接收到一段案件事实描述，需要提取全部法律要素后再进行分析 - 需要判断某一法律关系是否成立（如合同成立、侵权构成、犯罪构成） - 需要对比两个或多个法律事实/条文的异同 - 在进入法律推理、法律适用、法律建议等下游任务之前，作为前置质量关卡 - 用户明确要求\"列出要素\"\"逐项分析\"\"检查是否遗漏\" 本技能的核心目标是：确保要素提取完整、无遗漏，形成可追溯、可验证的结构化清单，然后才允许进入下一阶段推理。它是法律分析链条中的\"质量闸门\"。",
  "license": "CC BY-NC-ND 4.0 (repo-level)",
  "skill_md_url": "https://raw.githubusercontent.com/THUYRan/Legal-Skills-Chinese/main/skills/structured-element-extraction/SKILL.md",
  "repository_url": "https://github.com/THUYRan/Legal-Skills-Chinese",
  "version": None,
  "visibility": "group",
  "allowed_groups": [
   "registry-admins"
  ],
  "tags": [
   "legal",
   "chinese-law",
   "thuyran"
  ],
  "metadata": {
   "author": "Legal-Skills-Chinese 项目团队（执业法律专业人员手写验证）",
   "source_repo": "THUYRan/Legal-Skills-Chinese",
   "skill_dir": "structured-element-extraction",
   "fm_name": "structured-element-extraction",
   "license_note": "repo README declares CC BY-NC-ND 4.0; some skill files mention MIT - treat all as NC-ND until the author grants per-file clarification"
  }
 },
 {
  "name": "systematic-interpretation",
  "description": "体系解释是指针对法律规范文义解释后所产生的含义或适用范围上的争议，根据法律规范在法律体系中的位置（如在哪一部法律、编、章或节），关联的法律规范的含义，或者法律作为一个体系的应由之意，做出最符合体系性的解释，从而明确体系视角下法律规范的含义与适用范围。 触发条件（满足任一即可调用）：",
  "license": "CC BY-NC-ND 4.0 (repo-level)",
  "skill_md_url": "https://raw.githubusercontent.com/THUYRan/Legal-Skills-Chinese/main/skills/systematic-interpretation/SKILL.md",
  "repository_url": "https://github.com/THUYRan/Legal-Skills-Chinese",
  "version": None,
  "visibility": "group",
  "allowed_groups": [
   "registry-admins"
  ],
  "tags": [
   "legal",
   "chinese-law",
   "thuyran"
  ],
  "metadata": {
   "author": "Legal-Skills-Chinese 项目团队（执业法律专业人员手写验证）",
   "source_repo": "THUYRan/Legal-Skills-Chinese",
   "skill_dir": "systematic-interpretation",
   "fm_name": "systematic-interpretation",
   "license_note": "repo README declares CC BY-NC-ND 4.0; some skill files mention MIT - treat all as NC-ND until the author grants per-file clarification"
  }
 },
 {
  "name": "teleological-interpretation",
  "description": "目的解释技能。当法律条文经过文义解释后仍无法得出确定结论时，通过系统性地发现并论证该条文的目的，在文本可承受范围内选择最正当的含义，形成可裁判的解释结论。触发条件（满足任一即可）：文义解释存在两种以上可能无法择一；文义解释结论明显不合理；条文含开放性评价概念（如\"合理\"\"正当\"\"必要\"\"重大\"）；条文较旧、面对新型事实时文义覆盖不足。",
  "license": "CC BY-NC-ND 4.0 (repo-level)",
  "skill_md_url": "https://raw.githubusercontent.com/THUYRan/Legal-Skills-Chinese/main/skills/teleological-interpretation/SKILL.md",
  "repository_url": "https://github.com/THUYRan/Legal-Skills-Chinese",
  "version": None,
  "visibility": "group",
  "allowed_groups": [
   "registry-admins"
  ],
  "tags": [
   "legal",
   "chinese-law",
   "thuyran"
  ],
  "metadata": {
   "author": "Legal-Skills-Chinese 项目团队（执业法律专业人员手写验证）",
   "source_repo": "THUYRan/Legal-Skills-Chinese",
   "skill_dir": "teleological-interpretation",
   "fm_name": "teleological-interpretation",
   "license_note": "repo README declares CC BY-NC-ND 4.0; some skill files mention MIT - treat all as NC-ND until the author grants per-file clarification"
  }
 },
 {
  "name": "trial-scheduling-and-deadline-monitoring",
  "description": "当用户需要跟踪、被提醒案件的开庭排期、执行排期、证据提交期限、上诉期限、送达期限、保全续保等各项法定期限时，使用此技能。 典型触发场景包括但不限于： - 提到\"上诉期限\"\"证据提交期限\"\"送达期限\"\"保全期限\"等关键词 - 增加、修改、询问案件期限时",
  "license": "CC BY-NC-ND 4.0 (repo-level)",
  "skill_md_url": "https://raw.githubusercontent.com/THUYRan/Legal-Skills-Chinese/main/skills/trial-scheduling-and-deadline-monitoring/SKILL.md",
  "repository_url": "https://github.com/THUYRan/Legal-Skills-Chinese",
  "version": None,
  "visibility": "group",
  "allowed_groups": [
   "registry-admins"
  ],
  "tags": [
   "legal",
   "chinese-law",
   "thuyran"
  ],
  "metadata": {
   "author": "Legal-Skills-Chinese 项目团队（执业法律专业人员手写验证）",
   "source_repo": "THUYRan/Legal-Skills-Chinese",
   "skill_dir": "trial-scheduling-and-deadline-monitoring",
   "fm_name": "trial-scheduling-and-deadline-monitoring",
   "license_note": "repo README declares CC BY-NC-ND 4.0; some skill files mention MIT - treat all as NC-ND until the author grants per-file clarification"
  }
 },
]

def _load_creds():
    client_id = os.environ.get("LOGTO_M2M_APP_ID")
    client_secret = os.environ.get("LOGTO_M2M_CLIENT_SECRET")
    if client_id and client_secret:
        return client_id, client_secret
    if os.path.exists(CREDS_FILE):
        env = {}
        with open(CREDS_FILE, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    key, _, value = line.partition("=")
                    env[key.strip()] = value.strip()
        return env.get("LOGTO_M2M_APP_ID"), env.get("LOGTO_M2M_CLIENT_SECRET")
    return None, None


def _mint_token():
    client_id, client_secret = _load_creds()
    if not client_id or not client_secret:
        sys.exit("error: LOGTO_M2M_APP_ID / LOGTO_M2M_CLIENT_SECRET not set "
                 f"(env or {CREDS_FILE})")
    basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    body = urllib.parse.urlencode(
        {"grant_type": "client_credentials", "resource": RESOURCE}).encode()
    req = urllib.request.Request(
        TOKEN_URL, data=body, method="POST",
        headers={"Authorization": f"Basic {basic}",
                 "Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.load(resp)
    token = payload.get("access_token")
    if not token:
        sys.exit(f"error: token endpoint returned no access_token: {payload}")
    return token


def _api(method, path, token, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        GATEWAY + path, data=data, method=method,
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw = resp.read().decode()
            return resp.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode(errors="replace")
        try:
            return exc.code, json.loads(raw)
        except ValueError:
            return exc.code, raw


def _list_skills(token):
    items, offset, page = [], 0, 100
    while True:
        status, payload = _api(
            method="GET",
            path=f"/api/skills?limit={page}&offset={offset}",
            token=token)
        if status != 200:
            sys.exit(f"error: GET /api/skills -> {status}: {payload}")
        items.extend(payload.get("skills", []))
        if not payload.get("has_next"):
            return items
        offset += page


def _skill_path(item):
    # list items carry "path" like "/skills/<slug>"; the API's {skill_path}
    # segment expects the bare slug (it re-prefixes /skills/ itself)
    path = item.get("path") or item.get("skill_path") or item.get("name")
    if path:
        for prefix in ("/skills/", "skills/", "/"):
            if path.startswith(prefix):
                path = path[len(prefix):]
                break
    return path


def _entry_payload(entry):
    return {k: entry[k] for k in (
        "name", "description", "skill_md_url", "repository_url", "version",
        "license", "tags", "visibility", "allowed_groups", "metadata")}


def _select(args):
    selected = CATALOG
    if args.repo:
        selected = [e for e in selected if e["metadata"]["source_repo"] == args.repo]
    if args.visibility:
        selected = [e for e in selected if e["visibility"] == args.visibility]
    if args.name:
        selected = [e for e in selected if e["name"] == args.name]
    return selected


def _check_catalog_duplicates():
    by_name = {}
    for entry in CATALOG:
        by_name.setdefault(entry["name"], []).append(entry["skill_md_url"])
    dupes = {n: urls for n, urls in by_name.items() if len(urls) > 1}
    if dupes:
        detail = "; ".join(f"{n} <- {' | '.join(urls)}" for n, urls in sorted(dupes.items()))
        sys.exit(f"error: duplicate CATALOG names (fix before registering): {detail}")


def _toggle_skill(token, path, enabled):
    return _api("POST", f"/api/skills/{path}/toggle", token, {"enabled": enabled})


def _ensure_enabled(token, path, item):
    """Re-enable a skill the gateway has auto-disabled (fail-safe drift disable).

    `item` is the listing entry when available; None forces a detail GET (needed
    for disabled entries, which the listing hides). Returns True when a toggle
    to enabled was issued and succeeded, None when no toggle was needed.
    """
    if item is None:
        st, det = _api("GET", f"/api/skills/{path}", token)
        if not (st == 200 and isinstance(det, dict)):
            return None
        item = det
    if item.get("is_enabled", item.get("enabled")) is False:
        st, _resp = _toggle_skill(token, path, True)
        return st in (200, 201)
    return None


def cmd_register(args):
    targets = _select(args)
    if not targets:
        sys.exit("error: no catalog entries match the given filters")
    existing_items = {}
    if not args.dry_run:
        token = _mint_token()
        for item in _list_skills(token):
            existing_items.setdefault(item.get("name"), item)
    failures = 0
    for entry in targets:
        payload = _entry_payload(entry)
        if args.dry_run:
            print(f"DRY {entry['visibility']:6} {entry['name']}  <- {entry['skill_md_url']}")
            continue
        item = existing_items.get(entry["name"])
        if item:
            upstream = _existing_source_url(token, item)
            if upstream and upstream != entry["skill_md_url"]:
                # fail closed: the name belongs to a different upstream skill
                print(f"COLLISION       {entry['name']}: name held by "
                      f"{upstream}; skipped, existing entry untouched")
                failures += 1
                continue
            path = _skill_path(item)
            status, resp = _api("PUT", f"/api/skills/{path}", token, payload)
            action = "updated"
            if status in (200, 201) and _ensure_enabled(token, path, item):
                action += "+enabled"
        else:
            status, resp = _api("POST", "/api/skills", token, payload)
            action = "created"
            if status in (409, 400):
                # race / stale list / DISABLED entry (auto-disabled skills are hidden
                # from the listing): fall back to an in-place update by name, which
                # re-baselines content and re-enables
                status, resp = _api("PUT", f"/api/skills/{entry['name']}", token, payload)
                action = "updated"
                if status in (200, 201) and _ensure_enabled(token, entry["name"], None):
                    action += "+enabled"
        ok = status in (200, 201)
        failures += 0 if ok else 1
        marker = "OK  " if ok else "FAIL"
        print(f"{marker} {action:8} [{status}] {entry['name']}"
              + ("" if ok else f": {str(resp)[:300]}"))
    print(f"done: {len(targets)} processed, {failures} failed")
    return 1 if failures else 0


def _existing_source_url(token, item):
    """Best-effort upstream URL of an already-registered skill.

    Returns None when the API exposes no source URL — the caller then proceeds
    (idempotent re-registration must keep working); only a *known different*
    upstream counts as a collision.
    """
    url = item.get("skill_md_url") or item.get("source_url") or item.get("url")
    if url:
        return url
    path = _skill_path(item)
    status, detail = _api("GET", f"/api/skills/{path}", token)
    if status == 200 and isinstance(detail, dict):
        detail = detail.get("skill") if isinstance(detail.get("skill"), dict) else detail
        return detail.get("skill_md_url") or detail.get("source_url") or detail.get("url")
    return None


def cmd_show(args):
    token = _mint_token()
    if args.name:
        status, resp = _api("GET", f"/api/skills/{args.name}", token)
        print(json.dumps(resp, ensure_ascii=False, indent=1)[:4000])
        return 0 if status == 200 else 1
    items = _list_skills(token)
    print(f"{'name':<44} {'vis':<7} {'license':<22} status")
    for item in items:
        lic = item.get("license") or "-"
        state = "disabled" if item.get("enabled") is False else str(
            item.get("status") or item.get("health_status") or "-")
        print(f"{str(item.get('name'))[:43]:<44} "
              f"{str(item.get('visibility') or '-'):<7} {lic[:21]:<22} {state}")
    print(f"total: {len(items)}")
    return 0


def cmd_remove(args):
    token = _mint_token()
    if not args.name and not args.repo and not args.visibility:
        sys.exit("error: remove needs a skill name or a --repo/--visibility filter")
    if args.name:
        items = _list_skills(token)
        match = next((it for it in items if it.get("name") == args.name), None)
        if not match:
            sys.exit(f"error: skill {args.name!r} not in catalog (nothing to remove)")
        targets = [match]
    else:
        selected = _select(args)
        if not selected:
            sys.exit("error: no catalog entries match the given filters")
        on_gateway = {it.get("name"): it for it in _list_skills(token)}
        targets, absent = [], []
        for entry in selected:
            item = on_gateway.get(entry["name"])
            targets.append(item) if item else absent.append(entry["name"])
        if absent:
            preview = ", ".join(absent[:10]) + ("…" if len(absent) > 10 else "")
            print(f"note: {len(absent)} catalog entries not on the gateway (skipped): {preview}")
    print(f"removing {len(targets)} skill(s)")
    failed = 0
    for item in targets:
        name = item.get("name")
        status, resp = _api("DELETE", f"/api/skills/{_skill_path(item)}", token)
        ok = status in (200, 204)
        failed += 0 if ok else 1
        print(f"{'OK  ' if ok else 'FAIL'} removed [{status}] {name}"
              + ("" if ok else f": {str(resp)[:300]}"))
    return 1 if failed else 0


def main():
    _check_catalog_duplicates()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="action", required=True)

    reg = sub.add_parser("register", help="register/update curated skills")
    reg.add_argument("--repo", help="only entries from this source repo (owner/name)")
    reg.add_argument("--visibility", choices=("public", "group"),
                     help="only entries with this visibility")
    reg.add_argument("--name", help="only this one skill")
    reg.add_argument("--dry-run", action="store_true", help="list actions, call nothing")
    reg.set_defaults(func=cmd_register)

    show = sub.add_parser("show", help="list catalog skills (or one detail)")
    show.add_argument("--name", help="show full detail for one skill")
    show.set_defaults(func=cmd_show)

    rem = sub.add_parser("remove", help="remove one skill by name, or a repo/visibility subset")
    rem.add_argument("name", nargs="?", help="exact skill name to delete")
    rem.add_argument("--repo", help="remove every catalog entry from this source repo")
    rem.add_argument("--visibility", choices=("public", "group"),
                     help="remove every catalog entry with this visibility")
    rem.set_defaults(func=cmd_remove)

    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
