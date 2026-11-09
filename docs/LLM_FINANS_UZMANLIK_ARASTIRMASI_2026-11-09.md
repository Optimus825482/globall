# LLM Finans Piyasaları Uzmanlığı — Araştırma + Entegrasyon (2026-11-09)

**Görev:** LLM'in (sohbet / tarama / işlem ikinci-görüş) tahminlerini güncel kılmak ve
"Forex + finans piyasaları uzmanı" rolünü sayısal bağlamla desteklemek.
**Yöntem:** Önce mevcut LLM bağlam yolu haritalandı (kod kanıtlı), sonra eksik veri
kaynakları **canlı ölçülerek** seçildi, son olarak entegrasyon + test + uzmanlık
skill'leri aynı turda uygulandı.

---

## 1. Mevcut durum denetimi (kod kanıtlı, harita)

LLM'e bağlam veren 3 yüzey ve o anki içerikleri:

| Yüzey | Bağlam kaynağı | Zengin olduğu alanlar |
|---|---|---|
| İşlem ikinci-görüş (dossier) | `app/llm_trade_review.build_dossier` | işlem detayı, ATR/RSI/ADX, çok-TF teknik, haber başlıkları, DXY rejimi, hesap yığılması, yaklaşan veri dakikaları, yapı kırılması (ruptures) + HMM rejim, COT/seans/edge (context_extras) |
| Panel "Fırsat taraması" | `routers/forex_chat.build_context` | tarama adayları, teknik, takvim, haber, DXY, demo işlemler, makro_baglam |
| Genel sohbet / sembol analizi | `routers/llm_chat` + `app/context_extras.macro_context` | 7-TF snapshot, market_scan, self-learning, bellek, makro_baglam, Fear&Greed (yalnız kripto hızlı şeridi) |

**Boşluklar (2026-11-09 denetimi):**

