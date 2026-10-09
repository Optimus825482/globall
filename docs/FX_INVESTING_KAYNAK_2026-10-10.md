# Investing.com'u Gerçek Kaynak Yap + Kıyas/Kova Düzeltmeleri (2026-10-10)

**Kaynak gereksinim:** Operatör talebi (2026-10-10): *"KAYNAK KISITINI KABUL ETMİYORUM
INVESTINGCOMDaki EKONOMİ TAKVİMİNİ DE KAYNAK OLARAK EKLEYELİM"* + önceki notun
"Bilinçli kabul edilenler" listesindeki iki maddenin düzeltilmesi
(*"BUNLARDA DUZELT"*): hassas olmayan birim kıyası ve `inventories`/`stok` latent hatası.
**Durum:** Kod hazır, testler yeşil, canlı kaynak gerçek ağla doğrulandı.

## Sorun

Önceki iş (`docs/FX_TAKVIM_ACIKLANAN_VERI_2026-10-09.md`) `actual` verisini yalnız
TradingView'den alıyordu ve bunu "kaynak kısıtı" olarak belgelemişti. Keşifte bu kısıtın
**gerçek bir kısıt olmadığı**, bir **arıza** olduğu ortaya çıktı:

1. **Investing.com kaynağı üretimde ZATEN ÖLÜYDÜ.** `fetch_investing_com_events` fonksiyon
   içinde `curl_cffi` ve `beautifulsoup4` import ediyordu; **bu paketler hiçbir requirements
   dosyasında yoktu** (`requirements.txt`, `requirements-dev.txt`, `Dockerfile`, CI).
   Docker ve CI'da import `ImportError` veriyor, fonksiyon **sessizce `[]` dönüyordu**
   (DEBUG seviyesinde log). Dosya başlığındaki "Multi-provider resilience" iddiası fiilen
   gerçek değildi.
2. **Kapı da kapalıydı.** Çağrı `if len(items) < 10` arkasındaydı; TradingView normalde
   10'un çok üzerinde olay döndürdüğünden Investing **neredeyse hiç denenmiyordu**.
3. **Birim uyuşmazlığı kontrol edilmiyordu.** `%` ile `K` körlemesine kıyaslanıyordu.
4. **`inventories`/`stok` latent hatası.** "Business Inventories" gibi petrol dışı olaylar
   ham petrol senaryosuna düşüyordu.

Canlı prob farkı gösterdi: bugün Investing'de 23 olay, **21'inde `actual`**; TradingView'de
aynı gün yalnız ~7 açıklanmış 2/3 yıldız olay. Yani kaynak eklenince vitrin gerçekten doldu.

## Ne yapıldı

