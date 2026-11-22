---
name: full-financial-analysis
description: 完整财报分析流程：按公司按年准备年报 PDF、Markdown 与同级索引 → 结构化财报分析；若用户要多年分析，再汇总多年综合报告。单年需求只做到单年分析即止。当用户要求对某只A股进行完整/单年/多年财务分析且 Agent 已挂载 prepare_financial_reports / analyze_financial_report 时触发。
---

# 完整财报分析流程（Subagent 版）

步骤 1–4 按本次年份范围执行；**步骤 5 仅多年模式**。步骤 1–4 调用已挂载 Subagent；步骤 5（若触发）由本 Agent **读取各年分析报告后亲自汇总**。父 Agent 不亲自下载、转写或建索引。

## 前置条件

当前 Agent **必须已挂载**以下两个 Subagent（否则步骤 1–4 无可用工具，应停止并提示用户挂载）：
- `prepare_financial_reports`
- `analyze_financial_report`

## ⚠️ 核心规则（必须严格遵守）

1. **步骤 1–3**：每个目标年份各调用一次 `prepare_financial_reports`。task 只写一个 `code` 和一个 `year`。多年时由父 Agent 拆开；互不依赖的年份可以同一轮并行。**禁止**把年份范围、`start`/`end` 或多家公司塞进一次 task。**禁止** `DelegateTask`，也禁止父 Agent 亲自下载、转写或跑建索引脚本。
2. **步骤 4**：必须调用 `analyze_financial_report`；**禁止** `DelegateTask`，也禁止父 Agent 亲自通读年报做分析。`report_path` 用该年 prepare 交回的实际 Markdown 路径。
3. **步骤 5**：仅**多年模式**执行；由本 Agent 亲自读取步骤 4 产出的各年 `.analysis.md`，按 `references/multi-year-synthesis-contract.md` 汇总并写出多年综合报告。单年需求跳过本步。**禁止**再委派 Subagent 重跑单年分析；**禁止**为汇总而全文通读原始年报。
4. **禁止调试脚本**：Subagent / 脚本报错时不要亲自调试；反馈用户或按降级策略处理。
5. **步骤预算**：每个步骤最多消耗父 Agent 5 步。超过后进入下一步。
6. **降级优先**：某步骤连续失败 2 次后跳过，用已有存量数据继续。
7. **目录规范**：只认 `prepare_financial_reports` 交回的路径。约定外目录里的旧文件不算已有。

## 前置确认

用户未明确提供时主动询问：
- **股票名称或代码**（必填）
- **报告年份范围**（默认：近 3 年完整年报）
- **报告类型**（默认：年报，非摘要）

先判定本次是**单年**还是**多年**，再决定是否跑步骤 5：
- 用户只要某一年（如「分析 2024 年年报」「看一下 2025 年报」）→ **单年模式**：步骤 1–4 只覆盖该年，**跳过步骤 5**
- 用户要多年 / 近 N 年 / 完整财报分析且年份跨度 ≥ 2（含默认近 3 年）→ **多年模式**：步骤 1–4 覆盖各年，步骤 4 完成后**执行步骤 5**
- 不要因为目录里碰巧已有其他年份的旧 `.analysis.md`，就在单年模式下擅自做多年汇总

## Subagent task 编写原则

1. 路径、参数前置；相对项目根 + 正斜杠
2. Windows 禁止写死盘符绝对路径
3. **不要**在 `task` 里自拟 JSON schema、章节规则或手工扫描步骤

---

## 步骤 1–3：准备该年年报（PDF、Markdown、索引）

调用 Subagent 工具 `prepare_financial_reports`（禁止 `DelegateTask` / 禁止本 Agent 亲自下载、转写或建索引）。

- 每家公司、每一年各调用一次
- 互不依赖的年份可以同一轮并行
- 子 Agent 自己判断缺 PDF、缺 Markdown 还是缺索引；有索引但没有同年报 Markdown 时，它会补 Markdown 并覆盖重建索引
- 父 Agent 不要把 `data/reports/index/`、`1_pdf/`、`2_markdown/` 里的旧文件当作已齐

**task 模板**（只有这两个字段）：
```
code: 600519
year: 2024
```

**输出**：子 Agent 交回的三个相对路径。文件名以它交回的 `{stem}` 为准，不要改写成 `{code}_{year}年年度报告_{year}`。

```
pdf: data/reports/pdf/{code}/{stem}.pdf
markdown: data/reports/md/{code}/{stem}.md
index: data/reports/md/{code}/{stem}.sections.json
```

**失败处理**：同一年失败 2 次后，若交回路径里 Markdown 与同级索引都在，则继续步骤 4；否则跳过该年。

---

## 步骤 4：结构化财报分析（各年）

调用 Subagent 工具 `analyze_financial_report`（禁止 `DelegateTask` / 禁止本 Agent 亲自通读分析）。

