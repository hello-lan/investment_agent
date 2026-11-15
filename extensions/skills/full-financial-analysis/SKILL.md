---
name: full-financial-analysis
description: 完整财报分析流程：下载A股近3年完整财报PDF → PDF转Markdown → 年报章节索引构建 → 结构化财报分析。当用户要求对某只A股进行完整财务分析且 Agent 已挂载 build_annual_report_index / analyze_financial_report 时触发。
---

# 完整财报分析流程（Subagent 版）

串行执行以下 4 步。步骤 1–2 由本 Agent **加载原子 skill 后亲自执行**；步骤 3–4 调用已挂载 Subagent。

## 前置条件

当前 Agent **必须已挂载**以下两个 Subagent（否则步骤 3/4 无可用工具，应停止并提示用户挂载）：
- `build_annual_report_index`
- `analyze_financial_report`

## ⚠️ 核心规则（必须严格遵守）

1. **步骤 1–2**：先 `Skill(name=...)` 加载对应原子 skill 完整说明，**下一轮**再按说明用 `run_python_script` 等执行。同一步不要「加载 Skill 又立刻按正文执行」。**禁止**对步骤 1–2 使用 `DelegateTask`。
2. **步骤 3–4**：必须调用对应 **Subagent 工具名**；**禁止** `DelegateTask`，也禁止父 Agent 亲自跑索引脚本或通读年报做分析。
3. **禁止调试脚本**：Subagent / 脚本报错时不要亲自调试；反馈用户或按降级策略处理。
4. **步骤预算**：每个步骤最多消耗父 Agent 5 步。超过后进入下一步。
5. **降级优先**：某步骤连续失败 2 次后跳过，用已有存量数据继续。
6. **目录规范**：输出路径是绝对约束；每步完成后校验产物是否落在预期路径。

## 前置确认

用户未明确提供时主动询问：
- **股票名称或代码**（必填）
- **报告年份范围**（默认：近 3 年完整年报）
- **报告类型**（默认：年报，非摘要）

## Subagent task 编写原则

1. 路径、参数前置；相对项目根 + 正斜杠
2. Windows 禁止写死盘符绝对路径
3. **不要**在 `task` 里自拟 JSON schema、章节规则或手工扫描步骤

---

## 步骤 1：下载财报 PDF

1. 调用 `Skill(name="download-a-share-reports")` 加载完整说明
2. 按该 skill 说明执行下载（优先 `run_python_script`）

**关键参数**：
- 股票代码 / 名称：`{code}` / `{name}`
- 年份：`{start_year}`–`{end_year}`
- 类别：年报
- 保存目录：`data/reports/pdf/`（产物在 `data/reports/pdf/{code}/`）

**输出**：`data/reports/pdf/{code}/` 下的 PDF 路径列表  
**失败处理**：失败 2 次后检查已有 PDF，有则继续下一步

---

## 步骤 2：PDF 转 Markdown

1. 调用 `Skill(name="pdf-to-markdown")` 加载完整说明
2. 按该 skill 说明转换（默认快速模式；优先 `run_python_script`）
3. 一次处理所有待转换 PDF；已有 `.md` 的年份跳过

**路径约定**：
```
输入: data/reports/pdf/{code}/{code}_{year}年年度报告_{year}.pdf
输出: data/reports/md/{code}/{code}_{year}年年度报告_{year}.md
```
> 实际 PDF 文件名以步骤 1 返回为准。

**输出**：`data/reports/md/{code}/` 下的 `.md`  
**校验**：目标年份 `.md` 均存在，缺失则补转

---

## 步骤 3：年报章节索引构建

调用 Subagent 工具 `build_annual_report_index`（禁止 `DelegateTask` / 禁止本 Agent 亲自跑建索引脚本）。

- 每个待建索引的 `.md` 各调用一次；互不依赖时可同 turn 并行
- 已有同级 `<stem>.sections.json` 则跳过
- `output_path` **必须**为报告同级 `.sections.json`（供步骤 4 复用）

**task 模板**：
```
report_path: data/reports/md/{code}/{code}_{year}年年度报告_{year}.md
output_path: data/reports/md/{code}/{code}_{year}年年度报告_{year}.sections.json
```

**输出**：同级 `<stem>.sections.json`  
**校验**：各年份索引存在，缺失则补调

---

## 步骤 4：结构化财报分析

调用 Subagent 工具 `analyze_financial_report`（禁止 `DelegateTask` / 禁止本 Agent 亲自通读分析）。

- 每个年份各调用一次；互不依赖时可同 turn 并行
- `task` 只写路径

**task 模板**：
```
report_path: data/reports/md/{code}/{code}_{year}年年度报告_{year}.md
output_path: data/reports/md/{code}/{code}_{year}年年度报告_{year}.analysis.md
```

**输出**：`data/reports/md/{code}/<stem>.analysis.md`

### 降级策略

1. **第 1 次重试**：只分析最近一年  
2. **第 2 次重试**：仍只最近一年，并注明「优先读索引与 P0，不做附注深挖」  
3. **彻底失败**：汇总 PDF / Markdown / 索引路径汇报，注明分析未完成  

降级仍须走 `analyze_financial_report` Subagent。

---

## 数据流

```
用户输入（股票名称/代码）
  → 步骤1: Skill(download-a-share-reports) → data/reports/pdf/{code}/*.pdf
    → 步骤2: Skill(pdf-to-markdown) → data/reports/md/{code}/{code}_{year}年年度报告_{year}.md
      → 步骤3: build_annual_report_index → 同级 .sections.json
        → 步骤4: analyze_financial_report → 同级 .analysis.md
```

> 步骤 3 索引必须写到 Markdown **同级** `.sections.json`，勿写到 `data/reports/index/`。

## 增量策略

- 步骤1：已有 PDF → 跳过
- 步骤2：已有 `.md` → 跳过
- 步骤3：已有同级 `.sections.json` → 跳过
- 步骤4：始终执行
