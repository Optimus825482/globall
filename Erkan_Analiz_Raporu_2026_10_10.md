# ERKAN - FOREX SCALPER İŞLEMLERİ ANALİZ RAPORU
## Dosya: `D:\scalperagent_global\forex_scalper_islemler_2026-10-10.csv`
## Tarih: 10.10.2026

---

## ÖZET

- **Toplam işlem:** 187
- **Win Rate:** %65,8 (123 kazanç / 64 kayıp)
- **Toplam Net Getiri:** +156,41 USD
- **Ortalama işlem süresi:** 23,2 dk (medyan: 11,1 dk)
- **Kayıplı işlem ortalama süresi:** 26,7 dk
- **Kazançlı işlem ortalama süresi:** 21,3 dk

Genel görünüm **kârlı** ama **riskli**. Win rate yüksek olsa da BTCUSD tarafı toplam getiriyi ciddi şekilde aşağı çekiyor.

---

## 1. STRATEJİ DAĞILIMI VE PERFORMANSI

| Strateji | İşlem | Kazanç | Kayıp | Win Rate | Toplam USD | Ort. Pip | Ort. Süre (dk) |
|---|---|---|---|---|---|---|---|
| M1/M5 Çoklu Radar | 177 | 120 | 57 | %68 | +225,45 | +1,19 | 22,5 |
| IC Markets MT5 | 8 | 3 | 5 | %38 | -32,15 | -5,15 | 43,0 |
| S3 SuperTrend+RSI | 2 | 0 | 2 | %0 | -36,89 | -194,7 | 4,0 |

**Bulgu:**
- **M1/M5 Çoklu Radar** hem işlem sayısı hem de kârlılık açısından ana strateji. Win rate %68 ve nette +225 USD kazandırıyor.
- **S3 SuperTrend+RSI** sadece 2 işlem ama ikisi de büyük kayıpla kapanmış (-194,7 pip ortalama). Strateji veri setinde yetersiz örneklem ama mevcut örnekler **zararlı**.
- **IC Markets MT5** stratejisi de negatif getirili. 8 işlemden 5'i kayıp.

### Parite × Strateji Performansı

| Parite | Strateji | İşlem | Win Rate | Toplam USD |
|---|---|---|---|---|
| BTCUSD | M1/M5 Çoklu Radar | 71 | %65 | **-42,11** |
| BTCUSD | S3 SuperTrend+RSI | 2 | %0 | **-36,89** |
| BTCUSD | IC Markets MT5 | 2 | %100 | +8,31 |
| GBPUSD | M1/M5 Çoklu Radar | 5 | %60 | +0,14 |
| GBPUSD | IC Markets MT5 | 3 | %0 | -11,50 |
| US30 | M1/M5 Çoklu Radar | 37 | %65 | **+148,13** |
| XAUUSD | M1/M5 Çoklu Radar | 64 | %73 | **+119,29** |
| XAUUSD | IC Markets MT5 | 2 | %0 | -30,22 |

**Yorum:**
- M1/M5 Çoklu Radar **XAUUSD ve US30'da çok başarılı**, BTCUSD'de zararlı.
- BTCUSD, M1/M5 stratejisinin en zayıf paritesi.
- S3 SuperTrend+RSI sadece BTCUSD'de denenmiş ve iki işlemde de büyük kayıp vermiş.

---

## 2. YÖN KARARLARININ TUTARLILIĞI

### Parite Bazında Yön Dağılımı

| Parite | BUY | SELL | Toplam | BUY Oranı |
|---|---|---|---|---|
| BTCUSD | 64 | 11 | 75 | **%85,3** |
| GBPUSD | 5 | 3 | 8 | %62,5 |
| US30 | 38 | 0 | 38 | **%100** |
| XAUUSD | 51 | 15 | 66 | %77,3 |
| **Toplam** | **158** | **29** | **187** | **%84,5** |

### Yön × Performans

| Parite | Yön | İşlem | Win Rate | Toplam USD | Ort. Pip | Ort. Süre (dk) |
|---|---|---|---|---|---|---|
| BTCUSD | BUY | 64 | %64,1 | -28,73 | -6,13 | 15,5 |
| BTCUSD | SELL | 11 | %63,6 | -41,96 | -41,74 | 5,5 |
| GBPUSD | BUY | 5 | %20,0 | -30,29 | -1,48 | 131,9 |
| GBPUSD | SELL | 3 | %66,7 | +18,93 | +2,63 | 60,9 |
| US30 | BUY | 38 | %65,8 | +149,39 | +8,71 | 35,1 |
| XAUUSD | BUY | 51 | %76,5 | +149,50 | +8,45 | 19,3 |
| XAUUSD | SELL | 15 | %53,3 | -60,43 | -8,65 | 8,2 |

