# MALİYET + SAAT DÜZELTMESİ SONRASI GİRİŞ MODU YENİDEN TARAMASI (2026-11-12)

**Soru:** maliyet modeli 2-12× fahişken ve bar saatleri 2 saat kayıkken PF<1,0 diye elenen giriş modları, düzeltilmiş ayarda hâlâ elenmeli mi?

**Ayar farkı:** taban = kategori spread tablosu (major 1,2 pip) + tz kayık. Düzeltilmiş = ölçülen saat-duyarlı spread profili + `--bar-tz-offset 2`. Aynı veri (60 gün DB), aynı 30 günlük pencere, `--skip-old`.

## 1) Ana sonuç — 6 mod, aynı pencere

| Giriş modu | PF (taban) | PF (düzeltilmiş) | Net (taban) | Net (düzeltilmiş) | İşlem |
|---|---|---|---|---|---|
| london_breakout | 0,99 | **1,73** | −86 $ | **+5.834 $** | 205 → 246 |
| ema_adx_pullback | 0,95 | **1,28** | −3.819 $ | **+19.865 $** | 1.477 → 1.472 |
| reopen_fade | 0,63 | **1,26** | −1.315 $ | **+613 $** | 90 → 108 |
| squeeze | 0,77 | **1,05** | −2.560 $ | **+382 $** | 229 → 177 |
| pullback | 1,43 | 1,70 | +8.192 $ | +12.133 $ | 359 → 353 |
| supertrend_rsi | 1,05 | 1,25 | +1.284 $ | +5.782 $ | 486 → 488 |

**4 mod zarardan kâra döndü.** Zaten pozitif olan ikisi de güçlendi.

## 2) Ayrıştırma — hangi düzeltme yaptı?

Aynı mod, dört ayar: taban / yalnız maliyet / yalnız saat / ikisi (PF).

| Mod | Taban | +Maliyet | +Saat | İkisi |
|---|---|---|---|---|
| london_breakout | 0,99 | 1,40 | 1,13 | **1,73** |
| reopen_fade | 0,63 | **0,32** ↓ | 0,84 | **1,26** |
| squeeze | 0,77 | 1,20 | **0,63** ↓ | **1,05** |

**Kritik bulgu: düzeltmeler tek başına bazı modlarda ZARAR veriyor.**
- `reopen_fade`: yalnız maliyet düzeltmesi PF'i 0,63 → **0,32'ye düşürüyor**. Sebep: saat kayıkken mod "00:00"da giriyor ama gerçekte 22:00 UTC = rollover → 3,5-10,8 pip spread ödüyor. Saat düzeltilince gerçek 00:00'da giriyor (spread 0,1) ve PF 1,26 oluyor.
- `squeeze`: yalnız saat düzeltmesi 0,77 → **0,63**. Maliyet düzeltmesi tek başına 1,20; ikisi birlikte 1,05 (maliyet-tek başına göre düşük).

**Yani "maliyeti düzelt ama saati bırak" gibi bir ara çözüm yanıltıcı.** İki düzeltme birbirine bağlı; doğru okuma yalnız ikisi birlikteyken elde edilir.

## 3) Dürüst sınırlar — terfi için YETMEZ

- **Tek pencere.** Aynı 30 günde hem bakılan hem karar verilen yer; OOS ayrımı yok. `--window prior` koşusu ayrıca yapıldı (bkz. §4).
- **Kill kriteri tek başına PF değil** (repo: iki pencerede biri negatifse / DD > 200 $ / 2× maliyet stresinde PF < 1,1 → kapanır). Bu tarama o üç kapıyı çalıştırmadı.
- `squeeze` PF 1,05 ≈ gürültü sınırı; 177 işlem.
- Bu modlar `--entry-mode` araştırma kolları; canlıya alma `app/arms/` dosyası + `fx_arm_backtest` + gölge yolundan geçer.

## 4) OOS doğrulaması — önceki 30 gün (`--days 60 --window prior`)

Aynı düzeltilmiş ayar, **farklı pencere**:

| Mod | IS PF | **OOS PF** | OOS net | OOS işlem | Karar |
|---|---|---|---|---|---|
| london_breakout | 1,73 | **1,59** | +3.959 $ | 217 | ✅ yön tekrar etti |
| reopen_fade | 1,26 | **1,29** | +549 $ | 92 | ✅ (örnek az) |
| ema_adx_pullback | 1,28 | **1,22** | **+13.668 $** | 1.297 | ✅ en güçlü |
| squeeze | 1,05 | **0,82** | −1.266 $ | 151 | ❌ **düştü** |

`squeeze` beklendiği gibi gürültüydü (IS PF 1,05) ve OOS'ta 0,82 → **elendi**.

## 5) Sıradaki adım

1. Geçen 3 moda **2× maliyet stresi** (`--slip-pips 2`) + DD kontrolü — repo kill kriteri: iki pencerede biri negatif / DD > 200 $ / 2× maliyette PF < 1,1 → kapanır.
2. Geçenler `app/arms/` dosyası olarak yazılıp `fx_arm_backtest` + gölge yolundan geçirilir; doğrudan canlıya alınmaz.
3. `reopen_fade` örneklem küçük (92 işlem) — kotayı büyütmek için pencere uzatılmalı.

## 6) Üretilen dosyalar

- `outputs/mx_<mod>_{old,new}.json` — ana matris (6 mod × 2 ayar)
- `outputs/dx_<mod>_{cost,tz}.json` — ayrıştırma (3 mod × 2 ayar)
- `outputs/oos_<mod>.json` — önceki 30 gün doğrulaması (4 mod)
- Tümü `outputs/` altında (gitignore); koşular `scripts/forex_replay_backtest.py` ile tekrar üretilebilir
