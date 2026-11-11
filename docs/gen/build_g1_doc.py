# -*- coding: utf-8 -*-
"""生成《G1 专项：限值类型体系设计》DOCX。"""
from docx import Document
from docx.shared import Pt, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

BODY_FONT = "宋体"
HEAD_FONT = "黑体"
MONO_FONT = "Courier New"


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


def para(doc, text="", size=10.5, bold=False, indent=True, space_before=0, space_after=4):
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


def code(doc, text, size=8.5):
    t = doc.add_table(rows=1, cols=1)
    t.style = "Table Grid"
    t.autofit = False
    trPr = t.rows[0]._tr.get_or_add_trPr()
    trPr.append(OxmlElement("w:cantSplit"))
    cell = t.rows[0].cells[0]
    cell.width = Cm(16.2)
    cell.text = ""
    for i, line in enumerate(text.split("\n")):
        p = cell.paragraphs[0] if i == 0 else cell.add_paragraph()
        p.paragraph_format.space_before = Pt(0)
        p.paragraph_format.space_after = Pt(0)
        p.paragraph_format.line_spacing = 1.0
        r = p.add_run(line if line else " ")
        set_run_font(r, MONO_FONT, size)
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), "F4F4F4")
    tcPr.append(shd)
    doc.add_paragraph().paragraph_format.space_after = Pt(2)


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


def cell_text(cell, text, size=9, bold=False, align="left", font=BODY_FONT):
    cell.text = ""
    for i, line in enumerate(str(text).split("\n")):
        p = cell.paragraphs[0] if i == 0 else cell.add_paragraph()
        p.paragraph_format.space_before = Pt(0)
        p.paragraph_format.space_after = Pt(0)
        p.paragraph_format.line_spacing = 1.05
        p.alignment = {"left": WD_ALIGN_PARAGRAPH.LEFT, "center": WD_ALIGN_PARAGRAPH.CENTER}[align]
        r = p.add_run(line)
        set_run_font(r, font, size, bold)


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
        for i, v in enumerate(row):
            cell_text(r.cells[i], v, size, False, "center" if i in center_cols else "left")
            vcenter(r.cells[i])
    for r in t.rows:
        for i, w in enumerate(widths):
            r.cells[i].width = Cm(w)
    for r in t.rows[:-1]:
        trPr = r._tr.get_or_add_trPr()
        trPr.append(OxmlElement("w:cantSplit"))
        for c in r.cells:
            for p in c.paragraphs:
                p.paragraph_format.keep_with_next = True
    return t


doc = Document()
style_setup(doc)
sec = doc.sections[0]
sec.page_width, sec.page_height = Cm(21.0), Cm(29.7)
sec.left_margin = sec.right_margin = Cm(2.2)
sec.top_margin = Cm(2.1)
sec.bottom_margin = Cm(1.9)

p = doc.add_paragraph()
p.alignment = WD_ALIGN_PARAGRAPH.CENTER
r = p.add_run("G1 专项：限值类型体系设计")
set_run_font(r, HEAD_FONT, 18, True)

p = doc.add_paragraph()
p.alignment = WD_ALIGN_PARAGRAPH.CENTER
p.paragraph_format.space_after = Pt(4)
r = p.add_run("—— 让限值表装得下代号、公式与引用")
set_run_font(r, BODY_FONT, 11)

p = doc.add_paragraph()
p.alignment = WD_ALIGN_PARAGRAPH.CENTER
p.paragraph_format.space_after = Pt(12)
r = p.add_run("附带可运行原型：g1/limit_engine.py + g1/gb3103_3.py（28 项断言全部通过）")
set_run_font(r, BODY_FONT, 9)

# ---------------- 1 ----------------
heading(doc, "1  问题重述")

para(doc, "G1 的一句话版本：限值明细的“值”现在是一个数字，而标准里的限值其实是一个函数——"
          "在给定规格、等级、材料之前，它没有唯一值。", indent=True)

