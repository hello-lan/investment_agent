---
name: annual-report-prepare
description: 为 A 股准备年报三件套（下载 PDF → 转 Markdown → 建索引）。支持单票单期，也支持多股票、多年份批量。触发词包括"下载年报"、"准备年报"、"PDF转Markdown"、"建索引"、"download financial reports"、"pdf to md"等。
---

# 年报准备（下载 → 转写 → 建索引）

为用户指定的股票与报告期准备三件套：PDF、Markdown、同级章节索引。支持一只或多只股票、一个或多个报告期。按「股票 × 报告期」逐份处理：每份按产物链级联检查，缺哪环就从哪环起重跑。不要通读年报。

## 任务范围

- 解析用户意图得到一组 `(code, 报告期)`；单票单期与批量（多股票、年份区间、近 N 年、`names`）均可
- 下载阶段可一次拉多票/多年份；转写与建索引仍按每份报告独立执行级联
- 未指定年份时：可按用户「近 N 年」展开；完全未说年份则先问清，或明确告知将使用脚本默认（当前年往前 5 年）再执行
- 原因说明：链路长时批量会占上下文——优先先批量下载，再逐份转写/建索引；交卷时用清单汇总，不要贴正文

## 只认的路径

其它目录里的文件不算已有，不读、不搬。

```text
base_dir = data/reports
```

- 上面是报告根目录默认值。执行前先看系统提示词有没有另给 `base_dir = ...`；有则以系统提示词为准。
- `{base_dir}` 指解析后的值。路径相对项目根，用 `/`。

| 产物 | 路径 |
|------|------|
| PDF | `{base_dir}/pdf/{code}/{stem}.pdf`（默认 `data/reports/pdf/{code}/`） |
| Markdown | `{base_dir}/md/{code}/{stem}.md` |
| 索引 | `{base_dir}/md/{code}/{stem}.sections.json` |

`{stem}` 与 PDF 文件名去掉扩展名相同（下载脚本按公告标题命名）。PDF、Markdown、索引用同一个 stem。

忽略 `{base_dir}/index/`、`{base_dir}/{code}/1_pdf/`、`2_markdown/`、`3_split/` 以及其它约定外路径。

## 脚本一览

| 脚本 | 说明 |
|------|------|
| `scripts/download_report.py` | 多数据源下载编排器（支持多票、年份区间） |
| `scripts/sources/*.py` | 巨潮 / 东方财富 / 新浪爬虫 |
| `scripts/pdf2markdown_fast.py` | PDF→MD（pdfplumber） |
| `scripts/build_outline_index.py` | **主路径**：PDF 书签 → MD 行号，生成章节索引 |
| `scripts/build_minimal_index.py` | **兜底**：无书签整份回退 / Agent 补缺时的 MD 目录方案 |
| `scripts/fill_sections_index.py` | 把 MD fallback 中缺的顶层/children 合并进主索引 |
| `scripts/validate_sections_index.py` | 校验索引 |

**优先 `run_python_script`**（cwd=项目根）。**禁止 `cd`**。仅当专用工具不可用时再用 `run_command`。

## 级联预检（确认参数后必须先做）

产物链固定顺序：**PDF → Markdown → 索引**。对每个 `(code, 报告期)` 分别找第一个缺失环节（断点），再决定删什么、从哪跑。多份任务时：可先统一下载缺 PDF 的，再逐份做转写与建索引。

### 1. 确认参数

得到待处理列表：一个或多个 `code`（或可解析名称）× 一个或多个报告期。参数不清时再问；不要因「多票/多年份」拒绝执行。

### 2. 预检匹配（按每份报告）

对每个 `code`，只列举这两个目录（目录不存在 → 该侧全部视为缺失；不要全盘 `find`）：

- `{base_dir}/pdf/{code}/`
- `{base_dir}/md/{code}/`

只认文件名里包含该报告期、且匹配类别的文件：

- 年报：含「年度报告」或「年报」
- 半年报 / 季报：按用户给定类别匹配
- 含「摘要」的跳过；其它报告期不看

PDF 命中后记下 `stem`（文件名去扩展名）。MD / 索引须与同一 `stem` 对应；PDF 缺失时，仍按报告期+类别匹配 md 目录里待清理的旧 MD / `.sections.json`。

### 3. 找断点 → 先删下游 → 从断点重跑

对每份报告，按 **PDF → MD → 索引** 找第一个缺失环节，记为断点 `k`。

