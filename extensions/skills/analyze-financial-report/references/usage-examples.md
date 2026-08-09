# Usage examples

这个文件展示 analyze-financial-report skill 的典型工作流，以及**如何从任务类型跳到 skill 内部的分类知识文件**。

它不是某家公司的固定答案模板，而是帮助你判断：
- 什么时候该先校验 `report_path`
- 什么时候该先补同级索引
- 什么时候该开始分析
- 分析时应优先调用哪组内部知识文件
- 什么时候只看关键章节，什么时候要按异常回查附注

统一前提：
1. 用户必须显式提供 `report_path`
2. 先确认 Markdown 存在
3. 再确认同级索引是否存在
4. 缺索引就同级补索引
5. 先读关键章节
6. 再用 `references/analysis-knowledge-map.md` 导航到对应的内部知识文件
7. 若出现特定指标、经验阈值、现金流画像或修正规则，再补读 `references/terminology-and-metric-conventions.md`
8. 只有异常触发时，才扩大到附注、管理层讨论、历史和同行
9. 除了在聊天中输出结果，还要把最终分析 Markdown 写到 `output_path` 或默认同级路径

---

## 1. 已有报告，直接分析

### 用户意图示例
- 帮我分析 `reports/company-a/annual-report-2024.md`
- 看一下这份 Markdown 年报，重点判断利润质量和现金流

### skill 应做的事
1. 确认 `report_path` 是 Markdown 且存在
2. 检查同级对应索引是否存在
3. 若索引已存在，先读取索引
4. 先读关键章节，再按任务重点调用相应内部知识文件
5. 把最终分析写到：
   - 用户给的 `output_path`
   - 或默认同级 `<report_stem>.analysis.md`

### 默认知识路径
- 若用户没限定主题：先读 `references/analysis-principles.md` 做前置排雷
- 若过程中出现现金债务比、现金流肖像、净利润含金量、销售收现比、有效税率等非纯通用术语，再补读 `references/terminology-and-metric-conventions.md`
- 再根据主线，进入：
  - `references/liability-profit-cashflow-linkage.md`
  - `references/asset-quality-and-capital-allocation.md`
  - `references/governance-and-fraud-signals.md`

### 不应做的事
- 不应直接全文通读
- 不应跳过索引直接读取大段原文
- 不应只停留在 knowledge map 的高层摘要

---

## 2. 有 Markdown，但没有同级索引

### 用户意图示例
- 帮我分析这份新放进来的年报 Markdown
- 先看这份财报有没有明显雷点

### skill 应做的事
1. 确认目标 `report_path` 存在
2. 发现同级没有可用 `sections.json`
3. 调用 `build-annual-report-index` skill 补建索引
4. 显式要求它把索引写到同级 `<report_stem>.sections.json`
5. 索引就绪后，再开始分析
6. 最终把分析写到 `output_path` 或默认同级 `<report_stem>.analysis.md`

### 输出重点
- 已自动补建同级索引
- 当前分析基于哪些关键章节
- 当前主要落到了哪些内部知识文件
- 哪些问题还需要继续回查附注

---

## 3. 缺少 Markdown 路径

### 用户意图示例
- 帮我分析某公司 2024 年财报
- 看下这家公司最新年报有没有雷

### skill 应做的事
1. 不要自动去仓库里替用户找报告
2. 明确要求用户提供 `report_path`
3. 在拿到明确 Markdown 路径前，不进入分析

### 推荐表达
- 先给我这份年报对应的 Markdown 路径，我再按这份报告继续分析。
- 当前这个 skill 需要显式 `report_path`，我先不替你猜路径。

### 不应做的事
- 不应在没有报告原文时凭空分析
- 不应把“没给路径”自动转换成 ticker / company / year 发现流程
- 不应把“找不到文件”伪装成“分析结果”

---

## 4. 用户给了输出路径

### 用户意图示例
- 帮我分析这份年报，并把结果写到 `reports/company-a/annual-report-2024.analysis.md`
- 这份报告直接输出到我指定的 Markdown 路径

### skill 应做的事
1. 先按 `report_path` 走正常分析流程
2. 若用户给了 `output_path`，最终分析报告写到该路径
3. 不再额外写默认同级路径，除非用户明确要求

### 不应做的事
- 不应忽略用户给定的 `output_path`
- 不应一边写指定路径，一边又偷偷回退写到旧的固定目录

---

## 5. 风险导向分析

### 用户意图示例
- 帮我排查这份年报里有没有明显不能碰的信号
- 我只关心财务风险、回款风险和现金流

### skill 应做的事
1. 先按前置排雷模块读审计意见、重要提示、重要事项、公司治理
2. 再优先看：
   - 股份变动及股东情况
   - 资产及负债状况分析
   - 合并现金流量表
   - 现金流量表补充资料
   - 应收、存货、借款、预计负债等附注
3. 输出“是否存在立即排除信号 + 风险集中在哪里”
4. 把最终 Markdown 分析报告写到约定路径

### 内部知识文件路由
- 前置排雷：`references/analysis-principles.md`
- 现金与回款风险：`references/asset-quality-and-capital-allocation.md`
- 三表闭环与现金流验证：`references/liability-profit-cashflow-linkage.md`
- 治理与舞弊雷点：`references/governance-and-fraud-signals.md`

