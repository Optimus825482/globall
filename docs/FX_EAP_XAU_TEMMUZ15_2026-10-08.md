# XAUUSD — TEMMUZ 1-15 2026 REPLAY (MT5 GEÇMİŞİYLE)

- **Tarih:** 2026-10-08 · **Sahip:** Erkan
- **İstek:** XAUUSD (ve BTC) için Temmuz'un ilk 15 günü replay
- **Pencere:** 2026-07-01 → 2026-07-16 UTC (Temmuz 1-15 dahil)
- **Veri kaynağı:** **MT5 geçmişi** (Yahoo 5m/15m yalnız 60 gün geriye gidiyor; Temmuz artık yok). `scripts/fx_build_mt5_cache.py` ile IC Markets MT5'ten çekildi, broker sunucu saati (UTC+3) → UTC'ye indirildi. Önbellek: `outputs/replay_cache_jul_mt5.json` (5m) + `..._m15.json`, 14 sembol, 06-15'ten itibaren (ısınma payı).
- **Kural seti:** EMA+ADX geri-çekilme skalpi · **optimal RR** SL 1.5×ATR / TP 2.0×ATR + komşu kollar
- **Kapı:** PURE (spec birebir) · gerçek p95 spread · izole XAU + (kontrol) geniş kapsam

---

## 0. KARAR (TL;DR)

**XAUUSD izole, Temmuz 1-15: 5m güçlü POZİTİF, 15m NEGATİF — 60 günlük bulgunun tam tersi.**

| Kapsam | TF | Konfig | n | WR% | Net $ | PF | DD $ |
|---|---|---|---|---|---|---|---|
| **XAU izole** | **5m** | **O_trail2** | 87 | 89.7 | **+252.70** | **3.15** | 70.90 |
| **XAU izole** | **5m** | **O_tp2 (optimal)** | 87 | 89.7 | **+153.90** | **2.31** | 64.46 |
| XAU izole | 5m | K_tp1.5 | 87 | 89.7 | +150.22 | 2.28 | 54.46 |
| XAU izole | 5m | K_sl1.0 | 88 | 84.1 | +142.30 | 2.14 | 73.40 |
| **XAU izole** | **15m** | **O_tp2 (optimal)** | 38 | 86.8 | **−16.56** | 0.87 | 57.26 |
| XAU izole | 15m | K_sl1.0 | 40 | 65.0 | −161.00 | 0.36 | 167.50 |
| GENİŞ (12FX+XAU+BTC) | 5m | O_trail2 | 900 | 50.7 | −91.00 | 0.92 | 309.57 |
| GENİŞ (12FX+XAU+BTC) | 15m | O_trail2 | 323 | 63.2 | −65.50 | 0.89 | 167.79 |

**Kritik çelişki:** 60 günlük koşumda (Ağustos-Ekim) **15m üstündü** (net +$313.76 / PF 2.19 vs 5m +$184.56). Temmuz 1-15'te ise **5m üstün ve kârlı, 15m negatif**. → **Zaman dilimi üstünlüğü pencereye bağlı, kararlı değil.**

---

## 1. XAUUSD İZOLE — 5m (Tem 1-15, kârlı)

| Konfig | n | WR% | Net $ | PF | DD $ | Çıkışlar SL/BE/TP/TRAIL |
|---|---|---|---|---|---|---|
| O_trail2 | 87 | 89.7 | **+252.70** | 3.15 | 70.90 | 9/76/0/2 |
| **O_tp2 (optimal)** | 87 | 89.7 | **+153.90** | 2.31 | 64.46 | 9/71/0/7 |
| K_tp1.5 | 87 | 89.7 | +150.22 | 2.28 | 54.46 | 9/68/4/6 |
| K_sl1.0 | 88 | 84.1 | +142.30 | 2.14 | 73.40 | 14/67/0/7 |

- **4/4 kol pozitif**, WR %84-90, PF 2.1-3.2.
- Günlük: 11 işlem gününün 8'i pozitif, en kötü gün −$38.58.
- **Trailing (O_trail2) en yüksek net** (+$252.70, PF 3.15) — Temmuz'da altın trending, trail kârı yakalıyor.
- Çıkışlar BE ağırlıklı (71 BE / 9 SL) — 60 günlük çıkış imzasıyla aynı (kâr BE kilidiyle toplanıyor).

