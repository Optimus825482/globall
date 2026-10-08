# FX Strateji Araştırması — DERİNLEŞTİRİLMİŞ (Dalga 2, TEST YAPILMADI)

**Tarih:** 2026-10-08 (2. tur)
**Talimat:** "Araştırmayı daha derinleştirerek yeniden yap; herhangi bir test yapmadan önce bulduklarını listele."
**Sonuç:** Bu turda **hiçbir backtest/replay koşulmadı.** Yalnız 12 paralel web-araştırma agent'ı
koşuldu ve bulgular aşağıda listelendi. Uygulama/karar bir sonraki adıma bırakıldı.

**Kümülatif araştırma kapsamı:** Dalga 1 = 10 agent (seans/ORB, mean-reversion, trend/Donchian,
stat-arb, carry, volatilite, haber, ICT/likidite, MTF/regime, backtest-rigor). Dalga 2 = 12 agent
(aşağıdaki 12 kol). Toplam **22 paralel araştırma kolu.**

---

## A. GENEL HÜKÜM (22 kolun ortak sonucu)

**İntraday FX'te (5m-1h) retail maliyetlerden sonra pozitif kalan, tekrarlanabilir KANITLI edge
neredeyse yok.** Bütün kollar aynı yere çıkıyor:

- Sinyalin brüt kenarı ≈ tur maliyeti (0.7-1.5 pip majörler, 1.5-3.1 pip kroslar).
- "Kârlı" görünen intraday FX Sharpe'ları ya (a) gross/cost-free, ya (b) tek pencere/eğriye-sığdırma,
  ya (c) kurumsal erişim gerektiriyor.
- Net-kâr barajını geçen ve tekrarlanan **tek istisna: EURUSD saat-günü sezonsallığı** (aşağıda C1).

---

## B. KOL BAZINDA BULGULAR

### B1 — Akademik intraday FX net-maliyet literatürü (2015-2025)
- **Order-flow imbalance** en güçlü FX sinyali (Evans-Lyons R²>50%) **ama tamamen kurumsal veriye
  kilitli**; ticari order-flow ile OOS güç YOK (Sager-Taylor 2008). → **Retail'de erişilemez.**
- **Post-news drift ÖLÜ** — haber bir "sıçrama" (jump), sürüklenme değil (Chaboud 2004, NBER).
- **Intraday momentum** (Baltussen JFE 2021): 60 vadeli işlemde kurunun çalıştığı tek sınıf **FX hariç**
  (currency leg anlamsız). Londra-açılış momentumu yalnız **USDJPY**'de ayakta (Seeck 2026, Sortino 0.75),
  BoJ müdahalesiyle ölür.
- **Fix reversal** (Krohn J.Finance 2023, ~2bp) gerçek ama **dealer-kontrollü**, retail toplayamaz.
- **Overreaction/reversal** (Caporale-Plastun) istatistikî gerçek, **net maliyet testi yok**, edge≈cost.
- **Break-even tablosu:** Neely-Weller (JIMF 2003) ~1.0 bp tek-yön; Ranaldo 2009 EURUSD 4 pip /
  gün-ay 10-19 pip; teknik/ML intraday "modest cost'ta ölü".
- **Verdict: yalnız EURUSD saat-günü sezonsallığı tekrarlanan net-kanıta sahip.**

### B2 — Saatlik/günlük sezonsallık haritaları (ölçülmüş veri)
- **Volatilite profili (saatlik TR, pip):** TÜM çiftlerde **13:00-15:00 UTC tepe**, 21:00-22:00 dip.
  EURUSD 14:00=28p vs 22:00=8p (3.4×); GBPJPY 14:00=42p vs 20:00=20p (2.1×); EURJPY **07:00'de ikinci
  tepe** (Londra açılışı); USDJPY Tokyo 00:00 ikinci tepe.
- **Spread/saat oranı (exploitable metrik):** 12-15 UTC'de spread aralığın ~%1-4'ü; **21:00'de %27-69'u**
  (EURUSD %27, GBPJPY %69!). 13:00'te EURUSD spread aralığın %1.2'si, 21:00'de %26.7 → **22× fark.**
- **Kaçınılacak saatler:** 21:00-23:00 (tüm çiftler — rollover), 03:00-05:00 (Londra-öncesi ölü bölge),
  19:00-20:00 (USDCHF/NZDUSD/JPY krosları).
