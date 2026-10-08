# FX Strateji Araştırması — Derinleştirilmiş Web Araştırması + Replay Kanıtı

**Tarih:** 2026-10-08
**Yöntem:** 10 paralel web-araştırma agent'ı → konkre kural setleri çıkarıldı → replay motoruna
4 yeni giriş modu + 2 yeni rejim kapısı eklendi → kısa tarama → 30g OOS → 60g tam → çapraz pencere.
**Kapsam:** 12 FX çifti (7 majör + 5 kros), izole FX defteri (XAU/BTC/endeks hariç), gerçek p95
spread profili, 99 slot. Veri: Yahoo 60g 5m cache (`replay_cache_60d_fxwide.json`, 34 sembol).
**Soru:** "FX çiftlerinde kârlı olabilecek stratejiler var mı; varsa hangi KANITLA kabul/red?"

---

## 0. TL;DR — Karar

**Hiçbir yeni aday, plan §8 canlıya-alım barajını (2 ayrı pencerede pozitif + OOS>0 + DD<$200)
GEÇEMEDİ.** Kısa pencerede kârlı görünen adaylar (özellikle Bollinger squeeze) farklı pencerede
negatife döndü — klasik aşırı-uydurma imzası.

**Ama üç değerli kalıcı kazanım var:**
1. **Klasik skor motoru FX'te felaket** — 30g izole FX'te **−$4.635** (7.316 işlem, PF 0.64).
   Mevcut canlı politika (JPY kroslarında klasik kapalı, yalnız Donchian) **kanıtla doğrulandı**.
2. **Donchian ailesi klasikten 20-50× iyi** — her pencerede klasik −$3.000…−$4.600 iken
   Donchian türevleri −$70…+$143 aralığında. Sinyal tarafı gerçekten daha iyi; mesele sinyal.
3. **H1 EMA200 trend kapısı** ve **göreli-ATR bandı** motora kalıcı araç olarak eklendi;
   H1 kapısı Donchian'ı bir pencerede +$143/PF 2.72'ye taşıdı ama diğer pencerede −$28 —
   **pencereye bağımlı, tutarlı değil.**

---

## 1. Web Araştırması — 10 Kolun Sentezi

| Kol | En güçlü bulgu | Net-kâr beklentisi |
|---|---|---|
| Seans/kırılım (ORB) | London ORB majors'ta 6E vadeli PF 1.29 net; Asya-kutu fade KESİN ölü (9.598 break, %49.4, z=−1.25) | majors ORB marjinal; kroslarda maliyet ölümü |
| Mean-reversion | SSRN OU çalışması: 10/10 sembol-TF hücresinde OOS negatif; BB fade PF 0.21 | **cost-doomed, denemeye değmez** |
| Trend/Donchian | Kapanış bazlı kırılım > ekstrem; sabit TP runner'ı kesiyor → trailing şart; XTX: saatlik trend ≈ random walk | zayıf-orta, trailing ile denenmeli |
| Stat-arb/pairs | Cointegration çoğu FX çiftinde p=0.17 (yok); üçgen arbitraj edge 0.6bp vs retail 30-40bp | **retail'de yapılamaz** |
| Carry/overnight | Swap 0.2-1.0 pip/gün = 5m gürültüsünde yuvarlama hatası; rollover 21-22 UTC = hard blackout | intraday flat sistemde ilgisiz |
| Volatilite | ATR breakout 0/27 walk-forward; sıkışma (squeeze) EURUSD H1 PF 1.14 ama D1 0.85 | zayıf; sıkışma en iyi aday |
| Haber/takvim | 580 test: %29 "anlamlı" = şans seviyesi; takvim = yön değil VOLATİLİTE sinyali | blackout filtresi > entry |
| Likidite/ICT | FVG "dolum" totoloji (tüm barlar %97-99 dolar); order-block 5.242 işlem $10k→$571 | folklore, kodlamaya değmez |
| **MTF/regime** | **H1 EMA200 kapısı en çok tekrarlanan iyileştirme — DD düşürür, PF hafif düşer** | **en yüksek kaldıraçlı filtre** |
| Backtest rigor | 30-60g pencere kısa; ≥200-500 işlem; DSR/çoklu-test düzeltmesi şart | disiplin |

