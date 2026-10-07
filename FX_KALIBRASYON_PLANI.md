# FX KALİBRASYON PROJESİ PLANI

**Durum:** PLAN (uygulama yok — her aşama kullanıcı onayı ile açılır)
**Tarih:** 2026-10-07
**Sahip:** Erkan + ZCode
**Hedef soru:** "Bu motorda FX çiftleri kâr edebilir mi, edemezse HANGİ KANITLA reddedilir?"
**Kapsam çiftleri (kullanıcı listesi):** EURUSD, GBPUSD, USDJPY, USDCHF, USDCAD, NZDUSD, EURJPY, GBPJPY, EURCHF, GBPCHF, EURNZD, GBPNZD

---

## 1. Arka Plan — Bugüne Kadarki Kanıt (2026-10-07 replay serisi)

| Deney | Sonuç | Ders |
|---|---|---|
| 7 majör + XAU/BTC, 30g | majörler filtreyle bile ≈ −$1.349 | Majörler mevcut motorla negatif |
| 30 sembol (7 majör + 21 kros), 30g | **NET −$3.983**, 28/28 FX zararda, maxDD $4.074 | Kapsam genişletmek çift zarar |
| Kullanıcının 12 çifti saf kitap, 6 slot | −$5.309 / DD $5.321 | Tek başına da kaybediyor |
| Kullanıcının 12 çifti saf kitap, **99 slot** | **−$6.102 / DD $6.107** | Slot rekabeti suçlu DEĞİL |
| 99 slot karışık kitap (XAU+BTC+12) | −$2.596 (6 slotta −$1.725'ten KÖTÜ) | 6 slot zararı frenliyordu |
| XAU+BTC referans | **+$3.718 / WR %75.3 / DD $117** | Motorun edge'i altın konsantrasyonunda |
| Majör seans filtresi (72h+30g) | bloklananlar gölgede −$5.939 / WR %51 | Asya seansı FX girişleri kaybettiriyor |
| Canlı CSV (6-7 Eki) | USDJPY 0/9, avgWin $27 vs avgLoss −$61 | Ödeme asimetrisi canlıda da aynı imza |

**Teşhis:** FX çiftleri %50-56 WR üretiyor ama ödeme asimetrisi + maliyet → negatif beklenti. Motorun
skor eşikleri (75/76/78), SL/TP/BE çarpanları, seans mantığı ve spread varsayımları **altın karakterinde
kalibre edilmiş**. FX'i kârlı yapmak isteniyorsa FX'e ÖZEL bir kalibrasyon katmanı gerekir — bu proje
o kalibrasyonun araştırılıp KANITA dayalı evet/hayır ile sonuçlandırılmasıdır.

---

## 2. Proje İlkeleri (öğrenilmiş derslerden)

1. **Altın motoruna DOKUNULMAZ.** Tüm deney replay'de; canlıya geçiş ancak bir çift tüm kapılardan geçerse ve kullanıcı onayıyla olur.
2. **Ölçüm adilliği:** Her çift kendi dedicated defterinde test edilir (slot rekabeti yok — `--max-open 99` ya da tek çift + XAU referansı).
3. **In-sample / out-of-sample ayrımı:** Parametre süpürmesi bir pencerede yapılır, kazanan ayar FARKLI bir pencerede doğrulanır. Aynı pencerede hem kalibre edip hem raporlamak = eğriye sığdırma (bu projenin en büyük tuzak).
4. **En ucuz öldürücü test önce gelir:** Maliyet (spread) tek başına kaybı açıklıyorsa, kalibrasyonun anlamı yoktur → proje erken ve ucuz kapanır.
5. **Kill kriterleri baştan yazılır** (bkz. §6) — "bir umut daha dene" yapılmaz.
6. **Her aşama tek karar bırakır:** devam / dur / değiştir.

---

## 3. Aşama 0 — Gerçek Maliyet Modeli (1 oturum, ön koşul)

**Soru:** Replay'de kullandığımız sabit spread'ler (majör 1.2, kros 2.0 pip) gerçeklikten ne kadar sapıyor?

- Köprü (`mt5_bridge.py`) her saniye gerçek broker spread'ini zaten hesaplıyor (`_LIVE_SPREAD_PIPS`).
- **Görev 0.1:** Köprüye "son N saatlik sembol başına spread istatistiği (min/ort/p95)" raporu ekle (bellek kopyası + opsiyonel JSON yazımı). Kod değişikliği küçük.
- **Görev 0.2:** 24-72 saat toplama → çift başına gerçek spread tablosu çıkar (`outputs/fx_spread_reality.json`).
- **Görev 0.3:** Replay'e `--spread-profile <dosya>` parametresi ekle: her çiftin gerçek ortalama (veya p95, ihtiyaca göre) spread'ini kullanır.

**Çıktı:** Gerçek maliyet tablosu + replay'e takılabilir profil dosyası.
**Tuzak:** Yahoo verisi fiyatı mid kabul eder; gerçek spread + slippage eklenmeden hiçbir FX sonucu "kâr" sayılmaz.

---

## 4. Aşama 1 — Maliyet Teşhisi: Kaybın Kaçı Spread? (1 oturum, ERKEN KARAR NOKTASI)

**Soru:** Mevcut sinyaller değişmeden, maliyetler gerçekleştirilince tablo ne kadar bozuluyor?

- **Görev 1.1:** 12 çift saf kitap (99 slot), gerçek spread profiliyle 30g replay (mevcut cache `outputs/replay_cache_30d_fxwide.json`).
- **Görev 1.2:** Aynı koşum "spread'siz" (sabit 0.5 pip sembolik maliyet) karşılaştırma kolu — fark = **spread vergisi**.
- **Görev 1.3:** Çift başına tablo: brüt sinyal PnL → spread sonrası PnL. Brütte kâr eden ama spread'te ölen çiftler "maliyet kurbanı" kategorisine girer (bunların kurtarılması ZOR); brütte bile zarardaysa sinyal sorunu vardır (Aşama 2'nin konusu).

