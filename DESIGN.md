# 投研分析 Agent Harness — 完整设计方案

## 一、项目定位

基于 Agent Harness 架构，构建一个面向 A 股市场的投研分析 Web 服务。
用户通过浏览器与 Agent 交互，Agent 自主调用工具完成基本面分析，输出 Markdown 研报。

---

## 二、技术选型

| 模块 | 选型 | 理由 |
|------|------|------|
| Web 框架 | FastAPI + Uvicorn | 异步支持好，SSE 流式输出方便 |
| 前端 | 原生 HTML/JS | 零构建，FastAPI 直接 serve |
| 数据库 | SQLite（aiosqlite） | 个人工具，零运维 |
| 向量库 | ChromaDB（本地） | 本地运行，无需外部服务 |
| 行情数据 | AKShare | A股免费数据，覆盖全 |
| 财务数据 | AKShare + Tushare | 三张表、估值指标 |
| LLM SDK | Anthropic SDK（主） + 抽象层 | 可切换 DeepSeek/OpenAI |
| 文档解析 | pdfplumber + python-docx | 解析年报/研报 PDF/Word |
| 图表 | matplotlib + mplfinance | 本地生成，返回 base64 |

---

## 三、项目结构

```
investment_agent/
├── main.py                    # FastAPI 入口
├── config.py                  # 全局配置（从 settings.json 读取）
├── settings.json              # 用户可配置项（模型、API Key、参数）
│
├── core/                      # 第一层：核心执行引擎
│   ├── engine.py              # 双循环执行引擎（快执行 + 慢思考）
│   ├── models.py              # 多模型抽象层（统一接口）
│   ├── checkpoint.py          # 断点续跑（SQLite 持久化）
│   └── session.py             # 会话生命周期管理 + 并发任务隔离
│
├── tools/                     # 第二层：工具系统
│   ├── registry.py            # 工具注册表 + 风险分级
│   ├── base.py                # 工具基类
│   ├── market_data.py         # L0: 行情数据（AKShare，含缓存）
│   ├── financials.py          # L0: 财务报表（三张表、估值，含缓存）
│   ├── news.py                # L0: 新闻/公告/研报摘要
│   ├── web_search.py          # L0: 网页搜索
│   ├── document.py            # L0: 本地文档解析（PDF/Word）
│   ├── chart.py               # L1: 图表生成
│   └── report.py              # L1: 研报导出（Markdown 文件）
│
├── context/                   # 第三层：上下文工程
│   └── compressor.py          # 分级压缩（L0保留/L1轻压/L2重压/L3删除）
│
├── memory/                    # 第四层：记忆系统
│   ├── short_term.py          # L1 短期：当前会话上下文（内存）
│   ├── mid_term.py            # L2 中期：研究笔记（SQLite）
│   └── knowledge.py           # L3 长期：公司/行业知识库（ChromaDB）
│
├── decision/                  # 第五层：自主决策引擎
│   ├── planner.py             # 目标拆解（Vision→Goal→Task→Action）
│   ├── opea.py                # OPEA 循环（Observe-Plan-Execute-Reflect）
│   └── safety.py              # 三道安全防线
│
├── agents/                    # 第六层：多 Agent 协作
│   ├── orchestrator.py        # 任务分配（拍卖机制）+ 结果汇总
│   ├── fundamental.py         # 基本面分析 Agent（内部跑 OPEA 循环）
│   ├── technical.py           # 技术面分析 Agent（可选）
│   ├── macro.py               # 宏观/行业分析 Agent（内部跑 OPEA 循环）
│   └── report_writer.py       # 研报生成 Agent（内部跑 OPEA 循环）
│
├── skills/                    # Skill 插件系统
│   ├── loader.py              # 动态加载 skill（扫描 skills/ 目录）
│   ├── base.py                # Skill 基类（定义接口规范）
│   └── builtin/               # 内置 skill 示例
│       ├── valuation.py       # 估值分析 skill（PE/PB/DCF）
│       └── industry_compare.py # 行业对比 skill
│
├── observability/             # 可观测性
│   ├── cost_tracker.py        # Token 成本追踪
│   ├── trace.py               # 全链路执行追踪
│   └── metrics.py             # 核心指标（成功率/耗时/成本）
│
├── api/                       # FastAPI 路由
│   ├── agents.py              # Agent 配置 CRUD
│   ├── chat.py                # POST /chat, GET /chat/stream（SSE），POST /chat/{task_id}/interrupt
│   ├── sessions.py            # 会话管理 CRUD
│   ├── settings.py            # 配置读写
│   ├── skills.py              # Skill 列表/启用/禁用
│   ├── knowledge.py           # 知识库管理（上传/查询，含文件校验）
│   └── observability.py       # 成本/日志查询
│
├── output/                    # 输出目录（研报、图表）
│   ├── reports/               # 导出的 Markdown 研报
│   └── charts/                # 生成的图表文件
│
└── static/                    # 前端（纯 HTML/JS）
    ├── index.html             # 主聊天界面
    ├── agents.html            # Agent 配置页（新增）
    ├── settings.html          # 配置页（模型/API Key/参数）
    ├── skills.html            # Skill 管理页
    ├── knowledge.html         # 知识库管理页
    ├── history.html           # 历史会话 + 研报列表
    └── js/
        ├── chat.js            # SSE 流式接收 + Markdown 渲染
        ├── settings.js        # 配置表单
        └── common.js          # 公共工具函数
```

