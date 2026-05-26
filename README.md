# Investment Agent

A-share 基本面分析智能助手。基于 LLM Agent 架构，自主调用数据工具完成选股、财报分析、估值评估等投研工作，支持 Markdown 研报输出。

---

## 功能特性

- **多模型支持** — 兼容 Claude、DeepSeek、Qwen、Ollama 等多种 LLM，可在 Web UI 中自由切换
- **A 股数据一站式获取** — 集成 AKShare，自动获取行情、财报、估值等数据，无需手动查找
- **文件上传分析** — 上传 PDF/Word/Excel 财报，Agent 自动解析内容并纳入分析上下文
- **Skill 插件扩展** — 通过 `SKILL.md` 声明式添加专业分析能力（财务造假识别、PDF 转 Markdown、行情查询等）
- **流式输出** — SSE 实时推送分析过程，工具调用步骤和思考过程对用户可见
- **会话管理** — 历史会话持久化，支持回溯和继续分析

---

## 快速开始

### 前置要求

- Python 3.10+
- 一个兼容 OpenAI API 或 Anthropic API 的 LLM

### 安装与启动

```bash
# 安装依赖
pip install -r requirements.txt

# 启动开发服务器
uvicorn investment_agent:app --reload --port 8000
```

### 配置模型

访问 `http://localhost:8000/model`，添加 LLM 配置（API Key、Endpoint、模型名称）。支持两种接入方式：

- **Anthropic** — 填入 API Key 即可（推荐 Claude Sonnet，工具调用能力强）
- **OpenAI Compatible** — 需填写 Endpoint 和 API Key，适用于 DeepSeek、Qwen、Ollama 等

### 开始分析

在对话页输入分析请求，例如：

> 分析贵州茅台（600519）近三年的盈利能力变化趋势

Agent 会自动调用工具获取财务数据并生成分析。你也可以上传财报文件让 Agent 基于文件内容进行分析。

---

## 使用场景

| 场景 | 示例 |
|------|------|
| 基本面分析 | "分析海康威视的营收质量和毛利率变化" |
| 财务排雷 | "检查东方财富是否存在财务造假风险" |
| 年报解读 | 上传 PDF 年报 → "提取关键财务指标并与去年对比" |
| 行业对比 | "对比茅台和五粮液的 ROE 和资产负债率" |
| 批量分析 | "下载伊利股份近五年年报并生成全量财务分析报告" |

---

## 配置

### 引擎参数（settings.json）

```json
{
  "engine": {
    "max_steps": 30,
    "slow_think_interval": 5,
    "token_budget": 100000,
    "loop_detection_threshold": 3
  }
}
```

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `max_steps` | 单次任务最大执行步数 | 30 |
| `slow_think_interval` | 每 N 步触发一次全局复盘 | 5 |
| `token_budget` | Token 预算上限 | 100000 |
| `loop_detection_threshold` | 连续同工具调用次数上限 | 3 |

### 上下文压缩

长对话自动压缩以节省 Token：保留最近 15 条消息原文，旧消息截断至 2000 字符，Token 总预算 20000。可在设置页调整。

---

## 项目结构

```
investment_agent/
├── main.py                  # FastAPI 入口 + 路由注册
├── app/
│   ├── api/                 # RESTful 接口（对话/会话/设置/Agent/Skills/文件/观测/工具）
│   ├── db.py                # SQLite 数据库
│   ├── observability/       # Token 成本 + 链路追踪（cost_tracker / trace / hooks）
│   └── static/              # 前端（原生 HTML/JS/CSS，无构建步骤）
├── agent/
│   ├── core/                # 执行引擎
│   │   ├── engine.py        # 双循环（快循环 + 慢思考）
│   │   ├── models.py        # 多模型抽象层（Anthropic / OpenAI Compat）
│   │   ├── subagent.py      # 子 Agent 委派
│   │   ├── tool_executor.py # 工具执行 + 死循环检测
│   │   └── task_planner.py  # 任务规划
│   ├── tools/               # 工具基类与注册系统（Skill/run_command/DelegateTask）
│   ├── skills/              # Skill 插件加载框架（loader + 脚本执行器）
│   └── context/             # 上下文管理（分级压缩 / 运行时截断 / Token 估算 / 检索）
├── extensions/skills/       # Skill 定义（10 个）
├── data/                    # SQLite 数据库 + 运行时数据
└── output/                  # 研报和图表输出（含 charts/、reports/）
```

---

## Skill 插件

Skill 是基于 `SKILL.md` 声明的分析能力模块，放置在 `extensions/skills/` 目录下即可被自动发现。