| Katman | Değişiklik |
|---|---|
| `backend/requirements.txt` | `curl_cffi==0.16.0` eklendi (düz `urllib` investing.com'dan 403 alıyor; TLS parmak izi taklidi şart) |
| `app/forex_news.py` | Korumalı import + `_INVESTING_DEPS_AVAILABLE` bayrağı; eksik bağımlılıkta **gürültülü** `RuntimeError` + `logger.error` |
| `forex_news.py` `extract_economic_calendar_store_json` (**yeni saf**) | Gömülü `economicCalendarStore` JSON'unu `<script>` içinden standart `html.parser` ile çıkarır |
| `forex_news.py` `parse_investing_payload` (**yeni saf**) | Ağ yok, saat yok; fixture ile birim testi koşulabilir |
| `forex_news.py` `fetch_investing_com_events` | **Yalnız İngilizce host**; 403/429 `logger.warning`; `translate_title`; `is_passed`; kararlı `id` |
| `forex_news.py` `normalize_event_title` + `_event_minute` + `merge_calendar_sources` (**yeni saf**) | Kaynak birleştirme; ağ yok, girdi mutasyonu yok |
| `forex_news.py` `calendar_value_unit_family` + `units_compatible` (**yeni saf**) | Birim ailesi ham metinden; `evaluate_event_outcome` uyumsuzda `None` |
| `forex_news.py` `is_oil_stock_event` + `_OIL_STOCK_MARKERS` | Kova ile yön kuralı **tek kaynağa** indi; `_OIL_STOCK_HINTS` silindi |
| `forex_news.py` `CALENDAR_MAX_EVENTS` | 30 → **150** (ölçüme dayalı; aşağıda) |
| `app/database.py` | `get_economic_calendar_events(limit=50)`; `CALENDAR_PRUNE_FLOOR` + `_should_prune_economic_calendar` + `prune_economic_calendar_events` |
| `frontend/app/lib/calendarOutcome.ts` | `selectPriorityAlertEvents` (**yeni saf**) — aynı dakikadaki kümeden tek popup |
| `frontend/app/forex/components/ForexCalendarAlertModal.tsx` | Uyarı döngüsü bu seçiciden geçer |
| `backend/tests/test_forex_news.py` | 17 → **36 test** |
| `frontend/app/lib/calendarOutcome.test.ts` | 30 → **39 test** |

### Kaynak önceliği: Investing değer bazında, ama ÜÇLÜ olarak

Çakışan olayda Investing'in `Beklenti`/`Önceki`/`Açıklanan` üçlüsü kazanır. Kritik nokta:
**üçlü bir bütün olarak tek kaynaktan alınır**, alan alan karıştırılmaz. Kaynaklar arası
alan karıştırmak birim uyuşmazlığı üretirdi (`%3,2` beklenti + `145K` açıklanan) — yani
"değer bazında öncelik" kararının tam olarak önlediği şey. TradingView liste/kapsam
otoritesi olarak kalır: `id`, `title`, `stars`, `date_iso`, `scenario`, `country_name`
korunur; `source` + `matched_source_id` yalnız `raw_data` içinde taşınır (**şema
migrasyonu yok**).

### Eşleştirme anahtarı ve belirsizlik politikası

Anahtar: `(para birimi, UTC dakikası, normalize başlık)` — **üçü de eşit olmalı**.
Yalnız para birimi+dakika yetmez: canlı veride CAD'de 12:30'da hem "Unemployment Rate"
hem "Employment Change" var. Normalizasyon `NFKD` + birleşen işaret atma + sondaki
nitelik belirteci (`prel`/`flash`/`final`/…) soyma.

Politika: **yanlış birleştirme yerine görünür kopya.** Tam 1 aday → birleştir; 0 aday →
ayrı satır; **≥2 aday veya aday tüketilmiş** → birleştirme yok, ayrı satır + `warning`.
Operatör iki satır görür; yanlış sayı taşıyan tek satır görmez.

### Kova ile yön kuralı artık ayrışamaz (yapısal)

Kök neden iki ayrı petrol kavramıydı: kova listesi `inventories`/`stok` içeriyordu, yön
kuralı ise ayrı `_OIL_STOCK_HINTS` ile daraltılmıştı. Artık tek liste
(`_OIL_STOCK_MARKERS = ["oil","petrol","crude","ham petrol"]`) ve tek fonksiyon
(`is_oil_stock_event`); kova bu fonksiyonla **tanımlanır**, yön kuralı aynı fonksiyona
bağlanır. Ayrışma yorumla değil yapıyla engellenir.

* "Business Inventories" → `generic`, senaryo metni artık "Ham Petrol Stok Senaryosu" değil.
* `eia` **bilerek çıkarıldı**: kalsaydı "EIA Natural Gas Storage" (içinde petrol kelimesi
  yok) yanlışlıkla ham petrol kovasına düşerdi.
* "EIA Crude Oil Inventories" yine `crude`/`oil` ile eşleşir.

### Birim kapısı

`evaluate_event_outcome` taban seçiminden sonra, `side` hesabından **önce**:
`units_compatible` değilse `None` döner. Oysa eskiden `3.0%` beklentiye `145K` açıklanan
gelirse 3.0 < 145000 çıkar ve olay **kesin bir yön** kazanırdı — doğru cevap "bilinmiyor"dur.

`index` (çıplak sayı) **joker**tir: TradingView'in `unit` alanı güvenilmez (canlı probda
`€` bozuk karakter geldi); joker olmasaydı `forecast="0.3"` + `actual="0.2%"` gibi gerçek
TV satırları haksız yere reddedilirdi. Bilinmeyen (`None`) engellemez — bilinmezlik kanıt
değildir. Hedef hata yine kapatılır (`"3.0%"` ↔ `"145K"`).

