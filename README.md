# Investment Agent

A 股基本面分析智能助手。浏览器里对话、上传财报，由 LLM Agent 自主调用数据工具和 Skill，完成行情查询、财报解读、排雷、估值和同业对比，并流式输出 Markdown 研报。另有七步法个股看板，用来直接看财务数字。

---

## 功能特性

- **多模型** — 兼容 Anthropic 与 OpenAI 兼容接口（Claude、DeepSeek、Qwen、Ollama 等）。可设默认模型，以及用于辅助任务的 utility 模型，并记录输入/输出/缓存价格。
- **三种执行循环** — 每个 Agent 可选双循环（快循环 + 慢思考）、ReAct，或 Plan Execute（先拆解再委派汇总）。
- **Skill 插件** — `extensions/skills/` 下的 `SKILL.md` 会被自动发现。对话中按需加载完整说明，需要时再跑技能脚本。
- **子 Agent** — 可定义独立上下文的 Subagent，也可通过 `DelegateTask` 把下载、转写、建索引、专项分析委派出去。子任务有自己的步数和 token 预算。
- **文件与脚本工具** — 列举、读取、搜索、写入 `data/`；在已启用技能目录里跑 Python 脚本；需要时再执行 shell。
- **外部检索** — 工具页可配置 HTTP 检索实例，把公司材料和投资通识片段接进对话。
- **财报流水线** — 下载年报 → PDF 转 Markdown → 章节索引 → 按规则做结构化分析与排雷，多年分析可再汇总。
- **个股看板** — 按代码或名称查询，用七步法展示营收质量、成本、成长、业务构成、资产负债、投入产出和收益率。
- **会话与观测** — 历史会话可继续；统计页查看 token 成本、执行轨迹，并支持导出和清理。

---

## 页面

| 路径 | 用途 |
|------|------|
| `/` | 对话：选 Agent、上传文件、看工具调用和慢思考 |
| `/agents` | 配置 Agent（模型、提示词、Skill、工具、Subagent、循环与上下文） |
| `/skills` | 查看已发现的 Skill |
| `/tools` | 管理 HTTP 检索等工具实例 |
| `/model` | 模型 CRUD、默认模型、utility 模型、连通性测试 |
| `/dashboard` | 七步法企业分析看板 |
| `/observability` | Token 成本与执行链路 |

---

## 快速开始

### 前置要求

- Python 3.10+
- 一个 Anthropic API，或兼容 OpenAI Chat Completions 的 LLM

### 安装与启动

Windows 可直接用启动脚本（会创建 `.venv` 并拉起服务）：

```bat
start.bat
start.bat --reload
start.bat --port 8000
```

或手动安装后启动：

```bash
pip install -r requirements.txt
uvicorn investment_agent:app --reload --host 0.0.0.0 --port 8000
```

浏览器打开 `http://127.0.0.1:8000`。

### 配置模型

打开 `/model`，填入显示名、模型名、API Key。两种接入：

- **Anthropic** — API Key 即可。工具调用更稳的模型更适合本项目。
- **OpenAI Compatible** — 需要 Base URL 和 API Key，适用于 DeepSeek、Qwen、Ollama 等。

第一个模型会自动成为默认模型。可再指定一个 utility 模型，用于生成会话标题。页面上可以测试连通性。

### 开始分析

在对话页输入请求，例如：

> 分析贵州茅台（600519）近三年的盈利能力变化趋势

也可以上传财报（`.txt` `.md` `.pdf` `.xlsx` `.xls` `.docx` `.doc`，单文件最大 100MB）。提取文本会截断到 5 万字符后进入上下文；完整年报分析更适合先下载并转成 Markdown，再走索引和结构化分析 Skill。

---

## 使用场景