**ERKEN KARAR (kill gate #1):**
- Brüt (spread'siz) bile net ≤ 0 olan çiftler için sinyal kalibrasyonu denenir ama beklenti düşük tutulur.
- 12 çiftin brüt toplamı da ciddi negatiftse (ör. ≤ −$4.000), 5m zaman dilimi sinyal tarafında kök sorun demektir → Aşama 3'te (zaman dilimi) ağırlık buna kayar.

---

## 5. Aşama 2 — Sinyal Kalibrasyonu (2-3 oturum, süpürme + OOS)

**Soru:** Çift/çift-ailesi özel eşiklerle (skor, seans, ATR rejimi) pozitif alt-kümeler var mı?

- **Görev 2.1 — Skor süpürmesi:** Çift başına `--min-score` 75→90 (5'li adım) × seans penceresi (7-20 UTC / 13-20 UTC / Londra-NY kesişimi 13-17 UTC) süpürmesi, dedicated kitap, **in-sample pencere** (ör. 09-29 Eki).
- **Görev 2.2 — ATR/volatilite rejimi:** Çok düşük ATR'de giriş yasağı (`--major-min-atr` çift-başı eşik) — ölü piyasa çiftleri (EURCHF tipi) bununla elenebilir.
- **Görev 2.3 — OOS doğrulama:** Süpürmenin en iyi 2-3 ayarı **hiç görülmemiş pencerede** (ör. 30 Eki-6 Kasım) tekrar koşulur. `--start/--end` mevcut.
- **Görev 2.4 — Çift-ailesi gruplandırma:** Tekil süpürme sonuçları aile mantığıyla birleştirilir (USD-majörler / JPY kros / CHF kros / NZD kros) — çift başına ayrı ayar bakım külfeti yaratmasın; panelde tek "FX profili" olur.

**Çıktı:** Her çift için "kalibre edilmiş en iyi ayar + OOS sonucu" tablosu.

---

## 6. Aşama 3 — Zaman Dilimi Merdiveni (1 oturum, Aşama 1 sonucuna göre)

**Hipotez:** 5m'de spread vergisi sinyal edge'ini yutuyor olabilir; 15m'de işlem başına maliyet oranı düşer, sinyal gürültüsü azalır.

- **Görev 3.1:** Replay'e 15m çalışma modu ekle (ya direkt Yahoo `interval=15m` çek ya 5m'den resample — teknik olarak küçük; HTF 15M zaten var, LTF 15m'ye yükseltilir).
- **Görev 3.2:** Aşama 2'de hayatta kalan çift(aile)ler 5m vs 15m A/B (aynı ayar ruhuyla, ayrı ayrı kalibre edilmiş eşiklerle).
- **Not:** 15m'de işlem sayısı ~1/3'e düşer → örneklem için 60 günlük pencere gerekebilir (Yahoo 5m/15m limiti ~60 gün; yeterli).

---

## 7. Aşama 4 — Çıkış Kalibrasyonu (1 oturum, sadece hayatta kalanlar)

- FX'e özel BE/trail/SL çarpanları: `--sl-mult`, `--tp-mult`, `--be-ratio-gold` benzeri çift-ailesi profilleri (replay'e `--fx-profile` JSON'u eklenir).
- Chandelier çarpanı FX için ayrı süpürülür (altında 1.2 kullanılıyor; FX volatilitesi farklı).
- Seri-SL sigortası FX'te default açık (3 SL → 5 dk) — FX'te seri kayıp riski altından yüksek.

---

## 8. Aşama 5 — Son Karar Kapısı ve (Kabul İse) Canlıya Alım

**Bir çiftin canlıya alınabilmesi için HEPSİ gerekir:**
1. OOS 30g net > 0 (en az 100 işlem),
2. OOS maxDD < $200 (replay lotlandırmasında),
3. İki ayrı pencerede pozitif (kullanıcının "yeterli örneklem" standardı: 2×30g),
4. Gerçek spread profiliyle kapanışta pozitif,
5. XAU+BTC kitabına eklendiğinde (slot rekabeti dahil) sistem netini DÜŞÜRMÜYOR (B30XAU +$3.718/DD $117 referansına karşı).

**Kabul olursa:** Sadece geçen çift(ler) panelden `allowed_symbols`'a eklenir; FX profili ayarları ayrı alan grubu olarak motor eklenir (XAU/BTC ayarları ortak store'da korunur). **Canlıda önce 1 hafta paper-gözlem** (engine zaten paper+MT5 aynı anda yazıyor).

**Hiçbir çift geçmezse:** Proje "kanıta dayalı RED" raporuyla kapanır — bu da değerli bir sonuçtur; artık "acaba FX" sorusu veriyle kapanmış olur.

---

## 9. Kill Kriterleri (proje erken biterse)

| Tetik | Anlamı | Aksiyon |
|---|---|---|
| Aşama 1: brüt (spread'siz) toplam ≤ −$4.000 | Sinyalin kendisi 5m FX'te yok | Aşama 3'e (15m) bir şans, sonra RED |
| Aşama 2: OOS'ta hiçbir ayar pozitif değil | Kalibrasyon eğriye sığdırma olurdu | RED (5m) |
| Aşama 3: 15m'de de OOS negatif | Zaman dilimi farksız | FX KESİN RED — dosya kapanır |
| Aşama 5: sistem netini düşürür | Edge XAU konsantrasyonunda | RED — "kârlı çift olabilir ama bizimkini bozuyor" |

---

## 10. Çalışma Sırası ve Efor Tahmini

| Aşama | Oturum | Çıktı | Karar |
|---|---|---|---|
| 0 — Maliyet modeli | 1 | spread tablosu + `--spread-profile` | devamsızlık = proje başlamaz |
| 1 — Maliyet teşhisi | 1 | brüt/net spread vergisi tablosu | kill gate #1 |
| 2 — Sinyal süpürmesi + OOS | 2-3 | çift bazlı kalibrasyon tablosu | kill gate #2 |
| 3 — 15m merdiveni | 1 | 5m vs 15m A/B | kill gate #3 |
| 4 — Çıkış kalibrasyonu | 1 | FX profil JSON | — |
| 5 — Son karar + (varsa) canlı | 1 | karar raporu / kabul listesi | kill gate #4 |

**Toplam: ~6-8 oturum.** Her oturum sonunda kullanıcıya tek sayfalık özet (tablo + karar önerisi).

---

## 11. Mevcut Envanter (sıfırdan başlamıyoruz)

- Replay motoru: `scripts/forex_replay_backtest.py` — 21 kros tanımı + gerçekçi pip_val override + `--max-open` + tüm kapı/çıkış varyantları hazır.
- Veri: `outputs/replay_cache_30d_fxwide.json` (30 sembol × 30g, 24.8MB) — Aşama 1-2 hazır veriyle başlar.
- Referans defterler: `majorsession_B30XAU.json` (+$3.718), `fx12_FX12ONLY_M99.json` (−$6.102) — A/B çıtaları.
- EV kalkanı, seri-SL sigortası, chandelier, seans filtresi: hepsi replay'de bayraklı — kalibrasyon bunların ÜSTÜNDE çalışır.

## 12. Riskler ve Dürüst Notlar

- Yahoo 5m kros verisi kalitesi iyi ama **gerçek fills** değildir; Aşama 0 olmadan hiçbir FX sonucu kabul edilmez.
- 30 gün tek piyasa rejimini temsil eder; OOS pencereleri farklı rejimlerde olmalı (trend/chop karışımı).
- Bu motorun tarihi: her "bir de bunu ekleyelim" denemesi replay'de test edilip REJET edildi (DCA, erken-dönüş çıkışları, uzama kapısı, kros/majör kapsamı). Bu proje de aynı disiplinle — kanıt yoksa eklememe — yürütülecek.
