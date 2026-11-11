# 规格说明书

> 版本：v0.3（2026-11-11）
> 范围：本仓库当前实现的行为规格。描述"系统怎么工作"，不描述"将来要做什么"（后者见文末）。

---

## 1. 目标与边界

**目标**：把产品标准（PDF）里的"可检项目 + 限值"变成可计算、可判定、可导出的检验卡。

**边界**：
- 只处理**公差/限值类**内容。材料、机械性能、表面缺陷等由产品标准另行规定，不在解析范围。
- 限值表由**人确认**后入库；系统不承诺从原文自动得出可直接判定的数据。
- 不支持跨标准共享限值表（见 §11）。

---

## 2. 角色与两条主线

| 角色 | 主线 | 入口 |
|---|---|---|
| 标准分析员 | 上传 PDF → 识别 → 确认 → 建表 → 发布 | `#/analyze`、`#/tables` |
| 检验员 | 选标准 → 填规格 → 出卡 → 录实测 → 判定 | `#/card` |

两条主线的交点是**标准（standard）**：分析员的产物是一个标准，检验员的输入也是一个标准。

```
PDF ──OCR──► 文本 ──条款切分──► 候选检项 ──人工确认──┐
                     └──表格识别──► 网格 ──列映射──► 限值表草稿 ──┘
                                                              ↓
                                                        发布为标准
                                                              ↓
                        选标准 → 填规格 → 查表算限值 → 录实测 → 判定 → 导出
```

---

## 3. 领域模型

| 概念 | 说明 |
|---|---|
| **标准 standard** | 一个标准号 + 名称 + 一组规格参数 + 一组检项 + 若干限值表 |
| **参数 param** | 检验前要填的规格量。`*_nom` 为公称值，是**唯一允许用于查表**的量 |
| **检项 item** | 一个检查项目，绑定一张限值表，有 `measured_key`（`*_act`，实测值） |
| **限值表 limit_table** | 多维查询表：维度 → 展开行 → 限值。属于**某一个标准** |
| **维度 dim** | 表的一个自变量，取值为枚举（`A,C`）或区间（`(0,4]`） |
| **限值行 limit_row** | 维度取值组合 + 下限/上限（数值或表达式），可标"不要求" |
| **符号 symbol** | 公差带代号 / IT 值的展开数据（如 H13 → 0/+0.27） |
| **实测 measured** | 检验员录入的实测值，只用于判定，禁止参与查表 |

### 3.1 命名约定（强约束）

| 后缀 | 含义 | 用途 |
|---|---|---|
| `*_nom` | 公称尺寸 | 查表分档、计算极限尺寸 |
| `*_act` | 实际尺寸 | 仅用于与极限比较 |

违反后果：用实测值查表会在档位边界上静默错档（18.01 落到 `(18,30]`，H13 由 0.27 变 0.33）。

---

## 4. 数据模型

SQLite，文件 `data/app.db`。完整字段说明与逻辑视图见 [docs/schema.md](docs/schema.md)。

```sql
CREATE TABLE standard (
    id TEXT PRIMARY KEY, code TEXT, title TEXT, category TEXT, scope TEXT, note TEXT,
    custom INTEGER, source_json TEXT, param_json TEXT, item_json TEXT,
    limits_json TEXT, created_at REAL);

CREATE TABLE limit_table (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    std_id        TEXT NOT NULL REFERENCES standard(id) ON DELETE CASCADE,
    local_id      TEXT NOT NULL,        -- 标准内的表 id，如 T-D1
    name TEXT, unit TEXT, value_form TEXT, nominal_param TEXT, item_code TEXT, sort INTEGER,
    UNIQUE (std_id, local_id));

CREATE TABLE limit_dim (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    table_id INTEGER REFERENCES limit_table(id) ON DELETE CASCADE,
    seq INTEGER, code TEXT, kind TEXT,   -- kind: enum | range
    values_json TEXT);                   -- ["A","C"] 或 [[0,4],[4,20]]

CREATE TABLE limit_row (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    table_id INTEGER REFERENCES limit_table(id) ON DELETE CASCADE,
    key_json TEXT,                       -- {"grade":"A","h_nom":[0,4]}
    lower REAL, upper REAL,              -- 数值型
    lower_expr TEXT, upper_expr TEXT,    -- 表达式型，优先于数值
    na INTEGER, note TEXT);
```

