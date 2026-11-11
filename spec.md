# 规格说明书

> 版本：v0.4（2026-11-11）
> 范围：本仓库当前实现的行为规格。描述"系统怎么工作"，不描述"将来要做什么"（后者见文末）。

---

## 1. 目标与边界

**目标**：把产品标准（PDF）里的"可检项目 + 限值"变成可计算、可判定、可导出的检验卡；
并把参数、参数值、限值这些资产按**产品小类**沉淀，跨标准复用。

**边界**：
- 只处理**公差 / 限值类**内容。材料、机械性能、表面缺陷等由产品标准另行规定，不在解析范围。
- 限值表由**人确认**后入库；系统不承诺从原文自动得出可直接判定的数据。
- 无鉴权，面向本机 / 内网。

---

## 2. 角色与两条主线

| 角色 | 主线 | 入口 |
|---|---|---|
| 标准分析员 | 上传 PDF → 四步确认 → 建表 → 发布 | `#/analyze` |
| 检验员 | 选标准与小类 → 填规格 → 出卡 → 录实测 → 判定 | `#/card` |
| 参数维护 | 产品小类 → 参数名称 → 参数取值 | `#/catalog` |

```
PDF ──OCR──► 文本 ──条款切分──► 候选检项 ──①确认──┐
                     └──表格识别──► 网格 ──②确认──► 参数 ──③限值──► ④关联 ──► 发布为标准
                                                                              ↓
                                        选标准/小类 → 填规格 → 查表算限值 → 录实测 → 判定 → 导出
```

---

## 3. 领域模型

| 概念 | 说明 |
|---|---|
| **标准 standard** | 标准号 + 名称 + 覆盖的产品小类 + 若干**层** |
| **层 standard_class** | 标准 × 产品小类。**一行只挂一个小类**，行下有自己的参数、检项、限值、限值表 |
| **参数 param** | 检验前要填的规格量。`*_nom` 为公称值，是**唯一允许用于查表**的量 |
| **检项 item** | 一个检查项目，绑定一张限值表，有 `measured_key`（`*_act`，实测值） |
| **限值表 limit_table** | 多维查询表：维度 → 展开行 → 限值。属于**某一层**（`sc_id`） |
| **维度 dim** | 表的一个自变量，取值为枚举（`A,C`）或区间（`(0,4]`） |
| **限值行 limit_row** | 维度取值组合 + 下限/上限（数值或表达式），可标"不要求" |
| **符号 symbol** | 公差带 / IT 值的展开数据（如 H13 → 0/+0.27） |
| **实测 measured** | 检验员录入的实测值，只用于判定，禁止参与查表 |
| **参数库** | `product_class`（小类）→ `param_name`（参数名称，全局）→ `param_value`（取值） |

### 3.1 命名约定（强约束）

| 后缀 | 含义 | 用途 |
|---|---|---|
| `*_nom` | 公称尺寸 | 查表分档、计算极限尺寸 |
| `*_act` | 实际尺寸 | 仅用于与极限比较 |

违反后果：用实测值查表会在档位边界上静默错档（18.01 落到 `(18,30]`，H13 由 0.27 变 0.33）。

### 3.2 分层规则

- 一份标准可覆盖多个小类；`standard.classes` 存小类 id 列表。
- 发布时按 `param.class_id` / `item.class_id` 分层，每个小类一层；`classes` 去重。
- 约束：`UNIQUE(std_id, IFNULL(class_id,''))` —— 同一标准同一小类只能一层。
- `class_id` 外键指向 `product_class`，删除小类时置空（层不级联删除）。
- 不传 `sc` 时接口默认用**第一层**。

---

## 4. 数据模型

SQLite，文件 `data/app.db`。完整字段说明与逻辑视图见 [docs/schema.md](docs/schema.md)。

| 表 | 作用 |
|---|---|
| `standard` | 标准本体（code/title/category/scope/note/classes_json/source_json） |
| `standard_class` | 标准 × 小类这一层：param_json / item_json / limits_json |
| `limit_table` | 限值表头（std_id + local_id + sc_id + value_form + nominal_param） |
| `limit_dim` | 维度（code / kind / values_json） |
| `limit_row` | 限值行（key_json / lower / upper / expr / na / note） |
| `document` | 原件（sha256 主键，≤20MB 进库，超出只存路径） |
| `standard_document` | 标准 ↔ 原件（多对多） |
| `product_class` | 产品小类 |
| `param_name` | 参数名称表（全局，code 唯一） |
| `param_value` | 参数值表（挂在参数名称下，seq/sym/val） |
| `class_param` | 小类 ↔ 参数（多对多） |

关键 DDL 片段：

