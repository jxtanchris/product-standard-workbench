# -*- coding: utf-8 -*-
"""生成《现有产品标准分析流程：还原、评估与改进建议》DOCX。"""
from docx import Document
from docx.shared import Pt, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

BODY_FONT = "宋体"
HEAD_FONT = "黑体"


def set_run_font(run, name=BODY_FONT, size=10.5, bold=False):
    run.font.name = name
    run.font.size = Pt(size)
    run.bold = bold
    rpr = run._element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.append(rfonts)
    for attr in ("w:ascii", "w:hAnsi", "w:eastAsia"):
        rfonts.set(qn(attr), name)


def style_setup(doc):
    for sname, size, bold in (("Normal", 10.5, False), ("Heading 1", 15, True), ("Heading 2", 12, True)):
        st = doc.styles[sname]
        st.font.name = HEAD_FONT if bold else BODY_FONT
        st.font.size = Pt(size)
        st.font.bold = bold
        st.font.color.rgb = RGBColor(0, 0, 0)
        rpr = st.element.get_or_add_rPr()
        rfonts = rpr.find(qn("w:rFonts"))
        if rfonts is None:
            rfonts = OxmlElement("w:rFonts")
            rpr.append(rfonts)
        for attr in ("w:ascii", "w:hAnsi", "w:eastAsia"):
            rfonts.set(qn(attr), HEAD_FONT if bold else BODY_FONT)
    pf = doc.styles["Normal"].paragraph_format
    pf.line_spacing = 1.25
    pf.space_after = Pt(4)


def para(doc, text="", size=10.5, bold=False, indent=True, space_before=0, space_after=4, color=None):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    if indent:
        p.paragraph_format.first_line_indent = Pt(size * 2)
    p.paragraph_format.space_before = Pt(space_before)
    p.paragraph_format.space_after = Pt(space_after)
    p.paragraph_format.line_spacing = 1.25
    if text:
        r = p.add_run(text)
        set_run_font(r, BODY_FONT, size, bold)
        if color:
            r.font.color.rgb = color
    return p


def bullet(doc, text, size=10.5):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    p.paragraph_format.left_indent = Pt(21)
    p.paragraph_format.first_line_indent = Pt(-10)
    p.paragraph_format.space_after = Pt(3)
    p.paragraph_format.line_spacing = 1.22
    r = p.add_run("· " + text)
    set_run_font(r, BODY_FONT, size)
    return p


def heading(doc, text, level=1):
    h = doc.add_heading(level=level)
    h.alignment = WD_ALIGN_PARAGRAPH.LEFT
    r = h.add_run(text)
    set_run_font(r, HEAD_FONT, 15 if level == 1 else 12, True)
    h.paragraph_format.space_before = Pt(14 if level == 1 else 9)
    h.paragraph_format.space_after = Pt(6)
    return h


def shade(cell, hexcolor="D9E2F3"):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hexcolor)
    tcPr.append(shd)


def cell_text(cell, text, size=9, bold=False, align="left"):
    cell.text = ""
    for i, line in enumerate(str(text).split("\n")):
        p = cell.paragraphs[0] if i == 0 else cell.add_paragraph()
        p.paragraph_format.space_before = Pt(0)
        p.paragraph_format.space_after = Pt(0)
        p.paragraph_format.line_spacing = 1.05
        p.alignment = {"left": WD_ALIGN_PARAGRAPH.LEFT, "center": WD_ALIGN_PARAGRAPH.CENTER}[align]
        r = p.add_run(line)
        set_run_font(r, BODY_FONT, size, bold)


def vcenter(cell):
    tcPr = cell._tc.get_or_add_tcPr()
    va = OxmlElement("w:vAlign")
    va.set(qn("w:val"), "center")
    tcPr.append(va)


def make_table(doc, headers, rows, widths, size=9, head_size=9, center_cols=()):
    t = doc.add_table(rows=1, cols=len(headers))
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    t.autofit = False
    tblPr = t._tbl.tblPr
    layout = OxmlElement("w:tblLayout")
    layout.set(qn("w:type"), "fixed")
    tblPr.append(layout)
    for i, w in enumerate(widths):
        t.columns[i].width = Cm(w)
    hdr = t.rows[0]
    for i, h in enumerate(headers):
        cell_text(hdr.cells[i], h, head_size, True, "center")
        shade(hdr.cells[i])
        vcenter(hdr.cells[i])
    for row in rows:
        r = t.add_row()
        cells = r.cells
        for i, v in enumerate(row):
            al = "center" if i in center_cols else "left"
            cell_text(cells[i], v, size, False, al)
            vcenter(cells[i])
    for r in t.rows:
        for i, w in enumerate(widths):
            r.cells[i].width = Cm(w)
    return t


