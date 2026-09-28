"use client";

import React, { createContext, useContext, useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";

export type MarketMode = "spot" | "forex";

interface MarketModeContextType {
  marketMode: MarketMode;
  setMarketMode: (mode: MarketMode) => void;
  toggleMarketMode: () => void;
}

const STORAGE_KEY = "scalper_market_mode";

const MarketModeContext = createContext<MarketModeContextType>({
  marketMode: "spot",
  setMarketMode: () => {},
  toggleMarketMode: () => {},
});

export function MarketModeProvider({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [marketMode, setMarketModeState] = useState<MarketMode>("spot");
  const [mounted, setMounted] = useState(false);

  // Synchronize initial state with path or localStorage
  useEffect(() => {
    setMounted(true);
    if (pathname.startsWith("/forex")) {
      setMarketModeState("forex");
      return;
    }

    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      if (saved === "forex" || saved === "spot") {
        setMarketModeState(saved);
      }
    } catch {
      // Storage unavailable fallback
    }
  }, [pathname]);

  // Keep state in sync when URL changes
  useEffect(() => {
    if (pathname.startsWith("/forex") && marketMode !== "forex") {
      setMarketModeState("forex");
    } else if (!pathname.startsWith("/forex") && pathname !== "/" && marketMode === "forex") {
      // Don't auto-switch unless it's a dedicated spot route
      if (pathname.startsWith("/monitoring") || pathname.startsWith("/mtf-scanner") || pathname.startsWith("/charts")) {
        setMarketModeState("spot");
      }
    }
  }, [pathname, marketMode]);

  const setMarketMode = (mode: MarketMode) => {
    setMarketModeState(mode);
    try {
      localStorage.setItem(STORAGE_KEY, mode);
    } catch {
      // Storage unavailable fallback
    }

    // Smart navigation when changing market mode
    if (mode === "forex" && !pathname.startsWith("/forex")) {
      router.push("/forex");
    } else if (mode === "spot" && pathname.startsWith("/forex")) {
      router.push("/monitoring");
    }
  };

  const toggleMarketMode = () => {
    setMarketMode(marketMode === "spot" ? "forex" : "spot");
  };

  return (
    <MarketModeContext.Provider value={{ marketMode, setMarketMode, toggleMarketMode }}>
      {children}
    </MarketModeContext.Provider>
  );
}

export const useMarketMode = () => useContext(MarketModeContext);
