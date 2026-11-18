// 软件服务与定制开发合同 —— docx 生成脚本
// 规范:documents:docx skill / scenes/contract.md(Profile A,1.5 倍行距,纯黑,无封面无目录)
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  Footer, PageNumber, AlignmentType, HeadingLevel, WidthType,
  BorderStyle, ShadingType,
} = require("docx");
const fs = require("fs");

const F_BODY = { ascii: "Times New Roman", eastAsia: "SimSun" };
const F_HEAD = { ascii: "Times New Roman", eastAsia: "SimHei" };
const BLACK = "000000";

const NB = { style: BorderStyle.NONE, size: 0, color: "FFFFFF" };
const cellNoBorders = { top: NB, bottom: NB, left: NB, right: NB };
const tblNoBorders = { top: NB, bottom: NB, left: NB, right: NB, insideHorizontal: NB, insideVertical: NB };
const GRID = { style: BorderStyle.SINGLE, size: 4, color: "808080" };
const tblGridBorders = { top: GRID, bottom: GRID, left: GRID, right: GRID, insideHorizontal: GRID, insideVertical: GRID };

function safeText(v, ph) {
  if (v === undefined || v === null || v === "" || String(v) === "NaN" || String(v) === "undefined") {
    return ph || "【待填写】";
  }
  return String(v);
}

// 条标题(第X条 / 附件X)
function art(title, opts = {}) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_1,
    pageBreakBefore: !!opts.newPage,
    spacing: { before: 300, after: 140, line: 360 },
    children: [new TextRun({ text: title, bold: true, color: BLACK, font: F_HEAD, size: 24 })],
  });
}

// 正文条款段
function c(text, opts) {
  opts = opts || {};
  return new Paragraph({
    alignment: AlignmentType.JUSTIFIED,
    indent: { firstLine: 480 },
    spacing: { line: 360, after: 40 },
    keepNext: !!opts.keepNext,
    children: [new TextRun({ text, size: 24, color: BLACK, font: F_BODY })],
  });
}

// 多 run 条款段(用于金额加粗)
function cRuns(runs) {
  return new Paragraph({
    alignment: AlignmentType.JUSTIFIED,
    indent: { firstLine: 480 },
    spacing: { line: 360, after: 40 },
    children: runs,
  });
}
function tr(text, bold) {
  return new TextRun({ text, size: 24, bold: !!bold, color: BLACK, font: F_BODY });
}

// 审核提示
function note(text) {
  return new Paragraph({
    alignment: AlignmentType.JUSTIFIED,
    indent: { firstLine: 420 },
    spacing: { line: 360, before: 40, after: 80 },
    children: [new TextRun({ text, size: 21, color: BLACK, font: F_BODY })],
  });
}

// 双方信息块(无边框表格对齐,规范要求)
function partyInfoBlock(partyLabel, partyName, fields) {
  const headerPara = new Paragraph({
    spacing: { before: 200, after: 60, line: 360 },
    children: [new TextRun({ text: partyLabel + ": " + safeText(partyName, "【请填写公司营业执照登记全称】"), size: 24, bold: true, color: BLACK, font: F_BODY })],
  });
  const infoTable = new Table({
    width: { size: 92, type: WidthType.PERCENTAGE },
    borders: tblNoBorders,
    rows: fields.map(function (f) {
      return new TableRow({
        cantSplit: true,
        children: [
          new TableCell({
            width: { size: 34, type: WidthType.PERCENTAGE },
            borders: cellNoBorders,
            margins: { top: 20, bottom: 20, left: 420, right: 60 },
            children: [new Paragraph({
              spacing: { line: 360 },
              children: [new TextRun({ text: f[0] + ":", size: 24, color: BLACK, font: F_BODY })],
            })],
          }),
          new TableCell({
            width: { size: 66, type: WidthType.PERCENTAGE },
            borders: cellNoBorders,
            margins: { top: 20, bottom: 20, left: 60, right: 120 },
            children: [new Paragraph({
              spacing: { line: 360 },
              children: [new TextRun({ text: safeText(f[1], "【请填写:" + f[0] + "】"), size: 24, color: BLACK, font: F_BODY })],
            })],
          }),
        ],
      });
    }),
  });
  return [headerPara, infoTable];
}

// 签署页表格
function buildSignatureBlock() {
  const fields = [
    ["甲方(盖章):", "乙方(盖章):"],
    ["法定代表人或授权代表(签字):", "法定代表人或授权代表(签字):"],
    ["联系人:", "联系人:"],
    ["联系方式:", "联系方式:"],
    ["电子邮箱:", "电子邮箱:"],
    ["签订地点:", "签订地点:"],
    ["日期: 【____年____月____日】", "日期: 【____年____月____日】"],
  ];
  return new Table({
    width: { size: 100, type: WidthType.PERCENTAGE },
    borders: tblNoBorders,
    rows: fields.map(function (pair) {
      return new TableRow({
        cantSplit: true,
        children: [
          new TableCell({
            width: { size: 50, type: WidthType.PERCENTAGE },
            borders: cellNoBorders,
            margins: { top: 100, bottom: 100, left: 120, right: 60 },
            children: [new Paragraph({
              spacing: { line: 360 },
              children: [new TextRun({ text: pair[0], size: 24, color: BLACK, font: F_BODY })],
            })],
          }),
          new TableCell({
            width: { size: 50, type: WidthType.PERCENTAGE },
            borders: cellNoBorders,
            margins: { top: 100, bottom: 100, left: 60, right: 120 },
            children: [new Paragraph({
              spacing: { line: 360 },
              children: [new TextRun({ text: pair[1], size: 24, color: BLACK, font: F_BODY })],
            })],
          }),
        ],
      });
    }),
  });
}