---

## 2. XAUUSD İZOLE — 15m (Tem 1-15, negatif)

| Konfig | n | WR% | Net $ | PF | DD $ |
|---|---|---|---|---|---|
| O_tp2 (optimal) | 38 | 86.8 | −16.56 | 0.87 | 57.26 |
| O_trail2 | 38 | 86.8 | −19.52 | 0.84 | 57.26 |
| K_sl1.0 | 40 | 65.0 | −161.00 | 0.36 | 167.50 |

- **4/4 kol negatif.** WR yüksek (%87) ama net negatif — kazananlar küçük, kaybeden SL'ler WR'yi yiyor (60 günün 15m tablosuyla aynı asimetri sorunu, ama burada n=38 ile daha az kazanan çıkmış).
- 5m'de 87 işlem → 15m'de 38 işlem. Temmuz'da sinyal 15m'de yeterince olgunlaşmamış.

---

## 3. GENİŞ KAPSAM KONTROLÜ (12 FX + XAU + BTC, Tem 1-15)

**Tüm geniş kapsam kolları negatif** (5m −$91…−$219, 15m −$65…−$221). Ama **XAU katkısı 5m'de +$142…+$252** — yani toplam zarar tamamen FX/BTC çiftlerinden geliyor. Bu, 48h ve 60g bulgularıyla tutarlı: **kâr yalnız XAU'da, kros/FX ve BTC taşıyıcı zarar.**

---

## 4. 60 GÜN İLE KARŞILAŞTIRMA — ÇELİŞKİNİN ANLAMI

| Pencere | XAU 5m (O_tp2) | XAU 15m (O_tp2) | Kazanan TF |
|---|---|---|---|
| Temmuz 1-15 | **+153.90** (n=87) | −16.56 (n=38) | **5m** |
| 60 gün (Ağu-Eki) | +184.56 (n=227) | **+313.76** (n=100) | **15m** |

**Yorum:** Strateji her iki pencerede de kârlı bir TF buluyor ama **hangi TF'in kârlı olduğu değişiyor.** Bu, edge'in zaman diliminden bağımsız "gerçek" olmadığını, pencereye/rejime duyarlı olduğunu gösteriyor. Sağlam bir canlı kol için tek pencereye dayanmak riskli.

**Not — 5m iki pencerede de pozitif:** Temmuz 1-15 +$153.90, 60 gün +$184.56. **5m her iki bağımsız pencerede pozitif** → 15m'den daha tutarlı. Bu, zaman dilimi seçimi için en önemli tek sinyal.

---

## 5. ÖNERİ

- **XAUUSD 5m, SL 1.5×ATR / TP 2.0×ATR (veya trail 2.0):** iki bağımsız pencerede de pozitif (Tem +$154, 60g +$185). **En tutarlı kol.** Canlı adayı.
- **15m:** 60 günde parlak ama Temmuz'da negatif → **tek pencereye güvenilmez**, canlıya alınmaz.
- **BTC / FX kros:** her pencerede negatif → kapsam dışı.
- **Önerilen doğrulama:** XAU 5m kolunu üçüncü bir bağımsız pencerede (örn. Haziran ikinci yarısı, MT5'ten çekilebilir) doğrula.

---

## 6. DOSYALAR

- MT5 önbellek üreticisi: `scripts/fx_build_mt5_cache.py` (Yahoo 60-gün sınırını aşar)
- Kampanya sürücüsü: `scripts/fx_eap_jul15.py`
- Ham sonuçlar: `outputs/eap_jul15/_summary_jul15.json` + 16 koşum JSON'u
- Veri: `outputs/replay_cache_jul_mt5.json` / `outputs/replay_cache_jul_mt5_m15.json`

**Metodolojik not:** Temmuz verisi Yahoo'da olmadığı için MT5'ten alındı. Spread profili (`fx_spread_p95.json`) Ağustos-Ekim ölçümünden geliyor; Temmuz'da gerçek spread farklı olabilir — maliyet tarafında küçük belirsizlik var.
