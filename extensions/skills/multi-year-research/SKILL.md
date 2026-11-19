---
name: multi-year-research
description: 多年综合研究编排。登记年报与外部材料，抽取带出处的证据包，拉取公告标题，再由分析子 Agent 自己写成综合备忘录。用户要求综合多年财报、经营研究和公司研究时使用。
depends_on:
  - build-research-corpus
  - extract-research-evidence
  - build-announcement-timeline
  - write-research-memo
  - download-a-share-reports
  - pdf-to-markdown
  - build-annual-report-index
---

# 多年综合研究

父 Agent 是调度员。抽取和写作交给 Subagent。父 Agent 不读年报、不读证据包正文、不读备忘录正文，也不预设分析框架。

## 前置条件

当前 Agent **必须已挂载**：

- `extract_research_evidence`
- `write_research_memo`

未挂载就停止，并提示用户挂载。不要改由父 Agent 亲自抽取或写作。

## 核心规则

1. 建清单、下 PDF、转 Markdown、建索引、拉公告：父 Agent 先 `Skill(name=...)` 加载对应说明，**下一轮**再按说明执行。同一步不要又加载又执行。这些步骤禁止 `DelegateTask`。
2. 抽取证据、写备忘录：必须调用对应 Subagent 工具名。禁止 `DelegateTask`，禁止父 Agent 亲自通读。
3. 脚本或 Subagent 报错时不要亲自调试。同一任务连续失败 2 次就降级，用已有产物继续。
4. 每个步骤最多消耗父 Agent 5 步。
5. 路径相对项目根，使用 `/`。禁止盘符绝对路径。
6. Subagent 的 `task` 只写路径、代码、年份、哈希和文档类型。不要在 task 里自拟分析框架。
7. 父 Agent 只用 `list_files` 或脚本 JSON 确认产物在约定路径，不用 `read_file` 打开年报、证据包或备忘录。

## 前置确认

用户没说清时再问：

- 股票代码（必填，6 位）
- 年份范围（默认最近三个完整会计年度：当前自然年的前三年。2026 年执行时即为 2023–2025）

## 步骤 1：语料清单

1. `Skill(name="build-research-corpus")`
2. 按该 skill 运行脚本

看 stdout JSON：

- `missing_annual_years` 非空 → 进入步骤 2
- `needs_index` 非空 → 进入步骤 3
- 否则进入步骤 4

失败 2 次：若 `data/research/{code}/corpus.json` 已在，就用它继续；否则停止并说明清单没建成。

## 步骤 2：补年报 Markdown（仅缺年报时）

只对 `missing_annual_years` 里的年份做。已有 Markdown 的年份跳过。

1. `Skill(name="download-a-share-reports")`，年报 PDF 保存到 `data/reports/pdf/`
2. `Skill(name="pdf-to-markdown")`，输出到 `data/reports/md/{code}/{code}_{year}年年度报告_{year}.md`
3. 再跑一次步骤 1 的清单脚本

某一年连续失败 2 次：放弃该年，清单里的缺口留到备忘录的覆盖说明。不要父 Agent 自己改下载脚本。

## 步骤 3：补章节索引（仅 `needs_index` 时）

对清单里 `trust=filing` 且 `index_path` 为空的文件，逐份建索引。索引只提供行号。

1. `Skill(name="build-annual-report-index")`
2. 按该 skill 跑脚本，把索引写到 Markdown **同级**的 `<stem>.sections.json`
3. 再跑一次清单脚本，确认这些文档的 `index_path` 已填上

同一文件连续失败 2 次：该文件不进入抽取。不要通读年报来手写索引。

## 步骤 4：抽取证据

对清单里 `evidence_status` 不是 `current` 的文档，各调用一次 `extract_research_evidence`。互不依赖的可以同一轮并行。已是 `current` 的跳过。

`task` 模板：

```text
source_path: data/reports/md/600519/600519_2024年年度报告_2024.md
evidence_path: data/research/600519/evidence/2024_annual.md
source_sha256: <清单中的 sha256>
doc_type: annual
trust: filing
year: 2024
index_path: data/reports/md/600519/600519_2024年年度报告_2024.sections.json
```

第三方材料照清单字段填，`index_path` 留空。

子 Agent 应只返回 `status` 和路径。父 Agent 用 `list_files` 确认 `evidence_path` 存在。

同一文档失败 2 次：跳过该文档。至少还有 1 份 `current` 的定期报告证据时，继续后面的步骤；一份都没有则停止，不要父 Agent 亲自读年报。

## 步骤 5：公告时间线

1. `Skill(name="build-announcement-timeline")`
2. 按该 skill 运行脚本

`status=missing` 不是失败，继续写备忘录。脚本本身失败（没有写出 `events.md`）时重试 1 次，仍失败就继续，并在下一步的 task 里注明公告文件缺失。

## 步骤 6：写备忘录

清单里至少有一份定期报告证据为 `current` 时，调用 `write_research_memo`。只调用这一次。

`task` 模板：

```text
corpus_path: data/research/600519/corpus.json
events_path: data/research/600519/events.md
memo_path: data/research/600519/2023-2025_research.md
notes_path: data/research/600519/notes.md
```

用户有侧重点时，在 task 末尾加一行 `focus: ...`。不要写分析提纲。

父 Agent 确认 `memo_path` 已生成后，把这个路径告诉用户，并说明缺了哪些年份或公告。不要复述备忘录。

失败 2 次：报告已经落盘的证据包和清单路径，说明备忘录未完成。

## 数据流

```text
用户给出代码和年份
  → corpus.json
    → 缺年报则下载并转 Markdown，缺索引则建索引，然后重写清单
      → evidence/{doc_id}.md
      → events.md
        → {start}-{end}_research.md
```

产物都在 `data/research/{code}/`，与 `data/reports/` 里的其他分析结果分开。
