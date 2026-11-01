# Spot Coin Paper Trade — GitHub Araştırması ve Karlılık Artırma Raporu

**Tarih:** 2026-11-01
**Kapsam:** `backend/app/spot_monitor.py` (Spot Monitor paper trade simülatörü)
**Yöntem:** GitHub/AÇık kaynak trading repo'ları + akademik kanıt taraması, mevcut kodun ve lab çıktılarının bu bulgularla karşılaştırılması

---

## 0. Özet — En Kritik 5 Bulgu

| # | Bulgu | Nereden | Etki |
|:-:|:------|:--------|:-----|
| 1 | **Maliyet sessizce edge'i yiyor.** Mevcut stratejilerin kazanma oranları, gerçek Binance ücretiyle (0.20% round-trip) **basabas oranının altında/çok yakınında** | spreadatlas 31.407 setup testi, knacker65 30+ backtest | Yüksek |
| 2 | **"Yüksek WR = kar" yanılgısı.** Lab v5'te 1h COPPOCK_ZERO_TURN WR %25.8 kaybederken, 5m TURTLE_DONCHIAN55 WR %42 ile de kaybediyor; PF ve maliyet-sonrası net belirleyici | freqtradestrategy.com, spreadatlas | Yüksek |
| 3 | **Paper simülatör iyimser taraflı.** TP önce kontrol ediliyor, SL'de `exit_price = stop_p` yazılıyor (gap-down yok sayılıyor) → canlı sonuçlar backtest'ten kötü çıkacak | `spot_monitor.py:647-663` | Yüksek |
| 4 | **Rejim filtresi yok.** Lab v5'in **6 rejim hücresinin tamamı negatif**; VOL-yüksek hücreleri felaket (-586 net) | `outputs/spot_15m_regime_long.json` | Yüksek |
| 5 | **Yapay zeka katmanı dekoratif.** `octobot_score`, `vibe_score`, `qlib_score`, `jesse_rr`, `trap_warning` hesaplanıp saklanıyor ama **hiçbiri işlemi engellemiyor** | `spot_monitor.py:496-563` | Orta |

---

## 1. Mevcut Sistemin Durumu

### 1.1 Ne var?

- 18 TRY paritesi (`BTCTRY`…`INJTRY`), 3 zaman dilimi (5m/15m/1h)
- 9 aktif strateji, öncelik sırasıyla ilk eşleşen kazanır
- 5.000 TL sanal portföy, 500 TL sabit işlem, %0.04 tek yön komisyon
- `Dynamic Exit Architect`: kademeli kâr kilidi (BE @%1.10, ratchet @%1.50, trailing @%1.80)
- Açık pozisyon takibi 60 saniyede bir, pozisyon başına tek sembol kuralı

### 1.2 Lab çıktılarının gerçek tablosu (`spot_indicator_combos_lab_v5.json`)

46 strateji konfigürasyonundan **yalnızca 7'si pozitif net** üretti:

| TF | Strateji | İşlem | WR | PF | Net | H1/H2 | Değerlendirme |
|:--|:---------|------:|----:|---:|----:|:------|:--------------|
| 5m | `RVOL_TOD_SPIKE` | 27 | 63.0% | 2.30 | +11.92 | +10.60 / +1.32 | ✅ **Tek sağlam aday** |
| 1h | `VPROFILE_VAL_BOUNCE` | 109 | 44.0% | 1.32 | +41.22 | +45.04 / **-3.82** | ⚠️ İkinci yarıda kırıldı |
| 5m | `HA_TWO_GREEN_FLIP` | 351 | 45.9% | 1.23 | +36.48 | +29.88 / +6.57 | ⚠️ Maliyete çok yakın |
| 5m | `COPPOCK_ZERO_TURN` | 291 | 45.4% | 1.06 | +9.08 | +25.58 / **-16.46** | ❌ Kararsız |
| 5m | `VPROFILE_POC_RECLAIM` | 107 | 43.0% | 1.22 | +10.26 | +10.35 / -0.09 | ❌ Sıfırlandı |
| 5m | `TURTLE_DONCHIAN55` | 162 | 42.0% | 1.07 | +5.28 | +8.31 / -3.03 | ❌ Maliyet altı |
| 15m | `TSI_TRIX_CONFLUENCE` | 6 | 50.0% | 1.47 | +1.80 | -0.50 / +0.96 | ❌ Örneklem yok |

**Geri kalan 39 strateji net negatif.** En kötüler: `DONCHIAN_MID_CONT` (1h, 583 işlem, -239.57), `COPPOCK_ZERO_TURN` (1h, 414 işlem, -284.84).

### 1.3 Maliyet matematiği — asıl darboğaz

```
Basabas WR = SL_net / (TP_net + SL_net)
           = (SL + maliyet) / (TP - maliyet + SL + maliyet)
```

| TF | TP | SL | Maliyet %0.08 | Basabas WR | Maliyet %0.20 | Basabas WR |
|:--|---:|---:|:-------------|:-----------|:--------------|:-----------|
| 5m | 1.4 | 0.9 | Binance+BNB | **%42.6** | Kayıtlı kullanıcı | **%47.8** |
| 15m | 2.2 | 1.1 | | **%35.8** | | **%39.4** |
| 1h | 3.2 | 1.6 | | **%35.0** | | **%37.5** |

Pozitif net üreten 7 stratejinin %0.20 maliyette durumu:

```
5m  RVOL_TOD_SPIKE       WR=63.0%  BE=%47.8  OK
1h  VPROFILE_VAL_BOUNCE  WR=44.0%  BE=%37.5  OK
15m TSI_TRIX_CONFLUENCE  WR=50.0%  BE=%39.4  OK   (n=6)
5m  HA_TWO_GREEN_FLIP    WR=45.9%  BE=%47.8  ALTINDA
5m  COPPOCK_ZERO_TURN    WR=45.4%  BE=%47.8  ALTINDA
5m  VPROFILE_POC_RECLAIM WR=43.0%  BE=%47.8  ALTINDA
5m  TURTLE_DONCHIAN55    WR=42.0%  BE=%47.8  ALTINDA
```

> **Sonuç:** Kod `COMMISSION_RATE = 0.0004` (%0.08 round-trip, BNB indirimli) varsayıyor. Kullanıcı BNB indirimi kullanmıyorsa **%0.20** geçerli ve bu durumda 5m stratejilerinin **4'ü 5'i edge'siz** kalıyor. Tek sağlam kalan `RVOL_TOD_SPIKE`'ın da 27 işlem örneklemi istatistiksel olarak yetersiz.

`★ Insight ─────────────────────────────────────`
- Yüksek kazanma oranı, kâr anlamına gelmez — basabas WR **TP/SL oranına** bağlıdır. 5m'de TP1.4/SL0.9 asimetrisi basabas eşiğini %47.8'e çıkarıyor; aynı strateji 15m'de (TP2.2/SL1.1) %39.4 eşiğiyle kârlı olabilir.
- **Frekans = maliyet çarpanı.** 5m stratejileri 1h'den ~12 kat daha fazla işlem yapıyor, yani komisyon yükü 12 kat. spreadatlas verisi bunu net gösteriyor: ≤10dk barlarda setup'ların **yalnızca %6'sı** maliyet sonrası kârlı, 4h barlarda ise %81'i.
- Bu, "daha çok sinyal avlamak" yerine "daha az ama daha kaliteli işlem" tasarımına işaret ediyor.
`─────────────────────────────────────────────────`

---

## 2. GitHub Araştırması — Repo Repo Ne Yaptılar, Neye Yaradı

### 2.1 EN DEĞERLİ BULGU: Negatif Sonuç Raporları

Bu kategori en değerli olanı, çünkü **neyin çalışmadığını kanıtlıyor** ve aynı hataları tekrarlamayı önlüyor.

#### `iolufemi/crypto-trend-research` — 538 milyon mumluk tarafsız çalışma ⭐ EN ÖNEMLİ

**Ne yaptılar:** 219 sembol, 538.752.184 adet 1-dakika barı (5.6 yıl), sızıntı-kontrollü walk-forward. Klasik ML yaklaşımını (18 ay, macro-F1 ≈ 0.70) bırakıp long-only spot market timing'e geçtiler. ML yön tahmini, cross-sectional rotasyon, ML rejim tespiti, istatistiksel jump modeli, çoklu-zaman dilimi kapıları — hepsini test ettiler.

**Neye vardılar:**

| Strateji (BTC, tam tarih) | CAGR | Sharpe | maxDD | Calmar |
|:--------------------------|-----:|-------:|------:|-------:|
| Buy & hold | 13.7% | 0.51 | -77% | 0.18 |
| 1h SMA200 long/flat | -19.5% | **-0.43** | -76% | -0.26 |
| **4h SMA200 long/flat** | **30.9%** | **0.96** | **-35%** | **0.88** |
| 1d SMA200 long/flat | 24.1% | 0.82 | -32% | 0.76 |

**Sonuç cümlesi:** *"Bir satırlık trend kuralı 4h barlarda buy-and-hold'u out-of-sample yener (BTC walk-forward Sharpe 1.15 vs 0.92; maxDD -30% vs -50%). Ve ML yön tahmini, cross-sectional rotasyon, ML rejim tespiti, jump modeli, çoklu-zaman dilimi giriş kapılarının **hiçbiri** bunu iyileştirmez. Neredeyse her sofistike katman risk-ayarlı getiriyi **çıkarır**."*

