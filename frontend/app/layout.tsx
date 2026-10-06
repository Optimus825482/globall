import type { Metadata } from "next";
import "./globals.css";
import AuthGate from "./components/AuthGate";
import AppShell from "./components/AppShell";
import { PwaProvider } from "./lib/pwa";
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
      </head>
      <body suppressHydrationWarning className="font-sans antialiased bg-bunker-950 text-white min-h-screen">
        <PwaProvider>
          <OfflineBanner />
          <AuthGate>
            <AppShell>{children}</AppShell>
          </AuthGate>
          <PwaInstallBanner />
        </PwaProvider>
      </body>
    </html>
  );
}
