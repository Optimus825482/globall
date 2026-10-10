# FOREX BTCUSD — V4 "Günlük Yükseliş" Momentum Katmanı Kalibrasyonu

**Tarih:** 2026-10-10 · **Veri:** Binance Global public REST (keyless), BTCUSDT
**Kapsam:** 15m ana + 1h/4h trend · 240 gün (2026-02-02 → 2026-10-10), 23.999 kapanmış 15m bar
**Son karar:** ⛔ **Kabul kriterleri GEÇİLMEDİ → katman KURULMADI.** (Dürüst sonuç; brief md.6)

---

## 1. Özet (TL;DR)

V4'ün altcoin momentum filtresi BTC'ye taşındı ve **BTC'ye özel eşik grid'i**
(ATR%, ret_8h, slope, ADX + EMA200/SuperTrend trend kapıları; long ve long+short)
train/test + walk-forward ile tarandı. Sonuç:

- **Brüt sinyal var ama kalıcı, maliyete dayanıklı, istatistiksel olarak sağlam edge YOK.**
- Ham görünen "yüksek lift" (10-20x) bir **baz-oran ~0 artefaktıdır**, gerçek beceri değil.
- İsabet-oranı lifti **haftalık/aylık pencerelerde ~1.0x**; yalnız büyük-hareket hedefinde (>1% / 8s)
  1.8-1.9x çıkıyor **fakat örtüşmesiz bağımsız örneklem n=40** (brief barajı 50-100) ve
  **her iki yarıda tek başına anlamlı değil** (p=0.13 / 0.08).
- Ortalama-getiri excess'i (asıl PnL sürücüsü) **blok-bootstrap p≈0.17-0.27 → anlamsız**.
- Çıkış kuralına kırılgan: geniş TP'de pozitif, sıkı TP/SL'de **negatif**.

**Karar:** Brief md.6 gereği kurulum yapılmadı. Özetle: **"BTC'de bu yöntemle (bu ölçekte) edge yok."**

---

## 2. V4 filtresi BTC'de neden çalışmıyor (briefteki bulgu doğrulandı)

Bu çalışmanın harness'i briefteki bulguyu **birebir** yeniden üretti:

| Ölçüm | Brief | Bu çalışma |
|-------|-------|-----------|
| V4 filtresi tetikleme (son ~5924 bar) | 26 / 5924 = %0,44 | **26 / 5924 = %0,44** ✅ |
| Sinyal sonrası +4s getiri | +%0,07 | **+%0,074** ✅ |
| Baz (tüm barlar) +4s getiri | +%0,07 | **+%0,068** ✅ |
| Ayrım (lift) | yok | **yok** ✅ |

**Kök neden — ölçek uyumsuzluğu.** BTC 15m medyanları (240g):

| Gösterge | V4 altcoin eşiği | BTC 15m medyanı | Kat farkı |
|----------|:----------------:|:---------------:|:---------:|
| ATR% | ≥ 0,5 | **0,255** | ~2x |
| ret_8h | ≥ %2,0 | **%0,013** | ~150x |
| slope (%/bar) | ≥ 0,30 | **0,0005** | ~600x |

V4 eşikleri meme/altcoin rejimine (ATR %2-5) kalibre; BTC yapısal olarak çok daha sakin.

---

## 3. Yöntem

1. **Veri:** Binance Global `api.binance.com/api/v3/klines`, sayfalı çekim; oluşmakta olan son
   mum atıldı; 240 günde **boşluk yok** (16dk üstü gap = 0).
2. **Göstergeler:** V4 `technical_analysis.py` kanonikleriyle birebir — ATR(14), ADX(14)+DI,
   LinReg slope(10), EMA50/200, SuperTrend(10,3), RSI, MFI, Bollinger.
   _(Doğrulama: 26/5924 + lift≈yok çıktısı, formüllerin doğru taşındığını kanıtlar.)_
3. **Eşik grid'i (BTC'ye özel):** ATR% [0.15,0.25,0.35,0.5] × ret_8h [0.3,0.5,0.8,1.2] ×
   slope [0.03,0.06,0.10,0.15] × ADX [15,20,25] × kapı {none, EMA200, SuperTrend, ikisi} ×
   yön {long, short} × ufuk {2,4,8,24}s × maliyet {gerçekçi, muhafazakâr} = **12.288 kombinasyon**.