para(doc, "GB/T 3103.3 里随手能拎出四种写法：", indent=True)
rows = [
    ["厚度 h", "±0.2", "数字，直接可用", "现在就能存"],
    ["通孔 d₁", "H13", "代号，要查 GB/T 1800.4 才知道是 +0.27", "装不下"],
    ["孔高 h₁", "0.5h", "公式，依赖同规格的 h", "装不下"],
    ["同轴度 t₁", "2IT12", "代号 × 系数，还要按 d₂ 分档查表", "装不下"],
]
make_table(doc, ["检项", "标准写法", "它到底是什么", "现状"], rows,
           [3.0, 3.2, 7.4, 3.0], size=8.5, center_cols=(0, 1, 3))

para(doc, "更麻烦的是：这四种写法在同一个检项里会混着出现。t₁ 的 2IT12 要用 d₂ 的公称值去查尺寸段，"
          "而 d₁ 的 H13 要用 d₁ 自己的公称值去查。同一个检项里两个代号，基准参数不同。", indent=True, space_before=4)

# ---------------- 2 ----------------
heading(doc, "2  值的四种形态")

para(doc, "判断一个值属于哪类，只需要问一句：换一个规格，这个值会不会变？", indent=True)
rows = [
    ["常量 CONST", "不会变", "±0.2、0.025、0.1", "存原值 + 单位"],
    ["代号 SYMBOL", "随公称尺寸变，但不由标准正文给，而在另一张表里", "H13、h14、IT12、2IT12",
     "存代号 + 系数 + 基准参数，运行时查符号表"],
    ["公式 FORMULA", "随同规格的其他参数变", "0.5h、0.25h~0.5h、0.1(d₂−d₁)",
     "存表达式，运行时按上下文求值"],
    ["引用 REF", "随另一处数据变", "“根据产品标准”“见附录 A 表 3”", "存引用路径，运行时解析"],
]
make_table(doc, ["形态", "什么时候变", "标准里的样子", "系统怎么存"], rows,
           [2.9, 4.4, 5.2, 4.1], size=8.5, center_cols=(0,))

para(doc, "判断顺序建议：常量 → 代号 → 公式 → 引用。先看是不是纯数字；不是数字就看是不是能在一张"
          "“代号—尺寸段—数值”的表里查到；再不是就看能不能用已有参数算出来；最后才落到引用。"
          "这个顺序也决定了录入界面的默认交互：能查的不要让人算，能算的不要让人填。", indent=True, space_before=4)

# ---------------- 3 ----------------
heading(doc, "3  三个比“四类值”更容易漏的语义")

para(doc, "只做“四类值”是不够的。下面三项如果不一起补，四类值照样会算错。", indent=True)

heading(doc, "3.1  三态：不要求 ≠ 未规定 ≠ 没有值", level=2)
para(doc, "C 级件的 h₁、倒角、Δh、t₂ 是“标准明确不要求”；h₂ 和塌边是“标准尚未规定，只记录”。"
          "这两者都不是空值，判定结论也不同：前者应直接判“本项目不适用”，后者应判“无判定依据，仅记录”。"
          "如果都用 NULL，报表里会长期显示“数据缺失”，C 级件的缺项统计永远降不下来，"
          "而且会把“不要求”误当成“没录”。", indent=True)
rows = [
    ["OK", "有值，可判定", "d₁ = 13.00～13.27", "合格 / 不合格"],
    ["NOT_REQUIRED", "标准明确不要求（如 C 级）", "C 级 h₁", "不适用（不计入不合格，也不计入缺项）"],
    ["UNSPECIFIED", "标准尚未规定（如 h₂、塌边）", "“尚待提出”", "仅记录，不作判定"],
    ["MISS", "上下文不足或尺寸超出表范围", "d₂ = 300 mm 超出 1～150 覆盖", "不能判，需人工确认"],
]
make_table(doc, ["状态", "含义", "例子", "对判定的影响"], rows,
           [3.0, 5.2, 4.4, 4.0], size=8.5, center_cols=(0,))

heading(doc, "3.2  偏差型与绝对值型必须分开", level=2)
para(doc, "厚度 h 的 ±0.2 是偏差，判定时要叠加公称值，得 1.8～2.2；厚度不均匀度 Δh 的 0.1 是绝对量，"
          "直接比较，不能叠加任何公称值。两者在表里都是一个数字，但判定语义完全相反。", indent=True)
