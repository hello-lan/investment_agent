# Investment Agent

A 股基本面分析智能助手。浏览器里对话、上传财报，由 LLM Agent 自主调用数据工具和 Skill，完成行情查询、财报解读、排雷、估值和同业对比，并流式输出 Markdown 研报。另有个股看板，用七步法看财务数字，并用商业八问整理定性问题。

分析结论面向研究阅读，不构成买卖建议。

---

## 功能特性

- **多模型** — 兼容 Anthropic 与 OpenAI 兼容接口（Claude、DeepSeek、Qwen、Ollama 等）。可设默认模型，以及用于生成会话标题的 utility 模型。支持输入/输出价格，以及缓存读取、缓存创建价格。
- **三种执行循环** — 每个 Agent 可选双循环（快循环 + 慢思考）、ReAct，或 Plan Execute（先拆解再委派汇总）。
- **Skill 插件** — `extensions/skills/` 下的 `SKILL.md` 会被自动发现。对话中按需加载完整说明，需要时再跑技能脚本。编排技能可声明依赖的原子技能。
- **子 Agent** — 可定义独立上下文的 Subagent，也可通过 `DelegateTask` 把多步任务委派出去。同一轮里互不依赖的子任务可以并行。子任务有自己的步数和 token 预算。
- **文件与脚本工具** — 列举、读取、搜索、写入 `data/`；在已启用技能目录里跑 Python 脚本；需要时再执行 shell。
- **外部检索** — 工具页可配置 HTTP 检索实例，把公司材料和投资通识片段接进对话。
- **财报流水线** — 下载年报 → PDF 转 Markdown → 章节索引 → 结构化分析与排雷。多年分析可再汇总。
- **个股看板** — 按代码或名称查询。七步法展示营收质量、成本、成长、业务构成、资产负债、投入产出和收益率；商业八问给出读公告和研报时的问题清单。数据来自 AKShare，结果缓存在 SQLite。
- **会话与观测** — 历史会话可继续。上下文可按「可见对话」或「完整轨迹」回放。统计页查看 token 成本、执行轨迹，并支持导出和清理。

---

## 页面

| 路径 | 用途 |
|------|------|
| `/` | 对话：选 Agent、上传文件、看工具调用和慢思考 |
| `/agents` | 配置 Agent（模型、提示词、Skill、工具、Subagent、循环、上下文、头像和输入框快捷入口） |
| `/skills` | 查看已发现的 Skill |
| `/tools` | 管理 HTTP 检索等工具实例 |
| `/model` | 模型 CRUD、默认模型、utility 模型、价格与连通性测试 |
| `/dashboard` | 七步法企业分析看板，附商业八问 |
| `/observability` | Token 成本与执行链路 |

---

## 快速开始

### 前置要求

- Python 3.10+
- 一个 Anthropic API，或兼容 OpenAI Chat Completions 的 LLM

### 安装与启动

```bash
pip install -r requirements.txt
uvicorn investment_agent:app --reload --host 0.0.0.0 --port 8000
```

Windows 可用启动脚本。脚本会创建并激活 `.venv`，再拉起服务。依赖安装那一行目前是注释，新环境需要先在虚拟环境里执行上面的 `pip install`。

```bat
start.bat
start.bat --reload
start.bat --port 8000
```

浏览器打开 `http://127.0.0.1:8000`。

### 配置模型

打开 `/model`，填入显示名、模型名、API Key。两种接入：

- **Anthropic** — API Key 即可。工具调用更稳的模型更适合本项目。可填写缓存读取价和缓存创建价。
- **OpenAI Compatible** — 需要 Base URL 和 API Key，适用于 DeepSeek、Qwen、Ollama 等。

第一个模型会同时成为默认模型和 utility 模型。utility 模型用于生成会话标题。页面上可以测试连通性，也可以单独改默认模型或 utility 模型。单条消息还可以在对话里临时换模型，不改 Agent 绑定。

### 开始分析

在对话页输入请求，例如：

> 分析贵州茅台（600519）近三年的盈利能力变化趋势