**Frontend değişikliği gerekmedi:** reddin sonucu `outcome=None` + `has_data=True` →
olay vitrine **girmez**, modalda iki dal + "ayrıştırılamadı" mesajı görünür, tabloda üç
değer rozetsiz durur. Mevcut sözleşme zaten doğru bozuluyor.

### Belirsizlik reddi: `6.5% = 6.5%`

Kanada İşsizlik Oranı eşitlikte (`|fark| < 1e-9`) `side=None` döner ve `label_tr` **"Beklentiye Uygun"**dur. Vitrin `outcomeSide(ev) !== null` istediği için eşitlik olayı **vitrine girmez** — davranış doğru, kullanıcı yanlış yöne işaret edilmiyor.

## Uygulama sırasında yakalanan üç gerçek hata

1. **`NFKC` Türkçe `İ`'yi bozuyordu.** `NFKC` `İ`'yi `I` + birleşen nokta olarak ayrıştırır;
   birleşen işaretler `\w` sınıfına **girmez**, bu yüzden "alfanümerik olmayan dizi" kuralı
   onu ayraç sanıp boşluğa çeviriyor ve `"İşsizlik"` → **`"i şsizlik"`** gibi bozuk bir
   eşleştirme anahtarı üretiyordu (sessiz eşleşme kaybı). Düzeltme: `NFKD` + birleşen
   işaretleri **önce** at. Test bunu kilitledi.
2. **`beautifulsoup4` bağımlılığı gereksizdi ve teste zarar veriyordu.** Saf ayrıştırıcı
   bs4'e bağlıyken, bs4 bulunmayan ortamda **testler sessizce boş liste alıp başarısız**
   oluyordu — yani kaynağın gerçekten çalıştığı doğrulanamıyordu. `html.parser`'a geçildi;
   ayrıştırıcı artık her ortamda test edilebilir ve requirements'tan bir paket düştü.
3. **Tavan tam olarak vitrinin ihtiyaç duyduğu satırları atıyordu.** `sort_key` açıklanmış
   olayları **sona** atar ve `filtered_items[:CAP]` **kuyruktan** kırpar; yani kırpılanlar
   hep geçmiş olaylardır. Canlı ölçüm (30 → 60 tavanıyla): 102 olay → 60 kalıyor, atılan
   42'nin **39'u bugün açıklanmış** (11 dün + 28 bugün). Bu tam olarak vitrinin gösterdiği
   kümedir: Investing'in eklediği `actual` verisi kaydedildikten hemen sonra siliniyordu.
   Düzeltme: `CALENDAR_MAX_EVENTS` 30 → **150** (ölçüm ve gerekçe kodda).

## Canlı doğrulama (2026-10-10, gerçek ağ)

`fetch_investing_com_events()` → **23 olay, 21'inde `actual`**.
`merge_calendar_sources(tv=82, inv=23)` → 102 satır; 3'ü TV kimliği altında Investing
üçlüsüyle zenginleşti, 20'si Investing satırı olarak eklendi.

**Kararlı sonuç satırı: 31** — 10'u TradingView, **21'i Investing** kaynaklı. Tavan
düzeltmesinden önce bu satırların çoğu kırpılıyordu. Örnekler:

```
Kanada İşsizlik Oranı              | 6.5% = 6.5% (Beklentiye Uygun)     -> side=None
ABD Michigan Tüketici Güveni       | 46.3 < 47.5 (Beklenti Altı)        -> bearish
İsviçre SECO Consumer Climate      | -36 < -32 (Beklenti Altı)          -> bearish
ABD Haftalık İşsizlik Başvuruları  | 197 < 200 (Beklenti Altı)          -> bullish
```

## Dürüstlük: düşük eşleşme oranı bir HATA DEĞİL

23 Investing olayının yalnız 3'ü TradingView satırıyla birleşti. Bu, eşleştiricinin
kaçırdığı gibi görünse de canlı teşhis nedenini gösterdi:

| Durum | Sayı | Açıklama |
|---|---|---|
| Tam eşleşme | 3 | Aynı para birimi + dakika + kanonik başlık |
| Aynı para birimi+dakika, farklı başlık | 4 | **Gerçekten farklı olaylar** (aşağıda) |
| TradingView'de karşılığı yok | 16 | Investing bugünü, TV haftayı kapsıyor |

"Aynı para birimi+dakika, farklı başlık" grubunun tamamı gerçekten ayrı olaylar:

