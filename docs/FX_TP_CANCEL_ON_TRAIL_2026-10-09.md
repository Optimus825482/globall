# `tp_cancel_on_trail` — Uygulama Notu (2026-10-09)

**Kaynak kanıt:** `outputs/exit_sweep/FINDINGS.md` (V03 `--no-tp-on-trail-live`), script
`scripts/fx_exit_dynamic_trail_sweep.py`.
**Durum:** Kod hazır, testler yeşil, **canlı VARSAYILAN AÇIK** (2026-10-09 kararı: dört pencere
A/B'de işaret-tutarlı tek kazanan). Geri alma: `FOREX_TP_CANCEL_ON_TRAIL=false` (env) veya
Ayarlar > Otonom Paper Trade'den `tp_cancel_on_trail` kapatma.

## Ne yapıldı

| Katman | Değişiklik |
|---|---|
| `backend/app/routers/forex.py` `ForexAutoPaperSettings` | Yeni alan `tp_cancel_on_trail: bool = False` |
| `forex.py` paper çıkış döngüsü (~3959) | Trailing devreye girince (`updated_trail`) ayar açıksa `pos["tp_price"] = 0.0` → (c) TP_HIT dalı bir daha ateşlemez |
| `forex.py` `_build_modify_sltp_cmd()` (yeni) | BE ve Trailing MT5 `MODIFY_SLTP` komutları tek yoldan üretilir; `tp_price=0` ise `tp_action="cancel"` taşınır (çıplak `tp=0` köprüde "koru" demek) |
| `forex.py` `sync_mt5_bridge` settings | Köprüye `tp_cancel_on_trail` bayrağı gönderilir |
| `scripts/mt5_bridge.py` `execute_modify_sltp` | Yeni `tp_action="cancel"` semantiği → TP gerçekten silinir (`tp=0.0` gönderilir); `tp=0` hâlâ "koru" (geriye dönük uyum) |
| `scripts/mt5_bridge.py` `check_and_apply_dynamic_exits` | Trailing aktif + ayar açık + TP var → TP iptal emri; SL taşıma gerekmiyorsa da gönderilir (`sl=cur_sl`) |

`_build_modify_sltp_cmd` tek yol olduğu için, TP bir kez iptal edildikten sonra gelen BE/trailing
güncellemeleri TP'yi geri diriltmez (butlan buydu: BE komutu aynayı yazsaydı iptal geri alınırdı).

## Kanıt özeti (A/B, DÖRT pencere — canlı varsayılan kararı)

| Pencere | BASE | V03 TP-iptal | Fark |
|---|---:|---:|---:|
| IS (09-07→10-07) | 3064.26 | 3264.96 | **+$200.70** |
| OOS (08-08→09-07) | 3864.95 | 4080.00 | **+$215.05** |
| OOS2 (07-15→08-15) | 2413.41 | 2478.73 | **+$65.32** |
| F1 (06-20→07-14, taze) | 2625.68 | 2795.46 | **+$169.78** |

Dört pencerede de pozitif; maxDD çoğunda düşüyor. ADX-rejimli dinamik trailing (V09-V12, V16-V19) ve
TP-ratchet (V13-V15) pencereler arası **işaret değiştirdiği** için (FINDINGS Bulgu 6, 7, 11) EKLENMEDİ —
V18'i doğrulama kuralı biçimsel geçse de ayrıştırma kazancın ADX'ten değil TP-iptalden geldiğini gösterdi.
Tam tablo: `outputs/exit_sweep/FINDINGS.md` + `PREREG_V18_F1.md`.

## Bilinçli kabul edilen risk

TP silinince kâr garantisi kalkar; sert gap'te trailing stop kötü fiyattan dolar. Paper tarafta
`auto_paper.py` (kripto) 2026-09-28'de tam tersi kararı vermişti (TP silinince kârla kapanan işlem
payı %33'e düşüyordu). İki bağlam farkı: orada çıkış tamamen trailing'e bırakılıyordu ve TP yoktu;
burada **BE + trailing + kâr kilidi** koruması altında çalışır ve FX/BTC'de trend koşusu ölçüldü.
Yine de bu opt-in bir bahistir — açmadan önce canlı-paper gözlemi önerilir (`FX_KALIBRASYON_PLANI.md` §8).

## Sıradaki (henüz YAPILMADI — dürüstlük notu)

1. **TP-ratchet A/B:** `backend/app/routers/auto_paper.py:1101-1123`'te kanıtlı daha güvenli
   alternatif (TP silmek yerine yukarı kaydırma) FX replay'ine (`forex_replay_backtest.py`
   `TUN_TP_MODE`) eklenip V03 ile kıyaslanmalı. **Hangisinin kazandığı henüz bilinmiyor** —
   FINDINGS §Öneri 2 açık iş olarak bırakıldı.
2. **ADX-rejimli dinamik trailing mesafesi** (hipotez 2'nin test edilmemiş ayağı).
3. Köprüye taşıma sırasında `tp_cancel_on_trail`'in canlı MT5'te ilk denemesi **paper-gözlemle**
   yapılmalı (Linux'ta MT5 yok; bu oturumda yalnız birim + döngü testleri koşuldu).

## Testler

`backend/tests/test_forex_enhancements.py`: `TestTpCancelOnTrail` (köprü komutu, `tp_action`
semantiği, döngü uçtan uca AÇIK/KAPALI/aktivasyonsuz), `TestBridgeSettingsPayload`,
`TestTpRatchetAlternative`. `test_forex_improvements.py` varsayılan=KAPALI kilidi ve payload anahtarı.
Sistem Python 3.12 ile koşuldu (`PYTHONUTF8=1`); forex süitleri 100% yeşil.