```sql
CREATE TABLE standard_class (
    id          TEXT PRIMARY KEY,
    std_id      TEXT NOT NULL REFERENCES standard(id) ON DELETE CASCADE,
    class_id    TEXT REFERENCES product_class(id) ON DELETE SET NULL,
    name        TEXT, sort INTEGER DEFAULT 0,
    param_json  TEXT DEFAULT '[]', item_json TEXT DEFAULT '[]',
    limits_json TEXT DEFAULT '{}'
);
CREATE UNIQUE INDEX ux_sc_std_class ON standard_class(std_id, IFNULL(class_id, ''));

CREATE TABLE limit_table (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    std_id TEXT NOT NULL REFERENCES standard(id) ON DELETE CASCADE,
    local_id TEXT NOT NULL, name TEXT, unit TEXT DEFAULT 'mm',
    value_form TEXT DEFAULT 'absolute', nominal_param TEXT,
    item_code TEXT, sort INTEGER DEFAULT 0, sc_id TEXT,
    UNIQUE (std_id, local_id)
);
```

`param_json` 元素：`{code, name, type: enum|number, unit, required, options[], values_list[{sym,val}], default, min, max, help, class_id}`

`item_json` 元素：`{id, name, symbol, clause, page, table, kind, measured_key, nominal_param, requires[], method, position, gauge, points, measured_hint, class_id}`

---

## 5. 求值语义

### 5.1 限值来源

| `value_form` | 含义 |
|---|---|
| `absolute` | 限值即绝对值 |
| `deviation` | 限值是偏差，叠加 `nominal_param` 所指公称值 |

### 5.2 行的限值

优先级：`lower_expr/upper_expr`（表达式）> `lower/upper`（数值）> `na=1`（不要求）。

### 5.3 三种状态

| 状态 | 含义 |
|---|---|
| `OK` | 命中一行，给出上下限 |
| `NOT_REQUIRED` | `na=1`，标准明确不要求 |
| `UNSPECIFIED` | 没命中任何行 / 表里没写 |
| `MISS` | 缺参数，无法求值 |

`NOT_REQUIRED ≠ UNSPECIFIED ≠ MISS`，报表口径依赖这个区分。

### 5.4 条款回溯

每个检项带 `page`。`/api/meta`、`/api/resolve` 返回它，界面把条款号渲染成
`/api/standards/{id}/source.pdf#page=N`，直接打开 PDF 对应页；没有原件时退化为纯文本。

页码回填：`POST /api/standards/{id}/backfill-pages` 重新 OCR 原件，优先取"行首即条款号"的标题行，
避开前言里的引用；挂载原件时自动跑一次。

### 5.5 区间约定

区间一律**左开右闭**：`[4,20]` 表示 `(4,20]`，边界值归下一档。

---

## 6. 接口

基址 `http://127.0.0.1:8022`，全部 JSON（上传与导出除外）。

### 6.0 前端路由

| 路由 | 页面 |
|---|---|
| `#/standards[/<std>]` | 全部标准（默认页） |
| `#/card/<std>[?sc=<层>]` | 检验卡（`?demo=1` 预填示例） |
| `#/tables/<std>[?sc=<层>]` | 限值表 |
| `#/analyze[/<job>[/<1-4>]]` | 上传分析四步向导 |
| `#/catalog[/<小类>]` | 参数库 |

支持的内窥参数：`?filtered=1`（展开被过滤候选）、`?why=<序号>`、`?rules=1`、
`?src=<表序号>&build=1`、`?newtable=<参数代码>`、`?vals=<参数代码>`、`?catpick=1`。

### 6.1 标准与解析

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/standards` | 标准列表（含 has_source / classes） |
| GET | `/api/meta?std=&sc=` | 参数、检项、层信息、封面数据 |
| POST | `/api/resolve` | `{std, sc?, params}` → 逐项限值 |
| POST | `/api/judge` | `{std, sc?, params, measured}` → 判定 |
| GET | `/api/card.xlsx?std=&sc=&<参数>` | 导出检验卡 |
| POST | `/api/standards/publish` | 发布（含 classes / params / items / limits） |
| POST | `/api/standards/unpublish/{id}` | 下架（内置标准禁止） |
| GET | `/api/rules` | 全部识别规则（正则 / 词表 / 评分公式） |

### 6.2 限值表

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/standards/{id}/editor?sc=` | 编辑器数据（参数/检项/表） |
| PUT | `/api/standards/{id}/tables/{tid}` | 整表覆盖保存 |
| DELETE | `/api/standards/{id}/tables/{tid}` | 删表 |

### 6.3 原件

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/standards/{id}/source.pdf` | 下载原件（`#page=N` 可定位） |
| POST | `/api/standards/{id}/source` | 把某次上传挂到标准（可挂多个） |
| DELETE | `/api/standards/{id}/source` | 解除关联（原件保留） |
| GET | `/api/documents` | 已存档原件清单（含 std_ids） |
| GET | `/api/analyze/jobs/{id}/source.pdf` | 作业原件 |

