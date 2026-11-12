# FX MALİYET MODELİ DENETİMİ — gerçek spread vs replay varsayımı

**Tarih:** 2026-11-12 · **Sembol:** 17 (FX majör/kros + emtia + endeks) · **Veri:** MT5 gerçek bid/ask tick (~120 gün derinlik)

## 1) Neden bu denetim

`docs/FX_YENI_SINYAL_AILESI_TUR2_2026-11-10.md` §4'te şu açık yazılıydı:

> "bizim p50 spread ölçümü roll/witching/tatil günlerinde **yanlış pozitif** üretir (gerçek spread 2-5×)"

Replay ise maliyeti **tek sabit tablodan** alıyordu:

```python
# scripts/forex_replay_backtest.py:72
CATEGORY_SPREAD_PIPS = {"major": 1.2, "commodity": 2.5, "crypto": 12.0, "index": 3.0, "cross": 2.0}
```

`--spread-profile` verilmezse **her koşumda bu tablo** kullanılır (`config` satırında `spreadProfile=-`). Yani tüm strateji eleme/terfi kararları bu varsayımın üstünde duruyordu.

## 2) Ölçüm yöntemi

`scripts/fx_spread_profile.py` (yeni) — MT5 `copy_ticks_range` ile **gerçek bid/ask tick**:

- gün dilimleriyle çekilir (XAUUSD 30 günde ~2M tick/gün → bellekte tutulmaz),
- her tick için `(ask-bid)/pip_size` → **dakika medyanı**,
- saat-of-day ve haftanın günü profili,
- `pip_size` CANLI `get_symbol_trading_specs`'ten (XAUUSD 0.1, endeksler 1.0 — elle yazılan 0.01 spread'i 100× şişiriyordu).

**İki tuzak kodda karşılandı:**
1. **Sunucu saati**: MT5 tick zaman damgaları broker saatinde (ICMarkets **UTC+2**). Düzeltilmeden saat profili 2 saat kayıyor ve "rollover" yanlış saate bakıyor. `server_offset_s()` ile yarım saate yuvarlanır.
2. **Endeks pip'i**: evren listesinde olmayan sembolde (DE40) `point`'tan türetme pip'i 0.01 yapıp spread'i 400 pip gösteriyordu → canlı çözücüye düşürüldü (doğrusu 4.0 pip).

## 3) Sonuç: varsayım ile gerçek arasındaki fark

30 gün, dakika-medyanı spread (**p50**), pip:

| Sembol | Replay varsayımı | Ölçülen | Kat | p90 | 22:00 UTC (rollover) |
|---|---|---|---|---|---|
| EURUSD | 1.2 (major) | **0.10** | 12× düşük | 0.10 | 3.50 (**17×**) |
| GBPUSD | 1.2 | **0.20** | 6× düşük | 0.30 | 8.00 (**16×**) |
| USDJPY | 1.2 | **0.10** | 12× düşük | 0.20 | 6.80 (**62×**) |
| AUDUSD | 1.2 | **0.10** | 12× düşük | 0.10 | 3.10 (**23×**) |
| USDCAD | 1.2 | **0.20** | 6× düşük | 0.20 | 4.30 (**15×**) |
| USDCHF | 1.2 | **0.10** | 12× düşük | 0.10 | 10.80 (**55×**) |
| NZDUSD | 1.2 | **0.10** | 12× düşük | 0.50 | 4.60 (**22×**) |
| EURGBP | 2.0 (cross) | **0.20** | 10× düşük | 0.50 | 5.80 (**12×**) |
| EURJPY | 2.0 | **1.10** | 1.8× düşük | 1.20 | 12.45 (**7×**) |
| GBPJPY | 2.0 | **0.60** | 3.3× düşük | 0.80 | 23.60 (**23×**) |
| XAUUSD | 2.5 (commodity) | **0.80** | 3× düşük | 1.20 | 0.80 (**1×**) |
| US30 | 3.0 (index) | **1.20** | 2.5× düşük | 1.20 | 1.20 (0.6×) |
| NAS100 | 3.0 | **1.00** | 3× düşük | 1.00 | 1.00 (1×) |
| US2000 | 3.0 | **0.35** | 8.6× düşük | 0.44 | 0.43 (0.7×) |
| JP225 | 3.0 | **4.00** | **1.3× YÜKSEK** | 5.00 | 5.00 (1×) |
| UK100 | 3.0 | **1.00** | 3× düşük | 5.00 | 5.00 (**5×**) |
| DE40 | 3.0 | **0.80** | 3.7× düşük | 4.00 | 4.00 (**5×**) |

