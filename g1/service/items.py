# -*- coding: utf-8 -*-
"""检项元数据：检项 ↔ 限值表 ↔ 参数 ↔ 实测键的绑定。

命名约定（贯穿全系统）：
  *_nom  公称尺寸，参数层，唯一允许用于查表分档
  *_act  实际尺寸，记录层，只用于与极限比较
  限值    由 公称 + 偏差 派生，不落库

method / position / gauge / points 为标准未规定的实施建议，
页面上与“标准规定”分栏展示。
"""
from __future__ import annotations

# requires: 解析本检项所需的公称参数（缺则降级为 MISS）
# nominal_param: 限值的公称依据，仅用于展示“这个限值是从哪个公称值算出来的”
# measured_key: 实测值的字段名，统一 *_act
ITEMS: list[dict] = [
    dict(
        id="d1", name="通孔直径", symbol="d₁", clause="3.1", table="T-D1", kind="尺寸",
        requires=["d1_nom"], nominal_param="d1_nom", measured_key="d1_act",
        method="批量用 H13/H14/H15 光滑极限塞规通、止检验；计量用内径千分尺或游标卡尺在"
               "互相垂直的两个方向测量",
        position="取孔壁圆柱直段（h₁ 段）内的轴向中部截面，避开塌边与撕裂带",
        gauge="光滑极限塞规、内径千分尺(0.01)、游标卡尺(0.02)",
        points="2 个互相垂直方向",
        measured_hint="实测 d₁（mm）",
    ),
    dict(
        id="h1", name="孔部高度", symbol="h₁", clause="3.1", table="T-H1", kind="尺寸",
        requires=[], nominal_param="h_nom", measured_key="h1_act",
        method="投影仪或工具显微镜按 5∶1 放大，测量孔壁未塌边的直段高度",
        position="孔壁直线段，不含塌边与撕裂带",
        gauge="投影仪、工具显微镜、深度尺",
        points="圆周均布 3 处，取最小值",
        measured_hint="实测 h₁（mm）",
    ),
    dict(
        id="d2", name="外径", symbol="d₂", clause="3.2", table="T-D2", kind="尺寸",
        requires=["d2_nom"], nominal_param="d2_nom", measured_key="d2_act",
        method="外径千分尺在互相垂直两方向测量，取最大、最小值；批量可用卡规或影像测量仪",
        position="卡在 d₂ 圆柱面上，避开外缘塌边过渡区",
        gauge="外径千分尺(0.01)、卡规、影像测量仪",
        points="2 个方向，分别取最大与最小",
        measured_hint="实测 d₂（mm）",
    ),
    dict(
        id="h", name="厚度", symbol="h", clause="3.3", table="T-H", kind="尺寸",
        requires=[], nominal_param="h_nom", measured_key="h_act",
        method="外径千分尺（平测头）测量；镀前状态下进行",
        position="孔边与外缘之间的带宽中部，避开倒角区与塌边",
        gauge="外径千分尺(0.01) 或厚度千分尺",
        points="沿圆周均布 3 点，逐点判定",
        measured_hint="实测 h（mm）",
    ),
    dict(
        id="e", name="倒角", symbol="e、α", clause="3.4", table="T-E", kind="尺寸",
        requires=[], nominal_param="h_nom", measured_key="e_act",
        method="投影仪或影像测量仪放大后，测量倒角斜面轴向宽度 e 与倒角角 α；可用倒角样板比对",
        position="圆周抽测 2～3 处",
        gauge="投影仪、影像测量仪、角度尺",
        points="2～3 处",
        measured_hint="实测 e（mm）；另需目视确认 α = 30°～45°",
    ),
    dict(
        id="dh", name="同一部位厚度不均匀度", symbol="Δh", clause="3.5.1", table="T-DH", kind="形位",
        requires=[], nominal_param="h_nom", measured_key="dh_act",
        method="在中间测量带内沿圆周均布 ≥3 个径向位置测厚，取同一部位最大厚度与最小厚度之差",
        position="自孔内棱边至外棱边、距两边各 x = 0.1(d₂−d₁) 的中间带（原文注“圆周宽度的 60%”）",
        gauge="外径/厚度千分尺(0.001 或 0.01)、测厚夹具",
        points="≥3 个径向位置，每处测最厚与最薄",
        measured_hint="实测 Δh = h_max − h_min（mm）",
    ),
    dict(
        id="t1", name="同轴度", symbol="t₁", clause="3.5.2", table="T-T1", kind="形位",
        requires=["d2_nom"], nominal_param="d2_nom", measured_key="t1_act",
        method="仲裁：三坐标测量机测内孔与外圆两圆柱面，按 GB/T 1182 评定；批量可用心轴＋百分表检具；"
               "壁厚差法仅作快速筛查",
        position="基准 A 为 φd₂ 外圆轴线，被测要素为 φd₁ 内孔轴线",
        gauge="三坐标测量机、同轴度检具、壁厚千分尺",
        points="整周",
        measured_hint="同轴度误差（mm）",
    ),
    dict(
        id="t2", name="平面度", symbol="t₂", clause="3.5.3", table="T-T2", kind="形位",
        requires=[], nominal_param="h_nom", measured_key="t2_act",
        method="先去除毛刺；将垫圈自由放置在 0 级平板上用塞尺测最大间隙；或用百分表沿圆周均布 ≥6 点"
               "测量，取最大读数差",
        position="整件，自由状态，不得施压",
        gauge="0 级平板、塞尺、百分表/千分表及表架",
        points="≥6 点",
        measured_hint="平面度误差（mm）",
    ),
]

ITEM_BY_ID = {i["id"]: i for i in ITEMS}