也可以上传财报（`.txt` `.md` `.pdf` `.xlsx` `.xls` `.docx` `.doc`，单文件最大 100MB）。提取文本会截断到 5 万字符后进入上下文；完整年报分析更适合先下载并转成 Markdown，再走索引和结构化分析 Skill。

---

## 对话页

- **快捷 Agent** — 在 `/agents` 勾选「显示在输入框」的 Agent 会出现在输入框上方，按排序号排列。
- **斜杠命令** — 输入 `/` 后选择：`/clear` 新建对话，`/agent` 切换 Agent，`/model` 临时换模型，`/context` 切换上下文回放。也可直接输入 `/context chat` 或 `/context full`。
- **引用文件** — 输入 `@` 从 `data/` 目录补全路径，插入后的路径会带反引号。
- **上下文回放** — `chat`（可见对话）继续会话时只带回问题和回复；`full`（完整轨迹）连同工具调用和结果一起回放。模式记在会话上。
- **运行控制** — 流式输出可中断；失败后可重试。刷新页面时，仍在运行的任务可以重新接上 SSE。

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

两条完整财报路径不要混用：

| Skill | 怎么跑 |
|-------|--------|
| `full-financial-analysis` | 父 Agent 按公司、按年调用 `prepare_financial_reports` 准备 PDF、Markdown 和同级索引；分析交给 `analyze_financial_report`。多年需求由父 Agent 汇总各年报告 |
| `orch-full-financial-analysis` | 旧编排。每一步用 `DelegateTask` 委派，只依赖下载和转写；排雷改走 full-financial-analysis |

---

## 工作方式

一次对话由 `AgentRunner` 拉起。`loop_factory` 按 Agent 的 `loop_mode` 创建引擎，默认是双循环。每个会话有独立的工具和技能注册表。循环只决定推理节奏，不决定能不能改文件。

| 模式 | 行为 |
|------|------|
| `dual_loop` | 每步推理并调用工具；每隔若干步插入慢思考，复盘进度并纠偏 |
| `react` | 单循环推理，适合轻量工具调用 |

聊天窗口可以在「执行」和「规划」之间切换，状态记在会话的 `collaboration_mode` 上，下一条消息生效。规划轮只开放读取、检索和 `propose_plan`；计划写到 `data/plans/{session_id}.md`。用户批准后才切回执行，并按该文件自动跑一轮。

主循环有步数上限、token 预算、连续同工具调用检测，以及可中断的 SSE 流。长对话在开跑前按预算压缩系统提示词和历史消息；运行中可裁剪上下文，并把过长的工具结果卸载成摘要，原文留在 `data/.offload/`，需要时再用 `read_file` 读回。

Skill 正文按需加载，并按 `skill_body_ttl` 做内存缓存。系统提示词里先放技能名称和描述；模型调用 `Skill` 工具后，下一轮才能按正文执行。同一步里不要「加载说明并立刻按正文执行」。

Subagent 与父对话隔离：只拿任务说明和自己的工具集，结束后把文本结果交回父 Agent。同一轮可以并行发起多个互不依赖的子任务，默认最多 3 个。子 Agent 不能再挂 `DelegateTask`，也不能再挂其他 Subagent。默认定义在 `extensions/subagents/`，启动时补齐数据库里缺失的条目。挂到 Agent 上之后，它们会以独立工具的形式暴露给主模型。模型留空时继承主 Agent。

---

## 数据目录

业务文件都在 `data/`。财报流水线按股票代码分目录：

```
data/
├── agent.db                      # SQLite
├── uploads/                      # 对话上传
├── plans/                        # 会话规划文件
├── reports/<股票代码>/
│   ├── 1_pdf/                    # 下载的 PDF
│   ├── 2_markdown/               # PDF 转写结果
│   ├── 3_split/                  # 旧切割产物，当前流程不再写入
│   └── 4_output/                 # 分析报告
├── tmp/                          # 仅文件名写入时的默认位置
├── tmp/subagents/                # 子 Agent 工作区
└── .offload/                     # 上下文卸载的临时原文
```

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
│       ├── runner.py             # 一次对话的创建、执行、落库
│       ├── registry_container.py # 会话级工具与技能注册
│       ├── core/                 # 双循环、ReAct、Plan Execute、子 Agent、模型适配
│       ├── tools/                # 文件、脚本、shell、Skill、委派、HTTP 检索
│       ├── skills/               # Skill 加载、依赖展开、脚本执行、正文缓存
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

