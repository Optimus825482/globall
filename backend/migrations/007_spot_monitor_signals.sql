-- 007_spot_monitor_signals.sql
-- Binance TR Spot MTF takip ve 5.000 TL portföy simülatörü tablosu

CREATE TABLE IF NOT EXISTS spot_monitor_signals (
    id SERIAL PRIMARY KEY,
    signal_key VARCHAR(100) UNIQUE NOT NULL,
    symbol VARCHAR(30) NOT NULL,
    timeframe VARCHAR(10) NOT NULL,
    strategy VARCHAR(50) NOT NULL,
    strategy_label VARCHAR(100) NOT NULL,
    entry_price DOUBLE PRECISION NOT NULL,
    target_price DOUBLE PRECISION NOT NULL,
    stop_price DOUBLE PRECISION NOT NULL,
    score DOUBLE PRECISION NOT NULL,
    kdj_j DOUBLE PRECISION,
    details JSONB,
    detected_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    -- Takip / Simülasyon Alanları
    status VARCHAR(20) NOT NULL DEFAULT 'OPEN', -- OPEN, WIN_TP, LOSS_SL, EXPIRED
    exit_price DOUBLE PRECISION,
    exit_time TIMESTAMPTZ,
    pnl_pct DOUBLE PRECISION DEFAULT 0.0,
    mfe_pct DOUBLE PRECISION DEFAULT 0.0,
    mae_pct DOUBLE PRECISION DEFAULT 0.0,
    
    -- Portföy Simülasyonu (300 TL sabit bütçe)
    trade_size_try DOUBLE PRECISION DEFAULT 300.0,
    commission_try DOUBLE PRECISION DEFAULT 0.24,
    net_pnl_try DOUBLE PRECISION DEFAULT 0.0
);

CREATE INDEX IF NOT EXISTS idx_spot_signals_detected ON spot_monitor_signals(detected_at DESC);
CREATE INDEX IF NOT EXISTS idx_spot_signals_status ON spot_monitor_signals(status);
CREATE INDEX IF NOT EXISTS idx_spot_signals_symbol ON spot_monitor_signals(symbol);
