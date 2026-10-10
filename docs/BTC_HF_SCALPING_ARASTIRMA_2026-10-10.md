# Yüksek-Frekans BTCUSD Scalping Arama — ≥30 İşlem/Gün Hedefi

**Tarih:** 2026-10-10 · **Veri:** MT5 BTCUSD 1m, 30 gün (2026-09-10 → 10-10), 43.249 bar
**Hedef (kullanıcı):** BTCUSD · günde ≥30 işlem · kârlı. XAUUSD bırakıldı.
**Sonuç:** ⛔ **Hedefi geçen YOK. 90 konfigürasyonun 0'ı ≥30 işlem/gün VE net>0 sağladı.**
Kök neden: 1m ölçeğinde sinyalin brüt yön edge'i **spread'den daha küçük** (~%0.001-0.005 vs
%0.006 spread).

---

## 1. Koşullar ve fizibilite

| Ölçüm | Değer |
|---|---|
| BTCUSD gerçek spread (MT5 canlı) | **5.0 pip = $5 = %0.0060** round-trip |
| 1m ATR(14) medyan | $49.24 = **%0.0602** |
| 1 bar mutlak getiri medyan | %0.0214 |
| 5 bar mutlak getiri medyan | %0.0474 |
| Günlük aralık medyan | %2.48 |
| Bar/gün | 1.395 |

Spread 1m ATR'nin ~%10'u. Yani 1m'de her işlem, ortalama 1-bar hareketinin yarısını maliyete
verir. **Bu, yüksek-frekansın matematiksel engeli.**

---

## 2. Test edilen 6 aile × 90 konfigürasyon

| Aile | Parametreler |
|---|---|
| 1. BB z-skor fade | periyot {20,50} × z {1.5,2.0,2.5} × SL/TP 3 çift |
| 2. RSI(n) aşırı-uç fade | n {2,3,7,14} × eşik 4 çift × SL/TP 2 çift |
| 3. N-bar kırılım | k {5,10,20,30} × SL/TP 4 çift |
| 4. EMA çift-kesişim | {5/20, 9/21, 12/26, 3/10} × SL/TP 3 çift |
| 5. VWAP bant fade | z {1.5,2.0,2.5,3.0} × SL/TP 2 çift |
| 6. Ardışık-mum fade (run) | run {3,4,5} × SL/TP 2 çift |

Simülatör: girişte/çıkışta spread'in yarısı aleyhte, ATR değil sabit $ SL/TP, tek pozisyon
(örtüşmesiz), max-hold. Gerçek 5 pip spread düşülerek.

---

## 3. Sonuç: 0 / 90 konfigürasyon hedefi geçti

**Tüm konfigürasyonlar net NEGATİF.** En az zarar edenler (hepsi yine negatif):

| Strateji | /gün | net pip | PF |
|---|---|---|---|
| RSIfade p14 10/90 SL40/TP40 | 0.4 | −110 | 0.63 |
| RSIfade p3 5/95 SL40/TP40 | 33.1 | **−8511** | 0.65 |
| EMA12/26 SL50/TP100 | 43.5 | −8671 | 0.82 |
| RunFade r5 | 48.6 | −9826 | 0.72 |
| BBfade p20 z2.0 | 106.3 | −18042 | 0.83 |
| VWAPfade z1.5 | 339.4 | −24223 | 0.89 |

**≥30 işlem/gün VE net>0 olan: 0 / 90.**

---

## 4. Kök neden — brüt edge yok (maliyet değil, sinyal sorunu)

Maliyeti tamamen SIFIRLAYIP sadece sinyalin yön öngörüsünü ölçtüm (bar-yönü, SL/TP yok):

| Strateji | /gün | brüt exp | brüt PF | breakeven spread |
|---|---|---|---|---|
| BBfade p20 z1.5 | 201 | −0.77 pip | 0.96 | −0.77 pip |
| BBfade p20 z2.0 | 126 | −0.98 pip | 0.95 | −0.98 pip |
| RSIfade p2 5/95 | 113 | −0.87 pip | 0.96 | −0.87 pip |
| RunFade r3 | 180 | −1.37 pip | 0.93 | −1.37 pip |
| VWAPfade z1.5 | 339 | −2.30 pip | 0.89 | −2.30 pip |
| BRK k10 | 132 | −3.83 pip | 0.82 | −3.83 pip |

