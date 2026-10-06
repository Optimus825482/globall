"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { BOTTOM_NAV_ITEMS, FOREX_BOTTOM_NAV_ITEMS } from "../lib/menu";
import { useMarketMode } from "../lib/marketMode";

export default function BottomNav() {
  const pathname = usePathname();
  const { marketMode } = useMarketMode();
  const navItems = marketMode === "forex" ? FOREX_BOTTOM_NAV_ITEMS : BOTTOM_NAV_ITEMS;

  const handleOpenMenu = () => {
    if (typeof window !== "undefined") {
      window.dispatchEvent(new CustomEvent("open-mobile-menu"));
    }
  };

  return (
    <nav
      className="fixed bottom-0 left-0 right-0 z-40 flex md:hidden items-center justify-around border-t border-bunker-800/90 bg-bunker-950/95 backdrop-blur-xl px-1.5 py-1 text-[11px] font-mono shadow-[0_-4px_25px_rgba(0,0,0,0.6)]"
      style={{ paddingBottom: "max(0.45rem, env(safe-area-inset-bottom, 0px))" }}
      aria-label="Mobil Hızlı Gezinme"
    >
      {navItems.map((item) => {
        const isActive = pathname === item.href || (item.href !== "/" && pathname.startsWith(item.href));
        return (
          <Link
            key={item.href}
            href={item.href}
            className={`flex flex-1 flex-col items-center justify-center py-1 px-1 rounded-xl transition-all touch-target active:scale-90 ${
              isActive
                ? "text-cyan-300 font-bold bg-cyan-950/50 border border-cyan-500/30 shadow-[0_0_10px_rgba(0,240,255,0.15)]"
                : "text-bunker-muted hover:text-white"
            }`}
          >
            <span className="text-xl leading-none mb-1 transition-transform">{item.icon}</span>
            <span className="truncate tracking-tight text-[10px]">{item.label}</span>
          </Link>
        );
      })}

      <button
        type="button"
        onClick={handleOpenMenu}
        className="flex flex-1 flex-col items-center justify-center py-1 px-1 rounded-xl text-bunker-muted hover:text-white transition-all touch-target active:scale-90"
        aria-label="Tüm Menüyü Aç"
      >
        <span className="text-xl leading-none mb-1">☰</span>
        <span className="truncate tracking-tight text-[10px]">Menü</span>
      </button>
    </nav>
  );
}
