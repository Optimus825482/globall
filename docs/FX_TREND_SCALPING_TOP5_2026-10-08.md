# TREND TAKİP MANTIĞINA UYGUN FOREX SCALPING — EN İYİ 5 STRATEJİ
## Derin web araştırması + 9 paralel araştırma kolu + kendi replay kanıtımız ile sentez

- **Tarih:** 2026-10-08
- **Sahip:** Erkan
- **Yöntem:** 9 paralel araştırma ajanı (her biri farklı bir trend-scalping ailesi), 300+ URL taraması, 6.142–660.005 işlemlik yayınlanmış backtest kanıtları, akademik meta veri API'leri (Crossref/OpenAlex/arXiv), TSFM (Topstep) birincil verisi, BIS raporu + kendi replay motorumuzun 12 FX çifti / 5 pencere ölçümü.
- **Araştırma kolları (ham raporlar):** `outputs/fx_trend_research/A1..A9*.md`
- **Kanıt etiketleri:** [AKADEMIK] · [BROKER/PROP-VERI] · [UYGULAYICI] · [PAZARLAMA-SUPHELI] · [BIZIM-REPLAY] (kendi motorumuz)

---

## 0. ÖNCE KARAR (dürüst çerçeve)

1. **Web'de "en kârlı forex scalping stratejisi" iddialarının büyük çoğunluğu doğrulanamaz.** Kanıt kalitesi etiketi [PAZARLAMA-SUPHELI] olan kaynaklar, ölçülebilir olanların çoğunu gölgede bırakıyor.
2. **Trend takibinin akademik kanıtı güçlü AMA yanlış frekansta:** TSMOM / AQR century kanıtı **çok enstrümanlı sepet + aylık/günlük ufuk** için geçerli (Sharpe ~0,4–1,1). M1–M5 tek parite scalping'e transfer edilmiş hali **kanıtlanmamıştır**.
3. **Maliyet, tüm ailelerin ortak ölüm sebebi.** 5 pip hedefte 0,80 pip round-turn maliyet başabaş kazanma oranını %50'den **%58**'e çıkarır; GBPJPY 15/15 pip hedefte %61,7. Günde 20 işlem × 0,80 pip = yılda **4.000 pip**.
4. **Bizim motorumuzda da hiçbir yeni aday canlıya-alım barajını geçemedi** (30g izole FX, p95 spread: klasik motor **−4.635 $**, PF 0,64, 7.316 işlem).
5. Bu yüzden aşağıdaki "en iyi 5" listesi **kârlılık garantisi değil**, kanıt gücü + FX-scalping uygunluğu sıralamasıdır. Her satırda **durum etiketi** var: DOĞRULANDI / PAPER-ONLY / REDDEDİLDİ / BELİRSİZ.

---

## 1. KANIT ÇERÇEVESİ — Neye "kârlı" diyoruz

| Kanıt seviyesi | Anlamı | Bu raporda örnek |
|---|---|---|
| En güçlü | Hakemli dergi + uzun örneklem + maliyet modeli + OOS | Gao-Han-Li-Zhou (JFE 2018), Hsu-Taylor-Wang (21.195 kural), Hurst-Ooi-Pedersen (1880–2016, 67 market) |
| Güçlü | Bildirili çalışma + net parametre + maliyet/komisyon varsayımı açık | Zarattini & Aziz ORB (1.795 işlem, komisyon sonrası) |
| Orta | Bağımsız uygulayıcı testi, örneklem ve maliyet açık, ama hakemsiz | Tick-Stream NQ (gerçek maliyet, t=2,09), StatOasis SPY (33 yıl) |
| Zayıf | Kuralı var, ölçüm belirsiz, seçim yanlılığı riski | Çoğu blog backtesti |
| Kanıt değil | Satış hunisi, "verified" ama denetlenmemiş hesap | Myfxbook/FX Blue tekil hesaplar |

