# Yeni Scalping Stratejisi Araştırması — 3 ve 5 Günlük Replay Sonucu

**Tarih:** 2026-10-10 · **Veri:** MT5 (IC Markets demo), XAUUSD + BTCUSD 5m
**Kısa sonuç:** **Session-VWAP z-skor ortalamaya dönüş** stratejisi 3 günde ve **5 günde
(2026-10-05 → 10-09, Pazartesi–Cuma)** her iki enstrümanda da **NET POZİTİF** çıktı.
Ancak örneklem küçük (18-23 işlem) ve 32 günlük bağlamda kâr eriyor → **umut verici ama
kanıtlanmadı, "temkinli aday" statüsünde.**

---

## 0. 5 GÜNLÜK SONUÇ (Pazartesi–Cuma, 2026-10-05 → 10-09) — istenen son koşum

Veri: MT5 5m, broker offset UTC+3 düzeltmeli. XAUUSD 1356 bar, BTCUSD 1430 bar.

| Strateji | XAUUSD (n / WR / net pip / PF) | BTCUSD (n / WR / net pip / PF) |
|---|---|---|
| A1 VWAP-z2.0 tüm-gün | 54 / %42.6 / +189 / 1.15 | 52 / %42.3 / +839 / 1.22 |
| **A2 VWAP-z2.0 07-16 UTC** | **23 / %52.2 / +365 / 1.69** | **18 / %44.4 / +731 / 1.54** |
| A3 VWAP-z2.5 ADX<20 | 27 / %37.0 / −83 / 0.87 | 29 / %44.8 / +874 / 1.48 |
| C0 referans EMA trend | 82 / %32.9 / **−663** / 0.81 | 78 / %43.6 / +2810 / 1.30 |

**A2 (07-16 UTC seanslı)** → XAUUSD **+365 pip (PF 1.69)**, BTCUSD **+731 pip (PF 1.54)**, net pozitif.

**Gün-gün (A2):**

- XAUUSD: Mon −90 · Tue 0 (setup yok) · Wed +141 · Thu +245 · Fri +69 → **4/4 işlem-günü pozitif**
  (Salı hariç, o gün hiç sinyal ateşlemedi). LONG +316 / SHORT +49.
- BTCUSD: Mon **+774** · Tue +212 · Wed −345 · Thu 0 · Fri +89 → **kârın çoğu Pazartesi'ye yığılı**
  (Pazartesi 3 işlemde %100 WR, +774 pip). LONG +66 / SHORT +665.

**USD karşılığı (0.1 lot):** XAUUSD ≈ **+$365**, BTCUSD ≈ **+$73**. (XAU 0.1 lot → 1 pip=$1;
BTC 0.1 lot → 1 pip=$0.1.)

**Uyarı:** BTC kârının ~%106'sı tek günden (Pazartesi) geliyor — o gün çıkarılırsa net negatif.
XAUUSD dağılımı daha sağlıklı (4 ayrı pozitif gün). Yani **XAUUSD tarafı daha tutarlı,
BTCUSD tarafı şanslı tek güne bağımlı.**

---


## 1. Araştırma — ne bulundu (özet)

Web araştırması (SSRN/JFE/Quantpedia + bağımsız doğrulama laboratuvarları) sonucu:

| Aile | Altın/Kripto için kanıt | Karar |
|---|---|---|
| **Opening-Range Breakout (ORB)** | Altında **ÇÜRÜK** (22 yıl, 12 varyant, 0 geçti; PF 0.93, Sharpe −0.20) ve kriptoda maliyetten 2.5-5× küçük brüt etki | **ATLANDI** |
| **Session-VWAP z-skor reversion** (+ADX rejim kapısı) | XAUUSD 5m 180g: PF 1.96, +%37.4, DD %6.9 (Formion, maliyetli). Kripto overreaction akademik destekli | **TEST EDİLDİ (öne çıktı)** |
| **Noise-Area intraday momentum** (Zarattini) | SPY: Sharpe 1.33 ama bağımsız OOS'da 0.39'a düşmüş | TEST EDİLDİ (zayıf) |
| **BTC 21:00-23:00 UTC seans hold** | Yıllık %33-40 ama 2022-23'te DD %−22.7, mekanizması zayıf | Sonraki tur |
| **BTC/ETH çift cointegration** | Sharpe 1.48 ama p=0.062 (marjinal) | Sonraki tur |
| **Gold-DXY lead-lag, RSI 30/70 MR, ATR breakout** | Bunlar **FALSİFİYE** (walk-forward OOS negatif) | **ATLANDI** |

