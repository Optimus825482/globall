# Scalping Stratejisi Araştırması — 3. TUR (Yön-Bağımsız / Rejim / Funding)

**Tarih:** 2026-10-10 · **Veri:** MT5 BTCUSD 1m, 30 gün + 60 gün (2026-08-11 → 10-10), 85.694 bar
**Kısa sonuç:** Klasik yön stratejileri yine elendi. **Tek sağlam bulgu: saat-08:00 UTC seans
drifti** — ama bu bir **günde 1 işlem** seans stratejisi, ≥30 işlem/gün HF değil.

---

## 1. Literatür özeti (araştırma turu)

Web araştırması (SSRN/JFE/Heliyon/arXiv/Quantpedia + bağımsız replikasyonlar) net bir konsensüs
verdi: **1m/5m'de OHLCV'den türetilen tüm yön edge'leri maliyetin içinde** (brüt ~1.3bp vs 5bp
en ucuz round-trip). Bu, 2. turdaki kendi bulgumuzu (brüt PF<1.0) doğruluyor. Hayatta kalan
aileler: **zaman-bazlı (time-of-day)**, **rejim-koşullu**, **çok-bacaklı (funding/pairs)**.

| Kaynak | Bulgu | Durum |
|---|---|---|
| Shanaev 2023 (Heliyon) | "Turn-of-15m-candle" +0.58bp/dk | 2026'da ÖLDÜ (bizim ölçüm: dk00=−0.10bp) |
| Shen/Urquhart 2022 | Güniçi TSMOM, yalnız yüksek-vol gün | etc. 1 işlem/gün |
| Franz/Schmeling | Funding carry Sharpe 8.76 | 2026'da ~%0.6'ya çürümüş |
| Padysak/Vojtko | 21:00-23:00 UTC seans %40 yıllık | 5g'de replike OLMADI (−286pip) |
| arxiv 2608.21888 | 15dk reversal: brüt 1.3bp < 5bp maliyet | Kanıt: ucuz bile değil |

**Ana ders:** HF + kârlı aynı anda, 1m OHLCV + CFD ile matematiksel olarak yok. Zaman-bazlı
edge'ler tek gerçek sığınak ama düşük frekanslı.

---

## 2. Test edilen 6 yeni aile (BTCUSD 1m, 60 gün)

| # | Aile | Sonuç |
|---|---|---|
| R1 | Volatilite-rejim koşullu MOMENTUM (yüksek-vol) | −1758…−4488 pip, PF 0.52-0.72 ❌ |
| R2 | Volatilite-rejim koşullu REVERSION (düşük-vol) | −585…−2565 pip, PF 0.66-0.69 ❌ |
| R3 | **Saat-seans drift** | **hour-08: +519 pip, PF 1.57 ✅** |
| R4 | Funding-z kontraryen (Binance perp) | −1200…−1462 pip, PF 0.55-0.98 ❌ |
| R5 | Güniçi TSMOM (ilk30→son30dk) | −1127 pip, PF 0.51 ❌ |
| R6 | Range-expansion breakout | −7712…−31241 pip, PF 0.56-0.61 ❌ (yüksek frekans ama net zarar) |

**Yeni keşif:** Saatin (UTC) öngörü gücü var; fiyat desenlerinin yok.

---

## 3. Öne çıkan: saat-08:00 UTC seansı

**Kural:** Her gün 08:00 UTC'de (son 60dk getirisinin yönünde) gir; ~1 saat tut; SL/TP $40.

**Bulgu — tüm saatler arasında TEK anlamlı drift:**

| Saat (UTC) | Ort 1-bar drift | t-stat |
|---|---|---|
| **08:00** | **+0.286 bp** | **+3.11** ✅ |
| 23:00 | +0.079 bp | +1.25 |
| diğer 22 saat | | 1.2'nin altı |

**Performans (60 gün):**

