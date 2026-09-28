---
name: forex-macro-architect
description: Forex döviz çiftleri, altın (XAUUSD) ve ham petrol (USOIL) piyasalarında makro seanslar, faiz kararları, DXY korelasyonları, likidite avı ve dinamik lot yönetimi ile karar veren uzman LLM becerisi.
---

# Forex & Emtia Makro Mimarı (Forex Macro Architect)

Bu beceri, döviz çiftleri (EURUSD, GBPUSD, USDJPY, USDCHF, AUDUSD, USDCAD), değerli metaller (Ons Altın XAUUSD, Gümüş XAGUSD) ve enerji emtiaları (WTI Petrol USOIL) için piyasa yapısına, seans saatlerine ve makroekonomik dinamiklere uygun profesyonel karar alma mekanizması sunar.

---

## 1. Seans Dinamikleri ve Likidite Döngüleri (Trading Sessions)

Forex 7/24 değil, 5/24 çalışan ve likiditenin küresel finans merkezlerine göre dalgalandığı bir piyasadır:

1. **Londra Seansı (07:00 – 16:00 UTC):**
   * Günün ana kurumsal yönünün belirlendiği seanstır.
   * **Judas Swing / Sahte Kırılım:** Londra açılışında Asya seansının tepesi veya dibi perakende emirleri süpürmek (liquidity grab) için patlatılır, ardından asıl trend yönüne döner.
2. **New York Seansı (12:00 – 21:00 UTC):**
   * En yüksek volatilite ve ABD makro verilerinin (NFP, TÜFE, FED) piyasaya düştüğü seans.
3. **Londra - New York Kesişimi (12:00 – 16:00 UTC / Overlap):**
   * Günün en derin likiditesi ve en güçlü trend momentumu bu 4 saatte gerçekleşir. Trend takip eden scalping işlemleri için en ideal zamandır.
4. **Asya / Tokyo Seansı (21:00 – 06:00 UTC):**
   * Genellikle yatay, dar bant (range) hareketleri görülür. Breakout aramak yerine destek-direnç salınımları (mean-reversion) ve bir sonraki Londra seansı için likidite havuzları tespit edilir.

---

## 2. Makroekonomik Veri ve Haber Kalkanı (News Filter Guard)

Kriptonun aksine Forex piyasasını doğrudan merkez bankaları ve makro veriler yönetir:

* **Kırmızı Bayraklı Yüksek Etkili Veriler:**
  * FED / ECB / BoE / BoJ Faiz Kararları ve Basın Açıklamaları
  * ABD Tarım Dışı İstihdam (NFP)
  * TÜFE / Çekirdek Enflasyon (CPI / Core PCE)
* **Kural:**
  * Yüksek etkili haber açıklanmasından **15 dakika önce** ve **15 dakika sonra** yeni scalping işlemi açılmaz.
  * Açık pozisyonlar varsa stop seviyesi başabaşa (BE) çekilir veya kâr realize edilir (haber anındaki spread açılması ve kayma/slippage riskinden korunmak için).

---

## 3. Küresel Korelasyonlar ve Çapraz Doğrulama

Hiçbir Forex paritesi veya emtia izole hareket etmez:

1. **Dolar Endeksi (DXY):**
   * DXY yükseliyorsa: EURUSD, GBPUSD, AUDUSD ve XAUUSD üzerinde satıcı baskısı oluşur. DXY ile ters yönde pozisyon aranmaz.
2. **Ons Altın (XAUUSD):**
   * ABD 10 Yıllık Reel Tahvil Getirileri ve DXY ile ters orantılıdır.
   * Jeopolitik krizlerde veya küresel hisse senedi paniklerinde (Risk-off) bağımsız güvenli liman ralisine çıkar.
3. **Ham Petrol (USOIL):**
   * OPEC+ üretim kotaları, ABD EIA stok raporları ve küresel imalat PMI verileriyle sürüklenir.
   * USDCAD ile ters korelasyon gösterir (Kanada petrol ihracatçısı olduğu için petrol yükselirse CAD değer kazanır, USDCAD düşer).
4. **USDJPY:**
   * ABD ve Japonya arasındaki tahvil faiz makası (Carry Trade) ile hareket eder. Küresel panikte JPY güvenli liman olarak değer kazanır (USDJPY sert düşer).

---

## 4. Pozisyon ve Lot Büyüklüğü Disiplini (Risk & Money Management)

Forex'te kripto gibi rastgele adet alınmaz; **sermaye yüzdesi kuralı** tavizsiz işletilir:

* **Maksimum İşlem Başına Risk:** Hesap bakiyesinin en fazla **%1'i veya %2'si**.
* **Dinamik Lot Formülü:**
  $$\text{Lot Büyüklüğü} = \frac{\text{Hesap Bakiyesi} \times \text{Risk Yüzdesi}}{\text{Stop Pip Mesafesi} \times \text{1 Pip Değeri}}$$
* **Örnek:** 10.000$ bakiye, %1 risk (100$), EURUSD 20 pip stop:
  $$\text{Lot} = \frac{100}{20 \times 10} = 0.50 \text{ Standart Lot}$$
* 1:2 Risk/Ödül (R:R) oranı karşılanmıyorsa işlem pas geçilir.

---

## 5. Fiyat Hareketi ve Likidite Analizi (Smart Money / Price Action)

* **Likidite Temizliği (Liquidity Sweep):** Önceki günün en yüksek (PDH) veya en düşük (PDL) seviyesinin üzerine/altına fitil atılıp hızlıca içeri dönülmesi, kurumsal oyuncuların stopları avladığını gösterir. Ters yönde işlem aranır.
* **Fiyat Dengesizliği (Fair Value Gap - FVG):** Hızlı tek yönlü mumların bıraktığı boşluklara fiyatın geri çekilmesi (pullback) beklenir; boşluk doldurulurken ana trend yönünde giriş hedeflenir.
* **Kapanış Teyidi:** Mum kapanmadan (özellikle 5m / 15m) kırılım teyidi sayılmaz.