para(doc, "现有“属性 Min/Max”只说了取上还是取下，没说取到之后要不要叠加公称值——这就是为什么 d₁ 这类"
          "“公称 + 偏差 = 极限尺寸”的运算在系统里没有位置。建议在限值表表头增加 value_form 字段："
          "DEVIATION（偏差）或 ABSOLUTE（绝对量），偏差型再记一个 nominal_param（叠加哪个参数）。", indent=True)

heading(doc, "3.3  基准参数：2IT12 查的是 d₂ 的档，不是 d₁ 的档", level=2)
para(doc, "这是整套设计里最容易漏、也最致命的一个字段。同一个检项“尺寸”里：", indent=True)
bullet(doc, "d₁ 的 H13 —— 用 d₁ = 13 mm 去查（10～18 档），得 +0.27；")
bullet(doc, "t₁ 的 2IT12 —— 要用 d₂ = 24 mm 去查（18～30 档），得 IT12 = 0.21，再乘 2 得 0.42。")
para(doc, "如果把 t₁ 的代号也拿 d₁ 去查，13 mm 落在 10～18 档，IT12 = 0.18，结果 0.36，比正确值小 14%——"
          "而且这个错误不会报错，只会静默给出一个偏严的限值。所以限值明细必须存 basis_param（基准参数名），"
          "不能默认“用被测要素自己的公称值”。", indent=True, space_before=2)

# ---------------- 4 ----------------
heading(doc, "4  符号表设计")

para(doc, "四类值里只有“代号”需要外部数据支撑。建议建一张独立的符号表，而不是把 H13 的数值硬写进限值明细。", indent=True)

heading(doc, "4.1  两种符号族，不能混用", level=2)
rows = [
    ["极限偏差型", "给上下偏差两个数", "H13 → 0 / +0.27；h14 → −0.52 / 0",
     "尺寸类（d₁、d₂、长度、螺纹）"],
    ["公差值型", "只给公差带宽，偏差由基本偏差决定", "IT12 → 0.21",
     "形位公差（t₁）、未注公差、分级取值"],
]
make_table(doc, ["符号族", "定义", "例子", "典型用途"], rows,
           [3.2, 5.0, 5.0, 3.4], size=8.5, center_cols=(0,))

para(doc, "为什么必须分开：H13 天然带正负方向（孔取正、轴取负），而 IT12 只是一个宽度，方向由使用者决定。"
          "把 2IT12 当成“公差带代号”去查，会查不到；把 H13 当成“公差值”去用，会丢掉符号。"
          "原型里两种各有一个枚举，查错会直接抛异常，不会静默出错。", indent=True, space_before=3)

heading(doc, "4.2  表结构", level=2)
code(doc, """symbol_set   (id, set_code, name, version, source_std,
              effective_date, status)
symbol_entry (id, set_id, code, size_from, size_to,
              kind,            -- DEVIATION | TOLERANCE
              lower_dev, upper_dev,   -- kind=DEVIATION 用
              tol,                    -- kind=TOLERANCE 用
              unit)
  UNIQUE (set_id, code, size_from)""")

para(doc, "尺寸段统一用左开右闭 (size_from, size_to]，与 GB/T 1800 的表述 “＞10～18” 一致；"
          "第一段 size_from = 0 且含 0，覆盖 ≤3 的情形。这一条必须写死在约定里，不能各表各写。", indent=True)

heading(doc, "4.3  与限值表的关系", level=2)
para(doc, "限值明细不存“H13 的数值”，只存 'GB1800-1998:H13' 这样的引用，外带系数与基准参数。"
          "好处有三：一是同一代号在几十张表里复用，改一处全局生效；二是标准升版时新增一个 symbol_set 版本即可，"
          "旧数据仍指向旧版本，可回放；三是录入时只需选代号，不用查表换算，直接消灭了步骤③里最大的一块手工。", indent=True)

# ---------------- 5 ----------------
heading(doc, "5  数据结构改造")