4. **Maliyet (BTCUSD CFD):** MT5 p95 spread 5 pip (pip_size=1.0) → gerçekçi ≈ %0.0072 round-trip;
   muhafazakâr (spread 15pip + 3pip slip + funding) ≈ %0.025. Her ikisi de test edildi.
5. **Overfit koruması:** ilk yarı train / ikinci yarı test + **6 pencereli walk-forward** +
   **pencere-yerel baz** düzeltmesi + **çeyrek/aylık** kırılım.
6. **Anlamlılık:** (a) naif bootstrap, (b) **otokorelasyon-farkındalıklı zaman-blok bootstrap**,
   (c) örtüşmesiz (bağımsız) alt-örneklem, (d) binom testi.

---

## 4. Sonuçlar

### 4.1 Grid taraması — kabul barajını geçen YOK

| Kabul kriteri (brief) | Sonuç |
|---|---|
| lift > 1.2x | Haftalık/aylık isabet lifti **~1.0x**; yalnız >1% hedefinde 1.8x (aşağıya bak) |
| test'te de tutuyor | Yarı-bazlı kısmen; **çeyrek bazlı 2/4 negatif** → kırılgan |
| n ≥ 50-100 | Örtüşmesiz bağımsız işlem **40** (sıkı eşikte 13-31) → **GEÇMEDİ** |
| net > 0 | Geniş TP'de +, sıkı TP/SL'de **−** → kırılgan |
| (ek) anlamlılık | **blok-bootstrap p = 0.17-0.27** → anlamsız |

### 4.2 En iyi görünen aday ve neden yine de geçmiyor

Aday: **long, 15m, H=8s, ret_8h≥1.2 & ATR%≥0.5 & slope≥0.15 & ADX≥25**

| Metrik | Değer |
|--------|-------|
| Ham sinyal barı | 224 |
| Örtüşmesiz bağımsız işlem | **40** (~6 günde 1) — barajın altı |
| Ortalama net getiri | +0.337% (baz +0.016%, excess +0.321%) |
| Blok-bootstrap excess p | **0.211** (anlamsız) |
| Çeyrek bazlı excess | +0.258, **−0.052**, +0.043, +0.695 |
| İşlem sim. SL2/TP4 ATR | n=31, WR %51.6, +0.39%/işlem |
| İşlem sim. SL1.5/TP3 ATR | n=40, WR %35.0, **−0.15%/işlem** ⛔ |

**Ham "ret_lift" ≈ 12-21x neden yanıltıcı:** baz oran ≈ +0.016% (sıfıra çok yakın) olduğu için
herhangi bir küçük pozitif sinyal getirisi oranı çok büyük gösteriyor. Bu bir **artefakt**;
beceri göstergesi değil. Brief'in asıl istediği **maliyet sonrası net > 0 VE anlamlı lift**'tir.

### 4.3 Trend kapısı (EMA200 / SuperTrend) fayda katmıyor

- EMA200 kapısı ve SuperTrend kapısı **naif sonuçları kötüleştirdi** (ör. 24s lift 12.4x→7.0x/9.0x).
- Önemsiz bir kapıyla kıyas (yalnız-EMA200 / yalnız-SuperTrend) doğruladı: sinyalin "gücü"
  aslında **"yükseliş trendinde long olmak"** = piyasa betası; seçici momentum değil.
- SuperTrend boğa her zaman-long referansı: 15m'de işlem sim. **+0.007%/işlem** (≈ sıfır) → filtre
  bu betadan fazlasını üretmiyor.

### 4.4 Short tarafı: kesin negatif

6144 short kombinasyonunun yalnız **116'sı** test'te pozitif; BTC'nin 240 günlük yükseliş
eğiliminde short momentum sistematik olarak kaybediyor. **Short tarafı kapatılmalı.**

### 4.5 4h zaman dilimi: en "iyi" görünen, ama yine anlamsız

BTC'nin doğal "günlük" ölçeği 4h'tir (medyan ATR% 1.21). Burada ham excess küçük ama tutarlı
görünüyor, **fakat**:
- blok-bootstrap p = **0.35-0.43** → anlamsız,
- çeyrek bazlı **2/4 negatif** (26-02→26-04 çeyreği −0.24%).

### 4.6 Diğer varlıklar (brief md.7 önizleme)