| Konfig | n | net pip | WR | PF | poz-gün |
|---|---|---|---|---|---|
| Yönlü SL40/TP40 | 60 | **+519** | %63 | 1.57 | 38/60 |
| Yönlü SL50/TP50 | 60 | +389 | %58 | 1.31 | 35/60 |
| Sabit-LONG | 60 | +296 | %60 | 1.29 | 36/60 |
| 08:00-08:30 kısa pencere | 60 | +293 | %60 | 1.29 | 36/60 |

**Doğruluk testleri:**
- ✅ Ham drift t=+3.11 (59 saat arasında tek anlamlı)
- ✅ Walk-forward: 5 pencerede 4/5 pozitif (30g veride); 6 pencerede 3/6 (60g)
- ✅ Aylık: Ağu +219, Eyl +5, Eki +295 (hepsi pozitif)
- ✅ Sabit-long da kazanıyor → gerçek seans drifti (yön filtresi şart değil)
- ✅ Saat 6,7,9,10 komşuları zarar → 8 özel, tesadüf değil
- ✅ Spread 5→10 pip'te +126 (dayanıklı), 20 pip'te bozulur
- ✅ London/European açılışıyla uyumlu (08:00 UTC = 09:00 London)

**Uyarılar:**
- **Günde 1 işlem** → ≥30 işlem/gün hedefini KARŞILAMAZ.
- Aylık dağılım dengesiz: Eylül neredeyse sıfır (+5), kâr Ağustos ve Ekim'den.
- Örneklem 60 işlem — istatistiksel olarak hâlâ küçük (güven için 200+).
- 6/60 walk-forward penceresinde nötr bantta (−25 tekrar eden sabit değer = SL'e takılan aynı gün).
- Long-only eğilimli (LONG +518 / SHORT −88): gerçek edge long tarafında.

---

## 4. Neden ≥30 işlem/gün + kâr hâlâ mümkün değil

Yüksek-frekans test edilen ailelerin (R1/R2/R6) hepsi net negatif. Sebep (2. turda kanıtlandığı
gibi): 1m ölçeğinde brüt yön edge'i spread'den küçük. Saat-bazlı tek edge ise **günde 1 sinyal**
üretiyor. İkisini birleştirmek (HF + zaman-edge) matematiksel olarak mümkün ama kâr eden HF
slot bulunamadı — 48 yarım-saat penceresinin yalnız 9'u (çoğu zayıf) pozitif.

---

## 5. Sonuç ve dürüst öneri

**3. tur:** 6 yeni aile test edildi. **≥30 işlem/gün + kârlı hedefi yine sağlanamadı.**
Tek sağlam, tekrarlanabilir bulgu: **saat-08:00 UTC seans drifti** (t=3.11, PF 1.57, 4/5
walk-forward, aylık pozitif) — ama bu günde 1 işlem.

**Net mesaj:** BTCUSD'de "günde ≥30 işlem + kârlı" kombinasyonu, MT5 CFD + 1m OHLCV ile
**kurulamaz.** Kanıt: 3 tur, ~150 konfigürasyon. Ya barajı gevşetin (saat-seans: günde 1-3
işlem, gerçek pozitif edge) ya da venue/maliyet yapısını değiştirin (maker-rebate + limit emir).

**Somut öneri:** Saat-08 UTC seans stratejisi **en umut verici, gerçek, ölçülmüş aday**
(komşu saatler zarar ederken o kazanıyor). Uzun veriyle (1-2 yıl, 300+ işlem) doğrulanmaya
değer. Ama kullanıcı "günde 30 işlem" istiyorsa, bu hedefle uyuşmuyor — karar kullanıcının.

---

## 6. Artefaktlar

| Dosya | İçerik |
|---|---|
| `scripts/btc_round3_signals.py` | 6 yeni aile (rejim/TSMOM/funding/seans/range) |
| `outputs/scalp_cache_btc_60d_1m.json` | BTCUSD 60g 1m (85.694 bar) |
| `outputs/scalp_cache_btc_30d_1m.json` | BTCUSD 30g 1m |
| `scripts/fx_build_recent_cache.py` | MT5 cache (range-based fetch bug fix) |