// 附件表格单元格
function gcell(text, opts) {
  opts = opts || {};
  return new TableCell({
    width: { size: opts.w || 20, type: WidthType.PERCENTAGE },
    margins: { top: 60, bottom: 60, left: 100, right: 100 },
    shading: opts.header ? { type: ShadingType.CLEAR, fill: "F2F2F2" } : undefined,
    children: [new Paragraph({
      alignment: opts.center ? AlignmentType.CENTER : AlignmentType.LEFT,
      spacing: { line: 360 },
      children: [new TextRun({ text: safeText(text, "【待填写】"), size: 21, bold: !!opts.header, color: BLACK, font: F_BODY })],
    })],
  });
}

// ============ 文档内容 ============
const children = [];

// 标题 + 合同编号
children.push(new Paragraph({
  alignment: AlignmentType.CENTER,
  spacing: { line: 506, lineRule: "atLeast", before: 120, after: 160 },
  children: [new TextRun({ text: "软件服务与定制开发合同", size: 44, bold: true, color: BLACK, font: F_HEAD })],
}));
children.push(new Paragraph({
  alignment: AlignmentType.RIGHT,
  spacing: { line: 360, after: 200 },
  children: [new TextRun({ text: "合同编号:【____】", size: 21, color: BLACK, font: F_BODY })],
}));

// 甲乙双方信息
children.push.apply(children, partyInfoBlock("甲方(服务接受方)", null, [
  ["统一社会信用代码", null],
  ["住所", null],
  ["法定代表人", null],
  ["联系人", null],
  ["联系电话", null],
  ["电子邮箱", null],
]));
children.push.apply(children, partyInfoBlock("乙方(服务提供方,寻数科技)", null, [
  ["统一社会信用代码", null],
  ["住所", null],
  ["法定代表人", null],
  ["联系人", null],
  ["联系电话", null],
  ["电子邮箱", null],
]));

children.push(c("签订地点:【____】"));
children.push(c("签订日期:【____年____月____日】"));

// 鉴于
children.push(art("鉴于"));
children.push(c("1. 乙方是一家从事数据服务、人工智能应用与软件技术研发的企业,拥有面向数据与人工智能场景的软件产品、基于 MCP(Model Context Protocol,模型上下文协议)的智能体服务、领域模型及相关技术能力,并以寻数科技(FindData)品牌对外提供服务。"));
children.push(c("2. 甲方希望获得乙方提供的标准软件服务、定制开发服务及私有化部署服务;对于甲方委托定制的 MCP 技能(Skills)、数据源接入程序及其他定制开发成果,双方约定其知识产权归甲方所有,甲方可基于该等成果开展经营并获取收益。"));
children.push(c("3. 双方本着平等自愿、诚实信用的原则,根据《中华人民共和国民法典》及有关法律法规的规定,经协商一致,订立本合同,共同遵守。"));

// 第一条 定义与解释
children.push(art("第一条 定义与解释"));
children.push(c("1.1 标准软件服务:指乙方以云端订阅方式向甲方提供的现有软件产品与数据服务,包括附件一所列的数据服务、MCP 网关智能体服务、LawBench 合同智能平台、Platform AI 助手平台、开放数据平台(DAAS)及数据中心在线浏览服务等,具体内容以附件一为准。"));
children.push(c("1.2 定制开发服务:指乙方根据甲方提出的需求,为甲方专门开发 MCP 技能(Skills)、数据源接入程序、定制模型微调适配器及其他软件的定制开发服务,具体范围以双方确认的《定制开发需求说明书》(附件二)为准。"));
children.push(c("1.3 私有化部署:指将乙方软件产品及(或)定制开发成果部署于甲方指定的基础设施(包括甲方自有机房、甲方租用的服务器或甲方指定的第三方云环境)内安装运行的交付方式。"));
children.push(c("1.4 定制开发成果:指乙方在履行定制开发服务过程中形成的、以相应《定制开发需求说明书》约定范围为准的开发成果,包括源代码、目标代码、部署包、配置文件、模型适配器、技术文档及其他交付物。"));
children.push(c("1.5 乙方既有软件:指甲方订购本合同项下服务之前,乙方已开发完成并拥有的软件产品、平台、组件、工具、数据产品及其文档,包括构成其底层能力的数据网关、指标体系、模型底座、训练与部署框架等。"));
children.push(c("1.6 乙方通用组件:指定制开发成果中不可避免地引用、链接、依赖或调用的乙方既有软件中的通用模块、接口、SDK、底层库及模型底座等组成部分。"));
children.push(c("1.7 保密信息:指一方(披露方)向另一方(接收方)披露的、标注保密或者按其性质应当视为保密的技术、商业、财务、数据等信息,包括但不限于源代码、算法、数据、客户名单、商业条款等。"));
children.push(c("1.8 本合同所称日,除特别注明外均指自然日;所称工作日指中华人民共和国法定工作日。"));