1. **VIX** — backend'de SIFIR geçiş.
2. **ABD tahvil verimi (US10Y)** — yalnız haber başlığı metninde "yield" kelimesi; sayı YOK.
3. **Altın / petrol gibi emtia cross-asset serileri** — isim olarak takvim metninde; fiyat/yön YOK.
4. **Fear&Greed** — yalnız kripto hızlı şeridinde; forex/emtia yüzeylerine girmiyor.
5. **Ekonomik takvim** — genel llm_chat sohbet bağlamında YOK (forex_chat + dossier'de var).

Bu boşlukların etkisi: persona "küresel Forex, Emtia ve Endeks uzmanı" diyor
(`app/llm_analysis.get_persona`), ama model risk iştahı/faiz/emtia okumasını
**kendi uydurmasıyla** dolduruyordu — kalıcı halüsinasyon kapısı.

---

## 2. Kaynak araştırması — iddialar CANLI ölçüldü (2026-11-09)

"Anahtarsız cross-asset fiyat kaynağı" adaylarının her biri `curl` ile o gün test edildi:

| Kaynak | Ölçüm | Sonuç |
|---|---|---|
| **Yahoo Finance v8 chart API** | `^VIX` → 20.65 · `DX-Y.NYB` → 101.902 · `^TNX` → 4.876 · `GC=F` · `CL=F` · `^GSPC` · `EURUSD=X` — **7/7 sembol 200**, düz User-Agent ile, anahtar YOK | ✅ **SEÇİLDİ** |
| **stooq.com CSV** (`q/l/?s=…&e=csv`) | `^vix`, `dx_f`, `dxy`, `xauusd`, `10usy.b`, `cl.f`, `^spx` — **6/6 sembol 404** ("The page you requested does not exist") | ❌ KARA LİSTE (Investing.com 403 dersinin aynısı — tekrar denenmez) |
| FRED (`fredapi`) | API anahtarı ister | Çağrılmaz (kotaya takılan anahtarlı kaynağı yedek yapma dersi — FMP budget turu) |
| FMP | Anahtar ister, ücretsiz plan 25 sorgu/gün | Çağrılmaz |

**Kritik proje içi bulgu:** Yahoo v8 chart API'si **zaten** `app/forex_research.py:114
_yahoo_candles` tarafından yıllardır kullanılıyor (UA + önbellek + hata izolasyonu
hazır). Yeni HTTP yolu yazmak yerine o yardımcı yeniden kullanıldı — sıfır yeni
bağımlılık (stdlib; `curl_cffi` gerekmedi, düz `urllib` geçti).

**^TNX birim tuzağı:** Yahoo'nun `^TNX` serisi **yüzde cinsinden** veriyor (2026-11-09
canlı: 4.876 → %4.88; ×10/100 tuzağına düşmeden). Test `ABD 10Y verim %4.88` biçimini
kilitler.

---

## 3. Entegrasyon — ne eklendi

### 3.1 `backend/app/market_pulse.py` (YENİ, üretim katmanı, stdlib)

Küresel varlık nabzı: **6 varlık × 5 işlem günü değişimi + sabit kural tablosu yorumu.**

| Varlık | Yahoo sembolü | Yorum kuralı |
|---|---|---|
| VIX | `^VIX` | CBOE klasik bantlar: <15 sakin · 15-20 normal · 20-25 gergin · >25 **STRES** |
| Dolar Endeksi | `DX-Y.NYB` | ±1% → GÜÇLÜ/–1% → belirgin zayıf; 0.2 bandı içinde yatay |
| ABD 10Y verim | `^TNX` | baz puan değişimi: yükseliş = USD'ye destek, riskli varlığa baskı |
| Altın | `GC=F` | yön + büyüklük |
| WTI petrol | `CL=F` | yön + büyüklük |
| S&P 500 | `^GSPC` | yön + büyüklük |

**Çapraz okumalar** (yalnız İKİ tarafın da verisi varsa kurulur — sessiz boşluk kuralı):
- DXY↑ + Altın↑ → "güvenli liman/ihtiyatlılık baskın; altın rallisini yalnız 'dolar zayıf' diye okuma"
- DXY↓ + Altın↓ → "klasik korelasyon bozuk — likidite çekilmesi şüphesi"
- VIX↑(>2%) + SPX↓(>1%) → "risk iştahı DARALIYOR; uzun fikirlerde kanıt eşiği artmalı"

**Sözleşmeler:** TTL 900 sn önbellek (6 istek/15 dk ≈ 24 istek/saat — rate limit güvenli);
hata satır bazında izole; hepsi başarısızsa `available=False` + "uydurulmaz" cümlesi;
yuvarlanmış sayılar (ham float JSON'a girmez); **karar/skor üretmez** — BAĞLAMDIR
(COT dersinin aynısı: skorlamaya sokmak ölçülmüş ayrı iş ister).

### 3.2 `app/context_extras.py` — dördüncü blok

`cross_asset_block()` → `macro_context()`'e `"kuresel_varlik_nabzi"` ve
`compact_lines()`'e `cross_asset_lines()` olarak bağlandı. **Tek uygulama kuralı
sayesinde üç LLM yüzeyine otomatik yayılır** — dossier, fırsat taraması ve sohbet
aynı satırları görür; panel/LLM çelişkisi imkansızlaşır.

### 3.3 `app/database.py` — 3 uzmanlık skill seed'i (`llm_skills`)

Panelden eziyet edilmemesi için mevcut seed sözleşmesiyle (`ON CONFLICT DO NOTHING`);
`ensure_default_scalper_skill` → **`ensure_default_llm_skills`** oldu (tek çağıran
`main.py:1101` güncellendi). Skill'ler `get_active_llm_config` üzerinden sohbet
system prompt'una akar:

| Skill | Öğrettiği |
|---|---|
| **Forex Makro Okuma** | nabzı okuma sırası (risk iştahı → dolar → faiz → emtia); DXY-altın birlikte yükselişi "güvenli liman" olarak okuma; VIX stres bandında boyut küçültme; veri yoksa piyasa geneli varsayımı YASAK |
| **Risk Yönetimi Disiplini** | her fikirle giriş/teyit/invalidasyon/hedef + gereken isabet; yüksek etkili olay ±30 dk giriş YOK; COT kalabalık/ayrışmada stop tamponu; düşük likidite penceresinde maliyet uyarısı |
| **Veri ve Haber Etki Okuma** | takvim satırını sürpriz yönü olarak okuma ("beklenen"i geleceğe tahmin gibi sunma YASAK); COT'un haftalık+3g gecikmesi; başlık tek başına sinyal değil; sayısal alan yoksa "bilinmiyor" |

Bu üçü, bağlamda ARTIK VAR olan sayıları (nabzı, COT'u, takvimi) yanlış okuma
kalıplarını kapatır — veri + kural birlikte gelir; ikisi tek başına yetmezdi.

### 3.4 `/api/system/health` — `cross_asset_pulse` bloğu

`market_pulse.cached_summary()` kullanır: **ağ çağrısı yapmaz** (deploy-düzeltmesi
dersi — health/liveness yolu network'e çıkamaz). İlk nabzı ilk LLM bağlam çağrısı
ısıtır; health `warming: true` bildirir.

---

## 4. Doğrulama kanıtları

**Sentetik (bilinen-cevap) testler** — `tests/test_market_pulse.py` + `tests/test_macro_context.py`
güncellemesi: **42/42 geçti.** Kilitlenenler: 90→100 = %+11.11 hesabı; kısa seride
None (uydurma yok); VIX 27.5 → "STRES rejimi"; DXY +1.5 → "GÜÇLÜ baskı"; 4.75→4.88
→ "+13 baz puan / yükseliyor"; DXY↑+Altın↑ → çapraz not; VIX↑+SPX↓ → "DARALIYOR";
tek taraf varken çapraz not YOK; hepsi başarısız → fail-closed "uydurulmaz"; TTL
önbellekte ikinci çağrı istek ATMZ; health ağa çıkamaz (`cached_summary` kilitli);
`macro_context` 4 blokluk sözleşme.

**Gerçek kaynak (canlı, 2026-11-09):** `pulse(force=True)` 6/6 varlık döndürdü:

```
VIX 20.74 (5g %-1.94) → "gergin — risk iştahı tartılı"
DXY 101.86 (5g %+0.11) → "dolar yatay"
ABD 10Y %4.88 (5g -1 baz puan) → "faiz beklentileri düşüyor (risk-on rüzgârı)"
Altın 4137.10 USD (5g %+4.22)   WTI 88.01 USD (5g %-8.76)   S&P 500 7523.95 (5g %-0.23)
```

---

## 5. Beklenen etki defteri (§C usulü)

| Değişecek | Değişmeyecek |
|---|---|
| LLM'in 3 yüzeyi artık **gerçek** VIX/DXY/10Y/altın/petrol/SPX yönü ve büyüklüğü görebilir; "piyasa geneli" yorumları uydurma yerine ölçüme bağlanır | Karar akışı: nabzı hiçbir skor/kanal/kapıya girmiyor — sinyal üretimi aynı |
| VIX stres / DXY-altın çaprazı / verim yönlü üç deterministik uyarı cümlesi LLM'e düşer | LLM modeli, endpoint, gecikme, maliyet: değişmedi (bağlam +~30 satır metin) |
| Sohbet uzmanlık skill'leri (3 seed) panelden görüntülenebilir/kapatılabilir | Fear&Greed hâlâ yalnız kripto şeridinde (aşağıda açık iş) |

**Tuzak kayıtları (uygulama sırasında yakalananlar):**
1. `compact_lines` mock/eksik summary'de `KeyError: 'label'` → savunmalı `a.get('label') or _label` (test ısrarıyla).
2. `^TNX` birim karışıklığı (×10 eski söylenti) → canlı değer 4.876 = %4.88 olarak ölçüldü ve testle kilitlendi.
3. `test_macro_context_shape` cross-asset bloğu yüzünden sessizce AĞA çıkacaktı → mock'la izole edildi (test paketi Yahoo'ya gitmez).

---

## 6. Açık işler (bilinçli olarak bu turda YAPILMADI)

| Madde | Neden |
|---|---|
| Fear&Greed'i macro_context'e genişletme | `alternative.me` kaynağı kripto odaklı; forex için CNN Fear&Greed ayrı kaynak işi — ayrı tur |
| Ekonomik takvimi llm_chat genel sohbetine ayrıca bağlama | `macro_context`'e mini takvim özeti eklemek mümkün; dossier/panel'de zaten var, tekrar riski — ayrı tur, ölçerek |
| Nabzı skorlamaya/kapıya sokma | COT ve geometri dersinin aynısı: BAĞLAM ≠ SİNYAL. "VIX stres = işlem açma" kuralı ancak replay A/B ile ölçülür |
| US2Y/US30Y, gümüş, EUR verimi genişletmesi | 6 varlık önce 2-3 hafta izlenmeli; genişleme çağrı bütçesini büyütür |
| Yahoo rate-limit gerçek davranışı | 24 istek/saat tasarımı güvenli; yine de ilk hafta health'teki `cross_asset_pulse.missing` izlenmeli |

---

## 7. Dosyalar

| Dosya | İş |
|---|---|
| `backend/app/market_pulse.py` | YENİ — cross-asset nabzı (fetch + yorum + TTL önbellek + fail-closed) |
| `backend/app/context_extras.py` | 4. blok `kuresel_varlik_nabzi` + `cross_asset_lines()` |
| `backend/app/database.py` | 3 uzmanlık skill seed'i + `_DEFAULT_SKILL_SEEDS` + `ensure_default_llm_skills()` |
| `backend/app/main.py` | seed çağrısı yeni ada |
| `backend/app/routers/system.py` | health'e `cross_asset_pulse` (ağsız) |
| `backend/tests/test_market_pulse.py` | YENİ — bilinen-cevap testleri |
| `backend/tests/test_macro_context.py` | shape sözleşmesi 4 blok + mock izolasyonu |