技能有两种类型：

| `type` | 作用 |
|--------|------|
| `atomic`（默认） | 一项具体能力，例如下载、转写、估值、排雷 |
| `orch` | 编排流程。用 `depends_on` 声明要展开的原子技能，由主 Agent 按正文调度 |

### 内置 Skill

| Skill | 作用 |
|-------|------|
| `a-share-stock-market` | 股票资料、历史行情、实时行情、指数 |
| `a-share-financial-data` | 利润表、资产负债表、现金流量表、估值与财务指标 |
| `a-share-valuation` | DCF、相对估值、周期股调整，输出前提显式的观察区间 |
| `industry-compare` | 同业关键指标对比，标出异常偏离 |
| `analyze-financial-report` | 年报索引定向排雷：R001–R038、必查覆盖、风险评级与三大前提 |
| `build-annual-report-index` | 为年报 Markdown 生成两级章节索引 |
| `download-a-share-reports` | 从巨潮、东方财富、新浪下载年报、半年报、季报 |
| `pdf-to-markdown` | PDF 转 Markdown（默认 pdfplumber，可切高质量模式） |
| `full-financial-analysis` | 下载 → 转写 → 建索引 → 单年分析；多年需求再汇总 |
| `orch-full-financial-analysis` | 旧编排：下载、转写；排雷已改走 full-financial-analysis |
| `demo_echo` / `demo_brief_report` | 调用链与多参数报告的演示技能 |

行情和财务报表数据来自 AKShare。

### 自定义 Skill

```yaml
---
name: my-skill
description: 一句话说明何时应该用它
type: atomic
depends_on: []
---
# 正文会在模型调用 Skill 工具时注入
```

`type` 省略时按原子技能处理。编排技能把 `type` 设为 `orch`，并在 `depends_on` 里列出要一起启用的原子技能名。脚本放在该技能的 `scripts/` 下。参数以 CLI 旗标传入，也可从 stdin 读 JSON。

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

路径访问受策略约束：业务上限制敏感目录，写文件落在 `data/`。检索实例保存后，连通性测试请求的是 `{base_url}/health`。

---

## 默认 Subagent

| 名称 | 作用 |
|------|------|
| `analyze_financial_report` | 对指定年报 Markdown 做最小必要阅读和可复核的排雷分析 |
| `prepare_financial_reports` | 只处理一家公司的一个年份：核对约定路径下的年报 PDF、Markdown 和同级索引，缺则补齐；孤立索引在补完 Markdown 后覆盖重建 |

在 `/agents` 的「Subagent 定义」里可以新建。写清 `description`（主模型靠它决定何时调用）、允许的 `tools` / `skills`，以及可选的 token 与裁剪覆盖。

---

## 配置

全局参数在 `investment_agent/settings.json`。模型密钥存在 SQLite `models` 表，不写进这个文件。单个 Agent 可以在页面上覆盖引擎和上下文参数；Agent 显式填写的值优先于全局配置。

```json
{
  "engine": {
    "max_steps": 30,
    "slow_think_interval": 5,
    "token_budget": 100000,
    "subagent_token_budget": 100000,
    "subagent": {
      "token_budget": 100000
    },
    "loop_detection_threshold": 3,
    "skill_body_ttl": 600,
    "context_trim_token_threshold": 90000,
    "max_subagent_depth": 3,
    "offload_threshold": 800,
    "offload_summary_strategy": "truncate",
    "offload_summary_chars": 200
  },
  "context": {
    "model_max_tokens": null,
    "safety_margin": 0.10,
    "max_chars_per_msg": 2000,
    "budget": {
      "system_max_tokens": 40000,
      "tools_max_tokens": 20000,
      "messages_max_tokens": null
    }
  },
  "skills": { "directory": "./extensions/skills" },
  "subagents": { "directory": "./extensions/subagents" },
  "db": { "type": "sqlite", "sqlite_path": "./data/agent.db" },
  "file_browser": {
    "include": [],
    "exclude": [".gitkeep", "agent.db"]
  }
}
```