| 断点 | 先删除（即使文件还在也要删） | 再执行 |
|------|------------------------------|--------|
| PDF 缺失 | 本期已匹配到的 MD + `.sections.json`（含孤立索引） | 步骤 1 → 步骤 2 → 步骤 3 |
| PDF 有、MD 缺失 | 同 stem（或本期匹配到）的 `.sections.json` | 步骤 2 → 步骤 3 |
| PDF+MD 有、索引缺失 | （下游已无，无需删） | 步骤 3 |
| 三件都有 | 不删 | 不跑，该份记 `status: ready` |

硬性要求：

- **级联失效**：断点之后的环节一律重跑，下游文件「在」也不能跳过
- **先删后建**：重跑前先删断点之后的对应文件，避免旧 stem / 孤立文件把目录搞乱
- 删除范围仅限该 `code` + 该报告期匹配到的文件；不动其它股票或其它报告期
- 下载后 `stem` 以新 PDF 为准；PDF 断点时预检匹配到的旧 MD/索引（即使 stem 不同）也要清掉
- 「有索引无 MD」= MD 断点（先删索引 → 转写 → 建索引）；若 PDF 也无则升为 PDF 断点
- 删除用 `run_command`（如 `rm` / `del`）针对具体文件路径；禁止 `rm -rf` 整目录

---

## 步骤 1：下载 PDF

通过巨潮、东方财富、新浪等多数据源下载。某一源失败时自动切下一源；全部失败则提示用户。

| 优先级 | 数据源 | 类型 |
|--------|--------|------|
| 1 | 巨潮资讯网 (cninfo) | API |
| 2 | 东方财富 (eastmoney) | API |
| 3 | 新浪财经 (sina) | 网页 |

### 参数提取

| 用户表述 | 参数 | 示例 |
|----------|------|------|
| 单个年份（如「2024 年报」） | `--start` 与 `--end` **相同** | `--start 2024 --end 2024` |
| 年份区间（如「2020–2024」） | `--start` / `--end` 分别为起止年 | `--start 2020 --end 2024` |
| 近 N 年 | 换算为起止年后传入 | 近 3 年 → 当前年起算 |
| 多只股票 | `--names` 逗号分隔，或多次 `--stock` | `--names 茅台,五粮液` |
| "年报" / "年度报告" | `--category 年报` | 默认 |
| "半年报" / "中报" | `--category 半年报` | |
| "季报" | `--category 季报` | |

批量时优先一次 `download_report.py` 拉齐缺 PDF 的票/年份，再进入转写。

### 调用模板

单票单期：

```text
run_python_script(
  script_path="extensions/skills/annual-report-prepare/scripts/download_report.py",
  kwargs={"stock": "600519", "start": 2024, "end": 2024, "category": "年报", "save_dir": "{base_dir}/pdf"},
  timeout_seconds=120
)
```

多票多年份：

```text
run_python_script(
  script_path="extensions/skills/annual-report-prepare/scripts/download_report.py",
  kwargs={"names": "茅台,五粮液", "start": 2020, "end": 2024, "category": "年报", "save_dir": "{base_dir}/pdf"},
  timeout_seconds=300
)
```

其它 kwargs：`name`（单只）/ `names`（多只）/ `source`（如 `eastmoney`）。

```bash
python extensions/skills/annual-report-prepare/scripts/download_report.py \
  --stock 600519 --start 2024 --end 2024 --category 年报 --save-dir {base_dir}/pdf

python extensions/skills/annual-report-prepare/scripts/download_report.py \
  --names 茅台,五粮液 --start 2020 --end 2024 --category 年报 --save-dir {base_dir}/pdf
```

下载成功后直接用脚本打印的路径，**不要再 `find` / 全量 `list_files` 探路**。

仅支持 A 股。完整名称映射见 `scripts/download_report.py` 的 `STOCK_NAME_MAP`。

---

## 步骤 2：PDF 转 Markdown

使用 `pdf2markdown_fast.py`（pdfplumber）。脚本会自动安装缺失依赖。

对每份缺 MD 的报告各跑一次（批量时逐份调用，不要通读 PDF）。

```text
run_python_script(
  script_path="extensions/skills/annual-report-prepare/scripts/pdf2markdown_fast.py",
  argv=[
    "{base_dir}/pdf/002415/002415_2025年年度报告_2025.pdf",
    "-o", "{base_dir}/md/002415/002415_2025年年度报告_2025.md"
  ],
  timeout_seconds=120
)
```

