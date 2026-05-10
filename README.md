# 投研分析 Agent

基于 Agent Harness 架构的 A 股投研分析 Web 服务。用户通过浏览器与 Agent 交互，Agent 自主调用工具完成基本面分析，输出 Markdown 研报。

---

## 快速开始

```bash
# 安装依赖
pip install -r requirements.txt

# 启动服务
uvicorn investment_agent:app --reload --port 8000
```

启动后访问 `http://localhost:8000`，先到「设置」页填入 API Key，然后在对话页输入分析请求即可。

---

## 项目结构

```
investment_agent/
├── main.py                  # FastAPI 入口，路由注册，DB 初始化
├── config.py                # settings.json 读写（带缓存）
├── settings.json            # 用户配置（模型、API Key、引擎参数）
├── requirements.txt
│
├── core/                    # 第一层：核心执行引擎
│   ├── engine.py            # 双循环执行引擎
│   ├── models.py            # 多模型抽象层
│   └── session.py           # 并发任务隔离
│
├── tools/                   # 第二层：工具系统
│   ├── base.py              # 工具基类
│   ├── registry.py          # 工具注册表
│   ├── market_data.py       # 行情数据工具（AKShare）
│   └── financials.py        # 财务数据工具（AKShare）
│
├── api/                     # FastAPI 路由
│   ├── chat.py              # 对话接口（SSE 流式）
│   ├── sessions.py          # 会话管理
│   ├── agents.py            # Agent 配置管理
│   └── settings.py          # 配置读写
│
├── static/                  # 前端（原生 HTML/JS）
│   ├── index.html           # 主对话页
│   ├── agents.html          # Agent 配置页
│   ├── settings.html        # 系统设置页
│   ├── history.html         # 历史会话页
│   ├── css/main.css
│   └── js/
│       ├── chat.js          # SSE 流式接收 + Markdown 渲染
│       ├── agents.js        # Agent 配置逻辑
│       └── settings.js      # 设置页逻辑
│
└── output/                  # 输出目录（自动创建）
    ├── reports/             # 导出的 Markdown 研报
    └── charts/              # 生成的图表
```

---

## 核心模块说明

### 执行引擎（core/engine.py）

实现双循环架构：

- **快执行循环**：每步执行 LLM 推理 → 工具调用 → 结果追加
- **慢思考循环**：每 N 步（默认 3 步）触发一次全局复盘，让模型评估进度、调整策略

内置安全机制：
- **最大步数限制**：防止无限循环（默认 30 步）
- **死循环检测**：连续 N 次调用相同工具自动停止（默认阈值 3）
- **Token 预算**：单次任务超出预算自动中止（默认 100,000 tokens）
- **优雅中断**：通过 `asyncio.Event` 支持用户随时停止任务

### 多模型抽象层（core/models.py）

统一接口，底层可切换：

| Provider | 模型 | 说明 |
|----------|------|------|
| Claude | claude-sonnet-4-6（默认） | 工具调用能力强，推荐用于复杂分析 |
| DeepSeek | deepseek-chat | 成本低，适合简单任务 |
| OpenAI | gpt-4o | 备选 |

路由规则在 `settings.json` 中配置，支持按任务复杂度自动选择模型。

### 工具系统（tools/）

所有工具按风险等级分类，当前实现均为 L0（只读，无副作用）：

**行情数据工具（market_data.py）**
- `get_stock_info` — 股票基本信息（名称、行业、市值等）
- `get_stock_price` — 历史 K 线数据（日/周/月）
- `get_stock_realtime` — 实时行情（价格、涨跌幅、成交量）
- `get_market_index` — 主要指数行情（上证、深证、创业板）

**财务数据工具（financials.py）**
- `get_income_statement` — 利润表（营收、净利润等）
- `get_balance_sheet` — 资产负债表
- `get_cash_flow` — 现金流量表
- `get_valuation` — 估值指标（PE、PB、PS、股息率）
- `get_financial_indicators` — 核心财务指标（ROE、ROA、毛利率等）

数据来源：AKShare（免费，覆盖全 A 股）

### 并发任务隔离（core/session.py）

每个任务分配独立的 `AgentEngine` 实例，通过 `task_id → engine` 字典管理，避免多用户并发时上下文互相干扰。

---

## API 接口

### 对话

```
POST   /api/chat                      # 发起分析任务，返回 task_id
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
GET    /api/settings          # 读取配置（API Key 脱敏）
PUT    /api/settings          # 更新配置
```

---

## 前端页面

| 页面 | 路径 | 功能 |
|------|------|------|
| 主对话页 | `/` | SSE 流式对话，工具调用步骤可见，慢思考展示，Token 用量统计 |
| Agent 配置 | `/agents` | 创建/编辑/删除自定义 Agent，配置系统提示词和模型参数 |
| 系统设置 | `/settings` | 配置 API Key、模型选择、引擎参数 |
| 历史会话 | `/history` | 查看和管理历史对话记录 |

---

## 数据库结构（SQLite）

```sql
agents       -- Agent 配置（名称、系统提示词、模型参数）
sessions     -- 会话记录（关联 agent_id，状态）
messages     -- 消息记录（role/content/tool_calls/token_usage）
checkpoints  -- 断点续跑状态（Phase 2 启用）
cost_log     -- Token 成本日志（Phase 2 启用）
```

---

## 配置说明（settings.json）

```json
{
  "models": {
    "default_provider": "claude",
    "providers": {
      "claude":   {"api_key": "", "model": "claude-sonnet-4-6"},
      "deepseek": {"api_key": "", "model": "deepseek-chat"},
      "openai":   {"api_key": "", "model": "gpt-4o"}
    }
  },
  "engine": {
    "max_steps": 30,
    "slow_think_interval": 3,
    "token_budget": 100000,
    "loop_detection_threshold": 3
  },
  "tools": {
    "tushare_token": ""
  },
  "output": {
    "report_dir": "./output/reports",
    "chart_dir": "./output/charts"
  }
}
```

---

## 开发路线图

### Phase 1 — 核心跑通 ✅
- FastAPI 基础结构
- 多模型抽象层（Claude/DeepSeek/OpenAI）
- AKShare 行情 + 财务工具（9个工具）
- 双循环执行引擎（含死循环检测、Token 预算、中断）
- SSE 流式输出
- Agent 配置管理
- 基础 Web UI（4个页面）

### Phase 2 — 工程化
- 断点续跑（SQLite 持久化每步状态）
- 上下文分级压缩（降低 Token 消耗 40-50%）
- Token 成本追踪 + 执行链路日志
- AKShare 请求缓存（避免重复拉取）

### Phase 3 — 专业化
- Skill 插件系统（估值分析、行业对比等）
- 多 Agent 协作（基本面 + 宏观 + 研报生成）
- 知识库（ChromaDB + 知识编译，幻觉率 < 5%）
- 本地 PDF 年报解析
- 完整 Markdown 研报导出

---

## 依赖

```
fastapi / uvicorn     — Web 框架
anthropic             — Claude SDK
openai                — OpenAI/DeepSeek SDK
aiosqlite             — 异步 SQLite
akshare               — A 股数据
sse-starlette         — SSE 流式响应
pdfplumber            — PDF 解析（Phase 3）
python-docx           — Word 解析（Phase 3）
matplotlib            — 图表生成（Phase 3）
```