- **Gün-h-içi profile iki on yılda sabit** (r=0.987). Gün-ay (DOW) yön etkisi 2005 sonrası kayboldu.
- **En iyi pencere:** 13:00-16:00 UTC tümü; GBPUSD/GBPJPY/EURJPY'ye ek **07:00-09:00**.
- **Verdict: saat haritası VOLATİLİTE için güvenilir; YÖN için değil ("ne zaman", "hangi yön" değil).**

### B3 — Tick volume / order-flow proksileri (MT5 retail)
- MT5 FX'te `real_volume` = 0; yalnız tick sayısı var. Tick volume ≈ volatilite proksisi
  (Spearman 0.55-0.77) → **"volume breakout" aslında gizli range breakout (totoloji).**
- **CVD/delta MT5'ten dürüstçe hesaplanamaz:** aggressor recoverable değil; tick-rule doğruluğu %67,
  sıfır-tick'te %63, sıfır-spread'de %49; CVD hatası gerçek büyüklüğün %169'u, R²=0.031 → **çalışmıyor.**
- CME 6E/6J vadeli hacmi spot'un ~%3'ü; price-discovery karışık; **COT haftalık, 3-gün bayat, intraday 0.**
- **Kodlamaya değer tek şey:** session-normalize tick-volume z-score (yalnız rejim/aktivite FİLTRESİ,
  asla yön) + tick-weighted VWAP (referans seviye, düz VWAP'ı yenerse tut).
- **Verdict: 5m'de FX volume/delta kenarı yok; en fazla filtre.**

### B4 — Machine learning (5m FX)
- En dürüst çalışma (Krueger 2026): 98 feature, walk-forward, net maliyet → **OOS rank IC=+0.004**
  (ekonomik sıfır); işlem kuralı **−1.4…−1.6 bp/işlem**; **79 hücrenin 0'ı net t=2'ye ulaştı.**
- Meta-labeling FX'te (8 majör, 1m): PF 0.85→0.94, Sharpe −1.13→−0.27 ama **42 enstrümanın 0'ı DSR>0.95.**
- 60 gün 5m veri (~17.280 bar ≈ 0.24 yıl) **MinBTL tabanının altında** → **hiçbir backtest güvenilir değil.**
- Retail maliyet 5m mumun **%40-70'i**; ML'in +0.004 IC'si bunu 100× ödeyemez.
- **Verdict: 60 gün 5m ML FX KESİN RED. Tek makul yol: günlük/4H + basit kural + vol-gating.**

### B5 — Volatilite rejimi zamanlaması
- Rejimler **yönü değil hangi strateji-türünün çalıştığını** öngörür (MS-GARCH OOS yön IC=+0.025).
- Vol spike sonrası: **orta kuantillerde reversion, aşırı kuyrukta devam** (Kuck-Maderitsch 2019, U-şekli).
- **Sıkışma yön vermez**, yalnız volatilite tahmin eder; breakout tetiği + trend filtresi ile silahlandırılmalı.
- Vol-targeting ve sıkışma filtreleri **DD/PF'yi iyileştirir, getiriyi DÜŞÜRÜR** (StatOasis 15.552 backtest:
  her filtre medyan −1.56 puan/yıl; yalnız %0.2 net kâr artırdı).
- **Verdict: 3 kural değerli — (1) ATR%-bazlı eşit-risk sizing, (2) seans/duyuru vol-kapısı,
  (3) vol-state ile strateji-router. Yön kenarı yok, risk/DD iyileşmesi var.**

### B6 — Korelasyon / USD-kümé
- DXY'nin %57.6'sı EUR → EURUSD'yi "DXY'ye karşı" trade etmek **döngüsel** (aynı grafiği teyit).
- **DXY majörleri LEAD ETMEZ** — M1'de neredeyse eşzamanlı, 2-dakika gecikmede kaybolur (arXiv 1906.10388).
- Risk-off'ta korelasyonlar yükselir → **çeşitlendirme tam ihtiyaç anında yok olur** (bu risk, alpha değil).
- Korelasyon-kalkanı **RISK kontrolü** olarak değerli (Neff=1+(N−1)(1−r_avg)); 3+ USD-yönü pozisyon ≈ tek bahis.
- **Cross-sectional intraday FX momentum/MR: kanıt YOK** (aylık fenomen).
- **Verdict: Korelasyon = risk şekillendirme, giriş sinyali DEĞİL. DXY-lead efsanesi öldü.**