### BTCUSD'de BUY Baskısı Var Mı?

**Evet, çok güçlü BUY baskısı var.** BTCUSD işlemlerinin **%85,3'ü BUY**. Bu oran diğer paritelere göre de çok yüksek:
- XAUUSD: %77,3 BUY
- US30: %100 BUY
- GBPUSD: %62,5 BUY

### Fiyat Hareketine Uygun Mu?

Veri setindeki ilk ve son giriş fiyatlarına bakarak genel trend yönü çıkarılabilir:

| Parite | İlk Giriş | Son Giriş | Değişim | Yön Uyumu |
|---|---|---|---|---|
| BTCUSD | 80.621 | 82.616 | **+2,47%** | BUY ağırlığı uyumlu |
| XAUUSD | 4.131 | 4.194 | **+1,51%** | BUY ağırlığı uyumlu |
| US30 | 51.174 | 51.342 | **+0,33%** | Sadece BUY, hafif yükselişle uyumlu |
| GBPUSD | 1,3231 | 1,3232 | **0,00%** | Yatay bant, karışık yön |

**BTCUSD detaylı yorum:**
- Fiyat genel trendte yükselmiş (+2,47%). Bu durumda BUY ağırlıklı işlem açmak **doğru yönde**.
- Ancak BUY işlemlerinin ortalama pip'i **-6,13** (negatif). Yani doğru yön tahmini yapılmış ama **giriş zamanlaması veya stop seviyeleri kötü**.
- SELL işlemleri özellikle zararlı: Ortalama -41,74 pip. Yükseliş trendine karşı SELL denemeleri genelde büyük kayıpla sonuçlanmış.

---

## 3. ARDIŞIK İŞLEMLERDE YÖN DEĞİŞİMİ / WHIPSAW

### Whipsaw (Kayıp → Ters Yön → Kayıp) Tespitleri

| Parite | Ters Yön Değişimi | Whipsaw Sayısı | Açıklama |
|---|---|---|---|
| BTCUSD | 4 | **1** | 16:27 BUY kayıp (-154,6p) → 16:37 SELL kayıp (-184,3p) |
| GBPUSD | 3 | **1** | 10:00 SELL kayıp (-8,0p) → 10:18 BUY kayıp (-8,0p) |
| US30 | 0 | 0 | Hiç yön değişimi yok |
| XAUUSD | 4 | 0 | Yön değişimi var ama whipsaw yok |

**BTCUSD Whipsaw Detayı:**
- 10-09 16:27: BUY giriş 82.925 → SL 82.771 (-154,6p)
- 10-09 16:37: SELL giriş 82.500 → SL 82.685 (-184,3p)
- Bu dönemde fiyat hem yukarı hem aşağı sert hareket etmiş; her iki yöndeki işlem de SL'ye gitmiş.

**Yorum:**
- Whipsaw sayısı düşük (187 işlemde sadece 2 örnek).
- Ancak **XAUUSD ve BTCUSD'de yön değişimleri** mevcut. Bu, stratejinin yön algısının bazı dönemlerde dalgalandığını gösterir.
- US30'da hiç SELL yok, bu da **tek yönlü bias** anlamına gelir. Piyasa aşağı döndüğünde korunmasız kalınabilir.

---

## 4. MARKET REGIME CLASSIFIER PERSPEKTİFİ

### Çıkış Nedenleri Dağılımı

| Çıkış Nedeni | Sayı | Oran | Win Rate | Ort. Pip | Toplam USD |
|---|---|---|---|---|---|
| Zarar Durdur (SL) | 167 | **%92,0** | %68 | -2,55 | +101,26 |
| Kâr Al (TP) | 9 | %4,8 | %100 | +60,0 | +154,82 |
| Scalper Close | 6 | %3,2 | %17 | -33,7 | -57,95 |
| Zarar (SL/Piyasa) | 5 | %2,7 | %0 | -26,1 | -41,72 |

**Kritik Bulgu:**
- İşlemlerin **%92'si SL ile kapanıyor**. Bu, stratejinin TP yerine **trailing stop / breakeven** mantığıyla çalıştığını gösterir.
- SL ile kapanan işlemlerin **%65,7'si kazançlı**. Yani SL seviyesi aslında kâr realizasyonu noktası gibi kullanılmış.
- TP oranı sadece **%4,8**. Bu çok düşük. Trend genişlemesi rejiminde TP'lerin artması beklenir.