### 6.4 分析作业

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/analyze/upload` | 上传 PDF；同 sha256 复用作业 |
| GET | `/api/analyze/jobs[/{id}]` | 作业列表 / 详情 |
| POST | `/api/analyze/jobs/{id}/step/{items\|params\|limits\|links\|tables}` | 分步保存 |
| POST | `/api/analyze/jobs/{id}/rerun` | 用存档原件重跑（清空确认与草稿绑定） |
| GET | `/api/analyze/jobs/{id}/text` | OCR 原文 |
| GET | `/api/analyze/jobs/{id}/tables` | 检测到的表格网格 |
| POST | `/api/analyze/jobs/{id}/tables` | 存限值表草稿 |
| DELETE | `/api/analyze/jobs/{id}/tables/{tid}` | 删草稿 |

### 6.5 参数库

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/catalog` | 小类 → 参数 → 取值 |
| GET | `/api/params` | 参数名称表（含用到它的小类） |
| POST | `/api/catalog/classes` | 建小类 |
| POST | `/api/catalog/params` | 建参数（带 class_id 时同时挂到小类） |
| POST | `/api/catalog/params/{id}/values` | 覆盖保存取值 |
| POST/DELETE | `/api/catalog/classes/{cid}/params/{pid}` | 挂载 / 解除 |
| DELETE | `/api/catalog/classes/{cid}` | 删小类 |

---

## 7. 检项识别（可解释）

规则集中在 `g1/service/analyze.py` 顶部，`GET /api/rules` 原样输出。

| 步骤 | 做法 |
|---|---|
| ① 切条款 | 行首 `数字(.)数字` 且后面紧跟汉字 |
| ② 取正文 | 跳过表格碎片行，剥掉标准号再判"有没有数值" |
| ③ 判类别 | 关键词 → 尺寸 / 形位 / 性能 / 表面 / 标记 / 其他 |
| ④ 打分 | `0.2 + 0.4*命中类别 + 0.2*有数值 + 0.2*层级≥2 + 0.1*提到表` |
| ⑤ 硬规则排除 | 性能等级写法 / 表格单元格 / 章节标题 / 过程性小节 / 标题无可测对象 |
| ⑥ 父子折叠 | 上级已是检项时，下级标为"方法步骤" |

每条候选带 `trace`（逐步判定过程）与 `reason`（被排除的原因），界面可查。

## 8. 参数识别

`PARAM_RULES` 是「正则 → 参数代码」表，正文任一页命中即建议，并记录命中页码与原文行。

## 9. 限值表识别（从原文建表）

| 步骤 | 做法 |
|---|---|
| ① 找表头 | 前 3 行里命中关键词最多且 ≥2 个表头词的行，支持跨行表头 |
| ② 列含义 | 含 上限/最大/max/公差 → 上限；含 下限/最小/min → 下限 |
| ③ 维度列 | 表头含 性能等级/螺纹规格/公称直径/厚度/螺距/材料 → 对应参数 |
| ④ 保守猜测 | 无表头线索时：数字列→上限，短文本取值≤8 的最多 2 列→维度 |
| ⑤ 表内分段 | 整列空白 / 表头混排（`max 直径d`）/ 维度表头重复 → 拆成多张表 |
| ⑥ 预览校验 | 逐行标问题：维度值可疑 / 缺下限 / 缺上限 / 下限大于上限 / 疑似噪声 |

## 10. 参数库语义

- 参数名称与取值是**全局**的；小类通过 `class_param` 引用，同一参数共用一份取值。
- 数值型参数无法枚举，用 `{sym:'/', val:'/'}` 占位，表示"有这个参数、值不固定"；
  导入标准时按 number 处理，不生成枚举可选值。
- 标准发布时**复制**当时的取值；库里后续改动不影响已发布标准（可复现）。

## 11. 已知限制

- 仅 PDF；OCR 依赖 macOS Vision。
- 表格列识别是启发式；列错位（一格塞多个数）需人工改。
- 条款号与性能等级同形（4.6 / 8.8）靠白名单排除，个别标准可能误判。
- 检项的 `class_id` 不在覆盖小类范围内时，归到第一层而非报错。
- 跨标准共享限值表未实现（表按 `std_id` 隔离）。
- 无鉴权。

## 12. 数据状态与重置

标准只有一个来源：`data/app.db`。代码里没有内置标准，空库启动即"没有任何标准"。

| 操作 | 命令 |
|---|---|
| 清空业务数据 | `tools/reset_db.py` |
| 连作业一起清 | `tools/reset_db.py --jobs` |
| 灌入样例标准 | `tools/load_gb3103.py` |

## 13. 测试矩阵

| 文件 | 项数 | 覆盖 |
|---|---|---|
| `g1/gb3103_3.py` | 28 | 引擎：8 张表、偏差叠加、不要求、区间边界 |
| `g1/service/test_parse.py` | 15 | 条款切分、标题清洗、类别 |
| `g1/service/test_limits.py` | 12 | 多维匹配、表达式、规则表 |
| `g1/service/test_generic.py` | 22 | 通用标准：参数校验、发布、解析 |
| `g1/service/test_api.py` | 50 | 接口：元数据、解析、判定、导出、表编辑、参数库 |
| `g1/service/test_analyze.py` | 64 | 全链路：上传 → OCR → 四步 → 发布 → 原件 → 分层 |

## 14. 未实现 / 待办

- 检项小类越界校验（越界应 422 而不是塞进第一层）
- 限值表跨标准共享
- 参数库 Excel 批量导入
- 表格列错位的自动纠正
