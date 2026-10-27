# Günlük %50 Hedefi (1000 → 1500 USD) Taraması — XAUUSD / BTCUSD, 7 ve 14 Hafta

Tarih: 2026-10-27 · Veri: MetaTrader 5 (mt5_bridge ile aynı terminal), bid mum, anlık spread
Script: `scripts/gunluk_tavan_tarama_xau_btc.py` · Sonuç: `scripts/gunluk_tavan_tarama_xau_btc.json` · Log: `scripts/gunluk_tavan_tarama_run.log`
Gösterge formülleri: `docs/GOSTERGELER_HESAPLAMALI.HTML` (masaüstündeki GOSTERGELER.HTML ile aynı, yedek alındı)

## 1. Kısa sonuç

**Hiçbir kural seti günde +%50'yi tutarlı biçimde vermiyor.** En iyi gerçek strateji BTC'de 98 günün 26'sında 1500'e ulaştı ama aynı kuralla 42 gün kasa 300'ün altına düştü; ortalama gün sonu 740 USD. %2 riskle hiçbir strateji tek bir günde bile 1500'e ulaşmadı ve ortalama gün sonu 950–1000 arası (maliyet erozyonu).

Buna karşılık **"TAVAN" (ileriyi bilen, hiç kaybetmeyen) ölçümü** %5 riskle BTC'de 98/98, altında 69/70 gün hedefi tutuyor. Yani piyasa hareketi hedef için yeterli; eksik olan sinyalin isabeti. %50/gün için gerekli isabet ~%55–60 (2R ile); gerçek stratejiler %15–25'te kaldı.

## 2. Test düzeni (koşudan önce kilitlendi)

