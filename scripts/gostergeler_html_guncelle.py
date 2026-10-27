#!/usr/bin/env python3
"""GOSTERGELER.HTML belgesine "Hesaplama (TradingView)" sutunu ekler.

Kaynaklar (2026-10-27):
  TV-yardim   : TradingView Yardim Merkezi "Built-in Indicators" makaleleri
                (hesaplama bolumu WebFetch ile okundu; scratchpad tv/formuller_*.json)
  TV-yardim*  : makale var ama hesaplama bolumu yok; genel tanim yazildi
  TV-kod      : TradingView acik kaynak Pine kodu bu oturumda/onceki oturumda okundu
  genel       : TradingView sayfasi yok veya okunmadi; yaygin bilinen tanim

Kullanim: python scripts/gostergeler_html_guncelle.py <GOSTERGELER.HTML> <formuller_klasoru>
Orijinal dosya .yedek_YYYY-MM-DD.HTML olarak kopyalanir; guncel belge ayni yola ve
docs/GOSTERGELER_HESAPLAMALI.HTML yoluna yazilir.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
from datetime import date

TV = {}  # ingilizce ad -> kayit (formuller_*.json)

# Turkce ad -> (TV ingilizce ad | None, ek/alternatif formul | None, kaynak etiketi | None)
MAP: dict[str, tuple] = {
    # ---------------- Hareketli ortalamalar
    "Arnaud Legoux Hareketli Ortalama": ("Arnaud Legoux Moving Average", None, None),
    "Ağırlıklı Hareketli Ortalama": ("Weighted Moving Average", None, None),
    "Aşırı Hareketli Ortalama (Hamming)": (None, "Hamming penceresi agirlikli ortalama: w_i = 0.54 - 0.46*cos(2*pi*i/(N-1)); HMA_hamming = Sum(w_i*src_i)/Sum(w_i). TV 'Hamming Moving Average' (yerlesik, uzunluk 20).", "genel"),
    "DEMA": ("Double Exponential Moving Average (DEMA)", None, None),
    "En Küçük Kareler H.O.": ("Least Squares Moving Average", None, None),
    "Guppy Çoklu Hareketli Ortalama": (None, "GMMA: kisa grup EMA 3,5,8,10,12,15; uzun grup EMA 30,35,40,45,50,60 (close). Gruplarin ayrismasi trend gucu, kesismesi donus.", "genel"),
    "Hareketli Ortalama (SMA)": ("Simple Moving Average", None, None),
    "Hareketli Ortalama Kanalı": (None, "Ust = SMA(high, N), Alt = SMA(low, N) (TV 'Moving Average Channel', varsayilan N=20).", "genel"),
    "HO Şeridi (Moving Average Ribbon) ★": ("Moving Average Ribbon", "TV varsayilani: 4 MA, uzunluklar 20/50/100/200, tip SMA, kaynak close.", None),
    "Hull Hareketli Ortalaması": ("Hull Moving Average", None, None),
    "Ichimoku Bulutu": ("Ichimoku Cloud", None, None),
    "İkili Hareketli Ortalama": (None, "Iki MA (TV 'Moving Average Double', varsayilan SMA 9 ve 26?) — belge: MA1 = SMA(src,N1), MA2 = SMA(src,N2); fark/kesisim okunur.", "genel"),
    "McGinley Dinamik": ("McGinley Dynamic", None, None),
    "Çoklu Hareketli Ortalama": (None, "TV 'Moving Average Multiple': 6 SMA; uzunluklar 20/50/100/150/200/250? belgede yok; her biri SMA(close, N_i).", "genel"),
    "Uyarlamalı Hareketli Ortalama (AMA)": ("Kaufmans Adaptive Moving Average (KAMA)", None, None),
    "Üçlü Hareketli Ortalama": (None, "Uc SMA: SMA(src,N1), SMA(src,N2), SMA(src,N3) (TV 'Moving Average Triple'); fiyatin uc ortalamaya gore konumu okunur.", "genel"),
    "Üçlü ÜHO (TEMA)": ("Triple EMA", None, None),
    "Üstel Hareketli Ortalama (EMA)": ("Exponential Moving Average", None, None),
    "Williams Gator (Alligator)": ("Williams Alligator", None, None),
    "Yuvarlatılmış Hareketli Ortalama": ("Smoothed Moving Average", None, None),
    # ---------------- Momentum
    "Chande Momentum Osilatörü": ("Chande Momentum Oscillator (CMO)", None, None),
    "Connors RSI": ("Connors RSI (CRSI)", None, None),
    "Coppock Eğrisi": ("Coppock Curve", None, None),
    "Değişim Oranı (ROC)": ("Rate of Change (ROC)", None, None),
    "Emtia Kanal Endeksi (CCI)": ("Commodity Channel Index (CCI)", None, None),
    "Fisher Dönüşümü": ("Fisher Transform", "Pine: v = 0.66*((hl2 - LL9)/(HH9 - LL9) - 0.5) + 0.67*v[1], |v| <= 0.999; fish = 0.5*ln((1+v)/(1-v)) + 0.5*fish[1]; tetik = fish[1].", None),
    "Fiyat Momentum Osilatörü (PMO) ★": ("Price Momentum Oscillator (PMO)", None, None),
    "Fiyat Osilatörü": ("Percentage Price Oscillator (PPO)", None, None),
    "Göreceli Güç Endeksi (RSI)": ("Relative Strength Index (RSI)", None, None),
    "Hızlanma Osilatörü (AC) ★": (None, "AO = SMA(hl2,5) - SMA(hl2,34); AC = AO - SMA(AO,5) (Bill Williams).", "genel"),
    "Know Sure Thing (KST)": ("Know Sure Thing (KST)", None, None),
    "Kütle Endeksi": ("Mass Index", None, None),
    "MACD": ("MACD", "TV varsayilani: EMA(close,12) - EMA(close,26); sinyal EMA(MACD,9); histogram = MACD - sinyal.", None),
    "Momentum": ("Momentum", None, None),
    "Müthiş Osilatör (Awesome)": ("Awesome Oscillator (AO)", None, None),
    "Nihai Osilatör (UO)": ("Ultimate Oscillator (UO)", None, None),
    "Pring Special K ★": ("Prings Special K", None, None),
    "SMI Ergodik Gösterge/Osilatörü": ("SMI Ergodic Indicator", "Osilator = SMI - sinyal (histogram). TV varsayilani: hizli 5, yavas 20, sinyal 5.", None),
    "Stokastik": ("Stochastic (STOCH)", None, None),
    "Stokastik Momentum Endeksi (SMI) ★": ("Stochastic Momentum Index (SMI)", None, None),
    "Stokastik RSI": ("Stochastic RSI (STOCH RSI)", None, None),
    "Trend Azaltma Fiyat Osilatörü (DPO)": ("Detrended Price Oscillator (DPO)", None, None),
    "TRIX": ("TRIX", None, None),
    "True Strength Index": ("True Strength Index", None, None),
    "Williams %R": ("Williams %R", None, None),
    "Woodies CCI ★": ("Woodies CCI", None, None),
    # ---------------- Trend
    "Aroon": ("Aroon Indicator", None, None),
    "Aroon Osilatörü ★": ("Aroon Oscillator", None, None),
    "Biriktirici Sallanma Endeksi": (None, "Wilder ASI: SI = 50 * (C-C1 + 0.5*(C-O) + 0.25*(C1-O1)) / R * K/T; R, mum iliskisine gore secilen aralik; K = max(|H-C1|,|L-C1|); T = limit hareket; ASI = ASI[1] + SI.", "genel"),
    "Boğa-Ayı Gücü (Bull Bear Power) ★": ("Bull Bear Power", None, None),
    "Dalgalılık Endeksi (Choppiness)": (None, "CHOP = 100 * log10( Sum(ATR(1), n) / (HH(n) - LL(n)) ) / log10(n); n=14; esikler 61.8 (yatay) / 38.2 (trend).", "TV-yardim"),
    "Göreceli Vigor Endeksi": ("Relative Vigor Index", None, None),
    "Güç Dengesi": ("Balance of Power (BOP)", None, None),
    "Kaşe Alanı (Chop Zone)": ("Chop Zone", None, None),
    "Ortalama Yönsel Endeks (ADX)": ("Average Directional Index (ADX)", None, None),
    "Trend Gücü Endeksi": ("Trend Strength Index", None, None),
    "Vortex Göstergesi": ("Vortex Indicator", None, None),
    "Williams Fraktalı": ("Williams fractal indicator", None, None),
    "Yönsel Hareket (DMI)": ("Directional Movement (DMI)", "Pine ta.dmi: yumusatma RMA (Wilder).", None),
    "Zig Zag": ("Zigzag indicator", None, None),
    # ---------------- Hacim
    "Birikim/Dağıtım": ("Accumulation Distribution (ADL)", None, None),
    "Chaikin Para Akışı": ("Chaikin Money Flow (CMF)", None, None),
    "Chaikin Osilatörü": ("Chaikin Oscillator", None, None),
    "Denge İşlem Hacmi (OBV)": ("On Balance Volume (OBV)", None, None),
    "Elder Güç Endeksi": ("Elders Force Index (EFI)", None, None),
    "Fiyat Hacmi Trendi": ("Price Volume Trend (PVT)", None, None),
    "Hacim Deltası (Volume Delta) ★": ("Volume Delta", None, None),
    "Hareket Kolaylığı": ("Ease of Movement (EOM)", None, None),
    "İşlem Hacmi": ("Volume", None, None),
    "İşlem Hacmi Osilatörü": ("Percentage Volume Oscillator (PVO)", "TV 'Volume Oscillator': (EMA(vol,5) - EMA(vol,10)) / EMA(vol,10) * 100.", None),
    "Klinger Osilatörü": ("Klinger Oscillator", None, None),
    "Kümülatif Hacim Endeksi (CVI) ★": ("Cumulative Volume Index (CVI)", None, None),
    "Negatif Hacim Endeksi (NVI) ★": ("Negative Volume Index (NVI)", None, None),
    "Net İşlem Hacmi": ("Net Volume", None, None),
    "Para Akışı Endeksi (MFI)": ("Money Flow (MFI)", None, None),
    "Pozitif Hacim Endeksi (PVI) ★": ("Positive Volume Index (PVI)", None, None),
    "Zamana Göre Göreli Hacim (RVOL) ★": ("Relative Volume at Time", None, None),
    # ---------------- Volatilite
    "Bollinger Bantları": ("Bollinger Bands (BB)", None, None),
    "Bollinger Bantları %B": ("Bollinger Bands %b", None, None),
    "Bollinger Bantları Genişliği": ("Bollinger BandWidth (BBW)", None, None),
    "Bollinger Trend (BBTrend) ★": ("BBTrend", None, None),
    "Chaikin Volatilitesi": (None, "CV = (EMA(H-L, 10) - EMA(H-L, 10)[10]) / EMA(H-L, 10)[10] * 100 (TV: uzunluk 10, ROC 10).", "genel"),
    "Donchian Kanalları": ("Donchian Channels (DC)", None, None),
    "Fiyat Kanalı": (None, "Ust = HH(high, N), Alt = LL(low, N) (TV 'Price Channel', N=20); Donchian ile ayni mantik, orta cizgi yok.", "genel"),
    "Göreceli Volatilite Endeksi": ("Relative Volatility Index", None, None),
    "Keltner Kanalları": ("Keltner Channels (KC)", "TV varsayilani: uzunluk 20, carpan 2, ATR uzunlugu 10, EMA.", None),
    "Medyan Kanalı (Median) ★": ("Median", None, None),
    "Ortalama Gerçek Aralık (ATR)": ("Average True Range (ATR)", None, None),
    "Ortalama Günlük Aralık (ADR) ★": ("Average Daily Range (ADR)", None, None),
    "Standart Hata": (None, "SE = sqrt( Sum((y - regresyon)^2, N) / (N-2) ); y = kaynak, regresyon = N barlik en kucuk kareler dogrusu (TV uzunluk 14).", "genel"),
    "Standart Hata Bandı": (None, "Orta = linreg(src, N); Ust/Alt = Orta +- k * SE; SE standart hata (TV: uzunluk 21, k=2, yumusatma SMA 3).", "genel"),
    "Standart Sapma": (None, "StdDev = sqrt( Sum((src - SMA(src,N))^2, N) / N ) (populasyon; TV uzunluk 5).", "genel"),
    "Tarihi Volatilite": ("Historical Volatility", None, None),
    "Volatilite Endeksi": (None, "TV 'Volatility Index': stdev(close, N) / SMA(close, N) * 100 benzeri oran (TV sayfasi yok; genel).", "genel"),
    "Volatilite Kapanıştan-Kapanışa": (None, "HV_cc = sqrt( 252 * Sum( ln(C/C1)^2, N ) / N ) (TV 'Volatility Close-to-Close', N=10, yillik 252).", "genel"),
    "Volatilite O-H-L-C": (None, "Garman-Klass / Yang-Zhang tipi: sigma^2 = 0.5*ln(H/L)^2 - (2ln2-1)*ln(C/O)^2, N bar ortalamasi, yillik sqrt(252) (TV 'Volatility O-H-L-C', N=10).", "genel"),
    "Volatilite Sıfır Trendi K.-K.": (None, "Sifir-trend K-K: sqrt( 252/N * Sum(ln(C/C1)^2) ) (ortalama cikarilmadan; TV 'Volatility Zero Trend Close-to-Close', N=10).", "genel"),
    "Zarflar (Envelope)": ("Envelope (ENV)", None, None),
    # ---------------- Referans
    "52 Haftalık Yüksek/Düşük ★": (None, "Ust = HH(high, 52 hafta), Alt = LL(low, 52 hafta); gunluk/haftalik barlarda 1 yillik pencere (TV '52 Week High/Low').", "genel"),
    "Görünür Ortalama Fiyat ★": ("Visible Average Price", None, None),
    "Hacim Ağırlıklı H.O. (HAHO/VWMA)": ("VWMA", None, None),
    "Hacim Ağırlıklı Ortalama Fiyat (HAOF/VWAP)": ("VWAP", None, None),
    "Medyan Fiyat": (None, "Medyan Fiyat = (H + L) / 2 (hl2).", "genel"),
    "Ortalama Fiyat": (None, "Ortalama Fiyat = (O + H + L + C) / 4 (ohlc4).", "genel"),
    "Pivot Noktalar Standardı": ("Pivot Points Standard", None, None),
    "Pivot Seviyeleri Yüksek/Düşük ★": ("Pivot Points High Low", None, None),
    "Tipik Fiyat": (None, "Tipik Fiyat = (H + L + C) / 3 (hlc3).", "genel"),
    "Zaman Ağırlıklı Ortalama Fiyat (TWAP) ★": ("Time Weighted Average Price", None, None),
    # ---------------- Istatistik
    "Doğrusal Regresyon Eğrisi": ("Linear Regression", "Pine ta.linreg(src, N, 0): y = a + b*x, b = (N*Sum(xy) - Sum(x)Sum(y)) / (N*Sum(x^2) - Sum(x)^2); egri = her barin kendi N-bar regresyonunun son degeri.", None),
    "Doğrusal Regresyon Eğimi (Slope)": (None, "Slope b = (N*Sum(x*y) - Sum(x)*Sum(y)) / (N*Sum(x^2) - Sum(x)^2), x = bar indeksi, y = kaynak, N barlik pencere (TV uzunluk 14).", "genel"),
    "Doğrusal Regresyon Kanalı ★": ("Linear Regression", None, None),
    "Fark (Spread)": (None, "Spread = Sembol1 - Sembol2 (veya iki serinin farki); TV 'Spread' yerlesigi.", "genel"),
    "Korelasyon - Log": (None, "r = corr( ln(close1), ln(close2), N ) Pearson korelasyonu (TV 'Correlation - Log', N=20).", "genel"),
    "Korelasyon Katsayısı": ("Correlation Coefficient (CC)", None, None),
    "Ratio": (None, "Ratio = Sembol1 / Sembol2 (TV 'Ratio').", "genel"),
    "RCI Şeridi (RCI Ribbon) ★": ("RCI Ribbon", None, None),
    "Sıra Korelasyon Endeksi (RCI) ★": ("Rank Correlation Index (RCI)", "RCI = (1 - 6*Sum(d^2) / (N*(N^2-1))) * 100; d = zaman sirasi - fiyat sirasi farki (Spearman).", None),
    # ---------------- Hacim profili
    "Birim Profili Sabit Aralığı (VbP Fixed Range)": (None, "Secilen bar araligi fiyat eksenine 'Row size' satira bolunur; her satira dusen (alt zaman dilimi) hacim toplanir; POC = en yuksek hacimli satir; Value Area = toplam hacmin %70'ini kapsayan satirlar (TV: Row Size 24, VA %70).", "genel"),
    "Hacim Profili Görünür Aralık (VPVR)": (None, "Ekranda gorunen barlar icin ayni hesap: fiyat satirlari x hacim; POC, VAH/VAL (%70) (TV 'Visible Range Volume Profile', Row Size 24).", "genel"),
    "Otomatik Sabitlenmiş Hacim Profili (AAVP) ★": (None, "Anchor otomatik secilir (pivot/swing/oturum); anchor'dan itibaren fiyat satiri x hacim, POC ve %70 deger alani (TV 'Auto Anchored Volume Profile').", "genel"),
    "Periyodik Hacim Profili (PVP) ★": (None, "Her periyot (gun/hafta/ay) icin ayri profil: satir hacimleri, POC, VAH/VAL (%70) (TV 'Periodic Volume Profile').", "genel"),
    # ---------------- Sinyal / stop
    "Avize Çıkışı (Chandelier Exit) ★": (None, "Long Exit = HH(22) - ATR(22)*3; Short Exit = LL(22) + ATR(22)*3 (TV yardim; TV kodu stoplari trend surerken geri cekmez: long stop = max(ls, ls[1]) eger C1 > ls[1]).", "TV-yardim"),
    "Chande Kroll Durdurması": ("Chande Kroll Stop", None, None),
    "Çoğunluk Kuralı": (None, "Majority Rule: son N barda yukari kapanis (C > C1) sayisi yuzdesi; %50 ustu alici cogunlugu (TV 'Majority Rule', N=20).", "genel"),
    "HO Cross": ("MA Cross", None, None),
    "HO ve ÜHO Kesişmesi": (None, "TV 'MovingAvg2Line Cross': SMA(close, 9) ile EMA(close, 21?) kesisimi; sayfa varsayilani: iki cizgi, kisa 9 / uzun 21 (yardim sayfasinda formul yok).", "TV-yardim*"),
    "Parabolik SAR": ("Parabolic SAR (SAR)", None, None),
    "RSI Uyumsuzluğu ★": ("RSI divergence indicator", None, None),
    "SuperTrend": (None, "hl2 +- carpan*ATR(n): ust/alt temel bant; ust = ust < ust[1] veya C1 > ust[1] ? ust : ust[1]; alt = alt > alt[1] veya C1 < alt[1] ? alt : alt[1]; yon: C > ust ise yukari, C < alt ise asagi; Supertrend = yukari ise alt, asagi ise ust (TV yardim; varsayilan ATR 10, carpan 3).", "TV-yardim"),
    "Teknik Derecelendirme ★": ("Technical Ratings", None, None),
    "ÜHO Kesişme (EMA Cross)": (None, "EMA(close, N1) ile EMA(close, N2) kesisimi (TV 'EMA Cross', 9/26?); kesisim noktalari isaretlenir.", "genel"),
    "Ülser Endeksi ★": ("Ulcer Index", None, None),
    "Volatilite Stopu (Volatility Stop) ★": ("Volatility Stop", None, None),
    # ---------------- Genislik
    "İşlem Seansları (Trading Sessions) ★": ("Trading Sessions", None, None),
    "Mevsimsellik (Seasonality) ★": (None, "Her yil icin ay/hafta/gun getirileri tablolanir; ortalama/medyan getiri ve pozitif yil yuzdesi (TV 'Seasonality'; hesap sayfada yok).", "TV-yardim*"),
    "Performans (Performance) ★": (None, "Secili donemlerde (1H, 1G, 1A, 3A, 6A, YTD, 1Y...) yuzde getiri: (C_simdi / C_donem_basi - 1) * 100 (TV 'Performance').", "TV-yardim*"),
    "Sembol Karşılaştırma (Compare) ★": (None, "Ikinci sembol ayni grafige eklenir; yuzde modunda her iki seri ortak baslangic noktasina gore % normalize edilir.", "genel"),
    "Yükselen/Düşen Oranı (A/D Ratio) ★": ("Advance/Decline Ratio", None, None),
    "Yükseliş/Düşüş": ("Advance/Decline Line", None, None),
    # ---------------- Otomatik cizim
    "Otomatik Ana Seviyeler (Auto Key Levels) ★": ("Auto key levels", None, None),
    "Otomatik Çatal (Auto Pitchfork) ★": ("Auto Pitchfork", None, None),
    "Otomatik Fibonacci Düzeltmesi ★": ("Auto Fib Retracement", None, None),
    "Otomatik Fibonacci Uzantısı ★": (None, "Zigzag pivotlarindan son uc nokta (A-B-C) alinir; uzanti seviyeleri = C + k*(B-A), k = 0.618, 1, 1.618, 2.618... (TV 'Auto Fib Extension'; sayfada hesap yok).", "TV-yardim*"),
    "Otomatik Trend Çizgileri ★": ("Auto trendlines", None, None),
    # ================= SMC / ICT (topluluk scriptleri; TV kaynak kodu bu oturumda okunmadi)
    "Balanced Price Range (BPR) ★": (None, "Zit yonlu iki FVG'nin ortusen bolgesi: BPR = [max(alt FVG tabanlari), min(ust FVG tavanlari)]; ortusme yoksa BPR yok.", "genel"),
    "Breaker Block ★": (None, "Yapi kirilimi (BOS) sonrasi gecersiz kalan Order Block: eski OB bolgesi, fiyat icinden gecip kapandiktan sonra ters yonde destek/direnc olarak isaretlenir.", "genel"),
    "CISD (Teslim Durumu Değişimi) ★": (None, "Change in State of Delivery: son ardisik ayni renkli mum serisinin acilisi; fiyat bu acilisin ustunde/altinda kapanirsa teslim durumu degisti sayilir.", "genel"),
    "CRT / Turtle Soup ★": (None, "Ust zaman dilimi mumunun high/low'u gecilip (sweep) geri icine kapanis: Turtle Soup = 20 bar dusugu/yuksegi kirilip ayni bar/sonraki bar icinde geri donus; giris geri donus mumu.", "genel"),
    "Dealing Range + IRL/ERL ★": (None, "Dealing range = son swing high - swing low; ERL (dis likidite) = araligin uclari; IRL (ic likidite) = aralik icindeki FVG/OB; premium = ust %50, discount = alt %50.", "genel"),
    "Displacement (Yer Değiştirme - ICT)": (None, "Govde buyuklugu > k * ATR(14) (yaygin k=1.5-2) ve ardinda FVG birakan mum; displacement = |C - O| / ATR >= esik.", "genel"),
    "Equal Highs / Equal Lows": (None, "Iki pivot high (veya low) farki <= tolerans (tipik 0.1*ATR veya tick carpani) ise EQH/EQL; likidite havuzu olarak cizilir.", "genel"),
    "Fair Value Gap (FVG)": (None, "Uc mum: yukari FVG = low[0] > high[2] (bolge: high[2]..low[0]); asagi FVG = high[0] < low[2]; fiyat bolgeyi doldurunca (mitigation) silinir.", "genel"),
    "Hacimli Yapı Kırılımı (BOS + Hacim)": (None, "BOS: kapanis son swing high ustunde / swing low altinda; filtre: kirilim mumu hacmi > SMA(hacim, 20) * k (k ~1.5).", "genel"),
    "Inversion FVG (Ters FVG) ★": (None, "Dolan (mitigated) FVG'nin ters yonde destek/direnc olarak kullanimi: yukari FVG asagi kapanisla gecilirse artik direnc (iFVG).", "genel"),
    "Inversion Order Block (iOB) ★": (None, "Fiyat icinden gecen (basarisiz) Order Block'un ters rol almasi; OB bolgesinin ters yonde yeniden test edilmesi.", "genel"),
    "IPDA Veri Aralıkları ★": (None, "Son 20 / 40 / 60 islem gununun high-low araliklari (ICT IPDA look-back); bu araliklarin uclari ve FVG/OB'leri referans seviye.", "genel"),
    "Liquidation Level (Likidite Seviyesi)": (None, "Kaldirac seviyeleri icin tasfiye fiyati: long = giris * (1 - 1/kaldirac + bakim marji); short = giris * (1 + 1/kaldirac - bakim marji); hacim agirlikli kumeler isi haritasi.", "genel"),
    "Liquidity Void ★": (None, "Tek yonlu hizli hareketle olusan, az islem gormus fiyat bolgesi: ardisik mumlarin govdeleri ortusmez ve hacim profili bos; FVG'nin buyuk olcekli hali.", "genel"),
    "Market Maker Modeli (MMXM) ★": (None, "Buy/Sell model: birikim (konsolidasyon) -> manipulasyon (likidite alimi) -> dagitim; yapi: orijinal konsolidasyon, smart money reversal, dusuk/yuksek riskli alim/satim bolgeleri.", "genel"),
    "Market Structure (BOS/CHoCH)": (None, "Swing high/low (pivot N sol/sag); BOS = trend yonunde son swing kirilimi; CHoCH = trende ters ilk swing kirilimi (kapanis esasli veya fitil esasli).", "genel"),
    "Mitigation Block": (None, "Swing'i alamayan (daha dusuk tepe / daha yuksek dip yapan) ve ardindan yapi kiran mumun govdesi; fiyat geri donerken bolge destek/direnc.", "genel"),
    "Order Block (Sipariş Bloğu)": (None, "Yukari OB: guclu yukari hareketten (BOS/displacement) onceki son asagi mum (O-C veya H-L bolgesi); asagi OB simetrik; mitigation'da gecersiz.", "genel"),
    "OTE (Optimal Giriş Bölgesi) ★": (None, "Son itki bacaginin Fibonacci 0.62-0.79 geri cekilme bolgesi (0.705 'sweet spot').", "genel"),
    "Premium / Discount Array ★": (None, "Dealing range'in %50 (equilibrium) ustu premium (satis araylari: OB, FVG, breaker), alti discount (alim araylari).", "genel"),
    "Propulsion Block ★": (None, "Order Block'un icine geri cekilip yeniden ileri atan mum; bu mumun govdesi ikinci giris bolgesi.", "genel"),
    "Rejection Block ★": (None, "Swing high/low'daki uzun fitil (fitil > govde * k); govde ustu/alti ile fitil ucu arasi bolge.", "genel"),
    "Vacuum Block ★": (None, "Acilis bosluklari (gap) ve ardisik mum araliklarindaki islem gormemis bolge; doldurulana kadar ceken bolge.", "genel"),
    "Volume Imbalance (VI) ★": (None, "Iki ardisik mumun govdeleri arasinda bosluk (C1 ile O arasi), fitiller ortusse bile; bolge: min(C1,O)..max(C1,O).", "genel"),
    "Wick Rejection / Z-Score": (None, "Fitil orani = ust/alt fitil / toplam aralik; Z = (close - SMA(close,N)) / stdev(close,N); |Z| > 2 ve fitil > %60 reddetme.", "genel"),
    "Hafta/Gün Açılış Boşluğu (NWOG/NDOG) ★": (None, "NDOG = gun kapanisi (16:59 NY) ile sonraki acilis (18:00 NY) arasi; NWOG = Cuma kapanisi ile Pazar acilisi arasi; bosluk ve orta noktasi (CE) cizilir.", "genel"),
    "ICT Makro Zamanları ★": (None, "Saat araliklari (NY): 09:50-10:10, 10:50-11:10, 11:50-12:10, 13:10-13:40, 15:15-15:45; bu pencerelerde likidite avi beklenir.", "genel"),
    "İlk Denge Kırılımı (Initial Balance) ★": (None, "IB = seans ilk 60 dk (tipik 09:30-10:30 NY) high-low; IB high/low kirilimi ve IB x 1, 1.5, 2 uzantilari.", "genel"),
    "Judas Salınımı (Judas Swing) ★": (None, "Seans acilisindan sonra gunluk acilisin ters tarafina sahte hareket (likidite alimi) ardindan gercek yon; acilis fiyati referans.", "genel"),
    "Killzones (Zaman Dilimleri) ★": (None, "Asya 20:00-00:00, Londra 02:00-05:00, NY AM 07:00-10:00, NY PM 13:30-16:00 (NY saati); her kutu high/low'u cizilir.", "genel"),
    "Likidite Isı Haritası ★": (None, "Pivot high/low seviyeleri etrafinda tahmini stop/tasfiye yogunlugu (hacim ve kaldirac agirlikli); yogunluk renk skalasi.", "genel"),
    "Liquidity Sweeps (Likidite Süpürmeleri) ★": (None, "Fitil swing high/low'u gecer ama kapanis gecmez: high > pivotHigh ve close < pivotHigh (sweep); mum sonrasi ters yon beklenir.", "genel"),
    "Opening Range Gap (ORG) ★": (None, "Onceki seans kapanisi ile yeni seans acilisi arasindaki bosluk; bosluk %25/%50/%75 seviyeleri (CE) cizilir.", "genel"),
    "Opening Range Kırılımları (ORB) ★": (None, "Acilistan sonraki ilk N dk (5/15/30) high-low; kirilim: close > OR high (long) / close < OR low (short); hedef OR yuksekligi carpani.", "genel"),
    "Önceki Gün/Hafta Yüksek-Düşük Seviyeleri ★": (None, "PDH/PDL = onceki gun high/low; PWH/PWL = onceki hafta; ayrica onceki kapanis; ust zaman dilimi security() ile alinir.", "genel"),
    "Power of Three (AMD) ★": (None, "Accumulation-Manipulation-Distribution: mum acilisi (A), acilisin ters tarafina fitil (M), gercek yonde govde (D); gunluk/haftalik mum uzerinde okunur.", "genel"),
    "Silver Bullet (Gümüş Kurşun) ★": (None, "NY 10:00-11:00 (ayrica 03:00-04:00, 14:00-15:00) penceresinde olusan FVG'ye giris; hedef yakin likidite.", "genel"),
    "SMT Uyumsuzluğu ★": (None, "Iliskili iki sembolde (orn. ES/NQ, EURUSD/DXY) biri yeni high/low yaparken digeri yapmazsa SMT; pivotlar karsilastirilir.", "genel"),
    "Anchored VWAP (Zamanlanmış HAOF)": (None, "AVWAP = Sum(hlc3*hacim, anchor'dan itibaren) / Sum(hacim); anchor kullanici secimli bar/tarih; bantlar +-k*stdev.", "genel"),
    "ATR Trailing Stop (Geri İzlemeli Durak)": (None, "Long stop = max(stop[1], close - k*ATR(n)); short stop = min(stop[1], close + k*ATR(n)); yon kapanis stop'u gecince degisir (k tipik 3, n 10-14).", "genel"),
    "CVD (Kümülatif Hacim Delta)": ("Cumulative Volume Delta", None, None),
    "Donchian + Inside Bar Filter": (None, "Donchian(20) ust/alt; inside bar = high < high[1] ve low > low[1]; sinyal: inside bar sonrasi kanal kirilimi.", "genel"),
    "Footprint Chart (Ayak İzi Grafiği)": (None, "Her fiyat seviyesinde bid x ask hacmi (alt zaman dilimi tick/1s verisi); delta = ask hacmi - bid hacmi; imbalance = oran >= 3:1.", "genel"),
    "Lorentzian Sınıflandırma (Makine Öğrenmesi) ★": (None, "jdehorty: ozellikler RSI(14), WT(10,11), CCI(20), ADX(20), RSI(9); k-NN (k=8) Lorentz mesafesi d = Sum(ln(1+|x_i - y_i|)); gecmis 2000 bar etiketi (4 bar sonra yukari/asagi); cogunluk oyu sinyal.", "genel"),
    "Machine Learning FSM (Makine Öğrenmesi Durum Modeli)": (None, "Sonlu durum makinesi: durumlar (trend yukari/asagi/yatay) gecisleri gosterge esikleriyle (orn. ADX, RSI) tetiklenir; gecis olasiliklari gecmis frekanstan.", "genel"),
    "Orderflow Imbalance (Sipariş Akışı Dengesizliği)": (None, "Seviye bazinda ask hacmi / bid hacmi (diagonal) >= 3; ardisik 3 seviye dengesizlik = yigilmis imbalance.", "genel"),
    "Session Volume Profile (Seans Hacim Profili)": (None, "Her seans icin fiyat satiri x hacim; POC, VAH/VAL (%70), gelisen (developing) POC.", "genel"),
    "Supertrend Clustering (Kümelenme)": (None, "LuxAlgo: carpan araligi (1..5 adim) icin Supertrend performanslari k-means (3 kume: iyi/orta/kotu) ile kumelenir; secilen kumenin ortalama carpaniyla Supertrend cizilir.", "genel"),
    "TD Sequential (Tom DeMark)": (None, "Setup: 9 ardisik kapanis 4 bar oncekinden dusuk (alim)/yuksek (satis); Countdown: 13 kapanis 2 bar onceki low/high'dan dusuk/yuksek; 9 ve 13 tukenis.", "genel"),
    "Çoklu Formasyon Tarayıcı (50+) ★": (None, "Pivot (zigzag) noktalarindan geometrik kurallar: tepe/dip esitligi toleransi, egim oranlari, boyun cizgisi; her formasyon icin kural seti.", "genel"),
    "Elliott Dalga Analizi ★": (None, "Zigzag pivotlarindan 5-3 dalga sayimi; kurallar: dalga 2 dalga 1 baslangicini gecmez, dalga 3 en kisa olamaz, dalga 4 dalga 1 alanina girmez; Fibonacci oranlari.", "genel"),
    "Fincan-Kulp / V Formasyonu ★": (None, "Fincan: U seklinde dip (derinlik %12-33), kulp: sag kenarda kucuk geri cekilme (< fincan derinliginin 1/3); kirilim kulp yuksegi. V: keskin dip, simetrik toparlanma.", "genel"),
    "Harmonik Formasyonlar (XABCD) ★": (None, "Gartley: B = 0.618 XA, D = 0.786 XA; Bat: B 0.382-0.5, D 0.886; Butterfly: B 0.786, D 1.27-1.618; Crab: D 1.618 XA; pivotlardan oran toleransli esleme.", "genel"),
    "İkili / Üçlü Tepe ve Dip ★": (None, "Iki/uc pivot high (low) farki <= tolerans (ATR veya %), aradaki dip (tepe) boyun cizgisi; kirilim boyun cizgisi kapanisi; hedef = formasyon yuksekligi.", "genel"),
    "Kama / Bayrak / Üçgen Kırılımı ★": (None, "Pivot high'lardan ust, pivot low'lardan alt regresyon/trend cizgisi; egim isaretleri ile kama (ayni yon), bayrak (direge ters), ucgen (yakinsayan); kirilim kapanis.", "genel"),
    "Mum Formasyonu Tanıyıcı ★": (None, "Govde/fitil oranlari: doji |C-O| <= %5 aralik; cekic alt fitil >= 2*govde; yutan govde onceki govdeyi kapsar; yildiz govde kucuk ve bosluk; TV 'All Candlestick Patterns' trend filtresi SMA(50).", "genel"),
    "Mum Formasyonu Tarayıcı ★": (None, "Ayni mum kurallari birden fazla sembol/zaman dilimine uygulanir; TV tarayicisinda formasyon = 1/0 kosulu.", "genel"),
    "Omuz-Baş-Omuz / Ters OBO ★": (None, "Uc pivot high: ortadaki en yuksek, omuzlar birbirine yakin (tolerans); boyun cizgisi iki dipten; kirilim kapanis; hedef = bas - boyun mesafesi.", "genel"),
    "Otomatik Grafik Formasyonları ★": (None, "TV yerlesik formasyon tanimlayicilari (ucgen, kama, bayrak, OBO, ikili tepe...): zigzag pivot + geometrik kural; yardim sayfasinda formul yok.", "TV-yardim*"),
    "Özel Pivot Formasyon Motoru (BYO) ★": (None, "Kullanici tanimli pivot sayisi ve oran kurallariyla (orn. P2/P1 = 0.618 +- tol) formasyon esleme motoru.", "genel"),
    "Three Drives / 5-0 ★": (None, "Three Drives: uc ardisik tepe/dip, her biri bir onceki itkinin 1.27-1.618 uzantisi, geri cekilmeler 0.618-0.786; 5-0: AB=CD, D = BC'nin %50'si.", "genel"),
    "VSA (Hacim Yayılım Analizi) ★": (None, "Spread = H - L; hacim SMA(20)'ye gore yuksek/dusuk; kapanis konumu (C-L)/(H-L); kurallar: dar spread + yuksek hacim = arz/talep emilimi, upthrust, no demand.", "genel"),
    "Wyckoff Faz Etiketleme ★": (None, "Birikim/dagitim semasi: PS, SC, AR, ST, Spring/UTAD, SOS/SOW, LPS/LPSY; pivot + hacim kurallariyla etiketleme; faz A-E.", "genel"),
    "Wyckoff Yay ve Sahte Kırılım (UTAD) ★": (None, "Spring: aralik dusugu altina fitil + geri icine kapanis (hacim dusuk/orta); UTAD: aralik yuksegi ustune fitil + geri kapanis (hacim yuksek).", "genel"),
    # ================= Topluluk
    "Aralık Filtresi (Range Filter) ★": (None, "DonovanWall: smrng = EMA(EMA(|src - src[1]|, N), 2N-1) * carpan; filt = src > filt[1] ? max(filt[1], src - smrng) : min(filt[1], src + smrng); yon = filt egimi (N=100, carpan 3).", "genel"),
    "Coral Trend ★": (None, "LazyBear: 6 kademeli ustel yumusatma (T3 benzeri) alpha = 2/(N+1), katsayilar c1..c4 (cd=0.4 varsayilan) ile bfr = -cd^3*i6 + c2*i5 + c3*i4 + c4*i3; renk egim (N=21).", "genel"),
    "Gaussian Kanalı ★": (None, "DonovanWall: N kutuplu Gauss filtresi (beta = (1-cos(2pi/periyot))/(2^(1/N)-1), alpha = -beta + sqrt(beta^2+2beta)); filt = alpha^N*src + ... ; bant = filtre(TR)*carpan (periyot 144, kutup 4, carpan 1.414).", "genel"),
    "Heikin-Ashi RSI Osilatörü ★": (None, "JayRogers: RSI(close, N) uzerinden Heikin-Ashi acilis/kapanis: haC = (O+H+L+C)/4 RSI'in; haO = (haO[1]+haC[1])/2; yumusatma EMA; 20/80 bolgeleri.", "genel"),
    "Jurik Hareketli Ortalama (JMA) ★": (None, "Everget/Jurik: faz ve guc parametreli adaptif filtre: beta = 0.45(N-1)/(0.45(N-1)+2), alpha = beta^power; e0 = (1-alpha)*src + alpha*e0[1]; e1 = (src - e0)(1-beta) + beta*e1[1]; e2 = (e0 + phaseRatio*e1 - jma[1])(1-alpha)^2 + alpha^2*e2[1]; jma = e2 + jma[1] (N=7, phase 50, power 2).", "genel"),
    "Nadaraya-Watson Zarfı ★": (None, "LuxAlgo: y_hat = Sum(K(i)*src_i)/Sum(K(i)), K Gauss cekirdegi exp(-i^2/(2h^2)) (h=8, pencere 500 bar); zarf = y_hat +- carpan*MAE (3); yeniden boyama (repaint) uyarisi.", "genel"),
    "QQE MOD ★": (None, "Mihkel00: RSI(14) EMA(5) yumusatma; ATR_RSI = |RSIma - RSIma[1]|, DAR = EMA(EMA(ATR_RSI,27),27)*4.238; izleyen bant (longband/shortband) RSIma'ya gore; ikinci QQE (RSI 6, faktor 1.61) + Bollinger(50, 0.35) histogram renklendirme.", "genel"),
    "Squeeze Momentum ★": (None, "LazyBear: BB(20, 2.0) Keltner(20, 1.5*ATR) icindeyse squeeze ON; momentum = linreg(close - avg(avg(HH20, LL20), SMA20), 20, 0); histogram rengi momentum ve degisimi.", "genel"),
    "SSL Hybrid ★": (None, "Mihkel00: SSL = SMA(high, N) ve SMA(low, N) (varsayilan HMA 60 baseline); Hlv = close > smaHigh ? 1 : close < smaLow ? -1 : Hlv[1]; sslDown/Up secimi; Keltner bantlari baseline etrafinda (0.2 ATR).", "genel"),
    "TDI (Traders Dynamic Index) ★": (None, "RSI(13) -> fiyat cizgisi SMA(RSI,2), sinyal SMA(RSI,7), taban SMA(RSI,34); Bollinger(RSI, 34, 1.6185) volatilite bantlari; seviyeler 32/50/68.", "genel"),
    "Tillson T3 Hareketli Ortalama ★": (None, "T3 = c1*e6 + c2*e5 + c3*e4 + c4*e3; e1..e6 ardisik EMA(N); c1 = -a^3, c2 = 3a^2 + 3a^3, c3 = -6a^2 - 3a - 3a^3, c4 = 1 + 3a + a^3 + 3a^2 (N=5, a=0.7).", "genel"),
    "UT Bot Alarmları ★": (None, "QuantNomad: nLoss = a*ATR(c); trailing stop: src > stop[1] ve src[1] > stop[1] ? max(stop[1], src - nLoss) : src < stop[1] ve src[1] < stop[1] ? min(stop[1], src + nLoss) : src > stop[1] ? src - nLoss : src + nLoss; sinyal EMA(src,1) stop kesisimi (a=1, c=10).", "genel"),
    "VuManChu Cipher B ★": (None, "WaveTrend (10/21 + 3/4 sinyal), ayrica MFI-RSI alani = SMA((close-open)/(high-low)*5, 60)*... , RSI(14) ve Stoch RSI(14); 'yesil nokta' = WT kesisimi asiri satim altinda; diverjans tespiti.", "genel"),
    "Waddah Attar Patlaması ★": (None, "t1 = (MACD(20,40) - MACD[1]) * 150 (hassasiyet); e1 = BB ust(20,2) - BB alt; trend yukari t1>0 histogram, deadzone = RMA(TR,100)*3.7; sinyal: |t1| > e1 ve > deadzone.", "genel"),
    "WaveTrend Osilatörü (WT) ★": (None, "LazyBear (TV kaynak kodu, 2026-10-27 okundu): ap = hlc3; esa = EMA(ap,10); d = EMA(|ap-esa|,10); ci = (ap-esa)/(0.015*d); wt1 = EMA(ci,21); wt2 = SMA(wt1,4); bantlar +60/+53, -60/-53.", "TV-kod"),
    "Arz-Talep Bölgeleri (Visible Range) ★": (None, "Gorunur aralik hacim profilinde dusuk hacimli (LVN) ve yuksek hacimli (HVN) bolgeler; LVN bolgesine komsu HVN arz/talep bolgesi; swing pivot + kapanis esikli alternatifler.", "genel"),
    "Çoklu Gösterge Uyumsuzluk Dedektörü ★": (None, "Fiyat pivotlari (sol/sag 5) ile RSI/MACD/Stoch/CCI/MFI/OBV pivotlari karsilastirilir: fiyat HH & gosterge LH = negatif, fiyat LL & gosterge HL = pozitif (LonesomeTheBlue).", "genel"),
    "Destek/Direnç Seviyeleri ve Kırılımlar ★": (None, "LuxAlgo: pivot high/low (sol/sag N=15) seviyeleri; kirilim = kapanis seviyeyi gecer ve hacim osilatoru (EMA5-EMA10)/EMA10 > %20 (filtreli).", "genel"),
    "Kırılımlı Trend Çizgileri ★": (None, "LuxAlgo: pivot high/low (N=14) noktalarindan egim = ATR / SMA / stdev tabanli (carpan 1) trend cizgisi; kirilim = kapanis cizgiyi gecer.", "genel"),
    "Para Birimi Gücü (Currency Strength) ★": (None, "Her para birimi icin ilgili paritelerin % degisimlerinin (RSI veya ROC) ortalamasi; 8 majorun goreli siralamasi; TV 'Currency Strength' topluluk scriptleri.", "genel"),
    "Piyasa Profili (TPO) ★": (None, "Her 30 dk (TPO) icin fiyat satirlarina harf; satir TPO sayisi; POC = en cok TPO; Value Area = %70 TPO; IB = ilk 2 TPO.", "genel"),
    # ================= Gelismis / nadir
    "Ağırlık Merkezi Osilatörü ★": (None, "Ehlers COG: COG = -Sum((i+1)*src[i], N) / Sum(src[i], N) (i=0..N-1); Pine ta.cog(src, 10).", "genel"),
    "Dikey-Yatay Filtre (VHF) ★": (None, "VHF = (HH(close,N) - LL(close,N)) / Sum(|C - C1|, N) (N=28); yuksek = trend, dusuk = yatay.", "genel"),
    "Ehlers Anlık Trend Çizgisi ★": (None, "Pine (everget): a=0.07; it = (a - a^2/4)*src + 0.5a^2*src[1] - (a - 0.75a^2)*src[2] + 2(1-a)*it[1] - (1-a)^2*it[2]; ilk 7 bar (src + 2src[1] + src[2])/4; tetik = 2*it - it[2] (TV kaynak kodu onceki oturumda okundu).", "TV-kod"),
    "Elder İtki Sistemi ★": (None, "EMA(13) egimi ve MACD(12,26,9) histogram egimi: ikisi yukari = yesil (al), ikisi asagi = kirmizi (sat), ayrisik = mavi (noter).", "genel"),
    "Göreli Momentum Endeksi (RMI) ★": (None, "RMI = 100 - 100/(1+RS); RS = RMA(max(C - C[m],0), N) / RMA(max(C[m] - C,0), N); m = momentum uzunlugu (RSI'de m=1) (N=14, m=5).", "genel"),
    "Kase Gelişmiş Stop ★": (None, "Kase DevStop: aralik = H - L[1] (2 bar); Dev = stdev(aralik, N); stop seviyeleri = HH/LL +- (ort(aralik) + k*Dev), k = 0, 1, 2.2, 3.6.", "genel"),
    "Kaufman Verimlilik Oranı ★": (None, "ER = |C - C[N]| / Sum(|C - C1|, N) (0..1; N=10); KAMA'nin cekirdegi.", "genel"),
    "Laguerre RSI ★": (None, "Ehlers: gamma=0.5 (veya 0.7); L0 = (1-g)*src + g*L0[1]; L1 = -g*L0 + L0[1] + g*L1[1]; L2 = -g*L1 + L1[1] + g*L2[1]; L3 = -g*L2 + L2[1] + g*L3[1]; CU/CD = L farklari pozitif/negatif toplami; LRSI = CU/(CU+CD).", "genel"),
    "MESA Uyarlamalı Ortalama (MAMA/FAMA) ★": (None, "Ehlers: Hilbert donusumu ile baskin dongu periyodu ve faz; alpha = fastLimit(0.5)*|deltaPhase| sinirli (min slowLimit 0.05); MAMA = alpha*src + (1-alpha)*MAMA[1]; FAMA = 0.5*alpha*MAMA + (1-0.5alpha)*FAMA[1].", "genel"),
    "Oldukça İyi Osilatör (PGO) ★": (None, "PGO = (close - SMA(close, N)) / EMA(TR, N) (N=89; LuxAlgo/Johnson); +3/-3 kirilim, sifir cikis (onceki oturumda kullanildi).", "genel"),
    "Psikolojik Hat ★": (None, "PSY = (son N barda yukari kapanis sayisi / N) * 100 (N=12); 75 ustu asiri iyimser, 25 alti kotumser.", "genel"),
    "QStick ★": (None, "QStick = SMA(close - open, N) (veya EMA) (N=8); sifir ustu alici baskisi.", "genel"),
    "R-Kare (R-squared) ★": (None, "R^2 = corr(close, bar_index, N)^2; dogrusal regresyonun aciklama gucu (N=20); 0.8 ustu guclu trend.", "genel"),
    "Rastgele Yürüyüş Endeksi ★": (None, "RWI_high = (H - L[N]) / (ATR(N) * sqrt(N)); RWI_low = (H[N] - L) / (ATR(N) * sqrt(N)); 1 ustu trend (N=14).", "genel"),
    "Schaff Trend Döngüsü ★": (None, "STC: MACD(23,50) -> stoch(MACD, 10) %K EMA(3) -> tekrar stoch(…,10) EMA(3); 0-100; 25/75 esikleri (faktor 0.5).", "genel"),
    "Siber Döngü (Cyber Cycle) ★": (None, "Ehlers: smooth = (src + 2src[1] + 2src[2] + src[3])/6; cycle = (1-0.5a)^2*(smooth - 2smooth[1] + smooth[2]) + 2(1-a)*cycle[1] - (1-a)^2*cycle[2] (a=0.07); tetik = cycle[1].", "genel"),
    "STARC Bantları ★": (None, "Orta = SMA(close, 5 veya 15); Ust = Orta + k*ATR(15), Alt = Orta - k*ATR(15) (k=2 / 1.33).", "genel"),
    "Twiggs Para Akışı ★": (None, "TRH = max(H, C1), TRL = min(L, C1); AD = ((C-TRL) - (TRH-C))/(TRH-TRL) * hacim; TMF = Wilder-EMA(AD, N) / Wilder-EMA(hacim, N) (N=21).", "genel"),
    "DeMarker ★": (None, "DeMax = H > H1 ? H - H1 : 0; DeMin = L < L1 ? L1 - L : 0; DeM = SMA(DeMax,N) / (SMA(DeMax,N) + SMA(DeMin,N)) (N=14); 0.3/0.7.", "genel"),
    "Fraktal Uyarlamalı HO (FrAMA) ★": (None, "Ehlers: N1 = (HH-LL ilk yari)/(N/2), N2 ikinci yari, N3 = (HH-LL tum)/N; D = (ln(N1+N2) - ln(N3))/ln2; alpha = exp(-4.6(D-1)) sinirli [0.01,1]; FRAMA = alpha*src + (1-alpha)*FRAMA[1] (N=16).", "genel"),
    "Heikin-Ashi ★": (None, "haClose = (O+H+L+C)/4; haOpen = (haOpen[1] + haClose[1])/2; haHigh = max(H, haOpen, haClose); haLow = min(L, haOpen, haClose).", "genel"),
    "Market Facilitation Index (BW MFI) ★": (None, "BW MFI = (H - L) / hacim; renk: MFI ve hacim ikisi artar = yesil, ikisi azalir = solgun, MFI artar hacim azalir = sahte, MFI azalir hacim artar = cekisme.", "genel"),
    "Numbers Bars (Sayı Barları) ★": (None, "Her mum icinde fiyat seviyesi basina alt zaman dilimi hacim/delta sayilari (footprint benzeri); TV topluluk 'Numbers Bars'.", "genel"),
    "OsMA ★": (None, "OsMA = MACD(12,26) - Sinyal(9) (MT4/5 'Moving Average of Oscillator'); MACD histogramina esdeger.", "genel"),
    "VIDYA (Değişken Endeks Dinamik Ortalaması) ★": (None, "Chande VIDYA: alpha = 2/(N+1) * |CMO(src, 9)|/100; VIDYA = alpha*src + (1-alpha)*VIDYA[1] (N=9 veya 20).", "genel"),
    # ================= Piyasa
    "HO Üzerindeki Hisse Yüzdesi ★": (None, "% = (SMA(50/200) ustunde kapanan hisse sayisi / toplam hisse) * 100 (endeks genisligi verisi, orn. $SPXA50R).", "genel"),
    "McClellan Osilatörü ve Toplam Endeksi ★": (None, "Net = yukselen - dusen (opsiyonel oranlanmis); McClellan Osc = EMA(Net,19) - EMA(Net,39); Summation Index = kumulatif toplam(Osc).", "genel"),
    "Pring Yayılım Göstergesi ★": (None, "Diffusion: belirli sayida hisse/sektorun 'MA ustunde' olma yuzdesinin yumusatilmis hali (orn. EMA 10); 0-100.", "genel"),
    "Put/Call Oranı ★": (None, "PCR = put hacmi / call hacmi (CBOE verisi, orn. $CPC); SMA(10) ile yumusatilir; 1 ustu korku.", "genel"),
    "TRIN / Arms Endeksi ★": (None, "TRIN = (yukselen/dusen hisse) / (yukselen hacim/dusen hacim); 1 ustu satis baskisi; TV sembolu $TRIN.", "genel"),
    "Yüksek-Düşük Endeksi / Net Yeni Zirveler ★": (None, "Record High % = yeni 52h zirve / (zirve + dip) * 100; High-Low Index = SMA(Record High %, 10); Net New Highs = zirve - dip.", "genel"),
    "Yükselen-Düşen Hattı (ADL) ★": ("Advance/Decline Line", None, None),
    "Yükseliş Yüzdesi Endeksi (BPI) ★": (None, "BPI = P&F alim sinyali veren hisse yuzdesi (0-100); 70 ustu asiri alim, 30 alti asiri satim (orn. $BPSPX).", "genel"),
    "COT Raporu (Vadeli Pozisyon) ★": (None, "CFTC haftalik: ticari / buyuk spekulator / kucuk net pozisyon = long - short; COT Index = (net - min(net,N)) / (max-min) * 100 (N = 26 hafta).", "genel"),
    "VIX / VVIX / SKEW ★": (None, "VIX = S&P 500 opsiyonlarinin 30 gunluk beklenen volatilitesi (CBOE formulu, varyans swap); VVIX = VIX opsiyon volatilitesi; SKEW = kuyruk riski (100 = normal).", "genel"),
    "Açık Pozisyon ve Uzun/Kısa Oranı ★": ("Open Interest", "Long/Short Ratio = long hesap sayisi / short hesap sayisi (TV yardim: Long/Short Ratio Accounts).", None),
    "CVDD / RHODL / CDD ★": (None, "CDD = Sum(harcanan coin * tutulma gunu); CVDD = kumulatif(CDD * fiyat) / (arz * 6e6); RHODL = 1 hafta / 1-2 yil realized value banti orani.", "genel"),
    "Fonlama Oranı (Funding Rate) ★": ("Funding rate", None, None),
    "MVRV / MVRV Z-Skoru ★": (None, "MVRV = piyasa degeri / gerceklesmis deger; Z = (piyasa degeri - gerceklesmis deger) / stdev(piyasa degeri).", "genel"),
    "NUPL ★": (None, "NUPL = (piyasa degeri - gerceklesmis deger) / piyasa degeri; >0.75 euphoria, <0 kapitulasyon.", "genel"),
    "Puell Çarpanı / Hash Şeritleri ★": (None, "Puell = gunluk madenci geliri (USD) / SMA(gelir, 365); Hash Ribbons: SMA(hashrate,30) ile SMA(hashrate,60) kesisimi.", "genel"),
    "SOPR ★": (None, "SOPR = harcanan ciktilarin satis fiyati / alis fiyati (gerceklesmis deger orani); 1 ustu kar realizasyonu (TV yardim: Spent Output Profit Ratio).", "TV-yardim*"),
    "Tasfiye (Likidasyon) Verisi ★": ("Liquidation data", None, None),
}


def formula_for(name: str) -> tuple[str, str]:
    if name not in MAP:
        return ("(hesaplama eklenmedi)", "yok")
    key, extra, tag = MAP[name]
    parts = []
    status = tag or "genel"
    if key is not None:
        rec = TV.get(key)
        if rec is None:
            raise SystemExit(f"TV kaydi yok: {key} ({name})")
        parts.append(rec["formula_tr"].strip())
        d = (rec.get("defaults") or "").strip()
        if d:
            parts.append("Varsayilan: " + d)
        status = tag or ("TV-yardim" if rec["status"] == "verified" else "TV-yardim*")
    if extra:
        parts.append(extra)
    return (" | ".join(parts), status)


def load_tv(folder: str) -> None:
    for b in "ABC":
        for rec in json.load(open(os.path.join(folder, f"formuller_{b}.json"), encoding="utf-8")):
            TV[rec["name"]] = rec


def parse_data(js: str):
    start = js.index("const DATA = [") + len("const DATA = ")
    tail = js[start:]
    end = re.search(r"\n\];", tail).end()
    arr = tail[:end - 1]
    py = re.sub(r"(\n\s*)(\w+):", r"\1'\2':", arr)
    data = eval(py)  # noqa: S307 - kendi belgemiz; \' kacislari Python ile uyumlu
    return data, start, start + end - 1


def main() -> None:
    html_path = sys.argv[1]
    load_tv(sys.argv[2])
    html = open(html_path, encoding="utf-8").read()
    m = re.search(r"<script>(.*)</script>", html, flags=re.S)
    js = m.group(1)
    data, a, b = parse_data(js)
    counts = {}
    for tab in data:
        for g in tab["groups"]:
            for it in g["items"]:
                f, st = formula_for(it[0])
                counts[st] = counts.get(st, 0) + 1
                if len(it) >= 4:
                    it[2], it[3] = f, st
                else:
                    it.extend([f, st])
    new_data = json.dumps(data, ensure_ascii=False, indent=2)
    js2 = js[:a] + new_data + js[b:]
    # render: 3. sutun
    js2 = js2.replace(
        """        '<th onclick="sortTab(\\'' + d.id + '\\', 1)">Teknik Avantajı ve Sağladığı Fayda ⇅</th>' +""",
        """        '<th onclick="sortTab(\\'' + d.id + '\\', 1)">Teknik Avantajı ve Sağladığı Fayda ⇅</th>' +
        '<th onclick="sortTab(\\'' + d.id + '\\', 2)">Hesaplama (TradingView) ⇅</th>' +""",
    )
    js2 = js2.replace("""return (it[0] + ' ' + it[1]).toLocaleLowerCase('tr').indexOf(t) !== -1;""",
                      """return (it[0] + ' ' + it[1] + ' ' + (it[2] || '')).toLocaleLowerCase('tr').indexOf(t) !== -1;""")
    js2 = js2.replace("""html += '<tr class="group-row"><td colspan="2">'""", """html += '<tr class="group-row"><td colspan="3">'""")
    js2 = js2.replace(
        """              '<td>' + esc(it[1]) + '</td></tr>';""",
        """              '<td>' + esc(it[1]) + '</td>' +
              '<td class="calc"><span class="src src-' + esc(it[3] || 'genel').replace('*', 'x') + '">' + esc(it[3] || 'genel') + '</span> ' + esc(it[2] || '') + '</td></tr>';""",
    )
    assert "Hesaplama (TradingView)" in js2 and 'class="calc"' in js2 and 'colspan="3"' in js2
    html2 = html[:m.start(1)] + js2 + html[m.end(1):]
    css = """        td.calc { font-family: Consolas, 'Courier New', monospace; font-size: 12px; color: #c9cdd6; line-height: 1.5; }
        .src { display: inline-block; font-size: 10px; padding: 1px 6px; border-radius: 8px; margin-right: 4px; font-family: 'Segoe UI', sans-serif; }
        .src-TV-yardim { background: #1b5e20; color: #c8e6c9; }
        .src-TV-yardimx { background: #4e5b2a; color: #e6eecf; }
        .src-TV-kod { background: #0d47a1; color: #bbdefb; }
        .src-genel { background: #4a4e59; color: #d1d4dc; }
        .calc-note { background-color: #232730; border-left: 3px solid #26a69a; color: #a9adb7; font-size: 13px; line-height: 1.6; padding: 12px 15px; margin: 0 0 18px 0; border-radius: 4px; }
"""
    html2 = html2.replace("        .tab-note {", css + "        .tab-note {", 1)
    note = ("<p class=\"calc-note\"><b>Hesaplama sütunu (eklendi: " + date.today().isoformat() + ")</b> — "
            "<span class=\"src src-TV-yardim\">TV-yardim</span> TradingView Yardım Merkezi makalesinin hesaplama bölümünden; "
            "<span class=\"src src-TV-yardimx\">TV-yardim*</span> makale var ama formül vermiyor, genel tanım yazıldı; "
            "<span class=\"src src-TV-kod\">TV-kod</span> TradingView açık kaynak Pine kodundan birebir; "
            "<span class=\"src src-genel\">genel</span> TradingView sayfası okunmadı, yaygın bilinen tanım. "
            "Topluluk/SMC scriptlerinin kodları yazara göre değişir; oradaki formüller temsili. "
            "Yumuşatma kısaltmaları: SMA basit, EMA üstel, RMA Wilder (ta.rma), WMA doğrusal ağırlıklı.</p>\n")
    html2 = html2.replace('<div class="tabs"', note + '<div class="tabs"', 1) if '<div class="tabs"' in html2 else html2.replace('<div id="tabs"', note + '<div id="tabs"', 1)
    assert "calc-note" in html2
    stem, ext = os.path.splitext(html_path)
    backup = f"{stem}.yedek_{date.today().isoformat()}{ext}"
    if not os.path.exists(backup):
        shutil.copyfile(html_path, backup)
    open(html_path, "w", encoding="utf-8").write(html2)
    repo_copy = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "GOSTERGELER_HESAPLAMALI.HTML")
    open(repo_copy, "w", encoding="utf-8").write(html2)
    print("yazildi:", html_path, "| yedek:", backup, "| kopya:", repo_copy)
    print("kaynak dagilimi:", counts)


if __name__ == "__main__":
    main()