---

## 四、核心模块设计

### 4.1 双循环执行引擎（core/engine.py）

```
快执行循环（每步）：
  LLM 推理 → 工具调用 → 结果追加 → 下一步

慢思考循环（每3步 或 遇到错误）：
  检查进度 → 评估策略 → 是否偏离目标 → 是否需要人工介入
```

关键机制：
- 最大步数限制（默认 30 步，可配置）
- 死循环检测（连续 3 次相同工具调用 → 强制停止）
- 每步完成后持久化状态到 SQLite（断点续跑）
- 支持 SSE 流式推送每步进度到前端
- 每个 task_id 对应独立引擎实例，避免并发干扰
- 支持通过 `asyncio.Event` 优雅中断

### 4.2 多模型抽象层（core/models.py）

```python
# 统一接口，底层可切换
class ModelProvider:
    async def chat(messages, tools) -> Response

# 实现
class ClaudeProvider(ModelProvider): ...
class DeepSeekProvider(ModelProvider): ...
class OpenAIProvider(ModelProvider): ...
```

路由规则（settings.json 可配置）：
- 默认：Claude Sonnet 4.6（支持 prompt caching）
- 简单任务（单工具调用）：DeepSeek（降成本）
- 敏感数据：本地模型（可选）

### 4.3 Agent 配置（api/agents.py）

用户可在 `agents.html` 页面自定义 Agent：
- 名称、描述
- 系统提示词（自定义）
- 启用的 Skill 列表
- 绑定的模型和参数（覆盖全局默认值）

数据库 `agents` 表结构：
```sql
CREATE TABLE agents (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    description TEXT,
    system_prompt TEXT,
    model_provider TEXT,
    model_name  TEXT,
    temperature REAL DEFAULT 0.7,
    max_tokens  INTEGER DEFAULT 4096,
    skills      TEXT,   -- JSON 数组
    created_at  TEXT,
    updated_at  TEXT
);
```

### 4.4 任务中断机制（api/chat.py）

SSE 是单向推送，中断通过独立接口实现：

```
POST /api/chat/{task_id}/interrupt
```

引擎内部用 `asyncio.Event` 监听中断信号，当前工具调用完成后优雅退出，不强杀进程。

### 4.5 Skill 插件系统（skills/）

Skill 是对多个工具的高层封装，代表一种分析能力。

```python
# skills/base.py
class BaseSkill:
    name: str           # skill 唯一标识
    description: str    # 给 LLM 看的描述
    tools: list[str]    # 依赖的底层工具列表

    async def run(self, params: dict) -> str: ...
```

加载机制：
- 启动时扫描 `skills/` 目录，自动注册所有 Skill
- Web UI 可以启用/禁用单个 Skill
- Skill 的 `description` 和 `tools` 自动注入到 Agent 的系统提示词

### 4.6 上下文压缩（context/compressor.py）

每条消息打分（0-100），按分级处理：