### B7 — Emtia-endeks ↔ FX çapraz bağları (motor XAU/BTC de trade ediyor)
- Gold→AUD, oil→CAD, risk→JPY **neredeyse tamamen EŞZAMANLI** (aynı makro şok saniyeler içinde fiyatlanır).
- Tek gerçek gecikme: **endeks→JPY ~1 dakika** — anlamlı ama 2-dakikada yok, 5m'de erişilemez.
- BTC FX'i **takip eder** (BTC-EURUSD korelasyonu <0.05; EURUSD BTC'yi lead eder).
- Önceki M1 bulgusu (lag R² negatif) bağımsız çalışmayla **DOĞRULANDI.**
- **Own-asset intraday momentum** (rest-of-day → son 30 dk, Gao-Han-Li-Zhou JFE 2018) tek sağlam
  intraday efekt — **XAU/BTC çıkış mimarisi için** değerli, FX çapraz-sinyal değil.
- **Verdict: FX-çapraz-asset sinyal DROP. VIX/risk = JPY/gold üzerinde REJİM FİLTRESİ, giriş değil.**

### B8 — Giriş yürütme ve zamanlama
- **Aynı-bar fill Sharpe ~15 sahte üretir**; her fill `open[i+1]` varsayılmalı; bir-bar kaydırma testi şart.
- **Limit emirlerde ters-seçim:** hızlı dolan = kötü dolan (fill <1dk −0.31, >10dk +0.43); momentum
  sinyalinde limit edge'i tersine çevirir.
- **Breakout vs retest: ölçülen fark ≈ 0** (NIFTY: break +0.09R vs retest-bekle +0.06R; 4/5 TF "fark yok").
- **Chase vergisi:** 50k-fill: overlap-breakout girişi −0.32 pip, stop-out'lar 4.2× daha kötü slippage.
  ORB 0.2-0.5 pip slippage'da kârlı, **0.5-1.5 pip'te %0 kârlı.**
- **Verdict: 5m momentum → market order; fill `open[i+1]`; rollover/red-folder blokla; gross edge
  <3× model-maliyet ise sinyali öldür.**

### B9 — Piramitleme / ölçekleme / boyutlandırma
- **Piramit (Turtle 0.5N) expectancy'yi artırmaz** — getiri ≈ ortalama maruz kalma (kısmen kaldıraç).
  Şart: her eklemede **tüm birimlerin stop'u taşınmalı**; stop sabitse 60% devam gerekir.
- **Kısmi kâr alma (scale-out) trend sisteminde expectancy'yi DÜŞÜRÜR** (0.350R→0.215R, −39%);
  yalnız WR/DD iyileştirir. İstenirse **baştan yarım boyut** gir.
- **BE-stop kuyruğu keser:** expectancy'nin **%25-43'ünü** yer; 45%WR/2R'de BE 0.80R→0.59R.
- **Risk-of-ruin:** 40%WR'de 5% risk → %11.6; 10% risk → %46.2. **0.25-1% işlem başı** tek savunulabilir.
- **Martingale kesin RED** (7 ardışık kayıp 1% riskte hesabı siler).
- **Verdict: tek giriş + geniş ATR stop + yapısal trail. Kısmi/BE refleksi YOK. İşlem başı %0.25-0.5,
  toplam ısı %3, korelasyonlu 3+ USD çifti = tek pozisyon.**

### B10 — JPY krosları derin spesifik
- **Volatilite:** GBJPY ADR ~135p (medyan 116), EURJPY 105 (89), USDJPY 104 (86). 5m ATR:
  GBPJPY 6-8, EURJPY 4-5, USDJPY 4-5.
- **Maliyet:** IC raw komisyon $7/lot RT = **1.10 pip**; all-in RT: USDJPY 1.3p, EURJPY 1.4p,
  GBPJPY 1.75p. 2×ATR stop'un **%3.3-4.4'ü** (0.065-0.088R) → JPY krosları **tek yaşayabilir sınıf.**
