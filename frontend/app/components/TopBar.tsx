"use client";

import { usePathname } from "next/navigation";
import { useExchange } from "../lib/exchange";
import { usePwa } from "../lib/pwa";
import { useTheme } from "../lib/theme";
import ForexEventTickerBanner from "./ForexEventTickerBanner";
import NavIcon from "./NavIcon";

// 2026-10-07: Yalnız var olan rotaların başlıkları tutulur. Silinen spot
// sayfalarının girdileri burada kalsaydı ölü referans olurdu.
const labels: Record<string, string> = {
  "/": "Ana Sayfa",
  "/settings": "Ayarlar",
  "/profile": "Kullanıcı Profili",
  "/chat": "Chat Merkezi",
  "/system-health": "Sistem Sağlığı",
  "/forex": "Forex Radar",
  "/forex/btc-gold": "BTC + Altın Konsolu",
  "/forex/islemler": "Forex İşlemler",
  "/forex/portfolio": "Forex Portföy",
  // 2026-10-14: "Teknik Grafik" sayfası Grafik ile birleşti; ayrı etiket kalktı.
  "/forex/charts": "Forex Grafik",
  "/forex/reports": "Forex Raporlar",
  "/forex/calendar": "Ekonomik Takvim",
  "/forex/ayarlar": "Forex Ayarları",
};

export default function TopBar() {
  const pathname = usePathname();
  const exchange = useExchange();
  const { isInstallable, isInstalled, openInstallDialog } = usePwa();
  const { isLight, toggleTheme } = useTheme();

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
      <div className="fixed top-0 left-0 right-0 h-[2px] bg-cyan-400/80 z-50 pointer-events-none" />

      <div className="sticky top-0 z-30">
        <header
          className="topbar flex items-center justify-between gap-2.5 px-3 sm:px-6 py-2.5 bg-bunker-950/90 border-b border-bunker-800/90 backdrop-blur-xl"
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
            <NavIcon name="menu" className="w-5 h-5" />
          </button>

          <div className="flex flex-col min-w-0">
            <p className="topbar-title truncate text-sm sm:text-base font-bold text-white font-mono flex items-center gap-2">
              <span className="truncate">{currentTitle}</span>
              <span className="hidden sm:inline-flex shrink-0 rounded border border-amber-400/40 bg-amber-500/10 px-1.5 py-0.5 text-[9px] font-bold tracking-wider text-amber-200">DEMO</span>
            </p>
          </div>
        </div>

        {/* Sağ Alan: PWA Yükle Butonu + Tema Değiştirici + Durum */}
        <div className="topbar-status flex items-center gap-2 shrink-0">
          {/* Aydınlık / Karanlık Mod Değiştirici */}
          <button
            type="button"
            onClick={toggleTheme}
            className="flex items-center gap-1.5 py-1 px-2.5 rounded-lg border border-slate-300 dark:border-bunker-700 bg-white/80 dark:bg-bunker-900/90 hover:bg-slate-100 dark:hover:bg-bunker-800 text-slate-800 dark:text-cyan-300 font-mono text-[10px] sm:text-xs font-bold transition-all touch-target active:scale-95 shadow-sm"
            title={isLight ? "Karanlık Moda Geç (Dark Mode)" : "Aydınlık Moda Geç (Light Mode)"}
            aria-label={isLight ? "Karanlık Moda Geç" : "Aydınlık Moda Geç"}
          >
            <span>{isLight ? "Karanlık" : "Aydınlık"}</span>
          </button>

          {/* Mobil/Masaüstü PWA Yükleme Butonu */}
          {isInstallable && !isInstalled && (
            <button
              type="button"
              onClick={openInstallDialog}
              className="flex items-center gap-1.5 py-1 px-2.5 rounded-lg border border-cyan-400/50 bg-gradient-to-r from-cyan-950/80 to-blue-950/80 hover:from-cyan-900/80 hover:to-blue-900/80 text-cyan-300 font-mono text-[10px] sm:text-xs font-bold tracking-wide shadow-[0_0_10px_rgba(0,240,255,0.2)] transition-all touch-target active:scale-95"
              title="Scalper Global uygulamasını cihazınıza yükleyin"
            >
              <span className="hidden xs:inline sm:inline">YÜKLE</span>
            </button>
          )}

          {/* 2026-10-07: Piyasa modu hızlı değiştirici (SPOT / FX) KALDIRILDI —
              uygulama yalnızca Forex & Emtia sunar, seçilecek ikinci piyasa yok. */}

          <div className="flex items-center gap-1.5 font-mono text-[10px] tracking-wider text-slate-900 dark:text-slate-300 font-black">
            <span className="w-2 h-2 rounded-full bg-emerald-600 dark:bg-neon-green animate-pulse" />
            <span className="hidden sm:inline">
              {exchange.error && !exchange.loading ? "BAĞLANTI HATASI" : "Veri akışı canlı"}
            </span>
          </div>
        </div>
      </header>
      <ForexEventTickerBanner />
    </div>
  </>
  );
}
