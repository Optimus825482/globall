"use client";

import React, { useState, useEffect } from "react";
import ForexNativeChart, { Timeframe } from "../components/ForexNativeChart";
import TradingViewWidget from "../components/TradingViewWidget";

interface SlotConfig {
  id: number;
  symbol: string;
  name: string;
  category: string;
  timeframe: Timeframe;
  tvSymbol: string;
}

const AVAILABLE_FX = [
  { symbol: "EURUSD", name: "EUR/USD", cat: "major", tv: "FX:EURUSD" },
  { symbol: "GBPUSD", name: "GBP/USD", cat: "major", tv: "FX:GBPUSD" },
  { symbol: "USDJPY", name: "USD/JPY", cat: "major", tv: "FX:USDJPY" },
  { symbol: "XAUUSD", name: "XAU/USD (Altın)", cat: "commodity", tv: "OANDA:XAUUSD" },
  { symbol: "GBPJPY", name: "GBP/JPY", cat: "cross", tv: "FX:GBPJPY" },
  { symbol: "EURJPY", name: "EUR/JPY", cat: "cross", tv: "FX:EURJPY" },
  { symbol: "AUDUSD", name: "AUD/USD", cat: "major", tv: "FX:AUDUSD" },
  { symbol: "USDCAD", name: "USD/CAD", cat: "major", tv: "FX:USDCAD" },
  { symbol: "USDCHF", name: "USD/CHF", cat: "major", tv: "FX:USDCHF" },
  { symbol: "NZDUSD", name: "NZD/USD", cat: "major", tv: "FX:NZDUSD" },
  { symbol: "NAS100", name: "Nasdaq 100", cat: "index", tv: "FOREXCOM:NSXUSD" },
  { symbol: "US30", name: "Dow Jones 30", cat: "index", tv: "FOREXCOM:DJI" },
  { symbol: "BTCUSD", name: "BTC/USD", cat: "crypto", tv: "BINANCE:BTCUSDT" },
];

const DEFAULT_SLOTS: SlotConfig[] = [
  { id: 1, symbol: "EURUSD", name: "EUR/USD", category: "major", timeframe: "5m", tvSymbol: "FX:EURUSD" },
  { id: 2, symbol: "GBPUSD", name: "GBP/USD", category: "major", timeframe: "5m", tvSymbol: "FX:GBPUSD" },
  { id: 3, symbol: "USDJPY", name: "USD/JPY", category: "major", timeframe: "5m", tvSymbol: "FX:USDJPY" },
  { id: 4, symbol: "XAUUSD", name: "XAU/USD (Altın)", category: "commodity", timeframe: "5m", tvSymbol: "OANDA:XAUUSD" },
];

type LayoutMode = "grid4" | "split2_h" | "split2_v" | "single";
type EngineType = "native" | "tradingview";