- **Tokyo öğle sıkışması 03:00-04:30 UTC** (Japonya DST'siz → sabit filtre): her çift %14-18 daralır.
- **Swap:** short tüm JPY kroslarında **−1.7…−2.3 pip/gece** (GBPJPY short ~−2.3, 3× Çarşamba) →
  5m flat-at-session sistemde ilgisiz, ama gece tutulursa öldürür.
- **Yön:** JPY krosları intraday **random-walk'a yakın** (asimetri yok); yalnız EURJPY %54.2 devam (p<0.05)
  — zayıf. **Edge "trendlilik"ten değil, maliyet/vol/seans yapısından gelir.**
- **Müdahale riski:** MoF/BoJ tek günde ¥5.9T (2024-04), USDJPY −%12.5 (3 hafta, Ağu 2024); 30-250 pip/1-3 dk.
  **150/155/160 seviyelerine yakın ve BoJ günlerinde yeni risk alma.**
- **Hafta-sonu gap:** GBPJPY medyan 16p, **p95 59p** (kroslar majörlerin 1.5-1.6×'i); düşük dolum oranı.
- **Verdict: GBPJPY/EURJPY window 08:00-16:00 UTC (peak 13-15), stop ≥28-35p, flat 21:00 öncesi,
  BoJ/müdahale penceresi blok. Maliyet/vol oranı bu sınıfı haklı çıkarıyor.**

### B11 — Range-expansion / volatilite breakout derinlemesine
- **Crabel NR4/NR7:** yüzyıl testi (1923-2025) 11/11 on yılda pozitif **ama gross** ve **Sharpes düşüyor**
  (1970'ler >6 → 2010'lar 0.91). FX-spesifik: NR7-as-ORB-filtresi NQ'da **yardım etmedi** (PF 1.02 vs 1.12).
- **Bollinger squeeze intraday neredeyse DAMNING:** USDJPY 4.032 ayar (0.3-pip spread) → **hiçbir TF 2024
  ve 2025'te birlikte kârlı değil**; break-even spread **−0.92 pip (yok)**. TTM 5m PF **0.18**. → **RED.**
- **Sıkışma→genişleme** "arm" olarak gerçek (XAUUSD 1h: skor≥3 → 2×ATR impuls 1.95× baz oran) **ama yön null**
  (132 değişken + order flow testi) ve **"5m kullanma"** (intraday U-hacim sinyali bozar).
- **Filtreli ORB** (OR/ADR∈[0.25-0.60], tek yön/gün, gün-trend onayı) en iyi range-expansion adayı;
  filtresiz ORB **negatif** (2.444 işlem / 28 parite = %97.7 drawdown).
- **Exit:** time-stop veya sabit R en iyi; **trailing/BE range-expansion'da ZARARLI** (Krueger: hold-to-close
  18/25 kombinasyonda trailing'i yendi).
- **Verdict: kodlanabilir 3 aday — (1) filtreli seans-open ORB (15m kutu), (2) 15m sıkışma-armed
  genişleme-barı (yön HTF-trendden), (3) NR4-ID günlük kutu. 5m squeeze/çıplak ATR-breakout KODLAMA.**

### B12 — Seans sınırı / gap / overnight
- **Rollover 21:00-22:00 UTC = saf maliyet olayı**, yön yok (spread EURUSD 0.1→1.2-4.5, 55-75 dk geniş, 22:05'te döner).
- **Hafta-sonu/Monday gap retail-untradeable:** MT5 ~Sun 21:00 UTC quote eder, **trading Mon 00:00** —
  3 saat "quote-var-trade-yok"; 2021 H1'de 11 gap'in 8'i ilk tradable bar öncesi doldu; 5-pip fade **5 yılda −$1.308.**
- **Asya aralığı → Londra:** kutu Londra'dan önce **%92-99.5 oranında zaten kırılmış** → klasik London-ORB
  "taze kutu" varsayımı YANLIŞ; fade %49.4 = coin flip.
- **Günlük reopen (Tolusic 2026 preprint):** ilk saat barı ort. **4.8 pip** açılır (%74 >1 pip); fade ile
  net **PF 2.63, sıfır kayıp yılı** — ama reopen=rollover, **veri feed'i + spread filtre şart** (retail spread cezası).
- **Tokyo fix 00:55 UTC:** long-then-short 15 yılda **+1.8 bp** ("marjinal, spread'in hemen üstünde").
- **Verdict: kodlanabilir — (1) günlük reopen gap-fade (ECN+spread filtre), (2) Tokyo fix (aylık/5-günlük),
  (3) month-end fix. Weekend gap + rollover-yön + London-ORB = retail-untradeable.**

### B13 — Prop desk / quant fon playbook'ları
- Prop playbook'ları çoğunlukla **pazarlama**; tek bağımsız simülasyon: 50%/3-gün profili %20.3 pass,
  scalper 58%/6-gün %59.1 pass ama yalnız %44.2 payout.
- FPFX (300k+ hesap): ~%14 funding, **~%7 payout**, ortalama payout hesabın %4'ü.
- **Bağımsız-hakemli ORB testleri negatif:** 47.5M varyant — **coin-flip bot her versiyonda yendi**;
  QQQ-ORB replication (2010-2026) Sharpe **−0.06**; StratForge ATR-breakout 27/27 EURUSD-4H **öldü**
  ("EURUSD ekstremlerini FADE ediyor").
- Quant fon araçları: **execution algoları (TWAP/VWAP/POV, sistematik-internalizer)** — retail **hiçbirini kopyalayamaz.**
- **Yapılamazlar:** co-location/latency arbitraj, L2 order-flow, fix-window internalization, market-making.
- **Verdict: kopyalanabilir tek şey TIMING disiplini (Londra/NY overlap, fix/haber ilk dakikalarından kaçınma)
  + risk kuralları (günlük stop ~firma limitinin %60'ı). ORB-parametre süpürmesi = para tuzağı.**

### B14 — Doğrulama metodolojisi (60g 5m, 12 çift)
- **60 gün = 0.24 yıl.** t = SR_ann×√0.24 → **t≥3 için SR_ann≥6.1 (ulaşılamaz).** Bu veri
  strateji-seviyesi anlamlılık KANITLAYAMAZ, yalnız **çürütebilir (falsify).**
- **MinBTL:** N=50 deneme, SR=1.5 → **2.3 yıl** gerek; SR=2.0 → 1.3 yıl. **0.24 yıl 5-10× kısa.**
- **Trade sayısı:** 45%WR/2R → t=3 için **163 işlem**; 70%WR-0.5R scalp → **1.785 işlem.** Yüksek-WR
  scalping KANITLAMASI EN YAVAŞ → işlem sayısı düşükse güvenilmez.
- **DSR örneği:** SR 2.0, N=50 deneme → **DSR=0.62 (0.95 barajını GEÇEMEZ).** Aynı pencere ±10-20%
  parametre oynatmada edge kaybolursa RED.
- **CPCV:** 17.280 bar → 6-10 grup, k=2 → 28-45 OOS yolu; purge=etiket ufku, embargo=feature lookback.
- **Zorunlu geçiş barajları:** ≥8/12 çift aynı işaret; ≥5 walk-forward pencere, ≥%60 pozitif; PBO<0.20;
  DSR≥0.95; 2× spread'te pozitif kalma; kâr tek çift/işlemde yoğunlaşmamalı.
- **Verdict: 60g ile yalnız "ölü" demek güvenilir; "kârlı" demek için gerçek untouched forward pencere ŞART.**

---

## C. KODLAMAYA DEĞER ADAYLAR (öncelik sırasıyla)

| # | Aday | Kol | Kural özeti | Kanıt | Neden umut |
|---|---|---|---|---|---|
| C1 | **EURUSD saat-günü sezonsallığı** | B1 | Yerel-saat depresiasyonu: EUR saatlerinde short, USD saatlerinde long; tek yön/gün, tight spread | **Güçlü** (Breedon-Ranaldo, Ranaldo, QuantRocket net Sharpe 0.7-1.3) | Tekrarlanan TEK net-pozitif intraday FX ailesi |
| C2 | **Filtreli seans-open ORB** (15m kutu, OR/ADR 0.25-0.60, tek yön/gün, gün-trend onayı, time-exit) | B11/B13 | Erken kırılım + ön-yapısal seviye + tüm-gövde kapanış | Orta | Filtresiz ORB ölü ama filtreli + geniş stop maliyete dayanır |
| C3 | **15m sıkışma-armed genişleme-barı** (yön HTF-trendden, 5m yürütme) | B5/B11 | Sıkışma "arm", genişleme barı tetik; asla yön tahmini | Orta (arm) / Zayıf (yön) | R-katı tutarlılığı, az işlem |
| C4 | **Günlük reopen gap-fade** | B12 | Broker-günü ilk saat 4.8 pip açılış; ≥1 pip gap fade; ECN feed + spread filtre | Orta (preprint) | Tek büyük, monoton, çok-yıllık net-sonr |
| C5 | **Tokyo fix (±15 dk, USDJPY)** | B12 | 00:55 UTC fix tevrit; gotobi/ay-sonu | Orta (Ito-Yamada) | +1.8 bp, spread fix'te daralır |
| C6 | **JPY krosları + Donchian ailesi + H1 EMA200 kapısı** | B10/B5 | GBPJPY/EURJPY, stop 2×ATR, H1 trend onayı | Zayıf-Orta | Maliyet/vol oranı en iyi sınıf; H1 kapısı DD düşürür |
| C7 | **Risk-katmanı (alpha değil):** işlem başı 0.25-0.5%, toplam ısı %3, 3+ USD çifti=tek pozisyon, ATR%-eşit-risk sizing | B9/B5/B6 | Sabit-fraksiyonel + korelasyon-saç tıraşı (×0.74 @ ρ0.85) | **Güçlü** | Risk-of-ruin'i neredeyse sıfırlar; yön gerektirmez |

---

## D. KESİN DROP LİSTESİ (kodlanmayacak)

| Aile | Kol | Neden |
|---|---|---|
| Mean-reversion / BB fade / RSI2 | W1,B1 | SSRN OU 10/10 hücre OOS negatif; BB fade PF 0.21 |
| Stat-arb / pairs / üçgen arbitraj | W1,B6 | Cointegration p≈0.17; üçgen 0.6bp vs retail 30-40bp |
| ICT / order-block / FVG / sweep | W1,B13 | FVG totoloji; OB 5.242 işlemde $10k→$571; sweep 18/18 z<0 |
| ML / LSTM / 5m deep nets | B4 | OOS IC +0.004; 60g < MinBTL; meta-labeling 0/42 DSR |
| Post-news drift / news breakout | W1,B4 | Haber = jump, sürüklenme yok; spread ×10-30 |
| Order-flow / CVD / delta (retail) | B3 | Aggressor recoverable değil; R²=0.031 |
| DXY-lead / USD-basket entry | B6 | Eşzamanlı (2-dk'da kaybolur); EURUSD ile döngüsel |
| Gold→AUD / oil→CAD / BTC→FX sinyal | B7 | Eşzamanlı; tek gerçek lag (endeks→JPY 1 dk) erişilemez |
| B4 squeeze 5m / çıplak ATR-breakout | B11 | USDJPY break-even spread −0.92; TTM 5m PF 0.18 |
| Unfiltered London-ORB / Asya-fade | B12,B13 | Kutu Londra'dan önce kırılı; fade %49.4 coin flip |
| Weekend gap fade | B12 | Sun 21:00 quote-var-trade-yok; 5-pip fade −$1.308/5y |
| Martingale / scale-out / refleks BE | B9 | Ruin; expectancy'nin %25-43'ünü yer |
| Latency arb / L2 / co-location | B13 | Altyapı duvarı |
| Carre arbitraj / day-of-week yön | B1,B2 | 0.2-1.0 pip/gün; DOW yön 2005 sonrası öldü |

---

## E. ÖNERİLEN SIRALI PLAN (test için, henüz KOŞULMADI)

1. **C1 (EURUSD saat-günü)** — en yüksek kanıt; tek parite, 15m/1h, günde 1 trade, net-maliyet testi.
2. **C2 (filtreli ORB)** — 15m kutu, OR/ADR bandı, time-exit, London+NY açılışları.
3. **C4 (reopen gap-fade)** — spread-filtreli, yalnız ECN feed.
4. **C6 (JPY + Donchian + H1 kapısı)** — önceki turdan devam; ≥2 ayrık pencere zorunlu.
5. **C7 risk katmanı** — her koşuya uygula (alpha değil, hayatta kalma).
6. Her aday **B14 barajlarından** geçmeli: ≥100 işlem, ≥8/12 çift, ≥%60 WF pencere, 2× spread pozitif,
   DSR/PBO, ±%15 parametre platоsu. **Kısa pencere yalnız eleme, onay için 2+ ayrık pencere.**

**Not:** Bu doküman bir ÖNERİ/ARAŞTIRMA çıktısıdır; hiçbir aday kodlanmadı, hiçbir replay koşulmadı.
Uygulama talimatı gelene kadar canlı politikada değişiklik yoktur (mevcut 4'lü kapsam + JPY Donchian korunur).