| 场景 | 示例 |
|------|------|
| 行情与财务数据 | 「查宁德时代最新估值和近五年 ROE」 |
| 财务排雷 | 「按排雷规则检查这份年报的利润质量和现金流」 |
| 完整财报流程 | 「对伊利股份做完整财务分析」 |
| 年报解读 | 上传或指定 Markdown 年报 → 「提取关键指标并对照去年」 |
| 行业对比 | 「对比茅台和五粮液的 ROE 和资产负债率」 |
| 估值观察 | 「用 DCF 和 PE/PB 给海康威视一个前提显式的估值区间」 |
| 看数字 | 打开 `/dashboard`，搜索 `600519` 或「茅台」 |

分析结论面向研究阅读，不构成买卖建议。

---

## 工作方式

一次对话由 `AgentRunner` 拉起。`loop_factory` 按 Agent 的 `loop_mode` 创建引擎，默认是双循环。

| 模式 | 行为 |
|------|------|
| `dual_loop` | 每步推理并调用工具；每隔若干步插入慢思考，复盘进度并纠偏 |
| `react` | 单循环推理，适合轻量工具调用 |
| `plan_execute` | 先把任务拆成可独立推进的阶段，再委派 Subagent 或 `DelegateTask`，最后由主 Agent 汇总 |

主循环有步数上限、token 预算、连续同工具调用检测，以及可中断的 SSE 流。长对话在开跑前按预算压缩系统提示词和历史消息；运行中可裁剪上下文，并把过长的工具结果卸载成摘要。

Subagent 与父对话隔离：只拿任务说明和自己的工具集，结束后把文本结果交回父 Agent。默认子 Agent 定义在 `extensions/subagents/`，启动时补齐数据库里缺失的条目。挂到 Agent 上之后，它们会以独立工具的形式暴露给主模型。

---

## 项目结构

```
investment_agent/                 # 仓库根目录
├── investment_agent/             # Python 包（uvicorn investment_agent:app）
│   ├── main.py                   # FastAPI 入口、页面与路由
│   ├── config.py                 # 读取 settings.json
│   ├── settings.json             # 引擎、上下文、目录、数据库
│   ├── app/
│   │   ├── api/                  # 对话、会话、Agent、Subagent、工具、文件、看板、观测
│   │   ├── services/             # Agent / 会话 / 行情同步 / 工具实例
│   │   ├── observability/        # 成本与链路追踪
│   │   ├── templates/            # Jinja2 页面
│   │   └── static/               # 原生 HTML/JS/CSS
│   └── agent/
│       ├── core/                 # 双循环、ReAct、Plan Execute、子 Agent、模型适配
│       ├── tools/                # 文件、脚本、shell、Skill、委派、HTTP 检索
│       ├── skills/               # Skill 加载与脚本执行
│       └── context/              # 预算、裁剪、卸载、token 估算
├── extensions/
│   ├── skills/                   # Skill 定义（SKILL.md + scripts/）
│   └── subagents/                # 默认 Subagent Markdown
├── data/                         # SQLite、上传文件、财报与输出
├── docs/                         # 读财报笔记与设计文档
├── requirements.txt
└── start.bat
```

---

## Skill

放在 `extensions/skills/<name>/SKILL.md`，启动时扫描注册。启用后，模型先看到名称和描述；需要执行时调用 `Skill` 工具加载正文。带 `scripts/` 的技能通过 `run_python_script` 运行入口脚本。

### 内置 Skill

| Skill | 作用 |
|-------|------|
| `a-share-stock-market` | 股票资料、历史行情、实时行情、指数 |
| `a-share-financial-data` | 利润表、资产负债表、现金流量表、估值与财务指标 |
| `a-share-valuation` | DCF、相对估值、周期股调整，输出前提显式的观察区间 |
| `industry-compare` | 同业关键指标对比，标出异常偏离 |
| `a-share-financial-forensic` | 三表联动排雷，输出疑点、分级和证据链 |
| `analyze-financial-report` | 基于年报索引做结构化分析（利润、现金流、资产、治理、R001–R038） |
| `build-annual-report-index` | 为年报 Markdown 生成两级章节索引 |
| `download-a-share-reports` | 从巨潮、东方财富、新浪下载年报、半年报、季报 |
| `pdf-to-markdown` | PDF 转 Markdown（默认 pdfplumber，可切高质量模式） |
| `split-financial-report` | 按章节切开大型财报 Markdown |
| `full-financial-analysis` | 下载 → 转写 → 建索引 → 单年分析；多年需求再汇总 |
| `orch-full-financial-analysis` | 编排完整流程：下载、转写、按章节切开、再做排雷 |
| `demo_echo` / `demo_brief_report` | 调用链与多参数报告的演示技能 |

