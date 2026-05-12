# 投研分析 Agent

基于 Agent Harness 架构的 A 股投研分析 Web 服务。用户通过浏览器与 Agent 交互，支持文件上传（PDF/Word/Excel），Agent 自主调用工具完成基本面分析，支持 Skill 插件扩展，输出 Markdown 研报。

---

## 快速开始

```bash
# 安装依赖
pip install -r requirements.txt

# 启动服务
uvicorn investment_agent:app --reload --port 8000
```

启动后访问 `http://localhost:8000`，先到「设置」页配置模型（填入 API Key 等信息），然后在对话页输入分析请求即可。对话支持上传 PDF、Word、Excel 等文件作为分析材料。

---

## 项目结构

```
investment_agent/
├── __init__.py
├── main.py                  # FastAPI 入口，路由注册，DB 初始化
├── config.py                # settings.json 读写（带缓存）
├── settings.json            # 引擎/压缩/Skills 配置（API Key 存 DB）
│
├── app/                     # 应用层（接口/静态资源/观测/持久化）
│   ├── __init__.py
│   ├── db.py                # SQLite 初始化与访问（7 张表）
│   ├── api/                 # FastAPI 路由
│   │   ├── chat.py          # 对话接口（SSE 流式 + 文件上传）
│   │   ├── sessions.py      # 会话管理
│   │   ├── agents.py        # Agent 配置管理
│   │   ├── skills.py        # Skills 列表
│   │   ├── observability.py # 观测数据接口
│   │   └── settings.py      # 配置读写 + 模型 CRUD
│   ├── observability/       # 成本与链路追踪
│   │   ├── cost_tracker.py  # Token 成本日志
│   │   └── trace.py         # 执行链路日志
│   └── static/              # 前端（原生 HTML/JS）
│       ├── index.html       # 主对话页
│       ├── agents.html      # Agent 配置页
│       ├── skills.html      # Skills 页
│       ├── settings.html    # 系统设置页
│       ├── history.html     # 历史会话页
│       ├── observability.html
│       ├── css/
│       │   ├── main.css
│       │   └── settings.css
│       └── js/
│           ├── chat.js      # SSE 流式接收 + Markdown 渲染
│           ├── agents.js    # Agent 配置逻辑
│           ├── skills.js    # Skills 页逻辑
│           ├── settings.js  # 设置页逻辑
│           ├── settings2.js # 模型管理逻辑
│           └── observability.js
│
├── agent/                   # 执行层（上下文/引擎/技能/工具）
│   ├── __init__.py
│   ├── context/
│   │   └── compressor.py    # 上下文分级压缩
│   ├── core/
│   │   ├── engine.py        # 双循环执行引擎
│   │   ├── models.py        # 多模型抽象层
│   │   └── session.py       # 并发任务隔离
│   ├── skills/              # Skill 插件系统
│   │   ├── base.py          # Skill 基类
│   │   ├── loader.py        # Skill 发现与注册
│   │   ├── markdown_parser.py
│   │   ├── markdown_skill.py
│   │   └── script_runner.py
│   └── tools/
│       ├── base.py          # Tool 基类
│       ├── registry.py      # Tool 注册中心
│       ├── market_data.py   # 行情数据工具（4 个）
│       ├── financials.py    # 财务数据工具（5 个）
│       └── run_command.py   # Shell 命令执行工具
│
├── extensions/skills/       # Skill 定义文件（SKILL.md）
│   ├── demo_echo/
│   ├── demo_brief_report/
│   ├── download-a-share-reports/
│   ├── pdf-to-markdown/
│   └── a-share-financial-forensic/
│
├── utils/
│   └── pdf_util.py          # PDF 转 Markdown 工具
│
├── data/                    # 运行时数据（SQLite 数据库等）
└── output/                  # 输出目录（自动创建）
    ├── reports/             # 导出的 Markdown 研报
    └── charts/              # 生成的图表
```

---

## 核心模块说明

### 执行引擎（agent/core/engine.py）

实现双循环架构：

- **快执行循环**：每步执行 LLM 推理 → 工具调用 → 结果追加
- **慢思考循环**：每 N 步（默认 3 步）触发一次全局复盘，让模型评估进度、调整策略

内置安全机制：
- **最大步数限制**：防止无限循环（默认 30 步）
- **死循环检测**：连续 N 次调用相同工具自动停止（默认阈值 3）
- **Token 预算**：单次任务超出预算自动中止（默认 100,000 tokens）
- **优雅中断**：通过 `asyncio.Event` 支持用户随时停止任务

