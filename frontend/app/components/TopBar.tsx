"use client";

import { usePathname } from "next/navigation";
import { useExchange } from "../lib/exchange";
import { usePwa } from "../lib/pwa";

// 2026-10-07: Yalnız var olan rotaların başlıkları tutulur. Silinen spot
// sayfalarının girdileri burada kalsaydı ölü referans olurdu.
const labels: Record<string, string> = {
  "/": "Canlı Terminal",
  "/settings": "Ayarlar",
  "/profile": "Kullanıcı Profili",
  "/chat": "Chat Merkezi",
  "/system-health": "Sistem Sağlığı",
  "/forex": "Forex Radar",
  "/forex/btc-gold": "BTC + Altın Konsolu",
  "/forex/islemler": "Forex İşlemler",
  "/forex/portfolio": "Forex Portföy",
  "/forex/charts": "Forex Grafik",
  "/forex/technical-charts": "Forex 4'lü Grafik",
  "/forex/reports": "Forex Raporlar",
  "/forex/calendar": "Ekonomik Takvim",
  "/forex/ayarlar": "Forex Ayarları",
};

export default function TopBar() {
  const pathname = usePathname();
  const exchange = useExchange();
  const { isInstallable, isInstalled, openInstallDialog } = usePwa();

  const raw =
    labels[pathname] ||
    Object.entries(labels).find(([path]) => path !== "/" && pathname.startsWith(path))?.[1] ||
    "SCALPER GLOBAL AGENT";

  const currentTitle = raw;

  const handleOpenMobileMenu = () => {
    if (typeof window !== "undefined") {
      window.dispatchEvent(new CustomEvent("open-mobile-menu"));
    }
  };

  return (
    <>
      {/* Global Terminal Üst Vurgu Çizgisi: Siber-siyan ışıltılı bant */}
      <div className="fixed top-0 left-0 right-0 h-[2.5px] bg-gradient-to-r from-cyan-400 via-sky-400 to-blue-600 shadow-[0_0_12px_rgba(0,240,255,0.7)] z-50 pointer-events-none" />

      <header
        className="topbar sticky top-0 z-30 flex items-center justify-between gap-2.5 px-3 sm:px-6 py-2.5 bg-bunker-950/90 border-b border-bunker-800/90 backdrop-blur-xl"
        style={{ paddingTop: "max(0.6rem, env(safe-area-inset-top, 0px))" }}
      >
        {/* Sol Alan: Mobil Menü Butonu + Başlık */}
        <div className="flex items-center gap-2.5 min-w-0">
          {/* Mobil Menü Aç Butonu */}
          <button
            type="button"
            onClick={handleOpenMobileMenu}
            className="md:hidden flex items-center justify-center w-9 h-9 rounded-xl border border-bunker-700 bg-bunker-900/90 text-white hover:text-cyan-300 hover:border-cyan-400/50 transition-all touch-target active:scale-95 shadow-sm"
            aria-label="Menüyü aç"
          >
            <span className="text-lg leading-none">☰</span>
          </button>

          <div className="flex flex-col min-w-0">
            <div className="flex items-center gap-1.5 flex-wrap">
              <span className="inline-flex items-center gap-1 px-1.5 py-0.2 rounded font-mono text-[9px] font-bold tracking-wider bg-cyan-500/15 border border-cyan-400/40 text-cyan-300 shadow-[0_0_8px_rgba(0,240,255,0.25)]">
                💱 FOREX
              </span>
              <p className="topbar-kicker text-cyan-400/80 font-mono hidden sm:block">
                FOREX &amp; EMTİA · DEMO / LIVE
              </p>
            </div>
            <p className="topbar-title truncate text-sm sm:text-base font-bold text-white font-mono">
              {currentTitle}
            </p>
          </div>
        </div>

        {/* Sağ Alan: PWA Yükle Butonu + Mod Seçici + Durum */}
        <div className="topbar-status flex items-center gap-2 shrink-0">
          {/* Mobil/Masaüstü PWA Yükleme Butonu */}
          {isInstallable && !isInstalled && (
            <button
              type="button"
              onClick={openInstallDialog}
              className="flex items-center gap-1.5 py-1 px-2.5 rounded-lg border border-cyan-400/50 bg-gradient-to-r from-cyan-950/80 to-blue-950/80 hover:from-cyan-900/80 hover:to-blue-900/80 text-cyan-300 font-mono text-[10px] sm:text-xs font-bold tracking-wide shadow-[0_0_10px_rgba(0,240,255,0.2)] transition-all touch-target active:scale-95"
              title="Scalper Global uygulamasını cihazınıza yükleyin"
            >
              <span>📲</span>
              <span className="hidden xs:inline sm:inline">YÜKLE</span>
            </button>
          )}

          {/* 2026-10-07: Piyasa modu hızlı değiştirici (SPOT / FX) KALDIRILDI —
              uygulama yalnızca Forex & Emtia sunar, seçilecek ikinci piyasa yok. */}

          {/* Canlı Veri Göstergesi */}
          <div className="hidden md:flex items-center gap-1.5 rounded-full border border-cyan-500/30 bg-cyan-950/40 px-2.5 py-1 font-mono text-[10px] text-cyan-300 shadow-[inset_0_1px_rgba(255,255,255,0.06)]">
            <span className="w-2 h-2 rounded-full bg-cyan-400 animate-pulse shadow-[0_0_8px_#00f0ff]" />
            <span className="font-semibold tracking-wider">
              GLOBAL FOREX
            </span>
          </div>

          <div className="flex items-center gap-1 font-mono text-[10px] tracking-wider text-slate-300">
            <span className="w-1.5 h-1.5 rounded-full bg-neon-green animate-pulse" />
            <span className="hidden sm:inline">
              {exchange.error && !exchange.loading ? "BAĞLANTI HATASI" : "CANLI PİYASA"}
            </span>
          </div>
        </div>
      </header>
    </>
  );
}
