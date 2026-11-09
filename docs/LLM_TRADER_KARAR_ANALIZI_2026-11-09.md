# LLM Trader Kararları + Gerçek İşlem Kayıtları — Analiz

**Tarih:** 2026-11-09 · **Kaynak:** (a) uygulamadaki "LLM Trader Kararları" paneli (517 karar), (b) MT5 işlem export'u `forex_scalper_islemler_2026-11-09.csv` (276 işlem, 2026-11-03 → 2026-11-09)
**Yöntem:** Panel sayılarının yeniden hesaplanması + CSV'nin bağımsız istatistiksel analizi (t-testi, %95 GA, break-even geometrisi)

---

## 0. Yönetici özeti — 3 net hüküm

| # | Hüküm | Kanıt |
|---|---|---|
| **1** | **Gerçek işlem akışı istatistiksel olarak KANITLI ZARARDA** | n=276, ortalama **−1.33 USD/işlem**, t=**−2.95**, %95 GA **[−2.22, −0.45]** (sıfırı içermiyor) |
| **2** | **LLM vetosu ölçülebilir bir değer katmıyor** — ama asıl maliyeti R değil **gecikme + %16 hata** | geçen +0.06 R vs veto edilen +0.08 R → fark **−0.02 R**, standart hatası ~0.10 → **sinyal yok**; medyan 26.3 sn, p99 60.5 sn, 83 hata |
| **3** | **Kök sorun seçim değil GEOMETRİ** — panelin kendi uyarısı doğru | break-even isabet **%67.2**, gerçekleşen **%56.2**; ortalama kazanç +3.95 vs ortalama kayıp **−8.10** (oran 0.49) |

Panel tasarımı **dürüst**: kendi kendine "kanıtlanmadı" diyor, çoklu-test uyarısı veriyor, fail-open yanlılığını ölçüyor. Sorun ölçümde değil, **ölçümün gösterdiği şeyde**.

---

## 1. Panelin sayıları — ne kanıtlı, ne değil

### 1.1 Kanıtlı olanlar

**Güven puanı kalibrasyonu BOZUK (ve yönü biliniyor).**

| Metrik | Değer | Yorum |
|---|---|---|
Brier | 0.2679 | taban oran 0.226 |
**Brier skill** | **−0.185** | negatif = "her zaman taban oranı söyle" demekten **daha kötü** |
AUC | 0.541 | rastgeleden ayırt edilemiyor (n=420'de SE≈0.03 → GA 0.5'i içerir) |

Kova tablosu bunu **nerede** bozulduğunu gösteriyor:

| Güven kovası | Öngörülen | Gerçekleşen | n | Hüküm |
|---|---|---|---|---|
0-20% | 0.16 | 0.33 | 18 | örneklem çok küçük, yorum yok |
20-40% | 0.31 | 0.30 | 159 | ✅ **kalibre** |
40-60% | 0.55 | 0.40 | 47 | ⚠ aşırı güvenli |
**60-80%** | **0.65** | **0.37** | **196** | ❌ **ciddi aşırı güven** (GA ±0.068 → %65 imkânsız) |

→ **Model 40% üstünde sistematik olarak yalan söylüyor.** Yüksek güven = daha iyi isabet DEĞİL (60-79% kovası %37, <60% kovası %38). Panelin "güven puanı işe yarıyor mu? → hayır" hükmü doğru.

### 1.2 Kanıtlı OLMAYANLAR (panel de böyle diyor — doğru)

**Veto farkı anlamsız.** Geçen +0.06 R (n=236) − veto edilen +0.08 R (n=184) = **−0.02 R**. R-multiple'ların tipik SD'si ~1.0 varsayımıyla bu farkın standart hatası ≈ **0.10 R** → −0.02, **0.2 SE**. Yani:

* "Veto −14.40 R kaybettirdi" **toplam** olarak doğru ama **karar başına** fark gürültüden ayırt edilemiyor.
* "LLM rastgele vetodan iyi" iddiası **kanıtlanmadı** (rastgele kontrol −0.01, LLM −0.02 → ikisi de ~0).