**Red kriterleri (bu raporun barajı):** <100 işlem · maliyet modeli yok · tek pencere · OOS yok · DSR/PBO düzeltmesi yok · "kazanma oranı" tek başına raporlanmış.

---

## 2. EN İYİ 5 STRATEJİ (kanıt ağırlıklı sıralama)

### #1 — SEANS AÇILIŞ ARALIĞI KIRILIMI (ORB): Londra ve NY açılışları
**Durum: DOĞRULANDI (kanıt gücü en yüksek aile) — ancak FX'te maliyet-sonrası kanıt USDJPY ile sınırlı**

**Mantık:** Seans açılışında fiyat keşfi yoğunlaşır; ilk N dakikanın aralığı, günün yön önyargısını taşır. Aralık kırılırsa devam (continuation) beklenir.

**Kural seti (kaynaklardan çıkarılmış en iyi pratik):**
- **Aralık:** 5 dk (gürültülü, çok sinyal) veya 15–30 dk (temiz, geniş stop). FX'te Asya kutusu (00:00–07:00 UTC) → Londra kırılımı da aynı ailedir.
- **Giriş:** Aralığın **kapanış bazlı** kırılımı (fitil teması değil). Retest girişi de kullanılır ama bağımsız kanıtı yok.
- **Yön:** İlk N dakikalık mumun yönü (sign signal) veya kırılım yönü.
- **Stop:** Aralığın karşı ucu (=R). **Hedef:** 10R veya seans sonu (EoD) — kilit nokta: sabit küçük TP değil.
- **Risk:** İşlem başına %1; 4× kaldıraç sınırı (broker kısıtı).
- **Filtreler:** Hacim/volatilite genişlemesi, OR/ATR genişlik bandı, haber kalkanı (FOMC/CPI/NFP ±15 dk), 10:00 ET sonrası giriş yasağı.

**Kanıt (sayılar kaynaklı):**
- Zarattini & Aziz (QQQ 5-dk ORB, 2016–2023): 1.795 işlem, %51 long, **yıllık alfa %33 (komisyon sonrası, p=0,0025)**, Sharpe 1,18; TQQQ ile %1.484 vs QQQ %169. [UYGULAYICI/SSRN]
- Aynı ekip "Stocks in Play" (7.000+ hisse): **Sharpe 2,81**. [UYGULAYICI]
- "Beat the Market" SPY intraday momentum: **Sharpe 1,33**. [UYGULAYICI]
- Gao-Han-Li-Zhou, *Market Intraday Momentum* (JFE 2018): ilk yarım saat getirisi son yarım saati öngörüyor. [AKADEMIK]
- **FX'e özel (en kritik):** Seeck 2026, *Intraday Momentum in Spot FX and Currency Futures* (SSRN 7008318): Londra açılışı **30-dk sign sinyali 6 enstrümandan 5'inde p<0,001**; JPY taşıma amplifikasyonu β 3,8× büyük; **maliyet sonrası yalnızca USDJPY pozitif kaldı (OOS Sortino +0,748)**. [AKADEMIK]
- 6.142 işlem günü (ES/NQ): 5-dk ORB günlerin %100'ünde kırılır, **%74,3'ünde iki taraf da**; 30-dk ORB continuation ES %64,6 / NQ %67,0; geniş ORB %77,5. [UYGULAYICI]
- Dukascopy M1 (FXAbsolute): EURUSD'de Asya aralığı **%98,7 kırılıyor**, medyan aralık 29,6 pip; 0,25R devam %84,6 / **0,50R %72,3** / 1R %54,1; GBPUSD 0,50R %71,4. [UYGULAYICI]
- Karşı kanıt: Backtrex 10 yıl EURUSD **−%28 (PF 0,87)**, GBPUSD **−%60 (PF 0,72)**; CRTLab 12.221 "sweep" işleminde beklenti **−0,04R**. [UYGULAYICI]
- Tick-Stream (NQ, gerçek maliyet dahil) 15-dk/2R: +205.612 $, t=2,09, PF ~1,1; "81% kazanma" iddialı varyant başabaş. [UYGULAYICI]