行情和财务报表数据来自 AKShare。

### 自定义 Skill

```yaml
---
name: my-skill
description: 一句话说明何时应该用它
---
# 正文会在模型调用 Skill 工具时注入
```

脚本放在该技能的 `scripts/` 下。参数以 CLI 旗标传入，也可从 stdin 读 JSON。

---

## 工具

内置工具在 Agent 配置里勾选。文件类工具默认绑定；`run_command` 和 `DelegateTask` 需要手动打开。

| 工具 | 作用 |
|------|------|
| `Skill` | 按名称加载某个 Skill 的完整说明 |
| `read_file` / `list_files` / `search_text` | 在授权范围内读文件、列目录、搜文本 |
| `write_file` | 把文本写到 `data/`（仅文件名时进 `data/tmp/`） |
| `run_python_script` | 只运行已启用技能目录里的 `.py` |
| `run_command` | 在项目根执行 shell（风险更高，默认不勾） |
| `DelegateTask` | 把多步子任务交给隔离的子 Agent |
| HTTP 检索实例 | 在 `/tools` 配置外部检索服务，每个实例是一个独立工具 |

路径访问受策略约束：业务上限制敏感目录，写文件落在 `data/`。

---

## 默认 Subagent

| 名称 | 作用 |
|------|------|
| `analyze_financial_report` | 对指定年报 Markdown 做最小必要阅读和可复核的排雷分析 |
| `build_annual_report_index` | 优先跑脚本，为年报生成章节索引 JSON |

在 `/agents` 的「Subagent 定义」里可以新建。子 Agent 不能再挂 `DelegateTask`，也不能再挂其他 Subagent。模型留空时继承主 Agent。

---

## 配置

全局参数在 `investment_agent/settings.json`。模型密钥存在 SQLite `models` 表，不写进这个文件。单个 Agent 可以在页面上覆盖引擎和上下文参数。

```json
{
  "engine": {
    "max_steps": 30,
    "slow_think_interval": 5,
    "token_budget": 100000,
    "subagent_token_budget": 100000,
    "loop_detection_threshold": 3,
    "skill_body_ttl": 600,
    "context_trim_token_threshold": 90000,
    "max_subagent_depth": 3,
    "offload_threshold": 800,
    "offload_summary_strategy": "truncate",
    "offload_summary_chars": 200
  },
  "context": {
    "safety_margin": 0.10,
    "max_chars_per_msg": 2000,
    "budget": {
      "system_max_tokens": 40000,
      "tools_max_tokens": 20000
    }
  },
  "skills": { "directory": "./extensions/skills" },
  "subagents": { "directory": "./extensions/subagents" },
  "db": { "type": "sqlite", "sqlite_path": "./data/agent.db" }
}
```

| 参数 | 含义 |
|------|------|
| `max_steps` | 单次任务最大步数 |
| `slow_think_interval` | 双循环下每隔多少步做一次慢思考 |
| `token_budget` | 主 Agent token 上限 |
| `subagent_token_budget` | 子 Agent 默认 token 上限 |
| `loop_detection_threshold` | 连续相同工具调用达到该次数后中止 |
| `context_trim_token_threshold` | 运行中开始裁剪上下文的 token 水位 |
| `max_subagent_depth` | 委派最大层数，`0` 表示不允许创建子 Agent |
| `offload_threshold` | 工具结果超过该字符数后卸载为摘要 |

