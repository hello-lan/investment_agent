# TODO 详细记录

## 在研问题

### 1. 逃逸检查与 Docker 隔离（P0）

**问题**：AccessPolicy 的 `check()` 方法中存在逃逸检查（第 120-125 行），要求所有路径必须在项目目录内。这与 deny list 设计理念矛盾——deny list 说"只禁止特定目录"，逃逸检查说"只允许项目内目录"。

**现象**（恒立液压第二次运行 session `0ae6ef36`）：
- 子Agent 幻觉出 `/home/user/`、`/workspace/` 前缀 → 逃逸拒绝（3 次）
- 父Agent 写 `/tmp/split_reports.py` → 逃逸拒绝（1 次）
- 共 5 次拒绝，全部来自逃逸检查，0 次来自 deny list

**根因**：
- 逃逸检查本质是 allow list，和 deny list 哲学冲突
- 路径幻觉是模型能力问题（子Agent 知道 PROJECT_ROOT 但仍构造错误前缀）
- 逃逸检查充当了"系统防火墙"角色，但代码层不适合做这个

**方案**：
1. **代码层**：删除 `access_policy.py` 第 120-125 行的逃逸检查
2. **基础设施层**：用 Docker 容器隔离兜底——容器内没有宿主机敏感文件（`/etc/passwd`、`/root/.ssh`、`/home/brook/.env`），agent 路径幻觉了 shell 自己报 `No such file`
3. **部署**：`data/` 目录通过 volume 挂载，其余目录在容器内

**安全模型（Docker 部署后）**：

| 层级 | 职责 | 实现 |
|------|------|------|
| 容器隔离 | 系统安全——防止访问宿主机文件 | Docker volume mount |
| deny list | 业务纪律——只禁 `investment_agent/` 和 `extensions/` | AccessPolicy |

**改动**：
- `access_policy.py`：删除逃逸检查（~5 行）
- 新增 `Dockerfile` + `docker-compose.yml`

---

### 2. Token 预算爆炸（P0）

**问题**：forensic 子Agent 15 步累计 509K input tokens（占总预算 50%+），单步峰值 66K。

**现象**（恒立液压第二次运行）：

| 引擎 | 步骤 | input tokens | 占比 |
|------|------|-------------|------|
| 父Agent | 24 | 194,798 | 15% |
| forensic 子Agent | 15 | 508,967 | 39% |
| split 子Agent #2 | 30 | 273,034 | 21% |
| split 子Agent #3 | 22 | 199,530 | 15% |
| pdf2md 子Agent | 8 | 29,850 | 2% |
| download 子Agent | 8 | 33,358 | 3% |
| **总计** | — | **1,239,537** | — |

**根因（双层）**：
- **架构层**：LLM 每次调用重发完整对话历史，读入的文件内容在后续每一步都重复发送。15 步累积放大 ~6 倍。
- **模型层**：模型读文件太贪（`cat` 整章而非 `grep` 定向提取），不会分批处理三年财报。

**方案**：
- **架构侧**：调优子Agent 的 `context_trim_interval`，更激进地裁剪已读过的大文件内容
- **架构侧**：限制 `run_command` 返回结果的最大字符数，防止一次读入整章财报撑爆上下文
- **模型侧**：在 forensic SKILL.md 中增加指引——分批处理（一年做完再做下一年），优先 `grep` 定向提取

---

### 3. 重复委派与子Agent提前终止（P2）

**问题**：3 个 split 子Agent 中前两个各只跑了 8 步就停了，第三个跑了 22 步完成。浪费 ~63K tokens。

**现象**：
- `delegate_37bcf80a`：8 步，input 29,850
- `delegate_44586626`：8 步，input 33,358
- `delegate_f6b1c291`：22 步，input 199,530（完成）

**根因**：未查明。可能原因：
- 子Agent 报错（权限拒绝、脚本执行失败）
- 父Agent 误判子Agent 完成状态
- max_steps 不足

**改进**：已在 `tool_executor.py` 和 `subagent.py` 中补充详细日志，下次出现类似问题时可快速定位：
- 委派开始/结束日志（含 skill_names、prompt 预览、delegate_id）
- 子Agent token 消耗明细
- 子Agent 终止原因（done/error/max_steps）
- 技能过滤结果（请求 vs 实际注册）

**下一步**：重新运行恒立液压分析，观察日志输出，确认前两个子Agent 的终止原因。

---

## 历史问题（已解决）

### 广州酒家中文财务比率误杀（2026-05-26 已修复）

**问题**：报告内容中的中文财务比率（`经营现金流/归母净利润`、`货币资金/有息负债`）含 `/`，被 `_is_path_like()` 误判为文件路径，触发权限拒绝。17 次拒绝，每次消耗 ~45K input token。

**修复**：
- deny list 模式：非黑名单路径一律放行
- `_is_path_like()` 增加 CJK、markdown、全角括号过滤

### 恒立液压 bare `/` 误杀（2026-05-26 已修复）

**问题**：`grep -n "目录\|3 / 171\|备查文件目录"` 中的 `'3 / 171'` 被 split 成 `'3`、`/`、`171'`，bare `/` 解析为系统根目录触发逃逸检查。28 次拒绝。

**修复**：`_is_path_like()` 增加 `if token == "/": return False`。

---

## 待办清单

### 近期（P0）

- [ ] 删除 `access_policy.py` 逃逸检查，改用 Docker 隔离
- [ ] 编写 `Dockerfile` + `docker-compose.yml`（`data/` 挂载卷）
- [ ] 调优子Agent `context_trim_interval` 参数
- [ ] 限制 `run_command` 返回结果最大字符数
- [ ] 文件读写权限判断逻辑改为 规则+AI(轻量AI,单次请求) 

### 中期（P1）

- [ ] forensic SKILL.md 增加分批处理指引
- [ ] 路径幻觉修复：`TASK_PLANNER_PROMPT` 生成绝对路径指令 ✅ 已完成
- [ ] 重复委派问题：补充日志后重新运行，确认根因

### 远期（P2）

- **带内容权重的 RAG 构建** — 为财报文本分段赋予权重，提升关键信息检索质量
- **Agent 执行日志自我进化** — Agent 根据执行日志分析自身表现，自动优化 skill prompt 与决策策略
- **上下文缓存命中 Token 节省** — 利用 Anthropic Prompt Caching 降低长上下文场景的 Token 消耗

---

## 相关文档

- [上下文压缩方案](context-compression.md)
- [上下文管理流程](context-management-flow.html)
- [上下文机制评估](context-mechanism-evaluation.md)
- [上下文优化计划](context-optimization-plan.md)
- [记忆与压缩设计](memory-and-compression-design.md)
- [子Agent并发设计](subagent-concurrency.md)