### 内置 Skill（10 个）

| Skill | 说明 |
|-------|------|
| `a-share-financial-data` | A 股财务数据查询（利润表、资产负债表、现金流量表、估值指标） |
| `a-share-stock-market` | A 股行情与基本信息查询（股价 K 线、实时行情、市场指数） |
| `a-share-financial-forensic` | 38 条财务造假识别规则，扫描财报风险信号 |
| `orch-full-financial-analysis` | 全量财务分析编排，自动执行多维度分析流程 |
| `split-financial-report` | 将大文件财报按章节拆分，分块处理 |
| `pdf-to-markdown` | PDF 转 Markdown（pdfplumber 快速模式 / docling 高质量模式） |
| `download-a-share-reports` | 从巨潮资讯网下载 A 股年报 |
| `analyze-session-trace` | 排查执行轨迹中的死循环、Token 预算、委派截断等问题 |
| `demo_echo` | 回显测试，验证 Skill 调用链路 |
| `demo_brief_report` | 简短结构化报告生成 |

### 自定义 Skill

新建目录并创建 `SKILL.md`：

```yaml
---
name: my-skill
description: 自定义分析能力
---
# 此处写 Markdown 提示词，将注入系统提示词
```

需要 Python 脚本时，在 `scripts/` 下添加入口文件，Skill 框架会自动调用。

---

## API 概览

```
对话
  POST   /api/chat                          → 发起分析任务
  GET    /api/chat/{task_id}/stream          → SSE 流式结果
  POST   /api/chat/{task_id}/interrupt       → 中断任务

会话
  GET    /api/sessions                       → 会话列表
  DELETE /api/sessions/{id}                  → 删除会话

Agent 配置
  GET    /api/agents                         → Agent 列表
  POST   /api/agents                         → 创建 Agent
  GET    /api/agents/{id}                    → 获取 Agent 详情
  PUT    /api/agents/{id}                    → 更新 Agent
  DELETE /api/agents/{id}                    → 删除 Agent

模型管理
  GET    /api/settings/models                → 模型列表（含默认标记）
  POST   /api/settings/models                → 添加模型
  PUT    /api/settings/models/default        → 设置默认模型
  PUT    /api/settings/models/{id}           → 更新模型
  DELETE /api/settings/models/{id}           → 删除模型
  POST   /api/settings/models/test           → 测试模型连接

系统设置
  GET    /api/settings                       → 读取配置
  PUT    /api/settings/engine                → 更新引擎参数
  PUT    /api/settings/skills                → 更新 Skill 目录
  PUT    /api/settings/tools                 → 更新工具配置

观测
  GET    /api/observability/cost             → Token 成本日志
  GET    /api/observability/traces           → 执行链路追踪

文件
  GET    /api/files                          → 文件树
  GET    /api/files/preview                  → 文件预览

其他
  GET    /api/skills                         → Skill 列表
  GET    /api/tools                          → 工具列表
  GET    /health                             → 健康检查
```

---

## 技术栈

| 层 | 技术 |
|----|------|
| Web 框架 | FastAPI + Uvicorn |
| LLM SDK | Anthropic SDK + OpenAI SDK |
| 数据源 | AKShare |
| 数据库 | SQLite（aiosqlite）|
| 前端 | 原生 HTML/JS/CSS（SSE 流式）|
| 文件解析 | pdfplumber / python-docx / openpyxl |
| 图表 | matplotlib / mplfinance |

---

## 开发

```bash
# 启动热重载开发服务器
uvicorn investment_agent:app --reload --port 8000
```

本项目使用纯原生前端，无需构建工具。后端修改自动生效，前端修改刷新页面即可。

### 添加新数据能力（推荐用 Skill）

Agent 的数据获取能力已全部通过 Skill 插件实现。新增数据源时，在 `extensions/skills/` 下创建 Skill 并编写对应的 `scripts/run.py` 脚本即可。

如需添加基础设施工具（如新的命令执行器、外部服务桥接），在 `agent/tools/` 下继承 `BaseTool` 实现 `run()` 方法，工具会在启动时自动注册。

### 添加新 Skill

参考上方的 Skill 模板，在 `extensions/skills/` 下创建子目录和 `SKILL.md` 即可。

---

## TODO

- 逃逸检查改用 Docker 容器隔离替代代码层路径检查
- 子Agent token 预算爆炸——调优上下文裁剪 + 限制工具返回大小
- 带内容权重的 RAG 构建
- Agent 执行日志自我进化
- 上下文缓存命中 Token 节省

详细分析见 [docs/TODO.md](docs/TODO.md)。

---

## 许可证

MIT