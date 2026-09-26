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
  "/reports/forecasts": "Fiyat Tahminleri",
  "/settings": "Ayarlar",
  "/admin": "Yönetim Merkezi",
  "/profile": "Kullanıcı Profili",
  "/database": "Veritabanı",
  "/audit-logs": "Olay Kayıtları",
  "/macd-monitor": "MACD Monitör",
  "/users": "Kullanıcı Yönetimi",
  "/chat": "Chat Merkezi",
  "/memory": "LLM Hafızası",
  "/symbol-analysis": "Sembol Analizi",
  "/alerts": "Alarmlar & Bildirimler",
  "/gainer-radar": "Yükselenler Radarı",
  "/history": "İşlem Geçmişi",
  "/risk": "Risk Yönetimi",
  "/system-health": "Sistem Sağlığı",
  "/trade-repair": "İşlem Onarımı",
};

export default function TopBar() {
  const pathname = usePathname();
  const exchange = useExchange();
  const raw =
    labels[pathname] ||
    Object.entries(labels).find(([path]) => path !== "/" && pathname.startsWith(path))?.[1] ||
    "Scalper Agent";
  // Özel terminal başlığı borsaya göre değişir. Sabit "Binance TR Canlı
  // İşlem" yazısı Global kullanıcısına yanlış borsayı gösterirdi.
  const currentTitle = raw.startsWith("Binance TR Canlı İşlem")
    ? `${exchange.loading ? "Binance" : exchange.label} Canlı İşlem`
    : raw;

  return (
    <div className="topbar">
      <div>
        <p className="topbar-kicker">SCALPERAGENT · PAPER TRADING</p>
        <p className="topbar-title">{currentTitle}</p>
      </div>
      <div className="topbar-status">
        {/* Borsa adı backend'den gelir; iki örnekte farklıdır. Sabit metin
            kalmış olsaydı Global kullanıcısı "Binance TR Canlı İşlem"
            başlığını kendi sayfasında görürdü. */}
        <span className="status-dot" />
        {exchange.error && !exchange.loading
          ? "CANLI PUBLIC DATA · BORSA DOĞRULANAMADI"
          : `CANLI PUBLIC DATA · ${exchange.loading ? "…" : exchange.label.toUpperCase()}`}
      </div>
    </div>
  );
}