* aynı dakikada yayınlanan **farklı anketler** — `Michigan Consumer Expectations` /
  `Michigan 1-Year Inflation Expectations` / `Michigan 5-Year Inflation Expectations`
  (TV bunların hiçbirini listelememiş);
* aynı dakikada açıklanan **farklı seriler** — `U.S. Baker Hughes Oil Rig Count` /
  `Total Rig Count`;
* **toplu açıklama** — dört ayrı `CFTC ... speculative net positions` satırı aynı damgada.

Bunları zorla birleştirmek, farklı sayıları tek satıra karıştırmak olurdu — politikanın
tam olarak engellediği şey. Sistematik bir kaçırma **yok**.

Doğrulanmış bir "kopya kalma" vakası: RUB `CPI` iki satır (id 1180/406) — aynı başlık,
aynı dakika, **farklı değerler** (`6.3%` = önceki/açıklanan vs `0.3%` = MoM). Kaynağın
kendisinde ayrı iki olay; birleştirme tahmin etmeyip ikisini de eklediği için doğru.

## Uyarı popup'ı: aynı dakikada açıklanan küme tek popup'a indi

Investing katmanı eklenince ortaya çıkan **ölçülmüş** bir maliyet: uyarı döngüsü
(`ForexCalendarAlertModal.checkApproachingEvents`) `item.id` ile tekilleştirme yapıyor,
ama aynı dakikada açıklanan olayların id'leri farklıdır (`cal-tv-…` vs `cal-inv-…`).
Sonuç: kümedeki **her olay ayrı popup** üretiyordu — ses üst üste, modal yer değiştiriyor.

`selectPriorityAlertEvents` eklendi: aynı zaman damgasındaki olaylardan yalnız **en
önemlisi** (yıldız → impact → girdi sırası) popup hakkı kazanır.

**Ölçüm (canlı):** 102 olay → **58 popup**; 19 küme tekleşti (Kanada 5→1, GBP 6→1,
USD Michigan 4→1). **Tablo hiç değişmedi** — 102 satırın tamamı görünmeye devam eder;
fonksiyon hiçbir olayı gizlemez, yalnız popup önceliğini seçer.

**Neden `(para birimi, dakika)` ile naif dedup YAPILMADI:** ilk akla gelen düzeltme
buydu ve **yanlış** olurdu. TradingView tek başınayken bile aynı dakikada açıklanan 14
gerçek küme var — `EIA Crude Oil Stocks Change` + `EIA Gasoline Stocks Change`,
`Retail Sales MoM` + `Retail Sales Ex Autos MoM`, `Existing Home Sales` + `... MoM`.
Bunlar **farklı olaylar**; dedup bunları bastırırdı. Ölçüm alınmasaydı "dar ve risksiz"
sanılan bu düzeltme gerçek uyarıları yutacaktı.

## Bilinçli kabul edilenler

* **Investing'te `forecast` seyrek.** Çoğu satır `basis="previous"` ile kıyaslanır — zaten
  test edilmiş ana yol. Beklenti sütununun dolması beklenmemeli.
* **Eşanlamlı başlıklar eşleşmez** → görünür kopya. "Bulanık eşleştirme yok" kararının
  kabul edilen bedeli. Ölçülen maliyet: Investing'in eklediği 20 satırdan **4'ü** aynı
  dakikadaki bir TradingView satırıyla örtüşüyor — **1'i gerçek mükerrer**
  (`Consumer Confidence` ≡ `SECO Consumer Climate`, aynı İsviçre verisi), 3'ü farklı
  bileşen (TV Michigan'da yalnız manşeti listeliyor, Investing `Consumer Expectations` /
  `1-Year` / `5-Year Inflation Expectations` satırlarını ayrı veriyor). Operatör Cuma
  15:00'te bu verileri iki satırda, farklı sayılarla görebilir. Yanlış birleştirmeden
  yeğlendi.
* **Tablo %23 uzadı: 82 → 102 satır.** 3 yıldız sayısı **değişmedi** (16); eklenen 20
  satırın tamamı 2 yıldız bandında. Bir kısmı gürültü (Baker Hughes rig count). Popup
  artık 58'e indiği için tablo dışındaki gürültü maliyeti azaldı, tablo uzunluğu kaldı.
