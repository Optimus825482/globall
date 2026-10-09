# Ekonomik Takvim — "Bugün Açıklanan Veriler" Vitrini + Tek Senaryo Modali (2026-10-09)

**Kaynak gereksinim:** Operatör talebi (2026-10-09): *"haberler kısmında özellikle veri
açıklaması olanlarda önceki beklenen ve veri açıklandıktan sonra açıklanan veri o gün
boyunca orada gösterilsin ve hangi senaryo gerçekleşti ise alt kısımda sadece o kalsın"*.
**Durum:** Kod hazır, testler yeşil, **canlı VARSAYILAN AÇIK** (bayrak arkasında değil).

## Sorun

Takvim hattı `forecast`/`previous`/`actual` alanlarını **zaten** çekiyordu
(`_fmt_val`, `fetch_tradingview_events`) ve `actual` dolunca `status = "Açıklandı"`
yapıyordu. Ama:

1. Hiçbir katmanda `actual` ile `forecast`/`previous` **karşılaştırılmıyordu** — hangi
   senaryo dalının gerçekleştiği hiçbir yerde hesaplanmıyordu (repoda böyle bir kod
   olduğu **kanıtlandı**: yok).
2. Modal her zaman 🟢 **ve** 🔴 dalını birlikte gösteriyordu; operatör hangisinin
   gerçekleştiğini tablodaki üçlüyü kafasında yorumlayarak bulmak zorundaydı.

## Ne yapıldı

| Katman | Değişiklik |
|---|---|
| `backend/app/forex_news.py` `classify_event_bucket` (**yeni**) | Senaryo metnini üreten anahtar kelime dalları tek kaynağa çıkarıldı; hem `generate_event_scenario` hem yön kuralı aynı kovayı kullanır |
| `forex_news.py` `higher_is_bullish_for_event` (**yeni**) | Yön kuralı: standart `yüksek = 🟢`; işsizlik/başvuru ve gerçek petrol stoğu **ters**; enflasyon ailesi **çevrilmez** |
| `forex_news.py` `parse_calendar_value` (**yeni**) | `"0.2%"`→0.2, `"145K"`→145000, `"-1.5M"`→-1500000, `"2,2%"`→2.2; `"—"`/serbest metin→`None` |
| `forex_news.py` `evaluate_event_outcome` (**yeni**) | `side`, `bucket`, `basis`, `comparison_tr`, `label_tr`, `direction_note_tr` üretir |
| `forex_news.py` `_update_event_dynamic_fields` | `has_data`/`outcome` her okuma yolunda (RAM/DB/disk/fallback) doldurulur — **şema migrasyonu yok** |
| `frontend/app/lib/calendarOutcome.ts` (**yeni**) | Saf görüntü mantığı: pencere (UTC+3 takvim günü), dal seçimi, vitrin filtresi |
| `frontend/app/page.tsx` | `EconomicEvent` genişletmesi + **"Bugün Açıklanan Veriler"** vitrini + modal tek dal |

### Tasarım kararı: karar backend'de, görüntü frontend'de

Senaryo metinleri ve gerçek `actual` değerleri yalnızca backend'de olduğu için yön kararı
orada verilir; frontend kararı **okur, yeniden türetmez**. Kuralı frontend'de kopyalamak
"gösterilen senaryo metni" ile "seçilen dal"ın zamanla ayrışmasına yol açardı.
Frontend'de kalan tek mantık **zaman penceresi**dir.

### Gösterim penceresi

Açıklanma anından **o takvim gününün sonuna** kadar (Türkiye saati, UTC+3; 2016'dan beri
DST yok). Gün sınırı kullanıcının gördüğü saatle aynı olmalı: arayüz olay saatlerini zaten
"Bugün 21:00" gibi TSİ ile gösteriyor (`format_event_date`). UTC tabanlı bir sınır koysaydık
23:00 TSİ'de açıklanan bir veri ekranda gece yarısından 3 saat **önce** kaybolurdu.

Pencere mevcut saniyelik paylaşımlı sayaçla (`useSharedNowSec`) değerlendirilir — **yeni
interval kurulmaz**. Bu, 2026-10-08'de satır-başına interval kaldırılarak düzeltilen
performans hatasının tekrarını engeller; gün dönümünde kart **fetch beklemeden** düşer.

## Canlı veri bulgusu (2026-10-09 — tasarımı değiştirdi)

TradingView akışı incelendiğinde 46 olayın **33'ünde `actual` var ama yalnız 13'ünde
`forecast` var**; `previous` neredeyse hepsinde dolu.

Sonuç: `basis="previous"` **istisna değil, ana yol**. Bu yüzden rozet metni tabana göre
değişmek zorundadır — `forecast` → "Beklenti Üzeri/Altı", `previous` → **"Önceki'ye Göre
Artış/Azalış"**. Aksi halde boş bir Beklenti alanına atıfla yanlış bilgi verilmiş olurdu.

## Uygulama sırasında yakalanan iki gerçek hata

1. **Çift birim / üstel gösterim:** `_format_comparison_value` ayrıştırılmış sayıyı kendi
   birim ekiyle yeniden basıyordu → `231K` ekranda **"231000K"**, `2.4M` → **"2.4e+06M"**.
   Düzeltme: kıyas metni **ham kaynak metinlerden** kurulur (`"231K > 220K (Beklenti Üzeri)"`),
   birim eki zaten metnin içinde. Regresyon testi eklendi.