Aynı iskelet PAXGUSDT (altın proxy), ETHUSDT ile denendi → **hiçbirinde edge yok**
(4h/15m, hepsi p>0.4, çeyrek bazlı çoğu negatif). Yöntemin kendisi varlık-bağımsız işe yaramıyor.
_(EURUSDT satırı geçersizdir: BTC spread'i $1.12 fiyatına uygulandığı için maliyet artefaktı.)_

---

## 5. Yorum — neden momentum BTC'de zayıf

1. **Verimli/olgun piyasa:** BTC 15m ölçeğinde momentum sürekliliği çok kısa ömürlü; 8-24s
   ufukta sinyal getirisi baz orandan ayrışmıyor.
2. **Beta'ya çöküş:** "Yukarı momentum + trend kapısı" fiilen "trendde long" demek. Seçicilik
   eklenince (filtre) edge ya kayboluyor ya rejim-sürüklenmesi oluyor (train/test işaret değişimi).
3. **Çıkış kırılganlığı:** Küçük ham avantaj, gerçek SL/TP ile ticarete çevrilince (özellikle sıkı
   stop) komisyon+spread+slippage'a yeniliyor.
4. **Örneklem yetersiz:** 240 günde bağımsız sinyal n≈40; güvenilir bir yargı için 3-5 yıl gerekir.

---

## 6. Karar ve öneriler

**Karar (brief md.6):** Bu ölçekte/yöntemde BTCUSD için **onaylanmış edge yok → otonom işlem
katmanı KURULMADI.** Yanlış bir katmanı canlıya almak, briefin uyardığı asıl risklerden biridir.

**Öneriler:**
1. **Filtreyi otonom işleme bağlamayın.** XAU/BTC'de zaten çalışan mevcut motor (SuperTrend +
   chandelier + skor) bu kalibrasyondan daha iyi bir dayanağa sahip; BTC için *ek* momentum
   katmanı katmadeğer getirmiyor.
2. İleride denenebilecek yön — **farklı türde edge**: funding/OI bazlı squeeze, seans/likidite
   modelleri, veya çok yıllık veriyle rejim-koşullu momentum (bu kalibrasyonun 240g penceresi
   tek rejim içeriyor).
3. **Aynı kalibrasyonu XAUUSD için ayrı yapın** (varlığa özel eşik); harness hazır ve yeniden
   kullanılabilir (`scripts/btc_momentum_calibration.py`).
4. İsterseniz **gölge/uyarı (advisory-only) mod**: sinyal üretir, loglar, ama **otomatik işlem
   açmaz** — sıfır maliyetli izleme. Onaylanmış edge olmadan otonom açılış önerilmez.

---

## 7. Artefaktlar (yeniden üretilebilir)

| Dosya | İçerik |
|-------|--------|
| `scripts/btc_momentum_calibration.py` | Ana harness: veri çek + göstergeler + grid + train/test + WF + maliyet. `--validate` brief bulgusunu doğrular |
| `scripts/btc_calib_analyze.py` | Kabul-kriteri eleme |
| `scripts/btc_calib_diag.py` | Kararlılık + aylık kırılım |
| `scripts/btc_calib_significance.py` | Bootstrap + rastgele kontrol |
| `scripts/btc_calib_decide.py` | Örtüşme düzeltmesi + hedef-tabanlı hit-lift |
| `scripts/btc_calib_final.py` | Zaman-blok bootstrap + always-long referansı |
| `scripts/btc_calib_trade_sim.py` | 4h + gerçek SL/TP işlem simülasyonu + çeyrek |
| `scripts/btc_calib_verdict.py` | 4h derinlemesine + kabul özeti |
| `scripts/btc_calib_hitrate.py` | Hit-lift anlamlılık + örtüşme teşhisi |
| `scripts/btc_calib_cross.py` | Diğer varlıklar (md.7) |
| `outputs/btc_momentum_calibration_240d.json` | Ham grid sonuçları (12.288 kombinasyon) |
| `outputs/btc_cache/` | BTCUSDT 15m/1h/4h önbelleği |

**Çalıştırma:**
```bash
python scripts/btc_momentum_calibration.py --days 240 --validate   # brief bulgusunu doğrula
python scripts/btc_momentum_calibration.py --days 240              # tam grid
python scripts/btc_calib_final.py                                  # nihai karar testi
```
