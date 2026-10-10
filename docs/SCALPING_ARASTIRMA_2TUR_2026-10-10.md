# Scalping Stratejisi Araştırması — 2. TUR (Farklı Aileler)

**Tarih:** 2026-10-10 · **Veri:** MT5 5m, XAUUSD + BTCUSD · Pencereler: 3 gün / 5 gün (Pzt-Cuma) / 32 gün
**Kısa sonuç:** 6 farklı strateji ailesi test edildi. **Hiçbiri tüm pencerelerde ve iki
enstrümanda birden kabul barajını geçmiyor.** Tek dikkat çeken: **Intraday-Momentum (son 30 dk)**
XAUUSD'de hem tutarlı hem maliyete dayanıklı — ama örneklem küçük (n≈39).

---

## 1. Test edilen aileler ve sonuç tablosu

Net pip (gerçek spread düşülerek). XAUUSD spread 1.1 pip, BTCUSD 5.0 pip.

| # | Strateji | XAU 3g | XAU 5g | XAU 32g | BTC 3g | BTC 5g | BTC 32g | Yorum |
|---|---|---|---|---|---|---|---|---|
| 1 | **Intraday-mom (son 30dk)** | +31 | +31 | **+234** | +235 | +96 | **+171** | **Tek pozitif-tutarlı aile** |
| 2 | Seans-hold 21-23 UTC | — | — | — | −43 | −286 | −397 | BTC anomali **replike olmadı** |
| 2 | Seans-hold 07-10 UTC | −129 | −129 | +402 | −315 | −359 | +471 | oynak, yönsüz |
| 2 | Seans-hold 13-16 UTC | −189 | −189 | −613 | −280 | −457 | **−2877** | kötü |
| 3 | RSI-2 MR + trend filt. | +125 | −50 | +880 | +249 | −520 | **+2936** | aşırı oynak |
| 4 | Squeeze breakout | −75 | −86 | +1439 | −1592 | −1583 | **−6441** | enstrümanlar ters |
| 5 | ORB (kontrol) | −51 | −51 | +149 | +47 | −0.4 | **−808** | literatürle uyumlu: zayıf |
| 6 | VWAP trend-devam | −669 | −795 | −2954 | +2938 | +1829 | **−4768** | dengesiz |

**Okuma:** Satırların çoğunda gün/32g ve XAU/BTC **ters işaretli**. Bu, "hangi dönemde hangi
enstrüman meyilliydiyse o kazandı" rastgeleliğin işareti — kalıcı edge değil. Özellikle:
- **Squeeze:** 32g'de XAU +1439 / BTC −6441 (tam zıt).
- **VWAP trend-devam:** 5g'de BTC +1829 (ama 2 günden geliyor) / 32g'de BTC −4768 (negatif).
- **RSI-2 MR:** 32g'de iki enstrümanda pozitif ama 5g'de BTC −520 → tutarsız.

---

## 2. Öne çıkan: Intraday-Momentum (son 30 dakika) — detay

**Mantık (Baltussen/Gao, JFE):** Günün açılışından T−30dk'ya kadarki getiri (rROD),
son 30 dakikanın yönünü öngörür. T−30'da rROD>0 ise long, <0 ise short; seans kapanışında flat.

| Pencere | Enstrüman | n | net pip | exp/işlem | WR | PF | maxDD |
|---|---|---|---|---|---|---|---|
| 5g | XAUUSD | 4 | +31 | +7.7 | %50 | 1.74 | −12.5 |
| 5g | BTCUSD | 4 | +96 | +24.1 | %50 | 1.66 | −32.3 |
| 32g | XAUUSD | 39 | **+234** | +6.0 | %59 | **1.32** | −122.0 |
| 32g | BTCUSD | 32 | +171 | +5.3 | %53 | 1.11 | −596.1 |

**Maliyet dayanıklılığı (spread 2×):**

| Enstrüman | gerçek spread | 2× spread |
|---|---|---|
| XAUUSD 32g | +234 pip / PF 1.32 | **+212 pip / PF 1.29** (dayanıklı ✓) |
| BTCUSD 32g | +171 pip / PF 1.11 | +20 pip / PF 1.01 (**eriyor** ✗) |

**Gün-gün (32g):** XAUUSD 39 günün **23'ü pozitif (%59)**; BTCUSD 32 günün 17'si (%53).
XAUUSD'de LONG 14 / SHORT 25 işlem — yön dağılımı makul, tek tarafa yığılma yok.

**Değerlendirme:** Bu, 2. turun en umut verici bulgusu — **yalnız XAUUSD'de**. Günde 1 işlem,
düşük turnover (maliyete dayanıklı), literatürde en güçlü intraday edge olarak geçiyor.
Ama **n≈39** örneklem ve 3g/5g'de sadece 4 işlem; istatistiksel kanıt için yetersiz.

---

## 3. Neden çoğu aile başarısız — kök nedenler

1. **Rejim/yon belirsizliği:** Aynı strateji XAU'da ve BTC'de zıt işaret → ortak bir yapısal
   edge yok, dönem-meyil (beta) var.
2. **Maliyet:** 5m'de spread, küçük brüt avantajları yiyor. BTC'de 5 pip spread, çoğu
   stratejiyi sıfıra/negatife çekiyor (BTC 2× spread → hepsi eriyor).
3. **Tek güne bağımlılık:** 5g BTC sonuçlarının çoğu tek güne (Pzt/Prş) yığılı.
4. **Örneklem:** 3-5 gün = 3-4 işlem/strateji → gürültü, kanıt değil.

---

## 4. Sonuç ve sıradaki adım

**2. tur özeti:** 6 aileden **hiçbiri kabul barajını geçmedi**. Test edilen "popüler" ailelerin
(ORB, seans-hold, squeeze) literatürdeki zayıflığı bu veride de doğrulandı.

**En umut verici tek aday: Intraday-Momentum (son 30 dk), XAUUSD.** Gerekçe: 32g'de PF 1.32,
%59 pozitif gün, spread 2× olunca bile dayanıyor, literatürde en yüksek kanıtlı intraday edge.
Eksik: örneklem küçük (n≈39) — ama bu "günde 1 işlem" doğası gereği böyle; güven için 1-2 YIL
veri (~250-500 işlem) gerekir.

**Öneri (uzun vade):** Intraday-Momentum XAUUSD'yi 1-2 yıllık veriyle test et — tek başına ve
VWAP-z reversion (1. tur A2) ile birlikte. Walk-forward + rejim etiketi şart. ORB/seans-hold/
squeeze/RSI-2 aileleri bu veride elendi, öncelik verme.

---

## 5. Artefaktlar

| Dosya | İçerik |
|---|---|
| `scripts/scalp_strategy_round2.py` | 6 strateji ailesi harness'i |
| `scripts/scalp_strategy_research.py` | 1. tur harness (A1-A3, B, C0) |
| `scripts/fx_build_recent_cache.py` | MT5 taze cache (tarih penceresi destekli) |
| `outputs/scalp_cache_5d_pazt_cuma.json` | 5 gün (Pzt-Cuma) |
| `outputs/scalp_cache_32d_5m.json` / `scalp_cache_3d_5m.json` | bağlam pencereleri |
