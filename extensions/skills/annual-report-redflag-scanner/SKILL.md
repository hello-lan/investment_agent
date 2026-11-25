---
name: annual-report-redflag-scanner
description: 仅用于 A 股年报财报排雷与风险检测（造假/硬伤信号、利润真假、现金流质量、资产与治理风险；R001–R038 + 必查覆盖表 → 风险评级与三大前提）。用户明确要排雷、风险扫描、造假识别、利润/现金流质量核查时使用。不做经营解读、业务驱动分析、行业对比或综合财务分析——那些应改用 annual-report-business-analyst / full-financial-analysis 等 skill。
---

# Annual Report Redflag Scanner

把“校验 Markdown 路径 → 检查同级索引 → 必要时补索引 → 定向阅读 → 输出分析并写报告”串成稳定流程。

这个 skill 只做排雷：基于最小必要阅读，对照规则和必查覆盖表，给出**财务判断、证据位置、风险含义、风险评级和下一步核查方向**。用户说「全面分析」时，指走完必查表，不是另起一套泛读。

## 适用范围

适合以下任务：
- 对一份已准备好的年报 Markdown 做排雷
- 排查利润是否为真、现金流、资产质量、负债压力与治理硬伤
- 判断三表是否闭环，并给出总体风险评级、必查覆盖与三大前提

不适合以下任务：
- 默认全文通读年报
- 重写索引生成逻辑
- 在缺少目标报告时凭空做财务判断

## 输入要求

必须要求用户提供：
- `report_path`
  - 必须是 Markdown 年报路径
  - 例如：`reports/company-a/annual-report-2024.md`
  - 或：`documents/annual_reports/2024/company-a-annual-report.md`

可选输入：
- `output_path`
  - 若提供，最终分析报告写到该路径
  - 若未提供，默认写到 `report_path` 同级父目录下的 `<report_stem>.analysis.md`

如果用户没有给出 `report_path`，先要求他们补充 Markdown 路径，不进入自动发现流程。

## Required workflow

### Step 1: 先校验目标报告路径
先读取 `references/report-discovery-rules.md`，按其中规则校验路径。

校验重点：
1. 用户是否显式提供了 `report_path`
2. `report_path` 是否指向 `.md` 文件
3. 该路径是否就是本次要分析的目标报告

如果没有明确的 `report_path`，就停在这里，先要求用户补充。

### Step 2: 检查 Markdown 是否存在
确认 `report_path` 对应的 Markdown 可读。

若不存在或不是 Markdown：
- 明确告知当前没有可分析的年报 Markdown
- 请用户提供准确的 Markdown 路径
- 不继续做财报分析

### Step 3: 只检查同级索引是否存在
默认索引路径：
- `report_path.parent / <report_stem>.sections.json`

先优先检查这一个同级标准索引。

若没有标准索引，再兼容检查同级目录下与该报告明显对应的：
- `<report_stem>.built.sections.json`
- `<report_stem>.generated.sections.json`
- 其他同 stem 的 `*.sections.json`

若仍没有可用索引：
- 调用 `annual-report-prepare` skill
- 只让它构建索引，不要顺带生成摘要或分析结论
- 显式传入当前 `report_path`
- 显式要求把索引写到同级父目录下的 `<report_stem>.sections.json`
- 索引完成后回到本 skill 的分析流程


### Step 4: 先读索引，再决定阅读范围
索引就绪后：
1. 先读取索引 JSON，建立章节地图
2. 优先识别 P0 / P1 章节
3. 先从关键章节形成全局判断
4. 只有命中异常时，才回查附注或相邻章节

不要因为用户说“分析财报”就默认把全文读完。

### Step 5: 按最小必要章节阅读
优先阅读以下章节；标题略有差异时，以实际命中标题为准。

**P0：默认优先读**
- `财务报告-审计报告`
- `第二节 公司简介和主要财务指标`
- `第三节 管理层讨论与分析`
- `财务报告-合并资产负债表`
- `财务报告-合并利润表`
- `财务报告-合并现金流量表`
- `财务报告-重要会计政策及会计估计`
- `财务报告-现金流量表补充资料`

**P1：按需要补充**
- `第四节 公司治理`
- `第六节 重要事项 / 重大事项`
- `第七节 股份变动及股东情况`
- `财务报告-合并所有者权益变动表`
- `财务报告-合并财务报表项目注释 / 合并报表附注`

如果索引里有 children，优先利用这些子节点做定向阅读：
- `主营业务分析`
- `资产及负债状况分析`
- `投资状况分析`
- `公司未来发展的展望`
- `公司治理`、`重要事项`、`股份变动及股东情况` 下的一层 children
- 附注中的一层科目节点，例如 `货币资金`、`应收账款`、`存货`、`短期借款`
- 财务报告专题节点，例如 `关联方及关联交易`、`合并范围的变更`、`承诺及或有事项`、`资产负债表日后事项`

### Step 6: 先过必查表，再按命中读专题
P0 读完后，固定按这个顺序取知识：

1. 读 `references/forensic-rules.md`（R001–R038 是对照下限）
2. 读 `references/mine-coverage.md`，对硬伤、货币资金、应收、存货、长期资产与商誉、利润质量、现金流肖像、联动逐组给出命中 / 未触发 / 待验证
3. 只有某一组命中，或证据不够、需要下钻时，才读对应专题文件
4. 出现术语、公式、阈值、现金流肖像或修正规则时，读 `references/terminology-and-metric-conventions.md`
5. 命中写成「事实数据 + R0xx + 风险推断」；规则外重大发现单独保留
6. 按 output contract 给出评级、必查覆盖表、三大前提与肖像类型名