- Giriş 5 dk, filtre 15 dk. 1 dk mum 14 haftayı kapsamıyor (terminal maxbars 100k), bu yüzden 5 dk.
- Her gün bağımsız: 00:00 UTC'de 1000 USD; hedef 1500; kasa 300 altına inerse gün biter (iflas); gün sonunda açık pozisyon kapanır. Gün içi kasa birikimli (kazanç risk tabanına eklenir).
- XAUUSD giriş 07–21 UTC, 21:00'de kapanış, hafta içi (70 gün). BTCUSD tüm gün, 23:55 kapanış (98 gün).
- Stop 1.2 ATR(14), hedef 2R, 1R'de başabaş, giriş sonraki 5 dk açılışı, tek pozisyon. Spread snapshot (XAU 0.10, BTC 5.0). Komisyon bilinmiyor, sıfır yazılmadı.
- Risk seviyeleri %2 / %5 / %10 / %20 kasa.
- 14 hafta: 21 Tem – 27 Eki 2026; 7 hafta: 8 Eyl – 27 Eki (son 7 hafta, 14'ün alt kümesi).
- Seçim yok; her strateji × risk için bütün günler yazıldı.

Stratejiler (GOSTERGELER.HTML'deki göstergeler, TradingView formülleriyle):

| Ad | Kural |
|---|---|
| hast_stochrsi_adx | Heikin-Ashi Supertrend(10,3) yönü + StochRSI(14,14,3,3) K/D kesişimi <20 / >80 + ADX(14) ≥ 20 |
| ema_9_21_st | EMA9/EMA21 kesişimi + Supertrend yönü |
| bb_sikisma_kirilim | Bollinger(20,2) genişliği 50 barın dibi, kapanış bant dışı + DI yönü |
| donchian_adx | Donchian(20) kırılımı + ADX ≥ 25 + DI yönü |
| keltner_geri | Keltner(EMA20, 2·ATR10) ortasına geri çekilme + Supertrend yönünde devam mumu |
| zl_wt_ust | Zero-Lag MACD (TV) 15 dk yönü + 5 dk WaveTrend ±53 bölge kesişimi |
| ichimoku_tk | Tenkan/Kijun kesişimi, fiyat bulutun aynı tarafında |
| rsi2_ema200 | RSI(2) < 10 ve kapanış > EMA200 long; RSI(2) > 90 ve kapanış < EMA200 short |
| chandelier_adx | Chandelier Exit(22, 3·ATR) yön değişimi + ADX ≥ 20 |
| psar_adx | Parabolic SAR(0.02, 0.2) yön değişimi + ADX ≥ 25 |
| TAVAN | Strateji değil: her barda 1.2 ATR stop yemeden 2R'ye ulaşan yön biliniyormuş gibi alınır |

## 3. Sonuçlar (14 hafta; "hedef" = 1500'e ulaşan gün sayısı, "iflas" = 300 altına düşen gün)

### XAUUSD (70 gün)

| Strateji / risk | Hedef | İflas | Ort. gün sonu | Medyan | Pozitif gün | İşlem | İsabet | 7 hafta hedef / ort |
|---|---|---|---|---|---|---|---|---|
| TAVAN %5 | 69/70 | 0 | 1575 | 1580 | 70 | 654 | 0.54 | 34/35 / 1576 |
| TAVAN %2 | 22/70 | 0 | 1415 | 1432 | 70 | 1288 | 0.57 | 8/35 / 1403 |
| rsi2_ema200 %20 | 18/70 | 5 | 945 | 782 | 25 | 477 | 0.25 | 7/35 / 926 |
| psar_adx %20 | 11/70 | 5 | 861 | 770 | 16 | 385 | 0.19 | 3/35 / 844 |
| keltner_geri %20 | 9/70 | 17 | 694 | 464 | 16 | 599 | 0.15 | 4/35 / 679 |
| chandelier_adx %20 | 7/70 | 2 | 926 | 813 | 25 | 265 | 0.22 | 2/35 / 867 |
| donchian_adx %20 | 7/70 | 0 | 828 | 761 | 15 | 312 | 0.16 | 3/35 / 836 |
| rsi2_ema200 %10 | 6/70 | 0 | 961 | 911 | 27 | 553 | 0.24 | 2/35 / 969 |
| hast_stochrsi_adx %20 | 5/70 | 0 | 930 | 807 | 24 | 268 | 0.23 | 4/35 / 975 |
| zl_wt_ust %20 | 2/70 | 0 | 1043 | 1000 | 18 | 69 | 0.32 | 0/35 / 1032 |
| tüm stratejiler %2 | 0/70 | 0 | 963–1004 | — | 15–28 | — | 0.15–0.32 | 0/35 |

### BTCUSD (98 gün)

| Strateji / risk | Hedef | İflas | Ort. gün sonu | Medyan | Pozitif gün | İşlem | İsabet | 7 hafta hedef / ort |
|---|---|---|---|---|---|---|---|---|
| TAVAN %5 | 98/98 | 0 | 1603 | 1603 | 98 | 886 | 0.55 | 49/49 / 1602 |
| TAVAN %2 | 94/98 | 0 | 1516 | 1522 | 98 | 1910 | 0.56 | 48/49 / 1515 |
| keltner_geri %20 | 26/98 | 42 | 740 | 362 | 27 | 1085 | 0.19 | 16/49 / 819 |
| rsi2_ema200 %20 | 23/98 | 29 | 785 | 585 | 27 | 976 | 0.20 | 15/49 / 834 |
| chandelier_adx %20 | 21/98 | 18 | 835 | 642 | 30 | 592 | 0.18 | 10/49 / 812 |
| hast_stochrsi_adx %20 | 17/98 | 10 | 902 | 803 | 33 | 578 | 0.20 | 9/49 / 972 |
| donchian_adx %20 | 16/98 | 9 | 775 | 578 | 20 | 682 | 0.18 | 5/49 / 734 |
| rsi2_ema200 %10 | 12/98 | 0 | 881 | 827 | 25 | 1177 | 0.21 | 8/49 / 918 |
| hast_stochrsi_adx %10 | 8/98 | 0 | 940 | 946 | 34 | 641 | 0.21 | 4/49 / 972 |
| tüm stratejiler %2 | 0/98 | 0 | 947–993 | — | 18–38 | — | 0.17–0.21 | 0/49 |

## 4. Okuma

- **%50/gün hedefine ulaşan günler, yüksek riskin (%20) ürettiği şans günleri.** Aynı kural, hedefe ulaştığından daha çok günde kasayı 300'ün altına indiriyor (BTC keltner_geri: 26 hedef, 42 iflas; rsi2: 23 hedef, 29 iflas). Medyan gün sonu 1000'in çok altında.
- **%2 riskle hiçbir strateji pozitif beklentili değil.** Ortalama gün sonu 950–1000; isabet %15–25, hedef 2R → başabaş noktası %33'ün altında. Bu, önceki haftalık taramalarla (ZL-MACD/WaveTrend, HA-Supertrend aileleri) aynı tablo.
- **TAVAN hedefi her gün tutuyor.** Piyasa, 1.2 ATR stop / 2R modeliyle bile günde +%50 için yeterli hareketi barındırıyor (%5 riskle bile). Eksik olan yön isabeti: TAVAN %55 isabetle hedefi tutuyor, gerçek kurallar %20 civarında. Dolayısıyla "daha agresif kaldıraç" değil, "daha isabetli sinyal" sorunu.
- **En az kötü aileler:** altında rsi2_ema200 (ortalama 945–991, iflas az), zl_wt_ust (tek pozitif ortalama: 1003–1043 ama 70 günde 69 işlem, yani çoğu gün sinyal yok); BTC'de hast_stochrsi_adx %10 (940, iflas 0). Hiçbiri +%50 hedefinin yakınında değil.
- 7 haftalık pencere 14 haftanın alt kümesi; sıralama ve sonuç aynı, son 7 haftada BTC ortalamaları biraz daha iyi (hast_stochrsi_adx %10: 972).

## 5. Sınırlar

- 5 dk veri; 1 dk ile daha sık sinyal olurdu ama maliyet erozyonu da artar (önceki 1 dk testleri aynı sonucu verdi).
- Spread anlık; haber saatlerinde gerçek spread daha geniş. Komisyon ve kayma yok. Gün içi haber filtresi yok.
- Aynı mumda stop ve hedef birlikteyse stop. TAVAN 96 bar (8 saat) ufukla sınırlı; bar içi stop önce sayılır (cömert değil).
- 10 strateji × 4 risk = 40 konfigürasyon/sembol; seçim yapılmadı, tüm tablo veriliyor.

## 6. GOSTERGELER.HTML güncellemesi

272 göstergeye "Hesaplama (TradingView)" sütunu eklendi. Kaynak etiketleri: TV-yardim 85 (yardım merkezi makalesinin hesaplama bölümü), TV-yardim* 34 (makale var, formül yok, genel tanım), TV-kod 2 (açık kaynak Pine: WaveTrend, Ehlers), genel 151 (topluluk/SMC/on-chain; TradingView sayfası okunmadı, yaygın tanım). Güncelleme scripti `scripts/gostergeler_html_guncelle.py`; masaüstünde yedek `GOSTERGELER.yedek_2026-10-27.HTML`.

Önemli formül notları: Zero-Lag MACD'nin TradingView sürümünde sinyal çizgisi de zero-lag (2·EMA − EMA(EMA)); canlı tarayıcı düz EMA(9) kullanıyor. WaveTrend TV varsayılanı 10/21/4, canlı tarayıcı 7/1/4.

## 7. Ne yapılabilir

1. Günde +%50 hedefi bu gösterge aileleriyle gerçekçi değil; 7 ve 14 haftalık günlük testler bunu gösteriyor. Hedefi "haftada +%X, düşük iflas" gibi ölçülebilir bir seviyeye çekmek gerekir.
2. Eğer yine de günlük hedefle devam edilecekse: TAVAN'a en yakın yapı olan "isabet ≥ %45" arayışı; aday aile RSI(2)+EMA200 (ortalama dönüş) ve HA-Supertrend+StochRSI. Ama bunlar %20 riskte bile 98 günün ≤26'sında hedefi tutuyor.
3. Canlı tarayıcı ZL-MACD sinyal formülü TV ile hizalanmalı (`backend/app/macd_mtf.py`).
