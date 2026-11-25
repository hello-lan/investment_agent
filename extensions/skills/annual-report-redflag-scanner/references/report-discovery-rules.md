# Report path and sibling output rules

这个文件只负责一件事：
**基于用户显式提供的 `report_path`，校验目标年报 Markdown，并推导同级索引与分析输出路径。**

## Canonical input rule

本 skill 的主输入不是 ticker、company、year，而是：
- `report_path`

要求：
1. 用户必须显式提供 `report_path`
2. `report_path` 必须指向 `.md` 年报文件
3. 若用户未提供 `report_path`，先要求补充，不进入自动发现流程

例如：
- `reports/company-a/annual-report-2024.md`
- `documents/annual_reports/2024/company-a-annual-report.md`

## Report path validation rule

收到 `report_path` 后，按以下顺序处理：

### 1. 明确它是这次要分析的目标报告
如果用户给出多个路径候选，先让他们明确本次分析哪一份。

### 2. 检查是否为 Markdown
若路径不是 `.md`：
- 明确告知当前只接受 Markdown 年报路径
- 请用户改为提供对应 Markdown 文件路径
- 不进入分析流程

### 3. 检查文件是否存在且可读
若不存在：
- 明确告诉用户当前仓库中没有可分析的目标 Markdown
- 请他们提供正确路径
- 不进入分析阶段

## Default sibling paths

以：
- `report_dir = report_path.parent`
- `report_stem = <report_path 去掉 .md 后的文件名>`

推导默认产物路径：

### Default index path
- `report_dir / <report_stem>.sections.json`

### Default analysis output path
- `report_dir / <report_stem>.analysis.md`

### User-provided output path
若用户显式给出：
- `output_path`

则最终分析报告写到该路径，而不是默认同级路径。

## Index discovery order

报告存在后，再定位索引。

### Preferred index path
优先寻找同级标准索引：
- `report_dir / <report_stem>.sections.json`

### Compatible fallback paths
如果标准索引不存在，可兼容寻找同级目录下与该报告明显对应的：
- `<report_stem>.built.sections.json`
- `<report_stem>.generated.sections.json`
- 其他同 stem 的 `*.sections.json`

兼容路径存在时：
- 优先使用 `<report_stem>.sections.json`
- 其次是 `<report_stem>.built.sections.json`
- 再其次是 `<report_stem>.generated.sections.json`
- 若有多个同 stem 候选，优先选择最接近正式标准命名的版本

不要默认回退到任何项目专属的固定目录。

默认规则只依赖当前 `report_path` 的同级父目录，不依赖某个仓库的既有目录结构。

## Missing markdown rule

若用户没有提供 `report_path`，或提供的不是可读 Markdown：
- 明确告诉用户当前没有可直接分析的目标 Markdown
- 请他们提供准确 Markdown 路径
- 不进入分析阶段

推荐表达风格：
- 先给我这份年报对应的 Markdown 路径，我再按这份报告继续分析。
- 当前只接受 Markdown 年报路径；你把目标 `.md` 文件路径给我，我再继续。

## Missing index rule

若未找到可用索引：
- 调用 `build-annual-report-index` skill
- 显式传入当前 `report_path`
- 显式要求它把索引写到同级：`report_dir / <report_stem>.sections.json`
- 只让它构建索引，不要顺带输出年报分析
- 构建完成后再继续本 skill 的分析流程

## Using the index

索引一旦存在，后续流程应遵守：
1. 先读索引 JSON
2. 先根据顶层章节和 children 建立阅读计划
3. 按 `line_start` / `line_end` 定向读取
4. 异常触发时再回查附注 children 或相邻章节

不要绕过索引直接退化成全文阅读。

## Output path rule

最终分析报告的写入规则：
1. 若用户提供 `output_path`，写到该路径
2. 若用户未提供，写到同级默认路径：`report_dir / <report_stem>.analysis.md`

聊天里给出结论，不等于完成任务；还应按约定把最终 Markdown 报告写出。

## Ambiguity handling

遇到以下歧义时先澄清，不要硬猜：
- 用户给了多个 `report_path` 候选
- 用户同时给了多个输出路径候选
- 同级目录下存在多个同 stem 索引，且标准命名优先级仍无法判断

## Historical layout note

不同项目里，历史索引与报告可能曾采用不同目录布局。

这些差异只说明“路径可能不统一”，**不代表本 skill 的默认规则**。

本 skill 当前的 canonical rule 是：
- 用户显式提供 `report_path`
- 索引默认在 `report_path.parent` 同级
- 分析报告默认也写到 `report_path.parent` 同级