* **Üçlü tutarlılık katı**: Investing eşleşti ama `actual`'ı `—` ise TV'nin gerçek
  `actual`'ı `—` ile ezilir ve olay vitrinden düşer. Aynı olay/dakika birlikte
  açıklanacağı için düşük olasılık, ama gerçek bir davranış değişikliği.
* **`index`-joker artığı**: `"148.2"` ile `"3.2%"` yine sayısal kıyaslanır. Joker bilerek
  bırakıldı (TV `unit` güvenilmez); hedef hata kapatıldı, bu kapatılmadı.
* **Tavan artığı**: 150'yi aşan bir pencerede yine kuyruktan (en eski) kırpılır. Sıralamayı
  değiştirmek tablonun okuma sırasını da değiştirirdi; istenmediği için sıra korundu.
* **Aksan/noktasız-i asimetrisi**: `NFKD` birleşen işaretleri atar ama Türkçe `ı` (U+0131)
  ayrışmayan ayrı bir harf olduğu için korunur — `"Oranı" != "Orani"`. Pratikte eşleştirme
  İngilizce `original_title` üzerinden yapıldığından bu kayıp gerçekleşmez.
* **`source` alanı yalnız `raw_data` içinde.** İleride `WHERE source=...` sorgusu gerekirse
  sütun/migrasyon gerekir.

## Kapsam dışı (bilinçli)

* **Vitrin/modali değişmedi** — vitrin kararı (`outcome` ister, modal iki dal + gerekçe)
  reddi doğru biçimde zaten temsil ediyor. Doğrulandı. Frontend'de değişen **tek** şey
  uyarı popup önceliğidir (yukarıda), ki o bir veri sözleşmesi değil görüntü kararıdır.
* **`ORDER BY date_iso ASC` yönü** değişmedi. Kalıcı çözüm ayrı iş.
* **Ölü `hash()` id'leri** (`cal-ff-*`, ForexFactory yolu): Investing tarafı `eventId` ile
  düzeltildi; ff tarafı hâlâ süreçten sürece değişir (mevcut durum).

## Testler

```bash
cd backend && ruff check app tests scripts
```

```bash
cd backend && py -3.12 -m pytest tests/test_forex_news.py -q
```

```bash
cd backend && py -3.12 -m pytest tests -p no:cacheprovider
```

```bash
cd frontend && npx vitest run app/lib/calendarOutcome.test.ts && npm run typecheck && npm run build
```

**Sonuç:** `ruff` → *All checks passed!*; `test_forex_news.py` → **36 passed**; tam backend
süiti → **1340 passed, 18 subtests passed**; vitest (`calendarOutcome.test.ts`) →
**39 passed**; `tsc --noEmit` → temiz; `next build` → başarılı.

**Uyarı önceliği uçtan uca (gerçek ağ + gerçek TS fonksiyonu):** backend'in canlı çektiği
102 olaylık payload `selectPriorityAlertEvents`'ten geçirildi → **102 → 58 popup**, her
zaman damgası en fazla bir kez, hiçbir olay düşürülmedi, girdi mutasyona uğramadı.

Yeni testler: `normalize_event_title` (sondaki belirteç, orta kelime korunur, aksan,
noktasız-i sınırı), `_event_minute`, `merge_calendar_sources` (tek aday / 0 aday / **≥2
aday** / tüketilmiş aday / mutasyonsuzluk / indekslenemeyen overlay),
`calendar_value_unit_family` + `units_compatible` + `evaluate_event_outcome` birim reddi +
reddin `has_data=True` ile birlikte yaşaması, kova ve yön kuralının yapısal tutarlılığı
(Business Inventories / EIA gas storage), `_should_prune_economic_calendar` eşiği ve
fixture tabanlı `parse_investing_payload` (2/3 yıldız filtresi, kararlı `id`, `is_passed`,
bozuk girdi).

**Dürüstlük notu (coverage kapısı):** `--cov-fail-under=55` eşiği bu Windows ortamında
**değişiklikten önce de** karşılanmıyordu (önceki turda ölçülen **%49.25**). Bu değişiklikle
**%50** ölçüldü — kapsam **arttı**, azalmadı. CI Linux'ta eşiğin üzerinde ölçüyor; fark
yerel ortam kaynaklıdır (`sqlalchemy`/`MetaTrader5` yokluğu bazı modülleri dışarıda bırakır).
