import type { Metadata } from "next";
import { Suspense } from "react";
import "./globals.css";
import AuthGate from "./components/AuthGate";
import AppShell from "./components/AppShell";
import { PwaProvider } from "./lib/pwa";
import { ThemeProvider } from "./lib/theme";
import PwaInstallBanner from "./components/PwaInstallBanner";
import OfflineBanner from "./components/OfflineBanner";

export const BUILD_ID = process.env.NEXT_PUBLIC_BUILD_ID || "dev";

export const metadata: Metadata = {
  title: {
    default: "🌐 GLOBAL ($) · SCALPER AGENT",
    template: "%s · 🌐 GLOBAL ($)"
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

export const viewport = {
  width: "device-width",
  initialScale: 1,
  maximumScale: 5,
  viewportFit: "cover",
  themeColor: "#070b14"
};

export default function RootLayout({
  children
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="tr" className="dark" suppressHydrationWarning data-build-id={BUILD_ID}>
      <head>
        <meta name="mobile-web-app-capable" content="yes" />
        <meta name="apple-mobile-web-app-capable" content="yes" />
        <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent" />
        <meta name="build-id" content={BUILD_ID} />
        <script
          dangerouslySetInnerHTML={{
            __html: `(function(){try{var t=localStorage.getItem("theme")||localStorage.getItem("forex_theme_preference");if(t==="light"){document.documentElement.classList.remove("dark");document.documentElement.classList.add("light");document.documentElement.setAttribute("data-theme","light");document.documentElement.style.colorScheme="light";}else{document.documentElement.classList.remove("light");document.documentElement.classList.add("dark");document.documentElement.setAttribute("data-theme","dark");document.documentElement.style.colorScheme="dark";}}catch(e){}})()`,
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