// 第二条 服务内容
children.push(art("第二条 服务内容"));
children.push(c("2.1 标准软件服务。", { keepNext: true }));
children.push(c("2.1.1 乙方向甲方提供附件一所列的标准软件服务,服务期限、账号(或实例、席位)数量、调用额度等以附件一为准。"));
children.push(c("2.1.2 标准软件服务的功能范围以乙方官方服务目录及附件一载明的内容为准。乙方对服务进行不影响甲方正常使用的优化、升级的,升级后的版本自动适用;涉及重大功能变更的,乙方应提前【7】日通知甲方。"));
children.push(c("2.1.3 乙方仅就附件一载明的服务内容承担交付义务;附件一未列明的能力、数据主题或指标,不构成本合同项下的交付义务。"));
children.push(c("2.2 定制开发服务。", { keepNext: true }));
children.push(c("2.2.1 甲方委托乙方进行的每一项定制开发,均应通过双方书面(含电子邮件)确认的《定制开发需求说明书》(附件二格式)约定需求范围、技术方案、交付物清单、开发周期、验收标准及费用。经确认的《定制开发需求说明书》为本合同附件,与本合同具有同等法律效力。"));
children.push(c("2.2.2 定制开发范围可以包括:(1)为甲方业务场景定制的 MCP 技能(Skills);(2)为接入甲方指定数据源而开发的数据接入、清洗与适配程序;(3)基于甲方数据的定制模型微调及其适配器;(4)双方约定的其他软件定制开发事项。"));
children.push(c("2.2.3 《定制开发需求说明书》一经确认,未经双方书面同意不得变更;甲方中途变更需求的,开发周期与费用相应调整,由双方另行书面确认。"));
children.push(c("2.3 私有化部署服务。", { keepNext: true }));
children.push(c("2.3.1 甲方选择私有化部署的,部署的产品与版本、部署环境、许可数量(实例数、节点数、用户数)、实施内容、费用及维保安排以附件一及双方另行签署的部署确认单为准。"));
children.push(c("2.3.2 私有化部署不改变乙方既有软件的知识产权归属;甲方获得的是附件一约定范围内的使用许可,而非软件所有权的转移。定制开发成果按第七条归属甲方。"));

// 第三条 合同期限与服务开通
children.push(art("第三条 合同期限与服务开通"));
children.push(c("3.1 本合同有效期自【____年____月____日】起至【____年____月____日】止。"));
children.push(c("3.2 标准软件服务自乙方收到甲方首期费用且甲方完成注册或配置之日起【5】个工作日内开通;私有化部署与定制开发的启动时间以相应附件约定为准。"));
children.push(c("3.3 合同期满前【30】日,双方可协商续费续期;未续期的,本合同于期满时终止,后续事宜按第十六条处理。"));

// 第四条 定制开发的需求、交付与验收
children.push(art("第四条 定制开发的需求、交付与验收"));
children.push(c("4.1 需求确认。甲方以书面形式提出需求,双方确认《定制开发需求说明书》后启动开发。需求说明书应明确交付物清单(含是否交付源代码)、验收标准与里程碑。"));
children.push(c("4.2 开发与交付。乙方应按需求说明书约定的时间与内容交付,交付物包括约定的源代码、部署包、部署说明、接口文档及用户文档。需要交付源代码而未在需求说明书中明确的,视为不交付源代码,但不影响知识产权按第七条归属甲方。"));
children.push(c("4.3 验收。甲方应在收到交付物后【10】个工作日内,按需求说明书约定的验收标准完成验收并签署《验收确认单》(附件三格式);甲方在上述期限内未提出书面异议,且已将交付物投入实际使用的,视为验收通过。"));
children.push(c("4.4 修改与缺陷修复。验收中发现不符合项的,甲方应一次性书面列明,乙方应在【15】个工作日或双方另行商定的期限内修复;修复后重新按第4.3款验收。"));
children.push(c("4.5 质保。定制开发成果自验收通过之日起质保期【12】个月,质保期内乙方对缺陷免费修复。因甲方部署环境变更、甲方人员修改代码或需求说明书范围以外的事项引起的问题,不属于免费修复范围。"));

// 第五条 私有化部署专项约定
children.push(art("第五条 私有化部署专项约定"));
children.push(c("5.1 许可授予。乙方授予甲方一项非独占、不可转让、不可转授权的使用许可,许可甲方在本合同有效期内、按附件一约定的范围与数量,在其部署环境内安装、运行和使用乙方软件(含定制开发成果及为运行所必需的乙方通用组件)。许可期限以附件一约定为准。"));
children.push(c("5.2 部署环境。甲方负责提供满足部署要求的硬件、网络、操作系统与安全环境,并确保该环境的合法性;部署环境的技术要求由乙方在实施前书面提供。"));
children.push(c("5.3 实施配合。双方各自指定项目负责人与技术人员;甲方应在乙方合理要求的范围内提供环境访问权限、账号与必要配合。"));
children.push(c("5.4 上线验收。私有化部署完成并经甲方按部署确认单验收通过后,进入维保期。"));
children.push(c("5.5 升级与维保。乙方按附件一约定提供版本升级与技术支持;首年维保费已包含在部署费用中(附件一另有约定的除外),自第二年起按附件一约定收取。"));