**Bizim replay kanıtımız [BIZIM-REPLAY]:** `orb_tp15` (12 FX, p95 spread) 30g: n=106, WR %71,7, **net −120,65 $, PF 0,60, DD 154,81 $**; kısa tarama (10–31 Ağu): n=74, net −57,43 $, PF 0,57. → **Bizim motorun ORB kurgusu (küçük sabit TP, 1,5R) kanıtın önerdiği 10R/EoD çıkışla test EDİLMEDİ.** Bu, listedeki en somut test boşluğumuz.

**Verdict:** Aile olarak en güçlü; FX'te kârlılık şartı **JPY krosları + maliyet sonrası OOS**tur. Bizde PAPER-ONLY, çıkış mimarisi değiştirilerek yeniden test edilmeli.

---

### #2 — LONDRA AÇILIŞI 30-DK MOMENTUM (JPY krosları)
**Durum: DOĞRULANDI (tek maliyet-sonrası pozitif FX kanıtı) — tek çalışma, tek dönem**

**Mantık:** Londra açılışının ilk 30 dakikası, günün akış yönünü belirler; JPY kroslarında taşıma (carry) amplifikasyonu sinyali büyütür.

**Kural seti:**
- Sinyal: 07:00–07:30 UTC kapanışının işareti (pozitif → long, negatif → short).
- Enstrüman: **USDJPY, GBPJPY, EURJPY** (JPY bacağı zorunlu).
- Giriş: 07:30 UTC, sinyal yönünde; çıkış: seans sonu (17:00–21:00 UTC) veya ters sinyal.
- **Maliyet bütçesi:** A6 ölçümü: JPY kroslarında all-in ~1,1–2,65 pip (swap dahil gecelik yasak).

**Kanıt:** SSRN 7008318 — 5/6 enstrümanda p<0,001 (permütasyon), iki ayrı dönemde tutarlı; **maliyet sonrası yalnız USDJPY pozitif, OOS Sortino +0,748**; GBPUSD sinyali ters yönde (JPY taşıma mekanizmasıyla tutarlı).

**Bizim replay kanıtımız:** JPY kolu (GBPJPY+EURJPY) **motordaki tek pozitif pencereleri üretti**: 60g `jp_da_h1` **+71,68 $ (n=118, WR %62,7, PF 1,46, DD 65,77 $)**; `jp_dp_h1` **+54,87 $ (n=102, PF 1,45)**; OOS 30g `jp_dp_h1` **+142,74 $ (PF 2,72, DD 36,4 $)**. **Ama** çapraz pencere (10 Ağu–7 Eyl): `jp_dp_h1` **−27,93 $ (PF 0,66)** → pencereye bağımlı. [BIZIM-REPLAY]

**Verdict:** PAPER-ONLY / DEVAM-TEST. Canlı gölge-defterde 2+ pencere daha birikmeden aktivasyon yok.

---

### #3 — DONCHIAN / N-BAR KIRILIMI + ATR TRAILING + TREND REJİM KAPISI (M15, JPY)
**Durum: Aile DOĞRULANDI (çok enstrümanlı, düşük frekans) — intraday tek-parite hali REDDEDİLDİ**

**Mantık:** N-bar ekstrem kırılımı + "kazananı koştur, kaybedeni kes" → pozitif çarpıklık (skew) üretir.

**Kural seti:**
- Giriş: kapanış > önceki N barın en yüksek high'ı (N=20–40) + ADX≥18 teyidi.
- **Rejim kapısı:** H1 (veya H4) EMA200 yönü tersse giriş yok — "işlem yapmama" kapısı.
- Stop: 2N (N=ATR); Çıkış: chandelier/trailing 2,5–3×ATR **veya** Turtle S1/S2 (10/20-gün dip) — sabit TP kapalı.
- Time-stop + seans sonu flat; gece taşıma yok.

