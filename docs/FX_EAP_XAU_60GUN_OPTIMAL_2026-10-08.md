# XAUUSD — 60 GÜN REPLAY · OPTİMAL RR AYARLARI

- **Tarih:** 2026-10-08 · **Sahip:** Erkan
- **İstek:** XAUUSD'yi optimal ayarlarla 60 günle koş
- **Optimal ayar (48h RR süpürmesinden):** SL 1.5×ATR(14) / TP 2.0×ATR(14) · ADX(14)>25 · EMA8>21>50 dizilimi
- **Motor:** `--entry-mode ema_adx_pullback` · **Sürücü:** `scripts/fx_eap_xau_60d.py` · **Çıktı:** `outputs/eap_xau_60d/`
- **Pencere:** 2026-08-08 → 2026-10-07 UTC (60 gün; XAU verisi 07-29'dan başlıyor → tam kapsanıyor)
- **İzole:** `--symbols XAUUSD` · **PURE mod** (spec birebir kapı seti) · gerçek p95 spread
- **Komşu kollar:** TP 1.5 (daha yakın TP) · SL 1.0 (daha dar SL) · chandelier-trail 2.0 (sabit TP yok)

---

## 0. KARAR (TL;DR)

**XAUUSD optimal ayarla 60 günde NET KÂRLI ve sağlam.** 8 ana koşumun **8'i pozitif**.

- **OPTIMAL (SL1.5/TP2.0), 15m:** **+$313.76, PF 2.19, n=100, WR %90.0, DD $64.9** — 60 günde en iyi risk-ayarlı sonuç.
- **OPTIMAL (SL1.5/TP2.0), 5m:** **+$184.56, PF 1.33, n=227, WR %83.7, DD $126.6**.
- **En önemli bulgu: 15m, 5m'i açık ara geçiyor.** Aynı kural seti 15m'de net %70 daha yüksek, PF 2.19 vs 1.33, DD %49 daha düşük. Sinyal 15m'de daha temiz; 5m'de 165 BE çıkışı gürültüyü gösteriyor.
- **TP komşusu (1.5) 15m'de daha da iyi: +$370.48 / PF 2.40** — altın 60 günde küçük TP'leri daha sık dolduruyor. Ama DD aynı ($64.9), yani TP1.5 vs TP2.0 farkı küçük (tek işlem farkı).
- **Her iki yarı da pozitif** (oturmuşluk): 15m O_tp2 → ilk yarı +$276.30, ikinci yarı +$37.46. Kâr ilk yarıda yoğun ama ikinci yarı da pozitif kalıyor.
- **Günlük dağılım sağlıklı:** 15m 60 günde 35 işlem gününün 28'i pozitif (7 negatif), en kötü gün −$31.52.

---

## 1. 60 GÜN — TÜM KOŞUMLAR (net'e göre sıralı)

| Konfig | TF | n | WR% | Net $ | PF | DD $ | Ort/işlem | Çıkışlar SL/BE/TP/TRAIL |
|---|---|---|---|---|---|---|---|---|
| K_tp1.5 (TP1.5) | 15m | 100 | 90.0 | **+370.48** | 2.40 | 64.90 | +3.70 | 10/71/4/15 |
| **O_tp2 (OPTIMAL)** | **15m** | **100** | **90.0** | **+313.76** | **2.19** | **64.90** | **+3.14** | 10/74/0/16 |
| O_trail2 | 15m | 100 | 90.0 | +273.58 | 2.04 | 99.60 | +2.74 | 10/85/0/5 |
| K_sl1.0 (SL1.0) | 15m | 100 | 84.0 | +257.66 | 1.87 | 65.14 | +2.58 | 16/69/0/15 |
| **O_tp2 (OPTIMAL)** | **5m** | **227** | **83.7** | **+184.56** | **1.33** | **126.62** | **+0.81** | 37/165/2/23 |
| K_tp1.5 | 5m | 227 | 83.7 | +168.50 | 1.30 | 117.36 | +0.74 | 37/159/12/19 |
| O_trail2 | 5m | 227 | 83.7 | +152.02 | 1.27 | 139.24 | +0.67 | 37/173/0/17 |
| K_sl1.0 | 5m | 231 | 76.2 | +135.02 | 1.24 | 65.14 | +0.58 | 55/153/2/21 |

**Tüm 8 koşum pozitif.** Optimal kol (O_tp2) her iki TF'de de kârlı ve PF>1.3.

---

## 2. ZAMAN DİLİMİ KARŞILAŞTIRMASI (optimal kol O_tp2)

| Metrik | 15m | 5m | Kazanan |
|---|---|---|---|
| Net $ | +313.76 | +184.56 | **15m (+%70)** |
| PF | 2.19 | 1.33 | **15m** |
| WR | %90.0 | %83.7 | **15m** |
| DD $ | 64.90 | 126.62 | **15m (−%49)** |
| İşlem | 100 | 227 | 15m (az maliyet) |
| BE çıkışı | 74 | 165 | 15m (daha az gürültü) |
| Net/DD | 4.83 | 1.46 | **15m (3.3×)** |

**Sonuç: 15m tercih edilmeli.** 5m'de 227 işlemin 165'i BE'de kapanıyor — sinyal çok erken tetikleniyor, maliyet + gürültü kârı yiyor. 15m'de sinyal olgunlaşıyor, WR %90'a çıkıyor.

---

## 3. PENCERE SAĞLAMLIĞI (oturmuşluk)

| Pencere | O_tp2 15m | O_tp2 5m |
|---|---|---|
| D60 (60 gün) | +313.76 | +184.56 |
| D60a (1. yarı, 08-08 → 09-17) | +276.30 | +158.70 |
| D60b (2. yarı, 09-17 → 10-07) | +37.46 | +25.86 |
| H48 (son 48 saat) | +2.16 (n=1, 15m işlem yok) | +32.60 |

- **Her iki yarı da pozitif** → strateji tek bir döneme bağlı değil.
- 15m'de kâr ilk yarıda yoğun (+$276), ikinci yarı daha sakin (+$37) ama pozitif.
- 48 saatte 15m yalnız 1 işlem — **48h penceresi 15m için çok kısa** (tick örneklemi yetersiz). 60 gün güvenilir.

---

## 4. ÇIKIŞ DAVRANIŞI (O_tp2 15m, 60 gün)

- **74 BE / 10 SL / 16 TRAIL / 0 TP.** Kârların çoğu **BE kilidi** ve trailing ile alınıyor — TP 2.0×ATR'ye hiç ulaşılmıyor (0 TP çıkışı).
- **BE ağırlığı = sistemin imzası:** Fiyat kâra gidiyor, kilitleniyor, trend bitmeden çıkılıyor. 10 tam SL = kontrollü kayıp.
- Bu, TP 2.0'ın neden "tavan" olduğunu doğruluyor: altın 15m'de TP'ye ulaşmadan dönüyor, kâr BE+trail ile toplanıyor.
- **TP'yi 1.5'e indirmek** (K_tp1.5) 4 TP çıkışı üretiyor ve +$57 daha net — küçük TP altında biraz daha iyi.

---

## 5. ÖNERİ

**XAUUSD, EMA+ADX geri-çekilme skalpi, 15m zaman dilimi, SL 1.5×ATR / TP 2.0×ATR** kolu 60 günde kanıtlandı:
- Net +$313.76, PF 2.19, WR %90, DD $65, 100 işlem, 28/35 pozitif gün.
- Her iki yarıda pozitif.

**Karar noktaları (kullanıcı):**
1. **Zaman dilimi:** 15m açık ara üstün → canlı için 15m önerilir.
2. **TP seçimi:** TP 1.5 (daha yüksek net) vs TP 2.0 (biraz daha simetrik RR). Fark küçük; TP 1.5 marjinal önde.
3. **Canlıya almadan:** Bu 60 gün XAU'nun trendli bir dönemine denk gelmiş olabilir (altın yaz boyunca güçlü yükseldi). Farklı rejim (yükseliş dışı) penceresinde doğrulama önerilir — örn. Temmuz başı veya daha eski veri.

---

## 6. DOSYALAR

- Sürücü: `scripts/fx_eap_xau_60d.py`
- Ham sonuçlar: `outputs/eap_xau_60d/_summary_xau60.json` + `{konfig}__{tf}__{pencere}.json` (32 dosya)