// 第六条 费用与支付
children.push(art("第六条 费用与支付"));
children.push(cRuns([tr("6.1 本合同费用(含税)总计:"), tr("【大写:____元整(小写:¥____)】", true), tr(",由以下部分构成,明细见附件一:")]));
children.push(c("(1)标准软件服务订阅费:" + "【大写:____元整(小写:¥____)】" + ",按年(或按附件一约定的周期)支付;"));
children.push(c("(2)定制开发费:按《定制开发需求说明书》逐项约定;每项原则上按预付款【30】%、交付款【40】%、验收款【30】%分期支付,具体以需求说明书为准;"));
children.push(c("(3)私有化部署费用:包括软件许可费、实施服务费及年度维保费;"));
children.push(c("(4)双方约定的其他费用(如专项培训、现场实施的差旅费据实报销等)。"));
children.push(c("6.2 甲方应在收到乙方发票后【30】日内,将款项支付至乙方指定银行账户。乙方应向甲方开具合法有效的增值税【专用/普通】发票,发票类目与所购服务一致。"));
children.push(c("6.3 逾期付款。甲方逾期付款的,每逾期一日按逾期金额的万分之五向乙方支付违约金;逾期超过【30】日的,乙方有权暂停相应服务且不视为乙方违约,甲方付清欠款及违约金后,乙方应在【2】个工作日内恢复服务。"));
children.push(c("6.4 本合同价款均为含税价;因国家税率调整引起价税分离的,不含税价格不变,税款按新税率计算。"));

// 第七条 知识产权
children.push(art("第七条 知识产权"));
children.push(c("7.1 乙方既有软件的知识产权(包括著作权、商标权、专利权、商业秘密等)归乙方所有。甲方在本合同项下获得的是使用许可,乙方既有软件的知识产权不因本合同的履行而发生任何转移。"));
children.push(c("7.2 定制开发成果的知识产权归甲方所有,包括著作财产权以及以甲方名义申请软件著作权登记、专利等知识产权保护的权利;乙方应为甲方办理前述登记或申请提供必要的协助文件。"));
children.push(c("7.3 甲方对定制开发成果享有完整的占有、使用、收益和处分的权利,可以自行使用、复制、修改、分发,也可以许可第三方使用、转让或开展商业化经营并获取收益,无需就此另行向乙方支付费用;但定制开发成果的运行如依赖乙方云端服务的(例如调用乙方的数据网关或模型服务),其运行以甲方保持相应服务的有效订阅或有效许可为前提。"));
children.push(c("7.4 乙方通用组件。定制开发成果中引用、链接、依赖或调用的乙方通用组件,其知识产权仍归乙方所有;乙方在此授予甲方及甲方的下游被许可人一项永久的、免费的、非独占的、为使定制开发成果得以安装、运行和分发所必需的使用许可。甲方不得对乙方通用组件进行反向工程、反编译或试图将其从定制开发成果中剥离后单独使用或提供给第三方。定制模型适配器所依赖的模型底座属于乙方通用组件,但其许可期限、许可范围与费用以附件一约定为准。"));
children.push(c("7.5 开源组件。交付物中包含的开源软件,按其适用的开源许可证执行;乙方承诺其使用方式不与相应许可证冲突,并在交付文档中列明开源组件清单及许可证类型。开源组件的权利归属与使用限制以其自身许可证为准。"));
children.push(c("7.6 通用经验。乙方保留在不复制甲方保密信息、不使用定制开发成果本身的前提下,将履行本合同过程中获得的一般性技术经验、方法论以及非专有的技术改进,用于乙方自身产品与服务的权利。"));
children.push(c("7.7 数据的权益不因本条转移。乙方数据产品(含数据集、指标体系、数据接口)的权利与授权按第八条执行;定制开发成果中沉淀的甲方业务数据与甲方业务逻辑归甲方所有。"));
children.push(c("7.8 权利担保。双方各自确保其交付物不侵犯第三方知识产权;因一方交付物侵犯第三方权利引起的索赔,由交付方负责处理并承担相应责任。"));
children.push(note("【审核提示】第7.3、7.4款是本合同知识产权安排的核心:定制成果归甲方并可商业化,但运行依赖乙方云端服务的部分需保持订阅。请双方在签署前确认该边界符合商业预期。"));

