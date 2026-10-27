# Zero-Lag MACD + WaveTrend Çoklu Zaman Dilimi Taraması — XAUUSD / BTCUSD

Tarih: 2026-10-27 · Veri: MetaTrader 5 (bid mum, anlık spread) · Script: `scripts/zlwt_tarama_xau_btc.py` (tur 1), `scripts/zlwt_tarama_tur2.py` (tur 2), `scripts/zlwt_tarama_10k.py` (10k kasa tekrarı)
Sonuç dosyaları: `scripts/zlwt_tarama_xau_btc.json`, `scripts/zlwt_tarama_tur2.json`, `scripts/zlwt_tarama_10k.json`, `scripts/zlwt_tarama_tur2_10k.json`

## 1. Kısa sonuç

**Bu gösterge ailesiyle, bu test düzeninde, paper'a alınabilecek bir AL/SAT stratejisi bulunamadı.**
96 konfigürasyon/sembol tarandı. BTC'de hiçbir konfigürasyon hem eğitim hem test döneminde pozitif değil. Altında 2 konfigürasyon iki dönemde de pozitif; ikisi de küçük ve seçim kriterine girmedi. Eğitimde en iyi seçilen kurallar testte zarar etti; çift spread stresi de negatif. Karar: **reject** (her iki sembol ve ortak kural için).

## 2. TradingView formülleri (kaynak koddan doğrulandı)

### Zero Lag MACD Enhanced 1.2 (albert.callisto, Glaz tabanlı)
Kaynak: https://www.tradingview.com/script/kfFN7M7u/

```
zlFast = 2*EMA(close,12) - EMA(EMA(close,12),12)
zlSlow = 2*EMA(close,26) - EMA(EMA(close,26),26)
ZLMACD = zlFast - zlSlow
sinyal = 2*EMA(ZLMACD,9) - EMA(EMA(ZLMACD,9),9)     # useOldAlgo=false: sinyal de zero-lag
hist   = ZLMACD - sinyal
```
Seçenekler: `useEma=true` (SMA "Glaz modu" kapalı), `useOldAlgo=false`.

**Depodaki fark:** `backend/app/macd_mtf.py` (`_zl_macd_status`) ve `scripts/zlmacd_wavetrend_mtf_xau_btc.py` MACD çizgisini DEMA ile doğru hesaplıyor ama sinyal çizgisini **düz EMA(9)** ile alıyor. TradingView'daki orijinal sinyali de zero-lag yapıyor; bu yüzden canlı tarayıcıdaki kesişimler TradingView'dan birkaç bar geç gelir. Yeni script TV ile birebir.

### WaveTrend [LazyBear]
Kaynak: https://www.tradingview.com/script/2KE8wTuF-Indicator-WaveTrend-Oscillator-WT/

```
ap  = hlc3
esa = EMA(ap,10);  d = EMA(|ap-esa|,10)
ci  = (ap-esa) / (0.015*d)
wt1 = EMA(ci,21);  wt2 = SMA(wt1,4)
bantlar: +60/+53 aşırı alım, -60/-53 aşırı satım
```
LazyBear'ın kullanımı: aşırı satım bandının altında wt1, wt2'yi yukarı keserse AL; aşırı alım bandının üstünde aşağı keserse SAT.
Canlı tarayıcı (`technical_analysis._wavetrend`) 7/1/4 "hızlı" parametre kullanıyor; bu LazyBear varsayılanı değil.

## 3. Tarama düzeni (koşudan önce kilitlendi)

- Giriş dilimleri: 5m, 15m, 30m, 1h. Üst dilimler: 5m→(30m,4h), 15m→(1h,4h), 30m→(4h,1d), 1h→(4h,1d). Üst dilimde yalnızca kapanmış bar.
- 12 kural: ZL kesişim (ham / sıfırın doğru tarafı / ters tarafı), WT bölge kesişimi (60 / 53 / 53+hist), ZL kesişim+WT yönü, üst dilim ZL yönü + WT 53, üst dilim ZL yönü + WT geri çekilme (sıfır altı yukarı kesişim), iki üst dilim ZL + ZL kesişim, üst ZL+WT yönü + ZL kesişim, iki üst dilim ZL + WT geri çekilme.
- 2 çıkış: `2r` (hedef 2R) ve `wt_ters` (4R tavan, ters WT kesişiminde çıkış). Stop 1.2 ATR(14), 1R'de başabaş. Üst üste 2 stop → 2 bar bekleme.
- Risk haftalık kasanın %2'si, her hafta 1000 USD. XAU 07–21 UTC, BTC tüm saatler.
- Eğitim 8 hafta (03 Ağu – 25 Eyl), test 4 hafta (28 Eyl – 23 Eki). Seçim yalnızca eğitim bakiyesine göre; test bir kez okundu.
- Dönem bağlamı: eğitimde BTC +%31, altın +%1.8; testte BTC −%4.5, altın −%2.5 (zirve 4228, dip 3976).

