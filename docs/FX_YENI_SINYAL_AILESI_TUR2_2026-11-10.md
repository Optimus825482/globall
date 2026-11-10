# YENİ SİNYAL AİLESİ ARAŞTIRMASI — TUR 2 (2026-11-10)

**Yöntem:** 4 paralel kol (pozisyonlanma/perakende sentiment · taşıma/swap · çapraz varlık lead-lag ·
vade/takvim yapısı). Her aday: kaynak doğrulaması + **veri erişim testi** + maliyet uyumu + kontrol gruplu
yanlışlama. Tur-1'de elenenler (bar-trend, tick OFI, gotobi, makro sürpriz, carry/momentum 5m-1h, SMC,
COT kontraryan) **tekrar önerilmedi**.

---

## 1) KENDİ ÖLÇÜMÜMÜZ — turun en güçlü iki adayı (MT5 barlarıyla)

> ## ⚠️ DÜZELTME (aynı gün, 2026-11-10) — BU AİLE ÖLÇÜMLE ELENDİ
>
> Aşağıdaki "+0.094 (t=4.22)" ve "+0.156 (t=7.06)" sonuçları **hatalıydı**: `daily_pairs`
> fonksiyonunda X'in değişimi de Y ile **aynı gün penceresinde** hesaplanıyordu → yani
> "lead" değil **eşzamanlı korelasyon** ölçülmüştü. Hata, aileyi kol dosyası olarak yazıp
> `fx_arm_backtest.py` ile A/B edince ortaya çıktı (kol −0.005R, PF 0.94, t=−2.09 verdi;
> doğrudan ölçüm pozitif diyordu → çelişki).
>
> **GERÇEK GECİKMEYLE yeniden ölçüm** (X: t−1 gün değişimi, Y: t günü getirisi):
>
> | sinyal (t−1) | hedef | kısmi rho | t | net p/gün | yarılar |
> |---|---|---|---|---|---|
> | ^TNX | USDJPY | **+0.025** | **+1.10** | −2.10 | −0.09 / −4.10 |
> | ^GSPC | AUDUSD | **+0.027** | **+1.20** | −0.69 | +0.92 / −2.30 |
> | PLASEBO ^FVX | EURUSD | +0.012 | +0.52 | (gürültü) | +0.83 / +3.16 |
>
> **Saatlikte gerçek gecikme VAR ama ekonomik değil:** ^GSPC→AUDUSD rho **+0.251 (t=14.1)**
> net **+0.32p** (t=1.61); ^TNX→USDJPY rho +0.130 (t=7.18) net +0.23p (t=0.57) — **1 pip
> maliyetin altında**. Yani çapraz-varlık bilgisi fiyata çoktan gömülü; bize kalan kırıntı
> maliyetin altında.
>
> **Durum:** aile **elenenler**e taşındı; kol dosyası `app/arms/crossasset_lag.py` **kayıtlı
> değil** (yalnız negatif sonucun yeniden üretilebilir kaydı; testle kilitli).
> **DERS:** bir "lead" iddiasını kabul etmeden önce X ile Y'nin **pencere örtüşmesi**
> kontrol edilmeli; eşzamanlı korelasyon, gecikme gibi görünür. Kol dosyası + bağımsız
> backtester bu hata sınıfını yakaladı.


Yahoo günlük (10 yıl) + **kendi MT5 D1 barlarımız**; X **gecikmeli** (t−1), Y_t getirisi,
Y_{t−1} kontrol edilerek **kısmi korelasyon**; kural: `isaret(X_{t−1})` yönünde 1 gün, maliyet düşülmüş.