para(doc, "不动现有主键，只做加法。限值明细加 6 列，限值表头加 2 列，另建符号表 2 张。", indent=True)
code(doc, """-- 限值表头
ALTER TABLE limit_table
  ADD value_form     VARCHAR(16) DEFAULT 'ABSOLUTE',  -- DEVIATION | ABSOLUTE
  ADD nominal_param  VARCHAR(32),                     -- 偏差型叠加哪个参数
  ADD symbol_set_id  BIGINT;                          -- 本表引用的符号表版本

-- 限值明细（每个值槽一份，下限 / 上限各一）
ALTER TABLE limit_detail
  ADD value_type   VARCHAR(16) DEFAULT 'CONST',       -- CONST|SYMBOL|FORMULA|REF
  ADD expr_text    VARCHAR(255),                      -- 公式或引用表达式
  ADD symbol_ref   VARCHAR(64),                       -- 'SET:H13'
  ADD symbol_mult  DECIMAL(10,4) DEFAULT 1,           -- 2IT12 里的 2
  ADD basis_param  VARCHAR(32),                       -- 代号用哪个参数的尺寸查档
  ADD status       VARCHAR(16) DEFAULT 'OK';          -- OK|NOT_REQUIRED|UNSPECIFIED

-- 坐标值（区间型参数）
ALTER TABLE limit_axis_value
  ADD lower_bound, upper_bound      DECIMAL(18,6),
  ADD lower_inclusive, upper_inclusive BOOLEAN;""")

para(doc, "两个设计取舍值得说明：", indent=True, space_before=2)
bullet(doc, "不用一个大 JSON 存“值”。JSON 能塞下一切，但查表引擎要解析、报表要拆解、校验要写一套运行时规则，"
            "最后等于在数据库里又写了一个数据库。结构化列 + 一个表达式列，够用且可索引。")
bullet(doc, "表达式存字符串但不直接 eval。原型里用 AST 白名单求值，只允许四则运算、括号和 min/max/round，"
            "变量名必须在上下文里存在。这样即使表达式来自外部导入，也不会变成代码执行漏洞。")

# ---------------- 6 ----------------
heading(doc, "6  解析算法")

para(doc, "一次查表分六步，每步都留下 trace，事后可以逐行回放“这个限值是怎么算出来的”。", indent=True)
code(doc, """resolve(table, ctx):
  1  维度求键    enum 维度直接取值；size 维度找 ctx 值落入的区间段
  2  命中行      未命中 -> MISS（不是 0，也不是 NULL）
  3  行级适用    applicable = false -> NOT_REQUIRED（C 级不要求走这里）
  4  值槽求值    CONST 取值 / SYMBOL 查符号表 / FORMULA 求值 / REF 解析引用
  5  形态换算    value_form = DEVIATION 时，叠加 nominal_param 的公称值
  6  产出        返回 (status, lower, upper, unit, trace)""")

para(doc, "第 4 步里代号求值的细节：", indent=True, space_before=2)
code(doc, """lookup('SET:H13', basis_param='d1_nom', part='upper', mult=1):
    size = ctx['d1_nom']                  -- 注意：用的是 basis_param，不是当前要素
    entry = symbol_set.lookup('H13', size)
    return entry.upper_dev * mult         -- TOLERANCE 型则返回 tol * mult""")

para(doc, "trace 的实际输出（原型跑出来的），一条 d₁ 的解析记录：", indent=True, space_before=3)
code(doc, """命中维度 grade=A, h_nom=(0, 4);
代号 H13@18.0 -> 0.0;
代号 H13@18.0 -> 0.27;
叠加公称值 18.0
=> [18.000, 18.270] mm""")

# ---------------- 7 ----------------
heading(doc, "7  七个坑（都踩过）")