// 第八条 数据权益与合规
children.push(art("第八条 数据权益与数据合规"));
children.push(c("8.1 数据授权。乙方通过数据服务向甲方提供的数据,甲方仅限在本合同及附件一约定的范围和用途内使用;未经乙方书面同意,甲方不得对数据进行镜像导出、转售,亦不得以批量数据服务的形式向第三方提供。"));
children.push(c("8.2 数据来源。乙方声明其数据产品来源于公开渠道或经合法授权的渠道,并已尽合理注意义务。因上游数据源的内容错误、迟延或中断引起的问题,乙方按第十条约定的方式处理,但乙方对数据准确性、完整性的担保以官方来源的对外口径为限。"));
children.push(c("8.3 合法使用。甲方承诺不将本合同项下服务用于违反法律法规的用途,不利用乙方服务从事危害国家安全、扰乱市场秩序或侵犯他人合法权益的活动。"));
children.push(c("8.4 个人信息与数据安全。服务涉及个人信息的,双方应遵守《中华人民共和国个人信息保护法》《中华人民共和国数据安全法》《中华人民共和国网络安全法》等法律法规的规定;甲方作为个人信息处理者的义务由甲方自行承担;乙方作为受托处理者处理个人信息的,双方可另行签署数据处理协议。"));
children.push(c("8.5 各自数据。甲方的业务数据归甲方所有;甲方存储于乙方云端服务中的数据,乙方仅可为履行本合同之目的进行处理,不得用于为甲方以外目的服务;本合同终止后数据的处理按第16.4款执行。"));
children.push(c("8.6 定制数据源。甲方指定接入的第三方数据源,其数据合法性、取得授权的完备性由甲方负责并自行承担相应责任;经乙方数据服务获取的数据,按第8.1款执行。"));

// 第九条 双方权利义务
children.push(art("第九条 双方权利义务"));
children.push(c("9.1 甲方权利义务:", { keepNext: true }));
children.push(c("(1)按本合同约定支付费用;"));
children.push(c("(2)提供开展服务所必需的需求说明、数据、部署环境与合理配合;"));
children.push(c("(3)妥善保管账号与密钥,因甲方保管不善造成的损失由甲方自行承担;"));
children.push(c("(4)不将标准软件服务的账号、密钥转借或共享给附件一约定范围以外的主体使用;"));
children.push(c("(5)对乙方现场实施人员遵守甲方合理的安全管理规定提供必要条件。"));
children.push(c("9.2 乙方权利义务:", { keepNext: true }));
children.push(c("(1)按约定的范围、标准与时间提供服务与交付物;"));
children.push(c("(2)对甲方提出的服务请求按第十条约定的方式与时限响应;"));
children.push(c("(3)配备具有相应能力的实施与支持人员,关键岗位人员变动应提前通知甲方;"));
children.push(c("(4)遵守甲方关于现场实施与环境访问的合理安全管理规定。"));

// 第十条 服务支持与维护
children.push(art("第十条 服务支持与维护"));
children.push(c("10.1 支持渠道与时间。乙方通过【电子邮件/在线工单/企业微信】渠道提供服务支持,工作日 9:00 至 18:00 响应;7×24 高级支持以附件一约定为准。"));
children.push(c("10.2 故障分级与响应时限。故障分为三级:致命(服务整体不可用)、严重(核心功能受损)、一般(不影响核心功能使用)。致命故障【2】小时内响应、【1】个工作日内解决或提供可行的规避方案;严重故障【4】小时内响应、【3】个工作日内解决;一般故障【1】个工作日内响应,在双方商定的期限或下一版本中解决。"));
children.push(c("10.3 计划内维护。乙方应提前【48】小时通知甲方;维护原则上安排在业务低峰时段,单次不超过【4】小时。"));
children.push(c("10.4 服务可用性。标准软件服务的月度可用性目标为【99.5】%,统计口径与未达标的服务补偿方式以附件一约定为准。"));
children.push(note("【审核提示】第10.2、10.4款中的响应时限与可用性指标为建议值,签署前请按实际运营能力确认,避免作出超出可交付水平的承诺。"));

// 第十一条 保密
children.push(art("第十一条 保密"));
children.push(c("11.1 接收方应对披露方的保密信息予以保密,未经披露方书面同意不得向第三方披露,亦不得用于本合同目的之外的用途,并采取不低于保护自身同类保密信息的措施。"));
children.push(c("11.2 保密义务的例外:(1)非因接收方过错已进入公有领域的信息;(2)接收方在披露前已合法持有的信息;(3)接收方从有权披露的第三方合法获得的信息;(4)依法律法规或有权机关要求披露的信息,但接收方应在法律允许的范围内事先通知披露方。"));
children.push(c("11.3 保密期限。本合同有效期内及终止后【5】年;源代码、数据集及商业秘密类信息不受该期限限制,直至其合法公开。"));
children.push(c("11.4 接收方应确保其员工以及经其聘用的分包方、顾问遵守同等的保密义务,该等人员违反保密义务视为接收方违反。"));

// 第十二条 陈述与保证
children.push(art("第十二条 陈述与保证"));
children.push(c("12.1 双方各自声明并保证:其为依法存续并有效存续的主体,签署与履行本合同已获得必要的内部授权,且不违反其对任何第三方的义务。"));
children.push(c("12.2 乙方保证:其提供的服务及交付物为乙方原创开发或已取得合法授权,不侵犯第三方知识产权;服务符合附件一载明的功能描述。"));
children.push(c("12.3 甲方保证:其向乙方提供的数据、素材及文档不侵犯第三方权利,且已取得为履行本合同所必需的授权与合法基础。"));
children.push(c("12.4 除本合同明确约定的保证外,任何一方未作其他明示或默示的保证。"));

