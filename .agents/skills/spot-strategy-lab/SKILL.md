---
name: spot-strategy-lab
description: Spot kripto varlıklar için karlı gösterge, osilatör ve filtre kombinasyonlarını test etme, geriye dönük doğrulama (backtest) yapma, eleme kriterlerini uygulama ve Spot Monitor'e entegre etme becerisi. Yeni strateji keşfi, indikatör test laboratuvarı çalıştırma veya parametre optimizasyonu istendiğinde kullanın.
---

# Spot Strateji & Gösterge Keşif Laboratuvarı (Spot Strategy Lab)

Bu beceri, Binance TR ve Binance Spot kripto piyasalarında yüksek başarı oranlı (Win Rate) ve karlı (Profit Factor > 1.5) gösterge/filtre kombinasyonlarını bilimsel metotla test etmek, doğrulamak ve canlı **Spot Monitor** sistemine entegre etmek için tasarlanmıştır.

---

## 1. Temel Prensipler ve Maliyet Disiplini

1. **Kamuya Açık Gerçek Veri (Fresh Public Data):**
   - Testler asla sentetik (mock) veya rastgele üretilmiş verilerle yapılmaz.
   - Binance Public API üzerinden en az 1.000 barlık gerçek 5m, 15m ve 1h mum verileri kullanılır (`fetch_binance_klines`).
2. **Kesin Komisyon ve Kayma (Slippage) Modeli:**
   - Spot piyasada her alım ve satımda toplam **%0.08 round-trip komisyon** (%0.04 Maker + %0.04 Taker) net kârdan doğrudan düşülür.
   - Komisyon düşülmeden önceki brüt kâr kesinlikle başarı metriği olarak kabul edilemez.
3. **Gerçekçi İşlem Simülasyonu:**
   - Tek barda aynı anda hem TP hem SL seviyesi görülmüşse muhafazakar olarak SL kabul edilir.
   - Zaman aşımı kuralı (maksimum 48 bar / 4 saat) ile likiditesi kilitlenen işlemler anlık fiyattan kapatılır.
   - Bir sembolde pozisyon açıkken aynı sembole mükerrer pozisyon açılmaz.
4. **Hacim ve Durağanlık (Ölü Tahta) Eleme Filtresi:**
   - **Range/Oynaklık Eşiği:** Son 20 barda fiyat tepe-dip aralığı (`recent_range_pct`) en az **%0.40** olmalıdır; saatlerce dar bir bantta sıkışıp donan ölü tahtalar doğrudan elenir.
   - **Minimum TRY Hacmi:** Son 20 barın ortalama bar hacmi en az **20.000 TL** ve ortalama işlem adedi bar başına en az **3 trade** olmalıdır.
   - **Göreceli Hacim (Fake Kırılım Koruması):** Sinyal anındaki bar hacmi, ortalama hacmin en az **%30**'u olmalıdır; hacimsiz ölü barlarda sahte indikatör kesişimleri engellenir.

---

## 2. Test Motoru ve Çalıştırma Protokolü