**Kesin elemeler (kodlanmadı):** mean-reversion familyası, stat-arb/pairs, üçgen arbitraj,
ICT/order-block/FVG, carrry-arbitraj, haber-entry. Gerekçe: araştırmanın en net, en çok
tekrarlanan sonucu bunların retail maliyet seviyesinde yapılamaz olması.

---

## 2. Motora Eklenen Yeni Yetenekler (`scripts/forex_replay_backtest.py`)

| Mod / Kapı | Kural | Kaynak |
|---|---|---|
| `--entry-mode donchian_pure` | Kapanış > önceki N barın EN YÜKSEK high (orta-hat değil) + ADX≥18 | Trend araştırması |
| `--entry-mode squeeze` | Bollinger bandwidth alt persentil (sıkışma) + band-dışı kapanış + EMA50 tiebreaker | Volatilite araştırması |
| `--entry-mode nr7` | Crabel NR7: son N barın en dar aralığının high/low kırılımı | Volatilite araştırması |
| `--entry-mode orb_ny` | London kutusu (07-13 UTC) → NY overlap (13-16 UTC) kırılımı + OR/ATR genişlik filtresi | Seans araştırması |
| `--htf-ema200-gate` | H1 EMA200 durumu tersse 5m girişi engelle (yalnız kapanmış saat barları) | MTF araştırması |
| `--rel-atr-band` | 0.8×medyan ≤ ATR(14) ≤ 3.0×medyan değilse giriş yok | Volatilite/MTF araştırması |
| `--mode-tp-atr 0` | Sabit TP kapalı → çıkış chandelier trailing'e bırakılır (trail-öncelikli) | Çıkış araştırması |
| `--exclude-symbols` | İzole defter (XAU/BTC çıkarma) | Metodoloji |
| `--skip-old` | OLD defterini atla → **~1.4× hız** (göstergeler bar başına tek kez) | Hız |

**Süpürme orkestratörü:** `scripts/fx_entrymode_sweep.py` — 36 konfig, paralel koşum, tek
kaynak CLI, liderlik tablosu + JSON özet.

---

## 3. Kanıt Zinciri — Pencere Pencere Sonuçlar

### 3.1 Kısa tarama (10-31 Ağu, ~3 hafta, 29 aday)
| Konfig | Net$ | n | WR% | PF |
|---|---:|---:|---:|---:|
| sq_pct10_t25 (squeeze) | **+43.15** | 52 | 80.8 | 2.37 |
| sq_tp2 (squeeze) | +27.50 | 106 | 71.7 | 1.25 |
| sq_t25 (squeeze) | +17.82 | 106 | 71.7 | 1.16 |
| jp_dp_t25 | −4.68 | 113 | 61.9 | 0.97 |
| da_tp4 (mevcut canlı) | −159.37 | 333 | 66.4 | 0.68 |
| classic_is | **−1.599** | 3.823 | 56.0 | 0.72 |

**Bulgu:** squeeze tek pozitif aile, hem JPY hem majör bacağında yeşil. Diğer her aile negatif.

### 3.2 IS penceresi (1 Ağu-14 Eyl) — squeeze sınavı
| Konfig | Net$ | n | PF |
|---|---:|---:|---:|
| sq_pct10_t12 | +6.75 | 97 | 1.05 |
| sq_pct10_tp2 | +2.90 | 97 | 1.02 |
| sq_pct10_t25 | **−9.61** | 97 | 0.92 |
| sq_tp2 | −31.21 | 208 | 0.89 |
| sq_t25 | −62.05 | 208 | 0.79 |

**Bulgu:** Kısa pencerede +$43 olan `sq_pct10_t25` bu pencerede **−$9.6** → **pencereye özgü.**

