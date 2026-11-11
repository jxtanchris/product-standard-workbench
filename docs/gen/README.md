# 文档生成脚本

生成 `spec`/`readme` 之外的几份分析文档（Word/Excel），需要 Python 环境带
`python-docx` / `openpyxl`：

| 脚本 | 产物 |
|---|---|
| `build_docx.py` | GB/T 3103.3-2000 可检查项与检查方法分析.docx |
| `build_xlsx.py` | GB/T 3103.3-2000 检验项目清单.xlsx |
| `build_analysis.py` | 现有产品标准分析流程 分析与改进建议.docx |
| `build_g1_doc.py` | G1 限值类型体系设计.docx |

产物写到当前目录，已在 `.gitignore` 里排除（`*.docx` / `*.xlsx`）。
