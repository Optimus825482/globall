"use client";

import React, { useEffect, useRef } from "react";

export default function ForexCalendarPage() {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!containerRef.current) return;
    containerRef.current.innerHTML = "";

    const script = document.createElement("script");
    script.src = "https://s3.tradingview.com/external-embedding/embed-widget-events.js";
    script.type = "text/javascript";
    script.async = true;
    script.innerHTML = JSON.stringify({
      width: "100%",
      height: "100%",
      colorTheme: "dark",
      isTransparent: true,
      locale: "tr",
      importanceFilter: "-1,0,1",
      countryFilter: "us,eu,gb,jp,ch,ca,au,nz",
    });

    containerRef.current.appendChild(script);
  }, []);

  return (
    <div className="space-y-4 pb-12 h-[calc(100vh-4rem)] flex flex-col">
      {/* BAŞLIK */}
      <div className="flex items-center justify-between p-4 rounded-xl bg-bunker-900/80 border border-bunker-800">
        <div className="flex items-center gap-3">
          <span className="text-2xl">📅</span>
          <div>
            <h1 className="font-mono text-base font-bold text-white tracking-tight">
              KÜRESEL EKONOMİK TAKVİM
            </h1>
            <p className="text-xs text-bunker-muted font-mono">
              Faiz Kararları, Enflasyon (TÜFE/CPI), İstihdam (NFP) ve Merkez Bankası Duyuruları
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2 font-mono text-xs text-bunker-muted">
          <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
          <span>Canlı Makro Veri Akışı</span>
        </div>
      </div>

      {/* TAKVİM TUVALİ */}
      <div className="flex-1 w-full rounded-2xl border border-bunker-800 bg-bunker-950 overflow-hidden shadow-xl p-2 min-h-[600px]">
        <div className="tradingview-widget-container w-full h-full" ref={containerRef}>
          <div className="tradingview-widget-container__widget w-full h-full" />
        </div>
      </div>
    </div>
  );
}
