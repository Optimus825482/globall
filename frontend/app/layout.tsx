import type { Metadata, Viewport } from "next";
import { Suspense } from "react";
import "./globals.css";
import AuthGate from "./components/AuthGate";
import AppShell from "./components/AppShell";
import { PwaProvider } from "./lib/pwa";
import { ThemeProvider } from "./lib/theme";
import PwaInstallBanner from "./components/PwaInstallBanner";
import OfflineBanner from "./components/OfflineBanner";
import { fontVariables } from "./fonts";

export const BUILD_ID = process.env.NEXT_PUBLIC_BUILD_ID || "dev";

// 2026-11-09: Sekme başlığında marka ÖNE alındı. Önceden "🌐 GLOBAL ($) ·
// SCALPER AGENT" idi; tarayıcı sekmesinde ilk 55–60 karakter okunur, emoji ve
// "($)" önce geldiği için sekmeler arasında tanınırlık düşüyordu.
export const metadata: Metadata = {
  title: {
    default: "SCALPER GLOBAL · Forex & Altın Terminali",
    template: "%s · SCALPER GLOBAL"
  },
  description: "Binance Global & Forex gerçek zamanlı piyasa analizi, radar ve otonom scalping PWA terminali ($)",
  applicationName: "SCALPER GLOBAL",
  manifest: "/manifest.webmanifest",
  icons: {
    icon: "/icon.svg",
    // iOS home-screen: apple-touch-icon PNG (180/152/120)
    apple: [
      { url: "/icons/iOS/Icon-180.png", sizes: "180x180", type: "image/png" },
      { url: "/icons/iOS/Icon-152.png", sizes: "152x152", type: "image/png" },
      { url: "/icons/iOS/Icon-120.png", sizes: "120x120", type: "image/png" }
    ]
  },
  appleWebApp: {
    capable: true,
    statusBarStyle: "black-translucent",
    title: "SCALPER GLOBAL"
  },
  formatDetection: {
    telephone: false
  }
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  // 2026-11-09: maximumScale 5 KORUNDU — `user-scalable=no` / `maximumScale=1`
  // zoom'u engeller ve WCAG 1.4.4'ü ihlal eder. Bilinçli olarak dokunulmadı.
  maximumScale: 5,
  viewportFit: "cover",
  // Uygulamanın VARSAYILANI artık AÇIK TEMA (Erkan kararı, 2026-11-09). Bu
  // yüzden tema rengi de açık tema değeri. Kullanıcı Karanlık'a geçtiğinde
  // `lib/theme.tsx` bu meta'yı çalışma anında günceller; OS tercihine göre iki
  // değer bildirmek artık yanıltıcı olurdu (app teması OS'e bağlı değil).
  themeColor: "#f8fafc"
};

export default function RootLayout({
  children
}: {
  children: React.ReactNode;
}) {
  return (
    // 2026-11-09: Başlangıç sınıfı `dark` → `light`. Varsayılan tema artık açık.
    // `dark:` Tailwind varyantları `.dark` sınıfına bağlı olduğu için bu değişiklik
    // onları da tutarlı hâle getirir (koyu varsayılanda `text-slate-800
    // dark:text-cyan-300` gibi çiftler açık temada yanlış dalı seçiyordu).
    <html lang="tr" className={`${fontVariables} light`} suppressHydrationWarning data-build-id={BUILD_ID}>
      <head>
        <meta name="mobile-web-app-capable" content="yes" />
        <meta name="apple-mobile-web-app-capable" content="yes" />
        <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent" />
        <meta name="build-id" content={BUILD_ID} />
        {/* Tema belirleme — FOUC önleyici, boyamadan ÖNCE senkron çalışır.
            VARSAYILAN AÇIK TEMA (Erkan kararı, 2026-11-09). Kullanıcının
            kayıtlı tercihi (localStorage) her zaman kazanır. `lib/theme.tsx`
            ile aynı kuralı uygular — ikisi ayrışırsa açılışta tema zıplar. */}
        <script
          dangerouslySetInnerHTML={{
            __html: `(function(){try{var t=localStorage.getItem("theme")||localStorage.getItem("forex_theme_preference");if(t!=="light"&&t!=="dark"){t="light";}var r=document.documentElement;if(t==="light"){r.classList.remove("dark");r.classList.add("light");r.setAttribute("data-theme","light");r.style.colorScheme="light";}else{r.classList.remove("light");r.classList.add("dark");r.setAttribute("data-theme","dark");r.style.colorScheme="dark";}}catch(e){}})()`,
          }}
        />
      </head>
      <body suppressHydrationWarning className="font-sans antialiased bg-bunker-950 text-white min-h-screen transition-colors duration-150">
        <ThemeProvider>
          <PwaProvider>
            <OfflineBanner />
            <AuthGate>
              <Suspense fallback={null}>
                <AppShell>{children}</AppShell>
              </Suspense>
            </AuthGate>
            <PwaInstallBanner />
          </PwaProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