// 第十三条 违约责任
children.push(art("第十三条 违约责任"));
children.push(c("13.1 甲方违约。甲方违反付款义务的,按第6.3款执行;甲方将账号超出约定范围使用,或以违反第7.4、8.1款的方式使用服务的,乙方有权限期要求纠正;甲方逾期【15】日未纠正的,乙方有权中止相应服务,并要求甲方赔偿由此造成的实际损失。"));
children.push(c("13.2 乙方违约。乙方未按《定制开发需求说明书》约定期限交付定制开发成果的,每逾期一日按该项定制开发费的万分之五向甲方支付违约金,累计以该项费用的【10】%为限;逾期超过【60】日的,甲方有权解除该项需求说明书,乙方应退还相应预付款。乙方未按附件一约定提供标准软件服务且连续【15】日未能恢复正常,致使合同目的不能实现的,甲方有权解除本合同,乙方按第14.1款承担责任。"));
children.push(c("13.3 任一方违反保密义务或知识产权约定给对方造成损失的,应赔偿守约方的实际损失。"));
children.push(c("13.4 违约金不足以弥补守约方实际损失的,违约方还应就差额部分予以赔偿。"));
children.push(note("【审核提示】违约金比例与上限为常见商业水平,请结合具体交易金额与风险偏好复核调整。"));

// 第十四条 责任限制
children.push(art("第十四条 责任限制"));
children.push(c("14.1 除因故意或重大过失造成损失、人身损害以及违反保密义务或知识产权约定的情形外,任一方在本合同项下的累计赔偿责任,以甲方在索赔事件发生前【12】个月内就相关服务实际支付的费用总额为上限。"));
children.push(c("14.2 在任何情况下,任何一方均不对间接损失、预期利润损失、商誉损失、数据丢失(可从备份恢复的除外)以及第三方的连带索赔承担责任。"));
children.push(note("【审核提示】本条为责任限制条款,属于对赔偿风险的重大安排,签署前请双方特别确认。"));

// 第十五条 不可抗力
children.push(art("第十五条 不可抗力"));
children.push(c("15.1 因不可抗力(包括但不限于自然灾害、战争、罢工、疫情管控、大规模网络攻击、基础电信故障及政府行为)致使一方不能履行本合同的,根据不可抗力的影响,部分或全部免除其责任,但法律另有规定的除外。"));
children.push(c("15.2 遭受不可抗力的一方应在【7】日内书面通知对方并提供证明,同时采取合理措施防止损失扩大;不可抗力持续超过【60】日的,任何一方有权书面通知对方终止本合同,双方按实际履行情况结算。"));

// 第十六条 合同变更、解除与终止
children.push(art("第十六条 合同变更、解除与终止"));
children.push(c("16.1 本合同的变更须经双方书面协议;《定制开发需求说明书》按其自身约定的确认机制执行。"));
children.push(c("16.2 经双方协商一致,可以解除本合同。"));
children.push(c("16.3 一方严重违约致使合同目的不能实现,或者一方进入解散、破产、清算程序且未提供令对方满意的担保的,另一方有权书面通知解除本合同。"));
children.push(c("16.4 终止或解除的后果:", { keepNext: true }));
children.push(c("(1)标准软件服务:甲方应结清欠付费用;乙方应在终止后【30】日内配合甲方导出甲方的业务数据;"));
children.push(c("(2)定制开发成果:不因本合同终止而影响甲方已取得的知识产权及乙方已授予的通用组件许可;尚未验收的部分,费用按实际进度结算,已交付部分的源代码与文档应移交甲方;"));
children.push(c("(3)私有化部署:按附件一约定的许可期限处理,许可期限届满或合同解除的,甲方应停止使用并删除乙方软件(定制开发成果除外);"));
children.push(c("(4)第7.4款、第八条、第十一条、第十四条、第十八条在合同终止后继续有效。"));

// 第十七条 通知与送达
children.push(art("第十七条 通知与送达"));
children.push(c("17.1 双方联系人及送达地址以本合同首部载明的信息为准;发生变更的,应提前【5】个工作日书面通知对方,否则按原信息送达仍视为有效送达。"));
children.push(c("17.2 通知可以专人送达、快递或电子邮件方式发出:专人送达以签收之日、快递以签收或投递记录载明之日、电子邮件以发送成功之日视为送达。"));

// 第十八条 争议解决
children.push(art("第十八条 争议解决"));
children.push(c("18.1 本合同的订立、效力、履行与解释,适用中华人民共和国法律。"));
children.push(c("18.2 因本合同引起的或与本合同有关的争议,双方应友好协商解决;协商不成的,按下列第【 】种方式解决(签署前请勾选其一):"));
children.push(c("(1)提交【____仲裁委员会】,按照申请仲裁时该会现行有效的仲裁规则进行仲裁,仲裁裁决是终局的,对双方均有约束力;"));
children.push(c("(2)向【乙方住所地/合同签订地】有管辖权的人民法院提起诉讼。"));
children.push(note("【审核提示】仲裁与诉讼只能择一约定,请签署前确认选项并删除另一项。"));

