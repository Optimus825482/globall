-- 006: MT5 gercek tick spread profili.
--
-- Neden ayri tablo: `historical_candles` yalnizca OHLCV tutar; replay motoru ise
-- sembol basina gercek spread (ask-bid) profiline ihtiyac duyar. Onceden bu deger
-- elle uretilen tek seferlik bir JSON dosyasindan geliyordu (outputs/fx_spread_p95.json).
-- Artik MT5 tick'inden olculup burada saklanir; replay DB'den okur.
--
-- `microstructure_snapshots` bunun yerine kullanilamaz: o tablo tek bir anin
-- bid/ask ornegidir (spread_pct), yuzdelik dagilim ozeti degildir.

CREATE TABLE IF NOT EXISTS mt5_spread_profile (
  symbol        TEXT NOT NULL,
  timeframe     TEXT NOT NULL,
  pip_size      DOUBLE PRECISION NOT NULL,
  avg_pips      DOUBLE PRECISION NOT NULL,
  p50_pips      DOUBLE PRECISION NOT NULL,
  p95_pips      DOUBLE PRECISION NOT NULL,
  sample_count  BIGINT NOT NULL,
  measured_from DOUBLE PRECISION,
  measured_to   DOUBLE PRECISION,
  source        TEXT NOT NULL DEFAULT 'mt5_icmarkets',
  updated_at    DOUBLE PRECISION NOT NULL,
  PRIMARY KEY (symbol, timeframe)
);

CREATE INDEX IF NOT EXISTS mt5_spread_profile_tf_idx ON mt5_spread_profile(timeframe);
