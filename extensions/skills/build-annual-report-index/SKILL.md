---
name: build-annual-report-index
description: 为 A 股年报 Markdown 生成最多两级的 chapter 索引 JSON；优先跑脚本生成并校验，适合新年报接入、补建索引和低上下文章节导航。
---

# Build Annual Report Index

这个 skill 只负责一件事：
**给一份上市公司年报 Markdown 生成一个最多两级的 chapter 索引 JSON。**

它不负责：digest、公司分析结论、通读整份年报。

## 强制执行顺序（违反即失败）

1. **第一步必须** `run_python_script` 跑 `build_minimal_index.py`（见下方）
2. **第二步** `run_python_script` 跑 `validate_sections_index.py` 校验
3. 根据校验 JSON 决定是否结束（见下「校验结果判定」）
4. **仅当**满足失败回退条件时，才允许最小修补；禁止一上来就 grep/read 扫全文

### 校验结果判定（必须遵守）

校验脚本 stdout 为 `{"errors":[...],"warnings":[...]}`，退出码：`errors` 非空 → 非 0，否则 → 0。

| 情况 | 动作 |
|------|------|
| `errors` 为空（无论 `warnings` 是否为空） | **成功**：返回输出路径 + 简短摘要（可附带 warnings 原文）并**立即结束** |
| `errors` 非空，或 build 脚本非 0 退出 | 才进入「失败回退」 |

**`warnings` 不是失败。** 常见如 `missing required financial report chapters: ...` 仅作提示：列出后交卷，**禁止**为此继续 `search_text`/`read_file` 扫年报或手写整份索引。

禁止事项（烧 token 的典型失败模式）：
- 禁止先 `Skill` 再手工探路；system 已有本 skill 快速参考时，**不要**再加载全文
- 禁止用 `grep`/`read_file`/`search_text` 反复扫描年报来「理解结构」替代脚本
- 禁止因校验 **warning** 进入长探索 / 手工补全附注 children
- 禁止因上游 `task` 给了简化字段（如只有 `title`/`start_line`/`children`）就改写输出 schema 或重写解析逻辑
- 禁止在「task 格式 vs Output contract」上长篇推理；**一律以本 skill Output contract + 脚本产出为准**
- 禁止通读 `scripts/*.py`、禁止预读全部 `references/`

## Quick start（唯一默认路径）

优先 `run_python_script`（cwd=项目根）。路径用相对路径 + `/`；**禁止** `cd`。仅当该工具不可用时再用 `run_command` 执行下方等价 shell。

```text
run_python_script(
  script_path="extensions/skills/build-annual-report-index/scripts/build_minimal_index.py",
  argv=[
    "data/reports/md/<code>/<stem>.md",
    "--output", "data/reports/md/<code>/<stem>.sections.json",
    "--pretty"
  ]
)
```

`<stem>` 与 Markdown 文件名去掉扩展名相同。`--output` 必须是这份 Markdown 的同级 `<stem>.sections.json`。文件已存在时照样执行，脚本会覆盖；禁止因为文件已在就跳过。不要写到 `data/reports/index/`。

校验：

```text
run_python_script(
  script_path="extensions/skills/build-annual-report-index/scripts/validate_sections_index.py",
  argv=["data/reports/md/<code>/<stem>.sections.json"]
)
```

`run_command` 兜底等价命令：

```bash
python extensions/skills/build-annual-report-index/scripts/build_minimal_index.py \
  data/reports/md/<code>/<stem>.md \
  --output data/reports/md/<code>/<stem>.sections.json \
  --pretty
```

上游若另给 `output_path`，仍只接受 Markdown 同级的 `<stem>.sections.json`。不要改到其它目录。

## Inputs / Outputs

输入：
- `report_path`（必填）：年报 Markdown 相对路径
- `output_path`（可选）：只接受 Markdown 同级的 `<stem>.sections.json`；已存在则覆盖

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

## 失败回退（仅 errors 非空 / build 非 0 才允许）

前提：`validate` 的 `errors` 非空，或 `build_minimal_index.py` 非 0 退出。  
**仅有 warnings → 不准进入本节。**

允许的最小修补：
1. 每次只读 `references/` 中**一个**相关规则文件
2. 用 `search_text` **单次**定位缺失标题行号（带路径与关键词限制）
3. 修补后再次跑脚本或校验；仍失败则返回已有输出路径 + **errors** 列表，停止

不要回退到「通读年报 + 手写整份索引」。单次回退循环最多再跑脚本/校验 **1 轮**。

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
- `--output` 只用 Markdown 同级的 `<stem>.sections.json`；上游给了别的路径也改回这一处，并覆盖已有文件
- 不要 `cd`；不要通读脚本源码；路径用相对路径 + `/`
