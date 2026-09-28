"use client";

import React, { useState, useEffect } from "react";
import { useSearchParams } from "next/navigation";
import TradingViewWidget from "../components/TradingViewWidget";

const PAIRS = [
  { symbol: "EURUSD", tv: "FX:EURUSD", name: "EUR/USD", cat: "major" },
  { symbol: "GBPUSD", tv: "FX:GBPUSD", name: "GBP/USD", cat: "major" },
  { symbol: "USDJPY", tv: "FX:USDJPY", name: "USD/JPY", cat: "major" },
  { symbol: "XAUUSD", tv: "OANDA:XAUUSD", name: "XAU/USD (Altın)", cat: "commodity" },
  { symbol: "AUDUSD", tv: "FX:AUDUSD", name: "AUD/USD", cat: "major" },
  { symbol: "USDCAD", tv: "FX:USDCAD", name: "USD/CAD", cat: "major" },
  { symbol: "USDCHF", tv: "FX:USDCHF", name: "USD/CHF", cat: "major" },
  { symbol: "NZDUSD", tv: "FX:NZDUSD", name: "NZD/USD", cat: "major" },
  { symbol: "USOIL", tv: "TVC:USOIL", name: "WTI Ham Petrol", cat: "commodity" },
  { symbol: "SPX500", tv: "FOREXCOM:SPXUSD", name: "S&P 500", cat: "index" },
];

export default function ForexSingleChartPage() {
  const searchParams = useSearchParams();
  const initialSym = searchParams.get("symbol") || "EURUSD";

  const [selectedPair, setSelectedPair] = useState(
    PAIRS.find((p) => p.symbol === initialSym.toUpperCase()) || PAIRS[0]
  );
  const [interval, setInterval] = useState("15");

  useEffect(() => {
    const sym = searchParams.get("symbol");
    if (sym) {
      const match = PAIRS.find((p) => p.symbol === sym.toUpperCase());
      if (match) setSelectedPair(match);
    }
  }, [searchParams]);

  return (
    <div className="space-y-4 pb-12 h-[calc(100vh-4rem)] flex flex-col">
      {/* ÜST PARİTE ÇUBUĞU */}
      <div className="flex flex-wrap items-center justify-between gap-3 p-3 rounded-xl bg-bunker-900/80 border border-bunker-800">
        <div className="flex items-center gap-1.5 overflow-x-auto pb-1 md:pb-0">
          {PAIRS.map((p) => (
            <button
              key={p.symbol}
              type="button"
              onClick={() => setSelectedPair(p)}
              className={`px-3 py-1.5 rounded-lg font-mono text-xs font-bold transition-all shrink-0 ${
                selectedPair.symbol === p.symbol
                  ? "bg-blue-500/20 text-blue-300 border border-blue-400/40 shadow-[0_0_10px_rgba(59,130,246,0.25)]"
                  : "bg-bunker-950/80 text-bunker-muted border border-bunker-800 hover:text-white"
              }`}
            >
              {p.name}
            </button>
          ))}
        </div>

        {/* Zaman Dilimleri */}
        <div className="flex items-center gap-1 font-mono text-xs">
          {[
            { label: "1d", val: "1" },
            { label: "5d", val: "5" },
            { label: "15d", val: "15" },
            { label: "1s", val: "60" },
            { label: "4s", val: "240" },
            { label: "Gün", val: "D" },
          ].map((int) => (
            <button
              key={int.val}
              type="button"
              onClick={() => setInterval(int.val)}
              className={`px-2 py-1 rounded text-xs font-bold transition-all ${
                interval === int.val
                  ? "bg-blue-500 text-white"
                  : "text-bunker-muted hover:text-white hover:bg-bunker-800"
              }`}
            >
              {int.label}
            </button>
          ))}
        </div>
      </div>

      {/* DETAYLI GRAFİK TUVALİ */}
      <div className="flex-1 w-full rounded-2xl border border-bunker-800 bg-bunker-950 overflow-hidden shadow-2xl min-h-[550px]">
        <TradingViewWidget
          symbol={selectedPair.tv}
          interval={interval}
          hideSideToolbar={false}
          height="100%"
        />
      </div>
    </div>
  );
}