rows = [
    ["区间开闭", "h 分档是 0.5＜h≤1、1＜h≤2.5，h = 2.5 必须唯一归入 (1, 2.5]",
     "四个字段存上下限与含否，禁止用文本 “＞1 7/8\" - ≤2\"” 匹配"],
    ["合并单元格", "C 级 h16 一档跨了 h≤4 与 h>4 两行", "展开时显式记“同值填充”，不要人工复制两遍"],
    ["单边限", "h₁ 只给下限 0.5h，没有上限", "上限存空表示 +∞，与“不要求”区分开"],
    ["无量纲值", "倒角 α = 30°～45°，不是长度", "值槽带 unit，角度单独给 deg，禁止塞进 mm 列"],
    ["浮点比较", "0.3 × 6 = 1.7999999999999998", "存 DECIMAL 或统一 round 到 6 位后比较，展示再格式化"],
    ["超出覆盖", "d₂ = 300 超出 1～150 mm 适用范围", "返回 MISS 并提示“超出标准范围”，不能返回 0 或空"],
    ["同值不同源", "C 级 h16 与 A 级 h14 在部分档数值相同，但代号不同",
     "不能因数值相同就合并成一个代号，否则升版时分叉"],
]
make_table(doc, ["坑", "表现", "处理"], rows, [2.4, 7.6, 6.4], size=8.5, center_cols=(0,))

# ---------------- 8 ----------------
heading(doc, "8  版本与升版")

para(doc, "符号表必须带版本，限值表引用具体版本号而不是“当前版本”。理由很直接："
          "GB/T 1800 从 1979 换到 1998 时，部分 IT 值有微调；GB/T 3103.3 从 1982 换到 2000 时，"
          "用 Δh 替掉了“平行度”。如果引用“当前版本”，老标准的限值会在某次升级后悄悄变化，历史判定结果无法复现。", indent=True)
para(doc, "做法：升版 = 新增一条 symbol_set 记录，旧记录保留且状态置为“已废止（仅供历史回放）”；"
          "限值表通过 symbol_set_id 固定引用。再配一个 diff 视图，升版时列出“哪些档的数值变了、影响哪些检项”。", indent=True)

# ---------------- 9 ----------------
heading(doc, "9  存量数据迁移")

para(doc, "现有数据全是数值型，迁移不需要重构，分四步：", indent=True)
rows = [
    ["① 加列", "按第 5 章 DDL 加列，默认值 value_type='CONST'、status='OK'", "旧代码完全不受影响"],
    ["② 标形态", "把“属性＝Min/Max”的行标为 ABSOLUTE 或 DEVIATION；建议先按检项类型给默认值再由人复核",
     "尺寸类默认 DEVIATION，形位与差值类默认 ABSOLUTE"],
    ["③ 建符号表", "先只导 IT 值与常用公差带（GB/T 1800.2～1800.4），再逐步替换已有的硬编码数值",
     "替换是可选的，两者并存不冲突"],
    ["④ 双跑", "新旧引擎并行，抽样比对读数；一致率达标后切换", "建议先在 GB/T 3103.3 这类小标准上双跑"],
]
make_table(doc, ["步骤", "做什么", "注意"], rows, [2.4, 8.4, 5.6], size=8.5, center_cols=(0,))

para(doc, "迁移里最值得投入的是第②步的“形态标注”。它决定了历史数据能不能被新引擎直接复用；"
          "如果标错，判定会静默出错，比迁移失败更危险。建议对存量数据做一次抽样人工核对，抽样比例不低于 5%。", indent=True, space_before=4)

# ---------------- 10 ----------------
heading(doc, "10  原型验证结果")

para(doc, "为了确认这套设计不是纸上推演，我写了可运行的原型：limit_engine.py 实现四类值、三态、"
          "偏差/绝对值与基准参数；gb3103_3.py 把 GB/T 3103.3—2000 表 1 的 8 张查询表全部建成数据并逐项断言。"
          "28 项断言全部通过。", indent=True)

