# XAUUSD / BTCUSD — AYRI RR (SL·TP × ATR) OPTİMİZASYONU · 48 SAAT

- **Tarih:** 2026-10-08 · **Sahip:** Erkan
- **İstek:** Altın ve BTC'yi AYRI izole koş, RR (SL/TP oranı) sınırını optimize et — yalnız 48 saat
- **Motor:** `--entry-mode ema_adx_pullback` · **Sürücü:** `scripts/fx_eap_rr_sweep_xaubtc.py` · **Çıktı:** `outputs/eap_rr_xaubtc/`
- **Pencere:** 2026-10-05 → 2026-10-07 UTC (48 saat) · **Kapsam:** `--symbols` ile TEK sembol izole
- **Grid:** SL {1.0, 1.5, 2.0}×ATR × TP {1.5, 2.0, 2.5, 3.0, 4.0}×ATR (15 sabit-TP kolu) + sabit-TP yok, chandelier trailing {1.5, 2.0, 2.5}×ATR (3 kol) = **18 konfig × 2 TF**
- **Kapılar:** PURE mod (spec birebir; EV kalkanı + majör seans/minATR kapalı) · gerçek p95 spread

---

## 0. KARAR (TL;DR)

- **XAUUSD — RR optimize edildi, kârlı.** En iyi: **SL 1.5×ATR / TP 2.0×ATR** (R=1.33) → **+$32.60, PF 2.28, n=15, WR %86.7**; chandelier-trail 2.0 → **+$34.14, PF 2.34**. 18 kolun **12'si pozitif** — SL=1.5 bandı sağlam. 15m'de yalnız **1 işlem** çıktı (değerlendirilemez).
- **BTCUSD — hiçbir RR ayarı kâra çevirmedi.** En iyisi sl1.0_tp1.5 (R=1.5) → **−$1.94** (5m) / **−$0.22** (15m), yani başabaş civarı ama negatif. **18/18 kol negatif.** BTC bu mantıkla 48 saatte pozitif değil.

---

## 1. XAUUSD — 5m (18 konfig, net'e göre sıralı)

| Konfig (SL/TP×ATR) | RR | n | WR% | Net $ | PF | DD $ | Çıkışlar SL/BE/TP/TRAIL |
|---|---|---|---|---|---|---|---|
| **sl1.5_trail2.0** | trailing | 15 | 86.7 | **+34.14** | 2.34 | 33.98 | 2/12/0/1 |
| **sl1.5_tp2.0** | 1.33 | 15 | 86.7 | **+32.60** | 2.28 | **23.22** | 2/10/1/2 |
| sl1.5_trail2.5 | trailing | 15 | 86.7 | +30.90 | 2.22 | 37.22 | 2/12/0/1 |
| sl2.0_tp2.0 | 1.00 | 15 | 86.7 | +24.18 | 1.71 | 31.64 | 2/10/1/2 |
| sl1.0_tp2.0 | 2.00 | 15 | 73.3 | +21.52 | 1.62 | **17.68** | 4/8/1/2 |
| sl1.5_tp1.5 | 1.00 | 15 | 86.7 | +20.90 | 1.82 | 23.22 | 2/10/2/1 |
| sl2.0_tp1.5 | 0.75 | 15 | 86.7 | +12.48 | 1.37 | 31.64 | 2/10/2/1 |
| sl1.0_tp1.5 | 1.50 | 15 | 73.3 | +9.82 | 1.28 | 17.68 | 4/8/2/1 |
| sl1.5_tp2.5 | 1.67 | 15 | 86.7 | +6.88 | 1.27 | 31.34 | 2/10/0/3 |
| sl1.5_tp3.0 | 2.00 | 15 | 86.7 | +6.88 | 1.27 | 31.34 | 2/10/0/3 |
| sl1.5_tp4.0 | 2.67 | 15 | 86.7 | +6.88 | 1.27 | 31.34 | 2/10/0/3 |
| sl1.5_trail1.5 | trailing | 15 | 86.7 | +4.80 | 1.19 | 32.30 | 2/10/0/3 |
| sl2.0_tp2.5 | 1.25 | 15 | 86.7 | −1.54 | 0.95 | 39.76 | 2/10/0/3 |
| sl2.0_tp3.0 | 1.50 | 15 | 86.7 | −1.54 | 0.95 | 39.76 | 2/10/0/3 |
| sl2.0_tp4.0 | 2.00 | 15 | 86.7 | −1.54 | 0.95 | 39.76 | 2/10/0/3 |
| sl1.0_tp2.5 | 2.50 | 15 | 73.3 | −4.20 | 0.88 | 24.20 | 4/8/0/3 |
| sl1.0_tp3.0 | 3.00 | 15 | 73.3 | −4.20 | 0.88 | 24.20 | 4/8/0/3 |
| sl1.0_tp4.0 | 4.00 | 15 | 73.3 | −4.20 | 0.88 | 24.20 | 4/8/0/3 |