## 4. Tur 1 sonuçları

| | XAUUSD | BTCUSD |
|---|---|---|
| Eğitimde pozitif konfig (≥12 işlem) | 9 / 70 | 21 / 88 |
| Eğitim+test pozitif | 2 / 96 | 0 / 96 |
| Eğitim ilk 10'un testte pozitif olanı | 2 | 0 |
| Seçilen | 15m / wt_53 / 2r | 5m / ust1_zl_wt_geri / 2r |
| Seçilenin eğitim → test | +172 → −80 (26 işlem, PF 0.60) | +428 → −665 (196 işlem, PF 0.54) |
| Ortak kural | 5m / ust1_zl_wt_geri / wt_ters: XAU −254, BTC −705 | |

Kural ailesi bazında (8 konfigürasyon toplamı, eğitim / test):

| Kural | XAU | BTC |
|---|---|---|
| ust1_zl_wt53 | −112 / +96 | −175 / −598 |
| ust12_wt_geri | −341 / +38 | −7 / −530 |
| wt_60 | −254 / −147 | −1273 / −1282 |
| zl_kesim (ham) | −3820 / −1666 | −6725 / −5563 |

Okuma:
- **Sinyal sıklığı arttıkça zarar artıyor.** 5m toplamı XAU −9.5k / BTC −16k; 1h toplamı XAU −1.2k eğitim, +0.5k test; BTC −0.7k / −1.1k. Ham ZL kesişimi en kötü; filtreli WT bölge kuralları en az zararlı.
- **İsabet %20–30, hedef 2R.** Bu oranda 2R ile başabaş noktası ~%33; strateji yapısal olarak eksi. Stop ve hedef tetikleri: seçilen BTC kuralında 196 işlemin 114'ü stop, 53'ü başabaş, 29'u hedef.
- Çift spread stresi, seçilen her iki kuralda da negatif.

Altında iki dönemde de pozitif kalan iki konfigürasyon: `5m/ust1_zl_wt53/wt_ters` (+89 → +13, 41/19 işlem) ve `5m/wt_60/2r` (+22 → +103, 127/45 işlem). İkisi de düşük tutarlı; seçime girmedi.

## 5. Tur 2 (ilk sonuca bakıldıktan sonra tanımlandı — seçim yanlılığı taşır)

En az zararlı 3 aile (ust1_zl_wt53, ust1_zl_wt_geri, ust12_wt_geri), 15m/30m/1h, stop 2.0 ATR, hedef 1.5R. 18 konfigürasyon/sembol.

- XAU: seçilen 15m/ust1_zl_wt_geri/2r +8.5 → −113. **1h ve 30m altın konfigürasyonları 0 işlem:** 1000 USD kasa, %2 risk = 20 USD; XAU min lot 0.01 × 100 = fiyat başına 1 USD → stop en fazla 20 USD olabilir. 1h ATR ~13, 2 ATR = 25 > 20, pozisyon açılamıyor. Bu, altında üst dilim testini sınırlıyor; sinyalin değil, kasa modelinin sonucu.
- BTC: seçilen 15m/ust1_zl_wt_geri/wt_ters +109 → −95 (74 işlem, PF 0.79). Ortak kural negatif.
- Karar yine **reject**.

## 6. Anlık çoklu dilim tarama (27 Eki 2026, 19:25 UTC kapanış)

| Sembol | 5m | 15m | 30m | 1h | 4h | 1d |
|---|---|---|---|---|---|---|
| XAUUSD ZL yönü | yukarı | yukarı | aşağı | yukarı | yukarı | aşağı |
| XAUUSD WT1/WT2 | 22.5 / 14.9 | 34.0 / 32.2 (AL kesişimi) | 47.0 / 49.1 | 41.6 / 36.4 | −26.3 / −40.4 | −64.5 / −54.3 (aşırı satım) |
| BTCUSD ZL yönü | aşağı | aşağı | aşağı | yukarı | yukarı | aşağı |
| BTCUSD WT1/WT2 | 21.2 / 26.5 | 47.2 / 48.2 | 51.8 / 52.3 | 36.4 / 28.3 | −36.5 / −45.3 | −37.0 / −28.1 |

