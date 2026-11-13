# -*- coding: utf-8 -*-
"""把数据库逻辑分层图 / ER 图渲染成 PNG。

    python3 docs/gen_db_diagrams.py

产物：
    docs/db-logical-view.png   四个逻辑领域的分层结构
    docs/db-er.png             实体关系图（主键 / 外键 / 基数）

实现：本地 mermaid.min.js + 无头 Chrome 截图 + PIL 裁边，
不依赖网络，也不依赖 graphviz。
"""
from __future__ import annotations

import html as _html
import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageChops

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs"
WORK = ROOT / ".build-cache" / "db-diagrams"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
MERMAID_SRC = ROOT / ".build-cache" / "mermaid.min.js"

# 渲染参数：width/height 是视口，先给足再裁边
CANVAS = {"arch": (2600, 1500), "er": (2600, 3600)}

THEME = """
  :root { color-scheme: light; }
  html, body { margin: 0; padding: 0; background: #ffffff; }
  body {
    padding: 36px;
    font-family: -apple-system, BlinkMacSystemFont, "PingFang SC",
                 "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
  }
  .mermaid { display: flex; justify-content: flex-start; margin: 0; background: none; }
  pre.mermaid { font-family: inherit; white-space: pre; }
"""

INIT = """
mermaid.initialize({
  startOnLoad: false,
  theme: "base",
  securityLevel: "loose",
  fontFamily: '-apple-system, BlinkMacSystemFont, "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif',
  themeVariables: {
    fontSize: "15px",
    primaryColor: "#eef6ff",
    primaryBorderColor: "#85b8ff",
    primaryTextColor: "#1f2937",
    lineColor: "#94a3b8",
    tertiaryColor: "#ffffff",
  },
  flowchart: { useMaxWidth: false, htmlLabels: true, curve: "basis", nodeSpacing: 46, rankSpacing: 64 },
  er: { useMaxWidth: false, entityPadding: 18, minEntityWidth: 130 },
});
"""

ARCH = """flowchart LR
    subgraph S4["④ 分类与参数知识库域"]
        direction TB
        PC["product_class<br/>产品小类"]
        PN["param_name<br/>参数名称（支持多维）"]
        CP["class_param<br/>小类 ↔ 参数"]
        SP["sub_param<br/>二级参数（坐标轴）"]
        PV["param_value<br/>参数定值（含坐标值）"]
        PC --> CP
        PN --> CP
        PN --> SP
        PN --> PV
    end

    subgraph S1["① 原件与追溯域"]
        direction TB
        DOC["document<br/>PDF 原件<br/>主键 = SHA-256"]
        SD["standard_document<br/>标准 ↔ 原件"]
        DOC --> SD
    end

    subgraph S2["② 标准实体与分层域"]
        direction TB
        STD["standard<br/>标准主表<br/>item / param / limits"]
        SC["standard_class<br/>标准 × 产品小类<br/>一层一套参数与限值"]
        STD -->|1 : N 分层| SC
    end

    subgraph S3["③ 多维限值与矩阵域"]
        direction TB
        LM["limit_matrix<br/>复合母表（表 3 类）"]
        SM["table_split_mode<br/>拆分模式知识库"]
        LT["limit_table<br/>单张限值表<br/>sc_id / item_code"]
        LD["limit_dim<br/>维度定义"]
        LR["limit_row<br/>限值明细行"]
        SM -.->|指导拆解| LM
        LM -.->|拆解派生| LT
        LT --> LD
        LT --> LR
    end

    SD ==>|归档| STD
    PC -.->|划分| SC
    STD ==>|拥有| LM
    SC -.->|挂载| LT

    classDef dom fill:#f8fafc,stroke:#cbd5e1,stroke-width:2px;
    class S1,S2,S3,S4 dom;
"""