### 不应做的事
- 不应把全部科目平均展开
- 不应把风险导向任务写成泛泛的公司介绍
- 不应发现异常后却不展开到对应内部知识文件拿风险含义

---

## 6. 利润质量导向分析

### 用户意图示例
- 帮我重点看这家公司利润质量是不是扎实
- 看一下收入、毛利、现金流能不能对上

### skill 应做的事
1. 先读利润表、现金流量表、现金流补充资料、主要财务指标
2. 回到管理层讨论中的主营业务分析
3. 再按异常点回查收入、应收、减值、费用、关联方相关附注
4. 输出三表联动是否闭环
5. 把最终 Markdown 分析报告写到约定路径

### 内部知识文件路由
- 利润质量主模块：`references/liability-profit-cashflow-linkage.md`
- 若毛利率、客户、异常定价可疑：`references/governance-and-fraud-signals.md`
- 若涉及应收和存货拖累利润现金含量：`references/asset-quality-and-capital-allocation.md`

### 重点关注的问题
- 收入增长来自需求、份额、提价还是并表
- 毛利率变化是否有业务解释
- 扣非后利润是否明显变弱
- 净利润能否转成经营现金流

---

## 7. 资产质量 / 回款风险导向分析

### 用户意图示例
- 重点看这家公司回款有没有恶化
- 帮我看应收、存货和现金流有没有问题

### skill 应做的事
1. 先看合并资产负债表、合并现金流量表、现金流补充资料、主营业务分析
2. 再按异常回查应收票据、应收账款、合同资产、存货、预付款、其他应收款附注
3. 把收入—应收—收现、存货—销量—毛利率串起来
4. 把最终 Markdown 分析报告写到约定路径

### 内部知识文件路由
- 经营与资产质量：`references/asset-quality-and-capital-allocation.md`
- 三表联动与收现验证：`references/liability-profit-cashflow-linkage.md`
- 若涉及异常客户、渠道和收入粉饰：`references/governance-and-fraud-signals.md`

### 重点关注的问题
- 应收增速是否快于收入
- 合同资产或应收款项融资是否在替代传统应收
- 存货与跌价准备是否匹配销量与景气度
- 预付款和其他应收款是否存在占款或解释模糊

---

## 8. 资本开支与商誉导向分析

### 用户意图示例
- 帮我看这家公司扩产投入值不值
- 重点排查在建工程、固定资产、商誉风险

### skill 应做的事
1. 先看投资状况分析、资产及负债状况分析、资产负债表
2. 再回查固定资产、在建工程、开发支出、商誉、合并范围变更附注
3. 判断资本开支是否形成收入、利润、现金回报闭环
4. 把最终 Markdown 分析报告写到约定路径

### 内部知识文件路由
- 长期资产与资本开支：`references/asset-quality-and-capital-allocation.md`
- 三表回报闭环：`references/liability-profit-cashflow-linkage.md`
- 若涉及并购或商誉风险：`references/governance-and-fraud-signals.md`

### 重点关注的问题
- 固定资产和在建工程增长是否与产能、收入匹配
- 是否存在长期不转固、延迟折旧、减值偏轻
- 开发支出资本化是否过激进
- 商誉是否建立在过度乐观假设上

---

## 9. 负债压力与资本结构导向分析

### 用户意图示例
- 看下这家公司债务压力大不大
- 重点看短债、现金债务比和分红质量

### skill 应做的事
1. 先看负债结构、现金流量表、现金流补充资料、权益变动表
2. 再回查借款、应付、预计负债、合同负债、回购、股份支付、分红相关说明
3. 判断公司是在主动优化资本结构，还是依赖再融资与拖款维持
4. 把最终 Markdown 分析报告写到约定路径

### 内部知识文件路由
- 负债、利润、现金流主线：`references/liability-profit-cashflow-linkage.md`
- 若存在担保、诉讼、股东异常行为：`references/governance-and-fraud-signals.md`
- 若需要先重建排雷顺序：`references/analysis-principles.md`

### 重点关注的问题
- 现金是否足以覆盖一年内到期债务
- CFO 改善是否只是靠应付账款增加
- 是否存在高利润低分红、股东回报弱的问题
- 预计负债是否确认充分

---

## Unified principle

无论用户怎么说，统一遵守这条主线：
1. 先拿到显式 `report_path`
2. 再找同级索引
3. 缺索引就同级补索引
4. 先读关键章节
5. 用 `analysis-knowledge-map.md` 定位到对应的内部知识文件
6. 异常触发时再定向回查附注、管理层讨论、历史和同行
7. 输出结论、证据和待验证问题
8. 把最终 Markdown 报告写到 `output_path` 或默认同级路径

关键提醒：
- `analysis-knowledge-map.md` 是导航，不是唯一知识源
- 其中的 `Quick trigger routing` 用来把“回款、商誉、短债、毛利率、分红、并购并表”等词，快速路由到正确内部知识文件
- 财务知识细节已经拆分到 `references/` 目录下，不再依赖外部参考文件
- 目标始终是“主线判断 + 风险含义 + 证据定位”，不是把知识点整段复述一遍
- 不要回退到旧的 ticker / company / year 自动发现路径假设