// 第十九条 其他
children.push(art("第十九条 其他"));
children.push(c("19.1 附件。本合同附件包括附件一《服务清单与费用明细》、附件二《定制开发需求说明书(模板)》、附件三《验收确认单(模板)》以及双方后续确认的各《定制开发需求说明书》。附件为本合同不可分割的组成部分,与正文具有同等法律效力;附件与正文不一致的,以【正文/相应附件的专门约定】为准(请确认后择一)。"));
children.push(c("19.2 完整协议。本合同构成双方就本合同事项的完整约定,并取代此前双方就同一事项的一切磋商与口头承诺。"));
children.push(c("19.3 可分割性。本合同任一条款被认定为无效或不可执行的,不影响其他条款的效力。"));
children.push(c("19.4 转让。未经对方书面同意,任何一方不得转让本合同项下的权利义务。"));
children.push(c("19.5 生效与份数。本合同一式【贰】份,甲乙双方各执【壹】份,自双方签字(盖章)之日起生效。"));

// ============ 签署页 ============
children.push(new Paragraph({
  pageBreakBefore: true,
  alignment: AlignmentType.CENTER,
  spacing: { before: 200, after: 200, line: 360 },
  children: [new TextRun({ text: "(以下无正文,为本合同签署页)", size: 24, color: BLACK, font: F_BODY })],
}));
children.push(buildSignatureBlock());

// ============ 附件一 ============
children.push(art("附件一 服务清单与费用明细", { newPage: true }));
children.push(new Paragraph({
  keepNext: true,
  spacing: { before: 60, after: 80, line: 360 },
  children: [new TextRun({ text: "表 1 服务清单与费用(含税)", bold: true, size: 21, color: BLACK, font: F_BODY })],
}));
children.push(new Table({
  width: { size: 100, type: WidthType.PERCENTAGE },
  borders: tblGridBorders,
  rows: [
    new TableRow({
      tableHeader: true,
      cantSplit: true,
      children: [
        gcell("类别", { header: true, w: 14, center: true }),
        gcell("服务项", { header: true, w: 30 }),
        gcell("规格与数量", { header: true, w: 26 }),
        gcell("期限", { header: true, w: 14 }),
        gcell("费用(元)", { header: true, w: 16 }),
      ],
    }),
    new TableRow({ cantSplit: true, children: [gcell("标准软件服务", { w: 14 }), gcell("数据服务(数据中心在线浏览)", { w: 30 }), gcell("【账号数/查询额度】", { w: 26 }), gcell("【订阅期限】", { w: 14 }), gcell("【____】", { w: 16 })] }),
    new TableRow({ cantSplit: true, children: [gcell("标准软件服务", { w: 14 }), gcell("MCP 网关智能体服务(开放数据/数据平台/商业数据联邦/财报抽取/合同智能,按需勾选)", { w: 30 }), gcell("【服务项与调用额度】", { w: 26 }), gcell("【订阅期限】", { w: 14 }), gcell("【____】", { w: 16 })] }),
    new TableRow({ cantSplit: true, children: [gcell("标准软件服务", { w: 14 }), gcell("LawBench 合同智能平台", { w: 30 }), gcell("【账号数/席位】", { w: 26 }), gcell("【订阅期限】", { w: 14 }), gcell("【____】", { w: 16 })] }),
    new TableRow({ cantSplit: true, children: [gcell("标准软件服务", { w: 14 }), gcell("Platform AI 助手平台", { w: 30 }), gcell("【账号数/席位】", { w: 26 }), gcell("【订阅期限】", { w: 14 }), gcell("【____】", { w: 16 })] }),
    new TableRow({ cantSplit: true, children: [gcell("标准软件服务", { w: 14 }), gcell("开放数据平台(DAAS)", { w: 30 }), gcell("【账号数/部署规格】", { w: 26 }), gcell("【订阅期限】", { w: 14 }), gcell("【____】", { w: 16 })] }),
    new TableRow({ cantSplit: true, children: [gcell("私有化部署", { w: 14 }), gcell("软件许可(产品与版本:【____】)", { w: 30 }), gcell("【实例数/节点数/用户数】", { w: 26 }), gcell("【许可期限】", { w: 14 }), gcell("【____】", { w: 16 })] }),
    new TableRow({ cantSplit: true, children: [gcell("私有化部署", { w: 14 }), gcell("实施服务", { w: 30 }), gcell("【人天与里程碑】", { w: 26 }), gcell("【实施周期】", { w: 14 }), gcell("【____】", { w: 16 })] }),
    new TableRow({ cantSplit: true, children: [gcell("私有化部署", { w: 14 }), gcell("年度维保(含升级与技术支持)", { w: 30 }), gcell("【支持等级】", { w: 26 }), gcell("【按年】", { w: 14 }), gcell("【____/年】", { w: 16 })] }),
    new TableRow({ cantSplit: true, children: [gcell("定制开发", { w: 14 }), gcell("MCP 技能(Skills)/数据源接入/定制模型微调等", { w: 30 }), gcell("详见相应《定制开发需求说明书》", { w: 26 }), gcell("【按项目】", { w: 14 }), gcell("【按附件二】", { w: 16 })] }),
  ],
}));
children.push(c("补充约定(支持等级、月度可用性统计口径、未达标的补偿方式、付款节点等):【____】。"));