doc = Document()
style_setup(doc)
sec = doc.sections[0]
sec.page_width, sec.page_height = Cm(21.0), Cm(29.7)
sec.left_margin = sec.right_margin = Cm(2.2)
sec.top_margin = Cm(2.2)
sec.bottom_margin = Cm(2.0)

p = doc.add_paragraph()
p.alignment = WD_ALIGN_PARAGRAPH.CENTER
r = p.add_run("现有产品标准分析流程：还原、评估与改进建议")
set_run_font(r, HEAD_FONT, 17, True)

p = doc.add_paragraph()
p.alignment = WD_ALIGN_PARAGRAPH.CENTER
p.paragraph_format.space_after = Pt(12)
r = p.add_run("—— 附 GB/T 3103.3—2000 落库演练")
set_run_font(r, BODY_FONT, 11)

para(doc, "本文依据《产品标准分析步骤》文档（5 个步骤、8 张界面截图）与上一轮 GB/T 3103.3—2000《紧固件公差 平垫圈》"
          "的人工分析结果，先还原现有流程与数据模型，再把该标准完整“落库”演练一遍，找出模型真正吃力的位置，最后给出改进建议。"
          "文中标注“（推断）”之处为依据截图界面反推，未见原始说明。", indent=True)

# ---------------- 1 ----------------
heading(doc, "1  现有流程还原")

para(doc, "文档把“标准进系统”拆成五步，前三步建结构、第四步建内容、第五步才是应用。这个顺序本身是对的：先有参数词典，"
          "限值表和检项才有落脚的坐标系。", indent=True)

rows = [
    ["① 基础资料定义", "1.1 产品类别（大／中／小三级）\n1.2 产品小类参数（参数 + 参数值）",
     "机械 → 紧固件产品 → 垫圈/螺栓/螺母……",
     "解决“同一个概念在不同标准里叫法不同”的问题，是全系统的词典"],
    ["② 产标产品参数定义", "从①的参数合集中勾选本标准的子集，并给出参数定值与默认带入",
     "GB/T 102 六角头木螺钉 选 d、L、Surface、Materials",
     "标准 × 产品小类 的“变量声明”，决定了后面限值表的维度空间"],
    ["③ 限值表分析", "3.1 定义维度数；3.2 系统按维度值展开成行，逐行录限值",
     "ASME B18.6.4 长度范围公差：2 维（端部种类 × 长度范围）",
     "把标准里的大表拆成“可查询的多维表”，是整条链路成本最高的一步"],
    ["④ 检项分析", "列出该标准可检的项目，逐项定义适用性与参数",
     "GB/T 5267.1 电镀层：电镀后螺纹尺寸检查、盐雾试验、局部/批平均镀层厚度、标记检查",
     "回答“检什么、能不能判、怎么判”"],
    ["⑤ 应用（推断）", "按产品参数取值 → 命中限值 → 与实测比对 → 出结论",
     "未见界面，但从④的数据结构可反推",
     "这一步才是客户真正感知的价值，也是目前证据最少的一步"],
]
make_table(doc, ["步骤", "文档定义", "截图中的实例", "它在系统中真正承担的作用"],
           rows, [2.9, 5.3, 4.4, 4.0], size=8.5, center_cols=(0,))

heading(doc, "1.1  从截图反推的数据模型", level=2)

para(doc, "把 8 张截图里的字段抽出来，现有模型大致是 6 个实体、4 条关键关系：", indent=True)

rows = [
    ["产品类别", "大类 / 中类 / 小类（含英文名、领域代码）", "三级分类，垫圈属“机械-紧固件产品-垫圈”"],
    ["参数（字典）", "参数代码、中文名、类型（分类／普通）、参数取值、二级参数信息", "“分类”型如 Surface 表面处理；普通型如 Thread 螺纹规格，其下再挂 公制/英制、D、P"],
    ["产标参数", "标准 → 参数子集 + 参数定值 + 默认带入", "同一标准下 d=6/8/10/12… 逐行给定值"],
    ["限值表", "限值名称、维度数、各坐标参数名、展开行、限值、单位、Min/Max/区间、是否生成实际数据、是否确认、编号", "长度范围公差,L.Max：2 维 = 端部种类 × 长度范围"],
    ["检项", "产品检项名称、属性/来源（分产品、申请检项）、匹配的方标申请检项、覆盖的具体检项、适用性（Y/N）", "“电镀后螺纹尺寸检查” ← 方标“可测量性和可装配性” 覆盖“电镀后螺纹可测量性检查”"],
    ["检项参数", "检验参数（结果类型、参数范围表达式、关联限值表 + 属性 Min/Max）、试验参数、中间参数", "WT-Rm 抗拉强度：X>=400 AND X<=1220；关联 抗拉强度Rm,Min，属性 Min"],
]
make_table(doc, ["实体", "关键字段（据截图）", "实例"], rows, [2.4, 7.6, 6.6], size=8.5, center_cols=(0,))

