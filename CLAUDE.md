# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Start development server
uvicorn investment_agent:app --reload --port 8000

# Run a Python script (all scripts run from project root)
python extensions/skills/<skill-name>/scripts/<script>.py
```

No test suite, linting, or type-checking is configured yet.

## Architecture

**Investment Agent** — a FastAPI web app for A-share (Chinese stock market) fundamental analysis. A browser-based chat UI lets users upload financial reports (PDF/Word/Excel) and ask analytical questions. The LLM-driven agent autonomously calls data-fetching tools and executes analysis skills, streaming results via SSE.

### Entry point and routing

`investment_agent/main.py` creates the FastAPI app (`investment_agent:app`), mounts `app/static/` for frontend files, serves Jinja2 templates from `app/templates/`, and registers seven API routers from `app/api/`. A Jinja2 `tabs` list is passed to every template for the nav bar.

### Dual-loop execution engine (`agent/core/engine.py`)

`AgentEngine` orchestrates an LLM reasoning → tool call → result → repeat loop:

- **Fast loop** (every step): LLM infers, invokes tools, appends results to conversation context.
- **Slow thinking** (every N steps, default 3): appends a meta-prompt asking the model to reflect on progress and strategy.
- **Safety guards**: max steps (30), token budget (100k), dead-loop detection (same tool called ≥3 consecutive times; `run_command` is whitelisted from this check), and graceful interruption via `asyncio.Event`.

The engine yields `dict` events (`text_delta`, `tool_call`, `tool_result`, `slow_think`, `done`, `error`, `interrupted`) that `chat.py` serializes into SSE.

### Multi-model abstraction (`agent/core/models.py`)

`ModelProvider` is an ABC with two implementations:
- `ClaudeProvider` — native Anthropic SDK (content blocks format).
- `OpenAICompatProvider` — OpenAI Chat Completions SDK; `_convert_messages()` translates between Anthropic content-block format and OpenAI tool_calls/role format at the boundary.

`get_provider()` is the factory — reads model config from the SQLite `models` table (default model or by ID), instantiates the correct provider.

### Tool system (`agent/tools/`)

`BaseTool` ABC requires `name`, `description`, `schema` (Anthropic tool schema dict), and `async run(**kwargs)`. Tools are registered at import time in `registry.py`'s module-level `_registry` dict. Currently 8 active tools:

| Tool | Source | Risk |
|------|--------|------|
| `get_stock_info` | `market_data.py` | L0 read-only |
| `get_stock_price` | `market_data.py` | L0 read-only |
| `get_income_statement` | `financials.py` | L0 read-only |
| `get_balance_sheet` | `financials.py` | L0 read-only |
| `get_cash_flow` | `financials.py` | L0 read-only |
| `get_valuation` | `financials.py` | L0 read-only |
| `get_financial_indicators` | `financials.py` | L0 read-only |
| `run_command` | `run_command.py` | L2 shell exec |

Data source is AKShare (free A-share data). Two realtime tools (`get_stock_realtime`, `get_market_index`) are commented out because their upstream API is unreachable in the current network environment.

### Skill plugin system (`agent/skills/`)

Skills are higher-level analysis capabilities defined by `SKILL.md` files (YAML frontmatter + Markdown body). Each lives in its own subdirectory under `extensions/skills/`.

- `loader.py` scans `extensions/skills/` for `SKILL.md` files, parses them with `markdown_parser.py`, and registers `MarkdownSkill` instances.
- `MarkdownSkill.run()` either executes a Python entry script via subprocess (`script_runner.py` with 20s timeout and path-traversal guard) or returns the Markdown body as-is.
- When a chat starts, the Agent's enabled skills have their bodies injected into the system prompt. The LLM sees skill schemas as tools and can invoke them.
- `run_command` is whitelisted from dead-loop detection specifically because skill execution uses it.

### Conversation flow (`app/api/chat.py`)

1. `POST /api/chat` — parses request (JSON or multipart with file upload), creates/resumes a session in SQLite, loads Agent config (system prompt, model, skills, engine/compress overrides), creates an `AgentEngine`, registers all tools, returns `task_id`.
2. `GET /api/chat/{task_id}/stream` — loads session messages from DB, compresses context, runs the engine, yields SSE events. On completion, saves the assistant's response to DB. Engine is cleaned up in `finally`.
3. `POST /api/chat/{task_id}/interrupt` — sets the engine's interrupt event.

File upload supports `.txt`, `.md`, `.pdf`, `.xlsx`, `.xls`, `.docx`, `.doc` (max 10MB, extracted text capped at 50k chars). PDF uses pdfplumber; Excel uses openpyxl/xlrd; Word uses python-docx.

### Session isolation (`agent/core/session.py`)

A global `_engines: dict[task_id → AgentEngine]` dictionary ensures concurrent users get independent engine instances. Engines are created by `create_engine()`, retrieved by `get_engine()`, and removed by `remove_engine()` after the SSE stream ends.

### Context compression (`agent/context/compressor.py`)

Non-LLM context management: keeps the most recent N messages intact, truncates older ones to a character limit, and applies a total character budget. Structured content blocks (tool calls/results) pass through unmodified to avoid breaking protocol format. Agent-level compress settings in DB override global settings.

### Configuration (`config.py` + `settings.json`)

`config.py` reads `investment_agent/settings.json` with an LRU-cached `get_settings()` function. `reload_settings()` clears the cache. `save_settings()` writes and refreshes.

`settings.json` holds: engine params (max_steps, slow_think_interval, token_budget, loop_detection_threshold), compress params, skills directory path, tushare_token, and database path.

Model configurations (API keys, endpoints, model names) are stored in the SQLite `models` table, not in `settings.json`. Managed via the `/model` UI page or `/api/settings/models` API.

### Database (`app/db.py`)

SQLite via aiosqlite with auto-created tables: `models`, `agents`, `sessions`, `messages`, `checkpoints`, `cost_log`, `trace_log`. `get_db()` is an async context manager with row factory set to `aiosqlite.Row`. `init_db()` handles schema creation and migrations (ALTER TABLE for missing columns).

### Frontend

Native HTML/JS served by FastAPI — no build step. Jinja2 templates at `app/templates/`, static files at `app/static/`. SSE streaming in `chat.js` renders events (text, tool calls, slow thinking) progressively in the chat UI. The model management page (`model.html` + `model.js`) handles CRUD for LLM model configurations stored in the `models` DB table. The file browser page (`files.html` + `files.js` + `app/api/files.py`) renders a collapsible tree of the `data/` directory and previews PDF/Markdown/HTML files in-browser.

### Skill development

To add a new skill, create a subdirectory under `extensions/skills/` with a `SKILL.md` file:

```yaml
---
name: my-skill
description: What this skill does
---
# Markdown body — injected into system prompt
```

Optionally add a `scripts/` directory with a Python entry point. The script receives kwargs as CLI flags (`--param-name value`) and a JSON payload on stdin.

### Git commit conventions

提交信息使用中文，格式：`type: 简短描述`

- `feat:` — 新功能
- `fix:` — 修复bug
- `refactor:` — 重构（无功能变化）
- 描述用中文，一行概括，不加句号
- 示例：`feat: 新增文件浏览页面，支持data目录下PDF/Markdown/HTML文件在线查看`

### Session Trace 分析工作流

当用户提供一个 session_id 时，按以下流程分析执行轨迹并找出改进点（完整说明见 `extensions/skills/analyze-session-trace/SKILL.md`）：

1. **数据采集** — 从 `data/agent.db` 提取该 session 的 trace_log、messages、agent 配置
2. **轨迹重建** — 按时间线梳理每步的事件类型、耗时、委派、错误
3. **问题识别** — 对照检查清单逐项排查：
   - 死循环检测误杀（DelegateTask 被计入、子Agent 未继承阈值）
   - Token 预算耗尽（子Agent token 累加回父Agent、缺少委派前预算检查）
   - 委派指令截断（_generate_task_instruction prompt 不完整、缺少 skill body、max_tokens 不足）
   - 脚本路径试错（SUBAGENT_SYSTEM_PROMPT 缺少项目目录结构）
   - 串行/并行效率（sub_agent_mode 配置、同步骤内多文件独立处理）
   - 可观测性缺失（委派后无 budget_status 事件、子Agent 事件透传）
4. **关联代码** — 定位 engine.py、config.py、对应 SKILL.md 中的根因
5. **输出报告** — 会话概览 + 执行时间线 + 委派统计 + 问题列表（含 trace 证据）+ 改进方案
6. **讨论实施** — 逐问题与用户确认，区分代码/skill/配置修改，按优先级执行

关键文件：`agent/core/engine.py`（引擎+委派+死循环+token）、`agent/config.py`（SUBAGENT_SYSTEM_PROMPT+默认参数）、`extensions/skills/{skill}/SKILL.md`（编排流程）
