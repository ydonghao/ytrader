-- ============================================================================
-- quant_schema.sql
-- 量化数据同步所需的表结构 / TimescaleDB hypertable 配置。幂等执行。
--
-- 适用对象：A 股 / H 股 / ETF 日线 + 分钟线、贵金属 / 原油日线、货币 OHLC 日线。
-- stock_ohlcv / stock_ohlcv_minute 为既有裸 SQL 表（DDL 原在仓库外手工维护），
-- 此处仅做补强：唯一约束、hypertable、压缩策略。
-- ============================================================================

-- ── 1. 商品日线表（贵金属 + 原油）──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS commodity_ohlcv (
    symbol      TEXT        NOT NULL,        -- XAU/XAG/XPT/XPD/GC/SI/OIL/CL/NG
    trade_date  DATE        NOT NULL,
    open_       DOUBLE PRECISION,
    high_       DOUBLE PRECISION,
    low_        DOUBLE PRECISION,
    close_      DOUBLE PRECISION,
    volume      DOUBLE PRECISION,
    amount      DOUBLE PRECISION DEFAULT 0,
    asset_class TEXT        NOT NULL,        -- metal | energy
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (trade_date, symbol)
);
CREATE INDEX IF NOT EXISTS idx_commodity_ohlcv_class ON commodity_ohlcv (asset_class);

-- ── 1b. 指数日线表（A 股宽基/行业/主题指数）──────────────────────────────────
CREATE TABLE IF NOT EXISTS index_ohlcv (
    symbol      TEXT        NOT NULL,        -- sh000300 / sz399001 ...
    trade_date  DATE        NOT NULL,
    open_       DOUBLE PRECISION,
    high_       DOUBLE PRECISION,
    low_        DOUBLE PRECISION,
    close_      DOUBLE PRECISION,
    volume      DOUBLE PRECISION,
    amount      DOUBLE PRECISION DEFAULT 0,
    market      TEXT        DEFAULT 'INDEX', -- 标识 INDEX 资产类
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (trade_date, symbol)
);

-- ── 2. fx_rate 扩展 OHLC（rate 保留作 close，兼容 portfolio 标量路径）────────
ALTER TABLE fx_rate ADD COLUMN IF NOT EXISTS open_ DOUBLE PRECISION;
ALTER TABLE fx_rate ADD COLUMN IF NOT EXISTS high_  DOUBLE PRECISION;
ALTER TABLE fx_rate ADD COLUMN IF NOT EXISTS low_   DOUBLE PRECISION;

-- ── 3. stock_ohlcv 唯一约束（若未建）──────────────────────────────────────
-- 注意：列名带下划线后缀（open_/close_ 等），避保留字。
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_indexes WHERE tablename = 'stock_ohlcv'
        AND indexdef LIKE '%UNIQUE%trade_date%symbol%'
    ) THEN
        ALTER TABLE stock_ohlcv ADD CONSTRAINT stock_ohlcv_uniq UNIQUE (trade_date, symbol);
    END IF;
END $$;

-- ── 4. stock_ohlcv_minute 唯一约束（若未建）──────────────────────────────
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_indexes WHERE tablename = 'stock_ohlcv_minute'
        AND indexdef LIKE '%UNIQUE%trade_time%symbol%interval%'
    ) THEN
        ALTER TABLE stock_ohlcv_minute
            ADD CONSTRAINT stock_ohlcv_minute_uniq UNIQUE (trade_time, symbol, interval);
    END IF;
END $$;

-- ── 4b. 股票估值日线表（PE/PB/PS/股息率/总市值）──────────────────────────────
-- 来源：ak.stock_a_indicator_lg（乐咕乐股），按交易日，从上市至今完整历史。
CREATE TABLE IF NOT EXISTS stock_valuation (
    symbol      TEXT        NOT NULL,        -- sh600000
    trade_date  DATE        NOT NULL,
    pe          DOUBLE PRECISION,            -- 静态市盈率
    pe_ttm      DOUBLE PRECISION,            -- 滚动市盈率（价值策略主用）
    pb          DOUBLE PRECISION,            -- 市净率
    ps          DOUBLE PRECISION,            -- 市销率
    ps_ttm      DOUBLE PRECISION,            -- 滚动市销率
    dv_ratio    DOUBLE PRECISION,            -- 股息率
    dv_ttm      DOUBLE PRECISION,            -- 滚动股息率（红利策略主用）
    total_mv    DOUBLE PRECISION,            -- 总市值（元）
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (trade_date, symbol)
);

-- ── 4c. 股票财务指标表（ROE 等，按报告期）────────────────────────────────────
-- 来源：ak.stock_financial_analysis_indicator（新浪），按报告期（季末）。
CREATE TABLE IF NOT EXISTS stock_financials (
    symbol        TEXT        NOT NULL,
    report_date   DATE        NOT NULL,      -- 报告期（季末日期）
    roe_weighted  DOUBLE PRECISION,          -- 加权净资产收益率 %
    roe_diluted   DOUBLE PRECISION,          -- 摊薄净资产收益率 %
    gross_margin  DOUBLE PRECISION,          -- 销售毛利率 %
    net_margin    DOUBLE PRECISION,          -- 销售净利率 %
    debt_ratio    DOUBLE PRECISION,          -- 资产负债率 %
    created_at    TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (report_date, symbol)
);

-- ── 5. TimescaleDB hypertable（仅当 timescaledb 扩展可用时）─────────────────
-- stock_ohlcv_minute 量级将达数亿行，必须转 hypertable + 压缩。
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'timescaledb') THEN
        PERFORM create_hypertable('stock_ohlcv_minute', 'trade_time', if_not_exists => TRUE);
        PERFORM create_hypertable('stock_ohlcv',        'trade_date',  if_not_exists => TRUE);
        -- 90 天前的分钟线自动压缩
        ALTER TABLE stock_ohlcv_minute SET (timescaledb.compress);
        PERFORM add_compression_policy('stock_ohlcv_minute', INTERVAL '90 days', if_not_exists => TRUE);
    END IF;
END $$;
