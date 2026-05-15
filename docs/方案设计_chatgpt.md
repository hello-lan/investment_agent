# A股财报 Agent 分析系统：完整技术与产品方案（V1）

你现在要做的，本质上不是“做一个财报分析 Prompt”，而是在做：

> 一个面向上市公司财务分析的「金融级 Agent Intelligence System」

它会逐步演化为：

* 财报解析引擎
* 财务知识图谱
* 财务规则推理系统
* 多模态金融知识库
* 长周期公司跟踪系统
* 财务风控 Agent 平台

你当前已经具备：

* PDF → Markdown 能力（Docling）
* 初版 Financial Forensic Skill
* 三表规则库
* 风险识别框架

但真正困难的部分，其实是：

> 如何把“超长、脏、异构、低结构化”的财报文本，转化为 AI 可稳定推理的高质量金融上下文。

这件事决定整个系统效果。

---

# 一、你的真实需求（重构与补充）

你当前的需求，本质上可以拆成 8 个系统问题：

---

# 1. 财报文本可信度问题（Data Reliability）

问题：

PDF → Markdown 即便质量很高，仍存在：

* 表格错位
* 数字断裂
* 标题层级丢失
* 附注错配
* OCR错误
* 页眉页脚污染
* 跨页表格断裂
* 单位丢失（万元/亿元）
* 三表字段对应错误

而：

> AI分析质量 ≈ 输入质量上限

所以你需要：

## 核心目标

建立：

# Financial Document QA Pipeline（财报质量修复流水线）

不是简单“转 markdown”。

而是：

```text
PDF
→ 结构解析
→ 文本清洗
→ 表格修复
→ 附注绑定
→ 语义校验
→ 数据一致性验证
→ 结构化重建
→ Agent分析
```

---

# 2. 超长文本与Token成本问题（Context Compression）

问题：

完整财报：

* 20万~80万 tokens
* 多年财报可能超百万 tokens

直接给 Agent：

问题：

* 成本爆炸
* 注意力稀释
* 推理能力下降
* 上下文污染
* 长文本 hallucination

所以必须：

# “金融领域专用 Chunking + Distillation”

而不是普通 RAG chunk。

---

# 3. 附注才是核心问题（Notes-to-FS Alignment）

你已经意识到最关键的问题：

> 真正的财务分析价值，往往在附注。

因为：

三表数据：

* akshare
* Wind
* TuShare
* 同花顺
* iFinD

都能拿到。

但：

真正能揭示：

* 收入确认
* 坏账政策
* 商誉减值
* 存货跌价
* 关联交易
* 表外安排
* 审计重点事项

的是：

# 财报附注

而附注的最大难点：

> “附注必须与报表科目建立映射关系”

这是整个系统最核心的数据建模问题之一。

---

# 4. Agent 输入组织问题（Context Engineering）

问题：

到底：

* 全量喂给 AI？
* 做 RAG？
* 做预摘要？
* 做结构化抽取？
* 做事件化？
* 做知识图谱？

答案其实是：

# 分层上下文系统（Hierarchical Financial Context System）

而不是单一方案。

---

# 5. 多年连续分析问题（Temporal Intelligence）

你已经意识到：

财报分析不是：

```text
分析某一年
```

而是：

```text
分析公司长期演化
```

因为很多风险：

* 是趋势问题
* 是恶化过程
* 是会计操纵连续行为
* 是资产质量长期变化

所以：

系统必须支持：

# Time-Series Financial Intelligence

---

# 6. 多源异构信息问题（Multi-source Fusion）

输入不仅有：

* 年报
* 季报

还有：

* 董秘问答
* 互动易
* 电话会议
* 研报
* 新闻
* 行业报告
* 处罚公告
* 招股书
* 问询函回复

问题：

这些：

* 结构完全不同
* 可信度不同
* 时效性不同

所以：

你真正需要的是：

# Financial Evidence Fusion Engine

---

# 7. Skill 系统问题（Dynamic Skill Architecture）

你已经不是在做：

```text
一个 Prompt
```

而是在做：

# 金融 Agent Skill Operating System

问题变成：

* Skill 如何拆分？
* Skill 如何编排？
* 如何动态调用？
* 如何适配不同输入完整度？
* 如何做可解释推理？
* 如何做证据链？

---

# 8. 是否需要多 Agent 协作（Multi-Agent）

答案：

# 后期一定需要

但：

> 第一阶段不要上复杂多 Agent。

因为：

多 Agent 最大问题不是技术。

而是：

# 上下文协调成本

金融分析尤其严重。

---

# 二、推荐的整体系统架构（非常关键）

推荐：

# “四层金融智能架构”

---

# 第一层：Document Intelligence Layer（文档智能层）