Ana ders (araştırmadan): 5m'de **maliyet her şeyi belirliyor** ve her ortalamaya-dönüş
sistemi **rejim kapısı olmadan** çöküyor (aynı mantık boğada +%16, ayıda −%40).

---

## 2. Ne kurup test ettim

`scripts/scalp_strategy_research.py` — 5m bar-bar replay, gerçek spread maliyeti
(XAUUSD 1.1 pip p95, BTCUSD 5.0 pip p95; giriş/çıkışta yarımşar uygulanır), ATR bazlı SL,
RR-bazlı TP, tek-pozisyon (örtüşmesiz), max-hold.

Test edilen adaylar:
- **A1** VWAP-z(2.0), ADX<25, tüm gün
- **A2** VWAP-z(2.0), ADX<25, **07-16 UTC seans filtresi**
- **A3** VWAP-z(2.5), ADX<20, tüm gün
- **B1/B2** Noise-Area momentum (VM 1.5 / 2.0)
- **C0** referans: EMA50/200 trend takip (kıyas tabanı)

Veri: MT5'ten taze çekim (`scripts/fx_build_recent_cache.py`), broker offset UTC+3
düzeltmeli. 3 günlük: XAUUSD 1202 bar, BTCUSD 1201 bar.

---

## 3. 3 GÜNLÜK SONUÇ (asıl istenen)

| Strateji | XAUUSD (n / WR / net pip / PF) | BTCUSD (n / WR / net pip / PF) |
|---|---|---|
| A1 VWAP-z2.0 tüm-gün | 43 / %46.5 / **+346** / 1.38 | 44 / %38.6 / **+69** / 1.02 |
| **A2 VWAP-z2.0 07-16 UTC** | **17 / %58.8 / +455 / 2.48** | **14 / %42.9 / +353 / 1.36** |
| A3 VWAP-z2.5 ADX<20 | 22 / %45.5 / +87 / 1.18 | 28 / %39.3 / +140 / 1.07 |
| B1 Noise-Area VM1.5 | işlem yok | 1 işlem / −311 |
| C0 referans EMA trend | 69 / %33.3 / **−621** / 0.79 | 64 / %48.4 / +4089 / 1.62 |

**3 günde A2 her iki enstrümanda da pozitif ve en yüksek PF'li gerçek-sinyal adayı.**
Referans EMA-trend XAU'da net zarar (−621 pip) — yani "trend takip" bu pencerede çalışmadı,
ortalamaya-dönüş çalıştı. Bu, araştırmanın "altında yön değil, volatilite/timing edge'i var"
bulgusuyla uyumlu.

**Ama 3 gün = ~14-17 işlem.** Bu, bir edge'i kanıtlamak için çok az; güven için 100+ gerek.

---

## 4. 32 GÜNLÜK BAĞLAM (dürüstlük kontrolü)

| Strateji | XAUUSD net pip / PF | BTCUSD net pip / PF |
|---|---|---|
| A1 VWAP-z2.0 tüm-gün | +87 / **1.01** (n=366) | **−798** / 0.97 (n=303) |
| A2 VWAP-z2.0 07-16 UTC | +257 / 1.04 (n=174) | +457 / 1.04 (n=137) |
| A3 VWAP-z2.5 ADX<20 | **−618** / 0.90 | **−1956** / 0.88 |
| B1 Noise-Area | +144 / 1.30 (n=10) | +934 / 1.33 (n=16) |
| C0 referans EMA trend | −3471 / 0.89 | −4503 / 0.94 |

**Kritik bulgu:** 3 günde parlayan A2, 32 günde PF 2.48→**1.04** ve 1.36→**1.04**'e indi.
Yani 3 günlük kâr büyük ölçüde **birkaç iyi güne** bağlıydı — kalıcı edge değil.

