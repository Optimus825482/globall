# FX MAJÖRLERİ İÇİN YENİ SİNYAL AİLESİ ARAŞTIRMASI (2026-11-10)

**Neden buradayız:** bar-tabanlı trend/kırılım/geri-çekilme ailelerinin majörlerde kenarı **ölçüldü ve yok** (replay PF 0.26 → 0.28; parametre oynatmak yalnız isabet↔payoff ödünçleşmesini kaydırıyor). Ölçülen tek gerçek kenar: RADAR × {USTEC, XAUUSD, US30} (+0.12…+0.22R, t=2.7-5.3). Bu rapor **yeni bilgi kaynağı** arayışıdır: 4 paralel araştırma kolu (tick/mikroyapı · seans/fixing · olay-makro sürpriz · çapraz varlık) + **kendi verimizde yapılan falsifikasyon testleri**.

**Yöntem disiplini:** her iddia (a) kaynak doğrulaması (Crossref/DOI + `gh api`), (b) kendi verimizde ölçüm, (c) **kontrol grubu** ve (d) **maliyet düşülmüş** sonuç ister. Kontrolsüz takvim iddiası kanıt sayılmaz.

---

## 0) KENDİ ÖLÇÜMÜMÜZ — öne çıkan bulgu: **01:00 UTC Tokyo-sabahı USD talebi**

`scripts/fx_family_probe.py --family hourofday --tf H1 --years 5` (1.290 gözlem/sembol/saat; **trend arındırılmış**: sembolün 5 yıllık ortalama saatlik getirisi düşülmüş):

| sembol | saat (UTC) | demean net | t | n | maliyet/tur | maliyet sonrası |
|---|---|---|---|---|---|---|
| GBPUSD | **01:00** | **+2.383p** | **10.68** | 1297 | 0.90p | **+1.48p** |
| EURUSD | **01:00** | +1.470p | 7.33 | 1297 | 0.80p | +0.67p |
| USDJPY | **01:00** | +2.569p | 6.35 | 1297 | 1.21p | +1.36p |
| XAUUSD | **01:00** | +86.0p ($8.6) | 3.23 | 1290 | 16.0p | +$7.0 |
| EURUSD | 00:00 | +0.905p | 7.11 | 1294 | — | rollover saatinde (spread patlar) |
| GBPUSD | 00:00 | +0.774p | 4.48 | 1294 | — | rollover saatinde |

**Okuma:** dört ayrı varlıkta **aynı saat** (01:00 UTC = 10:00 JST, Tokyo sabahı) pozitif ve t istatistikleri çok yüksek; 24 saat × 4 sembol = 96 hücre taradığımız için Bonferroni eşiği ~t=3.5 → **çoğu hücre onu geçiyor**. Mekanizma literatürle tutarlı: Breedon & Ranaldo (JMCB 45(5):953-965, 2013) yerel seans saatlerinde yerel para biriminin **değer kaybettiğini** ölçüyor; Ito & Yamada (JIE 109:214-234, 2017) Tokyo fix çevresinde kalıcı USD alım dengesizliği buluyor. 01:00 UTC = Tokyo sabahı ⇒ JPY satışı + USD talebi ⇒ **tüm USD-majörleri aynı yöne** (long USD) taşır — bu, tek sembole bağlı olmayan bir "ortak faktör" sinyalidir.

**Açık kalan 3 doğrulama (bu yüzden henüz CANLI DEĞİL):**
1. **Yıllık kırılım** — etki 2021-2026 boyunca mı kalıcı, yoksa faiz diferansiyeli/kampanya artefaktı mı? (yıl yıl t ve ortalama isteniyor)
2. **Rollover tuzağı** — 00:00 UTC saatinde broker rollover'ı spread'i 10-30× açar; ölçüm p50 spread kullanıyor. 01:00 temiz görünüyor ama giriş/çıkışın **tick ile** doğrulanması şart.
3. **Kapsam çakışması** — mevcut `eurusd_tod` / `tokyo_fix` kollarımız bu pencereyi zaten kullanıyor olabilir; canlı defterde 01:00 saatinde işlem var mı bakılmalı.

---