**Kanıt:**
- Hurst-Ooi-Pedersen, *A Century of Evidence on Trend-Following Investing*: 1880–2016, 67 market, ortalama **Sharpe ~0,4**; brüt ~%20, maliyet+ücret sonrası ~%14,3/yıl. [AKADEMIK]
- Moskowitz-Ooi-Pedersen (JFE 2012): 58 vadeli sözleşme, çeşitlendirilmiş TSMOM Sharpe >1 (OOS 1,1). [AKADEMIK]
- Lempérière ve ark.: iki yüzyılda Sharpe 0,80/0,72; **FX alt sepeti 0,47**. [AKADEMIK]
- Baltas-Kosowski: brüt Sharpe 1,15 → maliyet sonrası 1,03 → **post-GFC −0,09**; range-tabanlı volatilite tahmincisi turnover'ı **%17**, sürekli trend kuralı **~%24**, ikisi birlikte **%36,2 azaltıyor (t=13,19)** ve performans cezası yok. [AKADEMIK]
- Karşı kanıt: on-kayıtlı 12 FX çifti H1 testi — **28 konfigün tamamı maliyet öncesi negatif**; EURUSD H4 random-entry'de ATR çarpanı 1/2/3/4 → PF 1,06/0,99/1,04/0,98 (kenar yok); 20-bar kırılımlarının **%94,2'si 60 bar içinde seviyeye dönüyor**; 20-günlük takip getirisi %0,851 → **%0,016**'ya eridi. [UYGULAYICI]
- ATR trailing tek başına: sabit ATR stopunu D1'de 6 varlıktan 5'inde geçemedi; **H1'de 6/6 negatif expectancy**. [UYGULAYICI]
- Kaminski & Lo (JFM 2014): stop kuralı rastgele yürüyüşte **negatif** "stopping premium"; momentum varsa pozitif ve aylık stop kalibrasyonunda getiri +%1,5 / vol −%5 / Sharpe +%20'ye kadar. [AKADEMIK]