**必须传 `-o`**，写成 `{base_dir}/md/{code}/{stem}.md`。不要写到 PDF 同目录。脚本会自动创建输出目录。转换成功后直接进入建索引，不要再探路。

---

## 步骤 3：建章节索引

给一份年报生成最多两级的 chapter 索引 JSON。**主路径用 PDF 书签**，行号仍落在已转写的 Markdown 上；不负责 digest、分析结论或通读全文。批量时对每份缺索引的报告各执行一轮。步骤 3 需要同 stem 的 PDF + MD 都已就绪。

### 强制执行顺序（违反即失败）

| 顺序 | 动作 |
|------|------|
| 3.1 | 跑 `build_outline_index.py`（PDF 书签主路径） |
| 3.2 | 若 3.1 非 0（无书签 / 定位过少）→ 整份改跑 `build_minimal_index.py` 写出同路径索引 |
| 3.3 | 跑 `validate_sections_index.py` |
| 3.4 | **Agent 目视检查**章节树是否完整（见下方清单；只读 `.sections.json`，不通读年报） |
| 3.5 | 判定不完整 → **只允许脚本补缺闭环**（见下）；禁止对年报 `.md` 多轮搜读 |
| 3.6 | 补缺后仍不完整 / 仍 `errors` → **硬失败该份**（见「失败回退」）；继续下一份 |

### 3.5 脚本补缺闭环（唯一允许的修复路径）

判定不完整后，**按顺序只做这些事**，不得插入对年报 `.md` 的 `search_text` / `read_file`：

1. `build_minimal_index.py` → 临时 `{stem}.sections.md-fallback.json`
2. `fill_sections_index.py` 把缺章 / 空 children / 错位章合并进主索引
3. 删除临时 fallback 文件
4. 再跑 `validate_sections_index.py`
5. 再做一次目视检查（仍只看 `.sections.json`）

补缺阶段**禁止**：

- 对 `{stem}.md`（或任何年报正文）调用 `search_text` / `read_file`
- 手写、拼贴、局部改写 `.sections.json`
- 用「再搜一次标题」「再读一段正文确认行号」代替 `fill_sections_index.py`
- 跳过 fill、只跑 minimal 后继续在 MD 里考古

若 fallback / fill / 二次目视后仍不完整 → 直接进入 3.6，**不要**开始长程排查。

### 校验结果判定

校验 stdout 为 `{"errors":[...],"warnings":[...]}`；`errors` 非空 → 非 0，否则 → 0。

| 情况 | 动作 |
|------|------|
| `errors` 为空（无论 `warnings`） | 进入 Agent 目视检查；检查通过则记下路径，继续下一份或交卷 |
| `errors` 非空，或 outline/minimal build 均非 0 | 进入 3.5 脚本补缺；补缺后仍失败 → 3.6 |
| 目视发现缺章 / 标题错位 / 缺 children | **必须**走 3.5；禁止改读年报 MD |

**`warnings` 不是失败，也不单独触发补全。** 禁止因 warning 继续 `search_text`/`read_file` 扫年报或手写索引。

禁止：用 grep/read 扫全文替代脚本；因 warning 或标题错位长探索；改写 Output contract；通读 `scripts/*.py` 或预读全部 `references/`；手写整份索引。

### Agent 完整性检查清单（目视，非代码 assert）

只读 `{stem}.sections.json` 的 `chapters`（标题 / `chapter_id` / 行号 / children）。**禁止为做本检查去读年报 `.md`。** 检查：

- 顶层是否有：公司简介/主要财务指标、管理层讨论与分析（或明显同义标题）
- 是否具备 6 个 `financial_report_*`：审计、合并资产负债/现金流/利润、会计政策、合并附注
- 简介章 / 管理层讨论章是否有合理 `children`；`financial_report_notes` 是否有附注科目 `children`
- 有无空区间、行号明显乱序/重叠（仅凭 JSON 判断）
- **标题错位（高优先级）**：`financial_report_*` 的 `title` 在去掉 `财务报告-` 前缀后，应能一眼看出对应报表名（如「合并利润表」「合并现金流量表」「审计报告」）。若 title 是会计政策长句、附注段落碎片、或与 `chapter_id` 明显不符（例如 id 是利润表但 title 像「当期净损益中属于少数股东…」「的现金流量纳入合并现金流量表…」）→ **视为不完整**，走 3.5，禁止自己在 MD 里重定位后改 JSON

任一项明显缺失或错位 → 走 3.5 补缺；全部看起来齐全 → 交卷该份。