// ============ 附件二 ============
children.push(art("附件二 定制开发需求说明书(模板)", { newPage: true }));
children.push(c("每项定制开发开始前,双方按以下要素确认需求说明书,并由双方授权代表签字(或电子邮件确认)。"));
children.push(c("(1)项目名称与背景目标:项目的业务背景、要解决的问题与预期目标;"));
children.push(c("(2)需求范围:功能点清单,逐条列明必备功能、可选功能与明确排除项;"));
children.push(c("(3)交付物清单:源代码(是否交付)、部署包、接口文档、用户文档、开源组件清单等;"));
children.push(c("(4)技术方案要点:系统接口、通信协议、依赖的乙方服务与数据源、运行环境要求;"));
children.push(c("(5)甲方提供的数据与素材:数据范围、格式、交付方式及其授权状态说明;"));
children.push(c("(6)开发周期与里程碑:阶段划分、每阶段交付内容与时间;"));
children.push(c("(7)验收标准:可量化、可执行的验收指标与验收方法;"));
children.push(c("(8)费用与支付节点:总费用、分期比例与各期支付条件;"));
children.push(c("(9)变更机制:需求变更的提出、评估、工期与费用调整的确认方式;"));
children.push(c("(10)双方项目联系人及升级机制。"));

// ============ 附件三 ============
children.push(art("附件三 验收确认单(模板)", { newPage: true }));
children.push(new Paragraph({
  keepNext: true,
  spacing: { before: 60, after: 80, line: 360 },
  children: [new TextRun({ text: "表 2 验收确认单", bold: true, size: 21, color: BLACK, font: F_BODY })],
}));
children.push(new Table({
  width: { size: 100, type: WidthType.PERCENTAGE },
  borders: tblGridBorders,
  rows: [
    new TableRow({ tableHeader: true, cantSplit: true, children: [gcell("项目", { header: true, w: 24 }), gcell("内容", { header: true, w: 76 })] }),
    new TableRow({ cantSplit: true, children: [gcell("项目名称", { w: 24 }), gcell("【____】", { w: 76 })] }),
    new TableRow({ cantSplit: true, children: [gcell("对应需求说明书", { w: 24 }), gcell("【需求说明书编号/名称】", { w: 76 })] }),
    new TableRow({ cantSplit: true, children: [gcell("交付物清单", { w: 24 }), gcell("【逐项列明交付物】", { w: 76 })] }),
    new TableRow({ cantSplit: true, children: [gcell("验收标准核对结果", { w: 24 }), gcell("【逐项对照需求说明书验收标准填写结果】", { w: 76 })] }),
    new TableRow({ cantSplit: true, children: [gcell("遗留问题及处理", { w: 24 }), gcell("【如有,列明问题、责任方与解决期限】", { w: 76 })] }),
    new TableRow({ cantSplit: true, children: [gcell("验收结论", { w: 24 }), gcell("□ 通过　□ 有条件通过(条件:【____】)　□ 不通过(原因:【____】)", { w: 76 })] }),
    new TableRow({ cantSplit: true, children: [gcell("甲方代表签署", { w: 24 }), gcell("签字:____________　日期:【____年____月____日】", { w: 76 })] }),
    new TableRow({ cantSplit: true, children: [gcell("乙方代表签署", { w: 24 }), gcell("签字:____________　日期:【____年____月____日】", { w: 76 })] }),
  ],
}));

// ============ 文档组装 ============
const doc = new Document({
  creator: "寻数科技 FindData",
  title: "软件服务与定制开发合同",
  styles: {
    default: {
      document: {
        run: { font: F_BODY, size: 24, color: BLACK },
        paragraph: { spacing: { line: 360 } },
      },
      heading1: {
        run: { font: F_HEAD, size: 24, bold: true, color: BLACK },
        paragraph: { spacing: { before: 300, after: 140, line: 360 } },
      },
    },
  },
  sections: [{
    properties: {
      page: {
        size: { width: 11906, height: 16838 },
        margin: { top: 1440, bottom: 1440, left: 1701, right: 1417 },
      },
    },
    footers: {
      default: new Footer({
        children: [new Paragraph({
          alignment: AlignmentType.CENTER,
          children: [new TextRun({ children: [PageNumber.CURRENT], size: 18, color: BLACK, font: F_BODY })],
        })],
      }),
    },
    children: children,
  }],
});

Packer.toBuffer(doc).then(function (buf) {
  fs.writeFileSync("软件服务与定制开发合同.docx", buf);
  console.log("OK: 软件服务与定制开发合同.docx (" + buf.length + " bytes)");
});