**Exit kuralı A/B:** baseline +0.02 · be_1r −0.06 (−0.08) · partial_1r −0.07 (−0.09) · trail_1r 0 (−0.02). Panelin "standart hata / çoklu test düzeltmesi olmadan uygulanmamalı" uyarısı **doğru ve yeterli**. Üç varyant × aynı veri → Bonferroni eşiği ~0.017; −0.08'in buna ulaşması için SE≈0.03 gerekir, gerçekçi değil. **Hiçbir çıkış varyantı kanıtlanmadı → değiştirmeyin.**

### 1.3 Panelin ölçtüğü gerçek maliyet: gecikme ve hata

| Bulgu | Değer | Anlamı |
|---|---|---|
LLM hata/zaman aşımı | **83 karar (%16)** | her 6 karardan 1'i yok |
Fail-open yanlılığı | hatalı kararların gölge sonucu **−0.17 R** vs normal **+0.07 R** | hata durumunda işlem AÇMAK kaybettiriyor |
Gecikme | medyan **26.3 sn** · p90 52.9 · p99 60.5 | tarama döngüsü bu kadar bekliyor |

→ Bu üçü birlikte şunu söylüyor: **LLM katmanı kenar üretmiyor, ama her kararda 26 saniye ve %16 oranında fail-open riski ekliyor.** Fail-open'ı fail-closed yapmak (hata → işlem yok) ölçülmüş veriyle **daha iyi** görünüyor (n=83, sınırlı ama yön net).

---

## 2. Gerçek işlem kayıtları (276 işlem) — bağımsız analiz

### 2.1 Genel

| Metrik | Değer |
|---|---|
İşlem | 276 |
İsabet | **%56.2** |
Brüt kâr / zarar | +611.65 / **−979.56** USD |
Net | **−367.91 USD** |
**PF** | **0.624** |
Ortalama kazanç / kayıp | **+3.95 / −8.10** USD (oran **0.49**) |
Ortalama sonuç | **−1.33 USD** · t=**−2.95** · %95 GA [−2.22, −0.45] |

**Geometri teşhisi:** %56 isabetle kârlı olmak için ortalama kazanç/kayıp ≥ **0.78** olmalı. Gerçek oran **0.49**. Break-even isabet **%67.2** — açık **+11 puan**.

> Bu, `docs/GITHUB_LLM_RADAR_ARASTIRMASI_2026-11-09.md` §14'te spot radar için bulunan hastalığın **aynısı**: yüksek isabet, kötü R oranı, ulaşılamaz break-even. İki ayrı sistemde aynı kök neden → **sorun strateji seçiminde değil, stop/hedef geometrisinde.**

### 2.2 İstatistiksel olarak anlamlı gruplar (|t|>1.96 = %95)

| Grup | n | Ort. USD | t | Net USD |
|---|---|---|---|---|
**AUD kümesi** (AUDCAD+AUDNZD+AUDUSD) | 19 | **−6.11** | **−4.12** | −116.15 |
**M1/M5 Çoklu Radar** | 226 | **−1.46** | **−2.80** | −330.27 |
Lot ≥ 50 (kripto yüksek lot) | 37 | **−2.54** | **−2.63** | −94.11 |
SELL | 130 | −1.59 | −2.37 | −206.95 |
Fırsat Taraması (Sohbet) | 38 | −1.47 | −1.80 | −55.80 |
BUY | 146 | −1.10 | −1.80 | −160.96 |
BTCUSD | 97 | −1.09 | −1.38 | −105.52 |

