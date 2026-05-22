# 上下文管理优化方案

## Context

用户请求分析万华化学财报时，编排技能 `orch-full-financial-analysis` 串行执行 4 步（下载PDF → PDF转Markdown → 章节切割 → 财务排雷），在步骤3（章节切割）处理到第3份年报时触发 300,000 token 预算上限，**分析未完成即中止**。总计消耗 300,834 input + 7,370 output tokens，约 0.95 元。

### 根本原因

当前上下文管理只在引擎执行前运行一次（`ContextManager.prepare()`），引擎执行期间消息列表单调增长，每一步 LLM 调用都发送完整历史。

### 链路日志关键数据（session `30d8bdce`）

| Step | input_tokens | 阶段 |
|------|-------------|------|
| 1 | 1,308 | 加载 orch skill |
| 4 | 4,325 | 开始下载 PDF |
| 6 | 6,073 | PDF 转 Markdown |
| 8 | 11,216 | 开始章节切割（2024年报） |
| 12 | 14,852 | 章节切割歧义消解 |
| 17 | 18,277 | 开始切割 2023年报 |
| 22 | 20,831 | 开始切割 2022年报 |
| 23 | 21,269 | **Token budget exceeded** |

**token 浪费的三个主因**：
1. **历史消息全量发送**：23 步中消息量从 3K → 54K 字符，每步增长 ~2K
2. **Reasoning blocks 累积**：每一步的推理内容（100-500 tokens）永久保留
3. **Skill body 永久驻留**：4 个 skill 的 body（共 ~20K 字符）加载后永不清除

---

## 优化方案

### 优化 1：引擎内运行时上下文管理 ✅ 已实现

**方案**：在 `AgentEngine.run()` 中添加周期性上下文整理逻辑。

**修改文件**：`investment_agent/agent/core/engine.py`、`runner.py`、`config.py`、`app/config_factory.py`、`settings.json`

**具体改动**：
- 新增参数 `context_trim_interval: int = 5`（每 N 步整理一次）
- 新增方法 `_trim_context(messages, keep_recent=5)`：
  - 保留最近 5 轮对话完整不变
  - 对于旧消息：剥离 reasoning blocks，替换为 `[推理过程已压缩]`
  - 对于旧的 tool_result（Skill body 返回等）：截断到前 500 字符 + `...[已截断]`
  - 对于旧的 `run_command` 结果：截断到前 300 字符
- 在每步 LLM 调用前，如果 `step % context_trim_interval == 0`，调用 `_trim_context()`

---

### 优化 2：Orch 技能内嵌关键指令 ⏳ 待实现

**方案**：将各子步骤的关键命令直接嵌入 orch 技能 body，避免加载完整子技能 body。

**修改文件**：`extensions/skills/orch-full-financial-analysis/SKILL.md`

**预计节省**：30-40% token

---

### 优化 3：Skill 工具返回精简版 ⏳ 待实现

**方案**：为 Skill 工具增加 `brief` 模式，智能提取核心内容。

**修改文件**：`investment_agent/agent/skills/tool.py`，各 SKILL.md（可选）

**预计节省**：15-20% token

---

### 优化 4：默认启用 Prompt Caching ✅ 已实现

**方案**：`settings.json` 中 `caching.enabled` 改为 `true`。

**修改文件**：`investment_agent/investment_agent/settings.json`

---

### 优化 5：Reasoning Block 截断 🔧 当前实现

**方案**：reasoning 在写入消息列表时做截断（>300 chars 时保留首尾各 150 chars），而非完全移除。SSE 事件仍输出完整 reasoning 供前端展示。

**原因**：完全移除 reasoning 可能导致遇到死胡同时无法回溯之前的决策逻辑。折中：保留截断版提供回溯线索，同时大幅减少 token 占用。

**修改文件**：`investment_agent/agent/core/engine.py`

---

### 优化 6：Slow Thinking 修复 ✅ 已实现

**方案**：
- 用 `_do_slow_think()` 替代旧的 `_slow_think()`，返回反思文本并注入 messages
- 仅发送最近 5 轮 + 精简 system prompt（从实际 system_prompt 提取角色定义）
- 使用 `_extract_role_from_system()` 避免硬编码角色
- 增加异常日志记录（`logger.warning(..., exc_info=True)`）
- max_tokens 限制为 512

**修改文件**：`investment_agent/agent/core/engine.py`

---

### 优化 7：Skill Body 体积削减 ✅ 已实现

**方案**：缩减 split-financial-report SKILL.md。

**修改文件**：
- `extensions/skills/split-financial-report/SKILL.md` — 附录外移
- `extensions/skills/split-financial-report/references/tier3-fallback.md` — 新增
- `extensions/skills/split-financial-report/references/benchmark.md` — 新增

---

## 实施优先级与预估效果

| 优先级 | 优化项 | 状态 | 预计 token 节省 |
|--------|--------|------|----------------|
| P0 | 引擎内运行时上下文管理 | ✅ | 50-60% |
| P1 | Orch 技能内嵌关键指令 | ⏳ | 30-40% |
| P2 | 默认启用 Prompt Caching | ✅ | 20-30% |
| P3 | Reasoning Block 截断 | 🔧 | 8-12% |
| P4 | Skill Body 体积削减 | ✅ | 5-10%（一次性） |
| P5 | Slow Thinking 修复 | ✅ | 5-8% |

---

## 验证方案

1. 使用相同输入「分析万华化学财报」重新运行，对比总 input/output tokens
2. 验证是否能在 token budget 内完成全部 4 步分析
3. 验证输出结果质量是否下降
4. 回归测试其他场景不受影响