**Üç bulgu:**
1. **FX'te replay maliyeti 2-12 kat FAZLA yazıyordu.** Gerçek hesap IC Markets Raw demo: majörlerde 0.1-0.2 pip.
2. **Rollover saati (22:00 UTC) belgelenen "2-5×"den çok daha kötü: FX'te 7-62×.** USDCHF 10.8 pip, GBPJPY 23.6 pip. XAU/endekslerde rollover etkisi yok (1×) — orada işlem yapan için sorun yok.
3. **JP225/UK100/DE40'ta ters yön: varsayım DÜŞÜK** (2-3 pip yerine 4-5 pip). Bu üç endeks 2026-11-10'da canlıya alındı; maliyetleri eksik hesaplanmış.

> Not: depodaki eski `outputs/fx_spread_db_1m.json` (EURUSD **1.81** pip) bar açılış spread'inden türetilmişti ve tick gerçeğinin **18 katı**. 2026-10-28 tarihli strateji taramaları bu profille koşulmuş (`docs/COMBO3_FX_PARITE_TESTI_2026_10_28.md:53`) → o taramalarda FX maliyeti fahişti.

## 4) Kârlılık etkisi — A/B (temiz tek değişken)

Aynı veri, aynı parametreler, aynı seed; **tek fark** `--spread-profile`:

```
python scripts/forex_replay_backtest.py --days 30 --interval 5m --tag costoff --out outputs/replay_costoff_30d.json
python scripts/forex_replay_backtest.py --days 30 --interval 5m --tag coston  --out outputs/replay_coston_30d.json \
       --spread-profile outputs/fx_spread_replay_profile.json
```

Config farkı: yalnız `tag` + `spreadProfile` (55 token içinde 2 fark).

| Metrik (NEW defter) | Varsayım (kategori) | Ölçülen (tick) | Fark |
|---|---|---|---|
| İşlem | 6.787 | 7.001 | +214 |
| İsabet | %72,1 | **%74,0** | +1,9 puan |
| Net | **−6.818 $** | **+87.845 $** | +94.663 $ |
| İşlem başına | −1,01 $ | +12,55 $ | +13,55 $ |
| Profit factor | **0,98** | **1,23** | +0,25 |
| Maks. düşüş | 28.615 $ | **11.172 $** | −17.443 $ |

Mekanizma iki kanaldan:

1. **Doğrudan maliyet** — her işlemden sahte 1-1,8 pip düşülüyordu.
2. **Çıkış motoru** (`cost_pips`) — break-even/trail eşikleri `cost_pips×3` ile kuruluyor (`forex_replay_backtest.py:2221`). Şişik maliyet, BE'yi **3-5 pip geç** tetikliyordu. BE çıkışları 4.089 → 4.336'a çıktı, SL zararı −421.756 $ → −382.009 $.

**Sembol kırılımı (net $):** XAUUSD 67.966 → **100.610** · USDJPY −10.930 → **+353** · USDCHF −32.664 → −10.106 · GBPUSD −13.834 → −4.219 · AUDUSD −16.890 → −6.992 · US30 5.706 → 8.491 · NAS100 4.599 → 6.570.

### 4a) Aynı işlemler üzerinde izolasyon

Yeni işlemlerin (6.787 → 7.001) karışmasın diye **eşleşen işlem** analizi (`symbol` + `opened_bar` çifti):

- eşleşen **6.201 işlem**, aynı giriş/çıkış zamanı ve yönü
- net **+1.030 $ → +85.104 $** (+84.074 $)

Yani kazancın tamamı **ek işlemlerden değil, aynı işlemlerin doğru maliyetlenmesinden**. En büyük düzeltme USDCHF (+17.006 $), AUDUSD (+15.422 $), XAUUSD (+20.961 $).

### 4b) Yön tekrarı — önceki 30 gün penceresi

`--days 60 --window prior` (2026-07 → 09, farklı rejim):

| Metrik | Varsayım | Ölçülen |
|---|---|---|
| İşlem | 5.899 | 6.100 |
| İsabet | %71,6 | %73,7 |
| Net | **−19.112 $** | **+66.384 $** |
| İşlem başına | −3,24 $ | +10,88 $ |
| Profit factor | **0,95** | **1,19** |

Aynı yön, aynı büyüklük sırası → bulgu tek pencereye bağlı değil.

> Maks. düşüş rakamı pencere seçiminden etkilenmiyor (kod `eq_new` tam seriden hesaplıyor, `forex_replay_backtest.py:4247`) → **DD'yi pencere bazlı kanıt olarak kullanma**.

## 5) Dürüst sınırlar

- **Tek pencere, tek rejim** — 30 gün ana pencere + 30 gün önceki pencere (yön tekrar etti, §4b). Daha eski rejimler (2023-2025) doğrulanmadı.
- Replay'in **mutlak doları canlıya taşınmaz** (bilinen: yön aktarılır, $ aktarılmaz). Buradaki iddia "$88k kazanç" değil, **"maliyet modeli yanlıştı ve kararı ters çeviriyordu"**.
- Profil şu an **sembol başına tek sayı** (seans-tipik p50). 22:00 UTC'de işlem açan bir strateji hâlâ eksik ücretlendirilir (FX 3-24 pip). Saat-duyarlı maliyet henüz replay'e bağlanmadı.
- Canlı motor etkilenmez: `cost_pips = cand["spread_pips"] + komisyon` canlı spread'den geliyor. Sorun **araştırma/replay** katmanındaydı.

