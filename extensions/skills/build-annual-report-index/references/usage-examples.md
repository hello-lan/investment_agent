# Usage examples

这个文件展示的是 **skill 的调用意图与工作流模式**，不是某一家公司的固定分析结论。

## 1. 单年速读 `quick-read`

### 适用场景
- 我只想快速判断一份年报值不值得继续深看
- 我不希望 agent 直接吞下整份年报

### 用户意图示例
- 帮我快速读这份 2024 年年报
- 先按重点章节速读，不要全文通读
- 先做一版低上下文排雷

### skill 应做的事
1. 定位 `report_path`
2. 查找对应 `sections.json` 和 `digest.md`
3. 若 digest 已存在，先读 digest
4. 若 digest 不存在，则只读取 P0：
   - `audit_opinion`
   - `important_matters`
   - `main_business_analysis`
   - `asset_and_liability_analysis`
   - 三张主表
5. 输出一句话结论、关键观察、风险点、回查区段

### 不应做的事
- 不应默认读取整份年报
- 不应把 P2 官样文章拉进上下文

---

## 2. 单年深读 `deep-read`

### 适用场景
- 我已经确认这家公司值得继续看
- 我想把单年年报读得更完整一些

### 用户意图示例
- 深读这份 2024 年报
- 除重点章节外，再把股东、员工和未来展望补上

### skill 应做的事
1. 先执行 `quick-read` 路径
2. 在此基础上扩大到 P1：
   - `shareholders`
   - `employee_info`
   - `future_outlook`
3. 若发现异常，再回查相关附注或相邻区段
4. 更新或生成更完整的 digest

### 不应做的事
- 不应因为“深读”就退化成全文阅读
- 不应跳过已有 digest 和 index

---

## 3. 风险排查 `risk-check`

### 适用场景
- 我主要想排雷
- 我想知道有没有明显不能碰的信号

### 用户意图示例
- 帮我排雷这份年报
- 重点看有没有财务风险、治理风险、回款风险
- 先判断是否值得排除

### skill 应做的事
1. 优先读：
   - `audit_opinion`
   - `important_matters`
   - `asset_and_liability_analysis`
   - `consolidated_cash_flow_statement`
2. 若命中升级触发词，再扩大到：
   - `consolidated_financial_statement_notes`（按异常项目定向回查，不默认整段通读）
   - `main_business_analysis`
   - `shareholders`
3. 输出：
   - 是否存在立即排除信号
   - 风险集中在哪几类项目
   - 下一步最值得回查的区段

### 重点关注的触发词
- 非标审计
- 保留意见
- 强调事项
- 重大诉讼
- 重大担保
- 资金占用
- 关联交易异常
- 债务违约
- 大额减值
- 应收异常
- 现金流恶化

---

## 4. 多年对比 `multi-year-compare`

### 适用场景
- 我想看 2-5 年趋势
- 我不想把多份全文同时塞进上下文

### 用户意图示例
- 对比 2022-2024 三年年报
- 帮我看这家公司近三年的风险焦点有没有变化
- 先看摘要，异常处再回原文

### skill 应做的事
1. 优先查找多个年份的 digest
2. 先比较 digest，不直接并排读取多份原文
3. 提取：
   - 收入/利润变化
   - 现金流质量变化
   - 应收/存货/在建工程变化
   - 负债结构变化
   - 管理层叙事是否一致
4. 只对异常年份的异常区段回查原文
5. 输出趋势主线、风险迁移、待验证问题

### 不应做的事
- 不应默认把 3-5 份年报全文一起读掉
- 不应在没有异常的情况下大规模回查原文

---

## 5. 新年报接入 `index-bootstrap`

### 适用场景
- 来了一份新的年报 Markdown
- 还没有 `sections.json` 和 `digest.md`

### 用户意图示例
- 给这份新年报建立第一版索引
- 不分析结论，先把 skill 所需产物搭起来

### skill 应做的事
1. 先调用 `build-annual-report-index`，按 `index-generation-rules.md` 生成最小可用 `sections.json`
2. 校验标题命中、区段顺序和行号范围
3. 只在需要时再生成第一版 digest

### 输出重点
- 生成了哪些基础产物
- 缺失了哪些标准区段
- 哪些标题是通过近义词匹配得到的

---

## 6. 推荐的用户表达方式

为了让 skill 更稳定，用户请求里最好明确以下元素：

- 年报路径或年份
- 任务类型
- 是否允许回查原文
- 是否只看风险 / 还是要做完整摘要
- 是否做跨年对比

例如：
- 用 `quick-read` 方式读 `reports/company-a/annual-report-2024.md`，不要全文通读
- 用 `risk-check` 方式排查这份年报，优先看审计意见、重要事项和现金流
- 用 `multi-year-compare` 对比 2022-2024，先比较 digest，再回查异常区段

---

## 7. 这些用法背后的统一原则

无论哪种模式，都遵守同一条主线：

1. 先找 index
2. 先找 digest
3. 只读最小必要区段
4. 发现异常再回原文
5. 优先沉淀可复用产物，而不是重复吞全文
