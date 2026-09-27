"use client";
import { usePathname } from "next/navigation";
import { useExchange } from "../lib/exchange";

const labels: Record<string, string> = {
  "/": "Canlı Terminal",
  "/portfolio": "Sanal Portföy",
  "/monitoring": "Radar & Hız Avcısı",
  "/charts": "Grafik",
  "/technical-charts": "Teknik Grafik (4'lü Ekran)",
  "/binance-tr": "Binance TR Canlı İşlem",
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
};

export default function TopBar() {
  const pathname = usePathname();
  const exchange = useExchange();
  const raw =
    labels[pathname] ||
    Object.entries(labels).find(([path]) => path !== "/" && pathname.startsWith(path))?.[1] ||
    "SCALPER GLOBAL AGENT";
  // Özel terminal başlığı borsaya göre değişir. Sabit "Binance TR Canlı
  // İşlem" yazısı Global kullanıcısına yanlış borsayı gösterirdi.
  const currentTitle = raw.startsWith("Binance TR Canlı İşlem")
    ? `${exchange.loading ? "Binance" : exchange.label} Canlı İşlem`
    : raw;

  return (
    <>
      {/* Global Terminal Üst Vurgu Çizgisi: TR örneğinde bulunmayan, Global örneğini ilk bakışta ayırt ettiren siber-siyan ışıltılı bant */}
      <div className="fixed top-0 left-0 right-0 h-[2.5px] bg-gradient-to-r from-cyan-400 via-sky-400 to-blue-600 shadow-[0_0_12px_rgba(0,240,255,0.7)] z-50 pointer-events-none" />
      <div className="topbar">
        <div className="flex flex-col">
          <div className="flex items-center gap-1.5">
            <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded font-mono text-[9px] font-bold tracking-wider bg-cyan-500/15 border border-cyan-400/40 text-cyan-300 shadow-[0_0_8px_rgba(0,240,255,0.25)]">
              🌐 GLOBAL
            </span>
            <p className="topbar-kicker text-cyan-400/80 font-mono">
              BINANCE GLOBAL · $ · PAPER TRADING
            </p>
          </div>
          <p className="topbar-title">{currentTitle}</p>
        </div>
        <div className="topbar-status flex items-center gap-2">
          {/* Global Terminal Gösterge Rozeti */}
          <div className="hidden sm:flex items-center gap-1.5 rounded-full border border-cyan-500/30 bg-cyan-950/40 px-2.5 py-1 font-mono text-[10px] text-cyan-300 shadow-[inset_0_1px_rgba(255,255,255,0.06)]">
            <span className="w-2 h-2 rounded-full bg-cyan-400 animate-pulse shadow-[0_0_8px_#00f0ff]" />
            <span className="font-semibold tracking-wider">BINANCE GLOBAL</span>
            <span className="text-cyan-400/50">·</span>
            <span className="font-bold text-cyan-200">$</span>
          </div>
          <span className="status-dot" />
          <span className="font-mono text-[10px] tracking-wider text-slate-300">
            {exchange.error && !exchange.loading
              ? "CANLI PUBLIC DATA · BAĞLANTI HATASI"
              : `CANLI PUBLIC DATA · ${exchange.loading ? "…" : exchange.label.toUpperCase()}`}
          </span>
        </div>
      </div>
    </>
  );
}
