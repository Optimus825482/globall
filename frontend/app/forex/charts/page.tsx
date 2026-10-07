"use client";

import React, { useState, useEffect } from "react";
import { useSearchParams } from "next/navigation";
import TradingViewWidget from "../components/TradingViewWidget";
import ForexNativeChart, { Timeframe } from "../components/ForexNativeChart";

const PAIRS = [
  { symbol: "EURUSD", tv: "FX:EURUSD", name: "EUR/USD", cat: "major" },
  { symbol: "GBPUSD", tv: "FX:GBPUSD", name: "GBP/USD", cat: "major" },
  { symbol: "USDJPY", tv: "FX:USDJPY", name: "USD/JPY", cat: "major" },
  { symbol: "XAUUSD", tv: "OANDA:XAUUSD", name: "XAU/USD (Altın)", cat: "commodity" },
  { symbol: "GBPJPY", tv: "FX:GBPJPY", name: "GBP/JPY", cat: "cross" },
  { symbol: "EURJPY", tv: "FX:EURJPY", name: "EUR/JPY", cat: "cross" },
  { symbol: "AUDUSD", tv: "FX:AUDUSD", name: "AUD/USD", cat: "major" },
  { symbol: "USDCAD", tv: "FX:USDCAD", name: "USD/CAD", cat: "major" },
  { symbol: "USDCHF", tv: "FX:USDCHF", name: "USD/CHF", cat: "major" },
  { symbol: "NZDUSD", tv: "FX:NZDUSD", name: "NZD/USD", cat: "major" },
  { symbol: "NAS100", tv: "FOREXCOM:NSXUSD", name: "Nasdaq 100", cat: "index" },
  { symbol: "US30", tv: "FOREXCOM:DJI", name: "Dow Jones 30", cat: "index" },
  { symbol: "BTCUSD", tv: "BINANCE:BTCUSDT", name: "BTC/USD", cat: "crypto" },
];

export default function ForexSingleChartPage() {
  const searchParams = useSearchParams();
  const initialSym = searchParams.get("symbol") || "EURUSD";

  const [selectedPair, setSelectedPair] = useState(
    PAIRS.find((p) => p.symbol === initialSym.toUpperCase()) || PAIRS[0]
  );
  const [viewEngine, setViewEngine] = useState<"native" | "tradingview">("native");
  const [interval, setInterval] = useState("15");

  useEffect(() => {
    const sym = searchParams.get("symbol");
    if (sym) {
      const clean = sym.toUpperCase().replace("/", "").replace("_", "");
      const match = PAIRS.find((p) => p.symbol === clean || p.tv.toUpperCase().includes(clean));
      if (match) setSelectedPair(match);
    }
  }, [searchParams]);

  return (
    <div className="space-y-4 pb-12 h-[calc(100vh-4rem)] flex flex-col font-mono">
      {/* ÜST PARİTE ÇUBUĞU */}
      <div className="flex flex-wrap items-center justify-between gap-3 p-3 rounded-xl bg-bunker-900/90 border border-bunker-800 shrink-0">
        <div className="flex items-center gap-1.5 overflow-x-auto pb-1 md:pb-0 max-w-full">
          {PAIRS.map((p) => (
            <button
              key={p.symbol}
              type="button"
              onClick={() => setSelectedPair(p)}
              className={`px-3 py-1.5 rounded-lg text-xs font-bold transition-all shrink-0 ${
                selectedPair.symbol === p.symbol
                  ? "bg-blue-500/20 text-blue-300 border border-blue-400/40 shadow-[0_0_10px_rgba(59,130,246,0.25)]"
                  : "bg-bunker-950/80 text-bunker-muted border border-bunker-800 hover:text-white"
              }`}
            >
              {p.name}
            </button>
          ))}
        </div>

        {/* GRAFİK MOTORU SEÇİCİSİ */}
        <div className="flex items-center gap-1 bg-bunker-950 p-1 rounded-lg border border-bunker-800 text-xs">
          <button
            type="button"
            onClick={() => setViewEngine("native")}
            className={`px-3 py-1 rounded-md font-bold transition-all flex items-center gap-1 ${
              viewEngine === "native"
                ? "bg-blue-600 text-white shadow-sm"
                : "text-bunker-muted hover:text-white"
            }`}
          >
            <span>✨</span>
            <span>Profesyonel Grafik Motoru</span>
          </button>
          <button
            type="button"
            onClick={() => setViewEngine("tradingview")}
            className={`px-3 py-1 rounded-md font-bold transition-all flex items-center gap-1 ${
              viewEngine === "tradingview"
                ? "bg-blue-600 text-white shadow-sm"
                : "text-bunker-muted hover:text-white"
            }`}
          >
            <span>🌐</span>
            <span>TradingView</span>
          </button>
        </div>
      </div>

      {/* GRAFİK GÖVDE ALANI */}
      <div className="flex-1 w-full rounded-2xl border border-bunker-800 bg-bunker-950 overflow-hidden shadow-2xl min-h-[550px] relative">
        {viewEngine === "native" ? (
          <ForexNativeChart
            symbol={selectedPair.symbol}
            displayName={selectedPair.name}
            category={selectedPair.cat}
            initialTimeframe="5m"
          />
        ) : (
          <div className="h-full w-full flex flex-col">
            <div className="p-2 bg-bunker-900 border-b border-bunker-800 flex items-center justify-between text-xs px-3">
              <span className="text-bunker-muted">TradingView Widget Görünümü ({selectedPair.tv})</span>
              <div className="flex items-center gap-1">
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
                    className={`px-2 py-0.5 rounded text-xs font-bold transition-all ${
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
            <div className="flex-1 w-full">
              <TradingViewWidget
                symbol={selectedPair.tv}
                interval={interval}
                hideSideToolbar={false}
                height="100%"
              />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