para(doc, "四条关键关系是：小类—参数（一对多）、产标—参数取值（多对多，带定值）、"
          "检项—限值表（通过检验参数关联，并指定取 Min 还是 Max）、检项—申请检项（覆盖关系）。"
          "这个骨架是清晰的，问题不在骨架，而在“值”的表达能力上。", indent=True)

# ---------------- 2 ----------------
heading(doc, "2  落库演练：把 GB/T 3103.3—2000 装进去")

para(doc, "标准内容很少（7 页），但正好覆盖了紧固件公差类标准的典型结构：尺寸公差、形位公差、按厚度分档、"
          "按产品等级分叉、以代号和公式给值。用它来压测模型最合适。", indent=True)

heading(doc, "2.1  参数集（对应步骤②）", level=2)
para(doc, "从“垫圈”小类参数库中勾选 7 个：d₁ 通孔直径、d₂ 外径、h 厚度、h₁ 孔部高度、e 倒角、Δh 厚度不均匀度、"
          "t₁ 同轴度、t₂ 平面度；另加两个“分类型”参数：产品等级（A/C，列表）、材料类型（非不锈钢/不锈钢，列表）。"
          "这一步现有模型完全够用。", indent=True)

heading(doc, "2.2  限值表（对应步骤③）—— 这里是分水岭", level=2)
para(doc, "标准表 1 可以拆成 8 张查询表。逐张看现有模型能否表达：", indent=True)

rows = [
    ["厚度 h", "产品等级 × h 分档", "±0.05 … ±1.6（数值）", "可以", "2 维，纯数值"],
    ["厚度不均匀度 Δh", "产品等级 × h 分档", "0.025 … 0.4（数值）", "可以", "2 维，纯数值"],
    ["平面度 t₂", "产品等级 × 材料 × h 分档", "0.1 … 1.5（数值）", "可以", "3 维，纯数值"],
    ["通孔 d₁", "产品等级 × h 分档", "H13 / H14 / H15", "不行", "值是公差带代号，不是数字"],
    ["外径 d₂", "产品等级 × h 分档", "h14 / h15 / h16", "不行", "同上"],
    ["孔部高度 h₁", "产品等级 × h 分档", "0.5h / 0.3h", "不行", "值是公式，依赖同规格的 h"],
    ["倒角 e / α", "产品等级", "0.25h ~ 0.5h；30°~45°", "不行", "公式型区间 + 角度，且 C 级为空"],
    ["同轴度 t₁", "产品等级 × d₂ 分档", "2IT12 / 2IT13 / 2IT15 / 2IT16", "不行", "代号 × 系数，还要再查 IT 表"],
]
make_table(doc, ["限值表", "维度（坐标参数）", "标准给的值", "现模型能否表达", "症结"],
           rows, [3.0, 3.9, 4.2, 2.4, 3.1], size=8.5, center_cols=(0, 3))

para(doc, "结论：8 张表里只有 3 张能直接落库，5 张卡住。卡住的原因只有一个——"
          "现有“限值明细”是一个数字加一个单位，而标准里的限值有四种形态：数值、代号、公式、引用。"
          "这不是界面问题，是数据模型缺一层。", indent=True, space_before=4)

heading(doc, "2.3  检项与参数（对应步骤④）", level=2)
para(doc, "标准共 9 项需判定（含 1 项前置的适用性确认）、2 项明确“尚未规定”只能记录。落到现有模型：", indent=True)
bullet(doc, "适用判定：C 级不要求 h₁、e/α、Δh、t₂，正好用“列表型 + Y/N”表达（引用参数“产品等级”，A=Y、C=N）。"
            "现有机制够用，这是设计得比较好的一点。")
bullet(doc, "检验参数：d₁、d₂、h、Δh、t₁、t₂ 都是数值结果；e、α、h₁ 也可以按数值处理。"
            "“参数范围”可以写成 X>=400 AND X<=1220 这类表达式，能覆盖固定上下限的场景。")