### 3.3 30 günlük OOS (7 Eyl-7 Eki) — belirleyici
| Konfig | Net$ | n | WR% | PF | DD$ | JPY$ |
|---|---:|---:|---:|---:|---:|---:|
| lb_tp15 | +19.38 | 144 | 76.4 | 1.07 | 89 | +88.4 |
| jp_sq_t25 | +12.77 | 63 | 73.0 | 1.17 | 37 | +12.8 |
| jp_da_tp4 | −17.68 | 165 | 65.5 | 0.94 | 76 | −17.7 |
| sq_tp2 | −18.67 | 164 | 72.6 | 0.92 | 50 | +27.6 |
| sq_pct10_t25 | −66.24 | 68 | 66.2 | 0.46 | 75 | −28.5 |
| da_tp4 (mevcut) | −133.13 | 532 | 72.9 | 0.84 | 193 | −34.1 |
| classic_is | **−4.635** | 7.316 | 53.6 | 0.64 | 4.669 | −854 |

**Bulgu:** Squeeze kazananı OOS'ta negatife döndü (aşırı-uydurma). Tutarlı pozitif: `jp_sq_t25`
(+12.8, PF 1.17) ve `lb_tp15`in JPY bacağı. Donchian da OOS'ta negatif.

### 3.4 60 günlük tam pencere + H1 EMA200 kapısı
| Konfig | Net$ | n | WR% | PF | DD$ | JPY$ |
|---|---:|---:|---:|---:|---:|---:|
| **jp_da_h1** (Donchian ADX+H1, JPY) | **+71.68** | 118 | 62.7 | **1.46** | 66 | +71.7 |
| **jp_dp_h1** (Donchian saf+H1, JPY) | **+54.87** | 102 | 68.6 | **1.45** | 110 | +54.9 |
| jp_da_tp4 (H1'siz) | −8.69 | 223 | 57.4 | 0.98 | 117 | −8.7 |
| jp_sq_t25 | −4.20 | 106 | 64.2 | 0.97 | 29 | −4.2 |
| da_tp4 (mevcut) | −245.48 | 669 | 68.6 | 0.77 | 339 | −8.7 |
| jp_classic | −281.94 | 2.664 | 56.5 | 0.93 | 542 | −281.9 |

**Bulgu:** H1 EMA200 kapısı Donchian'ı 60g'de **negatiften pozitife** çeviriyor (+$54…+$72,
PF 1.45-1.46). Araştırmanın öngörüsü doğrulandı — **ama tek pencere.**

### 3.5 Çapraz pencere (10 Ağu-7 Eyl) — H1 kapısı sınavı
| Konfig | Net$ | n | WR% | PF |
|---|---:|---:|---:|---:|
| jp_dp_h1 | **−27.93** | 66 | 62.1 | 0.66 |
| jp_da_h1 | **−52.80** | 78 | 51.3 | 0.58 |
| dp_h1 (tüm FX) | −120.06 | 206 | 68.4 | 0.65 |
| nr7_h1 | −126.36 | 218 | 61.0 | 0.69 |
| sq_tp2_h1 | −24.15 | 57 | 66.7 | 0.71 |

**Bulgu — KRİTİK:** Aynı `jp_dp_h1` konfigi son 30g'de **+$142.74/PF 2.72**, önceki 30g'de
**−$27.93/PF 0.66**. H1 kapısı pencereye bağımlı; tutarlı bir edge değil, **pencere şansı.**

---

## 4. Karar Kapıları — Resmi Değerlendirme (Plan §8)

Bir çiftin canlıya alınabilmesi için HEPSİ gerekli:

| Aday | OOS 30g>0 (≥100 işlem) | DD<$200 | 2 pencerede pozitif | Sonuç |
|---|---|---|---|---|
| jp_dp_h1 (Donchian saf+H1) | +142.7 ✓ / ama n66 | 36 ✓ | **−28 ✗** | **RED** |
| jp_da_h1 (Donchian ADX+H1) | +26.9 ✓ / n85 | 45 ✓ | **−53 ✗** | **RED** |
| jp_sq_t25 (Squeeze JPY) | +12.8 ✓ / n63 | 37 ✓ | 60g −4.2 ✗ | **RED** |
| lb_tp15 | +19.4 ✓ / n144 | 89 ✓ | FX bacağı 60g −136 ✗ | **RED** |
| sq_pct10_t25 | OOS −66 ✗ | 75 | — | **RED** |

**Hiçbiri barajı geçmiyor.** Türkçesi: FX çiftlerinde, bu motorda, bu dönemde **tutarlı ve
maliyet-sonrası pozitif bir yeni strateji KANITLANAMADI.** Bu projenin değerli çıktısıdır:
"acaba FX" sorusu artık 36 konfig × 5 pencere kanıtıyla kapanmıştır.

---

## 5. Meşru Bulgular (Red kararının yanında kalan pozitifler)

1. **Klasik motor FX'te kesin olarak zararlı** — her pencerede −$1.600…−$4.635, PF 0.64-0.72.
   Canlı politika (klasik FX kapalı, JPY'de yalnız Donchian) **doğru karar** — bu araştırma onu
   bağımsız olarak doğruladı.
2. **Maliyet-per-volatilite, JPY kroslarını tek yaşayabilir FX sınıfı yapıyor** (araştırma §1):
   GBPJPY 5m ATR ≈ 9.2 pip vs toplam maliyet ≈ 1.9 pip (oran 0.21); EURUSD 2.3 vs 0.8 (0.35).
   Bu, canlı kapsamın (GBPJPY/EURJPY) neden doğru olduğunu açıklar.
3. **H1 EMA200 kapısı motora kalıcı eklendi** — pencereye bağımlı olsa da, canlıda gözlem
   amaçlı izlenebilir; tek pencere kanıtıyla parametre sabitlenmemeli.
4. **Göreli-ATR bandı** (mutlak pip tabanı yerine) motora eklendi — canlıdaki `major_min_atr=4`
   yerine per-sembol ölçeklenebilir alternatif olarak test edilmeye hazır.

---

## 6. Öneriler

**Kısa vade (canlı politika):** Değişiklik YOK. Mevcut 4'lü kapsam (XAU, BTC, GBPJPY, EURJPY)
+ JPY'de klasik-kapalı/donchian canlı politikası kanıtla doğrulandı. Yeni modlar
(`donchian_pure`, `squeeze`, `nr7`, `orb_ny`) **canlı koda taşınmamalı** — replay'de barajı
geçemediler.

**Orta vade (araştırma):**
- FX'te kalıcı ilgi alanı tek: **GBPJPY/EURJPY + Donchian ailesi**. H1 EMA200 kapısını
  **paper-gözlem** olarak canlı gölge-defterde izle (motor zaten gölge defter tutuyor);
  gerçek para/MT5'e almadan önce 2+ pencere daha veri biriksin.
- Squeeze ailesini **kesin kapat** — kısa pencerede parladı, IS ve OOS'ta söndü.
- Majör/kros genişletme (7 majör + 12 kros) **kesin kapalı** — klasik de yeni modlar da negatif.

**Metodoloji:**
- Bundan sonra her FX adayı **en az 2 ayrık pencere** + ≥100 işlem + 2× spread stress
  barajından geçmeden "aday" sayılmasın (bu araştırmanın tek-kazananı tam bu yüzden elendi).
- Kısa pencere (3 hafta) yalnız ELEME için kullanılsın, onay için değil.

---

## 7. Artefaktlar

- Süpürme orkestratörü: `scripts/fx_entrymode_sweep.py` (36 konfig)
- Replay motoru yeni yetenekler: `scripts/forex_replay_backtest.py`
- Sonuç JSON'ları: `outputs/fxsweep/*_{px,sq,30,60,oosv,xval}.json` + `_summary__*.json`
- Cache: `outputs/replay_cache_60d_fxwide.json` (60g 5m), `..._15m.json`
- Spread profili: `outputs/fx_spread_p95.json`
