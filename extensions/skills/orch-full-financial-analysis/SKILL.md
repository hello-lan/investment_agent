---
name: orch-full-financial-analysis
type: orch
description: 完整财报分析流程：下载A股近3年完整财报PDF → PDF转Markdown → 财报章节切割 → 财务排雷分析。当用户要求对某只A股进行完整财务分析时触发（如"分析茅台财报"、"对XXX做财务尽调"、"全面分析XXX的财务状况"）。
depends_on:
  - download-a-share-reports
  - pdf-to-markdown
  - split-financial-report
  - a-share-financial-forensic
---

# 完整财报分析流程（编排）

## ⚠️ 核心规则（必须严格遵守）

1. **必须委派**：每个步骤的执行必须通过 `DelegateTask` 委派给子Agent。**绝对禁止**父Agent亲自调用 `run_command` 执行步骤内的工作。
2. **禁止调试脚本**：如果委派的子Agent报告脚本错误或API故障，**不要亲自调试**。直接将错误信息反馈给用户，或换用备选方案。亲自调试是步数浪费的首要原因。
3. **步骤预算**：每个步骤最多消耗父Agent 5步（用于委派创建和结果检查）。超过后立即进入下一步骤。
4. **降级优先**：某步骤委派连续失败2次后，跳过该步骤，使用已有的存量数据继续。
5. **委派失败处理**：如果某次委派返回错误（如工具调用超限、执行异常），**绝对禁止父Agent亲自调用 run_command 接管执行**。正确的处理方式是：分析失败原因 → 调整委派指令（缩小范围、降低复杂度）→ 重新委派。如果同一任务重新委派2次仍失败，按规则4降级跳过。
6. **目录规范强制执行**：委派指令中的输出路径是**绝对约束**，子Agent必须使用指定的路径，不得自行创建新目录或更改命名。每个步骤委派完成后必须校验输出是否符合预期目录结构。

串行执行以下 4 个步骤，每步完成后再进入下一步。任一步骤失败时停止并报告用户。

## 前置确认

执行前确认以下信息（用户未明确提供时主动询问）：
- **股票名称或代码**（必填）
- **报告年份范围**（默认：近 3 年完整年报）
- **报告类型**（默认：年报，非摘要）

## 委派指令编写原则

委派指令必须**精简、关键信息前置**，避免被截断：

1. **第一行写死输出路径**（完整绝对路径），后续行引用时可省略
2. **路径、参数、文件名放前面**，说明性文字放后面或省略
3. **用列表格式**而非段落，每行一个文件
4. **避免冗余描述**（如"已有文件跳过"已包含在规则6中，各原子技能内部已实现，无需在委派指令中重复）

---

## 步骤 1：下载财报 PDF

**必须委派**。用 `DelegateTask(skill_names=["download-a-share-reports"], task="...")` 委派给子Agent下载指定股票的年度报告 PDF。

**委派指令模板**：
```
下载{股票名称}（{股票代码}）的年度报告PDF。
- 股票代码：{code}
- 年份范围：{start_year}-{end_year}（共{count}年）
- 报告类型：年报
- 保存目录：{PROJECT_ROOT}/data/reports/{code}/1_pdf/
- 已有文件跳过，只下载缺失的
```

**输入**：股票代码、年份范围
**输出**：`data/reports/{股票代码}/1_pdf/` 目录下的 PDF 文件路径列表
**步数预算**：父Agent最多消耗5步（含委派创建+结果检查）
**失败处理**：委派失败2次后，检查已有文件并继续下一步

---

## 步骤 2：PDF 转 Markdown

**必须委派**。用 `DelegateTask(skill_names=["pdf-to-markdown"], task="...")` 委派。

- **一次委派处理所有待转换的 PDF 文件**
- 已有 `.md` 文件的年份跳过，只列出缺失的

**委派指令模板（精简）**：
```
输出目录: {PROJECT_ROOT}/data/reports/{code}/2_markdown/
逐一转换以下PDF为Markdown（快速模式）:
- {PROJECT_ROOT}/data/reports/{code}/1_pdf/{code}/{code}_{year1}年年度报告_{year1}.pdf
- {PROJECT_ROOT}/data/reports/{code}/1_pdf/{code}/{code}_{year2}年年度报告_{year2}.pdf
- ...
```
> 路径占位符替换规则：`{code}`=股票代码（如002258），`{year1}`=起始年，`{PROJECT_ROOT}`=项目根目录

**输入**：步骤 1 输出的 PDF 路径列表
**输出**：`data/reports/{股票代码}/2_markdown/` 目录下的 `.md` 文件
**步数预算**：父Agent最多消耗3步
**委派后校验**：执行 `ls data/reports/{code}/2_markdown/*.md` 确认数量与年份匹配，缺失则用单文件委派补充

---

## 步骤 3：财报章节切割