para(doc, "A 级与 C 级在 h=2、d₁=13、d₂=24、非不锈钢条件下的解析结果：", indent=True, space_before=2)
rows = [
    ["厚度 h", "1.800 ～ 2.200", "1.700 ～ 2.300", "常量 ±，偏差型叠加公称值"],
    ["通孔 d₁", "13.000 ～ 13.270", "13.000 ～ 13.430", "代号 H13 / H14，按 d₁ 查档"],
    ["外径 d₂", "23.480 ～ 24.000", "22.700 ～ 24.000", "代号 h14 / h16，按 d₂ 查档"],
    ["孔高 h₁", "≥ 1.000（0.5h）", "不要求", "公式；C 级三态"],
    ["倒角 e", "0.500 ～ 1.000", "不要求", "公式区间 0.25h～0.5h"],
    ["Δh", "≤ 0.100", "不要求", "常量，绝对量"],
    ["同轴度 t₁", "≤ 0.420", "≤ 1.680", "2IT12 / 2IT15，按 d₂ 查档后乘 2"],
    ["平面度 t₂", "≤ 0.200", "不要求", "常量，按材料分表"],
]
make_table(doc, ["检项", "A 级结果（mm）", "C 级结果（mm）", "用到的值形态"], rows,
           [2.6, 4.4, 4.0, 5.4], size=8.5, center_cols=(0, 1, 2))

para(doc, "边界与基准参数的验证（摘录）：", indent=True, space_before=3)
rows = [
    ["d₁ = 18", "18.000 ～ 18.270", "18 落在 (10,18]，H13 = 0.27，区间右端闭合"],
    ["d₁ = 18.01", "18.010 ～ 18.340", "落 (18,30]，H13 = 0.33，档位切换正确"],
    ["d₂ = 50 / 50.1", "0.50 / 0.92（t₁）", "50 走 2IT12，50.1 走 2IT13，基准参数为 d₂ 而非 d₁"],
    ["h = 2.5 / 2.51", "2.30～2.70 / 2.21～2.81", "2.5 归 (1,2.5]，2.51 归 (2.5,4]"],
    ["d₂ = 300", "MISS", "超出 1～150 mm 适用范围，拒绝判定而非返回空"],
]
make_table(doc, ["输入", "结果", "说明"], rows, [3.6, 4.4, 8.4], size=8.5, center_cols=(0, 1))

para(doc, "一个值得记录的插曲：我第一版手写的期望值有三处是错的——把 h16 在 18～30 档记成 0.9（实为 1.3）、"
          "把 18.01＋0.33 算成 18.33、把不锈钢 1＜h≤2.5 的 t₂ 记成 0.2（实为 0.3）。引擎三处都判了 FAIL，"
          "复盘后确认是人的问题。这恰好说明 G1 真正的价值：不是省录入，而是把这类“人一定会犯、且不会报错”的查表错误消灭掉。", indent=True, space_before=4)

# ---------------- 11 ----------------
heading(doc, "11  工作量与建议")

rows = [
    ["加列与迁移", "0.5 人日", "6 列 + 2 列，纯增量，不影响旧代码"],
    ["符号表与导入", "1.5 人日", "IT 值 + 常用公差带约 200 条，一次性脚本导入"],
    ["表达式引擎", "1 人日", "白名单 AST，原型已验证可行，可直接复用"],
    ["查表引擎改造", "2 人日", "六步流程 + trace，替换现有取数逻辑"],
    ["界面调整", "2 人日", "限值录入从“填数字”改为“选类型 + 填参数”"],
    ["双跑与验收", "1 人日", "GB/T 3103.3 全量 + 抽样比对"],
]
make_table(doc, ["项", "估算", "说明"], rows, [3.4, 3.0, 10.0], size=8.5, center_cols=(0, 1))

para(doc, "合计约 8 人日。这个量级远小于“每个标准重新人工查表”的长期成本，"
          "也是我建议把它放进 P0 而不是 P1 的原因：一旦限值表能存代号，步骤③的“手工拆分”就从"
          "“逐格查表填数”退化为“选代号”，这是整条链路里投入产出比最高的一处改动。", indent=True, space_before=4)

para(doc, "风险仍然存在，但不在技术上：符号表的权威性需要业务方认账（用哪一版 GB/T 1800、"
          "IT 值取 1998 还是 1988），这一点必须由标准化归口部门确认后再导入，否则算得再准也是错的。", indent=True)

doc.save("G1 限值类型体系设计.docx")
print("saved")
