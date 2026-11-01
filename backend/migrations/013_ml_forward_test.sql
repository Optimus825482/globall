-- 013_ml_forward_test.sql
-- ML modelinin DONDURULMUŞ ileri (forward) test kaydı.
--
-- Amaç: bir modelin gerçekten işe yarayıp yaramadığını YALNIZCA eğitimden
-- sonra üretilen, hiç görülmemiş tahminlerle ölçmek. Geriye dönük backtest ve
-- in-sample holdout bu soruyu cevaplayamaz (her ikisi de modelin gördüğü
-- dağılıma yakın durur).
--
-- Akış:
--   1. Model dondurulur (artifact kopyalanır + sha256), `ml_frozen_models`e yazılır.
--   2. Her canlı taramada, eşiği geçen her tahmin `ml_shadow_predictions`e düşer.
--   3. Ufuk süresi geçince sonuç gerçek mumlardan ölçülür (pending -> evaluated).
--   4. Rapor: isabet oranı, lift, kümülatif getiri. Hiçbir şey ayarlanmaz.
--
-- Bu tablolar SALT KAYIT amaçlıdır: hiçbir sinyal işlemi bunlara bakmaz.

CREATE TABLE IF NOT EXISTS ml_frozen_models (
    id BIGSERIAL PRIMARY KEY,
    frozen_at DOUBLE PRECISION NOT NULL,
    artifact_path TEXT NOT NULL,
    artifact_sha256 TEXT NOT NULL,
    feature_version TEXT NOT NULL,
    trained_at DOUBLE PRECISION,
    horizons JSONB NOT NULL DEFAULT '[]'::jsonb,
    symbol_count INTEGER NOT NULL DEFAULT 0,
    gate_probability DOUBLE PRECISION,
    note TEXT,
    retired_at DOUBLE PRECISION
);
CREATE INDEX IF NOT EXISTS ml_frozen_models_frozen_idx ON ml_frozen_models(frozen_at DESC);

CREATE TABLE IF NOT EXISTS ml_shadow_predictions (
    id BIGSERIAL PRIMARY KEY,
    frozen_id BIGINT NOT NULL REFERENCES ml_frozen_models(id) ON DELETE CASCADE,
    predicted_at DOUBLE PRECISION NOT NULL,
    horizon_minutes INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    entry_price DOUBLE PRECISION NOT NULL,
    -- Model çıktıları
    hit_probability DOUBLE PRECISION,
    target_pct DOUBLE PRECISION,
    gate_passed BOOLEAN NOT NULL DEFAULT FALSE,
    -- Özellik vektörü (sonradan analiz için tam kopya)
    features JSONB NOT NULL DEFAULT '{}'::jsonb,
    -- Değerlendirme
    status TEXT NOT NULL DEFAULT 'pending',   -- pending | evaluated | expired
    evaluated_at DOUBLE PRECISION,
    max_favorable_pct DOUBLE PRECISION,
    max_adverse_pct DOUBLE PRECISION,
    exit_pct DOUBLE PRECISION,               -- takipçi çıkışıyla net getiri (fee dahil)
    hit_target BOOLEAN,
    bars_held INTEGER
);
CREATE INDEX IF NOT EXISTS ml_shadow_pred_idx
    ON ml_shadow_predictions(frozen_id, status, predicted_at);
CREATE INDEX IF NOT EXISTS ml_shadow_symbol_idx
    ON ml_shadow_predictions(symbol, predicted_at DESC);

-- Aynı sembol+bardan iki kez tahmin yazılmasın (tarama tekrar edebilir)
CREATE UNIQUE INDEX IF NOT EXISTS ml_shadow_unique_bar
    ON ml_shadow_predictions(frozen_id, symbol, predicted_at, horizon_minutes);
