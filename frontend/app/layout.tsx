import type { Metadata } from "next";
import "./globals.css";
import AuthGate from "./components/AuthGate";
import AppShell from "./components/AppShell";

export const BUILD_ID = process.env.NEXT_PUBLIC_BUILD_ID || "dev";

export const metadata: Metadata = {
  title: {
    default: "🌐 GLOBAL ($) · SCALPER AGENT",
    template: "%s · 🌐 GLOBAL ($)"
  },
  description: "Binance Global public-data paper scalping terminal ($)",
  manifest: "/manifest.webmanifest",
  icons: {
    icon: "/icon.svg",
    // iOS home-screen: apple-touch-icon PNG (180/152/120), SVG yalnız tarayıcı sekmesi.
    apple: [
      { url: "/icons/iOS/Icon-180.png", sizes: "180x180", type: "image/png" },
      { url: "/icons/iOS/Icon-152.png", sizes: "152x152", type: "image/png" },
      { url: "/icons/iOS/Icon-120.png", sizes: "120x120", type: "image/png" }
    ]
  },
  // Next's appleWebApp metadata emits the deprecated apple-mobile-web-app-capable tag.
};

export const viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  themeColor: "#070b14"
};

export default function RootLayout({
  children
}: {
  children: React.ReactNode;
}) {
  return (
    // suppressHydrationWarning: browser extensions inject attributes onto <html>
    // before hydration (e.g. rtrvr-*); ignore mismatches on this element only.
    <html lang="tr" className="dark" suppressHydrationWarning data-build-id={BUILD_ID}>
      <head><meta name="mobile-web-app-capable" content="yes" /><meta name="build-id" content={BUILD_ID} /></head>
      <body suppressHydrationWarning className="font-sans antialiased">
        <AuthGate>
        <AppShell>{children}</AppShell>
        </AuthGate>
      </body>
    </html>
  );
}
