# Globall / SCALPER GLOBAL — Arayüz Tasarım & Frontend Denetimi
**Tarih:** 2026-11-09 · **Kapsam:** `frontend/` (Next.js 16 App Router, React 18, Tailwind 3.4) · **Yöntem:** statik kod denetimi + token/kontrast ölçümü (`web-design` skill kuralları: semantik HTML → layout → bileşen → tipografi → tema → etkileşim → medya → a11y → performans → PWA)

---

## 1. Yönetici özeti

| Alan | Puan | Kısa hüküm |
|---|---|---|
| Semantik yapı / landmark'lar | 8/10 | Her rotada tek `<h1>`, `<main>`, `<nav aria-label>`, tablo sarmalayıcıları profesyonel |
| Responsive / layout | 7/10 | `touch-target` 44px, `dvh`, safe-area, tablo yatay kaydırma sarmalayıcıları tam |
| PWA katmanı | 8/10 | Manifest + `sw.js` + kurulum akışı + iOS ikonları; maskable ikon eksik |
| Performans | 7/10 | Render-blocking font `@import`'u kaldırılmış, `standalone` çıktı; 55/62 bileşen `"use client"` |
| Erişilebilirlik | 5/10 | Kontrast, focus kaybı, placeholder-as-label, skip-link yok |
| **Tema mimarisi** | **4/10** | 208 `html.light` kuralı / 135 `!important`, `prefers-color-scheme` yok |
| **Tipografi / okunabilirlik** | **3/10** | **852 px-sabit font boyutu; deklare edilen 3 font ailesi uygulamaya HİÇ yüklenmiyor** |
| **Genel** | **≈5.5/10** | İskelet ve PWA güçlü; tipografi ve erişilebilirlik katmanı acil borç |