**Brüt PF < 1.0 (hepsi 0.82-0.96).** Yani sıfır maliyetle bile bu stratejiler zarar ediyor —
spread sorun değil, **sinyalin yön öngörüsü yok.** "Breakeven spread" sütunu negatif: maliyet
sıfırın altına inse bile kâr olmaz.

Uzun horizonlarla (30-60 bar) tek bir zayıf pozitif göründü (BBfade p50 z2.0: brüt +0.016%),
ama gerçek SL/TP simülasyonunda **2507 işlem, net −12312 pip, PF 0.85**; alt pencerelerin
2/3'ünde negatif. Sıfır maliyetle bile net −63 pip. **Yanılsama.**

---

## 5. Neden 30 işlem/gün + kâr aynı anda gelmiyor (matematik)

- Günde 30+ işlem = ortalama 1m-5m ölçeğinde giriş/çıkış.
- Bu ölçekte tipik hareket = 0.02-0.05%.
- Spread = 0.006% (yatay maliyet) + **her işlemde SL/TP gürültüsü**.
- Kazanmak için ortalamanın spread'i **artı** gürültü bandını geçmesi gerekir; 1m'de bu
  sistematik olarak mevcut değil (BTC 1m ≈ rastgele yürüyüş + mikro-dönüş bariyeri).

Yani "günde 30 işlem + kârlı" hedefi, **1m'de yön öngörüsü olmadan matematiksel olarak
mümkün değil.** Daha yüksek frekans (tick/L2) veya maker-rebate/negatif komisyon gerekir —
ikisi de mevcut kurulumda yok.

---

## 6. Sonuç ve dürüst öneri

**Hedef (BTCUSD, ≥30 işlem/gün, kârlı) bu koşullarda sağlanamadı.** Sebep maliyet değil;
1m/5m ölçeğinde BTC'de sistematik yön edge'i yok.

**Gerçekçi alternatifler:**

1. **İşlem/gün barajını gevşet.** Önceki turlarda tek tutarlı edge **günde 1 işlem** ölçeğindeydi
   (intraday-momentum, VWAP-z). 5-15 işlem/gün + küçük pozitif, 30+ işlem/gün + negatiften iyidir.
2. **Maliyet yapısını değiştir.** Maker rebate / negatif komisyonlu venue + limit emir
   (spread ödemezsin) → HF matematiği değişir. Mevcut MT5 CFD koşullarında yok.
3. **Volatilite patlamalarında yoğunlaş** (haber/FOMC/session open): işlem sayısı düşer ama
   işlem başına hareket spread'i aşar. Yine "günde 30" değil, amaç dolar getirisi ise bu yol.
4. **Bariyer-free kabul et:** 1m'de mevcut tüm klasik yön stratejileri bu veride PF<1.0 → aile
   değiştirmek çözmez; problem ölçek.

**Doğrudan söylenmesi gereken:** "günde en az 30 işlem + kârlı + BTCUSD" üçü birlikte, MT5 CFD
maliyetleri ve 1m OHLCV verisiyle **gerçekleştirilemez.** Bunu kanıtlamak için 6 aile × 90
konfigürasyon + sıfır-maliyet kontrolü koşuldu; hiçbiri geçmedi.

---

## 7. Artefaktlar

| Dosya | İçerik |
|---|---|
| `scripts/btc_hf_scalp_search.py` | 6 aile × parametre grid + sabit-$ SL/TP simülatörü |
| `scripts/fx_build_recent_cache.py` | MT5 cache (1m parçalı çekim düzeltildi) |
| `outputs/scalp_cache_btc_30d_1m.json` | BTCUSD 30g 1m (43.249 bar) |
| `outputs/btc_hf_scalp_results.json` | 90 konfig sonucu |

**Çalıştırma:**
```bash
python scripts/fx_build_recent_cache.py --days 30 --symbols BTCUSD --tf 1m --out outputs/scalp_cache_btc_30d_1m.json
python scripts/btc_hf_scalp_search.py
```
