"use client";

import { useEffect } from "react";
import { usePathname } from "next/navigation";
import Sidebar from "./Sidebar";
import TopBar from "./TopBar";
import BottomNav from "./BottomNav";
import ForexRadarModal from "../forex/components/ForexRadarModal";
import { reconcilePushSubscription } from "../lib/push";
import { useExchangeProvider } from "../lib/exchange";

const CURRENT_BUILD = process.env.NEXT_PUBLIC_BUILD_ID || "dev";

export default function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  // 2026-10-07: `/symbol-analysis` (spot sembol analizi) sayfası kaldırıldı;
  // onun `?embedded=1` gömme modu da ölü kaldı. Borsa kimliği backend'den TEK
  // kez okunur ve tüm ağaca dağıtılır (menü, para birimi rozeti, sembol
  // türetme). `NEXT_PUBLIC_*` build-time sabittir; build ile backend arasında
  // uyuşmazlık olursa bu değer onu GÖSTERİR — uygulama sağlıklı görünüp yanlış
  // borsada çalışmaz.
  const { info: exchange, ExchangeContext } = useExchangeProvider();

  // PUSH-RESILIENCE (2026-09-16): açılışta aboneliği SESSİZCE uzlaştır.
  useEffect(() => {
    void reconcilePushSubscription().catch(() => undefined);
  }, []);

  // SW VERSİYON KONTROLÜ (2026-09-16)
  useEffect(() => {
    function onMessage(event: MessageEvent) {
      const data = event.data;
      if (!data || data.type !== "SW_VERSION") return;
      if (data.build === CURRENT_BUILD) return;
      const flag = `scalper_sw_reloaded_${data.build}`;
      if (typeof sessionStorage !== "undefined" && sessionStorage.getItem(flag)) return;
      if (typeof sessionStorage !== "undefined") sessionStorage.setItem(flag, "1");
      if (typeof window !== "undefined") window.location.reload();
    }
    if (typeof navigator !== "undefined" && navigator.serviceWorker) {
      navigator.serviceWorker.addEventListener("message", onMessage);
      return () => { try { navigator.serviceWorker.removeEventListener("message", onMessage); } catch { /* yok say */ } };
    }
  }, []);

  const isForexIslemler = pathname === "/forex/islemler" || pathname?.startsWith("/forex/islemler/");

  if (isForexIslemler) {
    return (
      <ExchangeContext.Provider value={exchange}>
        <main className="min-h-screen w-full overflow-y-auto">
          <div className="w-full px-2 sm:px-4 lg:px-6 py-2.5 sm:py-4 max-w-[1700px] mx-auto">
            {children}
          </div>
          <ForexRadarModal />
        </main>
      </ExchangeContext.Provider>
    );
  }
  return (
    <ExchangeContext.Provider value={exchange}>
      <div className="flex min-h-screen">
        <div data-sidebar><Sidebar /></div>
        <main className="flex-1 min-w-0 min-h-screen overflow-y-auto">
          <div data-topbar><TopBar /></div>
          <div className="content-shell">{children}</div>
        </main>
        <BottomNav />
        <ForexRadarModal />
      </div>
    </ExchangeContext.Provider>
  );
}