Her iki sembolde de dilimler arası uyum yok; günlük aşağı, 4h/1h yukarı, 30m aşağı. Backtest'te kurallar reddedildiği için bu tablo işlem önerisi değil, durum özeti.

## 7. Sınırlar ve ne yapılmadı

- Komisyon bilinmiyor, sıfır yazılmadı. Spread anlık snapshot; geçmiş spread yok. Haber filtresi yok. Kayma yok.
- Aynı mumda stop ve hedef birlikteyse stop sayıldı.
- 96 (+18) konfigürasyon tarandı; eğitim en iyisi seçim yanlılığı taşır, test bu yüzden ayrıldı. Yine de 12 hafta kısa; tek rejim (BTC +%31 eğitim, −%4.5 test) sonucu etkiler.
- Altın üst dilim (30m/1h) testi, 1000 USD kasa + 0.01 lot tabanı yüzünden kısmen boş kaldı; bölüm 8'deki 10k tekrarı bu boşluğu kapattı.

## 8. 10.000 USD kasa tekrarı (aynı kural seti, aynı haftalar, risk %2)

Amaç: 1000 USD kasada 0.01 lot tabanı altın 30m/1h stoplarını engelliyordu. 10k ile risk bütçesi 200 USD olunca bütün konfigürasyonlar işlem açabildi (altın uygun konfig 70 → 84; tur 2'de 2 → 7).

**Tur 1 (96 konfig):**

| | XAUUSD | BTCUSD |
|---|---|---|
| Eğitimde pozitif (≥12 işlem) | 8 / 84 | 23 / 88 |
| Eğitim+test pozitif | 2 / 96 (aynı ikisi: 5m/ust1_zl_wt53/wt_ters, 5m/wt_60/2r) | 0 / 96 |
| Eğitim ilk 10'un testte pozitifi | 2 | 0 |
| Seçilen → test | 15m/wt_53/2r: +1886 → −988 (26 işlem, PF 0.61, DD 2028) | 5m/ust1_zl_wt_geri/2r: +4435 → −6863 (196 işlem, PF 0.54, DD 7413) |
| Çift spread | −992 | −7154 |
| Ortak | 5m/ust1_zl_wt_geri/wt_ters: XAU −2848, BTC −7296 | |

Dilim toplamları (eğitim / test): XAU 5m −108k / −43k, 15m −56k / −40k, 30m −19k / −23k, 1h −42k / +1.9k. BTC 5m −169k / −182k, 15m −121k / −71k, 30m −27k / −45k, 1h −8.9k / −11.8k. Sonuç 1000 USD koşusunun ölçeklenmiş kopyası; kasa büyüyünce yapı değişmedi.

**Tur 2 (18 konfig, stop 2 ATR, hedef 1.5R):** artık altın 30m/1h de işlem açıyor, ama 7 uygun konfigürasyonun hiçbiri eğitimde pozitif değil (seçim yok). Testte 4'ü pozitif (örn. 30m/ust1_zl_wt_geri/2r −2080 → +1025, 1h/ust1_zl_wt_geri/wt_ters −992 → +207); eğitim negatifken test pozitifi tutarlılık değil, dönem etkisi. BTC seçilen 15m/ust1_zl_wt_geri/wt_ters +1000 → −1060 (74 işlem, PF 0.78). Karar **reject**.

Yani 1000 USD koşusundaki "altın üst dilim test edilemedi" boşluğu kapandı; sonuç değişmedi.

## 9. Önerilen sonraki adımlar

1. Canlı tarayıcıdaki ZL-MACD sinyal çizgisini TV ile aynı yapmak (zero-lag sinyal): `backend/app/macd_mtf.py::_zl_macd_status`. Bu bir backtest bulgusu değil, formül uyumu.
2. Eğer bu aile sürdürülecekse: yalnızca üst dilim onaylı WT bölge/geri çekilme kuralları, 15m ve üstü, 26 haftalık walk-forward (4 pencere). 5m ve ham ZL kesişimi bırakılmalı. 12 haftalık tek rejimde kanıt yok.
