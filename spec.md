# 规格说明书

> 版本：v0.5（2026-11-12）
> 范围：本仓库当前实现的行为规格。描述"系统怎么工作"，不描述"将来要做什么"（后者见文末）。

---

## 1. 目标与边界

**目标**：把产品标准（PDF）里的"可检项目 + 限值"变成可计算、可判定、可导出的检验卡；
并把参数、参数值、限值这些资产按**产品小类**沉淀，跨标准复用。

**边界**：
- 支持**几何尺寸公差**与**力学性能/复合大表**。
- 限值表由**人确认**后入库；系统提供启发式提取与主从向导，不承诺从原文自动得出完全免校对的可判定数据。
- 无鉴权，面向本机 / 内网。

---

## 2. 角色与主线

| 角色 | 主线 | 入口 |
|---|---|---|
| 标准分析员 | 上传 PDF → 四步确认 → 建表 → 发布 | `#/analyze` |
| 复合大表拆解员 | 录入复合母表 → 自动继承公共参数 → 确认专属参数 → 展开生成明细 → 切分编译 | `#/tables/<标准>` 弹窗 |
| 检验员 | 选标准与小类 → 填规格 → 出卡 → 录实测 → 判定 | `#/card` |
| 参数维护 | 产品小类 → 参数名称 → 参数取值 | `#/catalog` |

```
PDF ──OCR──► 文本 ──条款切分──► 候选检项 ──①确认──┐
                     └──表格识别──► 网格 ──②确认──► 参数 ──③限值──► ④关联 ──► 发布为标准
                                                      │                      ↓
                                                      └─► 录入复合大表 (USMP 拓扑三层向导)
                                                          选标准/小类 → 填规格 → 查表算限值 → 录实测 → 判定 → 导出
```

---

## 3. 领域模型

| 概念 | 说明 |
|---|---|
| **标准 standard** | 标准号 + 名称 + 覆盖的产品小类 + 若干**层** |
| **层 standard_class** | 标准 × 产品小类。**一行只挂一个小类**，行下有自己的参数、检项、限值、限值表 |
| **母表 limit_matrix** | 复合大表母表定义（如表3机械性能），包含公共参数池与按 No. 划分的主表列表 |
| **限值表 limit_table** | 多维查询表：维度 → 展开行 → 限值。属于**某一层**（`sc_id`），可追溯母表血缘 |
| **维度 dim** | 表的一个自变量，取值为枚举（`A,C`）或区间（`(0,4]`） |
| **专属增量维度 extra_dim** | 某检项内部细分所派生的独占自变量（如公称抗拉强度、试验温度） |
| **限值行 limit_row** | 维度取值组合 + 公称基准 + 下限/上限（数值或表达式），可标"不要求" |
| **实测 measured** | 检验员录入的实测值，只用于判定，禁止参与查表 |
| **参数库** | `product_class`（小类）→ `param_name`（参数名称，全局）→ `param_value`（取值） |

### 3.1 复合大表拓扑三层解构模型 (USMP)

国标复合大表（如 GB/T 3098.1 表3）采用三层拓扑模型解构：
1. **Layer 1：表头公共自变量池 (`common_dims`)**：整张母表全局自变量（如：`property_class`、`d_nom`），所有主表默认自动继承；
2. **Layer 2：按 No. 序号展开的独立限值主表 (`tables`)**：每一个 No.（如 No. 1 抗拉强度、No. 2 屈服强度、No. 5 保证应力）独立作为一张单指标限值主表实体；
3. **Layer 3：专属增量自变量树 (`extra_dims`)**：由人工在界面确认该 No. 是否需要额外参数（如为 No. 1 抗拉强度加入 `公称抗拉强度 rm_nom`）；
4. **指标总空间维度**：$\mathcal{D}_{\text{ind}} = \mathcal{D}_{\text{common}} \otimes \mathcal{D}_{\text{extra}}$。明细行采用完全正交复合 Key 寻址定位，支持大规格加严及标准公称基准值透传。

---

## 4. 数据模型

SQLite，文件 `data/app.db`。完整字段说明与逻辑视图见 [docs/schema.md](docs/schema.md)。

| 表 | 作用 |
|---|---|
| `standard` | 标准本体（code/title/category/scope/note/classes_json/source_json） |
| `standard_class` | 标准 × 小类这一层：param_json / item_json / limits_json |
| `limit_matrix` | 复合大表母表（std_id + local_id + title + matrix_json） |
| `limit_table` | 限值表头（std_id + local_id + sc_id + matrix_local_id + nominal_param） |
| `limit_dim` | 维度（code / kind / values_json） |
| `limit_row` | 限值行（key_json / nominal / lower / upper / expr / na / note） |
| `document` | 原件（sha256 主键，≤20MB 进库，超出只存路径） |
| `standard_document` | 标准 ↔ 原件（多对多） |
| `product_class` | 产品小类 |
| `param_name` | 参数名称表（全局，code 唯一） |
| `param_value` | 参数值表（挂在参数名称下，seq/sym/val） |
| `class_param` | 小类 ↔ 参数（多对多） |