bullet(doc, "关联限值表：d₁ 这类要靠“公称值 + 极限偏差”算上下限的场景，现有“关联限值表 + 属性 Min/Max”"
            "只能取到一个偏差数，还需要一步“公称 + 偏差 = 极限尺寸”的运算，模型里没有位置。")
bullet(doc, "方法层缺失：量具（塞规／千分尺／投影仪）、测点数量（圆周均布 3 处）、测量部位（带宽中部、避开塌边）、"
            "前置条件（去毛刺后测平面度、镀前尺寸）全部无处安放。检项只能回答“判什么”，回答不了“怎么测”。")

# ---------------- 3 ----------------
heading(doc, "3  六个缺口（按影响排序）")

gaps = [
    ("G1　限值只能填数字，装不下代号、公式与引用",
     "标准里 H13、h14、2IT12、0.5h、0.25h~0.5h 这类写法极常见，尤其在“公差”“性能等级”“螺纹”类标准中。"
     "目前只能人工先查 GB/T 1800.4 换算成数字再录入——等于把标准的换算工作重复做一遍，且一旦标准升版就要全部重算。"
     "这是影响面最大的缺口，也直接决定了步骤③“手工拆分”的工作量。"),
    ("G2　检项没有“方法层”",
     "现有检项只有检验参数／试验参数／中间参数，都是“判什么”。现场要的是“用什么东西、在哪个部位、测几处、什么状态下测”。"
     "GB/T 3103.3 里“去除毛刺后测量平面度”“公差适用于镀前尺寸”这类条件，一旦丢掉，判定结果就不可复现。"),
    ("G3　适用判定只有“列表 + Y/N”",
     "真实标准里适用条件常是组合式：A 级 且 不锈钢 且 d₂≤50 才适用。列表型只能表达单参数枚举，"
     "遇到“材料 × 尺寸段 × 等级”的组合就只能拆成多张表，维护成本随维度乘积增长。"
     "建议保留列表型作为最常用的快捷方式，同时提供表达式型。"),
    ("G4　区间边界语义没有固定",
     "h 分档是 0.5＜h≤1、1＜h≤2.5 这种左开右闭区间，h=2.5 必须唯一归入一档。"
     "截图里“长度范围”写作 \">1 7/8\" - ≤2\"”，是文本描述而非结构化区间，查表时依赖字符串匹配，边界值极易错档。"
     "建议把坐标值存成 (下限, 是否含下限, 上限, 是否含上限)，而不是文本。"),
    ("G5　没有溯源与置信度的位置",
     "“未 OK 数”在截图中随处可见（螺栓 350 条中有 209 条未确认，垫圈 178 条中 111 条未确认），说明人工确认就是主要成本。"
     "但数据里没有“这条来自第几页第几条”“置信度多少”“谁在什么时候确认的”，错了无法回溯，也无法把 AI 预填和人工确认分开统计。"),
    ("G6　单位与量纲不统一",
     "截图里同时出现公制与英制（1 7/8\"、5/32\"、in）。限值明细带了单位，但没有看到换算层。"
     "同一张小类参数库里混着 mm 和 in，一旦有人录错单位，判定结果会静默出错。"),
]
for title, body in gaps:
    heading(doc, title, level=2)
    para(doc, body, indent=True)

# ---------------- 4 ----------------
heading(doc, "4  改进建议")

heading(doc, "4.1  给限值表补“值类型”与“符号表”（解决 G1、G4、G6）", level=2)
para(doc, "不改动现有表结构的主体，只在“限值明细”的每一列上增加四个属性：", indent=True)

rows = [
    ["值类型", "数值 / 代号 / 公式 / 引用", "H13 是代号；0.5h 是公式；2IT12 是“系数 × 引用 IT 表”"],
    ["表达式", "可含变量与函数，如 0.5*h、2*IT(12,d2)、0.25*h ~ 0.5*h", "存公式而非结果，标准升版时只改一处"],
    ["单位与换算", "unit + 基准单位 + 换算系数", "录入 in，内部统一换算为 mm 保存"],
    ["区间定义", "下限/含否、上限/含否，四字段", "替代 “>1 7/8\" - ≤2\"” 这类文本"],
]
make_table(doc, ["新增属性", "取值", "举例"], rows, [3.4, 6.4, 6.8], size=8.5, center_cols=(0,))

para(doc, "配一张独立的“符号表”（公差带代号 H13/h14、IT 等级、材料牌号、性能等级均可共用），"
          "由系统按“代号 + 公称尺寸”查表展开为极限偏差。这样 d₁ 的限值表只存一个 H13，"
          "实际上下限由系统按公称直径实时算出，既省录入，又能在标准升版时一处修改全局生效。", indent=True, space_before=4)