| 参数 | 含义 |
|------|------|
| `max_steps` | 单次任务最大步数 |
| `slow_think_interval` | 双循环下每隔多少步做一次慢思考 |
| `token_budget` | 主 Agent token 上限 |
| `subagent_token_budget` | 子 Agent 默认 token 上限；`engine.subagent.token_budget` 是同一额度的嵌套写法 |
| `loop_detection_threshold` | 连续相同工具调用达到该次数后中止 |
| `skill_body_ttl` | Skill 正文内存缓存秒数，过期后下次读取再加载 |
| `context_trim_token_threshold` | 运行中开始裁剪上下文的 token 水位 |
| `max_subagent_depth` | 委派最大层数，`0` 表示不允许创建子 Agent |
| `offload_threshold` | 工具结果超过该字符数后卸载为摘要 |
| `model_max_tokens` | 上下文预算使用的模型窗口；`null` 时走程序内默认值 |
| `messages_max_tokens` | 历史消息预算上限；`null` 时按窗口扣除系统和工具预算后计算 |
| `file_browser.include` | 对话页 `data/` 文件树白名单，路径相对 `data/`、用 `/`。空数组表示不限制。非空时只展示这些路径：写目录则包含其下全部内容；写到更深路径时，上级目录仍显示，否则无法点进去。例如 `["reports/600519"]` 时根目录可见 `reports`，其下只有 `600519`，再往下全部可见 |
| `file_browser.exclude` | 文件树黑名单。不含 `/` 的名字按文件名匹配任意层级，命中目录时连同其下内容一起隐藏（默认 `.gitkeep`、`agent.db`；`tmp` 会隐藏各级名为 `tmp` 的目录）。含 `/` 时按从 `data/` 起的路径前缀匹配，例如 `plans/old.md` 只隐藏该文件，`reports/600519` 隐藏该目录及其下内容。与 include 同时配置时，先按 include 收窄，再去掉 exclude。不支持通配符。缺省整段 `file_browser` 时仍排除 `.gitkeep` 和 `agent.db`。只影响 `/api/files/tree` 与 `/api/files/children`（左侧文件树和 `@` 文件列表），不拦截 `/api/files/view` |

下面几项未写进当前 `settings.json`，省略时使用括号中的默认值，也可以写进 `engine` 或单个 Agent 的引擎配置：

| 参数 | 默认 | 含义 |
|------|------|------|
| `runtime_context_compression_enabled` | `true` | 是否在运行中裁剪上下文 |
| `max_parallel_subagents` | `3` | 同一轮并行子任务上限 |
| `planning_max_tokens` | `1024` | 生成委派指令时的单轮输出上限 |
| `subagent_workspace_dir` | `data/tmp/subagents` | 子 Agent 工作目录 |

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
  PATCH  /api/sessions/{id}/context        设置回放模式：chat 或 full
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

在 `agent/tools/` 继承 `BaseTool`，实现 `name`、`description`、`schema` 和 `async run()`，再在 `AgentRegistry.bootstrap_default_tools()` 里登记。外部 HTTP 能力优先用工具页的检索模板配实例，而不是再写一个专用客户端。

### 加一个子 Agent

在 `extensions/subagents/` 放一份带 YAML frontmatter 的 Markdown，或在 `/agents` 页面创建。写清 `description`、允许的 `tools` / `skills`，以及可选的 token 与裁剪覆盖。

---

## 后续方向

已有上下文压缩、Plan Execute 和 `search_text`。还没做的方向：

- 接入 MCP，让 Agent 使用浏览器
- 跨会话记忆
- 根据使用情况进化 Skill
- `find_skills` / skill 投票
- search_tools

---

## 许可证

MIT