### 调用模板

书签主路径（优先）：

```text
run_python_script(
  script_path="extensions/skills/annual-report-prepare/scripts/build_outline_index.py",
  argv=[
    "--pdf", "{base_dir}/pdf/<code>/<stem>.pdf",
    "--md", "{base_dir}/md/<code>/<stem>.md",
    "--output", "{base_dir}/md/<code>/<stem>.sections.json",
    "--pretty"
  ]
)
```

无书签整份回退 / 补缺来源：

```text
run_python_script(
  script_path="extensions/skills/annual-report-prepare/scripts/build_minimal_index.py",
  argv=[
    "{base_dir}/md/<code>/<stem>.md",
    "--output", "{base_dir}/md/<code>/<stem>.sections.json",
    "--pretty"
  ]
)
```

补缺合并（Agent 判定不完整时；fallback 用临时路径）：

```text
run_python_script(
  script_path="extensions/skills/annual-report-prepare/scripts/build_minimal_index.py",
  argv=[
    "{base_dir}/md/<code>/<stem>.md",
    "--output", "{base_dir}/md/<code>/<stem>.sections.md-fallback.json",
    "--pretty"
  ]
)

run_python_script(
  script_path="extensions/skills/annual-report-prepare/scripts/fill_sections_index.py",
  argv=[
    "{base_dir}/md/<code>/<stem>.sections.json",
    "--from", "{base_dir}/md/<code>/<stem>.sections.md-fallback.json",
    "--output", "{base_dir}/md/<code>/<stem>.sections.json",
    "--pretty"
  ]
)
```

补缺后删除临时 `{stem}.sections.md-fallback.json`，再跑校验。

```text
run_python_script(
  script_path="extensions/skills/annual-report-prepare/scripts/validate_sections_index.py",
  argv=["{base_dir}/md/<code>/<stem>.sections.json"]
)
```

`--output` 必须是 Markdown 同级 `<stem>.sections.json`；已存在则覆盖。不要写到 `{base_dir}/index/`。

### Output contract（不可协商）

顶层至少：`report_file`、`company`、`ticker`、`year`、`index_version`、`chapters`

每个 chapter 至少：`chapter_id`、`title`、`line_start`、`line_end`、`priority`、`reason`；可选 `children`

脚本行为：顶层优先来自 PDF 书签（MD 目录为回退）；`财务报告` 不保留为父节点，报表条目提升为 `财务报告-xxx`；仅对「公司简介和主要财务指标」「管理层讨论与分析」「财务报告-合并报表附注」展开一层 children；最多两级。行号始终相对 Markdown。

### 失败回退（3.6：补缺后仍不完整 / 仍 errors）

脚本补缺闭环已用尽后，**立刻**将该份记为失败，不要进入长程修复：

1. 可选：只读 `references/` 中**一个**相关规则文件（非必须）
2. 可选：对索引 JSON 或年报 MD 做 **最多 1 次** `search_text`（仅用于写清 `reason`，不得据此手改整份索引）
3. 该份输出 `status: failed` + 一句 `reason`（如「利润表/现金流量表标题错位，outline 与 MD fallback 均未能纠正」）
4. **立即继续下一份**（批量时）；不得为修这一份再开多轮工具。除非用户明确只要这一份，否则禁止在失败票上继续探索

不要通读年报手写整份索引。单份失败不等于整批失败。

### Canonical rule files

- `references/index-generation-rules.md`
- `references/section-priority-rules.md`
- `templates/section-index-template.json`
- `references/usage-examples.md`

### Guardrails

- 不要默认读整份年报；不要把目录命中当正文命中
- 目视检查与补缺阶段：只碰 `.sections.json` 与索引脚本；发现错位就走 fill，不在 MD 正文里考古
- 不要输出旧平面 `sections`；不要保留原始 `财务报告` 父节点；不要把附注展到第三层
- 路径相对项目根 + `/`；禁止盘符路径；禁止 `cd`

---

## 交卷

按每份报告列清单；不要贴 PDF、Markdown 或索引正文。

单份：

```text
code: 600519
year: 2024
status: ready
pdf: {base_dir}/pdf/600519/<stem>.pdf
markdown: {base_dir}/md/600519/<stem>.md
index: {base_dir}/md/600519/<stem>.sections.json
```

多份时逐条列出（或表格），并给一句汇总，例如 `ready 8 / failed 1 / total 9`。失败条目写 `status: failed` 与一句 `reason`。
