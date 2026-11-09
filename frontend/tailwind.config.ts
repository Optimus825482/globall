import type { Config } from "tailwindcss";

// 2026-11-09 ARAYÜZ DENETİMİ DÜZELTMELERİ
// ---------------------------------------------------------------------------
// 1) `fontSize["2xs"]` — Tipografi TABANI. Denetimden önce arayüzde 852 adet
//    px ile sabitlenmiş metin boyutu vardı (`text-[10px]`×461, `text-[9px]`×67,
//    `text-[8px]`×3). Sorun iki katmanlıydı: (a) px birimler kullanıcının
//    "varsayılan yazı tipi boyutu" tarayıcı ayarını yok sayar → WCAG 1.4.4
//    (200% zoom) riski; (b) 8–11px bandı okunabilirlik alt sınırının altında.
//    Çözüm: 11px = 0.6875rem TABAN olarak tanımlandı; `text-2xs` sınıfı hem
//    göreli birime geçirir hem de tek bir yerden ayarlanabilir kılar.
//    Line-height BİLİNÇLİ olarak verilmedi: önceki davranış (kalıtılan
//    satır yüksekliği) birebir korunur, `leading-*` sınıfları yine kazanır.
// 2) `colors.ink.*` — Semantik metin token'ları. `globals.css` içindeki
//    `:root` (koyu) ve `html.light` (açık) bu değişkenleri tanımlar; bileşenler
//    tema-agnostik kalır. Ölçülen kontrast: ink-1 19.7:1, ink-2 8.0:1,
//    ink-3 7.4:1 (bunker-950 zemininde). Metin için #64748b (4.14:1) ve
//    slate-600/700 (2.15–2.60:1) KULLANILMAZ.
export default {
  darkMode: "class",
  content: ["./app/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bunker: {
          950: "#070b14",
          900: "#0c1322",
          800: "#142036",
          700: "#1f3050",
          600: "#314a77",
          muted: "#93a7c6"
        },
        neon: {
          green: "#00e676",
          greenHover: "#10b981",
          red: "#ff3366",
          yellow: "#f0b90b",
          cyan: "#00f0ff",
          blue: "#38bdf8"
        },
        global: {
          cyan: "#00f0ff",
          sky: "#38bdf8",
          gold: "#f0b90b",
          dark: "#070b14"
        },
        surface: {
          primary: "#0c1322",
          secondary: "#142036",
          danger: "#350914",
          success: "#022938"
        },
        /** Tema-duyarlı metin rolleri (`:root` / `html.light` değişkenleri). */
        ink: {
          1: "var(--text-primary)",
          2: "var(--text-secondary)",
          3: "var(--text-muted)"
        }
      },
      fontSize: {
        "2xs": "0.6875rem" // 11px — metin TABANI, altına inilmez
      },
      // 2026-11-09 denetimi: `xs:` öneki kodda KULLANILIYORDU
      // (`TopBar.tsx`: `hidden xs:inline sm:inline`) ama `xs` ekranı
      // tanımlı değildi — Tailwind bilinmeyen ekran önekini sessizce yok
      // sayar, yani o sınıf hiçbir şey yapmıyordu (ölü sınıf). Telefon
      // ile tablet arası için gerçek bir kırılma noktası tanımlandı.
      screens: {
        xs: "420px"
      },
      fontFamily: {
        sans: ["var(--font-sans)", "ui-sans-serif", "system-ui", "sans-serif"],
        display: ["var(--font-display)", "var(--font-sans)", "sans-serif"],
        mono: ["var(--font-mono)", "ui-monospace", "SFMono-Regular", "Menlo", "monospace"]
      }
    }
  },
  plugins: [],
} satisfies Config;
