# EMA + ADX GERİ-ÇEKİLME SKALPİ — 48 SAAT REPLAY SONUCU

- **Tarih:** 2026-10-08 · **Sahip:** Erkan
- **Motor:** `scripts/forex_replay_backtest.py --entry-mode ema_adx_pullback` · **Sürücü:** `scripts/fx_eap_h48_campaign.py` (temiz, çakışmasız dizin `outputs/eap_h48/`)
- **Pencere:** 2026-10-05 00:00 → 2026-10-07 00:00 UTC (48 saat; veri sonu 10-07 07:58)
- **Kapsam:** 12 FX çifti + **XAUUSD + BTCUSD** (kullanıcı isteği) · 99 eşzamanlı slot · gerçek p95 spread profili (`outputs/fx_spread_p95.json`)
- **Kural seti (birebir):** EMA8>EMA21>EMA50 → LONG / ters → SHORT · ADX(14)>25 · EMA21'e geri çekilme + trend yönünde onay kapanışı · SL 1.5×ATR(14) · TP 2.0×ATR(14) veya chandelier trailing
- **İki kapı modu:** `PURE` = spec birebir (seans/minATR/EV kapıları kapalı) · `LIVE` = motor canlı varsayılanları (majör seans 7-20 UTC, minATR 4.0, EV kalkanı)

---

## 0. KARAR (TL;DR)

**Kural seti 48 saatte kâr üretmedi.** 16 koşumun 15'i negatif; tek pozitif 15m + günde-3-giriş sınırı kolu (+$9.94, n=49 — örneklem çok küçük, anlamlı sayılmaz).

- **5m:** net −$145 … −$180 (n≈185, WR %54-56, PF 0.5-0.6). Maliyet + SL yükü stratejiyi yiyor.
- **15m:** net −$27 … +$10 (n≈73-79, WR %71-80, PF 0.8-1.18). Yüksek WR ama **kâr hâlâ yok** — kazananlar küçük (BE/TP), kaybedenler tam SL.
- **Altın tek istikrarlı pozitif kolu:** XAUUSD 5m'de +$32.60 (15 işlem, 13 kazanç); günde-3 sınırıyla +$42.10 (11 işlem, 10 kazanç). WR ~%87-91.
- **BTC istikrarlı negatif:** −$5.82 … −$13.83 (n=11-14, WR ~%50). Trend takip mantığı BTC'nin 5m gürültüsünde çalışmıyor.
- **Günde-3-giriş sınırı (`--eap-max-per-day 3`) en iyileştirici tek kol:** yığılmayı kesip DD'yi 5m'de $200→$56, 15m'de pozitife çeviriyor. Ama kâr marjı hâlâ maliyet sınırında.
- **Yapısal teşhis:** Çıkış dağılımı SL ağırlıklı (5m C1: SL 77 / BE 80 / TP 18). SL 1.5×ATR çok sık vuruluyor; TP 2.0×ATR (=1.33R) kazananları erken kesiyor. **R<2 asimetrisi + maliyet = negatif beklenti.**

---

## 1. ANA TABLO — 48 SAAT (2026-10-05 → 10-07)

| Konfig | Mod | TF | n | WR% | Net $ | PF | DD $ | XAU $ (n) | BTC $ (n) | JPY $ |
|---|---|---|---|---|---|---|---|---|---|---|
| **C4_tp2_cap3** | LIVE | 15m | 49 | 79.6 | **+9.94** | 1.18 | 26.42 | +2.16 (1) | −7.42 (6) | +16.09 |
| **C4_tp2_cap3** | PURE | 15m | 55 | 74.5 | **+2.09** | 1.03 | 26.42 | +2.16 (1) | −7.42 (6) | +17.44 |
| C1_tp2 | LIVE | 15m | 73 | 74.0 | −3.31 | 0.96 | 39.97 | +2.16 (1) | −7.42 (6) | +11.77 |
| C3_trail | LIVE | 15m | 73 | 74.0 | −14.68 | 0.83 | 39.97 | +2.16 (1) | −8.85 (6) | +6.98 |
| C2_tp3 | LIVE | 15m | 73 | 74.0 | −15.49 | 0.82 | 39.97 | +2.16 (1) | −7.42 (6) | +5.34 |
| C4_tp2_cap3 | PURE | 5m | 104 | 61.5 | −20.08 | 0.88 | 55.51 | **+42.10 (11)** | −5.82 (11) | +6.05 |
| C4_tp2_cap3 | LIVE | 5m | 82 | 62.2 | −25.01 | 0.83 | 59.29 | **+42.10 (11)** | −5.82 (11) | +8.82 |
| C3_trail | PURE | 5m | 185 | 53.5 | −145.47 | 0.60 | 189.91 | +34.14 (15) | −13.83 (14) | −33.63 |
| C1_tp2 | LIVE | 5m | 154 | 55.8 | −161.28 | 0.50 | 189.81 | +32.60 (15) | −11.05 (14) | −49.30 |
| C1_tp2 | PURE | 5m | 185 | 55.1 | −169.72 | 0.53 | 201.05 | +32.60 (15) | −11.05 (14) | −52.07 |
| C2_tp3 | PURE | 5m | 185 | 54.1 | −180.50 | 0.51 | 215.69 | +6.88 (15) | −13.83 (14) | −38.19 |

