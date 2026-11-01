-- 012_spot_monitor_peak_trailing.sql
-- Spot Monitor çıkış modeli: sabit TP kaldırıldı, zirve takipçi stop eklendi.
--
-- Yeni model:
--   • Kâr %1.5'e ulaşınca takipçi devreye girer
--   • Devreye girdiği anda stop, maliyet + %0.8'e çekilir (işlem kaybedemez)
--   • Sonrasında stop, zirvenin %0.6 gerisinden gelir
--
-- `spot_monitor.py` içindeki `_ensure_spot_schema()` bu kolonları idempotent
-- olarak eklediği için migration elle çalıştırılmasa da sistem çalışır; bu
-- dosya şemayı belgelemek ve temiz kurulumda hazır etmek içindir.

ALTER TABLE spot_monitor_signals
    ADD COLUMN IF NOT EXISTS trailing_active BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS peak_price DOUBLE PRECISION;

COMMENT ON COLUMN spot_monitor_signals.trailing_active IS
    'Zirve takipçi stop devrede mi (kâr %1.5 eşiğini geçtiyse TRUE)';
COMMENT ON COLUMN spot_monitor_signals.peak_price IS
    'Pozisyon açıldığından beri görülen en yüksek fiyat (takipçi referansı)';

-- target_price artık kullanılmıyor: TP hedefi üretilmiyor, kayıt sırasında
-- NOT NULL kısıtını karşılamak için entry_price yazılıyor. Geriye dönük
-- sorguları bozmamak için kolon silinmiyor.
COMMENT ON COLUMN spot_monitor_signals.target_price IS
    'KULLANILMIYOR — TP kaldırıldı; entry_price yazılır. Çıkış zirve takipçisiyle yönetilir.';