**要点**

1. 表**属于标准**，`local_id` 只在标准内唯一 → 两个标准可各有 `T-D1`，互不影响。
2. `value_form`：
   - `absolute` —— 值即绝对量（Δh ≤0.2）
   - `deviation` —— 值是偏差，判定时叠加 `nominal_param` 的公称值（通孔 0/+0.27）
3. `na=1` 表示"该情形标准不要求"（C 级豁免），与"没填"严格区分。
4. 旧库（`limit_table.id` 为全局 TEXT 主键）在 `connect()` 时自动迁移。

---

## 5. 限值求值语义

### 5.1 三种录入形态

| 形态 | 存法 | 例子 |
|---|---|---|
| 常量 | `lower/upper` 数值 | 0.025 / 0.4 |
| 表达式 | `lower_expr/upper_expr` | `0.25*h_nom`、`d_nom+0.27` |
| 规则 | `standard.limits_json` 的 `rules[]` | `h_nom<=4 and d_nom<=18 => d_nom ~ d_nom+0.27` |

表达式与规则使用**白名单 AST 求值**，不使用 `eval`：仅允许四则运算、括号、`min/max/round/abs`、
比较（`<= >= < > == !=`）、布尔（`and or not`）；变量必须在上下文里存在。

### 5.2 求值六步

```
1 维度求键   enum 直接取值；range 找落在 (from,to] 的档
2 命中行     未命中 → MISS
3 行级适用   na=1 → NOT_REQUIRED
4 值槽求值   CONST / FORMULA / SYMBOL
5 形态换算   deviation → 叠加 nominal_param
6 产出       (status, lower, upper, unit, trace)
```

### 5.3 四种结果状态

| 状态 | 含义 | 判定结论 |
|---|---|---|
| `OK` | 有值 | 合格 / 不合格 |
| `NOT_REQUIRED` | 标准明确不要求 | 不适用 |
| `UNSPECIFIED` | 标准尚未规定 | 仅记录 |
| `MISS` | 上下文不足 / 超范围 | 无法判定 |

### 5.4 条款回溯

每个检项带 `page`（在原件中的页码）。`/api/meta`、`/api/resolve` 都会返回它，
界面把条款号渲染成 `/api/standards/{id}/source.pdf#page=N` 的链接，直接打开 PDF 对应页。
没有存档原件时（`has_source=false`）退化为纯文本。

### 5.5 区间约定

所有分档一律**左开右闭** `(from, to]`，第一档 `from=0` 时含 0。
`h=2.5` 唯一归入 `(1, 2.5]`，不会同时命中两档。

---

## 6. 接口规格

基址 `http://127.0.0.1:8022`。全部 JSON（上传与导出除外）。

### 6.0 前端路由

| 路由 | 页面 | 说明 |
|---|---|---|
| `#/standards` | 全部标准 | 默认页；左列表 + 右详情（检验卡 / 限值表两个入口） |
| `#/standards/<std>` | 全部标准 | 选中某个标准 |
| `#/card/<std>` | 检验卡 | 支持 `?demo=1` 预填示例实测值 |
| `#/tables/<std>` | 限值表 | 左选表、右明细 |
| `#/tables/<std>/<tid>` | 限值表 | 直接定位到某张表 |
| `#/analyze` | 上传分析 | 右上角「上传标准做分析」进入 |
| `#/analyze/<job>` | 上传分析 | 打开某次作业 |

无 hash 时回到 `#/standards`；`?std=` 查询参数作为兼容入口保留。

