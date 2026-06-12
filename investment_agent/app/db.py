import shutil

import aiosqlite
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..config import get_settings, PROJECT_ROOT


# SQLite 数据库文件路径
DB_PATH = (PROJECT_ROOT / get_settings().get("db", {}).get("sqlite_path", "./data/agent.db")).resolve()


@asynccontextmanager
async def get_db():
    """异步 SQLite 上下文管理器：自动开启/关闭连接，Row 工厂返回字典行"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        yield db


async def _ensure_columns(
    db: aiosqlite.Connection,
    migrations: list[tuple[str, str, str]],
) -> None:
    """批量检查并添加缺失列。

    Args:
        db: 数据库连接
        migrations: (表名, 列名, 类型定义) 列表
    """
    # 按表分组，减少 PRAGMA 调用
    by_table: dict[str, list[tuple[str, str]]] = {}
    for table, col, col_type in migrations:
        by_table.setdefault(table, []).append((col, col_type))

    for table, columns in by_table.items():
        cursor = await db.execute(f"PRAGMA table_info({table})")
        existing = {row[1] for row in await cursor.fetchall()}
        changed = False
        for col, col_type in columns:
            if col not in existing:
                await db.execute(
                    f"ALTER TABLE {table} ADD COLUMN {col} {col_type}"
                )
                changed = True
        if changed:
            await db.commit()


async def init_db() -> None:
    """初始化数据库：建表 + 执行旧结构迁移"""
    async with get_db() as db:
        await db.executescript("""
            -- LLM 模型配置（支持 Anthropic 和 OpenAI 兼容接口）
            CREATE TABLE IF NOT EXISTS models (
                id          TEXT PRIMARY KEY,     -- 主键ID
                name        TEXT NOT NULL,        -- 模型显示名称
                type        TEXT NOT NULL,        -- 模型类型（claude / openai_compat）
                api_key     TEXT DEFAULT '',      -- API 密钥
                model       TEXT NOT NULL,        -- 模型名称（如 claude-sonnet-4-6）
                base_url    TEXT DEFAULT '',      -- API 基础地址
                is_default  INTEGER DEFAULT 0,    -- 是否默认模型（0=否 1=是）
                input_price  REAL,                -- 输入价格（每百万 token）
                output_price REAL,                -- 输出价格（每百万 token）
                currency     TEXT DEFAULT 'USD',  -- 计价货币（USD / CNY）
                created_at  TEXT                  -- 创建时间（ISO8601）
            );

            -- 自定义 Agent 配置（绑定模型、Skills、压缩参数）
            CREATE TABLE IF NOT EXISTS agents (
                id            TEXT PRIMARY KEY,       -- 主键ID
                name          TEXT NOT NULL,          -- Agent 名称
                description   TEXT,                   -- 描述说明
                system_prompt TEXT,                   -- 系统提示词
                model_id      TEXT,                   -- 关联模型 ID
                temperature   REAL DEFAULT 0.7,       -- 模型温度参数（0~1）
                max_tokens    INTEGER DEFAULT 4096,   -- 最大输出 token 数
                skills        TEXT DEFAULT '[]',      -- 启用的技能列表（JSON 数组）
                compress_config TEXT,                 -- 上下文压缩配置（JSON）
                engine_config TEXT,                   -- 引擎运行配置（JSON）
                created_at    TEXT,                   -- 创建时间
                updated_at    TEXT                    -- 更新时间
            );

            -- 对话会话
            CREATE TABLE IF NOT EXISTS sessions (
                id         TEXT PRIMARY KEY,          -- 会话 ID
                agent_id   TEXT,                      -- 关联 Agent ID
                title      TEXT,                      -- 会话标题
                status     TEXT DEFAULT 'active',     -- 状态（active=活跃 running=运行中 archived=归档）
                created_at TEXT                       -- 创建时间
            );

            -- 会话消息（role / content / tool_calls / token_usage）
            CREATE TABLE IF NOT EXISTS messages (
                id          TEXT PRIMARY KEY,         -- 消息 ID
                session_id  TEXT NOT NULL,            -- 所属会话 ID
                role        TEXT NOT NULL,            -- 角色（user / assistant / system / tool）
                content     TEXT,                     -- 消息内容
                tool_calls  TEXT,                     -- 工具调用信息（JSON）
                token_usage TEXT,                     -- Token 用量（JSON）
                created_at  TEXT                      -- 创建时间
            );

            -- 断点续跑状态
            CREATE TABLE IF NOT EXISTS checkpoints (
                task_id    TEXT PRIMARY KEY,          -- 任务 ID
                session_id TEXT,                      -- 所属会话 ID
                step       INTEGER DEFAULT 0,         -- 当前步骤数
                messages   TEXT,                      -- 消息快照（JSON）
                status     TEXT DEFAULT 'running',    -- 状态（running=运行中 completed=已完成）
                updated_at TEXT                       -- 更新时间
            );

            -- Token 成本日志
            CREATE TABLE IF NOT EXISTS cost_log (
                id            TEXT PRIMARY KEY,       -- 记录 ID
                session_id    TEXT,                   -- 所属会话 ID
                task_id       TEXT,                   -- 所属任务 ID
                model         TEXT,                   -- 模型名称
                agent_name    TEXT,                   -- Agent 名称
                input_tokens  INTEGER DEFAULT 0,      -- 输入 Token 数
                output_tokens INTEGER DEFAULT 0,      -- 输出 Token 数
                cache_read_tokens     INTEGER DEFAULT 0,  -- 缓存读取 Token 数
                cache_creation_tokens INTEGER DEFAULT 0,  -- 缓存创建 Token 数
                cache_hit_ratio       REAL DEFAULT 0,     -- 缓存命中率
                cost_usd      REAL DEFAULT 0,         -- 费用（美元）
                currency      TEXT,                   -- 计价货币
                created_at    TEXT                    -- 创建时间
            );

            -- 执行链路追踪日志
            CREATE TABLE IF NOT EXISTS trace_log (
                id         TEXT PRIMARY KEY,          -- 记录 ID
                session_id TEXT,                      -- 所属会话 ID
                task_id    TEXT,                      -- 所属任务 ID
                agent_name TEXT,                      -- Agent 名称（主 Agent / 子 Agent）
                step       INTEGER,                   -- 步骤序号
                event_type TEXT,                      -- 事件类型（tool_call / tool_result / delegate / budget_status 等）
                detail     TEXT,                      -- 事件详情（JSON）
                created_at TEXT                       -- 创建时间
            );

            -- ── 个股看板数据表 ──────────────────────────────────────────

            -- 股票基础信息
            CREATE TABLE IF NOT EXISTS stock_info (
                code        TEXT PRIMARY KEY,  -- 股票代码
                name        TEXT,              -- 股票名称
                industry    TEXT,              -- 所属行业
                market_cap  REAL,              -- 总市值
                listed_date TEXT,              -- 上市日期
                updated_at  TEXT               -- 更新时间
            );

            -- 财务指标：86项 AKShare 指标中选取最常用的40项
            CREATE TABLE IF NOT EXISTS stock_indicators (
                id                      INTEGER PRIMARY KEY AUTOINCREMENT,  -- 自增主键
                code                    TEXT NOT NULL,     -- 股票代码
                report_date             TEXT NOT NULL,     -- 报告期（如 2024-12-31）
                report_type             TEXT DEFAULT 'annual',  -- 报告类型（annual=年报 quarter=季报）
                -- 盈利
                total_revenue           REAL,              -- 营业总收入
                net_profit              REAL,              -- 归母净利润
                net_profit_adjusted     REAL,              -- 扣非归母净利润
                gross_margin            REAL,              -- 毛利率（%）
                net_margin              REAL,              -- 净利率（%）
                roe                     REAL,              -- 净资产收益率 ROE（%）
                roe_diluted             REAL,              -- 摊薄净资产收益率（%）
                roa                     REAL,              -- 总资产收益率 ROA（%）
                -- 成长
                revenue_yoy             REAL,              -- 营收同比增长率（%）
                net_profit_yoy          REAL,              -- 归母净利润同比增长率（%）
                net_profit_adjusted_yoy REAL,              -- 扣非净利润同比增长率（%）
                equity_yoy              REAL,              -- 归属母公司权益同比增长率（%）
                total_assets_yoy        REAL,              -- 总资产同比增长率（%）
                -- 每股
                eps                     REAL,              -- 每股收益 EPS
                bvps                    REAL,              -- 每股净资产 BPS
                cfps                    REAL,              -- 每股经营现金流 CFPS
                -- 偿债
                debt_ratio              REAL,              -- 资产负债率（%）
                current_ratio           REAL,              -- 流动比率
                quick_ratio             REAL,              -- 速动比率
                equity_multiplier       REAL,              -- 权益乘数
                equity_ratio            REAL,              -- 归属于母公司股东权益占比（%）
                -- 营运
                ar_turnover             REAL,              -- 应收账款周转率（次）
                ar_turnover_days        REAL,              -- 应收账款周转天数
                inventory_turnover      REAL,              -- 存货周转率（次）
                inventory_turnover_days REAL,              -- 存货周转天数
                fixed_asset_turnover    REAL,              -- 固定资产周转率（次）
                total_asset_turnover    REAL,              -- 总资产周转率（次）
                -- 现金流
                cfr                     REAL,              -- 经营活动现金流量净额／营收
                cfnp                    REAL,              -- 经营活动现金流量净额／归母净利润
                UNIQUE(code, report_date)
            );

            -- 资产负债表（东方财富完整字段，152项）
            CREATE TABLE IF NOT EXISTS stock_balance (
                id                      INTEGER PRIMARY KEY AUTOINCREMENT,  -- 自增主键
                code                    TEXT NOT NULL,     -- 股票代码
                report_date             TEXT NOT NULL,     -- 报告期
                report_type             TEXT,              -- 报告类型
                accept_deposit_interbank REAL,  -- 吸收存款及同业存放
                accounts_payable REAL,          -- 应付账款
                accounts_rece REAL,             -- 应收账款
                accrued_expense REAL,           -- 预提费用
                advance_receivables REAL,       -- 预收款项
                agent_trade_security REAL,      -- 代理买卖证券款
                agent_underwrite_security REAL, -- 代理承销证券款
                amortize_cost_finasset REAL,    -- 以摊余成本计量的金融资产
                amortize_cost_finliab REAL,     -- 以摊余成本计量的金融负债
                amortize_cost_ncfinasset REAL,  -- 以摊余成本计量的非流动金融资产
                amortize_cost_ncfinliab REAL,   -- 以摊余成本计量的非流动金融负债
                appoint_fvtpl_finasset REAL,    -- 指定以公允价值计量且变动计入当期损益的金融资产
                appoint_fvtpl_finliab REAL,     -- 指定以公允价值计量且变动计入当期损益的金融负债
                asset_balance REAL,             -- 资产平衡项目
                asset_other REAL,               -- 资产其他项目
                assign_cash_dividend REAL,      -- 应付股利
                available_sale_finasset REAL,   -- 可供出售金融资产
                bond_payable REAL,              -- 应付债券
                borrow_fund REAL,               -- 拆入资金
                buy_resale_finasset REAL,       -- 买入返售金融资产
                capital_reserve REAL,           -- 资本公积
                cip REAL,                       -- 在建工程
                consumptive_biological_asset REAL,  -- 消耗性生物资产
                contract_asset REAL,            -- 合同资产
                contract_liab REAL,             -- 合同负债
                convert_diff REAL,              -- 外币报表折算差额
                creditor_invest REAL,           -- 债权投资
                current_asset_balance REAL,     -- 流动资产平衡项目
                current_asset_other REAL,       -- 流动资产其他项目
                current_liab_balance REAL,      -- 流动负债平衡项目
                current_liab_other REAL,        -- 流动负债其他项目
                defer_income REAL,              -- 递延收益
                defer_income_1year REAL,        -- 一年内到期的递延收益
                defer_tax_asset REAL,           -- 递延所得税资产
                defer_tax_liab REAL,            -- 递延所得税负债
                derive_finasset REAL,           -- 衍生金融资产
                derive_finliab REAL,            -- 衍生金融负债
                develop_expense REAL,           -- 开发支出
                div_holdsale_asset REAL,        -- 持有待售资产
                div_holdsale_liab REAL,         -- 持有待售负债
                dividend_payable REAL,          -- 应付股利
                dividend_rece REAL,             -- 应收股利
                equity_balance REAL,            -- 股东权益平衡项目
                equity_other REAL,              -- 股东权益其他项目
                export_refund_rece REAL,        -- 应收出口退税
                fee_commission_payable REAL,    -- 应付手续费及佣金
                fin_fund REAL,                  -- 财务基金
                finance_rece REAL,              -- 应收融资租赁款
                fixed_asset REAL,               -- 固定资产
                fixed_asset_disposal REAL,      -- 固定资产清理
                fvtoci_finasset REAL,           -- 以公允价值计量且变动计入其他综合收益的金融资产
                fvtoci_ncfinasset REAL,         -- 以公允价值计量且变动计入其他综合收益的非流动金融资产
                fvtpl_finasset REAL,            -- 交易性金融资产
                fvtpl_finliab REAL,             -- 交易性金融负债
                general_risk_reserve REAL,      -- 一般风险准备
                goodwill REAL,                  -- 商誉
                hold_maturity_invest REAL,      -- 持有至到期投资
                holdsale_asset REAL,            -- 持有待售资产
                holdsale_liab REAL,             -- 持有待售负债
                insurance_contract_reserve REAL, -- 保险合同准备金
                intangible_asset REAL,           -- 无形资产
                interest_payable REAL,           -- 应付利息
                interest_rece REAL,              -- 应收利息
                internal_payable REAL,           -- 内部应付
                internal_rece REAL,              -- 内部应收
                inventory REAL,                  -- 存货
                invest_realestate REAL,          -- 投资性房地产
                lease_liab REAL,                 -- 租赁负债
                lend_fund REAL,                  -- 拆出资金
                liab_balance REAL,               -- 负债平衡项目
                liab_equity_balance REAL,        -- 负债和股东权益总计
                liab_equity_other REAL,          -- 负债和股东权益其他项目
                liab_other REAL,                 -- 负债其他项目
                loan_advance REAL,               -- 发放贷款及垫款
                loan_pbc REAL,                   -- 向中央银行借款
                long_equity_invest REAL,         -- 长期股权投资
                long_loan REAL,                  -- 长期借款
                long_payable REAL,              -- 长期应付款
                long_prepaid_expense REAL,      -- 长期待摊费用
                long_rece REAL,                 -- 长期应收款
                long_staffsalary_payable REAL,  -- 长期应付职工薪酬
                minority_equity REAL,           -- 少数股东权益
                monetaryfunds REAL,             -- 货币资金
                noncurrent_asset_1year REAL,    -- 一年内到期的非流动资产
                noncurrent_asset_balance REAL,  -- 非流动资产平衡项目
                noncurrent_asset_other REAL,    -- 非流动资产其他项目
                noncurrent_liab_1year REAL,     -- 一年内到期的非流动负债
                noncurrent_liab_balance REAL,   -- 非流动负债平衡项目
                noncurrent_liab_other REAL,     -- 非流动负债其他项目
                note_accounts_payable REAL,     -- 应付票据
                note_accounts_rece REAL,        -- 应收票据
                note_payable REAL,              -- 应付票据
                note_rece REAL,                 -- 应收票据
                oil_gas_asset REAL,             -- 油气资产
                other_compre_income REAL,       -- 其他综合收益
                other_creditor_invest REAL,     -- 其他债权投资
                other_current_asset REAL,       -- 其他流动资产
                other_current_liab REAL,        -- 其他流动负债
                other_equity_invest REAL,       -- 其他权益工具投资
                other_equity_other REAL,        -- 其他权益工具
                other_equity_tool REAL,         -- 其他权益工具
                other_noncurrent_asset REAL,    -- 其他非流动资产
                other_noncurrent_finasset REAL, -- 其他非流动金融资产
                other_noncurrent_liab REAL,     -- 其他非流动负债
                other_payable REAL,             -- 其他应付款
                other_rece REAL,                -- 其他应收款
                parent_equity_balance REAL,     -- 归属于母公司股东权益合计
                parent_equity_other REAL,       -- 归属于母公司股东权益其他项目
                perpetual_bond REAL,            -- 永续债
                perpetual_bond_paybale REAL,    -- 应付永续债
                predict_current_liab REAL,      -- 预计流动负债
                predict_liab REAL,              -- 预计负债
                preferred_shares REAL,          -- 优先股
                preferred_shares_paybale REAL,  -- 应付优先股
                premium_rece REAL,              -- 应收保费
                prepayment REAL,                -- 预付款项
                productive_biology_asset REAL,  -- 生产性生物资产
                project_material REAL,          -- 工程物资
                rc_reserve_rece REAL,           -- 应收分保准备金
                reinsure_payable REAL,          -- 应付分保账款
                reinsure_rece REAL,             -- 应收分保账款
                sell_repo_finasset REAL,        -- 卖出回购金融资产款
                settle_excess_reserve REAL,     -- 结算备付金
                share_capital REAL,             -- 股本
                short_bond_payable REAL,        -- 应付短期债券
                short_fin_payable REAL,         -- 应付短期融资
                short_loan REAL,                -- 短期借款
                special_payable REAL,           -- 专项应付款
                special_reserve REAL,           -- 专项储备
                staff_salary_payable REAL,      -- 应付职工薪酬
                subsidy_rece REAL,              -- 应收补贴款
                surplus_reserve REAL,           -- 盈余公积
                tax_payable REAL,               -- 应交税费
                total_assets REAL,              -- 资产总计
                total_current_assets REAL,      -- 流动资产合计
                total_current_liab REAL,        -- 流动负债合计
                total_equity REAL,              -- 股东权益合计
                total_liab_equity REAL,         -- 负债和股东权益总计
                total_liabilities REAL,         -- 负债合计
                total_noncurrent_assets REAL,   -- 非流动资产合计
                total_noncurrent_liab REAL,     -- 非流动负债合计
                total_other_payable REAL,       -- 其他应付款合计
                total_other_rece REAL,          -- 其他应收款合计
                total_parent_equity REAL,       -- 归属于母公司股东权益合计
                trade_finasset REAL,            -- 交易性金融资产
                trade_finasset_notfvtpl REAL,   -- 非交易性金融资产
                trade_finliab REAL,             -- 交易性金融负债
                trade_finliab_notfvtpl REAL,    -- 非交易性金融负债
                treasury_shares REAL,           -- 库存股
                unassign_rpofit REAL,           -- 未分配利润
                unconfirm_invest_loss REAL,     -- 未确认投资损失
                useright_asset REAL,            -- 使用权资产
                UNIQUE(code, report_date)
            );

            -- 利润表（东方财富完整字段，95项）
            CREATE TABLE IF NOT EXISTS stock_income (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,  -- 自增主键
                code              TEXT NOT NULL,     -- 股票代码
                report_date       TEXT NOT NULL,     -- 报告期
                report_type       TEXT,              -- 报告类型
                total_operate_income REAL,   -- 营业总收入
                operate_income REAL,         -- 营业收入
                interest_income REAL,        -- 利息收入
                earned_premium REAL,         -- 已赚保费
                fee_commission_income REAL,  -- 手续费及佣金收入
                other_business_income REAL,  -- 其他业务收入
                toi_other REAL,              -- 营业总收入其他项目
                total_operate_cost REAL,     -- 营业总成本
                operate_cost REAL,           -- 营业成本
                interest_expense REAL,       -- 利息支出
                fee_commission_expense REAL, -- 手续费及佣金支出
                research_expense REAL,       -- 研发费用
                surrender_value REAL,        -- 退保金
                net_compensate_expense REAL, -- 赔付支出净额
                net_contract_reserve REAL,   -- 提取保险合同准备金净额
                policy_bonus_expense REAL,   -- 保单红利支出
                reinsure_expense REAL,       -- 分保费用
                other_business_cost REAL,    -- 其他业务成本
                operate_tax_add REAL,        -- 营业税金及附加
                sale_expense REAL,           -- 销售费用
                manage_expense REAL,         -- 管理费用
                me_research_expense REAL,    -- 管理费用中的研发费用
                finance_expense REAL,        -- 财务费用
                fe_interest_expense REAL,    -- 财务费用-利息支出
                fe_interest_income REAL,     -- 财务费用-利息收入
                asset_impairment_loss REAL,  -- 资产减值损失
                credit_impairment_loss REAL, -- 信用减值损失
                toc_other REAL,              -- 营业总成本其他项目
                fairvalue_change_income REAL, -- 公允价值变动收益
                invest_income REAL,           -- 投资收益
                invest_joint_income REAL,     -- 对联营和合营企业投资收益
                net_exposure_income REAL,     -- 净敞口套期收益
                exchange_income REAL,         -- 汇兑收益
                asset_disposal_income REAL,   -- 资产处置收益
                asset_impairment_income REAL, -- 资产减值损失转回
                credit_impairment_income REAL, -- 信用减值损失转回
                other_income REAL,            -- 其他收益
                operate_profit_other REAL,    -- 营业利润其他项目
                operate_profit_balance REAL,  -- 营业利润平衡项目
                operate_profit REAL,          -- 营业利润
                nonbusiness_income REAL,      -- 营业外收入
                noncurrent_disposal_income REAL, -- 非流动资产处置利得
                nonbusiness_expense REAL,     -- 营业外支出
                noncurrent_disposal_loss REAL, -- 非流动资产处置损失
                effect_tp_other REAL,         -- 影响利润总额其他项目
                total_profit_balance REAL,    -- 利润总额平衡项目
                total_profit REAL,            -- 利润总额
                income_tax REAL,              -- 所得税费用
                effect_netprofit_other REAL,  -- 影响净利润其他项目
                effect_netprofit_balance REAL, -- 影响净利润平衡项目
                unconfirm_invest_loss REAL,   -- 未确认投资损失
                netprofit REAL,               -- 净利润
                precombine_profit REAL,       -- 被合并方在合并前实现利润
                continued_netprofit REAL,     -- 持续经营净利润
                discontinued_netprofit REAL,  -- 终止经营净利润
                parent_netprofit REAL,        -- 归母净利润
                minority_interest REAL,       -- 少数股东损益
                deduct_parent_netprofit REAL, -- 扣非归母净利润
                netprofit_other REAL,         -- 净利润其他项目
                netprofit_balance REAL,       -- 净利润平衡项目
                basic_eps REAL,               -- 基本每股收益
                diluted_eps REAL,             -- 稀释每股收益
                other_compre_income REAL,     -- 其他综合收益总额
                parent_oci REAL,              -- 归属于母公司的其他综合收益
                minority_oci REAL,            -- 归属于少数股东的其他综合收益
                parent_oci_other REAL,        -- 归属母公司其他综合收益其他项目
                parent_oci_balance REAL,      -- 归属母公司其他综合收益平衡项目
                unable_oci REAL,              -- 不能重分类进损益的其他综合收益
                creditrisk_fairvalue_change REAL, -- 信用风险公允价值变动
                otherright_fairvalue_change REAL, -- 其他权益工具投资公允价值变动
                setup_profit_change REAL,     -- 设定受益计划净变动
                rightlaw_unable_oci REAL,     -- 其他不能重分类进损益项目
                unable_oci_other REAL,        -- 不能重分类进损益其他项目
                unable_oci_balance REAL,      -- 不能重分类进损益平衡项目
                able_oci REAL,                -- 将重分类进损益的其他综合收益
                rightlaw_able_oci REAL,       -- 其他将重分类进损益项目
                afa_fairvalue_change REAL,    -- 可供出售金融资产公允价值变动
                hmi_afa REAL,                 -- 持有至到期投资重分类
                cashflow_hedge_valid REAL,    -- 现金流量套期有效部分
                creditor_fairvalue_change REAL, -- 其他债权投资公允价值变动
                creditor_impairment_reserve REAL, -- 其他债权投资信用减值准备
                finance_oci_amt REAL,         -- 金融资产重分类计入其他综合收益
                convert_diff REAL,            -- 外币报表折算差额
                able_oci_other REAL,          -- 将重分类进损益其他项目
                able_oci_balance REAL,        -- 将重分类进损益平衡项目
                oci_other REAL,               -- 其他综合收益其他项目
                oci_balance REAL,             -- 其他综合收益平衡项目
                total_compre_income REAL,     -- 综合收益总额
                parent_tci REAL,              -- 归属于母公司综合收益总额
                minority_tci REAL,            -- 归属于少数股东综合收益总额
                precombine_tci REAL,          -- 被合并方在合并前综合收益
                effect_tci_balance REAL,      -- 影响综合收益总额平衡项目
                tci_other REAL,               -- 综合收益总额其他项目
                tci_balance REAL,             -- 综合收益总额平衡项目
                acf_end_income REAL,          -- 期末累积折算差额调整
                UNIQUE(code, report_date)
            );

            -- 现金流量表（东方财富完整字段，120项）
            CREATE TABLE IF NOT EXISTS stock_cashflow (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,  -- 自增主键
                code            TEXT NOT NULL,     -- 股票代码
                report_date     TEXT NOT NULL,     -- 报告期
                report_type     TEXT,              -- 报告类型
                sales_services REAL,               -- 销售商品、提供劳务收到的现金
                deposit_interbank_add REAL,        -- 吸收存款及同业存放净增加额
                loan_pbc_add REAL,                 -- 向中央银行借款净增加额
                ofi_bf_add REAL,                   -- 存放同业及其他金融机构款项净增加额
                receive_origic_premium REAL,       -- 收到原保险合同保费
                receive_reinsure_net REAL,         -- 再保险业务现金净额
                insured_invest_add REAL,           -- 保户储金及投资款净增加额
                disposal_tfa_add REAL,             -- 处置交易性金融资产净增加额
                receive_interest_commission REAL,  -- 收取利息、手续费及佣金
                borrow_fund_add REAL,              -- 拆入资金净增加额
                loan_advance_reduce REAL,          -- 发放贷款及垫款净减少额
                repo_business_add REAL,            -- 回购业务资金净增加额
                receive_tax_refund REAL,           -- 收到税收返还
                receive_other_operate REAL,        -- 收到其他与经营活动有关的现金
                operate_inflow_other REAL,         -- 经营活动现金流入其他项目
                operate_inflow_balance REAL,       -- 经营活动现金流入平衡项目
                total_operate_inflow REAL,         -- 经营活动现金流入小计
                buy_services REAL,                 -- 购买商品、接受劳务支付的现金
                loan_advance_add REAL,             -- 发放贷款及垫款净增加额
                pbc_interbank_add REAL,            -- 存放中央银行和同业款项净增加额
                pay_origic_compensate REAL,        -- 支付原保险合同赔款
                pay_interest_commission REAL,      -- 支付利息、手续费及佣金
                pay_policy_bonus REAL,             -- 支付保单红利
                pay_staff_cash REAL,               -- 支付给职工以及为职工支付的现金
                pay_all_tax REAL,                  -- 支付各项税费
                pay_other_operate REAL,            -- 支付其他与经营活动有关的现金
                operate_outflow_other REAL,        -- 经营活动现金流出其他项目
                operate_outflow_balance REAL,      -- 经营活动现金流出平衡项目
                total_operate_outflow REAL,        -- 经营活动现金流出小计
                operate_netcash_other REAL,        -- 经营活动现金流净额其他项目
                operate_netcash_balance REAL,      -- 经营活动现金流净额平衡项目
                netcash_operate REAL,              -- 经营活动产生的现金流量净额
                withdraw_invest REAL,              -- 收回投资收到的现金
                receive_invest_income REAL,        -- 取得投资收益收到的现金
                disposal_long_asset REAL,          -- 处置固定资产、无形资产等收回的现金净额
                disposal_subsidiary_other REAL,    -- 处置子公司及其他营业单位收到的现金
                reduce_pledge_timedeposits REAL,   -- 减少质押和定期存款所收到的现金
                receive_other_invest REAL,         -- 收到其他与投资活动有关的现金
                invest_inflow_other REAL,          -- 投资活动现金流入其他项目
                invest_inflow_balance REAL,        -- 投资活动现金流入平衡项目
                total_invest_inflow REAL,          -- 投资活动现金流入小计
                construct_long_asset REAL,         -- 购建固定资产、无形资产等支付的现金
                invest_pay_cash REAL,              -- 投资支付的现金
                pledge_loan_add REAL,              -- 质押贷款净增加额
                obtain_subsidiary_other REAL,      -- 取得子公司及其他营业单位支付的现金
                add_pledge_timedeposits REAL,      -- 增加质押和定期存款所支付的现金
                pay_other_invest REAL,             -- 支付其他与投资活动有关的现金
                invest_outflow_other REAL,         -- 投资活动现金流出其他项目
                invest_outflow_balance REAL,       -- 投资活动现金流出平衡项目
                total_invest_outflow REAL,         -- 投资活动现金流出小计
                invest_netcash_other REAL,         -- 投资活动现金流净额其他项目
                invest_netcash_balance REAL,       -- 投资活动现金流净额平衡项目
                netcash_invest REAL,               -- 投资活动产生的现金流量净额
                accept_invest_cash REAL,           -- 吸收投资收到的现金
                subsidiary_accept_invest REAL,     -- 子公司吸收少数股东投资收到的现金
                receive_loan_cash REAL,            -- 取得借款收到的现金
                issue_bond REAL,                   -- 发行债券收到的现金
                receive_other_finance REAL,        -- 收到其他与筹资活动有关的现金
                finance_inflow_other REAL,         -- 筹资活动现金流入其他项目
                finance_inflow_balance REAL,       -- 筹资活动现金流入平衡项目
                total_finance_inflow REAL,         -- 筹资活动现金流入小计
                pay_debt_cash REAL,                -- 偿还债务支付的现金
                assign_dividend_porfit REAL,       -- 分配股利、利润或偿付利息支付的现金
                subsidiary_pay_dividend REAL,      -- 子公司支付给少数股东的股利
                buy_subsidiary_equity REAL,        -- 子公司购买少数股东权益支付的现金
                pay_other_finance REAL,            -- 支付其他与筹资活动有关的现金
                subsidiary_reduce_cash REAL,       -- 子公司减资支付给少数股东的现金
                finance_outflow_other REAL,        -- 筹资活动现金流出其他项目
                finance_outflow_balance REAL,      -- 筹资活动现金流出平衡项目
                total_finance_outflow REAL,        -- 筹资活动现金流出小计
                finance_netcash_other REAL,        -- 筹资活动现金流净额其他项目
                finance_netcash_balance REAL,      -- 筹资活动现金流净额平衡项目
                netcash_finance REAL,              -- 筹资活动产生的现金流量净额
                rate_change_effect REAL,           -- 汇率变动对现金及现金等价物的影响
                cce_add_other REAL,                -- 现金及现金等价物增加额其他项目
                cce_add_balance REAL,              -- 现金及现金等价物增加额平衡项目
                cce_add REAL,                      -- 现金及现金等价物净增加额
                begin_cce REAL,                    -- 期初现金及现金等价物余额
                end_cce_other REAL,                -- 期末现金及现金等价物余额其他项目
                end_cce_balance REAL,              -- 期末现金及现金等价物余额平衡项目
                end_cce REAL,                      -- 期末现金及现金等价物余额
                -- 以下为现金流量表附注（间接法）
                netprofit REAL,                    -- 净利润
                asset_impairment REAL,             -- 资产减值准备
                fa_ir_depr REAL,                   -- 固定资产折旧、油气资产折耗、生产性生物资产折旧
                oilgas_biology_depr REAL,          -- 油气及生物资产折旧
                ir_depr REAL,                      -- 无形资产及投资性房地产折旧
                ia_amortize REAL,                  -- 无形资产摊销
                lpe_amortize REAL,                 -- 长期待摊费用摊销
                defer_income_amortize REAL,        -- 递延收益摊销
                prepaid_expense_reduce REAL,       -- 预提费用减少
                accrued_expense_add REAL,          -- 预提费用增加
                disposal_longasset_loss REAL,      -- 处置固定资产、无形资产等损失
                fa_scrap_loss REAL,                -- 固定资产报废损失
                fairvalue_change_loss REAL,        -- 公允价值变动损失
                finance_expense REAL,              -- 财务费用
                invest_loss REAL,                  -- 投资损失
                defer_tax REAL,                    -- 递延所得税
                dt_asset_reduce REAL,              -- 递延所得税资产减少
                dt_liab_add REAL,                  -- 递延所得税负债增加
                predict_liab_add REAL,             -- 预计负债增加
                inventory_reduce REAL,             -- 存货减少
                operate_rece_reduce REAL,          -- 经营性应收项目减少
                operate_payable_add REAL,          -- 经营性应付项目增加
                other REAL,                        -- 其他
                operate_netcash_othernote REAL,    -- 经营活动现金流净额其他项目(附注)
                operate_netcash_balancenote REAL,  -- 经营活动现金流净额平衡项目(附注)
                netcash_operatenote REAL,          -- 经营活动产生的现金流量净额(附注)
                debt_transfer_capital REAL,        -- 债务转为资本
                convert_bond_1year REAL,           -- 一年内到期的可转换公司债券
                finlease_obtain_fa REAL,           -- 融资租入固定资产
                uninvolve_investfin_other REAL,    -- 不涉及现金的投资和筹资活动其他
                end_cash REAL,                     -- 现金期末余额
                begin_cash REAL,                   -- 现金期初余额
                end_cash_equivalents REAL,         -- 现金等价物期末余额
                begin_cash_equivalents REAL,       -- 现金等价物期初余额
                cce_add_othernote REAL,            -- 现金及现金等价物增加额其他(附注)
                cce_add_balancenote REAL,          -- 现金及现金等价物增加额平衡(附注)
                cce_addnote REAL,                  -- 现金及现金等价物净增加额(附注)
                minority_interest REAL,            -- 少数股东损益
                useright_asset_amortize REAL,      -- 使用权资产摊销
                UNIQUE(code, report_date)
            );

        """)
        await db.commit()

        # ── 声明式列迁移 ──────────────────────────────────────────────
        # 格式: (表名, 列名, 类型定义)
        # 按表分组执行，减少 PRAGMA 调用次数
        column_migrations: list[tuple[str, str, str]] = [
            ("agents", "model_id", "TEXT"),
            ("agents", "compress_config", "TEXT"),
            ("agents", "engine_config", "TEXT"),
            ("agents", "tools", "TEXT DEFAULT '[]'"),
            ("sessions", "current_task_id", "TEXT"),
            ("sessions", "input_tokens", "INTEGER DEFAULT 0"),
            ("sessions", "output_tokens", "INTEGER DEFAULT 0"),
            ("sessions", "cost_usd", "REAL DEFAULT 0"),
            ("sessions", "cache_read_tokens", "INTEGER DEFAULT 0"),
            ("sessions", "cache_creation_tokens", "INTEGER DEFAULT 0"),
            ("sessions", "currency", "TEXT"),
            ("trace_log", "agent_name", "TEXT"),
            ("trace_log", "detail_size", "INTEGER DEFAULT 0"),
            ("cost_log", "agent_name", "TEXT"),
            ("cost_log", "currency", "TEXT"),
            ("cost_log", "cache_read_tokens", "INTEGER DEFAULT 0"),
            ("cost_log", "cache_creation_tokens", "INTEGER DEFAULT 0"),
            ("cost_log", "cache_hit_ratio", "REAL DEFAULT 0"),
            ("models", "input_price", "REAL"),
            ("models", "output_price", "REAL"),
            ("models", "currency", "TEXT DEFAULT 'USD'"),
            ("models", "provider_type", "TEXT DEFAULT 'openai_compat'"),
            ("models", "enable_cache", "INTEGER DEFAULT 1"),
            ("models", "cache_read_price", "REAL"),
            ("models", "cache_creation_price", "REAL"),
        ]
        await _ensure_columns(db, column_migrations)

        # ── 特殊迁移（数据回填）──────────────────────────────────────
        # agents.model_id: 从旧列 model_name 回填
        cursor = await db.execute("PRAGMA table_info(agents)")
        agent_cols = {row[1] for row in await cursor.fetchall()}
        if "model_name" in agent_cols:
            await db.execute(
                "UPDATE agents SET model_id = model_name WHERE model_id IS NULL"
            )
            await db.commit()

        # trace_log.detail_size: 回填已有记录
        await db.execute(
            "UPDATE trace_log SET detail_size = LENGTH(detail) "
            "WHERE detail_size IS NULL OR detail_size = 0"
        )
        await db.commit()

        # ── 恢复：服务器重启时，将遗留的 running 会话重置为 active ──
        await db.execute(
            "UPDATE sessions SET status = 'active', current_task_id = NULL WHERE status = 'running'"
        )
        await db.commit()

        # ── 创建查询优化索引（IF NOT EXISTS 确保幂等）──────────────
        await db.executescript("""
            -- cost_log 索引：支持 JOIN 条件、WHERE 过滤、ORDER BY
            CREATE INDEX IF NOT EXISTS idx_cost_session_task
                ON cost_log(session_id, task_id);
            CREATE INDEX IF NOT EXISTS idx_cost_created_at
                ON cost_log(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_cost_session_created
                ON cost_log(session_id, created_at DESC);

            -- trace_log 索引：支持 JOIN 条件、WHERE 过滤、子查询、ORDER BY
            CREATE INDEX IF NOT EXISTS idx_trace_session_task_event
                ON trace_log(session_id, task_id, event_type);
            CREATE INDEX IF NOT EXISTS idx_trace_created_at
                ON trace_log(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_trace_session_created
                ON trace_log(session_id, created_at DESC);

            -- stock 索引：加速 code + report_date 查询
            CREATE INDEX IF NOT EXISTS idx_stock_indicators_code_date
                ON stock_indicators(code, report_date DESC);
            CREATE INDEX IF NOT EXISTS idx_stock_balance_code_date
                ON stock_balance(code, report_date DESC);
            CREATE INDEX IF NOT EXISTS idx_stock_income_code_date
                ON stock_income(code, report_date DESC);
            CREATE INDEX IF NOT EXISTS idx_stock_cashflow_code_date
                ON stock_cashflow(code, report_date DESC);
        """)

        # 启动时清理过期数据
        await cleanup_old_records(db=db)


async def cleanup_old_records(
    trace_days: int = 30,
    cost_days: int = 90,
    db: aiosqlite.Connection | None = None,
) -> dict:
    """清理过期的 trace_log 和 cost_log 记录。

    trace_log 保留 trace_days 天（默认 30），cost_log 保留 cost_days 天（默认 90）。
    返回各表删除的行数。可在 init_db 启动时调用，也可通过 API 手动触发。
    """
    trace_cutoff = (datetime.now(timezone.utc) - timedelta(days=trace_days)).isoformat()
    cost_cutoff = (datetime.now(timezone.utc) - timedelta(days=cost_days)).isoformat()
    result = {"trace_deleted": 0, "cost_deleted": 0}

    async def _do_cleanup(conn: aiosqlite.Connection):
        cursor = await conn.execute(
            "DELETE FROM trace_log WHERE created_at < ?", (trace_cutoff,)
        )
        result["trace_deleted"] = cursor.rowcount
        cursor = await conn.execute(
            "DELETE FROM cost_log WHERE created_at < ?", (cost_cutoff,)
        )
        result["cost_deleted"] = cursor.rowcount
        await conn.commit()

    if db is not None:
        await _do_cleanup(db)
    else:
        async with get_db() as conn:
            await _do_cleanup(conn)

    return result
