---
name: build-annual-report-index
description: 为 A 股年报 Markdown 生成最多两级的 chapter 索引 JSON；优先跑脚本生成并校验，适合新年报接入、补建索引和低上下文章节导航。
---

# Build Annual Report Index

这个 skill 只负责一件事：
**给一份上市公司年报 Markdown 生成一个最多两级的 chapter 索引 JSON。**

它不负责：digest、公司分析结论、通读整份年报。

## 强制执行顺序（违反即失败）

1. **第一步必须** `run_command` 跑 `build_minimal_index.py`（见下方命令）
2. **第二步** 跑 `validate_sections_index.py` 校验
3. 校验通过 → 返回输出路径 + 简短摘要，**立即结束**
4. **仅当脚本失败或校验报错**，才允许按「失败回退」做最小修补；禁止一上来就 grep/read 扫全文

禁止事项（烧 token 的典型失败模式）：
- 禁止先 `Skill` 再手工探路；system 已有本 skill 快速参考时，**不要**再加载全文
- 禁止用 `grep`/`read_file`/`search_text` 反复扫描年报来「理解结构」替代脚本
- 禁止因上游 `task` 给了简化字段（如只有 `title`/`start_line`/`children`）就改写输出 schema 或重写解析逻辑
- 禁止在「task 格式 vs Output contract」上长篇推理；**一律以本 skill Output contract + 脚本产出为准**
- 禁止通读 `scripts/*.py`、禁止预读全部 `references/`

## Quick start（唯一默认路径）

`run_command` **已在项目根执行**。路径用相对路径 + `/`；**禁止** `cd`。

```bash
python extensions/skills/build-annual-report-index/scripts/build_minimal_index.py \
  data/reports/md/<code>/<report>.md \
  --output data/reports/index/<code>_<year>年年度报告_index.json \
  --pretty
```

校验：

```bash
python extensions/skills/build-annual-report-index/scripts/validate_sections_index.py \
  data/reports/index/<code>_<year>年年度报告_index.json
```

若上游指定了 `output_path`，把 `--output` 改成该路径。默认也可写到报告同级 `*_index.json`。

## Inputs / Outputs

输入：
- `report_path`（必填）：年报 Markdown 相对路径
- `output_path`（可选）：索引 JSON 输出路径

产出：
1. 一个 chapter 索引 JSON（脚本写入）
2. 简短执行摘要：顶层章节、带 children 的章节、财务报告关键条目、缺失/复核项

## Output contract（不可协商）

顶层至少包含：`report_file`、`company`、`ticker`、`year`、`index_version`、`chapters`

每个 chapter 至少包含：`chapter_id`、`title`、`line_start`、`line_end`、`priority`、`reason`；可选 `children`

上游 task 若给出简化字段名或不同 JSON 骨架，**仍以本 contract + 脚本产出为准**，不要手工改成简化结构。

脚本行为摘要（无需重做）：
- 顶层按目录建立骨架；`财务报告` 不保留为父节点，关键报表条目提升为 `财务报告-xxx`
- 仅对「公司简介和主要财务指标」「管理层讨论与分析」及「财务报告-合并报表附注」展开一层 children
- 最多两级，不展开第三层

## 失败回退（脚本失败后才允许）

仅当脚本非 0 退出或校验报错时：
1. 每次只读 `references/` 中**一个**相关规则文件
2. 用最小命令定位缺失标题行号（单次 `grep -n`，带行号范围限制）
3. 修补后再次跑脚本或校验；仍失败则返回已有输出路径 + 错误列表，停止

不要回退到「通读年报 + 手写整份索引」。

## Canonical rule files

- `references/index-generation-rules.md`
- `references/section-priority-rules.md`
- `templates/section-index-template.json`
- `references/usage-examples.md`

## Guardrails

- 不要默认读取整份年报
- 不要把目录命中当成正文命中
- 不要输出旧的平面 `sections`
- 不要保留原始 `财务报告` 父节点
- 不要把附注展开到第三层
- 若上游已指定 `output_path`，不要擅自改到其他目录
- 不要 `cd`；不要通读脚本源码；路径用相对路径 + `/`