heading(doc, "4.2  给检项加“方法卡”（解决 G2）", level=2)
para(doc, "在检项下新增一层“方法”，至少四个字段：量具／设备、测量部位、测点数量与分布、前置条件。"
          "方法可以是标准原文规定的，也可以是推荐做法——两者要能区分，因为只有前者具备判定效力。"
          "上一轮交付的检验卡（Word／Excel）本质上就是方法卡的可打印形态，可以直接作为输出样板。", indent=True)

heading(doc, "4.3  适用判定升级为“列表 + 表达式”双模（解决 G3）", level=2)
para(doc, "保留列表型（覆盖 80% 场景，录入快），增加表达式型：引用产标参数 + 比较运算 + 逻辑组合。"
          "表达式型可以复用检验参数已有的 “X>=400 AND X<=1220” 解析器，工程量不大。", indent=True)

heading(doc, "4.4  全链路加溯源字段（解决 G5）", level=2)
para(doc, "每个参数、每张限值表、每个检项都加：来源（页码／条款号）、原文摘录、抽取方式（人工／AI）、置信度、"
          "确认人、确认时间。界面上一眼可见“未确认”与“低置信度高亮”，人工只做确认不做录入。", indent=True)

heading(doc, "4.5  流程从“四步手工”改为“三阶段半自动”", level=2)

rows = [
    ["抽取", "PDF → 候选参数、候选限值表、候选检项（带页码与原文）", "AI／规则，全自动", "只产出候选，不直接入库"],
    ["归一", "候选对齐到参数库与符号表，人工确认与补全", "AI 预填 + 人确认", "这是当前“未 OK 数”对应的环节，应压缩到只点确认"],
    ["应用", "选规格 → 命中限值 → 与实测比对 → 出检验卡", "全自动，确定性计算", "不允许模型参与数值计算"],
]
make_table(doc, ["阶段", "做什么", "执行方", "边界"], rows, [2.2, 7.2, 3.6, 3.6], size=8.5, center_cols=(0,))

para(doc, "关键是把“展开成行”再往前推一步：既然系统已经能按维度展开，就应该同时支持“按代号批量生成”"
          "（选 H13 + 尺寸段 → 自动生成该段所有档的数值）和“同值填充”（C 级 h16 一档填一次，自动铺满）——"
          "这两件事能砍掉步骤③大半的录入手工。", indent=True, space_before=4)

heading(doc, "4.6  服务化建议（衔接上一轮的讨论）", level=2)
para(doc, "若要做成对外的网页服务，建议先做“标准 → 限值表 → 检验卡”的批处理 + 人工确认工作台，"
          "而不是一上线就做在线实时判定。原因：判定逻辑依赖大量人工确认过的数据，"
          "在数据尚未覆盖时，实时判定的错误率会直接损伤信任；而“帮你把标准拆成可用的检验卡”是立刻能交付价值的一步。"
          "技术形态仍是 FastAPI + 单页前端，本机可跑，后续再加账号与多租户。", indent=True)

# ---------------- 5 ----------------
heading(doc, "5  分期路线与验收")

rows = [
    ["P0（1～2 周）", "补值类型／符号表／区间四字段；用 GB/T 3103.3 全量跑通 8 张限值表 + 9 个检项",
     "该系统能完整表达该标准，且 d₁ 的上下限由系统算出而非人工录入"],
    ["P1（3～4 周）", "方法卡、适用表达式、溯源字段；再压测 2～3 个不同结构的标准（如 GB/T 97.1 产品尺寸、GB/T 3098.1 机械性能）",
     "换一类标准时不需要改代码，只加数据"],
    ["P2（5～8 周）", "AI 抽取 + 人工确认工作台；批量生成限值表；检验卡导出",
     "单标准人工工时下降 50% 以上，且每条数据可溯源到条款"],
]
make_table(doc, ["阶段", "范围", "验收标准"], rows, [2.6, 8.6, 5.4], size=8.5, center_cols=(0,))

para(doc, "风险提示：最容易低估的是 G1。它看起来只是一个字段，实际会牵动限值表的展开逻辑、查表引擎与标准升版策略；"
          "如果 P0 阶段只做界面不做这一层，后面每接一个公差类标准都要返工一次。"
          "建议先拿 GB/T 3103.3 这种“小而全”的标准把 G1 打穿，再谈通用化。", indent=True, space_before=6)

doc.save("现有产品标准分析流程 分析与改进建议.docx")
print("saved")