Konfigler: C1=TP2.0 / C2=TP3.0 / C3=chandelier-trail / C4=TP2.0+günde max 3 giriş.

---

## 2. XAU/BTC AYRINTISI (5m, PURE, C1_tp2)

| Sembol | n | Kazanç | PnL $ |
|---|---|---|---|
| **XAUUSD** | 15 | 13 | **+32.60** |
| USDJPY | 3 | 2 | +2.05 |
| NZDUSD | 5 | 3 | +1.55 |
| GBPUSD | 2 | 1 | +0.05 |
| USDCHF | 11 | 5 | −0.95 |
| EURUSD | 5 | 1 | −6.60 |
| **BTCUSD** | 14 | 7 | **−11.05** |
| EURCHF | 12 | 7 | −14.20 |
| EURNZD | 13 | 7 | −15.34 |
| USDCAD | 21 | 14 | −17.40 |
| EURJPY | 14 | 6 | −25.47 |
| GBPJPY | 21 | 12 | −28.65 |
| GBPNZD | 32 | 19 | −41.76 |
| GBPCHF | 17 | 5 | −44.55 |

**Altın:** tek başına kapsamın tüm kârını taşıyor; 13/15 kazanç, 86.7% WR. Trend+ADX mantığı altın trendinde çalışıyor.
**BTC:** ~%50 WR, iki yönlü 5m gürültüsünde EMA dizilimi sık sık yanılıyor. Trend takibi BTC'de zarar.
**Zarar yoğunlaşması:** GBPCHF, GBPNZD, GBPJPY, EURJPY — kros JPY/GBP çiftleri. Maruziyet büyük ve sinyal gürültülü.

---

## 3. NEDEN NEGATİF — YAPI

1. **R asimetrisi:** SL 1.5×ATR vs TP 2.0×ATR = 1.33R. %55-74 WR'de bile 1.33R kazanan ve 1.0R kaybeden, maliyetten sonra negatif kalıyor. TP 3.0×ATR (R=2, C2) **daha kötü** — çünkü nadiren ulaşılıyor, SL yine vuruluyor.
2. **SL çok sık:** 5m'de 77-80 tam SL. 1.5×ATR geri çekilme skalpi için dar; EMA21 teması zaten gürültü kenarı.
3. **Maliyet:** 5m'de 185 işlem × gerçek p95 spread = belirgin drag. 15m'de işlem sayısı ~1/2.4 → sonuç pozitife yaklaşıyor.
4. **BE ağırlığı:** 5m C1'de 80 BE çıkışı — fiyat kâra gidiyor sonra BE'de kapanıyor. Trail (chandelier 2.0) kurtarmıyor (−$145).

---

## 4. ÖNERİ

- **Canlıya alınmaz.** 48 saatte baraj geçilmedi (net negatif, R<2, SL ağırlığı).
- **Tek umut verici kol:** TP2.0 + günde max 3 giriş. Yığılmayı kesiyor, WR'yi yükseltiyor, DD'yi çökertiyor (5m $200→$56). Yine de kâr maliyet sınırında → **OOS pencerede doğrulanmadan güvenilmez.**
- **Altın ayrı değerlendirilebilir:** XAUUSD bu kural setinde tek pozitif, yüksek WR. İzole XAU-only EAP kolu ayrı test edilmeye değer (kros/FX çiftleri hariç).
- **BTC bu mantıkla kapatılmalı** — 48 saatte tutarlı negatif.
- **Bir sonraki adım (kullanıcı kararı):** C4 (TP2+cap3) kolunu 30 günlük OOS pencerede doğrula; XAU-only varyantını izole koş.

---

## 5. ARŞİV NOTU

`outputs/eap14/` dizini bugün erken saatlerde w48 ve m15 dalgaları tarafından **paylaşıldı**; 15m koşumu 5m H48 dosyalarının üzerine yazdı ve `_summary_w48.json` bayat kaldı (ilk koşum motor hatasıyla 0 işlem vermişti). Bu raporun tüm sonuçları **temiz `outputs/eap_h48/`** dizininden gelir; her koşum `{konfig}__{mod}__{tf}__{pencere}.json` tekil adıyla saklanır.