专题文件只在命中或待验证需要补证据时打开：

- 应收、票据、合同资产、存货、预付、其他应收、固定资产、在建工程、开发支出、商誉、货币资金 → `references/asset-quality-and-capital-allocation.md`
- 短债、存贷双高、毛利率、费用率、税率、利润与经营现金流背离、现金流肖像 → `references/liability-profit-cashflow-linkage.md`
- 并购并表、募投变更、关联交易、质押、收入粉饰、费用资本化、洗大澡、现金流包装 → `references/governance-and-fraud-signals.md`

用户只点名某一块（例如只看利润或只看应收）时，仍然先完成硬伤和必查表，再把该块写深。`analysis-knowledge-map.md` 只负责导航，不替代规则库和必查表。

只对已读或因异常扩读的节点下结论。缺证据标待验证。禁止为刷规则通读附注。

### Step 7: 命中异常时扩大回查
出现以下情况时，扩大回查，但仍保持定向阅读：
- 审计意见非标、强调事项、持续经营提示
- 收入、利润、经营现金流明显背离
- 应收、存货、在建工程、商誉、其他应收款异常放大
- 高现金与高有息负债并存
- 大额减值、追溯重述、会计政策变更
- 关联交易、担保、诉讼、并购并表变化明显
- 管理层解释与数字不闭环

扩大回查时，优先回到：
- `财务报告-合并财务报表项目注释 / 合并报表附注` 的对应科目 children
- `财务报告-关联方及关联交易`
- `财务报告-合并范围的变更`
- `财务报告-承诺及或有事项`
- `财务报告-资产负债表日后事项`
- `管理层讨论与分析` 的相关 children
- `财务报告-重要会计政策及会计估计`
- 与异常直接相关的治理、股东、合并范围、重大投资章节

## Output contract

输出前先读取 `references/output-contract.md`，并按其中结构组织结果。

至少覆盖：
1. 一句话结论 + 总体风险评级
2. 前置排雷结果
3. 必查覆盖表（硬伤、货币资金、应收、存货、长期资产与商誉、利润质量、现金流肖像、联动；每行写未触发 / 命中规则 / 待验证）
4. 核心财务观察（只展开 3–5 条最重要的雷；现金流须标注肖像类型名）
5. 重点风险清单（含 `R0xx` 与高/中/低分层；可附规则外重大发现）
6. 三表联动判断
7. 三大前提判定（利润是否为真 / 是否可持续 / 维持是否需大量资本投入）
8. 杜邦驱动一问（指标可得时）
9. 待验证问题、下一步回查，以及 P0/P1/P2 跟踪建议

输出要求：
- 不做“摘要复述”，而做“分析结论 + 证据定位 + 风险含义”
- 每个关键判断尽量同时落到“年报证据”与“内部分析逻辑”两层
- 排雷命中引用 `references/forensic-rules.md` 中的 `R0xx`；分组是否覆盖以 `references/mine-coverage.md` 为准
- 涉及指标、阈值、经验口径、现金流画像、修正规则时，以 `references/terminology-and-metric-conventions.md` 为准
- 除了在聊天中给出结论，还要把最终 Markdown 报告写到：
  - `output_path`（若用户提供）
  - 否则写到 `report_path.parent / <report_stem>.analysis.md`

## Guardrails

- 缺少 Markdown 时，不要硬做分析
- 缺少索引时，不要退化成全文通读；优先复用 `annual-report-prepare`
- 不要重造索引逻辑
- 不要把附注整段全部读入上下文；只按异常项目定向回查
- 不要只罗列数字，要解释数字之间是否闭环
- 不要把无法解释的异常轻描淡写；解释不闭环本身就是风险信号
- 不要在命中异常后跳过对应专题知识文件
- 不要跳过 `forensic-rules.md` 和 `mine-coverage.md`；也不要为刷规则全文通读
- 不要省略总体风险评级、必查覆盖表、三大前提或现金流肖像类型名
- 不要因为用户只问某一科目就跳过硬伤和必查表
- 第一版不要生成 digest 文件
- 不要自行从 ticker / company / year 推测报告路径
- 不要默认回退到任何项目专属的固定索引目录
- 不要只在聊天里输出结果而忘记按约定路径写出最终分析 Markdown

## Suggested user intents

以下表达都适合触发本 skill：
- 帮我分析 `reports/company-a/annual-report-2024.md`
- 看下这份 Markdown 年报值不值得继续跟
- 帮我排查这份年报里有没有明显雷点
- 先分析这份财报，不要全文硬读

## References

按需读取：
- `references/report-discovery-rules.md`：报告路径校验、同级索引与输出路径规则
- `references/analysis-knowledge-map.md`：执行型知识导航
- `references/forensic-rules.md`：R001–R038 排雷规则、严重度与回查映射
- `references/mine-coverage.md`：排雷必查分组、触发条件与覆盖表收口
- `references/terminology-and-metric-conventions.md`：术语、公式、阈值、经验口径、修正规则
- `references/analysis-principles.md`：前置排雷、分析顺序、对比纪律、扩大回查规则
- `references/asset-quality-and-capital-allocation.md`：经营性资产、长期资产、资本开支、非主业资产与投资问题
- `references/liability-profit-cashflow-linkage.md`：负债结构、利润质量、现金流质量、三表联动
- `references/governance-and-fraud-signals.md`：治理异常、并购并表、关联交易、欺诈与包装信号
- `references/output-contract.md`：输出结构、写法与报告落盘要求
- `references/usage-examples.md`：典型场景与知识路由示例
- 如需补建索引，调用 `annual-report-prepare` skill