**Altın okuması:**
- **SL = 1.5×ATR optimal bant.** SL 1.0 (daha çok SL vuruluyor, WR 86.7→73.3) ve SL 2.0 (kayıp büyüyor) ikisi de daha kötü.
- **TP = 2.0×ATR tatlı nokta.** TP'yi 2.5+ yapmak hiçbir ek kazanç getirmiyor (aynı çıkışlar, sadece BE/TRAIL'e dönüyor) — altının 48 saatlik hareketi 2.0×ATR'yi nadiren aşıyor.
- **Trail (chandelier 2.0)** sabit TP'ye göre marjinal yüksek net (+$34.14) ama DD daha yüksek (33.98 vs 23.22). Sabit TP2.0 daha temiz risk profili → **canlı için sl1.5_tp2.0 önerilir.**
- **15m:** yalnız 1 işlem (veri/ısınma nedeniyle) → 15m altın bu pencerede değerlendirilemez, 5m geçerli.

---

## 2. BTCUSD — 5m (en az zarar üstte)

| Konfig (SL/TP×ATR) | RR | n | WR% | Net $ | PF | DD $ |
|---|---|---|---|---|---|---|
| sl1.0_tp1.5 | 1.50 | 14 | 50.0 | **−1.94** | 0.87 | 8.73 |
| sl1.0_tp2.0 | 2.00 | 14 | 50.0 | −3.79 | 0.74 | 9.91 |
| sl1.0_tp2.5..4.0 | 2.5-4.0 | 14 | 50.0 | −6.57 | 0.56 | 9.91 |
| sl1.5_tp1.5 | 1.00 | 14 | 50.0 | −9.20 | 0.58 | 14.85 |
| sl1.5_tp2.0 (spec) | 1.33 | 14 | 50.0 | −11.05 | 0.50 | 16.15 |
| sl2.0_tp1.5 | 0.75 | 14 | 57.1 | −11.36 | 0.55 | 15.99 |
| sl2.0_tp2.0 | 1.00 | 14 | 57.1 | −13.21 | 0.48 | 17.29 |
| sl1.5_tp2.5+ / trail | — | 14 | 50.0 | −13.83 | 0.37 | 16.15 |
| sl2.0_tp2.5+ | 1.25+ | 14 | 57.1 | −15.99 | 0.37 | 17.29 |

**BTC 15m:** tümü negatif; en iyi sl1.0_tp1.5 → −$0.22 (n=6), sl2.0_tp1.5 → −$1.39 ama WR %60 (n=5).

**BTC okuması:**
- **18/18 kol negatif.** En iyi kol bile başabaş civarı.
- BTC'de **dar SL + küçük TP zararı küçültüyor** (sl1.0_tp1.5), yani sinyal kâr üretmiyor; sadece maliyet/SL yükü minimize ediliyor.
- **WR %50** — yazı-tura. EMA dizilimi BTC'nin iki yönlü 5m gürültüsünde yön ayrımı yapamıyor.
- **Sonuç: BTC bu mantıkla kapatılmalı; RR optimizasyonu kurtarmıyor.**

---

## 3. BAĞLAM — 48 saat önceki geniş kapsamla uyum

Geniş kampanya (`docs/FX_EAP_EMA_ADX_PULLBACK_48H_2026-10-08.md`): 12 FX + XAU + BTC birlikte → XAU +$32.60 (tek pozitif), BTC −$11.05. İzole koşum bu tabloyu **birebir doğruladı**: XAU kârlı ve sağlam, BTC negatif ve RR ile düzelmiyor.

---

## 4. ÖNERİ (karar kullanıcının)

- **XAUUSD:** `sl_atr=1.5, tp_atr=2.0, ADX>25, EMA8/21/50 dizilimi` kolu **48 saatte kanıtlı**. Ama n=15 — **canlıya almadan önce 30 gün OOS'ta doğrulanmalı.**
- **BTCUSD:** bu kural setiyle **kapatılmalı**.
- Sıradaki olası test (kullanıcı onayıyla): XAU sl1.5_tp2.0 kolunu 30 günlük pencerede doğrula.

---

## 5. DOSYALAR

- Sürücü: `scripts/fx_eap_rr_sweep_xaubtc.py`
- Ham sonuçlar: `outputs/eap_rr_xaubtc/_summary_rr.json` + `{SYM}__{konfig}__{tf}__H48.json` (72 dosya)