---

## 5. A2 dürüstlük testi (neden temkinliyim)

**Gün-gün tutarlılık (32g, XAUUSD):** 32 işlem-gününün **16'sı pozitif, 16'sı negatif** (%50).
Kâr birkaç günde toplanmış (09-11: +521, 09-18: +290), komşu günler −344, −311.
BTCUSD'de %61 pozitif — biraz daha iyi ama yine dağınık.

**Maliyet duyarlılığı (en önemli):**
- XAUUSD: 1.1 pip spread'de exp +1.48 pip/işlem; spread **2× olursa +0.41** (neredeyse sıfır).
- BTCUSD: 5 pip spread'de exp +3.34 pip; spread **10 pip olursa −3.72** (negatife döner).
→ **Edge spread'e aşırı duyarlı.** Gerçek spread p95'in üstüne çıktığı (haber/volatilite)
günlerde edge kayboluyor.

**Yön asimetrisi:** XAU'da LONG pozitif (+521), SHORT negatif (−264). BTC'de tersi:
SHORT pozitif (+578), LONG negatif (−121). **Tutarlı bir yön edge'i yok** — bu bir
"hangi tarafa meyilliydiyse o dönem kazandı" görüntüsü; sinyalin kendisi yön ayrımı yapmıyor.

---

## 6. Sonuç ve öneri

**3 günlük replay sonucu (istenen):** Session-VWAP z-skor ortalamaya dönüş (A2, 07-16 UTC
seans filtresi) **XAUUSD'de +455 pip (PF 2.48), BTCUSD'de +353 pip (PF 1.36)** — her ikisi de
maliyet sonrası net pozitif.

**Dürüst değerlendirme:** Bu **umut verici bir aday ama kanıtlanmış bir edge değil.** Çünkü:
1. Örneklem çok küçük (14-17 işlem) → istatistiksel olarak anlamsız.
2. 32 güne uzatılınca PF ~1.04'e iniyor (kenar eriyor).
3. Gün-gün tutarlılık %50 (yazı-tura); kâr 2-3 güne yığılı.
4. Maliyet duyarlılığı yüksek; spread normalin 2× olduğu an edge biter.
5. Yön edge'i yok (LONG/SHORT asimetrisi enstrümandan enstrümana ters).

**Öneri (kullanıcı "uzununa sonra bakarız" dedi):**
- **Longuna bakılacak aday: A2 (VWAP-z reversion + ADX + seans filtresi).** Ama kurmadan
  önce şu 3 şart test edilmeli:
  1. **3-6 aylık** veri (1000+ işlem) → asıl kanıt;
  2. **walk-forward** (4+ pencere) — kâr tek döneme bağlı mı?
  3. **Rejim etiketi** (trend vs range günü ayrımı) — edge yalnız range günlerinde mi?
- Noise-Area (B1) BTCUSD'de 32g'de PF 1.33 ama **n=16** → çok zayıf örneklem, takip edilmeli.
- ORB'u **denemeyin** (araştırma + literatür net falsifiye).

---

## 7. Artefaktlar

| Dosya | İçerik |
|---|---|
| `scripts/fx_build_recent_cache.py` | MT5'ten taze 5m/15m cache (offset düzeltmeli) |
| `scripts/scalp_strategy_research.py` | Ana harness: 5 strateji + bar-bar SL/TP sim + gerçek spread |
| `scripts/scalp_a2_honesty.py` | A2 dürüstlük testi (gün-gün, maliyet, yön) |
| `outputs/scalp_cache_3d_5m.json` | 3 günlük 5m veri |
| `outputs/scalp_cache_32d_5m.json` | 32 günlük 5m veri (bağlam) |

**Çalıştırma:**
```bash
python scripts/fx_build_recent_cache.py --days 4 --symbols XAUUSD,BTCUSD --tf 5m --out outputs/scalp_cache_3d_5m.json
python scripts/scalp_strategy_research.py --cache outputs/scalp_cache_3d_5m.json --label "3 GUN"
python scripts/scalp_a2_honesty.py
```
