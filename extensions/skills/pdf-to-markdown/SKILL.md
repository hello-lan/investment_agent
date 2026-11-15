---
name: pdf-to-markdown
description: 将 PDF 文件转换为 Markdown 格式。默认使用 pdfplumber（快速、轻量）；当用户明确提出高质量/OCR 等要求时切换至 docling。触发词：PDF转Markdown、转换PDF、提取PDF内容、convert PDF to markdown、pdf to md 等。
---

# PDF 转 Markdown

将 PDF 文件转换为 Markdown 格式。内置两种转换引擎，根据用户需求自动选择。

## 双模式说明

| 模式 | 引擎 | 特点 | 适用场景 |
|------|------|------|----------|
| **快速模式**（默认） | pdfplumber | 快速、轻量，自动提取文本段落和表格 | 日常转换、文本提取、表格识别 |
| **高质量模式** | docling | 高质量、支持 OCR、保留文档结构 | 扫描版 PDF、图片 PDF、复杂排版、对转换质量有要求 |

## 模式选择规则

检测用户输入中的质量关键词来决定使用哪种模式：

| 用户说（关键词） | 触发模式 |
|--------|--------|
| 高质量, high quality, 效果好, better quality | 高质量模式 |
| 精确, 准确, accurate, precise | 高质量模式 |
| 质量, quality | 高质量模式 |
| OCR, docling | 高质量模式 |
| 扫描版, 图片PDF, scanned, image-based | 高质量模式 |
| （默认，无以上关键词） | 快速模式 |

## 依赖

脚本运行时会自动检测并安装缺失的依赖（`pdfplumber` / `docling`），无需手动操作。

注：docling 首次运行时会自动下载 OCR 模型文件（约 500MB+），需要网络连接且耗时较长。

## 调用模板

**优先 `run_python_script`**（cwd=项目根）。输入/输出路径一律相对项目根，**禁止 `cd`**。仅当专用工具不可用时再用 `run_command`。

**快速模式（默认）：**

```text
run_python_script(
  script_path="extensions/skills/pdf-to-markdown/scripts/pdf2markdown_fast.py",
  argv=[
    "data/reports/pdf/002415/002415_2025年年度报告_2025.pdf",
    "-o", "data/reports/md/002415/002415_2025年年度报告_2025.md"
  ],
  timeout_seconds=120
)
```

**高质量模式：**

```text
run_python_script(
  script_path="extensions/skills/pdf-to-markdown/scripts/pdf2markdown_quality.py",
  argv=[
    "data/reports/pdf/002415/002415_2025年年度报告_2025.pdf",
    "-o", "data/reports/md/002415/002415_2025年年度报告_2025.md"
  ],
  timeout_seconds=120
)
```

`run_command` 兜底：`python extensions/skills/pdf-to-markdown/scripts/pdf2markdown_fast.py <pdf> -o <md>`

若省略 `-o`，输出文件自动命名为 `<输入文件名>.md`（与 PDF 同目录；请确保输出仍在 `data/` 下）。

转换成功后直接进入下一步（分割/建索引），**不要再 `find` / 全量 `list_files` 探路**。

## 执行流程

1. 从用户输入提取 PDF 文件路径和输出路径（可选）
2. 检测用户输入中的质量关键词，选择对应脚本
3. 若未指定输出路径，默认写到 `data/reports/md/...`，文件名为 `{原文件名}.md`
4. 用 `run_python_script` 执行（**脚本自动创建输出目录，无需先 `mkdir`**）
5. 脚本输出包含行数和字符数，**无需额外行数校验**

## 输出格式

### 快速模式

- **页标记**：每页以 `## Page N` 开头，方便定位原文页码
- **表格**：自动识别并转换为 GitHub 风格的 markdown 表格（`| col | col |` 格式）
- **段落**：根据 PDF 文本坐标自动合并连续文字为段落
- **换行清理**：连续 3 个以上空行压缩为 2 个

### 高质量模式

- docling 原生 Markdown 导出，保留完整的文档结构和排版
- 支持 OCR 识别扫描件和图片中的文字

## 注意事项

- 扫描版 PDF（纯图片）使用快速模式无法提取文字，请使用高质量模式
- 复杂排版（多栏、混排）快速模式可能导致段落顺序不理想
- 快速模式下部分 PDF 的表格可能因边框线不完整而漏识别
- 快速模式转换大文件（200+ 页）可能需要 30-60 秒

## 配合其他 Skill 使用

本 skill 通常作为前置步骤，转换后的 markdown 可交给 `split-financial-report` / `build_annual_report_index` 进行章节切割与索引。
