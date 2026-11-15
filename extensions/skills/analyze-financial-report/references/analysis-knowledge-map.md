# Analysis knowledge map

这个文件是本 skill 的**导航页**。

它负责回答三件事：
1. 当前任务该先落到哪几个分析模块
2. 每个模块优先该看哪些章节与附注
3. 需要进一步展开时，应该去读哪个内部知识文件

它**不负责**承载全部细节。更完整的知识已经按主题拆到 `references/` 目录下，避免重复堆叠。

---

## How to use this map

推荐顺序：
1. 先按 `SKILL.md` 完成报告定位、Markdown 检查、索引检查
2. 先读索引，确定关键章节与 children
3. 先读本文件，判断当前任务属于哪几个分析模块
4. 再读取对应的内部知识文件，优先抓：
   - 关键核查问题
   - 高风险信号
   - 风险含义
   - 优先证据位置
   - 追加回查动作
5. 形成主线判断后，再决定是否扩大阅读范围

不要把这个 map 当成唯一知识源；它负责分流，其他 references 文件负责提供可执行细节。

---

## Quick trigger routing

当用户问题或已读章节里命中下面这些词，优先这样跳转：

- **回款、应收、票据、合同资产、销售收现、账期拉长**
  - 先进入 **经营与资产质量**
  - 优先读：`references/asset-quality-and-capital-allocation.md`
  - 若需要把收入、应收、现金串成闭环，再补 `references/liability-profit-cashflow-linkage.md`

- **存货、预付款、其他应收款、跌价准备、渠道压货**
  - 先进入 **经营与资产质量**
  - 优先读：`references/asset-quality-and-capital-allocation.md`

- **固定资产、在建工程、转固、折旧、开发支出、商誉、扩产、并购溢价**
  - 先进入 **资本开支与长期资产**
  - 优先读：`references/asset-quality-and-capital-allocation.md`
  - 若并购因素明显，再补 `references/governance-and-fraud-signals.md`

- **短债、现金债务比、高现金高负债、再融资、分红、股份支付、预计负债**
  - 先进入 **负债与资本结构**
  - 优先读：`references/liability-profit-cashflow-linkage.md`
  - 若涉及现金债务比等特定口径，再补 `references/terminology-and-metric-conventions.md`

- **毛利率、费用率、扣非、投资收益、公允价值、有效税率、净利润含金量**
  - 先进入 **利润质量**
  - 优先读：`references/liability-profit-cashflow-linkage.md`
  - 若涉及有效税率、净利润含金量等特定口径，再补 `references/terminology-and-metric-conventions.md`

- **CFO、销售收现比、自由现金流、现金流画像、借新还旧、融资续命、现金流补充资料**
  - 先进入 **现金流质量**
  - 优先读：`references/liability-profit-cashflow-linkage.md`
  - 若涉及销售收现比、自由现金流、现金流画像等特定口径，再补 `references/terminology-and-metric-conventions.md`

- **三表联动、不闭环、附注验证、管理层解释、历史对比、同行对比**
  - 先进入 **三表联动与附注下钻**
  - 优先读：`references/liability-profit-cashflow-linkage.md`
  - 若需要先重建分析顺序和扩大回查规则，再补 `references/analysis-principles.md`

- **关联交易、收入粉饰、费用资本化、洗大澡、现金流包装、并购并表、募投变更、审计师变动、高管异动**
  - 先进入 **治理与欺诈信号**
  - 优先读：`references/governance-and-fraud-signals.md`
  - 若需要先判断是否值得继续深挖，再补 `references/analysis-principles.md`

### 常见起手路由

- **用户只说“先排雷 / 有没有明显雷点 / 值不值得继续跟”**
  - 先走：**前置排雷** → **现金流质量** → **负债与资本结构** → **治理与欺诈信号**

- **用户只说“重点看利润质量”**
  - 先走：**利润质量** → **现金流质量** → **三表联动与附注下钻**

- **用户只说“重点看回款、应收、存货”**
  - 先走：**经营与资产质量** → **现金流质量** → **三表联动与附注下钻**

- **用户只说“重点看资本开支、扩产、商誉”**
  - 先走：**资本开支与长期资产** → **三表联动与附注下钻** → 必要时补 **治理与欺诈信号**

---

## Internal knowledge files

### `references/terminology-and-metric-conventions.md`
放术语与口径统一：
- 现金债务比、有息负债率、生产资产占比等公式口径
- 轻重资产判断、现金流肖像、净利润含金量等经验型定义
- 销售收现比、票据背书修正、真实营收还原等修正规则
- 常用经验阈值与工程口径说明

### `references/analysis-principles.md`
放跨模块通用原则：
- 前置排雷
- 先看什么后看什么
- 何时扩大回查
- 历史/同行对比纪律
- 输出判断原则

### `references/asset-quality-and-capital-allocation.md`
放资产侧知识：
- 货币资金、应收、票据、合同资产、存货
- 预付款、其他应收款、长期应收款
- 固定资产、在建工程、开发支出、商誉
- 非主业资产、金融投资、资本开支回报

### `references/liability-profit-cashflow-linkage.md`
放负债、利润、现金流与三表联动知识：
- 债务结构、流动性、预计负债、分红与激励
- 收入、毛利率、费用率、扣非、非经常性项目
- CFO 质量、投资/筹资现金流
- 收入—应收—现金、利润—CFO、资本开支—回报闭环

### `references/governance-and-fraud-signals.md`
放治理与高风险信号：
- 会计师与高管异动
- 并购并表与募投质量
- 关联交易、或有事项、日后事项
- 收入粉饰、费用资本化、洗大澡、现金流包装