- 每个年份各调用一次；互不依赖时可同 turn 并行
- `task` 只写路径
- 本步只做**单年**分析；多年对比留给步骤 5

**task 模板**（路径用该年 prepare 交回的 Markdown，不要另写一套文件名）：
```
report_path: data/reports/md/{code}/{stem}.md
output_path: data/reports/md/{code}/{stem}.analysis.md
```

**输出**：`data/reports/md/{code}/{stem}.analysis.md`

### 降级策略

1. **第 1 次重试**：只分析最近一年  
2. **第 2 次重试**：仍只最近一年，并注明「优先读索引与 P0，不做附注深挖」  
3. **彻底失败**：汇总 PDF / Markdown / 索引路径汇报，注明分析未完成；**跳过步骤 5**

降级仍须走 `analyze_financial_report` Subagent。

---

## 步骤 5：多年综合分析报告（仅多年模式）

**仅当本次任务为多年分析时执行。** 单年需求在步骤 4 结束后即完成，不要进入本步。

本步是多年对比的唯一落点；`analyze-financial-report` 本身不做多年协议。

### 触发与跳过（按用户意图优先）

| 条件 | 行为 |
|------|------|
| **单年模式**（用户只要 1 个报告年） | **跳过步骤 5**；交付该年 `.analysis.md` 即可，勿生成多年综合报告 |
| **多年模式**且目标年份中可读 `.analysis.md` ≥ 2 份 | **必须**执行步骤 5 并落盘 |
| **多年模式**但因降级等只剩 1 份可读分析 | 跳过步骤 5；说明「目标为多年但仅完成单年分析，未生成综合报告」 |
| 可读分析 0 份 | 跳过；按步骤 4 失败汇报 |

> 是否多年，以**本次确认的年份范围**为准，不以目录里历史残留文件为准。

### 执行方式（多年模式且满足触发条件时）

在步骤 4 **本次目标年份全部完成（或按降级留下可读产物）之后**：

1. 先读取 `references/multi-year-synthesis-contract.md`
2. 只列出**本次目标年份**的 `*.analysis.md`（不要把范围外旧文件算进来）
3. **逐份 `read_file` 各年分析报告**（只读 `.analysis.md`，不要通读原始年报）
4. 按 contract 汇总趋势、规则连续性、画像演变、三大前提与跟踪建议
5. 写出多年综合报告并校验路径

### 输入

```
data/reports/md/{code}/{stem}.analysis.md
```
（`{stem}` 是该年 prepare 交回的 Markdown 文件名；仅本次多年任务覆盖到、且步骤 4 成功的年份）

### 输出

```
data/reports/md/{code}/{code}_{start_year}-{end_year}_多年综合财务分析.md
```

示例：`data/reports/md/300124/300124_2023-2025_多年综合财务分析.md`

### 汇总要点（细节以 contract 为准）

- 核心指标与各年评级 / 现金流量肖像对照表
- 恶化 / 改善 / 拐点；哪些 `R0xx` 跨年重复或升级
- 三表联动的跨年是否同向
- 三大前提的多年口径回答
- 高/中/低风险分层 + P0/P1/P2 跟踪建议

### 禁止

- 禁止在单年模式下执行本步或“顺便”汇总目录里其他年份
- 禁止重新委派 `analyze_financial_report` 做「多年模式」
- 禁止把各年 `.analysis.md` 全文粘贴进综合报告
- 禁止为补数而全文通读原始年报 Markdown
- 禁止输出买卖建议

---

## 数据流

```
用户输入（股票名称/代码 + 单年或多年范围）
  → 步骤1–3: 每个 code+year 一次 prepare_financial_reports
      → pdf/{code}/{stem}.pdf
      → md/{code}/{stem}.md
      → md/{code}/{stem}.sections.json
        → 步骤4: analyze_financial_report → 同 stem 的 .analysis.md
          → 步骤5（仅多年模式）: 读取本次各年 .analysis.md → {code}_{start}-{end}_多年综合财务分析.md
```

> 索引由 `prepare_financial_reports` 写到 Markdown **同级** `.sections.json`。  
> 单年模式在步骤 4 结束；步骤 5 不执行。

## 增量策略

- 步骤 1–3：交给 `prepare_financial_reports`。Markdown 与同级索引都在它会跳过；有索引但没有 Markdown 时它会补 Markdown 并覆盖重建索引。父 Agent 不要凭约定外的旧文件跳过
- 步骤4：始终执行（覆盖本次目标年份的单年分析）
- 步骤5：仅多年模式；目标综合报告已存在且本次各年 `.analysis.md` 未更新时可跳过，否则在步骤 4 后重跑汇总

## References

- `references/multi-year-synthesis-contract.md`：步骤 5 输出结构、路径与护栏