**Okuma:**
1. **AUD/kiwi grubu sistematik olarak ölü** — AUDCAD 0/5, AUDUSD 2/7, AUDNZD 1/7. t=−4.12 ile en net sinyal. Bu bir "kötü şans" değil.
2. **Ana strateji (M1/M5 Çoklu Radar) kanıtlı negatif** — 226 işlem, −330 USD. Para kaybının %90'ı burada.
3. **Yüksek lot kripto işlemleri anlamlı kötü** — büyük pozisyon = büyük zarar; boyutlandırma kalibrasyonu yok.
4. **BTCUSD zararın en büyüğü ama İSTATİSTİKSEL OLARAK KANITLI DEĞİL** (t=−1.38, n=97). Yön negatif; "BTCUSD'yi kes" demek için daha fazla veri ya da DSR düzeltmesi gerekir.
5. **Kazandıran stratejiler (Kombo XAU +22.29, London Breakout +8.70, Donchian +6.72) n=2–4.** Bunlar **kanıt değil** — bu örneklemde aşırı uyum göstergesi. Bunları "iyi strateji" sayıp ağırlık artırmak tam olarak PBO'nun cezalandırdığı hata.

### 2.3 En çok zarar ettiren semboller

| Sembol | n | Net USD |
|---|---|---|
BTCUSD | 97 | −105.52 |
AUDCAD | 5 | −49.99 |
XTZUSD | 4 | −36.00 |
AUDUSD | 7 | −35.57 |
AUDNZD | 7 | −30.59 |
ETHUSD | 17 | −29.13 |

---

## 3. İki ölçüm arasındaki ÇELİŞKİ — ve nedeni

| Ölçüm | Sonuç |
|---|---|
Panel: onaylanan işlemlerin **gölge** sonucu | **+0.054 R**/işlem (pozitif) |
CSV: aynı stratejilerin **gerçek** sonucu | **−1.33 USD**/işlem (anlamlı negatif) |

**Neden:** Panelin kendi uyarısı: *"tahmindir (trailing, kısmi kâr ve gerçek spread yok)"*. Gölge 1R modeli:
* trailing stop ve kısmi kâr çıkışlarını **hesaba katmıyor** → gerçekte kazançlar daha erken/az kapanıyor,
* **spread, komisyon, kayma yok** → gerçek USD sonucu gölgeden sistematik olarak düşük,
* R normalizasyonu stop mesafesine göre → mutlak para büyüklüğünü gizler.

**Sonuç: gölge ölçüm İYİMSER bir üst sınırdır.** Karar verirken gölge R'sini tek başına kullanmayın; gerçek USD sonucuyla birlikte okuyun. (Bu, `ml_shadow` ve `geometry_shadow` tasarımının da neden "gerçek değerlendirme" ile eşleştirilmesi gerektiğini doğruluyor.)

---

## 4. VERİ KALİTESİ — 3 ölçüm engelleyici hata

### 4.1 Çıkış nedeni etiketi %87 BOZUK (en kritik)

| Etiket | WIN | LOSS |
|---|---|---|
🛑 Zarar Durdur (SL) | **152** | 88 |
Scalper Close | 2 | 33 |
🎯 Kâr Al (TP) | 1 | 0 |

**240 / 276 işlem "Zarar Durdur (SL)" etiketli; bunların 152'si KAZANÇ.** Yani `exit_reason` alanı gerçek çıkış sebebini taşımıyor — muhtemelen trailing stop / scalper close ayrımı yapılmadan hepsi "SL" yazılıyor.

**Neden kritik:** Panelin **"Çıkış kuralı A/B"** ölçümü tam olarak çıkış nedenine dayanıyor. Gerçek işlem kayıtlarındaki etiket bozuksa, canlı veriyle exit-rule doğrulaması **yapılamaz**. Bu, paneldeki A/B'nin neden yalnız gölge yoldan üretilebildiğini de açıklıyor.

### 4.2 `Radar Skoru` tüm satırlarda boş (`-`)

Sinyal skoru ↔ sonuç korelasyonu **ölçülemiyor**. Spot tarafında bunu `signal_edge.py` (IC) ile yapabiliyoruz; MT5 tarafında veri yok. Bu, "radar skoru işe yarıyor mu" sorusunun forex tarafında **cevapsız** kalmasının nedeni.

### 4.3 `SL Seviyesi` / `TP Seviyesi` tüm satırlarda boş (`-`)

R cinsinden normalizasyon **gerçek işlemlerden** yapılamıyor; yalnız gölge yoldan türetilebiliyor. Bu yüzden "1R = stop mesafesi" varsayımı canlı işlemlerde doğrulanamıyor.

