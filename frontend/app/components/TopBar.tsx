"use client";

import { usePathname } from "next/navigation";
import { useExchange } from "../lib/exchange";
import { useMarketMode } from "../lib/marketMode";
import { usePwa } from "../lib/pwa";

const labels: Record<string, string> = {
  "/": "Canlı Terminal",
  "/portfolio": "Sanal Portföy",
  "/monitoring": "Radar & Hız Avcısı",
  "/charts": "Grafik",
  "/technical-charts": "Teknik Grafik (4'lü Ekran)",
  "/binance-tr": "Binance Canlı İşlem",
  "/reports": "Raporlar",
  "/settings": "Ayarlar",
  "/admin": "Yönetim Merkezi",
  "/profile": "Kullanıcı Profili",
  "/database": "Veritabanı",
  "/audit-logs": "Olay Kayıtları",
  "/macd-monitor": "MACD Monitör",
  "/users": "Kullanıcı Yönetimi",
  "/chat": "Chat Merkezi",
  "/system-health": "Sistem Sağlığı",
  "/forex": "Forex Radar",
  "/forex/btc-gold": "BTC + Altın Konsolu",
  "/forex/portfolio": "Forex Portföy",
  "/forex/charts": "Forex Grafik",
  "/forex/technical-charts": "Forex 4'lü Grafik",
  "/forex/reports": "Forex Raporlar",
  "/forex/calendar": "Ekonomik Takvim",
  "/mtf-scanner": "MTF Tarama",
  "/alerts": "Alarmlar",
  "/memory": "LLM Hafızası",
  "/risk": "Risk Yönetimi",
};

export default function TopBar() {
  const pathname = usePathname();
  const exchange = useExchange();
  const { marketMode, setMarketMode } = useMarketMode();
  const { isInstallable, isInstalled, openInstallDialog } = usePwa();

  const raw =
    labels[pathname] ||
    Object.entries(labels).find(([path]) => path !== "/" && pathname.startsWith(path))?.[1] ||
    "SCALPER GLOBAL AGENT";

  const currentTitle = raw.startsWith("Binance TR Canlı İşlem")
    ? `${exchange.loading ? "Binance" : exchange.label} Canlı İşlem`
    : raw;

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
                🌐 GLOBAL
              </span>
              <p className="topbar-kicker text-cyan-400/80 font-mono hidden sm:block">
                BINANCE GLOBAL · $ · PAPER TRADING
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

          {/* Piyasa Modu Hızlı Değiştirici (Spot / Forex) */}
          <div className="flex items-center p-0.5 rounded-lg bg-bunker-900 border border-bunker-800">
            <button
              type="button"
              onClick={() => setMarketMode("spot")}
              className={`px-2 py-0.5 rounded font-mono text-[10px] font-bold transition-all ${
                marketMode === "spot"
                  ? "bg-amber-500/25 text-yellow-400 border border-yellow-500/40 shadow-[0_0_6px_rgba(234,179,8,0.2)]"
                  : "text-bunker-muted hover:text-white"
              }`}
              title="Kripto Spot Modu"
            >
              🟡 SPOT
            </button>
            <button
              type="button"
              onClick={() => setMarketMode("forex")}
              className={`px-2 py-0.5 rounded font-mono text-[10px] font-bold transition-all ${
                marketMode === "forex"
                  ? "bg-blue-500/25 text-cyan-300 border border-cyan-400/40 shadow-[0_0_6px_rgba(0,240,255,0.2)]"
                  : "text-bunker-muted hover:text-white"
              }`}
              title="Forex & Altın Modu"
            >
              💱 FX
            </button>
          </div>

          {/* Canlı Veri Göstergesi */}
          <div className="hidden md:flex items-center gap-1.5 rounded-full border border-cyan-500/30 bg-cyan-950/40 px-2.5 py-1 font-mono text-[10px] text-cyan-300 shadow-[inset_0_1px_rgba(255,255,255,0.06)]">
            <span className="w-2 h-2 rounded-full bg-cyan-400 animate-pulse shadow-[0_0_8px_#00f0ff]" />
            <span className="font-semibold tracking-wider">
              {marketMode === "forex" ? "GLOBAL FOREX" : "BINANCE GLOBAL"}
            </span>
          </div>

          <div className="flex items-center gap-1 font-mono text-[10px] tracking-wider text-slate-300">
            <span className="w-1.5 h-1.5 rounded-full bg-neon-green animate-pulse" />
            <span className="hidden sm:inline">
              {exchange.error && !exchange.loading
                ? "BAĞLANTI HATASI"
                : marketMode === "forex"
                ? "CANLI PİYASA"
                : (exchange.loading ? "…" : exchange.label.toUpperCase())}
            </span>
          </div>
        </div>
      </header>
    </>
  );
}