| sinyal (t−1) | hedef | n | kısmi rho | t | **net p/gün** | t | isabet% |
|---|---|---|---|---|---|---|---|
| **^TNX (10y getiri)** | **USDJPY** | 1997 | **+0.094** | **+4.22** | **+4.41** | **+2.74** | 51.6 |
| **^GSPC (S&P)** | **AUDUSD** | 1996 | **+0.156** | **+7.06** | **+2.98** | **+2.68** | 51.1 |
| ^VIX (ters) | AUDUSD | 1999 | −0.121 | −5.43 | (SPX'in aynası) | | |
| **PLASEBO: ^FVX** | **EURUSD** | 1997 | −0.052 | −2.32 | **−0.81** | −0.68 | 49.6 |

**Okuma:** iki çapraz-varlık gecikmesi **bizim broker barlarında** yaşıyor ve plasebo para kenarı üretmiyor.
Zamanlama mantığı sağlam: SPX/^TNX **20:00-21:00 UTC**'de kapanıyor, FX günlük barı **22:00 UTC**'de →
gerçek lead, örtüşme değil. **Uyarılar:** (a) tek dönem/tek parite, alt-dönem kırılımı YAPILMADI;
(b) 24 saat tutuş → gecelik swap/boşluk riski; (c) `^TNX` kotasyonu yalnız ABD nakit saatlerinde →
saatlik (1h) uygulama için ayrı hizalama denetimi şart (ilk denememde ızgara uyuşmadı: MT5 sunucu saati UTC+2).

---

## 2) TAŞIMA (SWAP) — canlı hesapta ölçüldü, modelde YOK

`symbol_info()` alanları canlı okundu ve **gerçek deal geçmişiyle doğrulandı** (oranlar 0.99-1.12 gün=1,
**3.01** çarşamba): `swap_mode=1` (POINTS), `SYMBOL_SWAP_ROLLOVER3DAYS=3` (Çarşamba).

| sembol | uzun yön günlük | stop'a oran | çarşamba ×3 |
|---|---|---|---|
| GBPJPY | **+1.14 pip/gün** | %5.7 (20p stop) | %17 |
| USDJPY | +0.83 pip/gün | %4 | — |
| EURUSD | kısa +0.14 pip/gün | %0.7 | gürültü |
| USDTRY | kısa +31.5 pip/gün | baskın | — |

**Kritik keşif:** sunucu saati **UTC+2** → **rollover 22:00 UTC** (bizim 00:00 UTC varsayımlarımız yanlış
pencereyi ölçüyor). `portfolio_risk.cost_r` **swap içermiyor** (`spread+komisyon`), oysa JPY çaprazlarında
swap stop riskinin %5-17'si.
**Dürüst karşı-veri:** 60 günlük defterde swap **−19,33 USD**, komisyon **−2.761 USD** → swap toplam
maliyetin **%0,7'si**. Yani "carry optimizasyonu" tek başına kâr motoru değil; doğru kullanım **maliyet
modelini düzeltmek** ve negatif-swap tarafını veto etmek.

---

## 3) VERİ DUVARLARI (spekülasyon değil, ölçülmüş erişim)

| kaynak | sonuç |
|---|---|
| CME FX options/futures OI (`CmeWS/mvc/...`) | **403 bot engelli**; tarayıcıyla EOD okunur ama global FX options'ın küçük dilimi |
| DTCC OTC FX options OI | **erişilemiyor** (GTR kısıtlı) → **strike pinning ailesi ölçülemez** |
| OANDA Order Book / Dukascopy SWFX / FXSSI / Myfxbook | **canlı var, TARİHSEL YOK** → backtest için 6-8 hafta kendi logumuz şart (Myfxbook API ücretsiz ama giriş ister, 100 istek/24s) |
| DailyFX/FXCM SSI, IG | **403/404** (Akamai) → programatik erişim yok |
| stooq | **JS proof-of-work** → scriptten kullanılamaz |
| FRED (`fredgraph.csv`) | çalışır ama **~1 iş günü gecikmeli + revizyon yok** → intraday lead ölçümünde **look-ahead** üretir; `vintage_date` yok sayılıyor |
| Yahoo `AUD=X` / `NZD=X` | **TERS kotasyon** (USDAUD) → işaretler ters çıkar |

---

## 4) ELENENLER (bu tur)

- **FX option strike pinning** — veri duvarı (DTCC kısıtlı, CME 403). Mekanizma hakemli olarak var
  (JIMF 2022 gamma hedging; BoE SWP 964), ama **strike-OI olmadan ölçülemez**.
- **Turn-of-the-Month (FX)** — Kumar (*JEB* 86:16-32, 2016): çok-para birimli kanıt **verimlileşmiş**.
- **VIX → JPY/CHF güvenli liman lead** — Ranaldo & Söderlind (*RoF* 14(3):385, 2010) etki var diyor ama
  bizim ölçümde **lead yok, yalnız eşzamanlı** (1h t≈1.1).
- **DXY sentetik residual** — 1h'de sentetik vs gerçek DXY corr **+0.981**, residual **1.3 baz puan** (maliyet altı).
- **N225→USDJPY (1h)**, **bakır→CLP**, **petrol→CAD/NOK (1h)** — 1h'te ölü (günlükte var ama zayıf).
- **LLM takvim metni** — bizde transcript akışı yok + haber ailesi zaten negatif ölçüldü (−2.06p, t=−1.96).
- **Quad witching / tatil / roll haftası** — sinyal değil **FİLTRE**; ve kritik: bizim p50 spread ölçümü
  o günlerde **yanlış pozitif** üretir (gerçek spread 2-5×).

---

## 5) ÖNERİLEN SIRA

1. ~~Çapraz-varlık gecikmesi ailesi~~ **ELENDİ** (bkz. §1 düzeltmesi) — saatlik ρ anlamlı ama
   net < maliyet; günlük "lead" ölçüm hatasıydı.
1b. **Sıradaki aday:** aşağıdaki swap/maliyet düzeltmesi (P1) ve perakende sentiment loglaması. (^TNX→USDJPY, ^GSPC→AUDUSD): alt-dönem kırılımı + maliyet stresi +
   saatlik hizalama denetimi (MT5 UTC+2 ofseti ile "kapanıştan sonraki ilk bar" kuralı). Geçerse
   `app/arms/` kol dosyası olarak yazılıp `fx_arm_backtest.py` ile A/B edilir.
2. **Swap'ı `cost_r`'ye sok** + negatif-swap veto (JPY çaprazları): tüm A/B'lerin maliyet doğruluğunu düzeltir.
3. **Perakende sentiment**: FXSSI/Myfxbook **loglamaya** başla (tarihsel yok); 6-8 hafta sonra ölç.
4. Takvim/vade ailesi yalnız **filtre** olarak (gerçek spread ile).