---

## 5. Öneriler (öncelikli)

| # | İş | Gerekçe | Maliyet |
|---|---|---|---|
**1** | **Fail-open → fail-CLOSED**: LLM hata/zaman aşımında işlem açma | hatalı kararların gölge sonucu −0.17 R vs +0.07 R (n=83) | S |
**2** | **Çıkış nedeni etiketini düzelt** (trailing/kısmi/sözleşme sonu ayrı) | %87 etiket bozuk → exit-rule A/B canlı veriyle imkânsız | S |
**3** | **LLM güvenini kalibre et + çekimserlik** — `app/ml_probability.py` hazır | Brier skill −0.185, 60-80% kovasında %65→%37 aşırı güven | S/M |
**4** | **Vetoyu kaldır ya da yalnız kalibre olasılık + abstention ile kullan** | veto farkı −0.02 R (0.2 SE) = sinyal yok; maliyet 26 sn + %16 hata | S |
**5** | **AUD/kiwi grubunu kapat** | t=−4.12, n=19, −116 USD | S |
**6** | **Yüksek lot kripto işlemlerini sınırla** (boyut kalibrasyonu) | t=−2.63, n=37, −94 USD | S |
**7** | **Geometri A/B'yi yeniden değerlendirme döngüsüne al** (`geometry_shadow.py` deseni) | break-even %67.2 vs %56.2; kazanç/kayıp 0.49 | M |
**8** | **MT5 export'a `radar_score`, `sl_pct`, `tp_pct`, `exit_reason_code` ekle** | 4.2/4.3 ölçüm boşlukları | S |
**9** | **Exit A/B'yi DEĞİŞTİRME** | farklar çoklu-test eşiğinin altında; panelin uyarısı doğru | — |

**Yapılmaması gerekenler:**
* Kazandıran küçük örneklemli stratejilere (n=2–4) ağırlık vermek → aşırı uyum.
* BTCUSD'yi "kanıtlandı" diye kesmek → t=−1.38, anlamlı değil (yön negatif, ama kanıt yok).
* Exit varyantlarından birini uygulamak → anlamsız fark.

---

## 6. Sınırlar

