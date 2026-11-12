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

## 5) 2× maliyet stresi (kill kriteri: PF ≥ 1,1 — İKİ pencerede de)

Profilin tüm spread değerleri ikiye katlandı (`outputs/fx_spread_replay_profile_2x.json`):

| Mod | 2× PF (son 30g) | 2× PF (önceki 30g) | Karar |
|---|---|---|---|
| london_breakout | 1,69 | 1,54 | ✅ geçti |
| ema_adx_pullback | 1,15 | 1,10 | ✅ geçti (sınırda) |
| reopen_fade | **1,09** | 1,12 | ❌ **kaldı** (bir pencerede <1,1) |

`reopen_fade` ayrıca örneklem olarak da zayıf (sembol başına 1-21 işlem) → **elendi**.

## 6) ⚠️ KOL ÖLÇÜMÜ REPLAY'İ ÇÜRÜTTÜ (kendi kararımı geri alıyorum)

`london_breakout` için `app/arms/london_breakout.py` yazıldı ve **bağımsız** ölçüldü
(`fx_arm_backtest`, 2 yıl 5m, harness çıkışları):

| Sembol | n | isabet | beklenti R | t | PF |
|---|---|---|---|---|---|
| GBPUSD | 376 | %45,2 | −0,006 | −0,11 | 0,95 |
| AUDUSD | 265 | %38,5 | **−0,136** | **−2,20** | 0,74 |
| XAUUSD | 225 | %41,3 | −0,006 | −0,09 | 0,95 |
| US30 | 330 | %48,2 | +0,078 | 1,29 | 1,13 |
| NAS100 | 303 | %44,9 | +0,088 | 1,42 | 1,26 |
| **TOPLAM** | **1.499** | %44,0 | **+0,008** | **0,31** | **1,16** |

**Beklenti +0,008R, t=0,31 → kenar sıfırdan ayırt edilemiyor.** Yani replay'deki
PF 1,73 **sinyalin** değil, **motorun çıkış yığınının** (BE `cost+1`, chandelier,
EV kalkanı, seans kapıları, risk normalizasyonu) eseri.

**Karar değişikliği:** `london_breakout` kol olarak **TERFİ EDİLMEDİ**; dosya ölçüm
artefaktı olarak duruyor. Aynı şüphe `ema_adx_pullback` için de geçerli (kolu henüz
yazılmadı; tam gösterge yığını gerektiriyor).

**Doğru yol:** bu sinyaller **motor içinde gölge** olarak ölçülmeli — kârı üreten çıkış
katmanı orada var. Kol dosyası olarak terfi, çıkış yığınını sinyalin hanesine yazmak olur.

## 7) Sıradaki adım

1. `ema_adx_pullback` + `london_breakout` için **motor içi gölge** (mode='shadow') — mevcut
   gölge mekanizmasıyla, karar değişmeden ölçüm.
2. `reopen_fade` kapandı; yeniden açılması için daha uzun pencere (≥90 gün) şart.
3. Yan bulgu düzeltildi: `fx_arm_backtest` 1m/5m desteklemiyordu ve uygulama adı ≠
   terminal adı olduğunda (NAS100→USTEC) `symbol_info` None dönüp **tüm koşuyu**
   AttributeError ile düşürüyordu.

## 8) Üretilen dosyalar

- `outputs/mx_<mod>_{old,new}.json` — ana matris (6 mod × 2 ayar)
- `outputs/dx_<mod>_{cost,tz}.json` — ayrıştırma (3 mod × 2 ayar)
- `outputs/oos_<mod>.json` — önceki 30 gün doğrulaması (4 mod)
- Tümü `outputs/` altında (gitignore); koşular `scripts/forex_replay_backtest.py` ile tekrar üretilebilir