负责：

PDF → 高质量金融文档

## 模块

### 1. PDF Parsing

当前：

* Docling（很好）

建议增加：

* OCR fallback
* Layout parser
* Table detector

推荐：

* Docling
* MinerU
* PaddleOCR
* Nougat（科研向）

---

## 2. 财报结构重建

核心：

不是 markdown。

而是：

# Financial AST（抽象财报结构树）

例如：

```json
{
  "section": "应收账款",
  "subsection": "账龄结构",
  "table_refs": [],
  "note_refs": ["附注七、5"],
  "page_range": [122,125]
}
```

必须保留：

* 标题层级
* 页码
* 表格关系
* 附注编号
* 表间引用

这是后续 Agent 的根基。

---

## 3. 财报质量修复（重点）

推荐：

# Rule + AI 双阶段

---

### 第一层：规则修复（低成本）

处理：

* 页眉页脚
* 重复行
* OCR乱码
* 单位识别
* 表格列错位
* 数字断裂

这里：

* Python
* regex
* layout analysis

即可。

成本极低。

---

### 第二层：AI校验（高价值区域）

只对：

* 三表
* 附注
* 审计意见

做 AI 校验。

因为：

这些区域决定分析质量。

不要全量 AI 修复。

成本太高。

---

# 三、最核心部分：财报 Chunking 方案

这是整个系统最重要部分之一。

---

# 传统 Chunk 不适合财报

错误方案：

```text
每1000 tokens切一块
```

会直接废掉。

因为：

财报存在：

* 表格依赖
* 附注依赖
* 跨章节关系
* 时间连续性

---

# 推荐方案：

# Financial Semantic Chunking

---

# Chunk 类型（非常关键）

## Level 1：Document Chunk

完整年报。

用于：

* 全局分析
* metadata

---

## Level 2：Section Chunk

例如：

* 经营情况讨论
* 风险提示
* 审计意见
* 现金流分析

---

## Level 3：Financial Topic Chunk（核心）

例如：

```text
应收账款
```

必须绑定：

* 报表项
* 附注
* 董事会解释
* 历史趋势

形成：

# Financial Topic Pack

例如：

```json
{
  "topic": "应收账款",
  "fs_items": [],
  "notes": [],
  "management_discussion": [],
  "historical_trend": [],
  "external_data": []
}
```

这才是真正适合 AI 分析的上下文。

---

# 四、你真正需要的不是RAG，而是：

# Financial Memory System

普通 RAG 不够。

因为财报分析不是：

```text
查资料
```

而是：

```text
证据推理
```

---

# 推荐：

# 三层记忆系统

---

# Layer 1：Raw Knowledge Base

存：

* 原始 chunk
* markdown
* pdf page
* embedding

用于：

* 追溯
* 原文引用

技术：

* pgvector
* Milvus
* Elasticsearch

---

# Layer 2：Structured Financial Facts（核心）

这是最重要层。

存：

```json
{
  "company": "",
  "year": 2024,
  "metric": "accounts_receivable",
  "value": 12.3e8,
  "source_note": "附注七",
  "confidence": 0.93
}
```

这是：

# Financial Fact Store

推荐：

PostgreSQL。

不要图数据库起步。

---

# Layer 3：Financial Event Memory

例如：

```text
2022：更换审计机构
2023：商誉减值异常
2024：经营现金流恶化
```

Agent 分析时：
直接读取。

这层会极大提升长期分析能力。

---

# 五、附注映射系统（极重要）

这是整个系统护城河之一。

你已经意识到了。

---

# 核心目标

建立：

# FS Item ↔ Note Mapping

例如：

```text
资产负债表：
应收账款

↕

附注七、5 应收账款
```

---

# 推荐方案

## Step1：规则映射

利用：

* “详见附注”
* “注释”
* 标题相似度

先做80%。

---

## Step2：AI语义对齐

处理：

* 标题变化
* 复杂引用
* 隐式关联

---

# 六、分析前是否预处理？

答案：

# 必须预处理

不要直接分析原文。

---

# 推荐：

# 两阶段 AI

---

# Stage1：Financial Extraction Agent

负责：

## 抽取：

* 财务指标
* 风险事件
* 会计政策
* 审计异常
* 管理层解释
* 风险因子

输出：

结构化 JSON。

---

# Stage2：Reasoning Agent

再做：

* 三表联动
* 风险推理
* 规则判断
* 证据链

这是最优架构。

---

# 七、Skill 系统应该怎么设计（重点）

你现在 skill 太“大一统”了。

后期会崩。

---

# 推荐：

# Skill Graph Architecture

---

# 不要：

```text
一个超级Prompt
```

---

# 而是：

## 基础 Skill