### Test Betiği Konumu
- Ana test laboratuvarı betiği: [`scripts/test_advanced_spot_strategies.py`](file:///d:/PROJELLER/globall/scripts/test_advanced_spot_strategies.py)

### Çalıştırma Komutu
```powershell
# Projenin sanal ortam python'u ile çalıştırın:
cd d:\PROJELLER\globall
d:\PROJELLER\globall\backend\venv\Scripts\python.exe scripts/test_advanced_spot_strategies.py
```

### Standart Test Havuzu
- **Coinler:** `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `AVAXUSDT`, `LINKUSDT`, `DOTUSDT`, `DOGEUSDT`, `PEPEUSDT`, `SHIBUSDT`, `OPUSDT`
- **Genişletilmiş Havuz:** `NEARUSDT`, `BNBUSDT`, `XRPUSDT`, `ADAUSDT`, `RENDERUSDT`, `FETUSDT`, `ARBUSDT`, `INJUSDT`
- **Zaman Dilimleri:**
  - `5m`: Hızlı Scalp (%1.5 TP, %0.9 SL)
  - `15m`: Standart Trend (%2.2 TP, %1.2 SL)
  - `1h`: Swing Momentum (%4.0 TP, %2.0 SL)

---

## 3. Gösterge Kütüphanesi ve Kombinasyon Kataloğu

Laboratuvarda test edilebilecek ve optimize edilecek başlıca gösterge bileşenleri:

| Gösterge Türü | Formül / Parametre | Görev / Avantaj |
| :--- | :--- | :--- |
| **KDJ İndikatörü** | Period: 9, Signal: 3 | J eğrisinin ekstrem dipten (J <= 15) K ve D'yi yukarı keserek sıçraması. |
| **EMA Pullback** | EMA 20, EMA 50, EMA 200 | Ana trend yönündeki geri çekilmelerde ortalamaya %0.8-%1.2 toleransla dokunup sekme. |
| **SuperTrend** | Period: 10, Factor: 3.0 | ATR tabanlı dinamik trend filtresi (Yalnızca yeşil/boğa yönünde işlem izni). |
| **Schaff Trend Cycle (STC)** | Period: 10, Fast: 23, Slow: 50 | MACD'ye uygulanan çift stokastik filtre; 25 seviyesi altından yukarı kırılım şampiyonu (SOL %64+ WR, 2.79 PF). |
| **Zero-Lag MACD (ZLMACD)** | Fast: 12, Slow: 26, Signal: 9 | Standart MACD gecikmesini sıfırlayan ZLEMA yapısı; sıfır çizgisi kesişimi ve EMA20>EMA50 filtresi (OP 2.17 PF). |
| **WaveTrend (WT)** | n1: 10, n2: 21 | Aşırı satım osilatör dip teyidi (WT1 <= -40 iken yukarı kesişim). |
| **Bollinger & VWAP** | BB(20, 2.0), Hacim Ağırlıklı VWAP | Volatilite sıkışması sonrası alt banttan sekme veya hacimli VWAP yukarı kırılımı. |
| **Fisher Transform** | Period: 10 | Fiyat hareketlerini Gauss olasılık eğrisine çevirerek ekstrem dönüş noktalarını (-1.2 altı) tespit etme. |
| **Çift Osilatör Confluence** | KDJ J <= 18 + RSI <= 35 | İki farklı matematiksel modelin aynı anda aşırı satım teyidi vermesi. |

---

## 4. Strateji Kabul ve Eleme Kriterleri (Hard Guardrails)

Yeni bir stratejinin canlı Spot Monitor'e terfi edebilmesi için aşağıdaki kriterlerin **tamamını** sağlaması şarttır:

1. **Örneklem Yeterliliği:** Test penceresinde en az **20 tamamlanmış işlem** üretmelidir (aşırı seyrek sinyaller elenir).
2. **Kazanma Oranı (Win Rate):**
   - Trend takip stratejilerinde minimum **%55.0**
   - Dip dönüş (Mean-reversion) stratejilerinde minimum **%60.0**
3. **Profit Factor (Kâr Faktörü):**
   - Minimum **1.50** (Toplam brüt kazanç / Toplam brüt kayıp)
4. **Komisyon Sonrası Pozitif Net Kâr:**
   - Round-trip %0.08 spot kesintisi sonrası net getiri kesinlikle pozitif olmalıdır.
5. **Cross-Asset Dayanıklılığı (Genelleştirilebilirlik):**
   - Yalnızca tek bir coinde tesadüfen iyi sonuç verip diğerlerinde zarar ettiren stratejiler (overfitting) reddedilir. Strateji en az 2-3 farklı karakterdeki coinde (örn: SOL + OP + LINK) pozitif getiri sunmalıdır.

---

## 5. Canlı Sisteme Entegrasyon Protokolü

Bir strateji laboratuvardan onay aldığında şu 4 adımla sisteme aktarılır:

1. **Teknik Analiz Motoruna Ekleme:**
   - [`backend/app/technical_analysis.py`](file:///d:/PROJELLER/globall/backend/app/technical_analysis.py) dosyasına bağımsız, saf Python/NumPy tabanlı yardımcı fonksiyonu (`_stc`, `_zlmacd` vb.) ekleyin. Hata durumunda `None` dönmesini sağlayın.
2. **Spot Monitor Tarayıcısına Ekleme:**
   - [`backend/app/spot_monitor.py`](file:///d:/PROJELLER/globall/backend/app/spot_monitor.py) dosyasında `run_single_scan()` içine kuralı ve skorunu ekleyin.
   - Örnek:
     ```python
     elif stc_dip:
         matched = True
         strategy_code = "stc_cycle"
         strategy_label = "Schaff Trend Cycle (STC Dip)"
         score = 92.0
         note = f"STC 25 altından yukarı kırdı (STC={stc_val:.1f})"
     ```
3. **Kasa ve Portföy Bütünlüğü:**
   - 5.000 TL portföy simülatöründe 300 TL sabit işlem büyüklüğü, `open_symbols` kontrolü ile coin başına tek aktif pozisyon kuralını koruyun.
4. **Doğrulama ve Dağıtım:**
   - Python derleme kontrolü: `python -m py_compile backend/app/spot_monitor.py`
   - Git commit & push ile canlıya aktarın.

---

## 6. Raporlama Formatı

Her test çalıştırması sonrasında şu formatta çıktı sunulmalıdır:

```markdown
### 📊 Spot Strateji Laboratuvarı Sonuçları
- **Test Edilen Strateji:** [Strateji Adı ve Parametreleri]
- **Kapsam:** [Coin Listesi], Zaman Dilimi: [5m / 15m / 1h], Mum Adedi: 1000
- **En İyi Performans Gösterenler:**
  1. [COIN 1]: Win Rate %XX.X, Profit Factor X.XX, Net Kâr +%X.XX (XX işlem)
  2. [COIN 2]: Win Rate %XX.X, Profit Factor X.XX, Net Kâr +%X.XX (XX işlem)
- **Zayıf Kalanlar / Riskler:** [Elenilen durumlar ve drawdown notları]
- **Karar:** [TERFİ ET / YENİDEN TEST ET / REDDET]
```