### 多模型抽象层（agent/core/models.py）

统一 `ModelProvider` 接口，支持两种类型：

- **Anthropic**：Claude 系列（claude-sonnet-4-6 等），工具调用能力强，推荐用于复杂分析
- **OpenAI Compat**：OpenAI、DeepSeek、Qwen、Ollama 等兼容接口

模型配置存储在 SQLite `models` 表中，通过 Web UI 或 API 进行 CRUD 管理，支持设置默认模型和连接测试。

### 工具系统（agent/tools/）

所有工具按风险等级分类：

**行情数据工具（market_data.py）— L0 只读**
- `get_stock_info` — 股票基本信息（名称、行业、市值等）
- `get_stock_price` — 历史 K 线数据（日/周/月，前复权）
- `get_stock_realtime` — 实时行情（价格、涨跌幅、成交量）
- `get_market_index` — 主要指数行情（上证、深证、创业板）

**财务数据工具（financials.py）— L0 只读**
- `get_income_statement` — 利润表（营收、净利润等）
- `get_balance_sheet` — 资产负债表
- `get_cash_flow` — 现金流量表
- `get_valuation` — 估值指标（PE、PB、PS、股息率）
- `get_financial_indicators` — 核心财务指标（ROE、ROA、毛利率等）

**Shell 工具（run_command.py）— L2**
- `run_command` — 在项目根目录执行 shell 命令（运行脚本、下载文件等）

数据来源：AKShare（免费，覆盖全 A 股）

### 并发任务隔离（agent/core/session.py）

每个任务分配独立的 `AgentEngine` 实例，通过 `task_id → engine` 字典管理，避免多用户并发时上下文互相干扰。

### Skill 插件系统（agent/skills/）

通过 `SKILL.md` 文件（YAML frontmatter + Markdown 正文）定义技能，自动从配置目录发现和加载。Skill 可声明 Python 入口脚本，通过子进程执行。当前已包含 5 个 Skill：

| Skill | 功能 |
|-------|------|
| `demo_echo` | 回显参数，用于验证 Skill 链路 |
| `demo_brief_report` | 根据参数生成简短结构化报告 |
| `download-a-share-reports` | 从 cninfo.com.cn 下载 A 股年报 |
| `pdf-to-markdown` | 通过 docling 将 PDF 转为 Markdown |
| `a-share-financial-forensic` | A 股财务造假识别（38 条规则检查） |

### 上下文压缩（agent/context/compressor.py）

降低长对话的 Token 消耗：

- 保留最近 N 条消息原文（默认 20 条）
- 旧消息截断至最大字符数（默认 2000 字符）
- 总字符预算控制（默认 100,000 字符）

### 文件上传

对话支持上传文件，自动解析内容注入上下文：

- 支持格式：`.txt`、`.md`、`.pdf`、`.xlsx`、`.xls`、`.docx`、`.doc`
- 最大文件：10 MB，提取文本上限 50,000 字符
- PDF 解析使用 pdfplumber，Office 文档使用 openpyxl/xlrd/python-docx

---

## API 接口

### 对话

```
POST   /api/chat                      # 发起分析任务（支持 multipart 文件上传），返回 task_id
GET    /api/chat/{task_id}/stream     # SSE 流式获取执行过程
POST   /api/chat/{task_id}/interrupt  # 中断正在执行的任务
```

**SSE 事件格式：**

```json
{"type": "text_delta",  "content": "正在分析..."}
{"type": "tool_call",   "tool": "get_stock_info", "input": {"symbol": "600519"}}
{"type": "tool_result", "tool": "get_stock_info", "output": "..."}
{"type": "slow_think",  "content": "当前进度符合目标，继续执行..."}
{"type": "done",        "usage": {"input_tokens": 1200, "output_tokens": 800}}
{"type": "error",       "message": "..."}
{"type": "interrupted"}
```

### 会话管理

```
GET    /api/sessions          # 历史会话列表
GET    /api/sessions/{id}     # 会话详情 + 消息记录
DELETE /api/sessions/{id}     # 删除会话
```

### Agent 配置

```
GET    /api/agents            # Agent 列表
POST   /api/agents            # 创建 Agent
GET    /api/agents/{id}       # Agent 详情
PUT    /api/agents/{id}       # 更新 Agent
DELETE /api/agents/{id}       # 删除 Agent
```

### 系统设置