### 6.1 标准与检项

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/standards` | 标准列表 |
| GET | `/api/meta?std=` | 参数 schema + 检项清单 |
| POST | `/api/resolve` | `{std, params}` → 逐项限值（含 trace） |
| POST | `/api/judge` | `{std, params, measured}` → 逐项结论 |
| GET | `/api/card.xlsx?std=&<参数>` | 导出检验卡 |
| GET | `/api/standards/{id}/source.pdf` | 下载标准原件（`#page=N` 可在浏览器定位到页） |
| POST | `/api/standards/{id}/source` | 把某次上传的原件挂到该标准 |
| GET | `/api/documents` | 已存档原件清单 |
| GET | `/api/db/stats` | 库统计 |

`/api/resolve` 响应片段：

```json
{"rows":[{"id":"d1","symbol":"d₁","status":"OK","status_text":"可判定",
  "limit_text":"13.000 ～ 13.270 mm","lower":13.0,"upper":13.27,
  "measured_key":"d1_act","nominal_param":"d1_nom","nominal_value":13.0,
  "trace":["命中维度 grade=A, h_nom=(0, 4)","代号 H13@13.0 -> 0.0",
           "代号 H13@13.0 -> 0.27","叠加公称值 13.0"]}]}
```

### 6.2 限值表

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/standards/{id}/tables` | 限值表（只读视图） |
| GET | `/api/standards/{id}/editor` | 参数 + 检项 + 表（含维度取值与行） |
| PUT | `/api/standards/{id}/tables/{tid}` | 整表覆盖保存（含 `item_code` 绑检项） |
| DELETE | `/api/standards/{id}/tables/{tid}` | 删表 |

保存校验：维度必须是该标准的参数、`kind ∈ {enum, range}`、至少一行。

### 6.3 发布

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/standards/publish` | 把参数 + 检项 + 限值存成标准 |
| POST | `/api/standards/unpublish/{id}` | 下架自定义标准（同时删表） |

### 6.4 标准分析

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/analyze/upload` | 上传 PDF（multipart），返回 `job_id`；同 sha256 直接复用 |
| POST | `/api/analyze/text` | 直接分析粘贴文本 |
| GET | `/api/analyze/jobs` | 作业列表 |
| GET | `/api/analyze/jobs/{id}` | 状态 + 候选检项 + 参数建议 |
| PUT | `/api/analyze/jobs/{id}/items` | 保存人工确认结果 |
| GET | `/api/analyze/jobs/{id}/text` | OCR 原文 |
| GET | `/api/analyze/jobs/{id}/tables` | 检测到的表格网格 |
| GET | `/api/analyze/jobs/{id}/card.xlsx` | 导出草稿检验卡 |
| DELETE | `/api/analyze/jobs/{id}` | 删除作业 |

作业状态机：`queued → ocr → analyzing → done | error`，前端 900ms 轮询。

### 6.5 错误约定

- 参数校验失败：`422 {"detail":{"errors":["缺少必填参数 公称厚度 h（h_nom）"]}}`
- 标准不存在：`404 {"detail":"未注册的标准：xxx"}`

---

## 7. 解析引擎

`g1/limit_engine.py`

| 组件 | 职责 |
|---|---|
| `SymbolSet` | 代号 → 尺寸段 → 偏差/公差值 |
| `LimitTable` | 多维表：维度匹配 + 值槽求值 + 偏差叠加 |
| `RuleTable` | 条件行表：`条件 => 下限 ~ 上限` |
| `_Evaluator` / `eval_cond` | 白名单 AST 求值（表达式 / 条件） |
| `Resolved` | `(status, lower, upper, unit, trace)` |

**trace** 记录每次求值的中间步骤（命中哪一行、查了哪个代号、是否叠加公称值），
界面上可展开查看，用于审计。

---

## 8. 从原文建表

```
PDF ──ocrkit──► 每页 words[{t,x,y,w,h}] ──tablefind──► 网格 ──列映射──► 草稿表
```

1. **OCR**：macOS Vision，300 dpi，输出词与外接框。
2. **网格还原**：按 y 聚行（容差 = 中位行高 × 0.55）→ 在行内投影 x → 空白 ≥26px 处切列 → 词落入格。
3. **列映射**：每列指定「忽略 / 维度(参数) / 下限 / 上限」；系统给初始猜测（数字列→上限，最左两个取值少的文本列→维度）。
4. **值解释**：`自动 / ±x / +x / −x / 单值当上限 / 单值当下限 / a~b`。
   自动模式识别 `±`、`士`（OCR 常混）、`+`、`−`、`~`；`H13`、`IT12` 等代号不参与数值解析。
5. **生成草稿**：维度列去重取值 → 维度；每行按列映射算 lower/upper；原文串写入 `note`。
6. **人工核对**后在编辑器修正、保存。

---

## 9. 判定

```
对每个检项：
  NOT_REQUIRED → 不适用（不计不合格，不计缺项）
  UNSPECIFIED  → 仅记录
  MISS         → 无法判定
  有实测值     → lower ≤ v ≤ upper ? 合格 : 不合格
  无实测值     → 未检测