---

## Module routing

### 1. 前置排雷
**先回答什么：**
- 这份年报是否值得继续深挖
- 报表可信度是否已经被审计、重述、口径变化或治理异常削弱

**优先看哪里：**
- 审计报告
- 重要提示 / 重大风险
- 主要财务指标
- 重要会计政策及会计估计
- 公司治理
- 重要事项

**优先读哪个知识文件：**
- `references/analysis-principles.md`
- 如治理异常明显，再读 `references/governance-and-fraud-signals.md`

---

### 2. 经营与资产质量
**先回答什么：**
- 回款质量是否恶化
- 经营性资产是否在积压、占款或换科目掩盖风险

**优先看哪里：**
- 合并资产负债表
- 合并现金流量表
- 应收票据 / 应收账款 / 合同资产 / 存货附注
- 主营业务分析、资产及负债状况分析

**优先读哪个知识文件：**
- `references/asset-quality-and-capital-allocation.md`
- 如需联动看收现与三表闭环，再读 `references/liability-profit-cashflow-linkage.md`

---

### 3. 资本开支与长期资产
**先回答什么：**
- 长期投入是否形成真实产能和回报
- 是否存在延迟转固、延迟折旧、减值偏轻、资本化过激进

**优先看哪里：**
- 投资状况分析
- 资产及负债状况分析
- 固定资产 / 在建工程 / 开发支出 / 商誉附注
- 合并范围的变更

**优先读哪个知识文件：**
- `references/asset-quality-and-capital-allocation.md`
- 如并购因素明显，再读 `references/governance-and-fraud-signals.md`

---

### 4. 负债与资本结构
**先回答什么：**
- 债务压力是否上升
- CFO 是否依赖拖供应商款项
- 股东回报是否站得住

**优先看哪里：**
- 合并资产负债表
- 合并现金流量表
- 现金流量表补充资料
- 借款、应付、预计负债、合同负债、权益变动附注
- 股份变动及股东情况

**优先读哪个知识文件：**
- `references/liability-profit-cashflow-linkage.md`
- 如涉及担保、诉讼、股东行为，再读 `references/governance-and-fraud-signals.md`

---

### 5. 利润质量
**先回答什么：**
- 利润来自主营改善，还是来自并表、提价、一次性项目、会计处理
- 扣非后利润是否仍然成立

**优先看哪里：**
- 合并利润表
- 主要财务指标
- 主营业务分析
- 收入、成本、费用、投资收益、税项、减值附注
- 关联方及关联交易

**优先读哪个知识文件：**
- `references/liability-profit-cashflow-linkage.md`
- 如涉及异常客户、毛利率失真、收入粉饰，再读 `references/governance-and-fraud-signals.md`

---

### 6. 现金流质量
**先回答什么：**
- 利润能否变现
- 投资是扩张性投入还是资金黑洞
- 筹资是主动优化还是被动续命

**优先看哪里：**
- 合并现金流量表
- 现金流补充资料
- 与应收、存货、借款、资本开支对应的附注节点

**优先读哪个知识文件：**
- `references/liability-profit-cashflow-linkage.md`

---

### 7. 三表联动与附注下钻
**先回答什么：**
- 收入—应收—现金是否闭环
- 利润—经营现金流是否闭环
- 资本开支—回报是否闭环
- 主表异常能否在附注与管理层叙事中得到可信解释

**优先看哪里：**
- 三张主表
- 权益变动表与现金流补充资料
- 对应异常科目的附注 children
- 管理层讨论与分析中的相关 children

**优先读哪个知识文件：**
- `references/liability-profit-cashflow-linkage.md`
- 如涉及项目、客户、并表、募投，再配合 `references/asset-quality-and-capital-allocation.md` 或 `references/governance-and-fraud-signals.md`

---

### 8. 治理与欺诈信号
**先回答什么：**
- 治理变化是否与财务异常同向
- 是否存在收入粉饰、费用资本化、洗大澡、现金流包装等高风险迹象

**优先看哪里：**
- 公司治理
- 股份变动及股东情况
- 重要事项
- 关联交易、股份支付、商誉、合并范围、或有事项、日后事项附注
- 审计报告

**优先读哪个知识文件：**
- `references/governance-and-fraud-signals.md`
- 如需先重建分析顺序，再回看 `references/analysis-principles.md`

---

## Escalation rule

默认只读最小必要章节。只有出现这些情况时，才扩大回查：
- 非标审计、强调事项、持续经营提示
- 收入、利润、经营现金流明显背离
- 应收、存货、在建工程、商誉、其他应收款异常放大
- 高现金与高有息负债并存
- 大额减值、追溯重述、会计政策变更
- 关联交易、担保、诉讼、并购并表变化明显
- 管理层解释与数字不闭环

扩大回查时，优先顺序：
1. 对应异常科目的附注 children
2. `财务报告-关联方及关联交易`、`财务报告-合并范围的变更`、`财务报告-承诺及或有事项`、`财务报告-资产负债表日后事项` 等专题顶层节点
3. 管理层讨论与分析的相关 children
4. 重要会计政策及会计估计
5. 治理、股东、合并范围、重大投资、募集资金等直接相关章节
6. 相关内部知识文件中的追加分析动作

---

## Synthesis reminder

输出时，不要按 8 个模块机械写成 8 段。
更好的做法是：
1. 先给一句话主线判断
2. 再归纳 3-5 个最关键发现
3. 每个发现尽量写清：现象、风险含义、证据位置、待验证点
4. 若存在立即排除信号，要直接说明
5. 若证据仍不闭环，要明确写成风险，而不是替公司补解释