## 1) ÇÜRÜTÜLEN ADAY: Tokyo fix "gotobi" takvimi (dürüst negatif)

Blog/YouTube iddiası: gotobi günlerinde (ayın 5/10/15/…/30'u) Tokyo fix öncesi USDJPY'de +4.5 pip/pencere, gross PF 1.62; fix SONRASI short ile PF 2.2.
**Kendi ölçümümüz** (`--family gotobi --tf H1 --years 5`, USDJPY/EURJPY/GBPJPY/EURUSD/USDCHF, 352 pencere, kontrol = aynı saatlerde gotobi OLMAYAN iş günleri):

| pencere | sonuç (maliyet sonrası) | kontrol | yorum |
|---|---|---|---|
| gotobi öncesi LONG (22:00→00:55) | −0.9p … −6.9p (t=−0.2…−3.2) | −3.1p … −5.9p | **kenar YOK** (bazı sembolde kontrolden de kötü) |
| gotobi sonrası SHORT (00:55→01:30) | −3.4p … −10.5p (t=−10…−21) | −3.8p … −10.1p | **ters yönde**; kontrolden ayırt edilemiyor |

**Sonuç:** iddia verimizde **reproduce edilmedi**. İki olası neden: (a) fix-sonrası pencere 35 dk → H1 çözünürlüğü yetersiz (bu test **sonuçsuz**, çürütülmüş değil); (b) 2021-2026'da etki tükenmiş (blog verileri daha eski). Derin M1 gerekiyor: terminalde M1 geçmişi yalnız ~3 ay (`maxbars=100000`), H1/D1'de 5 yıl var → **M1 derinliği ayrı bir iş** (Dukascopy tick arşivi ya da terminal grafik geçmişi indirmesi).

---

## 2) ADAY LİSTESİ (kaynak + mekanik spec + maliyet uyumu + yanlışlama)

### P1 — veri elimizde, hemen ölçülebilir
1. **`tokyo_morning` (01:00 UTC ortak faktör)** — §0. Mekanik: 01:00 UTC'de USD-majörleri + XAUUSD long, 02:00 UTC kapanış; sepet olarak (tek sembol riski yok); SL 1×ATR(1h), günlük 1 işlem/sembol. Maliyet 0.7-1.5p/tur, ölçülen net +0.7…+1.5p (XAU +$7). **Kabul kapısı:** yıllık kırılımda ≥4/5 yıl pozitif + tick doğrulaması + replay A/B PF>1.0.
2. **Tick-rule imzalı akış (Evans & Lyons tabanlı OFI vekili)** — kaynak: "Order Flow and Exchange Rate Dynamics", *JPE* 110(1):170-180, 2002 (DOI 10.1086/324391, doğrulandı). Mekanik: `dir_t = sign(mid_t − mid_{t−1})`, `SF = Σ dir·tick_volume` (5-15 dk kova), z>2 + spread normalin ≤1.2×'i ise yön yönünde giriş, SL 1.5×ATR(kova), hedef 2R. Veri: **bid/ask tick elimizde var**. DİKKAT: gerçek aggressor/L2 derinliği yok → **microprice ve klasik OFI (queue imbalance) uygulanamaz** (Cont-Kukanov-Stoikov, JFE 12(1):47-88, 2014 derinlik ister). Yanlışlama: sentetik sabit-katsayılı flow→fiyat etkisi enjekte et + replay A/B.
3. **Maliyetsiz yön/rejim kapıları** (yeni bacak yok, mevcut sinyalleri *keserek* iyileştirir): (a) ΔUS10Y + ΔDXY aynı işaretteyse yalnız o yönde izin ver (Obstfeld & Zhou, BPEA 2022); (b) VIX üst tercilede carry/reversal aileleri kapalı (Brunnermeier-Nagel-Pedersen, NBER 14473); (c) korelasyon rejimi > μ+2σ ise göreli-değer aileleri kapalı. Veri: hepsi mevcut (`market_pulse`, `forex_correlation`). **Ayrıca `symbol_info().swap_long/swap_short` gerçek taşıma verisi elimizde ve hiç kullanılmıyor.**
4. **Makro sürpriz devamı (t0+90-180 sn giriş)** — kaynak: Andersen-Bollerslev-Diebold-Vega, *AER* 93(1):38-62, 2003; Faust-Rogers-Wang-Wright, *JME* 54:1051-1068, 2007; Evans & Lyons, *JFE* 88(1):26-50, 2008 (etkinin ~2/3'ü order flow ile, kademeli emilim). Mekanik: `|surprise| ≥ 1.5σ` (aynı `title_key`, `calendar_surprises` tablosu **elimizde**), giriş **sıçramadan 90-180 sn sonra** (spread normale dönerken), yön = sürpriz işareti × sembol yönü, SL `max(1.2×ATR_1m, ilk dakika aralığının %50'si)`, TP 1.5-2R. Yanlışlama: sentetik sürpriz serisi + gerçek replay A/B (`news_bias` açık/kapalı baseline). **Haber anında giriş yapan "sıçramayı yakala" aileleri maliyetle ölür** (spread 3-10×; Bessembinder 1994, Wei 1991) — bu yüzden t0+90 sn şart.

### P2 — veri var ama ölçüm/kod gerekiyor
5. **Ay sonu WMR fix geri dönüşü** — kaynak: Krohn-Mueller-Whelan, "Foreign Exchange Fixings and Returns around the Clock", *Journal of Finance* 79(1):541-578, 2024 (DOI 10.1111/jofi.13306, **doğrulandı**); Melvin & Prins, *JFM* 22:50-72, 2015. Mekanik: ayın son iş günü 15:00 UTC, yön = S&P MTD diferansiyeli, çıkış 16:05-17:00 UTC. Yılda ~50-70 işlem → maliyet yükü en düşük aday. Kontrol: ayın 3. iş günü + |diferansiyel|<%1 aylar (PF<1 çıkmalı).
6. **Lee-Mykland sıçrama tespiti + bipower rejim** — kaynak: *RFS* 21:2535-2563, 2008. Tick mid'den hesaplanır (veri var). Jump sonrası devam/fade ayrımı ölçülebilir; parametre duyarlılığı riski yüksek.
7. **Seans-saati yön eğilimi (Breedon-Ranaldo)** — §0'ın genellemesi; Asya/Londra/NY pencereleri için aynı demean testi `--family hourofday` ile yapılır (pencere bazlı genişletme).

### P3 — ilginç ama kanıt zayıf/veri eksik
8. **FOMC iki faz (statement → basın toplantısı)** — Gómez-Cram & Grotteria, *JFE* 143(3):993-1025, 2022. Veri var, olay sayısı az (yılda 8).
9. **Merkez bankası konuşma tonu (LLM)** — Ahrens ve ark., *J. Econometrics* 249:105921, 2025. **Bizde transcript akışı YOK**; ayrıca `yuyongkim/fomc-turning-points` reposu metin tek başına baseline'ı yenmiyor (negatif kanıt).
10. **Çapraz varlık: US10Y/DXY yön vetosu + VIX rejimi** (§2.3'te filtr olarak P1, tek başına aile olarak P3).
11. **Hawkes/quote-varış yoğunluğu** — `X-DataInitiative/tick` (618★, BSD-3, aktif 2026-11-09, doğrulandı). FX'te trade olayı yok → quote sürecini modeller; yön bilgisi ayrıca gerekir.

---

## 3) ELENENLER (kanıtlı gerekçeyle)

| aday | neden elendi |
|---|---|
| Microprice / klasik OFI / queue imbalance | **L2 derinlik (bid/ask size) gerekir**, FX spot'ta yok; MT5 `COPY_TICKS_ALL` yalnız fiyat verir |
| Sub-saniye lead-lag / üçgen arbitraj | Foucault-Kozhan-Tham: 172.044 fırsat, **medyan ömür 890 ms**, kâr 1.4-1.6 bps → bizim maliyetimiz 0.08-0.15R ile yapısal kayıp (Poutré-Dionne kârı LOB+kolokasyon ile alıyor) |
| SMC/ICT "liquidity sweep → dönüş" | Ölçülmüş kanıt yok ("Smart Money or Costly Folklore?" özeti); Osler (*JF* 2003 / *JIMF* 24(2):219-241, 2005) yuvarlak seviye kırılımında **devam** (kaskad) buluyor, dönüş değil |
| Carry/momentum'un 5m-1h'e indirgenmesi | Menkhoff ve ark. ufku 1-12 ay; Rob Carver: "birkaç günlük hızlı momentum kârlı değil, maliyeti yüksek" |
| COT aşırı-pozisyon kontraryan | FX-majör bazlı hakemli doğrulama **bulunamadı** |
| `mlfinlab` bağımlılığı | NOASSERTION lisans + 2023'te donmuş |
| EURUSD vs GBPUSD "spread mean reversion" | Cebirsel olarak EURGBP pozisyonu demek; FX'te eşbütünleşme kanıtı (hisse senedi literatürünün aksine) doğrulanamadı |

---

## 4) Yeni araçlar (bu araştırma turunda yazıldı)

| betik | ne yapar |
|---|---|
| `scripts/fx_family_probe.py` | Takvim/saat ailelerini **kendi verimizde, maliyet düşülmüş ve kontrollü** ölçer: `--family gotobi|hourofday|eom`, `--tf`, `--years`; kontrol = aynı saatlerde etkisiz günler + rastgele gün seti; JSON çıktı |
| `scripts/fx_import_mt5_bars.py` | MT5 → `historical_candles` (5m/1m/…) bar aktarımı; replay'i ağdan kurtarır (60 gün/40 sembol = 454.587 bar) |
| `scripts/fx_symbol_expectancy.py` | Gerçek defterden sembol/kanal bazlı R beklentisi + ölçülen maliyet + kararlılık yarısı |
| `scripts/fx_payoff_compare.py` | Replay raporlarını **payoff/break-even** gözüyle karşılaştırır (PF yerine asıl metrik) |

---

## 5) Önerilen sıra

1. **01:00 UTC ailesini kabul kapısından geçir** — yıllık kırılım (5 yıl), tick ile giriş/çıkış fiyatı doğrulaması, sepet (4 sembol) portföy testi, replay A/B. Geçerse: `--entry-mode`'a yeni kol (mevcut motorun dışında, zaman-tabanlı) + gölgede 2-4 hafta.
2. **Tick-rule imzalı akış** (P1 #2) — FX majörlerinde yeni bilgi kaynağı; tick'ten hesaplanıp IC + replay A/B ölçülür.
3. **Maliyetsiz kapı üçlüsü** (#3) — mevcut sinyalleri keserek iyileştirir; replay A/B'de ΔPF ≥ +0.10 aranır.
4. **Makro sürpriz devamı** (#4) — takvim sürpriz tablosu hazır, t0+90 sn kuralı maliyet-uyumlu.
5. **M1 derinliği** (gotobi fix-sonrası pencere + tick doğrulaması için) — Dukascopy tick arşivi ya da terminal geçmiş indirmesi.

**Kural:** hiçbir aday bu kapıları geçmeden canlıya alınmaz; her aday için "kontrol grubu" ve "maliyet sonrası" şartı zorunludur.

---

## 6) UYGULAMA TURU — (a) RADAR sızıntıları ve (b) haber ailesi ÖLÇÜLDÜ

### (a) RADAR/mevcut hat sızıntıları — 2 gerçek düzeltme (commit f9dca4ed)

**1. Kalite kalkanındaki TERS MANTIK (canlı, kripto dalı):**
```python
max_dist = 0.85 if score >= 80.0 else 0.30     # skor ≥80 → FOMO'ya 3× izin
min_body = 0.25 if score >= 80.0 else 0.35     # skor ≥80 → zayıf gövdeye izin
```
Canlı RADAR defterinde skor **ters** çalışıyor: skor <90 → **+0.204R**, 90-95 → +0.053R, 96+ → **−0.065R** (n=468). Yani "yüksek skor" pratikte "daha uzamış (geç) giriş" demekti. **Düzeltildi:** skor artık kalkanı gevşetmiyor (tek tip sıkı eşik 0.30/0.35).
⚠️ **Replay A/B sonuçsuz çıktı** — çünkü replay `asset_quality_gate`'e `score` **geçmiyor** (`score=0` → eski kod da sıkı dalı kullanıyordu). Yani bu değişiklik **canlı defterden** doğrulanacak (deploy sonrası skor kovası beklentisi); harness boşluğu ayrı iş.

**2. XRPUSD kara listeye eklendi:** canlı RADAR'da n=48, isabet **%22.9**, −0.116R — aynı kanalda BTCUSD %69.4. %22.9 isabette başabaş için **RR>3.4** gerekir. (Not: XRP kripto allowlist'inde; yasak ölçümle gerekçeli, boş listeyle geri alınabilir.)

**3. FRS/fırsat kanalı (−0.177R, t=−2.51): SEMBOL YASAKLAMADIM.** Ölçüm: kanalın negatifliği sembole özgü değil (her sembol hücresi n=5-11 ve işaret karışık: GBPUSD +0.234 / AUDJPY −0.395 / EURGBP −0.261). Orada sembol kesmek curve-fitting olurdu. Kanalın geometrisi farklı: medyan SL 26.5p, TP 36.9p, RR 1.48, isabet %49.5 → gerçekleşen kazanç RR'ın çok altında (kazanan erken kesiliyor). Doğru iş: kanalın BE/trailing davranışını ölçmek — sıradaki tur.

### (b) Haber/sürpriz ailesi — `scripts/fx_news_probe.py` (kontrol gruplu ölçüm)

Kural: `calendar_surprises` (z cinsinden sürpriz) → sürpriz yönünde, **t0+90 sn** giriş, 60 dk tutuş, gerçek maliyet düşülmüş. 40 olay / 124 parite-işlem:

| | sonuç |
|---|---|
| TOPLAM net | **−2.06 pip/işlem (t=−1.96)** |
| En kötü | USDJPY −5.92p (t=−2.39), EURUSD −3.12p, EURJPY −18.3p (n=5) |
| En iyi | USDCAD +1.71p (n=20, t=0.49), GBPJPY +5.43p (n=6) |
| **Kontrol 1 (ters yön)** | net −1.45p → **ters yön de kaybediyor** |
| **Kontrol 2 (|z|<0.5)** | net −3.94p |
| **Kontrol 3 (saat kaydırma)** | net **−0.33p** → olay anı, rastgele saatten **daha kötü** |

**Okuma:** brüt etki ≈ **0.4 pip**, maliyet ≈ **1.7 pip** → sürpriz yönünde devam **yok**; ters yönde de yok (maliyet ikisini de yiyor). Literatürün en güçlü olduğu CPI/NFP/FOMC olayları bu yerel örneklemde **yok** (yerel tablo CAD/CHF/GBP ikincil göstergeleri ağırlıklı; 3 yıldızlı yalnız 11 olay) ve M1 derinliği ~3 ay. Yani **"bu örneklemde kenar yok"** — "hiç yok" değil. Prob sunucuda (tam takvim + daha derin geçmiş) koşulmaya hazır.

**Sonuç:** iki kol da dürüst biçimde kapandı: (a) canlıda iki somut hata düzeltildi, (b) haber ailesi bu örneklemde maliyeti aşamadı.

---

## 7) FRS KANALI ve "giriş kalitesi" ÖLÇÜMÜ — ayar tükendi, sebep GİRİŞ

### 7.1 FRS çıkış davranışı (canlı defter, M1'den MFE hesabı, n=93 FRS / 871 RADAR)

| kanal | gerçek R | **medyan MFE** | medyan hedef | MFE≥1R oranı | çıkış dağılımı |
|---|---|---|---|---|---|
| RADAR | −0.067R | **0.41R** | 0.81R | %12.6 | SL 803 · EA 62 · TP 6 |
| FRS | −0.177R | **0.28R** | **1.49R** | **%10.8** | SL 64 · EA 26 · TP 3 |

**Hipotez yanlış çıktı:** sorun "kazananı erken kesmek" değil — FRS işlemleri **hiç gitmiyor** (medyan lehte hareket 0.28R ≈ gürültü) ve hedef 1.49R, yani ulaşılması imkânsız bir hedef.

### 7.2 Hedef politikası matematiği (MFE dağılımından — çıkış kuralından BAĞIMSIZ kanıt)

| kanal | TP=0.3R | TP=0.5R | TP=0.7R | TP=1.0R | TP=1.5R |
|---|---|---|---|---|---|
| RADAR | −0.409 | −0.556 | −0.703 | −0.807 | −0.897 |
| FRS | −0.399 | −0.532 | −0.671 | −0.785 | −0.866 |

Ulaşma olasılıkları: FRS P(MFE≥0.5R)=%31.2, P(MFE≥1.5R)=%5.4 — **başabaş için gereken %67 / %40**. Yani **hiçbir TP ayarı bu kanalları pozitife çeviremez**; bu, "çıkış parametresi" hipotezlerinin (TP genişliği, trailing, BE) matematiksel olarak kapandığı yerdir.

### 7.3 Giriş kalitesi öngörülebilir mi? (1.074 işlem, hedef = MFE≥0.5R, taban oran %28.9)

- **Skor: TAMAMEN DÜZ** — çeyrekler %29.5 / %28.0 / %28.7 / %29.3. Yani skor seçicilik üretmiyor (canlı defterde "ters" görünmesinin sebebi de bu: bilgi taşımıyor, kalite kalkanı gevşetmesi ayrı kusurdu).
- Stop mesafesi: küçük stoplar %40.7 ↔ büyük stoplar %17.4 (sembol vekili).
- Tutma süresi (sonradan bakıldığında): %21.3 ↔ %36.3.
- **Çok değişkenli lojistik (skor, stop, saat, yön) 5-kat CV AUC = 0.576 ± 0.053** → yazı-tura.

**Sonuç:** mevcut giriş-anı özellikleriyle lehte hareket öngörülemiyor. Bu yüzden:
1. Çıkış/hedef ayarları **kapandı** (7.2 matematiksel).
2. Basit özelliklerle seçicilik **kapandı** (7.3).
3. Kalan kaldıraç: (a) **daha zengin giriş özellikleri** (bağlam: DXY/seans/volatilite rejimi, takvim yakınlığı, HTF yapı — mevcut Forex ML özellik seti IC≈0.22 veriyordu), (b) **kanıtlanmış kapsama yoğunlaşma** (RADAR × USTEC/US30/XAUUSD, t=2.7-5.3 — tek istatistiksel anlamlı kenar).

### 7.4 Uygulanan tek değişiklik
**Kanıt kapısı (abstain gate) varsayılanı `off` → `shadow`** (davranış DEĞİŞMEZ; yalnız "engellerdi" logu). Gerekçe: 7.2/7.3 ölçümü kapının ne söyleyeceğini artık değerli kılıyor. `enforce` hâlâ iş kararı.

---

## 8) SEÇİCİLİK MODELİ (MFE etiketi) — zayıf sinyal, ama KARARI netleştirdi

`scripts/fx_selectivity_probe.py` — 4.297 canlı işlem, etiket **MFE ≥ 0.5R**, özellikler yalnız giriş anında bilinenler (saat/gün, yön, skor, stop, maliyet/stop, son 30/60 dk momentum + volatilite, 60 dk içindeki konum), **kronolojik** %70/%30 ayrım, permütasyon kontrolü.

| ölçüm | değer |
|---|---|
| Taban oran P(MFE≥0.5R) | %33.5 |
| **OOS AUC (kronolojik)** | **0.592** |
| Permütasyon AUC (kontrol) | 0.508 |
| Eşik p≥0.3 | kapsam %75, P(hit) %38.2 → gereken TP 1.62R → **yetmiyor** |
| Eşik p≥0.5 | kapsam %7, P(hit) %50.6 → gereken TP 0.98R → **sınırda/breakeven** |

**Ulaşma eğrisi (test kümesi, exit-politikasından bağımsız):**

| kesit | n | P(≥0.3R) | P(≥0.5R) | P(≥1R) | P(≥1.5R) |
|---|---|---|---|---|---|
| TÜMÜ | 1290 | 52.9% | 34.3% | 10.9% | 4.8% |
| RADAR | 1082 | 53.1% | 34.8% | 11.2% | 5.0% |
| **RADAR×(USTEC/US30/XAU)** | 310 | 41.0% | 22.9% | 8.1% | 1.6% |
| RADAR×(XAU/BTC) | 329 | 56.8% | 37.4% | 7.9% | 1.8% |

**Kritik okuma:** "kanıtlı üçlü"nün MFE eğrisi ortalamanın **altında** — çünkü o kolların kenarı **çok küçük kazançlarda yüksek isabet** (US30 %91.7 isabet / ortalama kazanç 0.29R; USTEC %95.7 / 0.20R). MFE-eşiği çerçevesi bu kolları **yanlış ölçer**; onların gerçek R-beklentisi pozitif (t=2.74/5.28/2.72) ve mevcut trailing/BE politikası o küçük kazançları zaten topluyor.
Öte yandan R-beklentisi negatif olan kümeler (FX majörleri, FRS, LBRK, Scalper/FVG mirası) için **hiçbir hedef eşiği** başabaşı geçmiyor.

**Sonuç — üç kapı da kapandı:** (1) çıkış/hedef ayarı, (2) basit özelliklerle seçicilik (AUC 0.58), (3) zengin özelliklerle seçicilik (AUC 0.59, en iyi kesitte dahi breakeven). Geriye **kapsam kararı** kalıyor: kanıtlı alt kümede (RADAR × USTEC/US30/XAUUSD + Tokyo pencereleri) yoğunlaşmak; R-beklentisi negatif kümelerde işlem açmamak.

---

## 9) KOL DOSYASI + BACKTESTER — Tokyo penceresi R cinsinden ne veriyor? (2026-11-10)

**Yeni araç:** `scripts/fx_arm_backtest.py` — `app/arms/*` kolunu **look-ahead'siz** ölçer:
sinyal bar `i` → giriş **bar `i+1` açılışı**; SL = `k×ATR(14)`; çıkış SL veya `hold_bars`;
maliyet (tick p50 spread + komisyon) tur başına düşülür; **bar içi SL önce** (muhafazakâr);
`--shift N` ile **kontrol grubu**. Çekirdek 5 known-answer testiyle kilitli
(`backend/tests/test_arm_backtest.py`).

`tokyo_window` kolu, 5 yıl H1, `hold_bars=1`, 4 sembol (7.767 işlem):

| varyant | isabet% | beklenti R | t | PF |
|---|---|---|---|---|
| **SL = 1.5×ATR (canlı varsayılanı)** | 47.7 | **+0.002** | 0.25 | 1.14 |
| SL = 1.0×ATR | 45.2 | −0.005 | −0.43 | 1.11 |
| SL = 0.6×ATR | 38.4 | −0.016 | −0.97 | 1.05 |
| SL = 3.0×ATR | 48.7 | −0.003 | −0.61 | 1.11 |
| **KONTROL: sinyal 5 bar kaydırılmış** | 49.9 | **−0.007** | −1.21 | **0.89** |

**Okuma (dürüst):**
1. **Kontrol grubu çöküyor** (PF 1.14 → 0.89) → zamanlama etkisi verinin genel eğilimi değil, **gerçek**.
2. Ama **hiçbir stop boyu R'yi pozitife çekmiyor**; en iyi varyant +0.002R (t=0.25) ≈ **başabaş**.
   Nedeni: ölçülen etki ~**+1.5 pip/saat**; 1 saatlik hareketin ATR'si ~8-12 pip olduğu için etki
   stop gürültüsünün içinde kalıyor (maliyet ~1 pip).
3. **Sonuç:** Tokyo penceresi **standalone işlem kolu olarak kâr motoru değil**. Doğru kullanım:
   **zaman filtresi/ağırlığı** — o saatlerde diğer sinyallere izin vermek/kısıtlamak, veya çok
   küçük stopla saat-içi ölçek. Canlı `tokyo_drift` kolu **kalabilir** (negatif değil, t=0.25),
   ama **boyut artırılmamalı**; bir sonraki adım: diğer kollar için "01:00 UTC penceresi" filtresini A/B etmek.
4. Metodolojik not: bu, "pip düzeyinde anlamlı (t=10.7) etki" ile "işlem R'sinde anlamlı kenar"
   arasındaki farkın **ölçülmüş** örneğidir; bir etkinin büyüklüğü, hedeflediği stop geometrisine
   göre değerlendirilmeden strateji sayılmamalı.