**Bizim replay kanıtımız:** H1 EMA200 kapısı, Donchian'ı 60g'de **negatiften pozitife** çevirdi (`da_tp4`: −245,48 $ → `da_tp4_h1`: −79,31 $; JPY'de `jp_da_h1` +71,68 $). Ama aynı konfig çapraz pencerede −52,80 $. [BIZIM-REPLAY]

**Verdict:** İntraday saf hali REDDEDİLDİ; filtreli/trailing'li JPY versiyonu PAPER-ONLY.

---

### #4 — MTF TREND FİLTRESİ + PULLBACK CONTINUATION (M5/M15)
**Durum: BELİRSİZ — mekanik EMA paketi REDDEDİLDİ, filtreli pullback ölçülmedi**

**Mantık:** Ana trend yönünde (HTF bias) geri çekilme sonrası devam hareketini yakala. Daha iyi fiyat, daha küçük stop.

**Kural seti:**
- Bias: H1/H4 EMA200 yönü (kapanmış mum).
- Dizilim: 8/21/50 EMA aynı yönde; fiyat EMA21/50'ye geri çekilir.
- Tetik: kapanışla EMA dizilimini geri kazanma + mum onayı.
- VWAP: **bounce (trend içi, VWAP hiç kaybedilmemiş)** = continuation; **reclaim** = daha düşük güvenilirlik.
- Stop: yapısal dip/tepe veya 1,1–1,5×ATR; Çıkış: trailing + time-stop (sabit 2R DEĞİL).

**Kanıt:**
- Temiz testte mekanik EMA-pullback paketi **negatif**: 7 yıl NQ, 3.458 işlem, 2:1 hedefte **WR %31,0, expectancy −0,1R** (iddia edilen %61,7 idi; fark: aynı mumda stop+hedef artefaktı ve sıfır maliyet varsayımı). [UYGULAYICI]
- Naif VWAP dokunuş/fade: 4 markette 13.801 işlem, **WR %28,9, PF 0,40** (EURUSDT %6,5 WR, PF 0,02). [UYGULAYICI]
- Order-block retest: BTC 4H %45 WR / −0,15R; mekanik majör-FX SMC %38–48 WR. [PAZARLAMA-SUPHELI]
- Kapı etkisi (tek doğrudan ölçüm): SPY taban PF **2,15** → ADX kapısı ile PF **2,6**, ama CAGR %9 → %7,3 ve maruziyet %24 → %7. [UYGULAYICI]
- ADX tek başına anlamsız: 7 motorun 3'ünde işe yaradı, 4'ünde yaramadı, 1'inde kötüleştirdi. [UYGULAYICI]
- **Kanıt boşluğu:** H1/H4 EMA200 kapısının **M5'te PF/DD etkisi hiçbir kaynakta ölçülmemiş.** [A4]

**Bizim replay kanıtımız:** `pb_t25` (pullback, 12 FX) 30g: n=193, net −70,53 $, PF 0,72; `pb_tp2`: n=329, −156,21 $, PF 0,71. → Pullback ailesi bizim motorda **negatif**; ama kurgu sabit TP'li. [BIZIM-REPLAY]

**Verdict:** PAPER-ONLY; önce kapılı/kapısız A/B testi (≥300 işlem) şart.

---

### #5 — VOLATİLİTE SIKIŞMASI → GENİŞLEME KIRILIMI (BBW / NR7 / Keltner)
**Durum: ÇIPLAK HALİ REDDEDİLDİ — yalnızca REJİM/RİSK FİLTRESİ olarak KABUL**

**Mantık:** Düşük volatilite kümelenmesi genişlemeyi önceler → sıkışma sonrası kırılım büyük hareket yakalar.

**Kritik gerçek:** Sıkışma **büyüklüğü** öngörür, **yönü öngörmez.** Bu yüzden tek başına giriş sinyali olarak kullanılamaz; trend filtresi + kırılım teyidi şart.

**Kural seti (yalnız filtre olarak):**
- Rejim kapısı: ATR(14) > 0,8×medyan (ölü piyasa yasağı) ve < 3,0×medyan (panik yasağı); CHOP > 61,8 → işlem yok.
- Giriş (trend filtresi varsa): BBW alt persentil sıkışma + band dışı **kapanış** + EMA50 yön teyidi.
- Stop/Çıkış: 1,5×ATR stop, 1R'de kâr alma yasağı, kazananı koştur, seans sonu flat.

**Kanıt:**
- BBW squeeze kırılımı: 1.010 işlem, kazanma %32,1, **PF 0,79, net −%55,1**, DD %59,7. [UYGULAYICI]
- Keltner/ATR kanal kırılımı: **M5 3.005 işlem → −%98**, **M15 873 işlem → −%83**; yalnızca 1,5× bandı +%4 (tepelik, plato değil). [UYGULAYICI]
- NR7 filtresi (16 yıl NQ 30-dk ORB): PF **1,02** vs filtresiz **1,12**; işlem başına +0,55 vs +2,85 puan → filtre değer katmıyor. [UYGULAYICI]
- ATR breakout EURUSD H4, 13 yıl walk-forward: **27/27 konfigürasyon elendi** (23'ü negatif). [UYGULAYICI]
- Rejim ayrışması gerçek: EUR/USD MS-GARCH rejimleri KS **p=1,35×10⁻¹⁵³**, ama OOS yön bilgi katsayısı yalnızca **+0,0252**; yazarlar modeli "risk aracı, alfa motoru değil" diye konumlandırıyor. [AKADEMIK]
- 1.611 kırılım sinyalinin **%75,5'i** hedefe ulaşmadı, %66,7'si ters döndü — yine de +337R, çünkü kazanan +3,04R / kaybeden −0,97R (asimetri, isabet oranı değil). [UYGULAYICI]

**Bizim replay kanıtımız:** Kısa taramada en iyi görünen `sq_pct10_t25` (+43,15 $, n=52) **OOS'ta söndü**; 30g `sq_t25` n=164 **−47,28 $**, PF 0,81. Klasik aşırı-uydurma imzası. [BIZIM-REPLAY]

**Verdict:** Giriş motoru olarak REDDEDİLDİ; rejim/risk kapısı olarak motora eklenebilir.

---

## 3. ORTAK ZORUNLU KATMANLAR (5 stratejinin hepsi için)

### 3.1 Maliyet kapısı (en sert kısıt)
| Ölçüm | Değer | Kaynak |
|---|---|---|
| All-in ECN maliyeti (Haz 2026) | EURUSD 0,48–0,86 · GBPUSD 0,61–1,45 · USDJPY 0,53–0,90 pip | [BROKER-VERI] |
| Başabaş kazanma oranı | 5/5 pip hedef + 0,80 maliyet → **%58**; 3/5 → %72,5; GBPJPY 15/15 → %61,7 | [UYGULAYICI-hesap] |
| Yıllık maliyet yükü | 20 işlem/gün × 0,80 pip = **4.000 pip/yıl** (EURUSD'nin 59,8 günlük toplam hareketi) | [UYGULAYICI-hesap] |
| Bizim ölçtüğümüz spread (IC Markets demo, 2026-10-07) | EURUSD avg 0,10 / p95 0,10 · GBPJPY avg 0,77 / p95 1,10 · GBPNZD p95 2,10 pip | [BIZIM-OLCUM] outputs/fx_spread_reality.json |
| Maliyet/ATR oranı (neden JPY krosları yaşayabiliyor) | GBPJPY 0,21 vs EURUSD 0,35 | [BIZIM-OLCUM] |
| GBPJPY short swap | −%4,90/yıl ≈ **2,65 pip/gece** → kısa yön gece taşınamaz | [BROKER-VERI] |

**Kural:** İşlem başına beklenen brüt kenar ≥ 2× spread+komisyon; aksi halde kural işletilmez. Maliyet modeli ×1,5 stres testinden geçemeyen aday elenir.

### 3.2 Çıkış mimarisi (kârlılığın gerçek kaynağı)
- **Sabit TP trendi öldürür:** No-TP 1,89 $/işlem ve DD %19,5 iken, %1'lik TP 0,89 $/işlem ve 0,41M $; **hiçbir TP seviyesi baz çizgiyi geçmedi.** [UYGULAYICI]
- **Breakeven edge'in dörtte birini yer:** expectancy +0,80R → +0,59R (−%26); DD −38R → −29R. [UYGULAYICI]
- **567.000 backtest (40 vadeli piyasa, 10 yıl, maliyet dahil):** en iyi çıkış "Stop & Reverse", ikinci breakeven, **chandelier en kötü grupta.** [UYGULAYICI]
- **Time-stop underrated:** çıkış eşiği sıkılaştırılınca DD %37 → %24, maruziyet %38 → %14. [UYGULAYICI]
- Trailing tek başına kenar değil: 660.005 OOS backtestte kombinasyonların yalnızca **%26'sı** al-tut'u geçti. [UYGULAYICI]
- **Doğru taban:** geri çekilmede hayatta kal + trend bittiğinde çık + seans sonu/haber kalkanı + maliyet farkındalığı.

### 3.3 Seans ve haber
- London–NY overlap (13:00–16:00 UTC) en derin likidite; Asya seansı FX girişleri bizim ölçümümüzde zarar üretti (bloklananların gölge PnL'i −5.939 $).
- Yüksek etkili haberden (FOMC/CPI/NFP/faiz) **±15 dk** yeni işlem yok; açık pozisyonda stop BE'ye veya kâr realise.
- Rollover (21:00–22:00 UTC) = hard blackout.

### 3.4 Metodoloji barajı (aday → canlı geçişi)
Her aday için **hepsi** gerekli: ≥2 ayrık pencere pozitif · OOS > 0 · ≥100–300 işlem · DD < 200 $ (izole defter) · gerçek/p95 spread profili · 2× maliyet stresi · DSR/PBO düzeltmesi · HLZ **t>3,0** eşiği · tamamlanmış mum provenance'ı.

---

## 4. BİZİM MOTORUMUZUN KANITI (özet tablo) [BIZIM-REPLAY]

12 FX çifti, izole defter, p95 gerçek spread, 99 slot:

| Pencere | Konfig | n | WR % | Net $ | PF | DD $ |
|---|---|---|---|---|---|---|
| 10–31 Ağu (tarama) | classic | 3.823 | 56,0 | −1.599,57 | 0,72 | 1.761,90 |
| 10–31 Ağu (tarama) | sq_pct10_t25 (en iyi) | 52 | 80,8 | +43,15 | 2,37 | 9,90 |
| 10–31 Ağu (tarama) | orb_tp15 | 74 | 68,9 | −57,43 | 0,57 | 75,19 |
| 10–31 Ağu (tarama) | pb_t25 (pullback) | 193 | 58,0 | −70,53 | 0,72 | 84,91 |
| 30 gün | classic | 7.316 | 53,6 | **−4.635,09** | 0,64 | 4.668,71 |
| 30 gün | lb_tp15 (en iyi) | 144 | 76,4 | +19,38 | 1,07 | 88,57 |
| 30 gün | orb_tp15 | 106 | 71,7 | −120,65 | 0,60 | 154,81 |
| 60 gün | **jp_da_h1** | 118 | 62,7 | **+71,68** | **1,46** | 65,77 |
| 60 gün | **jp_dp_h1** | 102 | 68,6 | **+54,87** | **1,45** | 110,43 |
| 60 gün | da_tp4_h1 (H1'siz) | 669 | 68,6 | −245,48 | 0,77 | 339,29 |
| OOS 30 gün | jp_dp_h1 | 76 | 76,3 | +142,74 | 2,72 | 36,40 |
| **Çapraz pencere (10 Ağu–7 Eyl)** | **jp_dp_h1** | 66 | 62,1 | **−27,93** | **0,66** | 37,14 |

**Okuma:** Tek pozitif aile **Donchian + H1 EMA200 kapısı, JPY krosları**; ama aynı konfig pencere değişince negatife dönüyor → **pencere bağımlı, canlı barajı geçmiyor.** ORB, pullback, squeeze, NR7 ve klasik motor FX'te maliyet sonrası negatif.

---

## 5. REDDEDİLENLER (kanıtla kapandı)

| Aile / Kural | Neden reddedildi |
|---|---|
| Mean-reversion (BB fade, OU) | 10/10 sembol-TF hücresinde OOS negatif; BB fade PF 0,21 |
| Stat-arb / pairs / üçgen arbitraj | Cointegration çoğu FX çiftinde p=0,17; üçgen edge 0,6bp vs retail 30–40bp |
| ICT / order-block / FVG | FVG "dolum" totolojisi (%97–99 bar); order-block 1.000 mekanik testte %38–48 WR |
| Carry / gece taşıma (intraday sistemde) | Swap 0,2–1,0 pip/gün + rollover blackout; GBPJPY short −2,65 pip/gece |
| Haber-entry | 580 testte %29 "anlamlı" = şans seviyesi; takvim yön değil volatilite sinyali |
| Naif VWAP fade/dokunuş | 13.801 işlemde WR %28,9, PF 0,40 |
| Çıplak sıkışma kırılımı (BBW/Keltner/ATR breakout) | PF 0,79 / −%98 (M5) / 27-27 walk-forward elenmesi |
| Mekanik EMA-pullback %61,7 iddiası | Temiz testte WR %31,0, expectancy −0,1R |
| Sabit küçük TP (2R) trend paketleri | A3/A5/A8 kanıtı: TP eklemek her seviyede sistemi kötüleştirdi |
| Gösterge-tabanlı "trend gücü" (HMA, Ichimoku, Supertrend) tek başına | HMA 4H net −%48; Ichimoku OOS taban %19,1 (taban %20,1); Supertrend WR %40,7–43,2 |

---

## 6. PROP VE GERÇEK PERFORMANS KANITI (neden şüpheci olmalı)

- **Topstep 2025 (tek denetlenebilir birincil kaynak):** Combine → Funded **%16,8** (deneme düzeyi); kişi düzeyinde %51,8; Funded içinde payout alan **%33,3**; Express Funded → Live **%0,71**. [BROKER/PROP-VERI]
- **FTMO "~%10 pass rate" rakamı:** firma pass-rate yayınlamıyor → dolaşımdaki %8–17 **doğrulanmamış** [PAZARLAMA-SUPHELI].
- **Payout ≠ kâr:** %33,3 (funded içinde) ile ~%7 (tüm challenge alıcıları) farklı paydalardır.
- **Bağımsız doğrulama yok:** Myfxbook doğrulaması hesap bazlı, firma kendi uyarısını koyuyor ("might have some inaccuracies"); seçim yanlılığını engellemiyor.
- **Gün içi trader gerçeği:** Tayvan 1992–2006: net ücret toplamı 15 yılın **her yılında negatif**, gün içi traderların **<%1'i** net ücret sonrası tahmin edilebilir pozitif; Brezilya: 300+ gün devam edenlerin **%97'si** zarar etti. [AKADEMIK]
- **Backtest denetimi:** DSR/PBO çerçevesi + HLZ **t>3,0** eşiği; deneme sayısı (N) açıklanmadan bulunan Sharpe "keşif" sayılmaz. [AKADEMIK]

---

## 7. UYGULAMA YOL HARİTASI (paper-only)

1. **Faz 0 (ön koşul):** Spread/komisyon/slippage'ı kendi hesabımızdan ölç (`outputs/fx_spread_reality.json` zaten var; 24–72 saat daha biriktir).
2. **Faz 1:** #1 ve #2'yi **çıkış mimarisi düzeltilmiş** halde replay'e al: 10R/EoD veya trailing, sabit küçük TP kapalı, time-stop açık.
3. **Faz 2:** JPY kolu (#2/#3) için 2 ayrı OOS penceresi daha; ≥300 işlem; 2× maliyet stresi.
4. **Faz 3:** #4 ve #5 yalnız **filtre** olarak A/B testi (kapılı vs kapısız, aynı girişler).
5. **Faz 4:** Barajı geçen tek konfig canlı gölge-defterde 4 hafta; sonra MT5 demo; canlıya geçiş **yalnızca Erkan onayı ile**.

**Kill kriteri:** İki pencerede biri negatifse, DD > 200 $ ise veya 2× maliyet stresinde PF < 1,1 ise kol kapatılır — "bir umut daha" yok.

---

## 8. ARTEFAKTLAR

- Ham araştırma raporları: `outputs/fx_trend_research/A1_orb_seans_kirilimi.md` … `A9_prop_gercek_performans.md` (+ `_ozet.md` özetleri, `raw` klasörlerinde indirilen kaynaklar)
- Bu sentez: `docs/FX_TREND_SCALPING_TOP5_2026-10-08.md`
- Replay kanıtı: `outputs/fxsweep/_summary__*.json`, `outputs/replay_cache_60d_fxwide.json`
- Maliyet kanıtı: `outputs/fx_spread_reality.json`, `outputs/fx_spread_p95.json`
- Önceki kalibrasyon planı: `FX_KALIBRASYON_PLANI.md`, `docs/FX_STRATEJI_ARASTIRMASI_2026-10-08.md`