关键 DDL 片段：

```sql
CREATE TABLE limit_matrix (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    std_id        TEXT NOT NULL REFERENCES standard(id) ON DELETE CASCADE,
    local_id      TEXT NOT NULL,
    title         TEXT NOT NULL,
    matrix_json   TEXT NOT NULL DEFAULT '{}',
    created_at    REAL,
    updated_at    REAL,
    UNIQUE (std_id, local_id)
);

CREATE TABLE limit_table (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    std_id        TEXT NOT NULL REFERENCES standard(id) ON DELETE CASCADE,
    local_id      TEXT NOT NULL,
    name          TEXT,
    unit          TEXT DEFAULT 'mm',
    value_form    TEXT DEFAULT 'absolute',
    nominal_param TEXT,
    item_code     TEXT,
    sort          INTEGER DEFAULT 0,
    sc_id         TEXT,
    matrix_local_id TEXT DEFAULT '',
    UNIQUE (std_id, local_id)
);

CREATE TABLE limit_row (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    table_id      INTEGER REFERENCES limit_table(id) ON DELETE CASCADE,
    key_json      TEXT,
    nominal       REAL,
    lower         REAL,
    upper         REAL,
    lower_expr    TEXT,
    upper_expr    TEXT,
    na            INTEGER DEFAULT 0,
    note          TEXT
);
```

---

## 5. 接口

基址 `http://127.0.0.1:8022`，全部 JSON（上传与导出除外）。

### 5.1 复合大表母表 (limit_matrix)

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/standards/{id}/matrices` | 获取标准下母表概要列表 |
| GET | `/api/standards/{id}/matrices/{mid}` | 获取母表完整矩阵与主从结构 |
| POST | `/api/standards/{id}/matrices` | 保存母表并自动编译切分为多维子表联动检项 |
| DELETE | `/api/standards/{id}/matrices/{mid}` | 级联删除母表及衍生所有子表 |

### 5.2 标准与解析

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/standards` | 标准列表（含 has_source / classes） |
| GET | `/api/meta?std=&sc=` | 参数、检项、层信息、封面数据 |
| POST | `/api/resolve` | `{std, sc?, params}` → 逐项限值与基准值 |
| POST | `/api/judge` | `{std, sc?, params, measured}` → 判定 |
| GET | `/api/card.xlsx?std=&sc=&<参数>` | 导出检验卡 |
| POST | `/api/standards/publish` | 发布（含 classes / params / items / limits） |
| POST | `/api/standards/unpublish/{id}` | 下架（内置标准禁止） |

### 5.3 限值表

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/standards/{id}/editor?sc=` | 编辑器数据（参数/检项/表） |
| PUT | `/api/standards/{id}/tables/{tid}` | 整表覆盖保存 |
| DELETE | `/api/standards/{id}/tables/{tid}` | 删表 |

### 5.4 原件与作业

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/standards/{id}/source.pdf` | 下载原件（`#page=N` 可定位） |
| POST | `/api/standards/{id}/source` | 把某次上传挂到标准 |
| GET | `/api/documents` | 已存档原件清单 |
| POST | `/api/analyze/upload` | 上传 PDF（sha256 去重） |
| GET | `/api/analyze/jobs[/{id}]` | 作业列表 / 详情 |

---

## 6. 数据清空与脚本管理

标准数据库文件为 `data/app.db`。系统提供了一键维护工具：

| 操作 | 命令 | 说明 |
|---|---|---|
| 一键清空业务数据 | `./clean_data.sh --restart` | 清空标准、限值表、母表、原件、作业缓存，保留参数库并重启 8022 |
| 预览清空范围 | `./clean_data.sh --dry-run` | 查看受影响数据量，不实际删除 |
| 灌入样例标准 | `.venv/bin/python g1/service/tools/load_gb3103.py` | 灌入 GB/T 3103.3 平垫圈标准样例 |

---

## 7. 测试矩阵

| 文件 | 项数 | 覆盖范围 |
|---|---|---|
| `g1/gb3103_3.py` | 28 | 引擎：8 张表、偏差叠加、不要求、区间边界 |
| `g1/service/test_parse.py` | 15 | 条款切分、标题清洗、类别 |
| `g1/service/test_limits.py` | 12 | 多维匹配、表达式、规则表 |
| `g1/service/test_matrix.py` | 36 | 复合大表母表保存、按 No 主从切分、三维寻址与加严判定 |
| `g1/service/test_generic.py` | 22 | 通用标准：参数校验、发布、解析 |
| `g1/service/test_api.py` | 56 | 接口：母表 CRUD、元数据、解析、判定、导出、表编辑、参数库 |
| `g1/service/test_analyze.py` | 69 | 全链路：上传 → OCR → 四步 → 发布 → 原件 → 分层 |
| **总计** | **238 项** | 全部自动化回归验证通过 |