**İstisna (iki pozitif):**
- 1h MA-eğim filtresi → 219 sembolün **%68.5'inde** iyileşme
- Üstüne 5m MACD-boğa teyidi → **%74'ünde** iyileşme (BTC Sharpe 1.09→1.15, daha sığ drawdown)

**Bizim için:** 5m/15m scalp stratejisi kurmak, bu çalışmanın ölçtüğü yolda. Kanıt diyor ki: **daha yüksek zaman dilimi + daha az işlem = daha iyi risk-ayarlı getiri.**

---

#### `knacker65/v5-crypto-scalper` — 30+ backtest ile dürüst öz-eleştiri

**Ne yaptılar:** Binance spot için üretim kalitesinde bir bot mimarisi — hub-and-spoke, 4 paralel strateji thread'i, LightGBM meta-labeling (22 özellik), shadow tracking (reddedilen sinyalleri de ileri yürütüp AI'ı yanlı veriyle eğitmemek), vektörize walk-forward backtest. 4 zaman diliminde 30+ backtest koştular.

**Neye vardılar:**

| Strateji Ailesi | 5m (90g, 11 sembol) | 1h (365g) | 4h (730g) |
|:----------------|:--------------------|:----------|:----------|
| MeanReversion | **-$0.18/işlem** | -$0.15 | -$0.31 |
| Momentum | **-$0.20/işlem** | -$0.18 | -$0.07 |
| Breakout | -$0.18/işlem | değişken | küçük örneklem |

**Meta-labeling deneyi (asıl ders):**

| Değerlendirme | Sonuç |
|:--------------|:------|
| In-sample (veri sızıntısı vardı) | +0.93% — **sahte** |
| Walk-forward (doğru: ilk %70'te eğit, son %30'da test) | **-0.25% AI kapılı vs -0.13% baz** |
| Holdout korelasyon `corr(tahmin, gerçek)` | **-0.008** (istatistiksel sıfır) |

**Verdict:** *"2026'da retail spot kripto için: teknik göstergeler arbitrajlanmış. Bu repodaki mimari mükemmel. İçindeki stratejiler değil."*

