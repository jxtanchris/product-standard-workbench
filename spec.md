# 规格说明书 (Specification)

> 版本：v0.6（2026-11-13）  
> 范围：本仓库当前实现的行为规格与系统架构规范。系统严格面向机械紧固件行业标准，将非结构化 PDF 文档转化为具备计算、查表与自动判定能力的结构化规则资产。

---

## 1. 目标与系统边界

### 1.1 目标
- **标准数字化为可执行规则**：解析国家/国际标准（GB/T、ISO、ASTM、DIN 等），提炼出标准化检项、规格参数、限值表。
- **多维复合参数体系与智能派生**：支持紧固件高阶主参数（如 `螺纹规格`）与二级参数坐标（`公英制`、`公称直径`、`螺距`、`粗细牙`）的联动解构，实现“一次输入、全检项自动满足”。
- **工业复合大表拓扑解构**：提炼 USMP 矩阵解构协议，内置 5 种大表切分模式，将跨多指标、多工况的复合大表自动化解构为独立限值子表并与检项关联。
- **参数资产按产品小类沉淀**：建立“产品小类 ↔ 参数名称 ↔ 二级参数 ↔ 参数定值”四级资产沉淀体系，实现跨标准完全复用。

### 1.2 边界
- **支持范围**：几何尺寸公差、机械和物理性能要求、表面渗碳层深度、扭矩与载荷等。
- **人机协同确认机制**：AI 与启发式算法辅助提取，最终由标准分析员把关确认入库。
- **运行环境**：无鉴权设计，面向本机或企业内网服务。

---

## 2. 角色与主业务流

| 业务角色 | 核心主线 | 主要交互入口 |
|---|---|---|
| **标准分析员** | 上传标准 PDF → 四步确认（检项/参数/限值/关联）→ 校验发布 | `#/analyze` |
| **限值/大表拆解员** | 原表拆解工作台（5大模式切分）/ 录入复合母表 → 自动切分多维子表与检项绑定 | `#/tables/<标准>` |
| **检验员** | 选择标准与小类 → 填报复合规格 → 自动派生限值 → 录入实测值 → 自动判定导出 | `#/card` |
| **参数管理员** | 维护产品小类 ↔ 主参数表 ↔ 二级参数坐标表 ↔ 定值库 | `#/catalog` |

```
PDF ──OCR──► 文本 ──条款切分──► 候选检项 ──①确认──┐
                     └──表格识别──► 原表网格 ──②确认──► 参数 ──③限值──► ④关联 ──► 发布为标准
                                                      │                      ↓
                                                      └─► 原表拆解工作台 (5大工业切分模式)
                                                          选标准/小类 → 填规格 → 查表算限值 → 录实测 → 判定 → 导出
```

---

## 3. 领域模型与多维语义规范

### 3.1 核心领域概念

| 实体概念 | 业务与技术定义 |
|---|---|
| **标准 standard** | 标准编号 + 名称 + 适用的产品小类列表 + 若干小类分层（`Layer`） |
| **层 standard_class** | 标准 × 产品小类的交集实体。一行严格绑定一个小类，持有专属的参数、检项与限值表映射 |
| **多维主参数 primary param** | 紧固件的核心规格参数（如 `thread 螺纹规格`、`bm_thread 旋入机体端螺纹规格`），标记 `is_multi_dim='Y'` |
| **二级参数 sub_param** | 组成多维复合参数的各坐标分量（如 `GYZLX 公英制类型`, `D 公称直径`, `P 螺距`, `YLX 粗细牙类型`） |
| **母表 limit_matrix** | 复合大表母表实体，记录全局公共参数池（`common_dims`）与按 No. 划分的主表定义 |
| **限值表 limit_table** | 多维查询表实体：定义自变量维度（`limit_dim`）与限值记录行（`limit_row`） |
| **切分模式 table_split_mode** | 预置 5 种工业大表切分规则，指导母表自动切分编译为独立子表实体 |

### 3.2 多维复合参数解构与主导权机制 (Multi-Dim Authority)

为了彻底解决紧固件“规格选了 M8，公称直径残留旧值 2 导致限值表计算错误”的人为矛盾，系统制定以下计算语义：

