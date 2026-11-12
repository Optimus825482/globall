# PERAKENDE KONUMLANMA (Myfxbook) — FX'te kalabalığın tarafı

**Tarih:** 2026-11-12 · **Kaynak:** Myfxbook topluluk outlook (ücretsiz API) · **Sınıf:** bağlam, kapı DEĞİL

## 1) Neden

Kriptoda türev verisi vardı (`derivatives_service` → Binance long/short, taker, OI). **FX tarafında perakende konumlanma hiçbir yüzeyde yoktu.** Bu, fiyattan türetilemeyen tek ücretsiz kitle bilgisi: EURUSD %88 long gibi bir okuma "herkes aynı tarafta" hipotezini ölçülebilir kılar.

## 2) Kaynak doğrulaması (2026-11-12, canlı)

| Yol | Sonuç |
|---|---|
| Myfxbook `login.json` → `get-community-outlook.json` | ✅ **HTTP 200, 88 sembol** (session ile) |
| Cloudflare koruması | Düz `curl` **403**; **`curl_cffi` + `impersonate="safari17_0"` → 200** (ForexFactory dersinin aynısı) |
| `widgets.mfbcdn.net/widgets/getOutlookData.json` | Anahtarsız **200 ama BOŞ** (`symbolsQuotes: {}`) — kullanılmaz |
| Dukascopy SWFX sentiment | 403 |
| FXSSI API | 404 |
| DailyFX sentiment | 403 |

**Ücret:** API ücretsiz (Myfxbook: *"we strive to keep our service free of any charge"*). Anahtar yok — **ücretsiz hesap** yeterli.
**Kota:** `get-community-outlook` ücretsiz **100 istek/24s** (paralı 2.880). Session **IP'ye bağlı**, ~1 ay.
**Kapsam sınırı:** FX + altın var; **endeksler (US30/NAS100/JP225/UK100) yok** → o sembollerde satır "kapsamda yok" der, sayı uydurulmaz.

## 3) Kurulan yapı

| Dosya | İş |
|---|---|
| `backend/app/retail_sentiment.py` | login → session (DB'de, 1 ay TTL, IP hatasında bir kez yeniden login) → outlook → normalize → özet/satır |
| `backend/app/database.py` | `retail_sentiment_history` (geçmiş log) + `retail_sentiment_session` |
| `backend/app/routines/db_routines.py` | `retail_sentiment` rutini, **30 dk** → panel kapalıyken de log birikir |
| `backend/app/context_extras.py` | 5. bağlam bloğu `perakende_konumlanma` → LLM dosyası / fırsat taraması / sohbet |
| `backend/app/routers/system.py` | `GET /api/system/retail-sentiment` + health içinde `retail_sentiment` |
| `frontend/app/components/RetailSentimentCard.tsx` | **Ana sayfa kartı** (kalabalık taraflar, çubuk + pozisyon sayısı) |
| `scripts/retail_sentiment_edge.py` | Ölçüm: aşırı konumlanma → ileri getiri (Spearman IC + kovalar + t) |
| `backend/tests/test_retail_sentiment.py` | 11 kilit test (ağa çıkmaz) |

**Kota koruması:** tur aralığı 30 dk (48 istek/gün) + günlük sert tavan 90 + aşımda **ağa çıkmaz**.
**İlk yükleme:** süreç yeniyse bellek boş olur → DB'deki son tur hydrate edilir ("veri yok" yanlış mesajı çıkmaz). Session da DB'den okunur, her restart'ta login (kota) harcanmaz.

## 4) Bugünkü okuma (örnek)

```
EURUSD  45301 pozisyon · %88 long / %12 short  → KALABALIK LONG
EURGBP  11868 pozisyon · %94 long / %6  short  → KALABALIK LONG
XAUUSD  14697 pozisyon · %69 long / %31 short  → eşik altı
GBPUSD  21915 pozisyon · %57 long / %43 short  → dengeli
```

## 5) Neden KAPI DEĞİL

Kapı yapmak için tek yol **ölçüm**. `retail_sentiment_edge.py`:
- Spearman IC: long% ↑ ise ileri getiri ↑ mı? (contrarian hipotez doğruysa **NEGATİF** olmalı)
- long% kovaları (≤30 / 31-49 / 50-69 / ≥70) için ortalama ileri getiri (pip) + t
- `--min-n 200` altında **"YETERSİZ ÖRNEKLEM"** der, sayı üretmez
- Maliyet düşülmemiş sütun ayrıca belirtilir → brüt kenar spread'in altındaysa karar değeri yok

**Veri geriye dönük alınamıyor.** Log bugün başladı; 6-8 hafta sonra ölçüm anlamlı olur. O zamana kadar yalnız bağlam.

## 6) Açık işler

1. 6-8 hafta sonra `retail_sentiment_edge.py --all --days 45 --horizon-h 24` → IC negatif + `|t|≥2` ise replay A/B.
2. Kalabalık eşiği (%70) görüntü ayarı; ölçümden sonra revize edilebilir.
3. `retail_sentiment_history` büyüdükçe panelde zaman serisi grafiği (şimdilik yalnız son tur).