**Sadece pozitif kalan:** `PairsRotation` (varlığın BTC'ye karşı log-oranı 30g ortalamasının 2σ altındaysa al) — günlük barlarda **+$2.24/işlem, 3 yılda 35 işlem** ✅ walk-forward doğrulanmış.

---

#### `RamavatMit/Binance` — ML ile dürüst holdout

**Ne yaptılar:** Triple-barrier etiketleme (TP vs SL vs zaman limiti, ücret+slipaj net) + walk-forward gradient boosting, BTC/ETH/BNB/SOL. Son 12 ay **hiçbir seçimde kullanılmayan holdout**. ~120 setup denediler.

| Dönem | İşlem | WR | PF | Getiri | maxDD |
|:------|------:|----:|---:|-------:|------:|
| Validation (~2 yıl) | 256 | 74.6% | 1.31 | +8.3% | 4.7% |
| **Holdout (son 12 ay, hiç görülmemiş)** | **21** | 66.7% | 1.92 | +2.0% | 1.6% |

**Kendi uyarıları:** *"21 holdout işlemi hiçbir şeyi kanıtlamaz. ~120 setup'ın en iyisi bu, yani bir kısmı şans. Kazançlar kayıpların yarısı (R:R 0.5). Canlı WR %67'nin altına düşerse para kaybeder."*

Ayrıca çarpıcı bir satır: *"Model olmadan aynı TP/SL zamanın %65'ini kazanır ve **%99.8 kaybeder** (yüksek WR ≠ kâr)."*

---

#### `spreadatlas.com` — 31.407 setup'lık maliyet haritası

**Ne yaptılar:** 16 klasik gösterge, 1 dakikadan 4 saate barlar, Upbit KRW piyasası, %0.05 ücret + 1 tick slipaj her işlemde. Tek bir setup = bir gösterge kuralı + ayarları, bazen filtre/çıkış kuralı.

**Neye vardılar:**

- **≤10 dakika barlarda setup'ların en fazla %6'sı** maliyet sonrası kârlı
- **4 saatlik barlarda %81'i** kârlı, 1.267'si iki-dönem testini geçti
- *"Aşırı satım dip alımları 4 saatlik işlemlerin yarısından fazlasını kazandı ve çoğu yine de para kaybetti. Kırılım kuralları işlemlerin yaklaşık üçte birini kazandı ve para kazandı, çünkü kazançları kayıplarından birkaç kat büyüktü."*
- **En dürüst satır:** *"Canlıda çalıştırdığımız en iyi kural replay'de yılda +92% yaptı. Gerçek sunucuda, kağıt parayla, iki hafta boyunca her kurala uydu ve -3.93% kaybetti."*

---

#### `Kureshi25/cryptobot` — frekansın aritmetiği

**Ne yaptılar:** Freqtrade bot + web dashboard + risk devre kesiciler. Paper modda. Dört stratejiyi walk-forward'dan geçirdiler.

**En öğretici deney — HighFreqDemo:**

| Metrik | Değer |
|:-------|:------|
| İşlem | 13 günde 15.949 |
| Kazanma oranı | **%67** |
| Medyan tutma | 2.0 dakika |
| Piyasa (dönem) | +%27.8 |
| **Sonuç** | **$1.000 → $23.97 (-%97.6)** |

*"Üç işlemden ikisini kazandı ve hesabın %97.6'sını kaybetti. Mekanizma aritmetik, kötü şans değil. Binance her yönde %0.045 taker alır — round-trip %0.09. 3x kaldıraçta bu kendi paranızın %0.27'si. Kazançlar ROI zamanlayıcısıyla %0.3'te sınırlı, yani kazanan işlem neredeyse hiçbir şey getirmezken her işlem tam ücreti ödüyor."*

**Walk-forward sonuçları:**

| Strateji | Param | OOS ortalama | Pencereler kârlı | Parametre salınımı |
|:---------|------:|-------------:|:-----------------|:-------------------|
| Spot, long only | 3 | -3.8% | 3/4 | 3.93× |
| Futures, long/short | 3 | +4.2% | 2/4 | 1.33× |
| Adaptive, long/short | 7 | **-22.3%** | 0/4 | 3.44× |
| Adaptive, long only | 7 | +5.0% | 3/4 | 2.15× |

*"Yedi parametreli adaptive bot burada inşa edilenlerin en yüksek in-sample getirisine (+%78.7) ve en düşük out-of-sample'ına (-%22.3) sahipti. Ekstra parametreler backtest performansını geri satın aldı ve bedelini gerçekte ödedi."*

---

### 2.2 Kanıtlanmış Pozitif Edge Kaynakları

#### `jicheolha/crypto-trading-bot` (Keltrader) — Sıkışma kırılımı

**Ne yaptılar:** Düşük volatilite konsolidasyonu tespit → volatilite genişlerken momentum kırılımı. Bollinger bantları Keltner kanallarının **içine** sıkışınca, hacim eşiği üstünde squeeze açılımı, RSI aşırı-alım/satım reddi. 6 yıl veri, Bayesian hiperparametre optimizasyonu, Monte Carlo permütasyon testi.

| Metrik | Değer |
|:-------|:------|
| İşlem | 512 |
| Kazanma oranı | **%67.2** |
| Profit Factor | 1.94 |
| Sharpe | **2.27** |
| maxDD | %27.4 |
| Getiri (komisyon+slipaj sonrası) | **+%1689.1** |

**Bizim için:** Mevcut `squeeze_breakout` (BB-KC sıkışma) stratejimiz **aynı aileden** ve sistemde birinci öncelikli (score 98.0). Ancak TPSL optimizer sonucu bunun canlı parametrelerinin yanlış olduğunu söylüyor — bkz. Bölüm 3.1.

---

#### `davidzr/freqtrade-strategies` — NotAnotherSMAOffsetStrategyHO

**Ne yaptılar:** Freqle Strategy League'de **strateji #1** (skor 94.9). 2022-2024, 33 parite, `+117%` getiri (piyasa +111%), CAGR +29.4%, maxDD **-3.51%**, WR **%80.7%**, Sharpe 6.373, PF 3.24, 813 işlem.

**Giriş mantığı (EWO = Elliott Wave Oscillator):**
```python
buy = (
    (rsi_fast < 35) &                                        # hızlı RSI aşırı satım
    (close < ma_buy_n * low_offset) &                        # EMA altına sapma (0.966)
    (EWO > ewo_high) &                                       # boğa dalgası (3.422)
    (rsi < rsi_buy) &                                        # ana RSI (52)
    (close < ma_sell_n * high_offset)                        # satış EMA'sının altında
)
# İkinci giriş varyantı: low_offset_2=0.951, ewo_high_2=-4.58, rsi<25
# Üçüncü: EWO < ewo_low (-8.562) — derin dip
```

**Çıkış/risk:**
```python
minimal_roi = {"0": 0.289, "25": 0.105, "80": 0.038, "140": 0}  # zamanla azalan ROI
stoploss = -0.35                                                 # GENİŞ stop
trailing_stop = True
trailing_stop_positive = 0.005                                   # %0.5 takip
trailing_stop_positive_offset = 0.03                             # %3'te devreye gir
trailing_only_offset_is_reached = True
```

**Çıkış filtresi (`confirm_trade_exit`):** Satış sinyalinde son mumu kontrol eder — `hma_50 * 1.149 > ema_100` VE `close < ema_100 * 0.951` ise satışı **iptal eder**.

> **★ Kritik içgörü:** WR %80.7 ve maxDD %3.51 **geniş stoploss (-0.35) + kademeli ROI + %0.5 trailing** kombinasyonundan geliyor. Sabit TP/SL değil. Bizim simülatör "TP'ye ulaş veya SL'ye in" ikili modeli kullanıyor — bu, kazanan işlemleri erken keser.

**Ayrıca dikkat:** Slippage koruması var — `slippage / candle.close` eşiği geçilirse işlem ertelenir (retry).

---

#### `TheoBrigitte/freqtrade` — E0V1E (en popüler topluluk stratejisi)

**Ne yaptılar:** League'de #3 (skor 94.8). +%90.7 getiri, maxDD -%3.39, WR %80.1, PF 7.37, 346 işlem.

**Giriş:**
```python
buy_1 = (
    (rsi_slow < rsi_slow.shift(1)) &        # yavaş RSI düşüyor (momentum zayıflıyor)
    (rsi_fast < 45) &                       # hızlı RSI aşırı satım
    (rsi > 35) &                            # ama ana RSI 35 üstü (dip değil!)
    (close < sma_15 * 0.961) &              # SMA15'in %3.9 altı
    (cti < -0.58)                           # Correlation Trend Indicator negatif
)
is_ewo = (
    (rsi_fast < 45) & (close < ema_8 * 0.942) &
    (EWO > -5.585) & (close < ema_16 * 1.084) & (rsi < 35) &
    dataframe['btc_usdt_dump_5m']            # ← BTC 5m dump koşulu!
)
```

**Çıkış (`custom_exit` — asıl yenilik):** `deadfish_exit` — ölü balık çıkışı:

```python
# Kâr var ama hareket durdu → çık
if current_profit > 0:
    if current_candle["fastk"] > sell_fastx:      # 75 — stokastik aşırı alım
        return "fastk_profit_sell"
if current_candle["cci"] > sell_cci:              # 90 — CCI aşırı alım
    return "cci_profit_sell"
# 2 saat geçti ve hâlâ kârda → çık
if current_time - timedelta(hours=2) > trade.open_date_utc:
    if current_profit > 0:
        return "profit_sell_in_2h"
# Zararda ve CCI çok yüksek → çık
if current_profit > sell_loss_cci_profit:          # -0.04
    if current_candle["cci"] > sell_loss_cci:      # 148
        return "cci_loss_sell"
```

**Ve en önemli satır:**
```python
minimal_roi = {"0": 10}     # ROI kapalı
stoploss = -0.99            # stoploss KAPALI
use_custom_stoploss = True  # ← tüm çıkış custom_exit'te
```

> **★ Kritik içgörü:** E0V1E'nin stoploss'u **-99% (etkin olarak kapalı)**. Tüm çıkış kararı `custom_exit`'te: gösterge-tabanlı (`fastk`, `cci`) + zaman-tabanlı (2 saat). WR %80 ve PF 7.37 sabit TP/SL'den değil, **"hareket durursa çık"** felsefesinden geliyor. Bizim `Dynamic Exit Architect` bunun ilkel bir versiyonu — ama gösterge sinyali kullanmıyor, sadece fiyat kârına bakıyor.
>
> **Ayrıca:** `btc_usdt_dump_5m` filtresi — **BTC dump koşulu girişin parçası**. Yani altcoin sinyali tek başına yeterli değil; BTC'nin düşmüş olması gerekiyor (dip alımı).

---

#### `btschwertfeger/infinity-grid` — Grid + cDCA

**Ne yaptılar:** Kripto/hisse/derivatifler için grid trading. `GridHODL`, `GridSell`, `SWING`, `cDCA` stratejileri. Kraken Spot, PostgreSQL/SQLite zorunlu.

**Mantık:**
- `GridHODL`: Mevcut fiyatın altına n adet alım, %4 aralıklarla. Örnek BTC $50.000 → ilk alım $48.000, ikincisi $46.080. Alım dolunca %4 üstüne satış emri. Sabit quote hacmi ($100).
- `cDCA`: Zaman-tabanlı değil **fiyat-tabanlı** aralıklar — her %4 hareketde al. **Satış emri yok**, saf birikim.
- `Adaptive`: Fiyat yükselirse alım emirlerini de yukarı kaydırır.

**Neye yaradı:** Yatay/volatil piyasada tekrarlayan küçük kazançlar. Birikim + sonradan fiyat artışı. **Trend piyasasında etkisiz.**

---

#### `Aihansu/smart-grid-bot` — EMA dinamik alım bölgeleri

**Ne yaptılar:** Binance grid bot + DCA + trailing stop + EMA-tabanlı dinamik alım bölgeleri + Telegram kontrol. Paper trading modu var.

| Bölge | EMA Mesafesi | Çarpan | Anlam |
|:------|:-------------|-------:|:------|
| Pahalı | > +%5 | 0x | EMA çok üstü, alma |
| EMA üstü | %0 – +%5 | 0.5x | Pahalı, az al |
| Zayıf dip | %0 – -%1.5 | 0.75x | Küçük dip, sermaye koru |
| Normal dip | -%1.5 – -%3 | 1.0x | Standart |
| Güçlü dip | -%3 – -%5 | 1.5x | Derin dip, agresif al |
| Sert dur | < -%5 | 0x | Çöküş koruması |

**Trailing:** +%1.2'de aktive, -%0.3 geri çekilmede sat.

**Bizim için:** Bu EMA-mesafesi → pozisyon çarpanı haritası, **sabit 500 TL işlem** yerine uygulanabilir bir boyutlandırma şeması. Mevcut kodda tüm işlemler aynı büyüklükte.

---

### 2.3 Meta-Labeling ve Triple Barrier (López de Prado)

#### `hudson-and-thames/mlfinlab` — referans implementasyon

**Ne yaptılar:** `Advances in Financial Machine Learning` kitabının tüm etiketleme altyapısı:
- `apply_pt_sl_on_t1` (Snippet 3.2, s.45): hangi bariyer ilk önce vuruldu
- `add_vertical_barrier` (Snippet 3.4, s.49): zaman bariyeri
- `get_events` / `get_bins` (Snippet 3.6-3.7, s.50-51): meta-labeling
- `get_av_uniqueness_from_triple_barrier`: örneklem ağırlığı (çakışan işlemler)
- `cusum_filter`: olay örnekleme

**İki mod:**
- Case 1 (`side` yok): `bin ∈ {-1, 0, 1}` — fiyat hareketiyle etiketle
- Case 2 (`side` var): `bin ∈ {0, 1}` — **meta-labeling**, PnL ile etiketle

**Neye yaradı:** İkincil model ("bu sinyale güvenmeli miyim?") birincil modelin yön tahminini filtreliyor. Bet boyutlandırma olasılıktan türetiliyor.

#### `ArmaanSharmaProjects/Meta-Labeling`

**Ne yaptılar:** Dollar bar + triple barrier + Random Forest, E-mini S&P 1 dakika verisi. Bariyerler: PT `+1σ`, SL `-2σ`, dikey 1 gün. Güven eşiği %75.

#### `rayhantithokharisma/bbca-tbm-meta`

**İki TBM konfigürasyonu:**
- SWING: max 5 gün, bariyerler `±1.5 × ATR(20)` — **dinamik**
- POSITION: max 21 gün, sabit `±%5`

> **★ Bizim için kritik:** SWING modu **ATR-tabanlı dinamik bariyer** kullanıyor. Bizim kod `tp_pct`/`sl_pct`'yi zaman dilimine göre sabit tutuyor (`5m: 1.4/0.9`, `15m: 2.2/1.1`, `1h: 3.2/1.6`) — **BTC ile PEPE aynı yüzdeyi alıyor**. ATR tabanlı bariyer bunu çözer.

#### `mchiuminatto/triple_barrier` — pip paketi

Trade labeler: SL, TP, dinamik bariyer, zaman bariyeri. Hangisi önce vurulursa kapanış nedeni o. `dynamic_exit` parametresi bir koşul fonksiyonu alır.

---

### 2.4 Rejim Tespiti

#### `DaruFinance/strategy-regime` — BIC ile K seçimi ⭐ UYGULANABİLİR

**Ne yaptılar:** Bar başına `f_t = [logret_t, vol_t, trend_t]` üzerine Gaussian HMM, Viterbi ile rejim dizisi, BIC ile K seçimi. Diagonal kovaryans (vol ve ATR neredeyse doğrusal bağımlı olduğunda tam kovaryans tekil matris hatası veriyor).

**Olağanüstü sonuç:** **10 kripto varlığının 10'unda da BIC oybirliğiyle K=4 seçti.** 30 dakikalık veride bu kripto piyasa yapısının neredeyse evrensel bir özelliği.

**BTC 30m, K=4 rejimleri (9 yıl, 146.120 bar):**

| Durum | logret | vol | trend | Pay | Kalma olasılığı | Etiket |
|:-----:|-------:|----:|------:|----:|----------------:|:-------|
| 0 | +0.06 | -0.08 | +0.69 | 33% | 0.969 | **Boğa trend** |
| 1 | +0.00 | -0.70 | +0.01 | 25% | 0.985 | **Sakin/range** |
| 2 | -0.05 | -0.12 | -0.56 | 24% | 0.970 | **Ayı trend** |
| 3 | -0.01 | +1.53 | -0.17 | 18% | 0.977 | **Yüksek vol** |

**Kalma olasılıkları ≥0.97** → rejimler yapışkan, etiket kullanılabilir bir koşullama değişkeni. Ömür: 30dk barda **16-38 saat**.

*"Bir strateji trend-up'ta +1.5 Sharpe, yüksek-vol'da -0.8 Sharpe ise — bu, her rejimde +0.3 olan bir stratejiyle aynı nesne değil, ikisinin harmanlanmış Sharpe'ı aynı olsa bile."*

**Sizing için:** Uygunsuz rejimde maruziyeti `P(z_t ∈ uygun | x_1:t)` ile ölçekle (canlı için **filtreleme**, smoothing değil). Zincir kendinden eminken yüklen; entropi yükselince risk azalt.

#### `farhad-nazari1990/crypto-regime-detection`

**Ne yaptılar:** HMM + GMM + Change Point Detection üçlü karşılaştırma, BTC.

| Rejim | Gün | Zaman % | Günlük getiri | Volatilite | Sharpe | Tip |
|:------|----:|--------:|--------------:|-----------:|-------:|:----|
| State 0 | 575 | 14.1% | **-2.37%** | 6.07% | **-7.46** | 🔴 Crash/Panik |
| State 1 | 696 | 17.1% | **+2.53%** | 4.40% | **+11.01** | 🟢 Boğa rally |
| State 2 | 1.563 | 38.4% | +0.30% | 1.78% | +3.26 | 🟡 Stabil büyüme |
| State 3 | 1.239 | 30.4% | -0.06% | 1.63% | -0.68 | ⚪ Konsolidasyon |

**HMM vs GMM:** HMM 762 geçiş vs GMM 1.008 → HMM daha stabil, ortalama süre 5.3 gün vs 4.0.

#### `Yosri-Ben-Halima/hmm-crypto-trading-model`

**Ne yaptılar:** HMM rejim + Monte Carlo sağlamlık testi.

| Metrik | HMM Stratejisi | Buy & Hold |
|:-------|:---------------|:-----------|
| Yıllık Sharpe | **1.71** | 1.02 |
| P&L | **+51%** | +23% |
| maxDD | **-21%** | -28% |

#### `JPeetz/Hidden_Markov_Model_Strategy_Tester` — 8-puan teyit sistemi

**HMM:** 7 gizli durumlu Gaussian HMM, 3 özellik: log getiri, `(H-L)/C` normalize range, hacim volatilitesi. 7 durum → Boğa/Ayı/Yatay olarak sınıflandırma.

**8 teyit koşulu (işlem için N tanesi gerekli):**
1. RSI eşik altı 2. Momentum min üstü 3. Volatilite max altı 4. ADX min üstü (trend var) 5. Hacim > SMA20 6. Fiyat > EMA50 7. Fiyat > EMA200 8. MACD > Signal

**Giriş:** Boğa rejimi **VE** ≥N teyit **VE** bekleme süresi dolmuş.

---

### 2.5 Pozisyon Boyutlandırma ve Risk

#### `HasibVortex369/riskkit` — kompozit risk katmanı ⭐ EN KAPSAMLI

**Altı bileşen:**

| Bileşen | Ne yapıyor |
|:--------|:-----------|
| `PositionSizer` | Volatilite-ayarlı fixed-fractional + **yarım-Kelly tavanı** + kayıp serisi/drawdown için azaltma merdiveni + sert notional tavanı |
| `DrawdownManager` | High-water-mark drawdown → kademe merdiveni (boyut kes → bar yükselt → durdur), toparlanma rampası, haftalık zarar molası |
| `StopEngine` | Pozisyon başına **stop yığını**: başlangıç, başabas, ATR/EMA trailing, chandelier, yapı (swing), PSAR, zaman, volatilite. **En sıkısı kazanır; stoplar yalnızca yakınlaşır** |
| `CorrelationGuard` | Korelasyon grubu başına en fazla bir açık pozisyon (statik veya dinamik matris) |
| `SessionManager` | Günlük işlem/zarar tavanı, kâr-alma durdurması, min aralık, kayıp serisi sonrası artan bekleme (cooldown), tilt tespiti |
| `PreTradeValidator` | Kompozit son kapı — her kuralı çalıştırır, biri bile düşerse vetolar, hangilerinin geçtiğini/düştüğünü döndürür |

**Kullanım:**
```python
sizer = PositionSizer(
    base_risk_pct=1.0,      # işlem başına %1 risk, düzeltmelerden önce
    max_risk_pct=1.5,
    max_notional_pct=4.0,   # pozisyon özkaynağın %4'ünü geçemez
)
result = sizer.size(SizingInputs(
    equity=10_000, entry_price=100.0, stop_price=98.0,
    atr=2.5, atr_baseline=2.0,     # ← çalkantılıysa riski kıs
    consecutive_losses=2,           # ← azaltma merdiveni
    drawdown_pct=4.0,
))
# result.multipliers_applied → hangi çarpanların ateşlediği (denetlenebilir)
```

**Portföy seviyesi:** toplam açık notional, toplam **heat** (stop'ta risk), sektör/varlık sınıfı maruziyeti. Ayrıca: `volatility_target_size`, `inverse_vol_weights`, `kelly_fraction`, `value_at_risk`, `conditional_value_at_risk`.

#### `leionion/dynamic-position-sizer-atr-calculator`

**Çekirdek formül:**
```python
risk_amount = account_balance * risk_percent
stop_distance = atr * atr_multiplier
risk_per_unit = stop_distance * tick_value
raw_units = risk_amount / risk_per_unit
lot_size = round_to_step(raw_units / contract_size, lot_step)
```

Kontrat-farkında lot boyutlandırma, broker-güvenli yuvarlama (aşağı/en yakın/yukarı), min/max lot kısıtları, portföy seviyesi risk tavanı.

#### `zachisit/july-backtester` PR #78 — 4 boyutlandırma yöntemi

| Yöntem | Formül |
|:-------|:-------|
| Fixed | `shares = (equity * allocation_pct) / price` |
| **Kelly** | `kelly_f = (p*b - q) / b; shares = (equity * kelly_f * kelly_fraction) / price` — %25 fraksiyonel Kelly |
| **Vol Parity** | `shares = (equity * target_risk) / (price * atr_pct)` — düşük vol → büyük pozisyon |
| **Risk Parity** | `shares = (equity * target_risk) / (price * stop_distance_pct)` — her pozisyon aynı $ riski |

Portföy heat kontrolü: `max_portfolio_heat = 0.10` (toplam %10 risk tavanı).

**PR'daki bug düzeltmeleri (bizim için öğretici):**
- 🔴 **Look-ahead bias**: `symbol_data=df.loc[:date]` ile dilimleme → ATR şu anki bardan okunmalı, tüm veri setinin son barından değil
- 🔴 **Kelly her zaman fixed**: ≥10 işlem sonrası rolling istatistik hesaplanmalı, öncesinde fixed'e düş
- 🔴 **risk_parity stop'u yok sayıyor**: `stop_distance_pct` stop config'inden türetilmeli (ATR stop → `(ATR * mult) / close`)

#### `ccollins80/crypto-stat-arb` — çarpımsal alfa + vol hedefleme

**Ne yaptılar:** 12 likit kripto, saatlik barlar, ~2.6 yıl, 7bps maliyet, BTC'ye göre residualizasyon.

| Strateji | Net Sharpe | Yıllık getiri | Yıllık vol | Yıllık devir | Maliyet/yıl |
|:---------|-----------:|--------------:|-----------:|-------------:|------------:|
| **Reversal** | **1.77** | 0.366 | 0.207 | ~89 | ~0.062 |
| **Momentum** | **1.32** | 0.291 | 0.222 | ~18 | ~0.013 |
| **Mixed (50/50)** | **2.18** | 0.329 | 0.151 | – | – |
| Mixed (Statik opt.) | 2.21 | 0.335 | 0.151 | – | – |
| **Mixed (Equal-Vol)** | **2.52** | 0.401 | 0.159 | – | – |

*"En iyi OOS performansçı; maliyet-dayanıklı (20bps'te Sharpe ≈ 2.1)."*

**Reversal en iyi config:** `k=4` (4-bar lookback), `band=2.5`, `beta_win=168` (~1 hafta), `every=24` (günlük rebalans), `vol_win=24`.

**Momentum:** `k≈336-500` (uzun lookback), yavaş rebalans → düşük maliyet.

> **★ Kritik içgörü:** Reversal (yüksek devir, kısa lookback) Sharpe 1.77 veriyor ama maliyet drag'i 0.062/yıl. Momentum (düşük devir) 1.32 Sharpe ama maliyet 0.013. **İkisinin birleşimi 2.52 Sharpe** — tek tek en iyisinden çok daha yüksek. Çünkü ortalama korelasyon ~0.11.

---

### 2.6 Order Flow / Mikroyapı (yüksek frekans — bizim için sınırlı değer)

#### `tejeshvenkat/microstructure-alpha`

**Ne yaptılar:** Bilinen ground-truth'lu limit order book simülatörü + Cont-Kukanov-Stoikov OFI tanımı + leakage-free `signal-backtester`.

| | Latent sinyal | Sinyal-kapalı kontrol |
|:--|:--|:--|
| OFI fiyat-etkisi β (R²) | 0.011 (**0.159**) | ≈0 (0.002) |
| OFI → 10-tick rank IC | **+0.728** | +0.066 |
| OFI strateji Sharpe | **+7.40** | +0.65 |

*"R² ~0.16 sonraki-tick hareketleri için ampirik OFI literatürüyle uyumlu."*

#### `ilibili-AI/AlphaLab` — EN DÜRÜST MİKROYAPI ÇALIŞMASI

**Ne yaptılar:** BTCUSDT sonraki 1 saniye mid-fiyat hareketi tahmini. Kronolojik doğrulama, ön-kayıtlı holdout protokolü.

**Sonuç:** Multi-feature model ön-kayıtlı holdout kriterlerinin **tamamını** geçti, OFI-only bazından 3/3 günde hem AUC hem AP'de üstün (ROC AUC 0.7262 vs 0.6877).

**Ama sonra şunu ölçtüler — execution-aware analiz:**
```
sinyal t'de gözlenir → 1 saniye gecikme → bid/ask geçerek gir
→ 1 saniye tut → bid/ask geçerek çık
```

| OFI eşiği | Basabas ek round-trip maliyeti |
|:----------|:-------------------------------|
| D8+ | 0.062 bps |
| D9+ | 0.070 bps |
| D10 | 0.086 bps |

*"Ek 0.10 bps round-trip maliyette, test edilen tüm eşikler negatif ortalama net beklenti üretti. Bu nedenle: **AlphaLab mevcut sinyalin kârlı canlı trading stratejisi oluşturduğu iddiasında bulunmuyor.** İstatistiksel alfa ile uygulanabilir alfa arasındaki ayrım kasıtlıdır."*

#### `tsuithomas/crypto_research_order_book_imbalance`

XGBoost regresör, 5 dakika ileri log-getiri tahmini. **OBI ~%45 özellik önemi** — hacim/volatilite metriklerinden baskın.

*"Agresif market-order çalıştırma (spread geçme, 4-8 bps taker ücreti) negatif net PnL ile sonuçlandı... Çalıştırma mantığını pasif maker emirlerine ve sıkı 15 bps tahmin eşiğine kalibre ederek strateji pozitif absolute getiriye (+%3.21) döndü — şiddetli bir piyasa düşüşünde (-%12.76)."*

#### `OliverNyx/crypto-liquidity-sniper`

Likidite süpürme + order-book dengesizliği, BTC/ETH/seçili altcoin.

| Metrik | Sonuç |
|:-------|:------|
| Kazanma oranı | %58.2 |
| Profit Factor | 1.42 |
| maxDD | -%12.4 |
| Sharpe (günlük) | 1.18 |

---

### 2.7 Çoklu-Strateji Tahsisi

#### `angel4angelov-glitch/Multi-Strategy-Allocation-Engine`

**Ne yaptılar:** Strateji getiri akışları evrenini alıp temizle → metrik hesapla → notlandır → korelasyon kısıtlı portföy seç → 7 tahsis yönteminden biriyle optimize et. **Sert %10 tek-pozisyon tavanı.**

**7 yöntem:** Equal Weight, Inverse Volatility, Max Sharpe, Min Variance, Min CVaR, Max Sortino, HRP (López de Prado hiyerarşik risk paritesi).

**Hepsinin ortak paydası:** Ledoit-Wolf büzülme kovaryansı, %10 pozisyon tavanı (iteratif kırp-yeniden dağıt), devir cezası (λ=0.1), **optimizasyon başarısız olursa equal-weight'e geri dön**.

**Notlandırma:** Percentile derecelendirme (top %20 STRONG, top %50 MODERATE) + **mutlak kalite kapıları** (Sharpe negatifse asla STRONG olamaz) + adaptive seçim kapıları + korelasyon filtresi + **trend cezası** (rolling Sharpe düşen stratejiler %50 ceza).

#### `LORD-ZYTHOZ/regime-aware-strategy-allocator`

**Çekirdek çözüm — Quadratic Program:**
```
b* = argmax_b [ νᵀb − (γ/2) bᵀΣb − λ_turn ‖b − b_prev‖₁ ]

kısıt:  1ᵀb ≤ 1   (tam yatırım)
        b ≥ 0     (açığa satış yok)
```
Burada `ν = η̂ − λ_U · U − λ_C · Ĉ` = strateji başına fayda skoru:
- `η̂` — tahmini edge (tahmin × sinyal kalitesi)
- `U` — belirsizlik cezası
- `Ĉ` — işlem maliyeti tahmini

**Üç rejim sinyali:** volatilite, korelasyon genişliği, trend. `adaptive_gamma` rejim değişince risk iştahını otomatik yeniden kalibre eder.

**Risk kapıları:** `OK` (çözülen bütçeler) | `DE_RISK` (tüm bütçeleri kıs, nakit tamponu artır) | `KILL` (tüm pozisyonları sıfırla, tam nakit).

#### `matiasjarnal/crypto-momentum-strategy` — BTC rejim koşullaması

| Bileşen | Detay |
|:--------|:------|
| Evren | 35 likit kripto |
| Sinyal | Çok-ufuklu momentum (10/20/60 gün), in-sample seçilen top-3 spec |
| **Rejim** | **BTC 200-gün MA: boğada tam maruziyet (1.0×) momentum-tilt; ayıda %50 maruziyet, düşük-vol tilt, top-K %30 kes** |
| Ağırlıklandırma | Softmax normalizasyon + ters-vol ağırlık (30 gün) |
| Vol hedefleme | Portföy %20 yıllık vol hedefi, max 3× kaldıraç |
| Maliyet | 20 bps düz/işlem (7 bps komisyon + 13 bps slipaj) |

**Sinyal:** Cross-sectional z-skoru, ±3σ winsorize. **Devir azaltma:** ağırlıkların üstel yumuşatması (α=0.25).

#### `s-brez/trading-server`

Çok-varlık, çok-strateji, olay-güdümlü platform. **%X sermaye tahsisi strateji başına, %Y maruziyet.** Telegram üzerinden işlem onayı. IPFS + Ethereum/BSC üzerine sinyal yayınlayarak **win rate'i ampirik olarak kanıtlama** — blokzincir-tabanlı strateji denetimi.

#### `jp-moregain/apex-trading-bot`

7 strateji, piyasa koşuluna göre otomatik seçim. Dinamik tahsis her 30 dakikada. Strateji başına P&L takibi. **~20 işlem/gün için optimize** (ücret farkındalığı).

---

### 2.8 Pine Script Göstergeleri ve Formülleri

#### Squeeze Momentum (LazyBear) — John Carter'ın TTM Squeeze türevi

Bizim `_bb_kc_squeeze` ile aynı aile. **Tam formül:**

```pinescript
length = 20, mult = 2.0        // BB
lengthKC = 20, multKC = 1.5    // Keltner

// Bollinger
basis = sma(close, length)
dev = multKC * stdev(close, length)
upperBB = basis + mult * stdev(close, length)
lowerBB = basis - mult * stdev(close, length)

// Keltner
ma = sma(close, lengthKC)
rangema = sma(tr, lengthKC)
upperKC = ma + rangema * multKC
lowerKC = ma - rangema * multKC

sqzOn  = (lowerBB > lowerKC) and (upperBB < upperKC)   // siyah nokta
sqzOff = (lowerBB < lowerKC) and (upperBB > upperKC)   // gri nokta
noSqz  = not sqzOn and not sqzOff                       // mavi

// Momentum (lineer regresyon tabanlı)
val = ta.linreg(close - avg(avg(highest(high, lengthKC), lowest(low, lengthKC)),
                            sma(close, lengthKC)),
                lengthKC, 0)

bcolor = val > 0 ? (val > val[1] ? lime : green)
                 : (val < val[1] ? red : maroon)
```

**Carter'ın kuralı:** "İlk siyah-sonrası gride bekle, momentum yönünde pozisyon al (momentum > 0 ise long). Momentum yön değiştirince çık."

**Orijinal yazarın dürüst notu:** *"Sınırlı deneyimim, iyi giriş noktalarını kaçırmamak için ek bir göstergenin (ADX / WaveTrend) gerekli olduğunu gösteriyor."*

**Bitduke'un strateji varyantı (v4):**
```
longCondition  = scolor[1] != aqua and scolor == aqua and bcolor == lime and filterMom
exitLongCondition = bcolor == green
filterMom = abs(val) > MomentumMin / 100000
// SL 600, TP 1000, trailing 20 (puan cinsinden)
strategy.exit("Exit Long", profit=take_profit, trail_points=trailing_stop, loss=s_loss)
```

#### UT Bot Alerts (QuantNomad) — ATR trailing referans

**Merkez:** stateful trailing seviye, aday mesafe `ATR × Key Value`. Varsayılanlar: Key Value 1, ATR period 10, Heikin-Ashi kapalı.

```
Her iki source de önceki seviyenin üstündeyse:
    yeni_seviye = max(önceki_seviye, source − ATR_mesafe)
Her ikisi de altındaysa:
    yeni_seviye = min(önceki_seviye, source + ATR_mesafe)
Source taraf değiştirirse: referans source'un ilgili tarafına sıfırlanır
```

**Alım sinyali:** source trailing referansı yukarı kesiyor VE üstünde.

**Pineify'ın uyarıları:**
- *"Hesaplama realtime barın onaylanmasını gerektirmez. Fiyat ve ATR bar açıkken değişebilir; görünen bir kesişim kapanıştan önce kaybolabilir."*
- *"Key Value'yu artırmak aday mesafeyi artırır ve referansı genellikle daha az hassas yapar. Tam seviye yol-bağımlıdır, dolayısıyla bu sinyal sayılarının her örnekte monoton değiştiğinin garantisi yoktur."*
- **Önerilen filtre deneyi:** kapanmış alım olayını yalnızca gerçek kapanış 200-EMA üstündeyse al.

---

### 2.9 Freqtrade Strateji Ligi — Kanıtlanmış Sıralama

**Freqle Strategy League** (6.437 strateji, 2022-2025, 33 parite, ağırlıklı skor: Calmar %18, Sortino %15, Sharpe %15, Expectancy %15, CAGR %12, PF %10, DD %10, WR %5):

| # | Strateji | Getiri | maxDD | WR | PF | İşlem |
|:-:|:---------|-------:|------:|---:|---:|------:|
| 01 | NotAnotherSMAOffsetStrategyHO | +117.0% | -3.51% | **80.7%** | 3.24 | 813 |
| 03 | E0V1E | +90.7% | -3.39% | **80.1%** | 7.37 | 346 |
| 04 | OptimalStrategy | +87.8% | -3.41% | 78.6% | 7.14 | 346 |
| 11 | BinClucMadV1 | +84.8% | -2.53% | 81.0% | 2.14 | 1.254 |
| 32 | NowoIchimoku1hV2 | +369.4% | -10.46% | 73.5% | 1.59 | 4.648 |
| 50 | abbas | +156.6% | -6.14% | 82.0% | 1.45 | 5.330 |

**Hariç tutulanlar (neden):** `MKV3` (+8061.6%) — lookahead_leak + dca_capital_fiction. `RSIVol` (-90.4%) — dca_capital_fiction. **Bunlar tam olarak bizim kaçınmamız gereken tuzaklar.**

**Skor açıklaması (alıntı):** *"Kaldıracın taklit edemeyeceği şeylere ağırlık verildi: Sharpe, Sortino, profit factor ve expectancy kaldıraçla değişmez — CAGR değişir, bu yüzden artık en ağır terim değil. Calmar %60 drawdown sonrası saymayı durdurur, yoksa neredeyse-batış harika bir yıl gibi puanlanır. Expectancy, ortalama kayıp üzerinde işlem başına edge'dir: ortalama işlemi ücreti zar zor geçen stratejileri yakalar."*

**freqtradestrategy.com** (27 strateji, 10 coin, 2 yıl, %0.1 ücret, $1.000 başlangıç, $200/işlem, max 5 açık):

| Strateji | TF | Getiri | maxDD | WR | PF |
|:---------|:--|-------:|------:|---:|---:|
| ReinforcedAverageStrategy | 4h | +126.5% | 9.7% | 33.2% | 1.93 |
| MultiMa | 4h | +97.8% | 11.1% | **67.3%** | **2.43** |
| UniversalMACD | 5m | +74.7% | 7.2% | **77.3%** | **3.91** |
| Supertrend | 1h | +68.3% | 27.0% | 60.9% | 1.13 |
| **MACDStrategy** | 5m | +22.9% | **39.2%** | **96.6%** | **1.11** |
| Strategy004 | 5m | -22.2% | 50.2% | 92.6% | 0.91 |
| Strategy003 | 5m | -39.0% | 51.6% | 92.0% | 0.77 |
| BinHV27 | 5m | -59.4% | 60.3% | 55.7% | 0.80 |

*"MACDStrategy: %96.6 kazanma oranı, PF sadece 1.11 — kazançları kayıplarına neredeyse eşit."*
*"Strategy004: %92.6 WR ve para kaybediyor."*

*"Bir strateji %40 kazanıp %60 drawdown istiyorsa, hesabınızın yarısından fazlasını kaybetmeyi oturup izlemenizi istedi. Getiriden önce max drawdown'a bakın."*

---

## 3. Mevcut Koda Somut Eşleştirme

### 3.1 TPSL Optimizer'ın söylediği — ve kodun yapmadığı

`outputs/spot_tpsl_optimizer.json` — 768 konfigürasyon tarandı, **tek bir öneri** çıktı:

| TF | Kod | Canlı parametre tutulsun mu? | Yeni TP | Yeni SL | IS (WR/PF/net) | **OOS (WR/PF/net)** |
|:--|:----|:------------------------------|--------:|--------:|:---------------|:--------------------|
| 5m | `BB_KC_SQUEEZE_BREAK` | **HAYIR** | **1.0** | **1.5** | 62.8% / 1.50 / +19.75 | **66.1% / 1.47 / +9.69** |

**Kod şu an ne yapıyor?** (`STRATEGY_TPSL_OVERRIDE` → `squeeze_breakout`):
```python
"tp_sl_override": {"15m": {"tp_pct": 2.2, "sl_pct": 1.1}},
# 5m ve 1h için override YOK → TIMEFRAMES varsayılanı kullanılıyor
# 5m: tp=1.4, sl=0.9
```

Optimizer **TP=1.0, SL=1.5** diyor. İki fark:
1. **TP 1.4 → 1.0** (daha erken kâr al)
2. **SL 0.9 → 1.5** (stopu %67 genişlet!)

SL'yi genişletmek WR'yi %42.6 → %66.1'e çıkarıyor. Bu, Bölüm 2.2'deki NotAnotherSMAOffsetStrategyHO'nun **geniş stoploss (-0.35)** ve E0V1E'nin **stoploss kapalı (-0.99)** tasarımıyla aynı yönde. **Kod bu bulguyu almamış.**

---

### 3.2 Paper simülatörün iyimser taraflılıkları

| # | Konum | Sorun | Etki |
|:-:|:------|:------|:-----|
| 1 | `spot_monitor.py:647` | `if curr_p >= target_p` **önce** TP kontrol ediliyor, `elif curr_p <= stop_p` sonra | 60sn'lik taramada TP ve SL arasına sığan hareketlerde **TP kazanır** — gerçekte bar içinde önce SL vurulmuş olabilir |
| 2 | `spot_monitor.py:657` | `exit_price = stop_p` — `curr_p` çok daha aşağıda olsa bile stop fiyatından çıkış kaydediliyor | **Gap-down yok sayılıyor.** Gerçekte %0.9 stop, %2 kayıpla dolabilir |
| 3 | `spot_monitor.py:609-637` | `new_mfe` / `new_mae` yalnızca 60sn'de bir örneklenen `pnl_pct` ile güncelleniyor | Bar içi gerçek MFE/MAE **sistematik olarak eksik** → trailing stop seviyeleri geç tetiklenir |
| 4 | `spot_monitor.py:666` | Zaman aşımı `curr_p`'den (60sn tick) hesaplanıyor | Kabul edilebilir |
| 5 | `spot_monitor.py:768` | `total_portfolio_try = INITIAL + realized + unrealized` — açık pozisyonların komisyonu düşülüyor ama **çıkış komisyonu** unrealized'a yansımıyor | Küçük iyimser sapma |

**Proje kendi kuralına aykırı davranıyor.** `.agents/skills/spot-strategy-lab/SKILL.md` diyor ki:

> *"Tek barda aynı anda hem TP hem SL seviyesi görülmüşse **muhafazakar olarak SL kabul edilir**."*

Ama canlı `update_open_signals_pnl()` bunun tersini yapıyor. **Backtest ile canlı simülatör farklı varsayım kullanıyor** → lab'dan geçen strateji canlıda daha kötü görünecek.

---

### 3.3 Dekoratif AI katmanı

```python
# spot_monitor.py:496-563 — hesaplanıyor:
octo_res  = octo_eval.evaluate(...)      # octobot_score, consensus_pct, signal
v_res     = vibe_track.analyze_vibe(...) # vibe_score, vibe_category, is_fomo_trap
trap_warn = "BULL_TRAP" if ... else ...  # trap_warning
qlib_res  = evaluate_qlib_alpha(...)      # qlib_score, qlib_rank
jesse_res = evaluate_jesse_risk(...)     # jesse_rr

# ...ve details JSON'a yazılıyor.
# HİÇBİRİ matched kararını etkilemiyor.
```

**Gerçek engelleme yok.** `trap_warning == "FOMO_TRAP"` olsa da işlem açılıyor. `octobot_consensus_pct < 60` olsa da açılıyor (oysa `OctoBotMatrixEvaluator(consensus_threshold=0.60)` parametresi geçiliyor ama sonucu kullanılmıyor).

**Ek sorun:** `evaluate_qlib_alpha` ve `evaluate_jesse_risk` sabit girdilerle çağrılıyor:
```python
indicators={"rsi": 55.0, "volume_ratio": vol_ratio, "atr": price * 0.015}
```
`rsi` **sabit 55.0** — her sembol, her zaman dilimi, her koşulda. Hesaplanmış `_rsi` mevcut ama kullanılmıyor. `atr` da `price * 0.015` tahmini — gerçek ATR yok.

---

### 3.4 Eksik risk katmanları (riskkit ile karşılaştırma)

| Bileşen | riskkit | `spot_monitor.py` |
|:--------|:--------|:------------------|
| Volatilite-ayarlı boyutlandırma | ✅ ATR bazlı | ❌ **Sabit 500 TL** |
| Kelly tavanı | ✅ Yarım-Kelly | ❌ |
| Kayıp serisi azaltma merdiveni | ✅ | ❌ |
| Drawdown kademesi (boyut kes → bar yükselt → durdur) | ✅ | ❌ |
| ATR/EMA/chandelier trailing | ✅ | ⚠️ Sadece fiyat-% trailing |
| Zaman stopu | ✅ | ✅ (60/150/360 dk) |
| Korelasyon grubu kilidi | ✅ | ❌ |
| Günlük zarar tavanı | ✅ | ❌ |
| Artan cooldown (kayıp sonrası) | ✅ | ❌ (sadece sembol başına pozisyon) |
| Tilt tespiti | ✅ | ❌ |
| Portföy toplam heat | ✅ | ❌ |
| VaR / CVaR | ✅ | ❌ |
| İşlem öncesi doğrulayıcı zinciri | ✅ | ❌ |

---

### 3.5 Rejim filtresi — lab verisi ne diyor

`outputs/spot_15m_regime_long.json` — 2.786 kayıt, 6 rejim hücresi. **HEPSİ negatif:**

| Hücre | n | Net | Ortalama/işlem |
|:------|--:|----:|---------------:|
| VOL-orta × DOM↓ | 2.329 | **-74.18** | -0.032 |
| VOL-düşük × DOM↓ | 1.885 | **-124.83** | -0.066 |
| VOL-orta × DOM↑ | 2.498 | **-157.83** | -0.063 |
| VOL-düşük × DOM↑ | 1.736 | **-201.24** | -0.116 |
| VOL-yüksek × DOM↑ | 3.712 | **-504.92** | -0.136 |
| VOL-yüksek × DOM↓ | 2.559 | **-586.74** | **-0.229** |

**En iyi hücre (VOL-orta × DOM↓) bile işlem başına -0.032 kaybediyor.**

**En kritik içgörü:** En yüksek işlem sayısı (3.712) **VOL-yüksek × DOM↑**'de ve orada işlem başına -0.136 var. Yani sistem **en çok, en kötü koşulda işlem yapıyor.** Bu, bir rejim filtresinin tam olarak çözeceği sorun.

---

## 4. Öneri Listesi — Önceliklendirilmiş

### 🔴 P0 — Maliyet ve gerçekçilik (önce bunlar)

| # | Öneri | Kaynak | Dosya |
|:-:|:------|:-------|:------|
| 1 | **Komisyon oranını yapılandırılabilir yap.** `COMMISSION_RATE = 0.0004` yerine BNB indirimi durumunu ayarla. `%0.20` senaryosu için UI'da seçim sun. | Binance fee tablosu, spreadatlas | `spot_monitor.py:27` |
| 2 | **TP/SL kontrol sırasını muhafazakar çevir.** Aynı taramada hem TP hem SL görülüyorsa **SL kazanır**. Skill'in kendi kuralı bu. | SKILL.md §1.3 | `spot_monitor.py:647-663` |
| 3 | **SL çıkışında gap-down modellen.** `exit_price = min(stop_p, curr_p)` — `curr_p` stop'un altındaysa oradan doldur. | Kureshi25 frekans aritmetiği | `spot_monitor.py:657` |
| 4 | **`squeeze_breakout` için optimizer'ın TP=1.0/SL=1.5 sonucunu uygula** (5m). OOS WR %66.1, PF 1.47. | `spot_tpsl_optimizer.json` | `spot_monitor.py:52` |
| 5 | **5m stratejilerini gözden geçir.** %0.20 maliyette 4/5'i basabas altında. `COPPOCK_ZERO_TURN`, `TURTLE_DONCHIAN55`, `VPROFILE_POC_RECLAIM` → devre dışı bırak veya 15m'e taşı. | Bölüm 1.3 hesabı | `ACTIVE_STRATEGIES` |

### 🟠 P1 — Rejim ve filtre katmanı

| # | Öneri | Kaynak | Nereye |
|:-:|:------|:-------|:-------|
| 6 | **Rejim filtresi ekle.** Lab verisi 6/6 hücrenin negatif olduğunu söylüyor; en kötü hücre en yoğun. Minimal: `VOL-yüksek` rejiminde taramayı atla. | `spot_15m_regime_long.json`, DaruFinance | `run_single_scan()` başı |
| 7 | **BTC 200-gün MA rejim koşullaması** (günlük/4h). Ayı rejiminde pozisyon boyutunu yarıya indir veya long-only durdur. Kanıtlanmış: matiasjarnal, iolufemi. | `matiasjarnal/crypto-momentum-strategy` | Yeni `_btc_regime()` |
| 8 | **ATR-tabanlı dinamik TP/SL.** Sabit yüzde yerine `TP = k1 × ATR`, `SL = k2 × ATR`. BTC ile PEPE aynı yüzdeyi almamalı. | `rayhantithokharisma/bbca-tbm-meta` (SWING modu) | `TIMEFRAMES` |
| 9 | **1h MA-eğim filtresi.** 219 sembolün %68.5'inde iyileşme, üstüne 5m MACD teyidi %74'ünde. En sağlam pozitif bulgu. | `iolufemi/crypto-trend-research` | Giriş koşuluna ekle |
| 10 | **İşlem saat-of-gün filtresi.** `RVOL_TOD_SPIKE` zaten saat-çapalı; genelleştir. UTC 7-11 düşük likidite (mamipour). | `mamipour/lead-lag-trader` | Giriş kapısı |

### 🟡 P2 — Risk yönetimi

| # | Öneri | Kaynak | Nereye |
|:-:|:------|:-------|:-------|
| 11 | **ATR-ters volatilite boyutlandırma.** Sabit 500 TL yerine: `size = (portfoy × hedef_risk) / (fiyat × atr_pct)`. Düşük vol → büyük, yüksek vol → küçük. | `leionion`, `zachisit` PR#78, riskkit | `TRADE_SIZE_TRY` kullanımı |
| 12 | **Kayıp serisi azaltma merdiveni.** 2 ardışık kayıpta boyut ×0.7, 3'te ×0.5. | riskkit `PositionSizer` | Yeni |
| 13 | **Drawdown devre kesici.** Portföy maxDD %10 → işlem boyutu yarıla; %15 → durdur. | riskkit `DrawdownManager`, Kureshi25 | Yeni |
| 14 | **Sembol başına cooldown.** Kayıptan sonra 15-60 dk aynı sembole girme. `RamavatMit`, `Portfolio` | `RamavatMit/Binance` | `open_symbols` genişlet |
| 15 | **Günlük zarar tavanı.** Günlük realized zarar > %3 → gün sonuna kadar dur. | riskkit `SessionManager`, Binance bot | Yeni |
| 16 | **Korelasyon kilidi.** Aynı korelasyon grubundaki (örn. tüm altcoinler) ikinci pozisyonu engelle. Şu an 10 pozisyon aynı anda BTC-beta taşıyor olabilir. | riskkit `CorrelationGuard`, Binance bot | `open_symbols` |
| 17 | **Toplam portföy heat tavanı.** Açık pozisyonların stop'ta toplam riski %10'u geçmesin. | `zachisit` PR#78 `max_portfolio_heat` | Yeni |

### 🟢 P3 — Çıkış kalitesi

| # | Öneri | Kaynak | Nereye |
|:-:|:------|:-------|:-------|
| 18 | **Deadfish exit (gösterge-tabanlı çıkış).** Kâr var ama hareket durdu → çık. `fastk > 75` veya `cci > 90` ve `profit > 0`. WR %80'in sırrı burada. | E0V1E `custom_exit` | `update_open_signals_pnl` |
| 19 | **Zaman-bazlı kâr çıkışı.** 2 saat geçti ve hâlâ kârda → çık. | E0V1E | Aynı yer |
| 20 | **Sıkışma öncesi durum kontrolü.** Squeeze girişinde `val > 0` (momentum pozitif) VE `val > val[1]` (momentum artıyor) şartı ara. | LazyBear formülü | `_bb_kc_squeeze` |
| 21 | **WaveTrend / ADX teyidi.** LazyBear'ın kendisi "ek gösterge olmadan iyi girişleri kaçırıyorum" diyor. | LazyBear yorumu | Giriş kapısı |

### 🔵 P4 — AI katmanını gerçek yap

| # | Öneri | Kaynak | Nereye |
|:-:|:------|:-------|:-------|
| 22 | **AI skorlarını gerçek kapıya çevir.** `trap_warning == "FOMO_TRAP"` → işlem açma. `octobot_consensus_pct < 60` → açma. Şu an dekoratif. | Mevcut kod | `spot_monitor.py:485` |
| 23 | **Sabit RSI 55.0'ı gerçek RSI ile değiştir.** `_rsi(closes, 14)` mevcut, kullanılmıyor. Gerçek ATR de hesaplanmalı. | `spot_monitor.py:524` | Aynı |
| 24 | **Meta-labeling ekle (dikkatli).** Triple barrier + ikincil model. **Ama:** knacker65'in walk-forward'ı AI kapının **-0.25% vs -0.13% baz** verdiğini gösteriyor. Yani saf ML kapı işe yaramadı. Yalnızca doğru walk-forward + holdout ile değerlendir. | mlfinlab, RiskLabAI, knacker65 | Yeni, deneysel |
| 25 | **Ters-vol ağırlıklı strateji birleştirme.** Tek strateji yerine, canlı PF'e göre ağırlıkla. Ortalama korelasyon ~0.11 → birleşim tek tek en iyisinden çok daha iyi (2.52 vs 1.77). | `ccollins80/crypto-stat-arb`, `angel4angelov` | `TRADE_SIZE_TRY` tahsisi |

### ⚪ P5 — Yeni strateji adayları (kanıtlı, düşük devirli)

| # | Strateji | Kanıt | Not |
|:-:|:---------|:------|:----|
| 26 | **4h SMA200 long/flat** | BTC Sharpe 1.15 vs 0.92 buy-hold, maxDD -30% vs -50%. 219 sembolde doğrulandı. | En sağlam bulgu. Spot paper trade'de ayrı bir "swing" kanalı olarak eklenebilir. |
| 27 | **PairsRotation (BTC'ye karşı 2σ sapma)** | +$2.24/işlem, 3 yılda 35 işlem, walk-forward doğrulanmış | Tek walk-forward-doğrulanmış pozitif edge. |
| 28 | **Cross-sectional reversal** | Net Sharpe 1.77, günlük rebalans, 89 devir/yıl | `k=4, band=2.5, beta_win=168` |
| 29 | **Grid + cDCA** | GridHODL yatay piyasada, cDCA fare-tabanlı birikim | Rejim filtresi ile birleştirilmeli — trendde çalışmaz |
| 30 | **Liquidity sweep** | WR %58.2, PF 1.42, Sharpe 1.18 | `OliverNyx` |

---

## 5. Yapılmaması Gerekenler (Kanıtlanmış Negatif)

| Tuzak | Kanıt |
|:------|:------|
| **≤10 dakika barlarda işlem avlamak** | spreadatlas: setup'ların **%6'sından azı** maliyet sonrası kârlı; 4h'de %81 |
| **Yüksek frekans + küçük TP** | Kureshi25: %67 WR, 15.949 işlem, **-%97.6** hesap |
| **Stoploss'u kapatıp "ortalama düşürme"** | `grantreed1/Crypto-Order-Flow-Imbalance`: -$62.3M drawdown |
| **Daha fazla parametre eklemek** | Kureshi25: 7-param adaptive, IS +%78.7 → OOS **-%22.3** |
| **Saf ML yön tahmini kapısı** | knacker65 walk-forward: **-0.25% AI kapılı vs -0.13% baz**, holdout korelasyon **-0.008** |
| **ML/sofistike katman umudu** | iolufemi: 538M bar, "neredeyse her sofistike katman risk-ayarlı getiriyi çıkarır" |
| **Backtest sonucuna güvenmek** | spreadatlas: replay +%92/yıl → gerçek paper **-%3.93 / 2 hafta** |
| **Yüksek WR'yi kâr sanmak** | freqtradestrategy: MACDStrategy %96.6 WR, PF 1.11; Strategy004 %92.6 WR, **zarar** |
| **Teorik dolum fiyatı varsaymak** | AlphaLab: OFI sinyali istatistiksel olarak anlamlı (AUC 0.726), ama **0.10 bps ek maliyette tüm eşikler negatif** |
| **Lookahead / DCA sermaye kurgusu** | Freqle ligi: `MKV3` (+%8061) ve `RSIVol` (-%90) tam bu nedenle **hariç tutuldu** |

---

## 6. En Yüksek Getirili 3 Hamle

Sıralı, her biri bağımsız değer üretir:

**1. Muhafazakâr dolum + gerçek komisyon (P0/1-3)**
Şu an simülatör sistematik olarak iyimser. TP-önce-SL-sonra sırasını çevirmek ve SL gap-down modellemek, canlı sonuçları backtest'e yaklaştırır. Komisyonu %0.20'ye çıkardığınızda hangi stratejilerin ayakta kaldığını görürsünüz — muhtemelen beklediğinizden az.

**2. Rejim filtresi (P1/6-7)**
Lab verisi 6/6 hücrenin negatif olduğunu gösteriyor, en yoğun hücre en kötü. `VOL-yüksek` ve BTC-ayı rejimlerinde taramayı atlamak, kayıpların büyük kısmını keser. Kod ~20 satır.

**3. ATR-ters volatilite boyutlandırma + drawdown kesici (P2/11-13)**
Sabit 500 TL, yüksek-vol altcoinlerde aynı riski taşımıyor demek — aynı **yüzde** stop, çok farklı **gerçek** risk. ATR-ters boyutlandırma + kayıp serisi merdiveni + drawdown kesici, tek başına en büyük risk-ayarlı iyileşme kaynağı (ccollins80: birleşik strateji 2.52 Sharpe vs tek tek 1.77).

---

## 7. Kaynak Listesi

**Negatif kanıt (en değerli):**
- [iolufemi/crypto-trend-research](https://github.com/iolufemi/crypto-trend-research) — 538M bar, 219 sembol, sızıntı-kontrollü
- [knacker65/v5-crypto-scalper](https://github.com/knacker65/v5-crypto-scalper) — 30+ backtest, dürüst özet
- [RamavatMit/Binance](https://github.com/RamavatMit/Binance) — ML + triple barrier + holdout
- [Kureshi25/cryptobot](https://github.com/Kureshi25/cryptobot) — frekans aritmetiği
- [spreadatlas.com](https://spreadatlas.com/) — 31.407 setup × maliyet haritası
- [degendaycare.com "Where the Edge Is"](https://degendaycare.com/university/papers/where-the-edge-is.html) — 53 walk-forward fold

**Pozitif strateji kanıtı:**
- [jicheolha/crypto-trading-bot](https://github.com/jicheolha/crypto-trading-bot) — Keltrader, squeeze breakout, Sharpe 2.27
- [davidzr/freqtrade-strategies](https://github.com/davidzr/freqtrade-strategies) — NotAnotherSMAOffsetStrategyHO
- [ssssi/freqtrade_strs](https://github.com/ssssi/freqtrade_strs) — E0V1E kaynak + deadfish exit
- [freqle.org/ranking](https://freqle.org/ranking) — 6.437 strateji ligi
- [freqtradestrategy.com](https://freqtradestrategy.com/) — 27 strateji karşılaştırma
- [ccollins80/crypto-stat-arb](https://github.com/ccollins80/crypto-stat-arb) — cross-sectional + vol hedefleme

**Risk / boyutlandırma:**
- [HasibVortex369/riskkit](https://github.com/HasibVortex369/riskkit) — 6 bileşenli risk çerçevesi
- [leionion/dynamic-position-sizer-atr-calculator](https://github.com/leionion/dynamic-position-sizer-atr-calculator)
- [zachisit/july-backtester PR#78](https://github.com/zachisit/july-backtester/pull/78) — 4 boyutlandırma yöntemi + look-ahead düzeltmeleri
- [Muvon/vanga](https://github.com/muvon/vanga) — trading-aware ordinal loss

**Rejim tespiti:**
- [DaruFinance/strategy-regime](https://github.com/DaruFinance/strategy-regime) — K=4 BIC oybirliği, stay-prob ≥0.97
- [farhad-nazari1990/crypto-regime-detection](https://github.com/farhad-nazari1990/crypto-regime-detection) — HMM/GMM/CPD
- [Yosri-Ben-Halima/hmm-crypto-trading-model](https://github.com/Yosri-Ben-Halima/hmm-crypto-trading-model) — Sharpe 1.71 vs 1.02
- [JPeetz/Hidden_Markov_Model_Strategy_Tester](https://github.com/JPeetz/Hidden_Markov_Model_Strategy_Tester) — 8-puan teyit
- [matiasjarnal/crypto-momentum-strategy](https://github.com/matiasjarnal/crypto-momentum-strategy) — BTC 200MA rejim

**Meta-labeling:**
- [hudson-and-thames/mlfinlab](https://github.com/hudson-and-thames/mlfinlab) — referans implementasyon
- [ArmaanSharmaProjects/Meta-Labeling](https://github.com/ArmaanSharmaProjects/Meta-Labeling)
- [rayhantithokharisma/bbca-tbm-meta](https://github.com/rayhantithokharisma/bbca-tbm-meta) — ATR bariyer modu
- [mchiuminatto/triple_barrier](https://github.com/mchiuminatto/triple_barrier) — pip paketi

**Mikroyapı:**
- [ilibili-AI/AlphaLab](https://github.com/ilibili-AI/AlphaLab) — en dürüst execution analizi
- [tejeshvenkat/microstructure-alpha](https://github.com/tejeshvenkat/microstructure-alpha) — OFI IC +0.728
- [tsuithomas/crypto_research_order_book_imbalance](https://github.com/tsuithomas/crypto_research_order_book_imbalance) — OBI %45 önem
- [OliverNyx/crypto-liquidity-sniper](https://github.com/OliverNyx/crypto-liquidity-sniper)

**Grid / DCA:**
- [btschwertfeger/infinity-grid](https://github.com/btschwertfeger/infinity-grid)
- [Aihansu/smart-grid-bot](https://github.com/Aihansu/smart-grid-bot) — EMA dinamik alım bölgeleri
- [ducminhle1904/crypto-dca-bot](https://github.com/ducminhle1904/crypto-dca-bot)

**Tahsisi:**
- [angel4angelov-glitch/Multi-Strategy-Allocation-Engine](https://github.com/angel4angelov-glitch/Multi-Strategy-Allocation-Engine) — 7 tahsis yöntemi
- [LORD-ZYTHOZ/regime-aware-strategy-allocator](https://github.com/LORD-ZYTHOZ/regime-aware-strategy-allocator) — QP + adaptive gamma
- [s-brez/trading-server](https://github.com/s-brez/trading-server)

**Göstergeler:**
- [fmzquant/strategies — Squeeze Momentum](https://github.com/fmzquant/strategies/blob/master/Squeeze-Momentum-Indicator.md)
- [Pineify — UT Bot Alerts analizi](https://pineify.app/resources/blog/ut-bot-indicator-tradingview-pine-script)

**Resmi:**
- [Binance Spot Fee Rate](https://www.binance.com/en/fee/trading)
- [Binance TR Ücret Tablosu](https://www.binance.tr/en/fees/schedule)