* CSV 7 gün / 276 işlem — mevsimsellik ve rejim çeşitliliği yok. 7 günlük bir pencerede t-testi %95 GA verir ama **farklı rejimleri temsil etmez**.
* Panel metrikleri panelin kendi tanımıyla alındı; ham karar kayıtlarına (517 satır CSV) erişip yeniden hesaplamadım. Panelin kendi "kanıtlanmadı" hükümleri bu yüzden **olduğu gibi** raporlandı.
* Gölge R ile gerçek USD arasındaki köprü (spread/kayma/trailing) **ölçülmedi** — öneri 8 bunu mümkün kılar.
* Aynı strateji içinde korelasyonlu işlemler (ör. BTCUSD'de 5 saniye arayla iki giriş) t-testinin bağımsızlık varsayımını zayıflatır; gerçek GA daha geniş olabilir.

---

## 7. UYGULAMA — Sıra 1 & 2 (2026-11-09)

### 7.1 Fail-open → **fail-CLOSED** (varsayılan)

`ForexAutoPaperSettings.llm_review_fail_open` varsayılanı **True → False** yapıldı. Gerekçe alan açıklamasına yazıldı: *"Ölçüm (517 karar): hatalı kararların gölge sonucu −0.17 R, hatasız kararlarınki +0.07 R → hata durumunda işlem açmak kaybettiriyor. Hata oranı %16, medyan gecikme 26 sn."*

**Kayıtlı ayar sessizce EZİLMEDİ.** Disk `forex_auto_settings.json` eski `true` değerini taşıyorsa motor açılışta **yüksek sesle uyarı** basar:

```
[FX AYAR] llm_review_fail_open=True (kayıtlı ayar). ÖLÇÜM: LLM hata/zaman aşımında
işlem açmak kaybettiriyor (hata gölge sonucu -0.17 R vs hatasız +0.07 R; hata oranı %16).
Önerilen: Ayarlar > LLM Trader > fail-closed.
```

**Neden göç (migration) YAPILMADI:** `persist_settings()` dosyayı `model_dump()` ile baştan yazıyor; tek seferlik göç işareti o dosyada tutulamaz ve kullanıcı panelden `true`'ya döndürdüğünde bir sonraki açılışta tekrar `false`'a çevrilirdi. Kullanıcının **açık seçimini sessizce ezmek** kabul edilemez; varsayılan + görünür uyarı doğru denge.

### 7.2 Kanonik kapanış nedeni — `app/trade_reasons.py` (YENİ)

Kök sorun: kapanış nedeni köprüden gelen **serbest metin**; EA trailing/kısmi kapanışları da "SL" diye işaretliyor. Mantık kapısı: **kârlı bir işlem SL_HIT olamaz** (zarar durdurma tanımı gereği kaybı sınırlar).

Kanıt önceliği: **(1) fiyat** (çıkış ≈ SL/TP seviyesi, %0.08 tolerans) → **(2) metin** (trailing/kısmi/flip/EOD/manuel/scalper-close/TP/SL; *trailing ve kısmi ÖNCE*, çünkü "İz Süren Stop" ikisini de içerir) → **(3) PnL işareti** → UNKNOWN.

**Gerçek CSV üzerinde ölçülen sonuç:**

| Kod | Önce (ham metin) | Sonra (kanonik) |
|---|---|---|
🛑 "Zarar Durdur (SL)" | **240** | 88 |
Kâr olarak onarılan | — | **OTHER_WIN 152** |
Scalper Close | 35 | 35 |
🎯 TP | 1 | 1 |
**Toplam** | 276 | **276** ✓ |
Çelişki tespit / onarım | — | **152 / 152** |
Onarım sonrası "SL ama kazanç" | 152 | **0** |

**Kablolama:**
* `app/routers/forex.py` MT5 kapanış eşlemesi → `exit_reason_code`, `exit_reason_canonical`, `exit_reason_repaired` alanları eklendi. **Ham metin (`exit_reason_title`) provenance olarak korunur.**
* CSV export'a **"Çıkış Kodu"** kolonu eklendi (ham "Çıkış Nedeni" yanında; veri gizlenmiyor).

**Neden önemli:** "Çıkış kuralı A/B" ölçümü kapanış nedenine dayanıyor; etiket bozukken canlı veriyle hiçbir çıkış varyantı doğrulanamıyordu. Ayrıca `normalize_close_reason()` seri-SL sigortası `SL_HIT` bekliyor — kazançlı kapanışın SL sayılması onu yanlış tetikliyordu.

**Testler:** `tests/test_trade_reasons.py` — 15 test (çelişki onarımı, fiyat kanıtı önceliği, trailing/kısmi sırası, PnL yedeği, CSV dağılımının taklidi).

**Tüm backend:** `2061 passed, 2 failed` (2 kırmızı önceden var).

### 7.3 Sıradaki maddeler (henüz yapılmadı)

| # | İş | Durum |
|---|---|---|
3 | LLM güvenini kalibre et + çekimserlik | ✅ **`scripts/report_llm_confidence_calibration.py`** — Brier/log-loss/ECE + izotonik eğri + **eşik önerisi** (`ml_probability` yeniden kullanıldı). Yerelde LLM kaydı olmadığı için **sunucuda** koşulmalı. 10 test |
4 | Vetoyu kaldır / yalnız kalibre eşikle kullan | ⏸ **bilinçli beklemede** — kalibre eşik + 2-3 hafta gölge veri olmadan vetoyu kaldırmak ölçümsüz müdahale olur |
5 | AUD kümesini kapat | ✅ **`blocked_symbols`** ayarı (varsayılan AUDCAD/AUDUSD/AUDNZD), girişte **risk kapısından ÖNCE** `continue`. Liste boşaltılarak kapatılabilir. 6 test |
5b | Yüksek lot kripto sınırı | ⏸ beklemede — mevcut `order_pct` boyutlandırmasıyla çakışıyor; ayrı tasarım gerekir |
7 | Export'a `radar_score` / `sl_pct` / `tp_pct` | **kısmen**: `exit_reason_code` eklendi; skor/SL/TP köprü payload'ında YOK → köprü (MT5 EA) tarafı düzeltilmeli |

### 7.4 Sıra 3 — LLM güven kalibrasyonu (sunucuda koşulacak)

```
python -m scripts.report_llm_confidence_calibration --days 60 --save artifacts/llm_confidence_calibration.json
```

Yaptığı: `llm_trade_reviews` (confidence + `shadow_pips`/`sl_pips` → R) üzerinden
(a) ham Brier/log-loss/ECE, (b) `ml_probability` ile **izotonik eğri** ve kalibre
metrikler, (c) güvenilirlik kovaları, (d) **`llm_review_min_confidence` için eşik
önerisi** — kalibre olasılığın break-even'ı ilk aştığı ham güven değeri. Hiç
aşmıyorsa "LLM onayı bu veriyle işlem açmayı GEREKTİRMİYOR" der.

**Yerelde 0 satır döndü** (LLM kararları sunucuda birikiyor) — betik veri yokken
sahte eğri üretmiyor, açıkça söylüyor.

### 7.5 Sıra 5 — sembol koruması

`ForexAutoPaperSettings.blocked_symbols` varsayılan **AUDCAD, AUDUSD, AUDNZD**
(açıklamada: n=19, −6.11 USD/işlem, t=−4.12, **7 günlük veri → aşırı uyum riski**).
Giriş döngüsünde **risk kapısından ÖNCE** kontrol edilir ve `continue` eder
(boşa LLM çağrısı/gecikme olmasın). Karşılaştırma büyük harf; liste boşaltılırsa
koruma tamamen kapanır.

---

## 8. AYARLAR PANELİNE İKİ DÜĞME (2026-11-09)

Erkan: *"panelden fail-closed kapat → kalibrasyon betiği için ayarlara bir buton koy, basayım yapsın."*

### 8.1 Fail-closed anahtarı — düzeltildi

Anahtar **zaten vardı** ama semantiği tersti: `checked={form.llm_review_fail_open !== false}` ifadesi, değer tanımsızken kutuyu **işaretli** gösteriyordu — yeni varsayılan fail-CLOSED olduğu için yanıltıcıydı. `=== true` yapıldı ve etiket ölçümle güncellendi:

> **LLM yanıt vermezse işlem yine açılsın (önerilmez)**
> Kapalı (varsayılan) = fail-closed. Ölçüm (517 karar): hatalı kararların gölge sonucu −0.17 R, hatasızlarınki +0.07 R; hata oranı %16. Bu yüzden varsayılan KAPALI.

### 8.2 "Güven kalibrasyonunu ölç" düğmesi — yeni

**Backend:** mantık `app/llm_calibration.py`'ye taşındı (CLI ve API **aynı kod**). Yeni uç:

```
POST /api/system/llm-calibration?days=60      (admin)
```

Yalnız **ölçer** + artefakt yazar; `llm_review_min_confidence` ayarını **değiştirmez**.

**Panel (`AutoSettingsPanel` → LLM Trader kutusu):** düğme → sonuç bloğu:
örnek / taban isabet / break-even · **Brier ham → kalibre** · **ECE ham → kalibre** · **Brier skill** (renkli: pozitif yeşil, negatif kırmızı) · **önerilen min. güven** + **"Eşiği uygula"** düğmesi (formu doldurur; kaydı kullanıcı yapar). Yeterli veri yoksa "sahte eğri üretilmez" mesajı.

### 8.3 Kullanım (sunucuda)

1. Ayarlar → LLM Trader → **"Güven kalibrasyonunu ölç"**
2. Çıkan öneriyi gör → **"Eşiği uygula"** → panelin **KAYDET**'i
3. Fail-closed kutusunun **kapalı** olduğunu doğrula (varsayılan), değilse kapat + kaydet

**Doğrulama:** frontend `typecheck` 0 hata + `build` ✓ · backend `2077 passed, 2 failed` (2 kırmızı önceden var).