## 6) Açık işler (öncelik sırası)

1. **Saat-duyarlı maliyet** (P1): replay'de giriş saatine göre spread (`hour_pips` zaten üretiliyor) → 21:00-23:00 UTC girişleri gerçek maliyetini ödesin. Bugün bu saatlerde giriş yapan strateji **bedava** sayılıyor.
2. **Eski eleme kararlarının gözden geçirilmesi** (P1): maliyet fahişken PF<1,0 kriteriyle elenen stratejiler yeniden koşulmalı; ölçüm onları haksız yere öldürmüş olabilir.
3. **JP225/UK100/DE40 maliyet düzeltmesi** (P2): bu üç endeksin gerçek maliyeti varsayımın 1,3-2× üstünde → canlı performansı replay'den kötü çıkacak.
4. **Dukascopy ile eski dönem doğrulaması** (P2): `scripts/fx_dukascopy_import.py` hazır (ücretsiz, anahtarsız, doğrulandı: EURUSD 2026-11-11 10:00 → HTTP 200). MT5 tick'i ~120 günle sınırlı; 2023-2025 spread rejimi doğrulanmadı. CDN bu ağdan yavaş (9-21 sn/istek, ara 503) → sembol başına birkaç haftalık örnek yeterli.

## 7) Replay hızlandırması (aynı gün, sonuç DEĞİŞMEDEN)

Şikâyet haklıydı: bir A/B ~10 dakika sürüyordu. cProfile ile ölçüldü — sürenin **%94'ü `_compute_technical_indicators`** içindeydi (95.865 çağrı, `_calc_ema` tek başına 226 s): her bar×sembol için EMA/RSI/ATR/ADX özyinelemeleri **saf Python döngüsüyle** baştan hesaplanıyordu.

**Yapılan:** birinci derece özyinelemeler `scipy.signal.lfilter` tabanlı `_smooth`/`_smooth_last` ile değiştirildi (`forex.py`). Matematik birebir aynı — kanıt: `backend/tests/test_forex_smoothing_parity.py` eski döngü formüllerinin kopyasını referans alıp **max fark 0** bekliyor (bu test yazılırken gerçek bir hata yakaladı: DX hesabında iç 100 çarpanı düşmüştü, ADX 11,4 yerine 0,001 dönüyordu).

| Ölçüm | Önce | Sonra |
|---|---|---|
| 5 günlük pencere (`--start/--end`) | 59 s | **17 s** |
| Tam koşu (60 gün, 6.787 işlem) | ~10 dk | **218 s (3,6 dk)** |
| Sonuç | — | **birebir aynı** (işlem/isabet/net/PF/DD/equity) |

**Yan bulgular (araştırma disiplini için):**
- `--days 5` koşuyu **kısaltmıyor**: 60 günlük seride koşuyor (aynı 17.179 bar). Kısa pencere `--start/--end` ile verilir; o da işlem sayısını düşürür ama bar döngüsünü değiştirmez.
- `--skip-old` zaten vardı: OLD defteri kapatıp gösterge yükünü yarıya indirir (maliyet/parametre A/B'lerinde önerilir).
- Kalan sürenin %79'u hâlâ gösterge hesabı; sıradaki gerçek kazanç **artımlı gösterge durumu** (bar başına O(1)); ondan önce `_resample_5m_to_15m` (%17, saf Python sözlük/sıralama) vektörel hale getirilebilir.
- vectorbt bu iş için uygun değil: motorun BE/chandelier/kısmi TP/EV guard çıkışları **durum bağımlı**; vbt'de aynı kuralı yeniden yazmak motoru değil başka bir stratejiyi ölçer. vbt'nin yeri kural taraması (5 yıl × 40 sembol, saniyeler).

## 8) Üretilen dosyalar

- `backend/app/routers/forex.py` — `_smooth`/`_smooth_last` (lfilter) + EMA/RSI/ATR/ADX döngüleri vektörel
- `backend/tests/test_forex_smoothing_parity.py` — eski döngü formüllerine karşı parite kilidi (8 test)
- `scripts/fx_spread_profile.py` — MT5 tick → saat/gün spread profili + `fx_spread_history` tablosu + replay profili
- `scripts/fx_dukascopy_import.py` — Dukascopy tick → M1 bar (fill-only) + gerçek spread; yıllara uzanan doğrulama
- `outputs/fx_spread_profile_30d.json` (tam profil), `outputs/fx_spread_replay_profile.json` (replay şeması), `outputs/replay_cost{off,on}_30d.json` (A/B) — `outputs/` gitignore'da, betiklerle 3 dakikada yeniden üretilir