1. **主参数绝对主导权**：
   - 当计算上下文（Context）中存在多维主参数（如 `thread = "M8×1.25粗牙"`）时，该参数享有**最高优先级**；
   - 引擎自动通过坐标映射或智能解析提取出二级参数（`D = 8.0`, `P = 1.25`, `GYZLX = "公制"`, `YLX = "粗牙"`）；
   - **强制覆写规则**：即使 Context 中已存在旧的单维参数（如 `d_nom = 2`），主参数解构出的新坐标将**强制覆写**旧值（更新为 `d_nom = 8.0`, `d = 8.0`），确保上下文中全量参数完全自洽。
2. **多维坐标自适应查表匹配**：
   - 下游限值表无论以多维主参数（`thread`）还是以解构后的二级单维参数（`d_nom`, `d`, `P`）作为维度，引擎均能自动精准命中；
   - 弱类型数值容差匹配（`_val_eq`）：自动打通字符型枚举维度（如表中存储的 `"8"`）与数值型（`8.0`）的等价比对，消除格式差异。

### 3.3 复合大表 5 大工业切分模式

| 模式编码 | 模式名称 | 核心规则与编译行为 |
|---|---|---|
| `single_indicator` | **模式 1: 单值单表** | 原表单一指标，直接转换为标准限值表，支持跨直径组展开。 |
| `multi_col_parallel` | **模式 2: 多指标按列拆分** | 复合大表按 No. 或表头指标列自动切分，每列独立生成子表实体，自动附加 Min/Max/Avg。 |
| `matrix_2d_cross` | **模式 3: 双向交叉大表** | 横向维度与纵向维度形成双向笛卡尔积，解构为标准多维行列。 |
| `composite_no_master` | **模式 4: 复合工况多维大表** | 跨等级、热处理状态等多重复合工况，抽离为独立维度构建正交表。 |
| `ignore_skip` | **模式 5: 自由稀疏/忽略表** | 纯文字性或试验程序说明表，标记为跳过，不参与检项绑定。 |

---

## 4. 数据架构与 DDL 规格

底层存储采用 SQLite（`data/app.db`），核心表关系与关键字段如下：

### 4.1 参数库与二级参数表
```sql
-- 参数名称定义表（全局）
CREATE TABLE param_name (
    id             TEXT PRIMARY KEY,             -- 如 QYCPMLCS00000000009
    code           TEXT NOT NULL UNIQUE,         -- 规范代码，如 thread
    name           TEXT NOT NULL,                -- 中文名称，如 螺纹规格
    unit           TEXT DEFAULT '',              -- 默认单位
    type           TEXT DEFAULT 'enum',          -- number | enum
    help           TEXT DEFAULT '',
    is_multi_dim   TEXT DEFAULT 'N',             -- 是否多维复合参数 (Y/N)
    dim_count      INTEGER DEFAULT 0,            -- 维度定义 (2, 3, 4)
    coord1_sub_id  TEXT DEFAULT '',              -- 坐标1关联二级参数ID
    coord2_sub_id  TEXT DEFAULT '',              -- 坐标2关联二级参数ID
    coord3_sub_id  TEXT DEFAULT '',              -- 坐标3关联二级参数ID
    coord4_sub_id  TEXT DEFAULT '',              -- 坐标4关联二级参数ID
    is_primary     INTEGER DEFAULT 0,            -- 是否主参数 (1/0)
    category       TEXT DEFAULT ''               -- 参数分类
);

-- 二级参数定义表
CREATE TABLE sub_param (
    id             TEXT PRIMARY KEY,             -- 如 EJCPMLCS00000000000
    class_id       TEXT NOT NULL,                -- 产品小类引用
    param_id       TEXT NOT NULL REFERENCES param_name(id) ON DELETE CASCADE,
    seq            INTEGER NOT NULL,             -- 坐标顺序 (1, 2, 3, 4)
    code           TEXT NOT NULL,                -- 二级参数代码，如 D
    name           TEXT NOT NULL,                -- 二级参数名称，如 公称直径
    help           TEXT DEFAULT ''
);

-- 参数定值表（挂载坐标值）
CREATE TABLE param_value (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    param_id       TEXT NOT NULL REFERENCES param_name(id) ON DELETE CASCADE,
    seq            INTEGER DEFAULT 0,
    sym            TEXT DEFAULT '',              -- 参数符号，如 M8×1.25Coarse
    val            TEXT NOT NULL,                -- 定值文本，如 M8×1.25粗牙
    coord1_val     TEXT DEFAULT '',              -- 坐标1值，如 公制
    coord2_val     TEXT DEFAULT '',              -- 坐标2值，如 8
    coord3_val     TEXT DEFAULT '',              -- 坐标3值，如 1.25
    coord4_val     TEXT DEFAULT ''               -- 坐标4值，如 粗牙
);
```

