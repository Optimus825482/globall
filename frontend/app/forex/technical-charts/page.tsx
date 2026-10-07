"use client";

import React, { useState } from "react";
import TradingViewWidget from "../components/TradingViewWidget";

interface SlotConfig {
  id: number;
  symbol: string;
  name: string;
  interval: string;
}

const AVAILABLE_FX = [
  { symbol: "FX:EURUSD", name: "EUR/USD" },
  { symbol: "FX:GBPUSD", name: "GBP/USD" },
  { symbol: "FX:USDJPY", name: "USD/JPY" },
  { symbol: "OANDA:XAUUSD", name: "XAU/USD (Altın)" },
  { symbol: "FX:AUDUSD", name: "AUD/USD" },
  { symbol: "FX:USDCAD", name: "USD/CAD" },
  { symbol: "FX:USDCHF", name: "USD/CHF" },
  { symbol: "FOREXCOM:NSXUSD", name: "Nasdaq 100" },
];

const INTERVALS = [
  { label: "1d", value: "1" },
  { label: "5d", value: "5" },
  { label: "15d", value: "15" },
  { label: "1s", value: "60" },
  { label: "4s", value: "240" },
  { label: "Gün", value: "D" },
];

export default function ForexTechnicalChartsPage() {
  const [slots, setSlots] = useState<SlotConfig[]>([
    { id: 1, symbol: "FX:EURUSD", name: "EUR/USD", interval: "15" },
    { id: 2, symbol: "FX:GBPUSD", name: "GBP/USD", interval: "15" },
    { id: 3, symbol: "FX:USDJPY", name: "USD/JPY", interval: "15" },
    { id: 4, symbol: "OANDA:XAUUSD", name: "XAU/USD (Altın)", interval: "15" },
  ]);

  const updateSlotSymbol = (id: number, symbol: string) => {
    const found = AVAILABLE_FX.find((f) => f.symbol === symbol);
    setSlots((prev) =>
      prev.map((s) =>
        s.id === id ? { ...s, symbol, name: found ? found.name : symbol } : s
      )
    );
  };

  const updateSlotInterval = (id: number, interval: string) => {
    setSlots((prev) =>
      prev.map((s) => (s.id === id ? { ...s, interval } : s))
    );
  };

  return (
    <div className="space-y-4 pb-16 min-h-[calc(100vh-4rem)] md:h-[calc(100vh-4rem)] flex flex-col overflow-y-auto">
      {/* BAŞLIK & KONTROLLER */}
      <div className="flex flex-wrap items-center justify-between gap-3 p-3 rounded-xl bg-bunker-900/80 border border-bunker-800">
        <div className="flex items-center gap-2.5">
          <span className="text-xl">🖥️</span>
          <div>
            <h1 className="font-mono text-sm font-bold text-white tracking-tight">
              FOREX 4'LÜ ÇOKLU TEKNİK EKRAN
            </h1>
            <p className="text-[11px] text-bunker-muted font-mono">
              Canlı TradingView Verisi · Majörler ve Emtialar
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() =>
              setSlots([
                { id: 1, symbol: "FX:EURUSD", name: "EUR/USD", interval: "15" },
                { id: 2, symbol: "FX:GBPUSD", name: "GBP/USD", interval: "15" },
                { id: 3, symbol: "FX:USDJPY", name: "USD/JPY", interval: "15" },
                { id: 4, symbol: "OANDA:XAUUSD", name: "XAU/USD (Altın)", interval: "15" },
              ])
            }
            className="px-2.5 py-1 rounded bg-blue-500/20 text-blue-300 border border-blue-400/30 text-xs font-mono font-bold hover:bg-blue-500/30 transition-all touch-target"
          >
            Varsayılan Majörler
          </button>
        </div>
      </div>

      {/* 4'LÜ GRAFİK GRID (2x2) */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3 flex-1">
        {slots.map((slot) => (
          <div
            key={slot.id}
            className="flex flex-col rounded-xl border border-bunker-800 bg-bunker-950 overflow-hidden shadow-lg h-full min-h-[380px]"
          >
            {/* Slot Başlık Çubuğu */}
            <div className="flex items-center justify-between px-3 py-2 bg-bunker-900/90 border-b border-bunker-800 font-mono text-xs">
              <div className="flex items-center gap-2">
                <span className="w-2 h-2 rounded-full bg-blue-400 animate-pulse" />
                <select
                  value={slot.symbol}
                  onChange={(e) => updateSlotSymbol(slot.id, e.target.value)}
                  className="bg-bunker-950 border border-bunker-700 rounded px-2 py-1 text-xs text-white font-bold outline-none focus:border-blue-400"
                >
                  {AVAILABLE_FX.map((fx) => (
                    <option key={fx.symbol} value={fx.symbol}>
                      {fx.name}
                    </option>
                  ))}
                </select>
              </div>

              {/* Zaman Dilimi Seçici */}
              <div className="flex items-center gap-1">
                {INTERVALS.map((int) => (
                  <button
                    key={int.value}
                    type="button"
                    onClick={() => updateSlotInterval(slot.id, int.value)}
                    className={`px-1.5 py-0.5 rounded text-[10px] font-bold transition-all ${
                      slot.interval === int.value
                        ? "bg-blue-500 text-white"
                        : "text-bunker-muted hover:text-white hover:bg-bunker-800"
                    }`}
                  >
                    {int.label}
                  </button>
                ))}
              </div>
            </div>

            {/* TradingView Grafiği */}
            <div className="flex-1 w-full h-full min-h-[340px]">
              <TradingViewWidget
                symbol={slot.symbol}
                interval={slot.interval}
                hideSideToolbar={true}
              />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
