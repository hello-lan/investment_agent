---
name: pdf-to-markdown
description: 使用 docling 的 DocumentConverter 将 PDF 文件转换为 Markdown 格式。当用户要求将 PDF 转为 Markdown、提取 PDF 内容或将 PDF 文档转为可编辑文本时，应使用此技能。触发词包括"PDF转Markdown"、"转换PDF"、"提取PDF内容"、"convert PDF to markdown"、"pdf to md"等。
---

# PDF 转 Markdown

将 PDF 文件转换为 Markdown 格式，基于 docling 的 DocumentConverter。

## 脚本位置

脚本位于本 SKILL.md 同级目录的 `scripts/pdf2markdown.py`。

## 触发规则

以下情况应使用本 skill：

| 用户说 | 触发？ |
|--------|--------|
| "把这个PDF转成Markdown" | ✅ |
| "提取这个PDF的内容" | ✅ |
| "convert this PDF to markdown" | ✅ |
| "帮我把财报PDF转成文本" | ✅ |
| "把 /path/to/file.pdf 转成 md" | ✅ |

## 参数提取规则

从用户输入中提取参数：

| 用户表述 | 参数 | 示例值 |
|----------|------|--------|
| "这个PDF" / 文件路径 | `--input` | `/path/to/file.pdf` |
| "保存到xxx" / 输出路径 | `--output` | `/path/to/output.md` |
| 未指定输出路径 | `--output` | 默认与 PDF 同目录同名 `.md` |

## CLI 调用模板

所有命令的 working directory 为 `SKILL.md` 所在目录，脚本在 `scripts/` 子目录下：

```bash
# 指定输入输出路径
cd scripts && python pdf2markdown.py --input /path/to/file.pdf --output /path/to/output.md

# 只指定输入（输出默认与 PDF 同目录同名 .md）
cd scripts && python pdf2markdown.py --input /path/to/file.pdf
```

## 执行流程

1. 从用户输入提取：PDF 文件路径、输出路径（可选）
2. 如果用户未指定输出路径，默认与 PDF 同目录，文件名为 `{原文件名}.md`
3. 构造 CLI 命令并执行（working directory = SKILL.md 所在目录）
4. 将转换进度和结果汇报给用户
5. 如果转换失败，提示用户检查文件是否存在或网络（首次运行需下载模型）

## 依赖

- `docling` 库：首次运行时会自动下载 OCR 模型文件，需要网络连接