整体：任一不合格 → 不合格；否则有未检测 → 待判定；否则合格
```

边界比较使用 `1e-9` 容差，避免浮点误差把合规件判成不合格。

---

## 10. 边界与已知问题（已处理）

| 场景 | 行为 |
|---|---|
| 区间边界（h=2.5） | 归 `(1,2.5]`，不重复命中 |
| 零值下限 | 保存与解析均按 0 处理（不是 null） |
| 超出表覆盖（d₂=300） | `MISS`，不返回 0 |
| 代号类型混用 | 极限偏差型 / 公差值型分开，查错抛异常 |
| 同名表跨标准 | 已隔离（`UNIQUE(std_id, local_id)`） |
| 数值型常量限值重启 | 重载时还原为零维表（已修） |

---

## 11. 未实现

| 项 | 说明 |
|---|---|
| 跨标准共享限值表 | 当前表属于单个标准；共享需要"库 + 引用"模型 |
| 符号表入库 | IT 值/公差带仍写在 `tools/load_gb3103.py` |
| LLM 增强抽取 | 当前为规则抽取，未接大模型 |
| 非 macOS OCR | 依赖 Vision；Linux 需替换 `extract_ocr` 实现 |
| 用户与权限 | 无登录、无多租户 |

---

## 12. 数据状态与重置

标准只有一个来源：`data/app.db`。代码里**没有**内置标准，空库启动即"没有任何标准"。

| 操作 | 命令 | 结果 |
|---|---|---|
| 清空业务数据 | `tools/reset_db.py` | 标准/表/行清零，作业保留 |
| 连作业一起清 | `tools/reset_db.py --jobs` | 再加删 `data/jobs`、`data/uploads` |
| 灌入样例标准 | `tools/load_gb3103.py` | GB/T 3103.3：8 表 143 行 |

删除 `data/app.db` 本身也可，但 `run.sh` 在库文件缺失时会自动执行 `load_gb3103.py`。

## 13. 测试矩阵

| 层 | 文件 | 项数 | 覆盖 |
|---|---|---|---|
| 引擎 | `g1/gb3103_3.py` | 28 | 8 张表求值、边界、基准参数 |
| 解析 | `test_parse.py` | 15 | `±/士/+/−/~/代号` 单元格解析 |
| 限值形态 | `test_limits.py` | 12 | 常量/公式/规则/不要求/未命中/表达式安全 |
| 通用性 | `test_generic.py` | 22 | 7 参数标准不改代码 |
| 接口 | `test_api.py` | 42 | HTTP、编辑往返、标准隔离 |
| 全链路 | `test_analyze.py` | 39 | 上传→OCR→识别→表格→发布→出卡 |