```
GET    /api/settings                    # 读取引擎/压缩/Skills/Tools 配置
PUT    /api/settings/engine             # 更新引擎参数
PUT    /api/settings/compress           # 更新压缩参数
PUT    /api/settings/skills             # 更新 Skills 目录（触发重载）
PUT    /api/settings/tools              # 更新 Tushare token
GET    /api/settings/models             # 模型列表（API Key 脱敏）
POST   /api/settings/models             # 添加模型
PUT    /api/settings/models/default     # 设置默认模型
PUT    /api/settings/models/{id}        # 更新模型
DELETE /api/settings/models/{id}        # 删除模型
POST   /api/settings/models/test        # 测试模型连接
```

### Skills

```
GET    /api/skills           # 所有已发现的 Skill 列表
```

### 观测数据

```
GET    /api/observability/cost     # Token 成本日志
GET    /api/observability/traces   # 执行链路追踪
```

### 健康检查

```
GET    /health               # 服务健康状态
```

---

## 前端页面

| 页面 | 路径 | 功能 |
|------|------|------|
| 主对话页 | `/` | SSE 流式对话，文件上传，工具调用步骤可见，慢思考展示，Token 用量统计 |
| Agent 配置 | `/agents` | 创建/编辑/删除自定义 Agent，配置系统提示词、模型、Skills 和压缩参数 |
| Skills | `/skills` | 查看所有已发现 Skill 及其参数 Schema |
| 系统设置 | `/settings` | 管理模型（CRUD + 连接测试）、引擎参数、压缩配置、Skills 目录 |
| 历史会话 | `/history` | 查看和管理历史对话记录 |
| 观测数据 | `/observability` | Token 成本日志和执行链路追踪表格 |

---

## 数据库结构（SQLite）

```sql
models       -- LLM 模型配置（名称、类型、API Key、endpoint、是否默认）
agents       -- Agent 配置（名称、系统提示词、关联模型、Skills、压缩参数）
sessions     -- 会话记录（关联 agent_id，状态）
messages     -- 消息记录（role/content/tool_calls/token_usage）
checkpoints  -- 断点续跑状态
cost_log     -- Token 成本日志
trace_log    -- 执行链路追踪日志
```

---

## 配置说明（settings.json）

```json
{
  "engine": {
    "max_steps": 30,
    "slow_think_interval": 3,
    "token_budget": 100000,
    "loop_detection_threshold": 3
  },
  "compress": {
    "enabled": true,
    "recent_keep": 20,
    "max_chars_per_msg": 2000,
    "total_budget_chars": 100000
  },
  "skills": {
    "directory": "./extensions/skills"
  },
  "tools": {
    "tushare_token": ""
  },
  "database": {
    "type": "sqlite",
    "sqlite_path": "./data/agent.db"
  }
}
```

模型（API Key、endpoint）在数据库 `models` 表中管理，通过设置页 UI 或 API 配置。

---

## 开发路线图

### Phase 1 — 核心跑通 ✅
- FastAPI 基础结构 + 7 个前端页面
- 多模型抽象层（Anthropic + OpenAI Compat，DB 管理）
- AKShare 行情 + 财务工具 + Shell 工具（10 个工具）
- 双循环执行引擎（含死循环检测、Token 预算、中断）
- SSE 流式输出 + 文件上传（PDF/Word/Excel）
- Agent 配置管理
- Skill 插件系统（5 个 Skill）
- 上下文分级压缩
- Token 成本追踪 + 执行链路日志

### Phase 2 — 工程化
- 断点续跑（SQLite 持久化每步状态）
- AKShare 请求缓存（避免重复拉取）
- 工具结果持久化缓存

### Phase 3 — 专业化
- 多 Agent 协作（基本面 + 宏观 + 研报生成）
- 知识库（ChromaDB + 知识编译，幻觉率 < 5%）
- 完整 Markdown 研报导出 + 图表生成
- 更多专业 Skill（估值分析、行业对比等）

---

## 依赖

```
fastapi / uvicorn        — Web 框架
anthropic                — Claude SDK
openai                   — OpenAI / DeepSeek / 兼容接口 SDK
aiosqlite                — 异步 SQLite
akshare                  — A 股数据
sse-starlette            — SSE 流式响应
python-multipart         — 文件上传解析
pdfplumber               — PDF 文本提取
python-docx              — Word 文档解析
openpyxl / xlrd          — Excel 文档解析
docling                  — PDF 转 Markdown
markdown                 — Markdown 处理
httpx                    — HTTP 客户端
aiofiles                 — 异步文件操作
pydantic / pydantic-settings — 数据验证与配置
matplotlib / mplfinance  — 图表生成
```
