# BİLEŞİK SENTIMENT ENDEKSİ — merkez 0, sol SHORT / sağ LONG

**Tarih:** 2026-11-12 · **Sınıf:** bağlam, kapı DEĞİL · **Ölçüm durumu:** ağırlıklar yargı — kenar ÖLÇÜLMEDİ

## 1) Ne istendi

> "Forex paritelerinin her biri için belirli kaynaklardan belirli dilimlerde alınan **haber, ekonomik veri ve temel göstergelerin analizi**; tam ortası 0 kabul edilirse **sol SHORT, sağ LONG**; yüzde olarak hangi tarafa ne kadar yakın — ortası 0 olan bir progressbar üzerinde."

Bu, Myfxbook perakende konumlanmasından **farklı** bir şey: perakende = kalabalığın açık pozisyonu; bu endeks = haber/veri/temel göstergelerin **analitik yönü**. İkisi de skorda ayrı bileşen.

## 2) Dört kanal — hepsi depoda zaten vardı, yenisini veri çekmedik

| Bileşen | Kaynak | Pencere / ölçü | Ağırlık |
|---|---|---|---|
| **Veri (takvim)** | `forex_news.evaluate_event_outcome` (yalnız **açıklanmış** `actual`) | **24 saat**, yarı-ömür 8 saat (yaşla azalan ağırlık) | %35 |
| **COT** | `cot_positions` (CFTC net, `bias` −1…+1) | haftalık rapor | %20 |
| **Küresel nabız** | `market_pulse` (DXY, ABD 10Y, VIX, S&P) | günlük değişim, `tanh` ölçek | %25 |
| **Kalabalık** | `retail_sentiment` (Myfxbook) | son tur (15 dk) — **ters** okunur | %20 |

**Skor:** `Σ(wᵢ·sᵢ)/Σ(wᵢ)` → **−100 (SHORT) … +100 (LONG)**. Her bileşen aynı işaret kuralına uyar (+ = LONG).

**Sembol haritalama:** USD bazlı paritelerde USD gücü ters, USD kotasyonlu paritelerde düz; altında zayıf dolar + risk-off; endekslerde risk iştahı; kriptoda risk-on − dolar. Kur haritası olmayan sembolde küresel bileşen **nötr vermez, devre dışı kalır**.

## 3) Dürüstlük kuralları (kodda zorunlu)

1. **Eksik veri nötr SAYILMAZ.** Bileşen yoksa ağırlığı düşer, `coverage` ve `missing` döner. Tek bileşen varsa skor **o bileşendir** (0'a seyreltilmez).
2. **Spekülasyon yok.** Takvim bileşeni yalnız `actual` dolu ve ayrıştırılabilir olayları kullanır (2026-10-14 kullanıcı kuralı: "açıklandıktan sonra").
3. **Kelepçe değil `tanh`.** İlk sürümde `clamp` vardı; sert bir günde tek bileşen ±100'e sabitlenip diğer üçünü gölgeliyordu. `tanh` doyumu kaldırdı.
4. **Ağırlıklar yargıdır.** `WEIGHTS` tek yerden değişir; ölçülmüş bir kenar değildir.
5. **KAPI DEĞİL.** Karar akışı, lot, radar sıralaması değişmez.

## 4) Yüzeyler

| Yüzey | Nerede |
|---|---|
| Ana sayfa | `SentimentGaugeCard` — **merkez 0 gauge** (sol kırmızı SHORT / sağ yeşil LONG), skor, kapsam rozeti, bileşen rozetleri |
| API | `GET /api/system/sentiment-index?symbols=...` (ağırlıklar + bantlar döner) |
| LLM | `context_extras.macro_context` 6. blok `bilesik_sentiment` + `compact_lines` satırı |
| Besleme | Canlı döngüdeki takvim çağrısına bağlı (`forex.py`, ek ağ isteği yok, 120 sn önbellek) |

## 5) Bugünkü okuma (örnek, 2026-11-12)

| Sembol | Skor | Etiket | Kapsam | Bileşenler |
|---|---|---|---|---|
| USDJPY | **+50** | LONG (belirgin) | %100 | veri +60 · COT +13 · küresel +82 · kalabalık +32 |
| EURUSD | **−39** | SHORT | %100 | veri +6 · COT −27 · küresel −82 · kalabalık −76 |
| GBPUSD | −24 | SHORT | %100 | veri −21 · COT +31 · küresel −82 · kalabalık −14 |
| XAUUSD | −11 | DENGELİ | %80 | veri +12 · küresel −22 · kalabalık −38 |
| NAS100 | −71 | SHORT (belirgin) | %25 | yalnız küresel (COT/kalabalık kapsam dışı) |

## 6) Sınırlar ve ölçüm yolu

- **Kenar ölçülmedi.** Bu bir *özet göstergedir*; "şu skorun üstünde long aç" kuralı kanıtlanmadı. Kapıya çevirmek için skorun **loglanması** ve ileri getiriyle IC'sinin ölçülmesi gerekir (retail için yazılan `retail_sentiment_edge.py` deseninin aynısı).
- Endekslerde kapsam %25: COT ve perakende yok → skor tek kanala dayanır, `coverage` bunu gösterir.
- Ağırlıklar şu an elle; ölçüm sonrası veri-temelli ağırlık denenebilir (ama o zaman da overfit riski).
- `bias` (COT) yorumu CFTC rapor tarihine bağlı; hafta ortasında bayatlayabilir.

## 7) Dosyalar

- `backend/app/sentiment_index.py` — bileşik skor çekirdeği (ağ yok, yalnız mevcut önbellekler)
- `backend/app/routers/system.py` — `GET /api/system/sentiment-index` + ısıtma
- `backend/app/context_extras.py` — `bilesik_sentiment` bloğu + satır
- `frontend/app/components/SentimentGaugeCard.tsx` — merkez 0 gauge
- `backend/tests/test_sentiment_index.py` — 16 sözleşme testi (ağa çıkmaz)