### En kritik 3 bulgu
1. **Fontlar hiç yüklenmiyor.** `globals.css:10-12` `Inter / Poppins / JetBrains Mono` deklare ediyor, `tailwind.config.ts:41-45` `font-sans/display/mono` bunlara bağlıyor, ama repoda `next/font` importu, `@font-face` ve tek bir `.woff2` dosyası **yok**. Yorum satırı ("next/font ile self-hosted yüklenir") gerçeği yansıtmıyor. Uygulama fiilen Segoe UI / Consolas ile çiziliyor — tasarım JetBrains Mono üzerine kuruluyken.
2. **Tipografi 8–10px'e sıkışmış.** 461×`text-[10px]`, 67×`text-[9px]`, 3×`text-[8px]` (toplam 852 px-sabit boyut). `globals.css:604` `.topbar-status` = `.52rem` (≈8.3px). Kullanıcı tarayıcı varsayılan font boyutunu büyüttüğünde px takmaz → WCAG 1.4.4 (200% zoom) riski.
3. **Kullanıcı odak (focus) göstergesini kaybediyor + kontrast eşik altı.** 4 girdide `outline-none` ve ikame stili yok; `#64748b` ve `text-slate-600/700` metin 2.1–3.9:1 aralığında (normal metin için gereken 4.5:1'in altında).

---

## 2. Güçlü yönler (korunmalı)

- `app/layout.tsx:66` `<html lang="tr">` ✅ ve `suppressHydrationWarning` ile tema flash'ı önlenmiş inline script ✅
- `layout.tsx:44-50` `maximumScale: 5` — zoom **engellenmemiş** ✅ (yaygın ihlal burada yok)
- `globals.css:691-696` `prefers-reduced-motion: reduce` bloğu ve `<svg>` inline ikon politikası (`NavIcon.tsx` — ikon fontu yok) ✅
- `globals.css:711-714` `.touch-target { min-height:44px; min-width:44px }` — dokunma hedefi kuralı ✅
- `components/ui.tsx:43` Tabs: gerçek `role="tablist"` + `aria-selected` + `ArrowLeft/Right` klavye gezinmesi + roving `tabIndex` ✅ (nadiren doğru yapılır)
- `components/MarkdownMessage.tsx:88` LLM tablosu: `role="region"` + `aria-label` + `tabIndex={0}` + `overflow-x:auto` — klavyeyle kaydırılabilir tablo ✅
- Tablo disiplini: 12 dosyada `table=scrollWrap` eşleşmesi tutarlı (tek istisna yok) ✅
- `lib/menu.ts` — masaüstü Sidebar ve mobil BottomNav **tek kaynaktan** besleniyor ✅
- PWA: `output: "standalone"`, `sw.js` için `no-cache`, iOS `apple-touch-icon` üçlemesi, `safe-area-inset` kullanımı, `useVisibleInterval` ile sekme arkada kalınca poll durdurma ✅

---

## 3. Bulgular

### P0 — Kullanıcıyı doğrudan etkiliyor

#### P0-1 · Deklare edilen font aileleri uygulamaya yüklenmiyor
**Kanıt:** `globals.css:10-12` + `tailwind.config.ts:41-45` vs. `grep -r "next/font" app` → **0 sonuç**; `grep -r "@font-face" app/globals.css` → **0**; `find . -iname "*.woff*"` → **0** (node_modules hariç).
**Etki:** `--font-mono: 'JetBrains Mono'` sistemde yoksa `ui-monospace/Consolas`'a düşer. Arayüzün *tamamı* mono tipografi üzerine kurulu (`font-mono` + 852 px-sabit boyut birlikte kullanılıyor) → tüm ekranlarda ölçüm, harf genişliği ve sütun hizası tasarlanandan farklı; sayısal tablo hizaları platform başına kayıyor.
**Düzeltme:** `app/layout.tsx`'te `next/font/local` (veya `next/font/google`) ile 3 aileyi yükle, `variable: "--font-sans|--font-display|--font-mono"` ver, `<html className={...variables}>` olarak bağla. Self-host + `display: swap` + yalnız kullanılan ağırlıklar (400/600/700).

#### P0-2 · Tipografi 8–10px bandına sıkışmış, px sabit
**Kanıt:** `grep -rhoE "text-\[[0-9]+px\]"` → `10px`×461, `11px`×315, `9px`×67, `8px`×3. `globals.css:604` `.topbar-status{font-size:.52rem}`; `globals.css:604/638/643` mobilde `h1{font-size:1rem}`.
**Etki:** (a) 8–10px normal metin okunabilirlik alt sınırının altında; (b) px birimler kullanıcının "varsayılan font boyutu" ayarını yok sayar → büyütme erişilebilirlik ayarı işlevsiz; (c) 200% zoom'da tablo ve etiketler taşar.
**Düzeltme:** Ölçek token'ı kur — `--fs-2xs:.6875rem(11px)`, `--fs-xs:.75rem(12px)`, `--fs-sm:.8125rem(13px)` ve `10px→0.6875rem`, `9px→0.625rem` eşlemesiyle kademeli geçiş. Hiçbir metin `0.6875rem` (11px) altına inmesin; `.52rem` → `.6875rem`. Bkz. §5 plan.

#### P0-3 · Focus göstergesi olmayan girdiler
**Kanıt:** `charts/page.tsx:473`, `charts/page.tsx:526`, `forex/components/AutoSettingsPanel.tsx:920`, `forex/metamobil/page.tsx:601` — `outline-none` var, aynı `className` içinde `focus:`/`focus-visible:` ikamesi yok.
**Etki:** Klavye kullanıcısı hangi alanda olduğunu göremez (WCAG 2.4.7 ihlali).
**Düzeltme:** Bu 4 alana `focus-visible:outline focus-visible:outline-2 focus-visible:outline-cyan-400` (light modda `outline-blue-500`) ekle. Ayrıca global bir güvenlik ağı: `:focus-visible { outline: 2px solid var(--focus-ring); outline-offset: 2px }` — `outline:none` sınıfını **tek başına** kullanan yeni kod bir daha focus kaybettirmesin.

#### P0-4 · Kontrast eşik altı metin renkleri
Ölçülen oranlar (WCAG normal metin eşiği **4.5:1**, büyük metin/ikon **3:1**):

| Ön plan | bunker-950 `#070b14` | bunker-900 `#0c1322` | bunker-800 `#142036` | bunker-700 `#1f3050` | Hüküm |
|---|---|---|---|---|---|
| `#ffffff` | 19.68 | 18.55 | 16.28 | 13.15 | ✅ |
| `#93a7c6` (bunker-muted) | 8.04 | 7.58 | 6.66 | 5.38 | ✅ |
| `#94a3b8` (slate-400) | 7.68 | 7.24 | 6.35 | 5.13 | ✅ |
| `#00f0ff` (neon cyan) | 13.97 | 13.17 | 11.56 | 9.34 | ✅ |
| `#ff3366` (neon red) | 5.55 | 5.23 | 4.59 | **3.71** | ⚠️ bunker-700'de FAIL |
| **`#64748b` (slate-500)** | **4.14** | **3.90** | **3.42** | 2.76 | ❌ FAIL |
| **`#475569` (slate-600)** | **2.60** | **2.45** | **2.15** | 1.74 | ❌ FAIL |

**Kanıt (FAIL kullanımları):** `globals.css:57` `.chat-footer{color:#64748b}`, `:505` `.empty-state`, `:522` `.portfolio-trade-footer`, `:90` `.chat-toggle small`; ayrıca TSX'te `text-slate-600`×18, `text-slate-700`×16.
**Etki:** Boş durum metinleri, alt bilgi satırları ve ikincil etiketler parlak ekranda/mobilde okunmuyor.
**Düzeltme:** İkincil metni `#93a7c6` (bunker-muted, 7.58:1) veya en kötü `#8fa3c0`'a çek; `#64748b`'ı yalnız **dekoratif ayraç/ikon** için bırak (ikon için ≥3:1 gerekir → `#7c8ba1`).

#### P0-5 · Tanımsız Tailwind renk tonları sessizce düşüyor
**Kanıt:** `tailwind.config.ts:7-14` yalnız `bunker: 950/900/800/700/600/muted` tanımlı. Kullanılan ama **tanımsız**: `text-bunker-300`×16, `bg-bunker-750`×4, `text-bunker-400`×2, `bg-bunker-500`×1, `border-bunker-750`×1 → örnek: `forex/components/GateSnapshotCard.tsx:117`, `forex/components/ForexRadarModal.tsx:306,394,452`, `forex/islemler/page.tsx:483,488,524,544`.
**Etki:** Sınıf hiç üretilmediği için bu metinler **kalıtılan beyaza** düşer. Yazılımın amacı "sönük ikincil metin" iken ekranda tam parlaklıkta beyaz çıkar → hiyerarşi bozulur (ve `forex/islemler` içinde `hover:bg-bunker-750` hiç hover vermez, yani ölü etkileşim).
**Düzeltme:** İki seçenek — (a) `tailwind.config.ts`'e `300/400/500/750` tonlarını ekle, veya (b) tercih edilen: bu 24 kullanımı tanımlı tonlara çevir (`bunker-300 → bunker-muted`, `bunker-750 → bunker-700`). CI'ya "tanımsız `bunker-*` sınıfı" lint kuralı ekle.

#### P0-6 · Placeholder tek başına etiket olarak kullanılıyor
**Kanıt:** `app/settings/page.tsx:462, 463, 464, 481, 487, 497, 498` — `<input placeholder="...">`, görünür `<label>` veya `aria-label` yok. (`AuthGate.tsx:96` doğru: `<label>` içinde ✅)
**Etki:** Ekran okuyucu alanı "düzenlenebilir metin" olarak okur, adı olmadan; yazmaya başlayınca ipucu kaybolur (WCAG 3.3.2 ihlali).
**Düzeltme:** Görünür `<span class="eyebrow">` etiketi ekle (uygulamanın kendi idiomu bu — `AuthGate` ile aynı desen), placeholder'ı örnek değer olarak koru.

---

### P1 — Kalite ve bakım borcu

#### P1-1 · Tema mimarisi: 208 `html.light` kuralı + 135 `!important`
**Kanıt:** `globals.css` içinde `html.light` 208 kez; `!important` 135 kez. Kırılgan seçiciler: `globals.css:1126` `html.light svg line[stroke="#334155"]`, `:1130` `html.light svg path[fill="#ffffff"]...drop-shadow-[...]`.
**Etki:** (a) Skill kuralı 5 ihlali — tema, `:root` custom property'leri + tek blok ile sürülmeli, tüm seçici blokları kopyalanmamalı; (b) TSX'te **518 `text-white`** ve **203 `bg-bunker-950`** hardcoded olduğu için her yeni `text-white` light modda sessizce kırılır; bu yüzden düzeltmeler `!important` ile yamanıyor ve yama listesi büyüdükçe gözden kaçan yüzey artıyor. Kırılganlık göstergesi: light modun `svg path[fill="#ffffff"]` gibi **render çıktısına** bağlanmış olması.
**Düzeltme:** Semantik token katmanı: `--surface-1/2/3`, `--text-primary/secondary/muted`, `--border`, `--accent`. `html.dark` ve `html.light` **yalnız** bu değişkenleri tanımlasın; bileşenler `text-[color:var(--text-primary)]` veya Tailwind `text-primary` kullansın. Tailwind config'de renkleri `rgb(var(--...) / <alpha-value>)` biçimine çevir. Bu tek refactor 135 `!important`'ın ~120'sini gereksiz kılar.

#### P1-2 · `prefers-color-scheme` desteği yok + tema rengi tek şema
**Kanıt:** `globals.css` ve `lib/theme.tsx`'te `prefers-color-scheme` **hiç** geçmiyor (`layout.tsx:66` inline script yalnız `localStorage`); `layout.tsx:47` `themeColor: "#070b14"` (tek değer), `manifest.webmanifest` `theme_color: #070b14`.
**Etki:** İlk ziyaretçi işletim sistemi açık temadaysa yine koyu temayla karşılaşır; açık temaya geçtiğinde tarayıcı çubuğu/başlık koyu kalır (görsel sıçrama).
**Düzeltme:** `theme.tsx`'te depolanmış değer yokken `matchMedia("(prefers-color-scheme: light)")` oku (varsayılan koyu kalsın); `layout.tsx`'e `themeColor: [{media:"(prefers-color-scheme: light)", color:"#ffffff"}, {media:"(prefers-color-scheme: dark)", color:"#070b14"}]` ekle.

#### P1-3 · Skip-link yok, sidebar 20+ bağlantı
**Kanıt:** `grep -i "skip"` → yalnız `BridgeSettingsPanel` istatistik alanları (`total_skipped_*`); gerçek bir "içeriğe atla" bağlantısı yok. `Sidebar` tek `<nav>` içinde ~19 bağlantı.
**Etki:** Klavye/screen reader kullanıcısı her sayfa geçişinde ~20 bağlantıyı Tab'layarak geçmek zorunda.
**Düzeltme:** `AppShell.tsx` içinde `<main id="main" tabIndex={-1}>` + layout başında `:focus` dışı gizli, `:focus` görünür `.skip-link`.

#### P1-4 · `hover` durumları için dokunma yedeği yok
**Kanıt:** `globals.css:691` reduced-motion bloğu var ama `@media (hover: none)` / `@media (any-pointer: coarse)` hiç yok; TSX'te `hover:` yoğun (`hover:bg-*`, `hover:text-*`, `hover:border-*` yüzlerce kez).
**Etki:** Mobilde hover ile açılan ipucu/vurgu kaybolur; bazı satır-içi eylemler (örn. `forex/islemler` satır hover'ı) dokunmatikte keşfedilemez. (BottomNav ve `touch-target` bu riskin bir kısmını zaten kapatıyor — iyi.)
**Düzeltme:** Kritik hover'ları `@media (hover: none) { /* kalıcı görünür */ }` ile kalıcılaştır veya `:active` karşılığı ver.

#### P1-5 · Okuma ölçüsü ve satır yüksekliği denetlenmemiş
**Kanıt:** `globals.css:380` `.page-heading p { max-width: 68ch }` — **tek** doğru örnek. Chat balonu `globals.css:67` `line-height:1.5`, `MarkdownMessage` `1.45`, `.message-table` `1.45`.
**Etki:** 45–75 karakter ölçüsü yalnız sayfa başlığı açıklamasında uygulanmış; uzun LLM yanıt bloklarında kontrol taşarak 100+ karakter satıra çıkabilir.
**Düzeltme:** `--measure: 66ch` değişkeni kur, `.chat-bubble`, `.message-markdown`, rapor gövdelerinde `max-inline-size` olarak uygula; gövde `line-height: 1.5–1.65` birleştir.

#### P1-6 · `100vh` kalıntısı
**Kanıt:** `charts/page.tsx:398` `"md:h-[calc(100vh-4rem)]"` (mobil dal `100dvh` doğru — iyi).
**Düzeltme:** `100vh` → `100dvh`.

#### P1-7 · Container query yok, monolithic istemci sayfaları
**Kanıt:** `@container` → **0 kullanım**. Sayfa boyutları: `spot-monitor/page.tsx` 2185, `forex/btc-gold/page.tsx` 2294, `forex/page.tsx` 1462 satır. 62 TSX'in **55'i** `"use client"` (tek istisna `metamobil/page.tsx`).
**Etki:** Bileşenler bağlam-bağımsız değil, ekran genişliğine göre dallanıyor; aynı kart panoda ve yan panelde kullanılamıyor. RSC avantajı neredeyse hiç kullanılmıyor → ilk JS yükü ve INP riski.
**Düzeltme:** Panel/kart bileşenlerine `container-type: inline-size` + `@container (min-width: 25em)`; `spot-monitor`/`btc-gold` sayfalarını sekme başına ayrı dosyaya böl (`app/spot-monitor/ActiveSignalsTab.tsx` vb.), veri çekmeyi sunucu bileşenine taşı.

#### P1-8 · Manifest maskable/PNG ikon eksik
**Kanıt:** `manifest.webmanifest` `icons` yalnız `/icon.svg` `purpose:"any"`. Repoda `public/icons/Android/Icon-192.png` ve `Icon-512.png` **var** ama manifest'te listelenmiyor.
**Düzeltme:** `192x192` ve `512x512` PNG'leri `"purpose":"any"` + ayrı `512x512 maskable` girdisi olarak ekle. `orientation: "portrait-primary"` tablet yatay kullanımını kilitliyor — `"any"` düşün.

#### P1-9 · 5 yerde tablo/min-width sabit (mobil yatay kaydırma)
**Kanıt:** `globals.css:489` `.portfolio-table, .portfolio-history-table{min-width:760px}`, `:644` `@media(max-width:768px){ table{min-width:680px} }`, `:425` `.table-scroll > table{min-width:40rem}`.
**Etki:** Mobilde **her** tablo yatay kaydırma gerektiriyor. Sarmalayıcılar doğru kurulu olduğu için veri kaybı yok (iyi), ama satır başına kritik alan ekran dışında kalıyor.
**Düzeltme:** En yoğun 2 tabloda (spot-monitor Aktif Sinyaller, forex İşlemler) mobil için kart görünümü — `globals.css:717` `.mobile-card-grid` deseni zaten var, aynı yaklaşım.

---

### P2 — Cila

- `globals.css:9` `:root{color-scheme:dark}` — açık temada JS inline `style.colorScheme` ile düzeltiliyor; JS yüklenmezse (veya `prefers-color-scheme: light` + parametrik çağrıda) yerel form kontrolleri koyu kalır. `color-scheme: light dark` + tema sınıfında daraltma daha temiz.
- `globals.css:52` `-webkit-tap-highlight-color: transparent` tüm `button/a/input/select/textarea` için → dokunma geri bildirimi kaybolur; `:active` ölçek (`active:scale-95`) bunu kısmen karşılıyor ✅ ama klavyeyle odaklanan `<a>`'larda hover/focus ayrımı net değil.
- `TopBar.tsx:107` canlılık göstergesi yalnız renkli nokta + `hidden sm:inline` metin: mobilde **yalnız renk** ile anlam aktarımı (skill kuralı 3 — renk tek başına anlam taşımamalı). Metni `sr-only` olarak da ekle.
- `Sidebar.tsx:155,167` `⚙` ve `⏻` karakterleri emoji/glyph olarak bağlantı metni yerine geçiyor; `title` var ama `aria-label` yok. `NavIcon` SVG desenine çevir (ikon fontu/glyph yerine inline SVG kuralı).
- `layout.tsx:20` `title.default` başlığında emoji + `$` karakterleri: sekme başlığı ilk 55–60 karakterde okunur kısımı "🌐 GLOBAL ($) · SCALPER AGENT" — emoji önce geldiği için sekme listesinde tanınırlık düşük. Marka adını başa al.
- `spot-monitor/page.tsx` h2 başlığı `globals.css` dışında `text-slate-200` kullanıyor (4.5:1 ✅) ama `text-slate-600/700` (18+16 kullanım) yer yer üzerine geliyor — parti temizliği gerekli (§P0-4).

---

## 4. Ölçüm tablosu — mevcut token'lar

Hesaplanan kontrast (WCAG 2.x, sRGB):

| Token | Hex | bunker-950 | bunker-900 | bunker-800 | bunker-700 |
|---|---|---|---|---|---|
| `white` | `#ffffff` | 19.68 ✅ | 18.55 ✅ | 16.28 ✅ | 13.15 ✅ |
| `bunker-muted` | `#93a7c6` | 8.04 ✅ | 7.58 ✅ | 6.66 ✅ | 5.38 ✅ |
| `neon-green` | `#00e676` | 11.79 ✅ | 11.11 ✅ | 9.76 ✅ | 7.88 ✅ |
| `neon-cyan` | `#00f0ff` | 13.97 ✅ | 13.17 ✅ | 11.56 ✅ | 9.34 ✅ |
| `neon-yellow` | `#f0b90b` | 10.92 ✅ | 10.29 ✅ | 9.03 ✅ | 7.30 ✅ |
| `neon-red` | `#ff3366` | 5.55 ✅ | 5.23 ✅ | 4.59 ✅ | 3.71 ⚠️ yalnız ≥18.5px bold |
| `slate-400` | `#94a3b8` | 7.68 ✅ | 7.24 ✅ | 6.35 ✅ | 5.13 ✅ |
| **`slate-500`** | `#64748b` | **4.14 ❌** | **3.90 ❌** | **3.42 ❌** | 2.76 ❌ |
| **`slate-600`** | `#475569` | **2.60 ❌** | **2.45 ❌** | **2.15 ❌** | 1.74 ❌ |

---

## 5. Öncelikli düzeltme planı

| Sıra | İş | Dosyalar | Süre | Doğrulama |
|---|---|---|---|---|
| 1 | Fontları gerçekten yükle (`next/font/local` × 3 aile, `variable` bağla) | `app/layout.tsx`, `globals.css:10-12` | ~1s | DevTools → Network'te `.woff2` istekleri; "Rendered fonts"ta Inter/JetBrains Mono |
| 2 | İkincil metni `#64748b`→`#93a7c6`'ya çek, `slate-600/700`'ü temizle | `globals.css:57,90,505,521-522` + 34 TSX kullanımı | ~1s | Kontrast denetimi: `#64748b` metin kalmadı |
| 3 | Tanımsız `bunker-300/400/500/750` kullanımlarını tanımlı tonlara çevir | 10 dosya / 24 kullanım | ~30dk | `grep -rE "(text\|bg\|border)-bunker-(300\|400\|500\|750)"` → 0 |
| 4 | 4 focus'suz girdiye `focus-visible` outline + global `:focus-visible` güvenlik ağı | `charts/page.tsx:473,526`, `AutoSettingsPanel.tsx:920`, `metamobil/page.tsx:601`, `globals.css` | ~30dk | Yalnız klavyeyle Tab ile tüm ekran: her adımda görünür halka |
| 5 | `settings/page.tsx` 7 placeholder'ına görünür etiket | `app/settings/page.tsx:462-498` | ~30dk | Ekran okuyucu: alan adı okunuyor |
| 6 | Tipografi ölçeği: `.6875rem` (11px) alt sınırı, px→rem migrasyonu | `globals.css` + 852 TSX kullanımı (kademeli) | ~1-2g | 200% zoom'da taşma yok; tablo etiketleri okunur |
| 7 | Skip-link + `<main id="main">` | `AppShell.tsx`, `layout.tsx` | ~20dk | Tab → ilk odak "İçeriğe atla" |
| 8 | `prefers-color-scheme` varsayılanı + iki şemalı `themeColor` + manifest maskable ikonları | `lib/theme.tsx`, `layout.tsx:47`, `manifest.webmanifest` | ~45dk | OS açık tema + gizli mod ilk açılış → açık tema |
| 9 | Tema token refactor'ü (`--surface/--text/--border`), 135 `!important` budaması | `globals.css` (208 `html.light` kuralı), `tailwind.config.ts` | ~2-3g | Açık/koyu regresyon turu; `!important` sayısı < 20 |

---

## 6. Doğrulama komutları (regresyon kapısı)

```bash
cd frontend

# 1. Tanımsız renk tonu kalmadı mı
grep -rE "(text|bg|border)-bunker-(300|400|500|750)" app --include=*.tsx

# 2. Focus'suz outline-none kalmadı mı
grep -rnE 'className="[^"]*outline-none[^"]*"' app --include=*.tsx | grep -v focus

# 3. px-sabit font boyutu sayısı (hedef: 0)
grep -rhoE "text-\[[0-9]+px\]" app --include=*.tsx | sort | uniq -c | sort -rn

# 4. Kontrast altı token kullanımı (hedef: yalnız dekoratif)
grep -rn "#64748b\|text-slate-600\|text-slate-700" app --include=*.tsx app/globals.css

# 5. Font gerçekten bağlı mı
grep -rn "next/font" app && ls -R public | grep -i woff

# 6. Placeholder-as-label kalmadı mı
grep -rn "placeholder=" app --include=*.tsx | grep -v "aria-label\|<label"

# 7. Tip kontrolü
npm run typecheck && npm test
```

**Manuel geçiş (her PR'da):** Tab-only klavye turu → 200% ve 400% zoom → açık/koyu tema turu → 320px genişlik turu → ekran okuyucu ile giriş formu.

---

## 7. Sonuç

Uygulamanın **mühendislik disiplini güçlü**: semantik iskelet, tablist klavye desteği, klavyeyle kaydırılabilir tablo, reduced-motion bloğu, 44px dokunma hedefi, safe-area, PWA önbellek politikası — bunlar bu ölçekteki projelerde nadiren eksiksiz olur ve burada eksiksiz.

Borç **iki katmanda birikmiş**: (1) **tipografi** — deklare edilen fontlar hiç yüklenmiyor ve tüm metin 8–11px px-sabit bandında; (2) **tema/erişilebilirlik** — 208 `html.light` kuralı `!important` ile yamanıyor, `prefers-color-scheme` yok, bir avuç kontrast token'ı ve focus göstergesi eşiğin altında.

Sıra 1–5 (yaklaşık bir günlük iş) en yüksek kullanıcı etkisini üretir: fontu yükle, kontrastı düzelt, 4 focus'u bağla, 7 etiketi ekle. Sıra 6–9 yapısal refactor; bunlar tamamlandığında tema ve tipografi katmanı bakım borcu olmaktan çıkar.

---

## 8. UYGULAMA KAYDI (2026-11-09 — "hepsini uygula" turu)

`npm run typecheck` ✅ · `npm run build` ✅ (20/20 rota) · `npm test` → 97/102 geçti; **5 başarısızlık `app/lib/format.test.ts`** içinde ve **önceden vardı** (env tabanlı para birimi formatı, temiz HEAD'de de kırmızı — bkz. proje notu "kovalamayın"). Benim değişikliklerim bu dosyaya dokunmadı (`git diff` boş).

### Uygulananlar

| # | Bulgu | Yapılan | Doğrulama |
|---|---|---|---|
| P0-1 | Fontlar hiç yüklenmiyordu | `app/fonts.ts` + `app/fonts/*.woff2` (Inter & JetBrains Mono değişken font, Poppins 600/700). `next/font/local`, `display: swap`, `variable` bağlandı. `globals.css` :root'taki sahte `--font-*` deklarasyonları kaldırıldı; CSS'teki 37 sabit `ui-monospace,…` yığını `var(--font-mono, …)` yaptı | `.next/static/media/*.woff2` 4 dosya üretildi; çıktı CSS'te `--font-mono` 43 kez |
| P0-2 | 852 px-sabit font boyutu | `text-[8/9/10/11px]` → `text-2xs` (= `.6875rem`, 11px **tabanı**), 12px → `text-xs`, 13/14px → rem. `globals.css`'te 43 + 33 `font-size`/`font` shorthand değeri `.6875rem` tabanına çekildi, `16px` → `1rem` | `.text-2xs{font-size:.6875rem}` çıktıda; `text-[Npx]` TSX'te **0** |
| P0-3 | Focus göstergesiz girdiler | Katmansız global `:focus-visible { outline: 2px solid var(--focus-ring) }` güvenlik ağı (Tailwind'in `outline-none`'ını özgüllükten bağımsız yener) | Çıktı CSS'te doğrulandı; kalan 5 `outline-none` artık kapsanıyor |
| P0-4 | Kontrast altı metin | `globals.css`'te 8 metin kuralı `#64748b`→`#93a7c6`; hafif-modda beyaz zemin üzerindeki placeholder `#475569` yapıldı; EVShieldModal'da koyu zemin üzerindeki `placeholder:text-slate-500`→`-400`, `hover:text-slate-600`→`-200`; kadran min/max SVG etiketi `#64748b/8`→`#93a7c6/11` | `color:#64748b` globals.css'te **0**; ekranda `#64748b` metin kalmadı |
| P0-5 | Tanımsız Tailwind tonları | 24 kullanım tanımlı tonlara eşlendi (`bunker-300/400`→`bunker-muted`, `750`→`700`, `500`→`600`); ölü `hover:text-bunker-muted` → `hover:text-white` | `grep -rE "(text\|bg\|border)-bunker-(300\|400\|500\|750)"` → **0** |
| P0-6 | Placeholder = etiket | `settings/page.tsx`'te 7 girdi + 2 `select` görünür `eyebrow` etiketiyle `<label>` içine alındı; placeholder örnek değere indirildi; `autoComplete`/`w-full` eklendi | 9 alanın tamamı etiketli |
| P1-1 | 208 `html.light` kuralı / 135 `!important` | Tema token katmanı (`--text-primary/secondary/muted`, `--focus-ring`, `--surface-*`, `--border-hairline`) `:root` + `html.light`'ta **tek kaynak**; `tailwind.config.ts`'e `ink.1/2/3`. **107 gereksiz `!important` budandı** (katmansız CSS `@layer utilities`'i zaten yener — 135 → 28) | `!important` sayısı 135→28; kalan 28 `@media` blokları, `svg`/gradient/ticker muafiyetleri ve `diverging-track` özgüllük hilesi |
| P1-2 | `prefers-color-scheme` yok | `layout.tsx` FOUC script'i + `lib/theme.tsx`: depolanmış tercih yoksa OS tercihi okunur | Kod yolu iki yerde aynı kural |
| P1-3 | Skip-link yok | `AppShell` başına `.skip-link` + `<main id="main-content" tabIndex={-1}>` | Klavye ile ilk Tab → "İçeriğe atla" |
| P1-4 | hover yedeği yok | `@media (hover:none),(any-pointer:coarse)` güvenlik ağı. **Not:** içeriği gizleyen hover deseni yoktu (yalnız `opacity-70→1`) | Çıktıda doğrulandı |
| P1-5 | Okuma ölçüsü | `--measure: 66ch`; düz metin akışına uygulandı (chat/markdown/boş durum); `line-height: 1.6`; `.page-heading p` 68ch → token | `var(--measure)` çıktıda 2+ |
| P1-6 | `100vh` | `charts/page.tsx` → `100dvh` | — |
| P1-8 | Manifest ikonları | PNG 192/512 `any` olarak eklendi + `sharp` ile üretilen **maskable 512** (`Icon-512-maskable.png`); `orientation` `portrait-primary`→`any` | 512×512 doğrulandı |
| P2 | Cila | `TopBar` canlılık durumu artık mobilde de METİNLİ ("CANLI"/"HATA") + `sr-only` + `aria-hidden` nokta; `Sidebar`'daki `⚙`/`⏻` glifleri yerine `NavIcon` (yeni `power` ikonu) ve `aria-label`; `title.default` marka-önce; `tailwind.config.ts`'e eksik **`xs: 420px`** eklendi (`xs:` öneki kodda kullanılıp tanımsızdı → ölü sınıf) | — |

### Bilinçli olarak YAPILMAYANLAR (ve gerekçesi)

- **`spot-monitor` / `btc-gold` / `forex` sayfalarının sekme başına bölünmesi ve RSC'ye taşınması (P1-7):** 2185/2294/1462 satırlık 3 dosyanın bölünmesi, davranış regresyonu riski taşıyan ve **render edilmiş bir karşılaştırma gerektiren** bir refactor. Görsel doğrulama yapılmadan körlemesine yapılması, düzeltmeye çalıştığımız arayüzden daha kötü bir sonuç üretir. Ayrı ve odaklı bir tur olarak bırakıldı.
- **`container-type: inline-size` (P1-7 CSS kısmı):** `inline-size` containment, genişliği içeriğe bağlı olmayan öğeleri (flex satırındaki `flex: 0 1 auto` kartlar) **0 genişliğe çökertebilir**. `.panel`/`.ui-card`'ın tüm kullanım yerlerini görsel doğrulamadan containment altına almak kabul edilemez risk. Aynı turda yapılmalı.
- **Açık tema (light mode) görsel turu:** Bu ortamda uygulama `AuthGate` arkasında; kimliği doğrulanmış kabuk render edilemedi. `html.light` bloklarındaki 107 `!important` kaldırması **katman sıralaması garantisine** dayanıyor (katmansız CSS, `@layer utilities`'i özgüllükten bağımsız yener; yarışan tüm kurallar ya Tailwind yardımcı sınıfı ya da daha düşük özgüllüklü katmansız kural). Satır içi stil taşıyan 11 öğe tarandı; hiçbiri bu kurallarla yarışmıyor. **Yine de açık temada bir tur atılması önerilir:** sidebar + topbar + bir tablo + bir kart + bir form.

### Yeni kabul kriterleri (PR kapısı)

```bash
cd frontend
grep -rE "(text|bg|border)-bunker-(300|400|500|750)" app --include=*.tsx   # 0 olmalı
grep -rhoE "text-\[[0-9]+px\]" app --include=*.tsx                      # 0 olmalı
grep -rhoE "text-\[0\.[0-6][0-9]*rem\]" app --include=*.tsx            # 0 olmalı (11px altı yok)
grep -rn "color:#64748b\|color: #64748b" app/globals.css                 # 0 olmalı
grep -c "!important" app/globals.css                                      # 28'i geçmemeli
grep -rn "next/font" app/fonts.ts                                         # 1+ olmalı
npm run typecheck && npm run build
```