| 分数 | 处理 | 场景 |
|------|------|------|
| 100+ | 原文保留 | 系统提示、最近3条消息、工具错误 |
| 70-100 | 轻度压缩 | 工具返回的数据摘要 |
| 30-70 | 重度压缩 | 早期分析过程 |
| <30 | 删除 | 重复信息、无关内容 |

目标：Token 消耗降低 40-50%。

### 4.7 知识编译（memory/knowledge.py）

写入流程（年报/研报上传时）：
```
原始文档 → 文本提取 → LLM 生成结构化知识单元 → 冲突检测 → 存入 ChromaDB
```

知识单元结构：
```json
{
  "id": "K-AAAA-001",
  "company": "贵州茅台",
  "category": "财务指标",
  "question": "2023年净利润是多少？",
  "answer": "2023年净利润为747亿元，同比增长19.2%",
  "source": "2023年年报第45页",
  "confidence": 0.97,
  "tags": ["利润", "2023", "白酒"]
}
```

上传限制：单文件最大 50MB，仅支持 PDF / Word / TXT 格式。

### 4.8 多 Agent 协作层级（agents/）

```
orchestrator.py              ← 任务拍卖、分配、结果汇总
    ├── fundamental.py       ← 内部跑 OPEA 循环
    ├── macro.py             ← 内部跑 OPEA 循环
    └── report_writer.py     ← 内部跑 OPEA 循环
```

协作机制：
- 任务拍卖：子 Agent 自评能力分，得分最高者接单
- 投票决策：多 Agent 意见不一致时少数服从多数
- 仲裁机制：两方僵持时引入第三方 Agent 裁决

### 4.9 安全防线（decision/safety.py）

三道防线：
1. **硬编码规则**：禁止 `output/` 目录以外的文件写操作，路径安全校验防止目录穿越
2. **语义检查**：LLM 判断工具调用意图，中风险以上需人工确认
3. **成本熔断**：单次任务 Token 超过预算阈值自动停止（settings.json 可配置）

### 4.10 数据缓存（tools/market_data.py, tools/financials.py）

AKShare / Tushare 接口有频率限制，财务数据变化慢，需本地缓存：
- 行情数据：缓存 1 小时
- 财务报表：缓存 24 小时
- 缓存存储：SQLite `cache` 表，按 `(tool, params_hash)` 索引

---

## 五、API 设计

```
# Agent 配置
GET    /api/agents                        # Agent 列表
POST   /api/agents                        # 创建 Agent
PUT    /api/agents/{id}                   # 更新 Agent
DELETE /api/agents/{id}                   # 删除 Agent

# 对话
POST   /api/chat                          # 发起分析任务（返回 task_id）
GET    /api/chat/{task_id}/stream         # SSE 流式获取执行过程
POST   /api/chat/{task_id}/interrupt      # 中断任务

# 会话
GET    /api/sessions                      # 历史会话列表
GET    /api/sessions/{id}                 # 会话详情 + 研报内容

# 配置
GET    /api/settings                      # 读取配置
PUT    /api/settings                      # 更新配置

# Skill
GET    /api/skills                        # Skill 列表（含启用状态）
PUT    /api/skills/{name}                 # 启用/禁用 Skill

# 知识库
POST   /api/knowledge/upload              # 上传文档（触发知识编译）
GET    /api/knowledge/search              # 知识库搜索

# 可观测性
GET    /api/observability/cost            # 成本统计
GET    /api/observability/traces          # 执行链路

# 健康检查
GET    /health                            # 服务状态
```

### SSE 事件格式

```json
{"type": "text_delta",   "content": "正在分析贵州茅台..."}
{"type": "tool_call",    "tool": "get_financials", "input": {"code": "600519"}}
{"type": "tool_result",  "tool": "get_financials", "output": "净利润 747亿..."}
{"type": "slow_think",   "content": "策略复盘：当前进度 60%，继续执行"}
{"type": "done",         "usage": {"input_tokens": 5000, "output_tokens": 1200, "cost_usd": 0.02}}
{"type": "error",        "message": "工具调用失败：AKShare 接口超时"}
{"type": "interrupted",  "message": "任务已中断"}
```

---

## 六、前端页面