2. **Rozet ↔ yön çelişkisi:** Ters ailelerde sayısal ilişki ile piyasa yönü ayrışır —
   "231K > 220K" ama sonuç 🔴. Yalnız "Beklenti Üzeri" yazan bir rozet, bu özelliğin
   önlemek için var olduğu yanlış okumayı bizzat üretirdi. Düzeltme: yalnız ters ailelerde
   dolan `direction_note_tr` alanı eklendi; vitrin ve modal "⚠️ Yüksek değer bu olayda
   **ayı** yönlüdür" uyarısını basar.

## Asla tahmin etme sözleşmesi

- Yalnız `forecast` boş olmak **dal belirsiz demek değildir** — `previous` tabanı var.
- **Her iki** taban da `"—"` ise `outcome=None`, modal iki dalı da gösterir.
- Ayrıştırılamayan `actual` → `outcome=None`.
- Eşitlikte (`|fark| < 1e-9`) `side=None` → dal gizlenmez, ikisi de gösterilir.
- `date_iso` yok/bozuksa pencere kararı verilemez → veri **gizlenmez**, gösterilir
  (`isOutcomeVisibleNow` `true` döner; kullanıcı gerçek bir açıklamayı kaçırmasın).

## Değişecek dosyalar

| Dosya | Değişiklik |
|---|---|
| `backend/app/forex_news.py` | 2 yardımcı + 3 saf fonksiyon + kova ortaklaştırma + `_update_event_dynamic_fields` |
| `backend/tests/test_forex_news.py` | 12 yeni test (parser, yön kuralı, taban önceliği, belirsizlik, geriye dönük uyum, kıyas biçimi, ters-aile notu) → dosyada toplam **17 test** |
| `frontend/app/lib/calendarOutcome.ts` | **YENİ** — saf pencere/karar yardımcıları (+ `directionNoteText`, `branchFallbackReason`) |
| `frontend/app/lib/calendarOutcome.test.ts` | **YENİ** — 30 vitest testi |
| `frontend/app/page.tsx` | `EconomicEvent` genişletmesi, vitrin bloğu, modal tek-dal |

## Bilinçli kabul edilenler

- **Kaynak kısıtı:** `actual` yalnız TradingView akışından gelir. Investing / ForexFactory /
  yerleşik `FALLBACK_EVENTS` yolunda `actual` boş olduğu için o olaylar vitrine hiç girmez ve
  modalları eskisi gibi iki dal gösterir. Bu kaynak kısıtıdır, bu değişiklikle giderilmez.
- **Hassas olmayan karşılaştırma:** `%` ile `K` farklı birimlerse (kaynaklar arası nadir
  sapma) yine sayısal kıyaslanır; birim uyuşmazlığı ayrıca kontrol edilmez.
- **Mevcut bir latent hata korunuyor:** `generate_event_scenario`'daki `inventories`/`stok`
  anahtarı "Business Inventories" gibi petrol dışı olayları da yakalar ve ters yorumlar.
  Yeni yön kuralı bu tuzağı **büyütmez** (`_OIL_STOCK_HINTS` petrol/stok eşleşmesini
  daraltır) ama mevcut senaryo metnini düzeltmez — ayrı bir iş.
- **Modal anlık görüntüsü:** `selectedEvent` açık modalda dondurulmuş bir nesnedir; arka plan
  fetch'i açık modalın `outcome`'unu tazelemez. `status`/geri sayım için de mevcut davranış
  budur.
- **Kova sırası:** "Fed ... Inflation" `rate`'e, "Unemployment Rate" `rate`'e düşer (mevcut
  senaryo metni kova sırasına bağlı; sırayı değiştirmek gösterilen metni değiştirirdi).
  Yön kuralı yine doğrudur çünkü işsizlik ters çevirmesi kova kontrolünden **önce** uygulanır.

## Kapsam dışı (bilinçli)

- `frontend/app/forex/components/ForexCalendarAlertModal.tsx` (açıklanmadan 5 dk önce çıkan
  uyarı) **değişmedi** — o an veri henüz yok, iki dal birlikte doğru davranıştır.
- `database.py` şeması **değişmedi**: olay `raw_data` TEXT blob olarak saklanıyor, `outcome`
  oradan akar; eski satırlar ilk okumada alanları kazanır.

## Testler

```bash
cd backend && ruff check app tests scripts
```

```bash
cd backend && py -3.12 -m pytest tests/test_forex_news.py -q
```

```bash
cd frontend && npx vitest run app/lib/calendarOutcome.test.ts && npm run typecheck
```

**Sonuç:** `ruff` → *All checks passed!*; `test_forex_news.py` → **17 passed**; tam backend
süiti → **1321 passed, 18 subtests passed**; vitest (`calendarOutcome.test.ts`) → **30 passed**;
`tsc --noEmit` → temiz.

**Uçtan uca (tarayıcı, koyu + açık tema):** Altı olaylık bir takvimle doğrulandı —
3 doğru olay vitrinde (dün açıklanan, henüz açıklanmayan ve eşitlik olayı **girmedi**);
kartlarda Beklenti/Önceki/Açıklanan yan yana ve kaynak birimleri korunmuş (`231K > 220K`,
`2.4M > -1.2M` — "231000K"/"2.4e+06M" değil); ters aile kartında ⚠️ uyarısı; modalda yalnız
gerçekleşen dal + "✅ Gerçekleşen Senaryo" rozeti; eşitlik/henüz-açıklanmadı durumlarında iki
dal + **doğru** gerekçe metni.

**Dürüstlük notu (coverage kapısı):** `--cov-fail-under=55` eşiği bu Windows ortamında
**değişiklikten önce de** karşılanmıyordu (parent commit `6ad3b2dc`'de ölçülen: **%49.12**;
değişiklikle **%49.25**). CI Linux'ta %57 ölçüyor (workflow yorumu); fark yerel ortam
kaynaklıdır. Bu değişiklik kapsamı **artırır**, azaltmaz.
