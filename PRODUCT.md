# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users
Tek operatör (ürün sahibi): botu canlı izleyen, stratejileri test eden ve sonuçları denetleyen bireysel trader/araştırmacı. Masaüstünde terminal olarak, canlı izleme sırasında telefonda dikey (portrait) kullanır. Başka kullanıcı ya da müşteri doğrulanmadı.

## Product Purpose
Binance spot (kripto) için paper-trading scalper ile forex ve XAU için MT5 DEMO ölçümünü tek panelde toplar. Operatör sinyalleri, pozisyonları, grafikleri, raporları ve strateji sonuçlarını izler; ayarları yönetir ve LLM sohbetiyle piyasayı tarar. Başarı: durum bir bakışta okunur, her işlemin nedeni denetlenebilir, uzun işler ilerleme ve log gösterir.

## Positioning
Üç doğrulanmış fark birlikte: (1) kanıt odaklı denetim (kaynak, zaman damgası, neden, replay), (2) LLM'in pozisyon okuyup yönettiği sohbet+işlem yardımcısı, (3) backtest/holdout/kombo sonuçlarını dürüstçe ölçen strateji laboratuvarı. Şu an yalnızca paper ve demo; canlı fonlu işlem yok.

## Operating Context
Backend FastAPI + PostgreSQL, frontend Next.js (port 3004), Binance public WebSocket, MT5 köprüsü (`run_mt5_bridge.bat`), Docker/nginx dağıtımı. Operatör Windows'ta çalışır; raporlar ve analiz betikleri repoda tutulur. Telefonda canlı izleme yaygındır.

## Capabilities and Constraints
- Rotalar: terminal (`/`), `charts`, `forex`, `settings`, `chat`, `profile`, `system-health`, `metamobil`.
- Şu an gerçek para emri yok; PAPER / SALT OKUNUR ve DEMO etiketleri görünür kalmalı.
- Forex + XAU MT5 demo ölçümü aktif; ileride gerçek hesaba geçiş olabilir (karar verilmedi, tarih yok). Geçiş olursa canlı/demo ayrımı ve onay akışı yeni tasarım gerektirir.
- Arayüz dili Türkçe, teknik terimler olduğu gibi.
- 320px'ten itibaren sayfa düzeyinde yatay taşma yok; tablolar kendi kapsayıcısında kaydırılır.

## Brand Commitments
Ad: "Scalper Global Agent". Mevcut koyu terminal dili (bunker yüzeyler, neon yeşil/sarı/kırmızı/mavi durum renkleri, Inter + monospace) korunur; kesin görsel kararlar DESIGN.md'de.

## Evidence on Hand
Gerçek canlı/paper veriler, rapor dosyaları (`Erkan_Analiz_Raporu_2026_10_10.md`, `FX_KALIBRASYON_PLANI.md`, `TESTLER.md`, `docs/`). Müşteri, referans, benchmark veya kanıtlanmış karlılık iddiası yok; uydurulmamalı.

## Product Principles
1. Kanıt yorumdan önce gelir: kaynak, durum, zaman damgası, neden.
2. Dürüstlük: simüle veya eksik veriyi gerçekmiş gibi gösterme; kayıp ve hata görünür.
3. Paper/demo sınırı her an açık; gerçek emir dili yalnızca açık bir geçiş kararından sonra.
4. Operatör hızı: önce durum ve birincil eylem, sonra kanıt ve tanı.
5. Telefonda da tam kullanılabilir canlı izleme.

## Accessibility & Inclusion
Pratik WCAG 2.1 AA: kontrast, klavye erişimi, ~44px dokunma hedefi, renk tek sinyal değil, `prefers-reduced-motion` desteği.