### İşlem Süreleri

| Süre Aralığı | İşlem Sayısı | Oran |
|---|---|---|
| ≤2 dk | 13 | %7,0 |
| ≤5 dk | 48 | %25,7 |
| 5-15 dk | 64 | %34,2 |
| >15 dk | 75 | %40,1 |

### Parite Bazında SL/TP Dağılımı

| Parite | İşlem | SL | TP | Scalper Close |
|---|---|---|---|---|
| BTCUSD | 75 | 71 (%95) | 0 (%0) | 4 (%5) |
| GBPUSD | 8 | 7 (%88) | 1 (%12) | 0 |
| US30 | 38 | 33 (%87) | 5 (%13) | 0 |
| XAUUSD | 66 | 61 (%92) | 3 (%5) | 2 (%3) |

### Rejim Değerlendirmesi

**CHOPPY_RANGE (Testere) Belirtileri:**
1. BTCUSD'de **%95 SL**, **%0 TP** ile kapanma — bu trend genişlemesi yerine **kısa vadeli dalgalanma** işareti.
2. BTCUSD'de sürekli BUY denemeleri ve sık SL vuruşları.
3. GBPUSD'de fiyat neredeyse yatay (%0 değişim) ama yine de işlem açılmış.
4. XAUUSD'de de SL oranı %92 çok yüksek.

**Trend Genişlemesi Belirtileri:**
- BTCUSD ve XAUUSD fiyatı genel olarak yükselişte.
- Ancak TP oranları çok düşük olduğu için "sağlıklı trend" yerine **zayıf/volatile trend** diyebiliriz.
- US30'da sürekli BUY ve kârlı sonuçlar — bu en yakın trend genişlemesi örneği.

**Sonuç:** Veri setinin büyük kısmı **düşük kaliteli trend / yüksek gürültü** ortamında işlem görmüş. BTCUSD özellikle **testere + yüksek volatilite** karışımı bir rejimde. Market Regime Classifier muhtemelen bu dönemi **CHOPPY_RANGE** veya **WEAK_TREND** olarak sınıflandırırdı.

---

## 5. SIGNAL ARBITER EXPERT PERSPEKTİFİ

Veride doğrudan volatilite, spread, CVD veya order book verisi yok. Ancak işlem sonuçlarından çıkarım yapılabilir:

### Yüksek Volatilite Riski

| Parite | Max Kazanç (pip) | Max Kayıp (pip) | Ort. Kayıp (pip) |
|---|---|---|---|
| BTCUSD | +420,3 | **-233,3** | -93,4 (kayıplarda) |
| XAUUSD | +91,8 | -76,8 | -53,7 (kayıplarda) |
| US30 | +248,7 | -54,7 | -52,8 (kayıplarda) |
| GBPUSD | +12,1 | -8,0 | -4,7 (kayıplarda) |

**BTCUSD:**
- Max kayıp **-233,3 pip** çok yüksek.
- Kayıplı işlemlerin ortalaması **-93,4 pip**.
- Bu, ya **geniş stop kullanımı** ya da **sert fiyat hareketleri** anlamına gelir.
- BTCUSD ortalama süresi 14 dk, median 8,2 dk. Kısa sürede büyük pip hareketleri = yüksek volatilite.

### Spread ve Slipaj Riski

- BTCUSD işlemlerinin **%95'i SL ile kapanıyor**, TP yok. Bu, spreadin veya anlık fiyat dalgalanmalarının sık stop avına uğradığını düşündürür.
- Özellikle gece saatlerinde (20:00-02:00) BTCUSD işlemleri yoğun. Bu saatlerde **likidite düşük**, spread yüksek olabilir.
- GBPUSD'de 20:36-20:56 arası 3 ardışık BUY işlemi, hepsi **SL/Piyasa** ile kayıpla kapanmış. Gece likiditesi + spread riski net.

### Sinyal Teyidi Eksikliği

- Ardışık işlemler arasında çok kısa aralıklar var (örneğin BTCUSD 05:18, 05:21, 05:46). Bu, stratejinin **her küçük harekette tekrar tekrar sinyal ürettiğini** gösterir.
- **MTF (Multi-Timeframe) teyit olmadan** bu kadar sık işlem açmak, gürültüden kaynaklanan false signal riskini artırır.

### Fake Breakout Riski

