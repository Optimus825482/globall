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
  // İki şema için ayrı tema rengi: açık temada tarayıcı çubuğu koyu kalıp
  // sayfayla çelişmiyordu (görsel sıçrama). Şema başına bir değer bildirilir.
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f8fafc" },
    { media: "(prefers-color-scheme: dark)", color: "#070b14" },
  ]
};

export default function RootLayout({
  children
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="tr" className={`${fontVariables} dark`} suppressHydrationWarning data-build-id={BUILD_ID}>
      <head>
        <meta name="mobile-web-app-capable" content="yes" />
        <meta name="apple-mobile-web-app-capable" content="yes" />
        <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent" />
        <meta name="build-id" content={BUILD_ID} />
        {/* Tema belirleme — FOUC önleyici, boyamadan ÖNCE senkron çalışır.
            2026-11-09: `prefers-color-scheme` eklendi. Önceden depolanmış tema
            yoksa koşulsuz koyu uygulanıyordu; işletim sistemi açık temada olan
            ilk ziyaretçi tercihine rağmen koyu görüyordu. Artık OS tercihi
            okunur, kullanıcının açık seçimi (localStorage) her zaman kazanır. */}
        <script
          dangerouslySetInnerHTML={{
            __html: `(function(){try{var t=localStorage.getItem("theme")||localStorage.getItem("forex_theme_preference");if(t!=="light"&&t!=="dark"){t=window.matchMedia&&window.matchMedia("(prefers-color-scheme: light)").matches?"light":"dark";}var r=document.documentElement;if(t==="light"){r.classList.remove("dark");r.classList.add("light");r.setAttribute("data-theme","light");r.style.colorScheme="light";}else{r.classList.remove("light");r.classList.add("dark");r.setAttribute("data-theme","dark");r.style.colorScheme="dark";}}catch(e){}})()`,
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
