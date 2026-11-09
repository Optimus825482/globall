// Tipografi yüklemesi — TEK kaynak.
//
// 2026-11-09 (2. tur) — TÜRKÇE GLİF HATASI DÜZELTİLDİ
// ---------------------------------------------------
// Önceki turda fontlar Google Fonts'tan YALNIZ `latin` alt kümesiyle
// indirilmişti. Türkçeye özgü harfler (`ğ Ğ İ ş Ş`) **latin-ext**, `₺` (U+20BA)
// ise **para birimleri** bloğundadır — yani dosyalarda YOKTU. Ölçüm:
//
//   Inter-Variable.woff2          glif=230  EKSIK: ğ Ğ İ ş Ş ₺ →
//   JetBrainsMono-Variable.woff2  glif=229  EKSIK: ğ Ğ İ ş Ş ₺ →
//
// Sonuç: o harfler yedek fontla (Arial) çiziliyordu; "bazı Türkçe karakterler
// tanınmıyor" şikâyetinin kök nedeni bu. `₺` uygulamada 58 yerde geçiyor.
//
// ÇÖZÜM: (1) Daha bilindik ve gözü yormayan bir çift seçildi —
// **Roboto** (arayüz) + **Noto Sans Mono** (sayı/tablo). (2) Dosyalar artık
// kaynak koddan ÖLÇÜLEN karakter kümesiyle üretiliyor (script: latin +
// latin-ext-A + para birimleri + genel noktalama; `tnum`/kerning korunur) ve
// her üretimde "kullanılan karakterlerin tamamı var mı" doğrulanıyor.
//
// Oklar (→ ▲ ✓ ✕) ve emoji bu fontların hiçbirinde yoktur — tarayıcı bunları
// işletim sisteminin sembol/emoji fontundan alır; `fallback` zincirine açıkça
// yazıldı ki hangi fontun devreye girdiği öngörülebilir olsun.
//
// `variable` adları `tailwind.config.ts` → `fontFamily` ile birebir eşleşir;
// `app/layout.tsx` bu sınıfları <html> üzerine koyar, tüm ağaç miras alır.

import localFont from "next/font/local";

// NOT 1: `fallback` dizileri DÜZ yazılmak zorunda — next/font/local bu seçeneği
// derleme sırasında statik olarak okur, spread (`...X`) kabul etmez
// ("Unexpected spread" hatası verir).
//
// NOT 2 (ÖLÇÜLDÜ, kritik): next/font bu adları üretilen CSS'e **TIRNAKSIZ**
// yazar. Tırnaksız bir aile adı, geçerli CSS tanımlayıcıları dizisi olmak
// zorundadır. `Noto Sans Symbols 2` bu kuralı İHLAL EDER (son parça rakamla
// başlıyor) → tarayıcı `font-family` bildiriminin TAMAMINI geçersiz sayar ve
// metin varsayılan olana (Times New Roman) düşer. Bir turda tam olarak bu oldu.
// Bu yüzden listede yalnız GEÇERLİ tanımlayıcılardan oluşan adlar bulunur;
// doğrulaması `validateFallback()` ile derleme öncesi yapılır.
export const fontSans = localFont({
  src: "./fonts/Roboto-Variable.woff2",
  weight: "400 700",
  style: "normal",
  display: "swap",
  variable: "--font-sans",
  fallback: [
    "-apple-system",
    "BlinkMacSystemFont",
    "Segoe UI",
    "Roboto",
    "Helvetica Neue",
    "Arial",
    // Okları/geometrik şekilleri karşılayan sistem sembol zinciri.
    "Segoe UI Symbol",
    "Noto Sans Symbols",
    "Apple Color Emoji",
    "Segoe UI Emoji",
    "Noto Color Emoji",
    "sans-serif",
  ],
});

export const fontMono = localFont({
  src: "./fonts/NotoSansMono-Variable.woff2",
  weight: "400 700",
  style: "normal",
  display: "swap",
  variable: "--font-mono",
  fallback: [
    "ui-monospace",
    "Cascadia Mono",
    "Segoe UI Mono",
    "Consolas",
    "SF Mono",
    "Menlo",
    "DejaVu Sans Mono",
    "Liberation Mono",
    // Okları/geometrik şekilleri karşılayan sistem sembol zinciri.
    "Segoe UI Symbol",
    "Noto Sans Symbols",
    "Apple Color Emoji",
    "Segoe UI Emoji",
    "Noto Color Emoji",
    "monospace",
  ],
});

/** <html> üzerine konacak sınıf listesi. `--font-display` ayrı bir aile
 *  gerektirmiyor: arayüzün tamamı Roboto + Noto Sans Mono'dur. */
export const fontVariables = `${fontSans.variable} ${fontMono.variable}`;
