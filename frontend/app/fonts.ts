// Tipografi yüklemesi — TEK kaynak.
//
// 2026-11-09 DENETİM DÜZELTMESİ: `globals.css` :root içinde `--font-sans:
// 'Inter'`, `--font-display: 'Poppins'`, `--font-mono: 'JetBrains Mono'`
// DEKLARE EDİLİYORDU ama hiçbir yerde `next/font` çağrısı, `@font-face` ya da
// .woff2 dosyası yoktu. Sonuç: arayüzün tamamı (852 px-sabit mono metin)
// fiilen sistem fontlarıyla (Segoe UI / Consolas) çiziliyordu — tasarım
// JetBrains Mono'nun harf genişliği üzerine kuruluyken. Tablo sütun hizaları
// bu yüzden platformdan platforma kayıyordu.
//
// Çözüm: dosyalar `app/fonts/` altında DEPOYA GÖMÜLÜ (self-hosted). Build
// sırasında ağ erişimi gerekmez — Docker/CI build'i Google Fonts'a bağlı
// değildir. Inter ve JetBrains Mono değişken (variable) font: tek dosya
// 400–700 ağırlık aralığının tamamını karşılar.
//
// `variable` adları `tailwind.config.ts` → `fontFamily` ile birebir eşleşir;
// `app/layout.tsx` bu üç sınıfı <html> üzerine koyar, tüm ağaç miras alır.

import localFont from "next/font/local";

export const fontSans = localFont({
  src: "./fonts/Inter-Variable.woff2",
  weight: "400 700",
  style: "normal",
  display: "swap",
  variable: "--font-sans",
  fallback: [
    "-apple-system",
    "BlinkMacSystemFont",
    "Segoe UI",
    "Roboto",
    "Helvetica",
    "Arial",
    "sans-serif",
  ],
});

export const fontDisplay = localFont({
  src: [
    { path: "./fonts/Poppins-600.woff2", weight: "600", style: "normal" },
    { path: "./fonts/Poppins-700.woff2", weight: "700", style: "normal" },
  ],
  display: "swap",
  variable: "--font-display",
  fallback: ["Inter", "-apple-system", "BlinkMacSystemFont", "sans-serif"],
});

export const fontMono = localFont({
  src: "./fonts/JetBrainsMono-Variable.woff2",
  weight: "400 700",
  style: "normal",
  display: "swap",
  variable: "--font-mono",
  fallback: [
    "ui-monospace",
    "SFMono-Regular",
    "Menlo",
    "Monaco",
    "Consolas",
    "monospace",
  ],
});

/** <html> üzerine konacak sınıf listesi. */
export const fontVariables = `${fontSans.variable} ${fontDisplay.variable} ${fontMono.variable}`;