### 4.2 限值表与复合母表
```sql
-- 复合大表母表
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

-- 限值表实体
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

-- 限值表维度
CREATE TABLE limit_dim (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    table_id      INTEGER NOT NULL REFERENCES limit_table(id) ON DELETE CASCADE,
    seq           INTEGER DEFAULT 0,
    code          TEXT NOT NULL,                 -- 维度参数代码，如 d_nom
    kind          TEXT DEFAULT 'enum',          -- enum | size
    values_json   TEXT DEFAULT '[]'
);

-- 限值明细行
CREATE TABLE limit_row (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    table_id      INTEGER NOT NULL REFERENCES limit_table(id) ON DELETE CASCADE,
    key_json      TEXT,                          -- 维度命中字典，如 {"d_nom": "8"}
    nominal       REAL,                          -- 标准公称基准值
    lower         REAL,                          -- 绝对下限
    upper         REAL,                          -- 绝对上限
    lower_expr    TEXT,
    upper_expr    TEXT,
    na            INTEGER DEFAULT 0,             -- 不适用/不要求标记
    note          TEXT
);
```

---

## 5. 核心接口规范

服务基址：`http://127.0.0.1:8022`，通信格式：`application/json`。

### 5.1 解析与判定核心 API

| 方法 | 路径 | 请求体 / 参数 | 说明 |
|---|---|---|---|
| `POST` | `/api/resolve` | `{std: str, sc?: str, params: dict}` | **规格解析核心**：自动应用多维主导权解构坐标，匹配限值表并输出逐项上下限与公称基准值 |
| `POST` | `/api/judge` | `{std: str, sc?: str, params: dict, measured: dict}` | **实测判定核心**：在限值解析基础上录入测量值，输出各单项及整单合格性判定结论 |
| `GET` | `/api/meta` | `?std=&sc=` | 获取标准当前层元数据（规格参数清单、默认值、可检项目列表） |
| `GET` | `/api/card.xlsx`| `?std=&sc=&<规格参数键值对>` | 导出当前规格配置的标准化 Excel 检验卡文件 |

### 5.2 参数库与复合母表 API

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/catalog` | 查询产品小类、主参数（含多维标识）、二级参数列表与定值列表 |
| `GET` | `/api/standards/{id}/matrices` | 获取标准下复合母表概要列表 |
| `POST`| `/api/standards/{id}/matrices` | 保存复合母表并按 USMP 协议自动编译切分为多维子表 |
| `GET` | `/api/tables/split-modes` | 获取 5 大大表拆分模式及其配置模板 |
| `POST`| `/api/tables/split` | 原表拆解预览与编译切分执行 |

---

## 6. 测试矩阵与质量保障

全仓库测试矩阵覆盖自底向上的每一层关键逻辑：

| 测试模块 | 执行脚本 | 验证项数 | 核心断言与覆盖范围 |
|---|---|:---:|---|
| **基础引擎与平垫圈** | `g1/gb3103_3.py` | 28 | 验证 8 张限值表查表、公差偏差叠加、C级豁免、区间开闭边界判定 |
| **条款与结构切分** | `g1/service/test_parse.py` | 15 | 验证条款候选提取、章节标题过滤、性能等级同形号排除 |
| **规则表达式与限值** | `g1/service/test_limits.py` | 12 | 验证常量、动态公式、多维规则表达式及安全沙箱 |
| **母表切分与三维加严** | `g1/service/test_matrix.py` | 52 | **5大工业切分模式验证**、No.主从切分、三维寻址与大规格加严计算 |
| **通用标准发布模型** | `g1/service/test_generic.py` | 22 | 验证跨小类分层、自定义参数校验、上下文构建 |
| **端到端 API 接口** | `g1/service/test_api.py` | 56 | 验证母表 CRUD、元数据接口、多维 resolve 判定、检验卡导出 |
| **全链路分析验证** | `g1/service/test_analyze.py` | 69 | 验证 PDF 上传、Vision OCR、四步向导状态保存与发布 |
| **总计** | | **254 项** | **全量自动化测试持续通过 (100% Pass Rate)** |