- BTCUSD'de 14:42'de BUY giriş 82.920 → 83.340 (+420,3p) büyük kazanç.
- Ancak hemen öncesinde ve sonrasında birçok işlem SL'ye gitmiş. Bu, **breakout denemelerinin çoğunun fake olduğunu**, sadece birkaçının tuttuğunu gösterir.
- 16:20-16:45 arası 4 işlemde 3'ü büyük kayıp: BUY → BUY → SELL → SELL. Fiyat 83.038'den 82.463'e düşmüş. Bu dönemde yön algısı net değil.

### CVD / Order Book Eksikliği

- Veride CVD (Cumulative Volume Delta) veya order book depth yok.
- Eğer bu veriler olsaydı, agresif alım/satımın **gerçek hacimle desteklenip desteklenmediği** kontrol edilebilirdi.
- Özellikle BTCUSD'de 85% BUY bias'ı, spot/emir defteri verisi olmadan **teknik indikatörden gelen yanılsama** olabilir.

---

## 6. GBPUSD YÖN ANALİZİ

**GBPUSD'de sadece BUY yok, hem BUY hem SELL var.**

| Yön | İşlem | Win Rate | Toplam USD |
|---|---|---|---|
| BUY | 5 | %20 | -30,29 |
| SELL | 3 | %67 | +18,93 |

### İşlem Listesi

| Zaman | Yön | Giriş | Çıkış | Pip | Sonuç | Süre | Çıkış Nedeni |
|---|---|---|---|---|---|---|---|
| 08.10 20:36 | BUY | 1,32309 | 1,32247 | -6,2 | Kayıp | 76 dk | SL/Piyasa |
| 08.10 20:48 | BUY | 1,32280 | 1,32247 | -3,3 | Kayıp | 64 dk | SL/Piyasa |
| 08.10 20:56 | BUY | 1,32267 | 1,32247 | -2,0 | Kayıp | 56 dk | SL/Piyasa |
| 08.10 21:57 | BUY | 1,32262 | 1,32383 | +12,1 | Kazanç | 364 dk | TP |
| 09.10 10:00 | SELL | 1,32338 | 1,32418 | -8,0 | Kayıp | 17 dk | SL |
| 09.10 10:18 | BUY | 1,32440 | 1,32360 | -8,0 | Kayıp | 98 dk | SL |
| 09.10 13:33 | SELL | 1,32372 | 1,32316 | +5,6 | Kazanç | 56 dk | SL (trailing) |
| 09.10 14:29 | SELL | 1,32315 | 1,32212 | +10,3 | Kazanç | 108 dk | SL (trailing) |

### Neden?

1. **Gece BUY'ları başarısız:** 20:36-20:56 arası 3 ardışık BUY, hepsi kayıp. Fiyat yatay/sınırlı hareket ediyor, spread ve gece likiditesi BUY'ları vurmuş.
2. **Bir uzun BUY kazançlı:** 21:57'de açılan BUY 364 dk tutulmuş ve TP ile kapanmış. Bu, sabırlı bekleyen tek işlem.
3. **Ertesi gün SELL'ler kazançlı:** 09.10 öğleden sonra SELL'ler kazançlı. Fiyat hafifçe gerilemiş.
4. **GBPUSD genel trend yok:** İlk ve son giriş fiyatları neredeyse aynı (%0 değişim). Bu yüzden hem BUY hem SELL denenmiş, ama **BUY tarafı ağır kaybetmiş**.

**Sonuç:** GBPUSD'de SELL işlemleri var ve **SELL'ler daha başarılı**. BUY ağırlıklı yaklaşım burada işe yaramamış.

---

## 7. ÖNERİLER: EK FİLTRELER VE REJİME GÖRE STRATEJİ

### 7.1. Eklenmesi Gereken Filtreler

| Filtre | Amacı | Öncelik |
|---|---|---|
| **MTF MACD** | M1/M5 sinyalinin H1/H4 trendiyle uyumunu teyit etmek | Yüksek |
| **ADX** | Trend gücünü ölçmek. ADX < 20 ise CHOPPY_RANGE, işlem yasak | Yüksek |
| **CVD (Cumulative Volume Delta)** | Alım/satım baskısını doğrulamak. Fiyat yükseliyor ama CVD düşüyorsa fake breakout | Yüksek |
| **Spread Filtresi** | Özellikle BTC ve gece saatlerinde spread > X pip ise işlem engelleme | Yüksek |
| **Hacim / Volume Profile** | Ana destek/direnç bölgelerinde işlem onayı | Orta |
| **Fonlama Oranı (Funding Rate)** | Kripto için long/short bias göstergesi. Negatif funding → short baskı | Orta |
| **Haber Kalkanı (News Filter)** | Yüksek etkili haberlerden önce/sonra işlem kapama | Yüksek |
| **VWAP / Anchored VWAP** | Ortalama fiyat referansı, fiyat VWAP üzerindeyse BUY bias | Orta |
| **ATR Bazlı Stop** | Sabit pip yerine ATR'ye göre dinamik stop | Yüksek |