export default function ForexTechnicalChartsPage() {
  const [slots, setSlots] = useState<SlotConfig[]>(DEFAULT_SLOTS);
  const [layout, setLayout] = useState<LayoutMode>("grid4");
  const [maximizedSlotId, setMaximizedSlotId] = useState<number | null>(null);
  const [chartEngine, setChartEngine] = useState<EngineType>("native");

  const updateSlotSymbol = (slotId: number, symbol: string) => {
    const found = AVAILABLE_FX.find((f) => f.symbol === symbol);
    if (!found) return;
    setSlots((prev) =>
      prev.map((s) =>
        s.id === slotId
          ? {
              ...s,
              symbol: found.symbol,
              name: found.name,
              category: found.cat,
              tvSymbol: found.tv,
            }
          : s
      )
    );
  };

  const updateSlotTimeframe = (slotId: number, tf: Timeframe) => {
    setSlots((prev) =>
      prev.map((s) => (s.id === slotId ? { ...s, timeframe: tf } : s))
    );
  };

  const applyPreset = (presetName: "majors" | "metals_indices" | "jpy_crosses" | "commodity_fx") => {
    if (presetName === "majors") {
      setSlots([
        { id: 1, symbol: "EURUSD", name: "EUR/USD", category: "major", timeframe: "5m", tvSymbol: "FX:EURUSD" },
        { id: 2, symbol: "GBPUSD", name: "GBP/USD", category: "major", timeframe: "5m", tvSymbol: "FX:GBPUSD" },
        { id: 3, symbol: "USDJPY", name: "USD/JPY", category: "major", timeframe: "5m", tvSymbol: "FX:USDJPY" },
        { id: 4, symbol: "XAUUSD", name: "XAU/USD (Altın)", category: "commodity", timeframe: "5m", tvSymbol: "OANDA:XAUUSD" },
      ]);
    } else if (presetName === "metals_indices") {
      setSlots([
        { id: 1, symbol: "XAUUSD", name: "XAU/USD (Altın)", category: "commodity", timeframe: "5m", tvSymbol: "OANDA:XAUUSD" },
        { id: 2, symbol: "NAS100", name: "Nasdaq 100", category: "index", timeframe: "5m", tvSymbol: "FOREXCOM:NSXUSD" },
        { id: 3, symbol: "US30", name: "Dow Jones 30", category: "index", timeframe: "5m", tvSymbol: "FOREXCOM:DJI" },
        { id: 4, symbol: "BTCUSD", name: "BTC/USD", category: "crypto", timeframe: "5m", tvSymbol: "BINANCE:BTCUSDT" },
      ]);
    } else if (presetName === "jpy_crosses") {
      setSlots([
        { id: 1, symbol: "GBPJPY", name: "GBP/JPY", category: "cross", timeframe: "5m", tvSymbol: "FX:GBPJPY" },
        { id: 2, symbol: "EURJPY", name: "EUR/JPY", category: "cross", timeframe: "5m", tvSymbol: "FX:EURJPY" },
        { id: 3, symbol: "USDJPY", name: "USD/JPY", category: "major", timeframe: "5m", tvSymbol: "FX:USDJPY" },
        { id: 4, symbol: "EURUSD", name: "EUR/USD", category: "major", timeframe: "5m", tvSymbol: "FX:EURUSD" },
      ]);
    } else if (presetName === "commodity_fx") {
      setSlots([
        { id: 1, symbol: "XAUUSD", name: "XAU/USD (Altın)", category: "commodity", timeframe: "5m", tvSymbol: "OANDA:XAUUSD" },
        { id: 2, symbol: "AUDUSD", name: "AUD/USD", category: "major", timeframe: "5m", tvSymbol: "FX:AUDUSD" },
        { id: 3, symbol: "USDCAD", name: "USD/CAD", category: "major", timeframe: "5m", tvSymbol: "FX:USDCAD" },
        { id: 4, symbol: "NZDUSD", name: "NZD/USD", category: "major", timeframe: "5m", tvSymbol: "FX:NZDUSD" },
      ]);
    }
  };

  const applyGlobalTimeframe = (tf: Timeframe) => {
    setSlots((prev) => prev.map((s) => ({ ...s, timeframe: tf })));
  };

  // Görünür slotları belirle
  const visibleSlots = React.useMemo(() => {
    if (maximizedSlotId !== null) {
      return slots.filter((s) => s.id === maximizedSlotId);
    }
    if (layout === "single") {
      return [slots[0]];
    }
    if (layout === "split2_h" || layout === "split2_v") {
      return slots.slice(0, 2);
    }
    return slots.slice(0, 4);
  }, [slots, layout, maximizedSlotId]);

  // Grid CSS sınıfı
  const gridClass = React.useMemo(() => {
    if (maximizedSlotId !== null || layout === "single") {
      return "grid-cols-1";
    }
    if (layout === "split2_h") {
      return "grid-cols-1 lg:grid-cols-2";
    }
    if (layout === "split2_v") {
      return "grid-cols-1";
    }
    return "grid-cols-1 lg:grid-cols-2";
  }, [layout, maximizedSlotId]);

  return (
    <div className="space-y-3 pb-12 min-h-[calc(100vh-4rem)] flex flex-col font-mono">
      {/* ÜST BAŞLIK & KONTROL MERKEZİ */}
      <div className="p-3 rounded-2xl bg-bunker-900/95 border border-bunker-800 flex flex-wrap items-center justify-between gap-3 shrink-0 shadow-lg">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-blue-500/20 border border-blue-400/40 flex items-center justify-center text-xl shadow-[0_0_12px_rgba(59,130,246,0.3)] shrink-0">
            🖥️
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-base font-bold text-white tracking-tight">
                FOREX ÇOKLU TEKNİK GRAFİK EKRANI
              </h1>
              <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-blue-500/20 text-blue-300 border border-blue-400/30">
                {chartEngine === "native" ? "⚡ YERLİ MOTOR (LIGHTWEIGHT)" : "🌐 TRADINGVIEW"}
              </span>
            </div>
            <p className="text-[11px] text-bunker-muted mt-0.5">
              Yerli motorla anlık mumlar; varsayılan Bollinger Bands + MACD alt paneli
            </p>
          </div>
        </div>

        {/* MOTOR SEÇİCİ & HAZIR ŞABLONLAR */}
        <div className="flex flex-wrap items-center gap-2 text-xs">
          
          {/* Motor Seçici Toggle */}
          <div className="flex items-center bg-bunker-950 p-1 rounded-xl border border-bunker-800">
            <button
              type="button"
              onClick={() => setChartEngine("native")}
              className={`px-3 py-1 rounded-lg font-bold transition-all flex items-center gap-1.5 ${
                chartEngine === "native"
                  ? "bg-blue-600 text-white shadow-[0_0_10px_rgba(37,99,235,0.4)]"
                  : "text-bunker-muted hover:text-white"
              }`}
            >
              <span>✨</span>
              <span>Yerli Grafik (Önerilen)</span>
            </button>
            <button
              type="button"
              onClick={() => setChartEngine("tradingview")}
              className={`px-3 py-1 rounded-lg font-bold transition-all flex items-center gap-1.5 ${
                chartEngine === "tradingview"
                  ? "bg-blue-600 text-white shadow-[0_0_10px_rgba(37,99,235,0.4)]"
                  : "text-bunker-muted hover:text-white"
              }`}
            >
              <span>🌐</span>
              <span>TradingView</span>
            </button>
          </div>

          {/* Yerleşim Düzeni Seçici */}
          <div className="flex items-center bg-bunker-950 p-1 rounded-xl border border-bunker-800">
            <button
              type="button"
              onClick={() => { setLayout("grid4"); setMaximizedSlotId(null); }}
              className={`px-2.5 py-1 rounded-lg font-bold transition-all ${
                layout === "grid4" && maximizedSlotId === null
                  ? "bg-bunker-800 text-white"
                  : "text-bunker-muted hover:text-white"
              }`}
              title="4'lü Grid (2x2)"
            >
              ⊞ 4'lü
            </button>
            <button
              type="button"
              onClick={() => { setLayout("split2_h"); setMaximizedSlotId(null); }}
              className={`px-2.5 py-1 rounded-lg font-bold transition-all ${
                layout === "split2_h" && maximizedSlotId === null
                  ? "bg-bunker-800 text-white"
                  : "text-bunker-muted hover:text-white"
              }`}
              title="2'li Yan Yana"
            >
              ◫ 2'li
            </button>
            <button
              type="button"
              onClick={() => { setLayout("single"); setMaximizedSlotId(null); }}
              className={`px-2.5 py-1 rounded-lg font-bold transition-all ${
                layout === "single" || maximizedSlotId !== null
                  ? "bg-bunker-800 text-white"
                  : "text-bunker-muted hover:text-white"
              }`}
              title="Tekli Tam Ekran"
            >
              ▢ Tekli
            </button>
          </div>
        </div>
      </div>

      {/* HIZLI ŞABLON & TOPLU ZAMAN ÇUBUĞU */}
      <div className="px-3.5 py-2 rounded-xl bg-bunker-900/80 border border-bunker-800/80 flex flex-wrap items-center justify-between gap-3 text-xs shrink-0">
        <div className="flex items-center gap-1.5 overflow-x-auto">
          <span className="text-[11px] text-bunker-muted mr-1">Şablonlar:</span>
          <button
            type="button"
            onClick={() => applyPreset("majors")}
            className="px-2.5 py-1 rounded-lg bg-bunker-950 border border-bunker-800 text-bunker-300 font-bold hover:text-white hover:border-bunker-700 transition-all"
          >
            🏛️ Majörler
          </button>
          <button
            type="button"
            onClick={() => applyPreset("metals_indices")}
            className="px-2.5 py-1 rounded-lg bg-bunker-950 border border-bunker-800 text-bunker-300 font-bold hover:text-white hover:border-bunker-700 transition-all"
          >
            🥇 Altın &amp; Endeks
          </button>
          <button
            type="button"
            onClick={() => applyPreset("jpy_crosses")}
            className="px-2.5 py-1 rounded-lg bg-bunker-950 border border-bunker-800 text-bunker-300 font-bold hover:text-white hover:border-bunker-700 transition-all"
          >
            ⚡ JPY Krosları
          </button>
          <button
            type="button"
            onClick={() => applyPreset("commodity_fx")}
            className="px-2.5 py-1 rounded-lg bg-bunker-950 border border-bunker-800 text-bunker-300 font-bold hover:text-white hover:border-bunker-700 transition-all"
          >
            🌍 Emtia &amp; Dolar
          </button>
        </div>

        {/* Toplu Periyot Değiştir */}
        <div className="flex items-center gap-1">
          <span className="text-[11px] text-bunker-muted mr-1">Tümünü Değiştir:</span>
          {(["1m", "5m", "15m", "1h", "4h"] as Timeframe[]).map((tf) => (
            <button
              key={tf}
              type="button"
              onClick={() => applyGlobalTimeframe(tf)}
              className="px-2 py-0.5 rounded bg-bunker-950 border border-bunker-800 text-[11px] text-bunker-muted font-bold hover:text-white hover:border-blue-400 transition-all"
            >
              {tf}
            </button>
          ))}
        </div>
      </div>

      {/* ÇOKLU GRAFİK GRID TUVALİ */}
      <div className={`grid ${gridClass} gap-3 flex-1 min-h-[600px]`}>
        {visibleSlots.map((slot) => {
          const isMaximized = maximizedSlotId === slot.id;
          return (
            <div
              key={slot.id}
              className="flex flex-col rounded-2xl border border-bunker-800 bg-bunker-950 overflow-hidden shadow-xl min-h-[460px] relative transition-all"
            >
              {/* Slot Başlık & Seçici Kontrolleri */}
              <div className="flex flex-wrap items-center justify-between px-3 py-2 bg-bunker-900/90 border-b border-bunker-800 text-xs shrink-0 gap-2">
                
                {/* Sembol Açılır Menüsü */}
                <div className="flex items-center gap-2">
                  <span className="w-2 h-2 rounded-full bg-blue-400 animate-pulse" />
                  <select
                    value={slot.symbol}
                    onChange={(e) => updateSlotSymbol(slot.id, e.target.value)}
                    className="bg-bunker-950 border border-bunker-700 rounded-lg px-2.5 py-1 text-xs text-white font-bold outline-none focus:border-blue-400 shadow-inner"
                  >
                    {AVAILABLE_FX.map((fx) => (
                      <option key={fx.symbol} value={fx.symbol}>
                        {fx.name} ({fx.cat.toUpperCase()})
                      </option>
                    ))}
                  </select>
                </div>

                {/* Periyot & Büyüt/Küçült Butonları */}
                <div className="flex items-center gap-1.5">
                  {(["1m", "5m", "15m", "30m", "1h", "4h"] as Timeframe[]).map((tf) => (
                    <button
                      key={tf}
                      type="button"
                      onClick={() => updateSlotTimeframe(slot.id, tf)}
                      className={`px-1.5 py-0.5 rounded text-[11px] font-bold transition-all ${
                        slot.timeframe === tf
                          ? "bg-blue-600 text-white"
                          : "text-bunker-muted hover:text-white hover:bg-bunker-800"
                      }`}
                    >
                      {tf}
                    </button>
                  ))}

                  <button
                    type="button"
                    onClick={() => setMaximizedSlotId(isMaximized ? null : slot.id)}
                    className={`ml-1 px-2 py-0.5 rounded border text-xs font-bold transition-all ${
                      isMaximized
                        ? "bg-amber-500/20 text-amber-300 border-amber-400/40"
                        : "bg-bunker-900 text-bunker-muted border-bunker-800 hover:text-white"
                    }`}
                    title={isMaximized ? "Küçült" : "Tam Ekran Yap"}
                  >
                    {isMaximized ? "✕ Küçült" : "⛶ Büyüt"}
                  </button>
                </div>
              </div>

              {/* Slot Grafik Gövdesi */}
              <div className="flex-1 w-full h-full relative">
                {chartEngine === "native" ? (
                  <ForexNativeChart
                    symbol={slot.symbol}
                    displayName={slot.name}
                    category={slot.category}
                    initialTimeframe={slot.timeframe}
                    className="h-full"
                  />
                ) : (
                  <div className="h-full w-full">
                    <TradingViewWidget
                      symbol={slot.tvSymbol}
                      interval={slot.timeframe === "1h" ? "60" : slot.timeframe === "4h" ? "240" : slot.timeframe === "1d" ? "D" : slot.timeframe.replace("m", "")}
                      hideSideToolbar={true}
                      height="100%"
                    />
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