### 1. fs-extractor

抽取三表数据

### 2. note-extractor

抽取附注

### 3. audit-opinion-analyzer

### 4. governance-risk-analyzer

### 5. cashflow-quality-analyzer

### 6. revenue-quality-analyzer

### 7. receivable-risk-analyzer

### 8. goodwill-risk-analyzer

### 9. forensic-rule-engine

### 10. evidence-chain-builder

---

# 上层 Orchestrator

负责：

* 动态调度 skill
* 判断数据是否足够
* 缺失数据降级
* 组织最终报告

---

# 八、多 Agent 是否需要？

答案：

# 第二阶段再上。

---

# 第一阶段：

推荐：

# 单 Orchestrator + Tool Skills

够了。

---

# 第二阶段：

再演进：

## 1. Parsing Agent

负责文档

## 2. Financial Extraction Agent

## 3. Forensic Agent

## 4. Industry Comparison Agent

## 5. Contradiction Detection Agent

## 6. Report Writing Agent

---

# 九、推荐技术架构（非常重要）

# Backend

你会 Python：

推荐：

## FastAPI

核心原因：

* AI生态最好
* LangGraph兼容
* 异步能力强

---

# Workflow

推荐：

## LangGraph

不要一开始上 AutoGen。

原因：

金融分析：
需要：

* 可控
* 可追溯
* 可恢复

LangGraph 更适合。

---

# Storage

## PostgreSQL（核心）

存：

* financial facts
* task state
* metadata

---

## pgvector

做向量检索。

不要一开始上 Milvus。

---

## Elasticsearch（可选）

做：

* 全文检索
* 财报原文搜索

---

# Object Storage

MinIO / OSS

存：

* pdf
* markdown
* parsed json

---

# 十、你真正应该建立的数据模型（关键）

核心实体：

---

# Company

---

# Filing

```text
公司某年某季度财报
```

---

# Financial Statement Item

---

# Note

---

# Financial Fact

---

# Risk Signal

---

# Evidence

---

# Event

---

# Analysis Report

---

# 十一、推荐的实际执行流程（生产级）

# Step1

PDF上传

---

# Step2

Docling解析

---

# Step3

结构修复

---

# Step4

Financial AST生成

---

# Step5

附注绑定

---

# Step6

结构化抽取

---

# Step7

Financial Fact Store入库

---

# Step8

风险规则引擎

---

# Step9

Agent推理分析

---

# Step10

报告生成

---

# 十二、你当前 skill 最大问题（重要）

你现在 skill：

优点：

* 非常专业
* 规则体系完整
* 财务逻辑成熟

问题：

# 太“静态 Prompt 化”

未来会：

* 超长
* 不可维护
* 不可组合
* 不可调度
* 不可演进

---

# 正确方向：

## Prompt → Skill Graph → Financial Cognitive System

这是你的演进方向。

---

# 十三、我建议你下一阶段优先做什么（路线图）

# Phase 1（现在最重要）

## 做高质量 Financial Extraction Pipeline

优先级最高。

因为：

> 数据质量决定天花板。

---

# Phase 2

建立：

## Financial Fact Store

---

# Phase 3

拆 Skill

---

# Phase 4

建立长期公司记忆

---

# Phase 5

多Agent

---

# 十四、最终推荐架构（建议你采用）

# 最优解（当前阶段）

```text
PDF
→ Docling
→ 文档修复
→ Financial AST
→ Chunking
→ Financial Extraction
→ Fact Store
→ Rule Engine
→ AI Reasoning
→ Report
```

而不是：

```text
PDF
→ Markdown
→ 全量塞给GPT
→ 输出报告
```

后者后期一定失控。

---

# 十五、你这个系统未来真正的护城河

不是：

* LLM
* Prompt
* RAG

而是：

# Financial Structured Intelligence

具体包括：

1. 财报结构化能力
2. 附注映射能力
3. Financial Fact Store
4. 多年连续记忆
5. 规则+AI混合推理
6. 财务证据链
7. 动态 Skill Graph

这些才是壁垒。

---

下一步我建议我们可以继续深入以下任意一个方向：

1. 财报解析与修复 Pipeline 详细设计
2. Financial AST 数据结构设计
3. Chunking 与附注映射算法
4. Financial Fact Store 表结构
5. Skill Graph 架构设计
6. LangGraph 工作流设计
7. 多 Agent 协作架构
8. 财务规则引擎设计
9. 财报分析 Prompt 工程
10. 成本优化与 Token 策略
11. RAG vs Fact Store 混合架构
12. 如何做“长期公司记忆”
13. 如何做财务证据链与可解释性
14. 如何做财务异常检测模型
15. 如何做行业横向对比系统