**必须委派**。用 `DelegateTask(skill_names=["split-financial-report"], task="...")` 委派。

- **一次委派处理所有待切割的 `.md` 文件**
- 输出目录必须使用 `3_split/{code}_{year}/` 格式（脚本根据年份自动创建子目录）

**委派指令模板（精简）**：
```
输出根目录: {PROJECT_ROOT}/data/reports/{code}/3_split/
逐一切割以下Markdown文件（auto模式，启用 --financial-sub）:
- {PROJECT_ROOT}/data/reports/{code}/2_markdown/{code}_{year1}年年度报告_{year1}.md
- {PROJECT_ROOT}/data/reports/{code}/2_markdown/{code}_{year2}年年度报告_{year2}.md
- ...
⚠️ 必须使用指定的输出根目录，禁止自行为输出目录改名（如3_chapters等）
```

**输入**：步骤 2 输出的 `.md` 文件路径列表
**输出**：`data/reports/{股票代码}/3_split/{股票代码}_{年份}/` 目录下的切割文件
**步数预算**：父Agent最多消耗3步
**委派后校验**：执行 `ls -d data/reports/{code}/3_split/{code}_*` 确认每个年份都有对应目录，缺失年份则单独补充委派

---

## 步骤 4：财务排雷分析

**必须委派**。用 `DelegateTask(skill_names=["a-share-financial-forensic"], task="...")` 委派。

**委派策略**：一次委派覆盖所有年份。`a-share-financial-forensic` 技能内部已支持多年模式（collect_data.py 自动发现所有年份），不要按年份拆分为多次委派。

**委派指令模板（精简）**：
```
股票代码: {code}
股票名称: {name}
split_dir: {PROJECT_ROOT}/data/reports/{code}/3_split/
覆盖年份: {year1}-{yearN}
输出报告: {PROJECT_ROOT}/data/reports/{code}/4_output/{code}_{year1}-{yearN}_财务排雷分析报告.md
```
> split_dir 下的年份子目录格式为 `{code}_{year}/`，collect_data.py 脚本按此格式自动发现

**输入**：步骤 3 输出的 `data/reports/{code}/3_split/` 目录路径
**输出**：完整分析报告，保存于 `data/reports/{code}/4_output/{code}_{year_from}-{year_to}_财务排雷分析报告.md`

**步数预算**：子Agent内部执行 a-share-financial-forensic 技能流程：collect_data.py（1步）→ cat data_manifest.md + 校验匹配（2-3步）→ 按清单逐文件读取（5-6步）→ 纯推理分析（0步）→ 写入报告（1-2步）= **合计 9-13步**。父Agent最多消耗3步用于委派创建和结果检查。

---

## 步骤 4 降级策略

如果步骤 4 委派失败（token 预算不足或执行错误），**禁止父Agent亲自调用 run_command**，应按以下顺序降级：

**第 1 次重试**：缩小委派范围，改为单一年份分析（优先最近年份）：
- 委派指令中只指定一个年份的切割目录
- 要求子Agent精简数据加载：只读 data_manifest.md + 三张报表（已解析）+ 审计报告 + 附注关键段落
- 工具调用预算降低至 5-6 次以内

**第 2 次重试**：进一步简化，只生成关键数据摘要：
- 委派指令中明确要求"只读取 data_manifest.md 中的结构化报表数据，基于已有数据做快速排雷，不读原始切割文件"
- 工具调用预算降低至 2-3 次

**彻底失败**：如果两次重试均失败，跳过步骤 4，汇总已有步骤的输出（PDF列表 + Markdown路径 + 切割结果）生成最终汇报。在汇报中注明"财务排雷分析未能完成"，并列出失败的年份供用户手动处理。

**关键约束**：无论降级到哪一层，都必须通过 `DelegateTask` 委派，**绝对禁止父Agent亲自调用 run_command 执行分析工作**。

---

## 数据流

```
用户输入（股票名称/代码）
  → 步骤1: PDF 文件（data/reports/{code}/1_pdf/{code}/*.pdf）
    → 步骤2: Markdown 文件（data/reports/{code}/2_markdown/{code}_{year}年年度报告_{year}.md）
      → 步骤3: 切割文件（data/reports/{code}/3_split/{code}_{year}/ch*.md）
        → 步骤4: 排雷报告 (data/reports/{code}/4_output/{code}_{year_from}-{year_to}_财务排雷分析报告.md)
```

> **目录格式约定**（不可变）：步骤3 切割输出使用 `3_split/{code}_{year}/`，步骤4 forensic 脚本依赖此格式自动发现年份目录。


## 增量策略

每一步都遵循"先检查已有产物 → 仅处理缺失部分"原则：
- 步骤1：已有 PDF → 跳过下载
- 步骤2：已有 `.md` → 跳过转换
- 步骤3：已有切割目录 → 跳过切割
- 步骤4：始终执行（分析基于最新数据）