改文件后需重启进程。`get_settings()` 有缓存，代码里调用 `reload_settings()` 才会重读。

---

## API 概览

```
对话
  POST   /api/chat                         发起任务（JSON 或带文件的 multipart）
  GET    /api/chat/{task_id}/stream        SSE 流
  GET    /api/chat/{task_id}/status        任务状态
  POST   /api/chat/{task_id}/interrupt     中断
  POST   /api/chat/retry                   重试

会话
  GET    /api/sessions
  GET    /api/sessions/{id}
  POST   /api/sessions/{id}/title
  PATCH  /api/sessions/{id}/context
  DELETE /api/sessions/{id}

Agent / Subagent
  GET|POST        /api/agents
  GET|PUT|DELETE  /api/agents/{id}
  POST            /api/agents/{id}/avatar
  GET|POST        /api/subagents
  GET|PUT|DELETE  /api/subagents/{id}

模型
  GET|POST        /api/settings/models
  PUT             /api/settings/models/default
  PUT             /api/settings/models/utility
  PUT|DELETE      /api/settings/models/{id}
  POST            /api/settings/models/test

工具与技能
  GET    /api/skills
  GET    /api/tools
  GET    /api/tools/templates
  GET|POST        /api/tools/instances
  PUT|DELETE      /api/tools/instances/{id}
  POST   /api/tools/test

文件（对话页左侧 data/ 树）
  GET    /api/files/tree
  GET    /api/files/children
  GET    /api/files/view

看板
  GET    /api/stocks/search
  GET    /api/stock-dashboard/{code}
  GET    /api/stock-dashboard/{code}/status

观测
  GET    /api/observability/cost
  GET    /api/observability/traces
  GET    /api/observability/traces/{trace_id}
  GET    /api/observability/trace-sessions
  GET    /api/observability/sessions
  GET    /api/observability/export/traces
  POST   /api/observability/cleanup

  GET    /health
```

---

## 技术栈

| 层 | 技术 |
|----|------|
| Web | FastAPI + Uvicorn + Jinja2 |
| LLM | Anthropic SDK、OpenAI SDK |
| 数据 | AKShare；看板结果缓存在 SQLite |
| 数据库 | SQLite（aiosqlite） |
| 前端 | 原生 HTML / JS / CSS，SSE 流式；看板用 ECharts |
| 文件 | pdfplumber、python-docx、openpyxl、xlrd |
| 图表 | matplotlib、mplfinance |

没有前端构建步骤。后端改完由 `--reload` 生效，静态文件刷新页面即可。

---

## 开发

### 加一个数据或分析能力

优先做成 Skill：在 `extensions/skills/` 下新建目录和 `SKILL.md`，需要计算或拉数时再加 `scripts/`。不要把一次性分析逻辑写进核心循环。

### 加一个基础设施工具

在 `agent/tools/` 继承 `BaseTool`，实现 `name`、`description`、`schema` 和 `async run()`。外部 HTTP 能力优先用工具页的检索模板配实例，而不是再写一个专用客户端。

### 加一个子 Agent

在 `extensions/subagents/` 放一份带 YAML frontmatter 的 Markdown，或在 `/agents` 页面创建。写清 `description`（主模型靠它决定何时调用）、允许的 `tools` / `skills`，以及可选的 token 与裁剪覆盖。

---

## 待办

仍在推进的方向见 [docs/TODO.md](docs/TODO.md)，主要包括：

- 用容器隔离替代代码层的路径逃逸检查
- 控制子 Agent 读大文件带来的 token 放大
- 文件权限判断改为规则加一次轻量模型校验
- 带内容权重的检索、根据执行日志改 Skill、进一步提高缓存命中

读财报方法笔记在 `docs/财报分析实操手册-初学者按图索骥.md`、`docs/财报排雷要点-手把手教你读财报.md`、`docs/财报企业经营分析要点-手把手教你读财报.md`。

---

## 许可证

MIT