**index.html（主界面）**
- 左侧：历史会话列表
- 中间：对话区（Markdown 渲染，SSE 流式显示执行步骤，工具调用可折叠）
- 右侧：当前任务进度面板（显示 Agent 正在做什么）
- 底部：输入框 + 发送 + 中断按钮

**agents.html（Agent 配置页）**
- Agent 卡片列表（名称、描述、绑定模型）
- 新建/编辑表单：系统提示词、模型选择、Skill 开关、参数调节

**settings.html（全局配置页）**
- 模型选择（下拉，支持多个 Provider）
- API Key 输入（本地存储，不上传）
- 执行参数（最大步数、Token 预算、慢思考频率）
- 输出目录配置

**skills.html（Skill 管理）**
- Skill 卡片列表（名称、描述、依赖工具、风险等级）
- 开关控制启用/禁用

**knowledge.html（知识库）**
- 文档上传（拖拽，限制 50MB / PDF+Word+TXT）
- 知识单元列表（可搜索、可删除）
- 编译状态显示（进度条）

**history.html（历史记录）**
- 会话列表（时间、Agent、状态）
- 研报列表（可下载 Markdown）

---

## 七、分阶段实现计划

### Phase 1 — 核心跑通（第1周）
- [ ] 项目脚手架 + FastAPI 基础结构 + `/health` 接口
- [ ] 多模型抽象层（Claude 接入，支持 prompt caching）
- [ ] 基础工具：行情数据、财务报表（AKShare，含缓存）
- [ ] 简单执行引擎（单循环，无断点续跑）
- [ ] 基础 Web UI（聊天界面 + SSE 流式输出）
- **目标**：能问「分析一下贵州茅台」并得到基本面回答

### Phase 2 — 工程化（第2周）
- [ ] 双循环引擎（加入慢思考）+ 死循环检测
- [ ] 断点续跑（SQLite 持久化）
- [ ] 任务中断机制（interrupt 接口）
- [ ] 并发任务隔离（独立引擎实例）
- [ ] 上下文压缩
- [ ] 成本追踪 + 执行链路日志
- [ ] Agent 配置页（agents.html + api/agents.py）
- [ ] 全局配置页（settings.html）
- **目标**：长任务稳定运行，成本可见，Agent 可配置

### Phase 3 — 专业化（第3周）
- [ ] Skill 插件系统（加载器 + 基类 + 2个内置 Skill）
- [ ] 多 Agent 协作（基本面 + 宏观 + 研报生成）
- [ ] 知识库（ChromaDB + 知识编译）
- [ ] 本地文档解析（PDF 年报，含文件校验）
- [ ] Skill 管理页 + 知识库管理页
- **目标**：输出完整的 Markdown 研报

---

## 八、settings.json 结构

```json
{
  "models": {
    "default": "claude-sonnet-4-6",
    "providers": {
      "claude": {
        "api_key": "",
        "model": "claude-sonnet-4-6"
      },
      "deepseek": {
        "api_key": "",
        "model": "deepseek-chat",
        "base_url": "https://api.deepseek.com"
      }
    },
    "routing": {
      "simple_task": "deepseek",
      "complex_task": "claude"
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
  "skills": {
    "valuation": true,
    "industry_compare": true
  },
  "output": {
    "report_dir": "./output/reports",
    "chart_dir": "./output/charts"
  }
}
```

---

## 九、关键依赖

```
fastapi
uvicorn[standard]
anthropic
aiosqlite
chromadb
akshare
tushare
pdfplumber
python-docx
matplotlib
mplfinance
markdown
python-multipart
sse-starlette
```

---

## 十、架构层级对应关系

| Harness 层 | 本项目模块 | 核心价值 |
|-----------|-----------|---------|
| 第1层 核心执行引擎 | core/ | 稳定性、断点续跑、多模型 |
| 第2层 工具系统 | tools/ | 数据获取、风险控制、缓存 |
| 第3层 上下文工程 | context/ | 成本降低 40-50% |
| 第4层 记忆系统 | memory/ | 知识库、低幻觉 RAG |
| 第5层 自主决策 | decision/ | OPEA 循环、安全防线 |
| 第6层 多 Agent | agents/ | 专业分工、并行提速 |
| 可观测性 | observability/ | 成本可见、问题可查 |