### 7.2. Rejime Göre Yön/Strateji Seçimi

| Rejim | Strateji | Yön | Risk Kuralları |
|---|---|---|---|
| **CHOPPY_RANGE** | Range-bound, Bollinger Bands orta bandı dönüşleri | Her iki yön | ADX < 20 + ATR düşük + hacim düşük → **işlem yasak veya lot küçült** |
| **WEAK_TREND** | M1/M5 Çoklu Radar + MTF MACD teyidi | Trend yönünde | Spread filtresi, CVD onayı, ATR stop |
| **STRONG_TREND** | Trend takibi, pullback'lerden giriş | Trend yönünde | SL'yi trailing stop'a çevir, TP hedefleri genişlet |
| **HIGH_VOLATILITY** | Breakout stratejisi | Breakout yönünde | Haber kalkanı zorunlu, pozisyon küçült, volatilite normalleşene kadar bekle |
| **LOW_LIQUIDITY** (gece) | İşlem yok veya çok küçük lot | Yalnızca güçlü setup | Spread kontrolü, BTC ve GBPUSD'de özellikle dikkatli |

### 7.3. Parite Özel Öneriler

**BTCUSD:**
- **BUY bias'ı azalt.** %85 BUY ağırlık çok yüksek.
- **Funding rate + CVD filtresi** ekle.
- **Spread filtresi** kritik. Gece ve volatil dönemlerde işlem sayısını sınırla.
- **S3 SuperTrend+RSI** stratejisi durdurulsun veya optimize edilsin. 2/2 kayıp.

**XAUUSD:**
- Performans iyi (+119 USD, %73 WR).
- Yine de SL oranı %92 → **TP hedefleri artırılmalı**.
- SELL işlemlerinde win rate düşük (%53), SELL filtresi güçlendirilmeli.

**US30:**
- En iyi performans (+149 USD, %66 WR).
- **SELL stratejisi eklenmeli.** Sadece BUY işlem açmak yukarı trendin tersine döndüğü anlarda riskli.

**GBPUSD:**
- **Gece işlemlerini sınırla.** 20:00-22:00 arası işlemler kötü sonuçlanmış.
- **Yatay piyasada işlem azalt.** ADX < 20 ise GBPUSD'de pasif kal.
- SELL'ler daha başarılı; SELL filtresi geliştirilmeli.

### 7.4. Risk Yönetimi Önerileri

1. **Günlük kayıp limiti:** Tek günde -X USD kayba ulaşıldığında işlemleri durdur.
2. **Ardışık kayıp limiti:** 3 ardışık kayıp sonrası 15 dk mola.
3. **Pozisyon büyüklüğü:** BTCUSD'de lot/pozisyon büyüklüğü düşürülmeli (kayıplar büyük).
4. **TP/SL oranı:** Mevcut SL odaklı strateji yerine **en az 1:1.5 R:R** hedeflenmeli.
5. **Correlation kontrolü:** Aynı anda çok fazla pozisyon açmak yerine parite korelasyonuna göre limit koy.

---

## SONUÇ

- **XAUUSD ve US30**, M1/M5 Çoklu Radar ile **güçlü performans** gösteriyor.
- **BTCUSD** stratejinin zayıf halkası. Aşırı BUY bias, yüksek SL oranı, büyük pip kayıpları var.
- **GBPUSD** işlem sayısı az ama BUY'lar özellikle gece saatlerinde zararlı.
- Veri seti genel olarak **yüksek volatilite / düşük TP oranı / SL odaklı** bir rejimi yansıtıyor.
- **Signal Arbiter** ve **Market Regime Classifier** entegrasyonu ile filtreler eklendiğinde (ADX, MTF MACD, CVD, spread, haber kalkanı), performansın daha stabil hale gelmesi beklenir.

**Hazırlayan:** Verdent Analiz Botu  
**Dosya:** `D:\scalperagent_global\forex_scalper_islemler_2026-10-10.csv`  
**Analiz Scripti:** `D:\scalperagent_global\analiz_2026_10_10.py`