ER = """erDiagram
    STANDARD ||--o{ STANDARD_CLASS : "1:N 分层"
    STANDARD ||--o{ LIMIT_TABLE : "1:N 拥有"
    STANDARD ||--o{ LIMIT_MATRIX : "1:N 拥有"
    STANDARD ||--o{ STANDARD_DOCUMENT : "1:N 挂接"
    DOCUMENT ||--o{ STANDARD_DOCUMENT : "1:N 关联"

    PRODUCT_CLASS ||--o{ STANDARD_CLASS : "1:N 划分"
    PRODUCT_CLASS ||--o{ CLASS_PARAM : "1:N 挂载"
    PARAM_NAME ||--o{ CLASS_PARAM : "1:N 被引用"
    PRODUCT_CLASS ||--o{ SUB_PARAM : "1:N 所属"
    PARAM_NAME ||--o{ SUB_PARAM : "1:N 拆解"
    PARAM_NAME ||--o{ PARAM_VALUE : "1:N 取值"

    LIMIT_MATRIX ||--o{ LIMIT_TABLE : "1:N 派生"
    LIMIT_TABLE ||--o{ LIMIT_DIM : "1:N 维度"
    LIMIT_TABLE ||--o{ LIMIT_ROW : "1:N 明细"

    STANDARD {
        text id PK "标准标识 gb3103-3"
        text code "标准号 GB/T 3103.3-2000"
        text title "标准名称"
        text classes_json "覆盖的产品小类"
        text item_json "检项"
        text param_json "参数"
        text limits_json "规则限值"
        integer custom "1=上传分析发布"
    }

    STANDARD_CLASS {
        text id PK "层标识 sc-std-class"
        text std_id FK "所属标准"
        text class_id FK "所属产品小类"
        text name "层名称"
        text param_json "本层参数"
        text item_json "本层检项"
        text limits_json "本层限值"
    }

    DOCUMENT {
        text id PK "sha256 内容寻址"
        text job_id "来源作业"
        text filename "原始文件名"
        integer size "字节数"
        text storage "db 或 file"
        blob content "PDF 原文"
    }

    STANDARD_DOCUMENT {
        text std_id PK,FK "标准"
        text doc_id PK,FK "原件"
        real created_at "挂载时间"
    }

    PRODUCT_CLASS {
        text id PK "小类标识 cls-bolt"
        text code "分类代码 01.02"
        text name "螺栓"
        text parent "紧固件产品"
        integer sort "排序"
    }

    PARAM_NAME {
        text id PK "参数标识 pn-thread"
        text code "参数代码 thread"
        text name "螺纹规格"
        text type "enum 或 number"
        text is_multi_dim "是否多维"
        integer dim_count "维度数"
        text coord1_sub_id "坐标1 二级参数"
        text coord2_sub_id "坐标2 二级参数"
        integer is_primary "是否主参数"
    }

    SUB_PARAM {
        text id PK "二级参数标识"
        text class_id FK "所属小类"
        text param_id FK "所属主参数"
        integer seq "坐标序号"
        text code "代码 D P"
        text name "公称直径 螺距"
    }

    CLASS_PARAM {
        text class_id PK,FK "小类"
        text param_id PK,FK "参数"
        integer sort "排序"
        integer required "是否必填"
    }

    PARAM_VALUE {
        integer id PK "自增"
        text param_id FK "所属参数"
        integer seq "顺序号 可手工调整"
        text sym "符号"
        text val "定值"
        text coord1_val "坐标1 取值"
        text coord2_val "坐标2 取值"
        text coord3_val "坐标3 取值"
        text coord4_val "坐标4 取值"
    }

    LIMIT_MATRIX {
        integer id PK "自增"
        text std_id FK "所属标准"
        text local_id "矩阵编号 M-PROP-1"
        text title "矩阵标题"
        text matrix_json "多维结构定义"
    }

    LIMIT_TABLE {
        integer id PK "自增"
        text std_id FK "所属标准"
        text local_id "表号 T-D1"
        text name "表名"
        text unit "单位"
        text sc_id "所属层"
        text matrix_local_id "来源母矩阵"
        text item_code "绑定检项"
    }

    LIMIT_DIM {
        integer id PK "自增"
        integer table_id FK "所属表"
        integer seq "维度顺序"
        text code "参数代码 d_nom"
        text kind "enum 或 range"
        text values_json "取值集合"
    }

    LIMIT_ROW {
        integer id PK "自增"
        integer table_id FK "所属表"
        text key_json "维度命中键"
        real nominal "标称基准"
        real lower "下限"
        real upper "上限"
        text lower_expr "下限表达式"
        text upper_expr "上限表达式"
        integer na "1=不要求"
    }

    TABLE_SPLIT_MODE {
        text id PK "模式标识"
        text code UK "模式编码"
        text name "模式名称"
        text complexity "复杂度"
        text config_json "拆分规则配置"
    }
"""


def build_html(title: str, body: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>{title}</title>
<script src="mermaid.min.js"></script>
<style>{THEME}</style>
</head>
<body>
<pre class="mermaid">{_html.escape(body)}</pre>
<script>
{INIT}
mermaid.run({{ querySelector: '.mermaid' }}).then(() => {{
  document.body.setAttribute('data-done', '1');
}}).catch(e => {{
  document.body.setAttribute('data-error', String(e));
}});
</script>
</body>
</html>"""


def render(name: str, title: str, body: str) -> Path:
    WORK.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(MERMAID_SRC, WORK / "mermaid.min.js")
    html = WORK / f"{name}.html"
    html.write_text(build_html(title, body), encoding="utf-8")

    w, h = CANVAS[name]
    png = OUT / ("db-logical-view.png" if name == "arch" else "db-er.png")
    profile = WORK / f"chrome-{name}"
    profile.mkdir(exist_ok=True)

    subprocess.run(
        [CHROME, "--headless=new", "--no-sandbox", "--disable-gpu",
         "--disable-crash-reporter", "--disable-breakpad", "--hide-scrollbars",
         "--no-first-run", "--no-default-browser-check",
         "--force-device-scale-factor=2",
         f"--user-data-dir={profile}", f"--window-size={w},{h}",
         "--virtual-time-budget=12000", f"--screenshot={png}", html.as_uri()],
        check=True, capture_output=True, timeout=180)

    trim(png)
    print(f"  {png.name}: {png.stat().st_size / 1024:.0f} KB")
    return png


def trim(path: Path) -> None:
    """裁掉四周白边（Chrome 视口通常比内容大）。"""
    im = Image.open(path).convert("RGB")
    bg = Image.new("RGB", im.size, (255, 255, 255))
    diff = ImageChops.difference(im, bg)
    box = diff.getbbox()
    if not box:
        return
    pad = 24
    box = (max(0, box[0] - pad), max(0, box[1] - pad),
           min(im.width, box[2] + pad), min(im.height, box[3] + pad))
    im.crop(box).save(path, optimize=True)


def main() -> int:
    print("渲染数据库逻辑视图…")
    render("arch", "数据库逻辑架构分层图", ARCH)
    print("渲染 ER 图…")
    render("er", "数据库实体关系图", ER)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
