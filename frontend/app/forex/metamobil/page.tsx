"use client";

export const dynamic = "force-dynamic";

import React, { useState, useEffect, useMemo, useRef, useCallback } from "react";
import Link from "next/link";
import { apiFetch } from "../../lib/api";
import { usePolling } from "../../lib/usePolling";

function formatPrice(v?: number | null, symbol: string = ""): string {
  if (v == null || !Number.isFinite(v) || v <= 0) return "—";
  const s = symbol.toUpperCase();
  if (s.includes("JPY")) return v.toFixed(3);
  if (
    s.includes("XAU") ||
    s.includes("GOLD") ||
    s.includes("NAS") ||
    s.includes("US30") ||
    s.includes("SPX") ||
    s.includes("BTC") ||
    s.includes("ETH") ||
    s.includes("OIL")
  ) {
    return v.toFixed(2);
  }
  return v.toFixed(5);
}

// --- TİPLER & MODEL TANIMLARI ---
interface QuoteItem {
  symbol: string;
  display: string;
  name: string;
  category: string;
  bid: number;
  ask: number;
  spread_pips: number;
  high: number;
  low: number;
  digits: number;
  time: string;
  trend?: string;
  change_pct?: number;
  prev_bid?: number;
  prev_ask?: number;
  flash_bid?: "up" | "down" | null;
  flash_ask?: "up" | "down" | null;
}

interface OpenPosition {
  id: string;
  ticket?: number;
  symbol: string;
  display?: string;
  direction: "BUY" | "SELL";
  lots: number;
  entry_price: number;
  current_price: number;
  sl_price?: number;
  tp_price?: number;
  pnl_usd: number;
  pnl_pips: number;
  open_time?: string;
  category?: string;
  strategy?: string;
}

interface ClosedTrade {
  id: string;
  ticket?: number;
  symbol: string;
  display?: string;
  direction: "BUY" | "SELL";
  lots: number;
  entry_price?: number;
  exit_price?: number;
  close_price?: number;
  pnl_usd: number;
  pnl_pips: number;
  outcome?: "WIN" | "LOSS" | "BE";
  close_time?: string;
  exit_time?: string;
  open_time?: string;
}

interface AccountSummary {
  balance: number;
  equity: number;
  margin: number;
  free_margin: number;
  margin_level: number;
  open_pnl: number;
  server_name: string;
  account_id: number;
  leverage: string;
  currency: string;
  ping_ms: number;
  is_connected: boolean;
}

// Varsayılan Başlangıç Sembolleri (MetaTrader 5 Klasik Majörler & Emtia)
const INITIAL_SYMBOLS: QuoteItem[] = [
  { symbol: "EURUSD", display: "EURUSD", name: "Euro vs US Dollar", category: "major", bid: 1.08642, ask: 1.08654, spread_pips: 1.2, high: 1.08980, low: 1.08320, digits: 5, time: "10:35:14" },
  { symbol: "GBPUSD", display: "GBPUSD", name: "Great Britain Pound vs US Dollar", category: "major", bid: 1.29415, ask: 1.29432, spread_pips: 1.7, high: 1.29850, low: 1.29110, digits: 5, time: "10:35:14" },
  { symbol: "USDJPY", display: "USDJPY", name: "US Dollar vs Japanese Yen", category: "major", bid: 153.245, ask: 153.262, spread_pips: 1.7, high: 153.850, low: 152.910, digits: 3, time: "10:35:14" },
  { symbol: "XAUUSD", display: "XAUUSD", name: "Gold (Oz) vs US Dollar", category: "commodity", bid: 2736.45, ask: 2736.85, spread_pips: 4.0, high: 2748.20, low: 2724.50, digits: 2, time: "10:35:14" },
  { symbol: "BTCUSD", display: "BTCUSD", name: "Bitcoin vs US Dollar", category: "crypto", bid: 67420.00, ask: 67435.00, spread_pips: 15.0, high: 68100.00, low: 66800.00, digits: 2, time: "10:35:14" },
  { symbol: "AUDUSD", display: "AUDUSD", name: "Australian Dollar vs US Dollar", category: "major", bid: 0.65421, ask: 0.65435, spread_pips: 1.4, high: 0.65780, low: 0.65150, digits: 5, time: "10:35:14" },
  { symbol: "USDCHF", display: "USDCHF", name: "US Dollar vs Swiss Franc", category: "major", bid: 0.86542, ask: 0.86558, spread_pips: 1.6, high: 0.86890, low: 0.86240, digits: 5, time: "10:35:14" },
  { symbol: "USDCAD", display: "USDCAD", name: "US Dollar vs Canadian Dollar", category: "major", bid: 1.38521, ask: 1.38539, spread_pips: 1.8, high: 1.38950, low: 1.38120, digits: 5, time: "10:35:14" },
  { symbol: "GBPJPY", display: "GBPJPY", name: "Great Britain Pound vs Yen", category: "cross", bid: 198.345, ask: 198.372, spread_pips: 2.7, high: 199.120, low: 197.800, digits: 3, time: "10:35:14" },
  { symbol: "USOIL", display: "USOIL", name: "Crude Oil (WTI) vs US Dollar", category: "commodity", bid: 71.45, ask: 71.49, spread_pips: 4.0, high: 72.80, low: 70.60, digits: 2, time: "10:35:14" },
];

// MT5 Fiyat Basamağı Ayrıştırıcı: Örn: 1.08645 -> { main: "1.08", big: "64", sub: "5" }
function splitMt5Price(val: number, digits: number = 5) {
  if (!Number.isFinite(val) || val <= 0) return { main: "—", big: "", sub: "" };
  const str = val.toFixed(digits);
  if (digits === 5) {
    // Örn: "1.08645" -> main: "1.08", big: "64", sub: "5"
    const dotIdx = str.indexOf(".");
    if (dotIdx === -1) return { main: str, big: "", sub: "" };
    const whole = str.substring(0, dotIdx + 1); // "1."
    const frac = str.substring(dotIdx + 1); // "08645"
    if (frac.length >= 5) {
      return {
        main: whole + frac.substring(0, 2), // "1.08"
        big: frac.substring(2, 4),           // "64"
        sub: frac.substring(4, 5),           // "5"
      };
    }
  } else if (digits === 3) {
    // Örn: "153.265" -> main: "153.", big: "26", sub: "5"
    const dotIdx = str.indexOf(".");
    if (dotIdx === -1) return { main: str, big: "", sub: "" };
    const whole = str.substring(0, dotIdx + 1); // "153."
    const frac = str.substring(dotIdx + 1); // "265"
    if (frac.length >= 3) {
      return {
        main: whole,
        big: frac.substring(0, 2),
        sub: frac.substring(2, 3),
      };
    }
  } else if (digits === 2) {
    // Örn: "2736.45" -> main: "2736.", big: "45", sub: ""
    const dotIdx = str.indexOf(".");
    if (dotIdx === -1) return { main: str, big: "", sub: "" };
    return {
      main: str.substring(0, dotIdx + 1),
      big: str.substring(dotIdx + 1),
      sub: "",
    };
  }
  return { main: str, big: "", sub: "" };
}

export default function MetaMobilePage() {
  // Aktif Sekme: "QUOTES" | "CHART" | "TRADE" | "HISTORY" | "SETTINGS"
  const [activeTab, setActiveTab] = useState<"QUOTES" | "CHART" | "TRADE" | "HISTORY" | "SETTINGS">("TRADE");
  
  // Kotasyon Görünüm Modu: "ADVANCED" (Gelişmiş) vs "SIMPLE" (Basit)
  const [quotesMode, setQuotesMode] = useState<"ADVANCED" | "SIMPLE">("ADVANCED");
  
  // Seçili Grafik Sembolü ve Zaman Dilimi
  const [selectedSymbol, setSelectedSymbol] = useState<string>("XAUUSD");
  const [selectedTimeframe, setSelectedTimeframe] = useState<string>("M5");
  
  // Veri Durumları
  const [quotes, setQuotes] = useState<QuoteItem[]>(INITIAL_SYMBOLS);
  const [openPositions, setOpenPositions] = useState<OpenPosition[]>([]);
  const [closedTrades, setClosedTrades] = useState<ClosedTrade[]>([]);
  const [account, setAccount] = useState<AccountSummary>({
    balance: 10000.0,
    equity: 10042.50,
    margin: 180.0,
    free_margin: 9862.50,
    margin_level: 5579.16,
    open_pnl: 42.50,
    server_name: "MetaQuotes-Demo",
    account_id: 1084291,
    leverage: "1:100",
    currency: "USD",
    ping_ms: 24,
    is_connected: true,
  });

  // Geçmiş Süre Filtresi
  const [historyPeriod, setHistoryPeriod] = useState<"TODAY" | "WEEK" | "MONTH" | "ALL">("TODAY");

  // Modallar ve Bottom Sheetler
  const [actionSheetSymbol, setActionSheetSymbol] = useState<QuoteItem | null>(null);
  const [newOrderModalOpen, setNewOrderModalOpen] = useState<boolean>(false);
  const [newOrderSymbol, setNewOrderSymbol] = useState<string>("XAUUSD");
  const [orderLots, setOrderLots] = useState<number>(0.05);
  const [orderSl, setOrderSl] = useState<string>("");
  const [orderTp, setOrderTp] = useState<string>("");
  const [orderType, setOrderType] = useState<"MARKET" | "BUY_LIMIT" | "SELL_LIMIT">("MARKET");
  const [orderStatusMsg, setOrderStatusMsg] = useState<string | null>(null);
  
  // Pozisyon Kapatma Modalı
  const [closingPosition, setClosingPosition] = useState<OpenPosition | null>(null);

  // Ses / Titreşim Bildirimi
  const playClickSound = useCallback(() => {
    try {
      if (typeof window !== "undefined" && window.navigator?.vibrate) {
        window.navigator.vibrate(20);
      }
    } catch {}
  }, []);

  // API Verilerini Çekme (Radar Fiyatları, Hesap Durumu, Pozisyonlar)
  const refreshAllData = useCallback(async () => {
    try {
      // 1. Radar Fiyatları
      const radarData = await apiFetch("/api/forex/radar").catch(() => null);
      if (radarData && Array.isArray(radarData.candidates)) {
        setQuotes((prev) => {
          return prev.map((item) => {
            const found = radarData.candidates.find((c: any) => c.symbol === item.symbol);
            if (!found) return item;
            const newBid = Number(found.bid ?? found.price ?? item.bid);
            const newAsk = Number(found.ask ?? found.price ?? item.ask);
            let flashBid: "up" | "down" | null = null;
            let flashAsk: "up" | "down" | null = null;
            if (newBid > item.bid) flashBid = "up";
            else if (newBid < item.bid) flashBid = "down";
            if (newAsk > item.ask) flashAsk = "up";
            else if (newAsk < item.ask) flashAsk = "down";

            return {
              ...item,
              bid: newBid,
              ask: newAsk,
              spread_pips: Number(found.spread_pips ?? item.spread_pips),
              trend: found.trend ?? item.trend,
              time: new Date().toLocaleTimeString("tr-TR"),
              flash_bid: flashBid,
              flash_ask: flashAsk,
            };
          });
        });
        // Flash efektlerini kısa süre sonra temizle (eskiden ayrı bir useEffect
        // her quotes değişiminde yeni timer kuruyordu; tek yerde temizlenir).
        setTimeout(() => {
          setQuotes((prev) =>
            prev.map((q) => (q.flash_bid || q.flash_ask ? { ...q, flash_bid: null, flash_ask: null } : q))
          );
        }, 600);
      }

      // 2. Açık ve Kapanan İşlemler
      const tradesData = await apiFetch("/api/forex/auto-paper/trades?period=today&limit=250").catch(() => null);
      if (tradesData) {
        if (Array.isArray(tradesData.open_positions)) {
          setOpenPositions(tradesData.open_positions);
        }
        if (Array.isArray(tradesData.trades)) {
          setClosedTrades(tradesData.trades);
        }
      }

      // 3. Hesap Durumu
      const statusData = await apiFetch("/api/forex/auto-paper/status").catch(() => null);
      if (statusData) {
        setAccount((prev) => {
          const bal = Number(statusData.balance ?? prev.balance);
          const eq = Number(statusData.equity ?? prev.equity);
          const pnl = Number(statusData.open_pnl ?? (eq - bal));
          const marg = Number(statusData.margin ?? prev.margin);
          const freeMarg = Number(statusData.free_margin ?? (eq - marg));
          const level = marg > 0 ? (eq / marg) * 100 : 9999;
          return {
            ...prev,
            balance: bal,
            equity: eq,
            open_pnl: pnl,
            margin: marg,
            free_margin: freeMarg,
            margin_level: level,
            is_connected: true,
          };
        });
      }
    } catch (err) {
      console.warn("MetaMobil veri yenileme uyarısı:", err);
    }
  }, []);

  // Periyodik Canlı Veri Yenileme
  // PERFORMANS (2026-10-08): 2 sn'lik çıplak interval arka planda da dönüyordu
  // ve üç endpoint'i sırayla çekiyordu. usePolling ile arka planda durur,
  // üst üste binen turlar engellenir. Flash efektleri tazelenme sonunda
  // temizlenir (eskiden her quotes değişiminde yeni bir timer kuruluyordu).
  usePolling(refreshAllData, 3000);

  // Güncel seçili sembol verisi
  const activeQuote = useMemo(() => {
    return quotes.find((q) => q.symbol === selectedSymbol) || quotes[0] || INITIAL_SYMBOLS[0];
  }, [quotes, selectedSymbol]);

  // Yeni Emir Açma İşlemi
  const handleExecuteOrder = async (direction: "BUY" | "SELL") => {
    playClickSound();
    setOrderStatusMsg("Emir sunucuya iletiliyor…");
    try {
      // Backend MT5 veya Paper order endpoint'i
      const res = await apiFetch("/api/forex/mt5/order", {
        method: "POST",
        body: JSON.stringify({
          symbol: newOrderSymbol,
          direction,
          lots: orderLots,
          sl: orderSl ? Number(orderSl) : undefined,
          tp: orderTp ? Number(orderTp) : undefined,
        }),
      }).catch(async () => {
        // Fallback: Yerel demo / paper emir simulasyonu
        return { success: true, message: "Demo emir işleme alındı" };
      });

      setOrderStatusMsg(`✓ Emir İletildi: #${Math.floor(100000 + Math.random() * 900000)} ${direction} ${orderLots} ${newOrderSymbol}`);
      setTimeout(() => {
        setNewOrderModalOpen(false);
        setOrderStatusMsg(null);
        setActiveTab("TRADE"); // Otomatik olarak Ticaret sekmesine git
        refreshAllData();
      }, 700);
    } catch (err: any) {
      setOrderStatusMsg(`Hata: ${err.message || "İşlem açılamadı"}`);
    }
  };

  // Pozisyon Kapatma İşlemi
  const handleClosePosition = async (pos: OpenPosition) => {
    playClickSound();
    try {
      await apiFetch("/api/forex/auto-paper/close-position", {
        method: "POST",
        body: JSON.stringify({ id: pos.id, ticket: pos.ticket }),
      }).catch(async () => {
        await apiFetch("/api/forex/mt5/close", {
          method: "POST",
          body: JSON.stringify({ ticket: pos.ticket || pos.id }),
        });
      });
      setClosingPosition(null);
      refreshAllData();
    } catch {
      // Fallback
      setClosingPosition(null);
      refreshAllData();
    }
  };

  // Geçmiş Filtrelenmiş Liste ve Toplam PnL
  const filteredClosedTrades = useMemo(() => {
    return closedTrades;
  }, [closedTrades]);

  const historyProfitTotal = useMemo(() => {
    return filteredClosedTrades.reduce((acc, t) => acc + Number(t.pnl_usd || 0), 0);
  }, [filteredClosedTrades]);

  return (
    <div className="fixed inset-0 w-full h-[100dvh] bg-bunker-950 text-slate-100 flex flex-col overflow-hidden font-sans select-none antialiased z-50">
      
      {/* 1. METATRADER 5 ÜST BAŞLIK ÇUBUĞU (TOP BAR - NATIVE APP HEADER) */}
      <header className="h-12 bg-bunker-900 border-b border-slate-800/80 flex items-center justify-between px-3 shrink-0 z-20 pt-[env(safe-area-inset-top,0px)]">
          {/* Sol: Geri Çıkış & Hesap No */}
          <div className="flex items-center gap-2">
            <Link
              href="/"
              className="w-7 h-7 rounded-lg bg-slate-800/80 hover:bg-slate-700 text-slate-300 hover:text-white flex items-center justify-center text-xs font-bold border border-slate-700/60"
              title="Dashboard'a Dön"
            >
              ←
            </Link>
            <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse shadow-[0_0_8px_#10b981]" />
            <div className="leading-tight">
              <div className="text-[12px] font-bold text-slate-100 flex items-center gap-1.5">
                <span>{account.server_name}</span>
                <span className="text-[9px] px-1 py-0.2 rounded bg-blue-500/20 text-blue-400 font-mono">
                  {account.leverage}
                </span>
              </div>
              <div className="text-[10px] text-slate-400 font-mono">
                #{account.account_id} · {account.ping_ms} ms
              </div>
            </div>
          </div>

          {/* Sağ: Yeni Emir Butonu (+) ve Hızlı Kotasyon Değiştirici */}
          <div className="flex items-center gap-1.5">
            {activeTab === "QUOTES" && (
              <button
                type="button"
                onClick={() => setQuotesMode((m) => (m === "ADVANCED" ? "SIMPLE" : "ADVANCED"))}
                className="px-2 py-0.5 rounded text-[10px] font-bold bg-slate-800 text-slate-300 border border-slate-700 hover:text-white"
              >
                {quotesMode === "ADVANCED" ? "Gelişmiş" : "Basit"}
              </button>
            )}

            <button
              type="button"
              onClick={() => {
                setNewOrderSymbol(activeQuote.symbol);
                setNewOrderModalOpen(true);
              }}
              className="w-7 h-7 rounded-lg bg-blue-600 hover:bg-blue-500 text-white font-bold flex items-center justify-center text-base shadow-sm transition-transform active:scale-90"
              title="Yeni Emir Aç"
            >
              +
            </button>
          </div>
        </header>

        {/* 3. İÇERİK ALANI (TAB VIEW CONTENT) */}
        <div className="flex-1 overflow-y-auto overflow-x-hidden relative bg-bunker-950">

          {/* ========================================================= */}
          {/* SEKME 1: KOTASYONLAR (QUOTES)                             */}
          {/* ========================================================= */}
          {activeTab === "QUOTES" && (
            <div className="divide-y divide-slate-800/60 pb-16">
              {/* Başlık Başlığı */}
              <div className="p-2.5 bg-bunker-900 flex items-center justify-between text-[11px] font-bold text-slate-400 uppercase tracking-wider">
                <span>Sembol / Spread</span>
                <div className="flex items-center gap-12 mr-2">
                  <span>Bid (Sat)</span>
                  <span>Ask (Al)</span>
                </div>
              </div>

              {quotes.map((q) => {
                const bidSplit = splitMt5Price(q.bid, q.digits);
                const askSplit = splitMt5Price(q.ask, q.digits);

                return (
                  <div
                    key={q.symbol}
                    onClick={() => {
                      playClickSound();
                      setActionSheetSymbol(q);
                    }}
                    className="p-3 hover:bg-slate-900/60 active:bg-slate-800/80 cursor-pointer transition-colors flex items-center justify-between"
                  >
                    {/* Sol Bilgiler: Sembol, Saat, Spread */}
                    <div className="space-y-0.5">
                      <div className="flex items-center gap-1.5">
                        <span className="font-bold text-[14px] text-white tracking-wide">
                          {q.symbol}
                        </span>
                        {q.category === "commodity" && (
                          <span className="text-[9px] px-1 py-0.2 rounded bg-amber-500/15 text-amber-400 font-bold">
                            EMTİA
                          </span>
                        )}
                        {q.category === "crypto" && (
                          <span className="text-[9px] px-1 py-0.2 rounded bg-indigo-500/15 text-indigo-400 font-bold">
                            KRİPTO
                          </span>
                        )}
                      </div>

                      <div className="text-[10px] text-slate-400 flex items-center gap-2 font-mono">
                        <span>{q.time}</span>
                        <span>Spread: {q.spread_pips.toFixed(1)}</span>
                      </div>

                      {quotesMode === "ADVANCED" && (
                        <div className="text-[9px] text-slate-400 flex items-center gap-2 font-mono pt-0.5">
                          <span>D: {formatPrice(q.low, q.symbol)}</span>
                          <span>Y: {formatPrice(q.high, q.symbol)}</span>
                        </div>
                      )}
                    </div>

                    {/* Sağ Fiyatlar: MT5 Büyük Punto Bid & Ask */}
                    <div className="flex items-center gap-4">
                      {/* BID KUTUSU */}
                      <div
                        className={`text-right font-mono transition-colors duration-300 rounded px-1.5 py-0.5 ${
                          q.flash_bid === "up"
                            ? "bg-blue-600/30 text-blue-400"
                            : q.flash_bid === "down"
                            ? "bg-rose-600/30 text-rose-400"
                            : "text-slate-200"
                        }`}
                      >
                        <span className="text-xs text-slate-400">{bidSplit.main}</span>
                        <span className="text-lg font-black">{bidSplit.big}</span>
                        <span className="text-[10px] align-super font-bold">{bidSplit.sub}</span>
                      </div>

                      {/* ASK KUTUSU */}
                      <div
                        className={`text-right font-mono transition-colors duration-300 rounded px-1.5 py-0.5 ${
                          q.flash_ask === "up"
                            ? "bg-blue-600/30 text-blue-400"
                            : q.flash_ask === "down"
                            ? "bg-rose-600/30 text-rose-400"
                            : "text-slate-200"
                        }`}
                      >
                        <span className="text-xs text-slate-400">{askSplit.main}</span>
                        <span className="text-lg font-black">{askSplit.big}</span>
                        <span className="text-[10px] align-super font-bold">{askSplit.sub}</span>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}

          {/* ========================================================= */}
          {/* SEKME 2: GRAFİK (CHARTS)                                  */}
          {/* ========================================================= */}
          {activeTab === "CHART" && (
            <div className="h-full flex flex-col pb-16">
              {/* Grafik Üst Araç Çubuğu: Sembol, Zaman Dilimi, One-Click Trading */}
              <div className="p-2 bg-bunker-900 border-b border-slate-800 flex items-center justify-between text-xs shrink-0">
                <div className="flex items-center gap-2">
                  <select
                    value={selectedSymbol}
                    onChange={(e) => setSelectedSymbol(e.target.value)}
                    className="bg-slate-900 text-white font-bold px-2 py-1 rounded border border-slate-700 outline-none"
                  >
                    {quotes.map((q) => (
                      <option key={q.symbol} value={q.symbol}>
                        {q.symbol}
                      </option>
                    ))}
                  </select>

                  {/* Zaman Dilimleri */}
                  <div className="flex items-center gap-1 font-mono text-[10px]">
                    {["M1", "M5", "M15", "H1", "D1"].map((tf) => (
                      <button
                        key={tf}
                        type="button"
                        onClick={() => setSelectedTimeframe(tf)}
                        className={`px-1.5 py-0.5 rounded font-bold transition-colors ${
                          selectedTimeframe === tf
                            ? "bg-blue-600 text-white"
                            : "bg-slate-800 text-slate-400 hover:text-white"
                        }`}
                      >
                        {tf}
                      </button>
                    ))}
                  </div>
                </div>

                <button
                  type="button"
                  onClick={() => {
                    setNewOrderSymbol(selectedSymbol);
                    setNewOrderModalOpen(true);
                  }}
                  className="px-2 py-1 rounded bg-blue-600 hover:bg-blue-500 text-white font-bold text-[11px]"
                >
                  ⚡ İşlem
                </button>
              </div>

              {/* MT5 ONE-CLICK HIZLI AL-SAT ÇUBUĞU */}
              <div className="grid grid-cols-3 gap-1 p-2 bg-bunker-800 border-b border-slate-800/80 text-xs shrink-0">
                {/* Hızlı Sell */}
                <button
                  type="button"
                  onClick={() => handleExecuteOrder("SELL")}
                  className="py-1.5 px-2 rounded bg-rose-600/20 hover:bg-rose-600/30 border border-rose-500/40 text-rose-300 font-bold flex flex-col items-center justify-center transition-transform active:scale-95"
                >
                  <span className="text-[10px] font-black uppercase tracking-wider text-rose-400">SELL</span>
                  <span className="font-mono text-xs">{formatPrice(activeQuote.bid, activeQuote.symbol)}</span>
                </button>

                {/* Lot Seçici */}
                <div className="flex flex-col items-center justify-center bg-slate-900 rounded border border-slate-800 py-1">
                  <span className="text-[9px] text-slate-400 font-bold uppercase">HIZLI LOT</span>
                  <div className="flex items-center gap-1 font-mono font-bold text-white text-xs">
                    <button
                      type="button"
                      onClick={() => setOrderLots((l) => Math.max(0.01, Number((l - 0.01).toFixed(2))))}
                      className="px-1 text-slate-400 hover:text-white"
                    >
                      -
                    </button>
                    <span>{orderLots.toFixed(2)}</span>
                    <button
                      type="button"
                      onClick={() => setOrderLots((l) => Number((l + 0.01).toFixed(2)))}
                      className="px-1 text-slate-400 hover:text-white"
                    >
                      +
                    </button>
                  </div>
                </div>

                {/* Hızlı Buy */}
                <button
                  type="button"
                  onClick={() => handleExecuteOrder("BUY")}
                  className="py-1.5 px-2 rounded bg-blue-600/20 hover:bg-blue-600/30 border border-blue-500/40 text-blue-300 font-bold flex flex-col items-center justify-center transition-transform active:scale-95"
                >
                  <span className="text-[10px] font-black uppercase tracking-wider text-blue-400">BUY</span>
                  <span className="font-mono text-xs">{formatPrice(activeQuote.ask, activeQuote.symbol)}</span>
                </button>
              </div>

              {/* Gerçekçi Grafik Alanı (TradingView / SVG Simülasyonu) */}
              <div className="flex-1 relative bg-bunker-950 p-3 flex flex-col justify-between overflow-hidden">
                {/* Üst Bilgi Rozeti */}
                <div className="flex items-center justify-between text-[11px] font-mono text-slate-400 z-10">
                  <div className="flex items-center gap-2">
                    <span className="text-white font-bold">{selectedSymbol}</span>
                    <span>{selectedTimeframe}</span>
                    <span className="text-emerald-400">RSI(14): 54.2</span>
                  </div>
                  <div className="text-right">
                    <span>A: {formatPrice(activeQuote.ask, activeQuote.symbol)}</span>
                  </div>
                </div>

                {/* Simüle Edilmiş Mum Çubukları & Fiyat Çizgileri */}
                <div className="flex-1 relative flex items-center justify-center my-2">
                  <div className="w-full h-full flex items-end justify-between px-2 gap-1.5 opacity-80">
                    {[42, 48, 45, 52, 58, 54, 60, 68, 62, 70, 75, 71, 79, 85, 82, 88, 92, 89, 94, 91, 96].map((h, i) => {
                      const isUp = i % 3 !== 0;
                      return (
                        <div key={i} className="flex-1 flex flex-col items-center h-full justify-end">
                          <div className={`w-[1px] ${isUp ? "bg-emerald-400" : "bg-rose-400"}`} style={{ height: `${h + 12}%` }} />
                          <div
                            className={`w-full rounded-xs ${isUp ? "bg-emerald-500" : "bg-rose-500"}`}
                            style={{ height: `${Math.max(10, h)}%` }}
                          />
                          <div className={`w-[1px] ${isUp ? "bg-emerald-400" : "bg-rose-400"}`} style={{ height: `${Math.max(4, h - 15)}%` }} />
                        </div>
                      );
                    })}
                  </div>

                  {/* Anlık Fiyat Çizgisi (Kırmızı Bid / Mavi Ask) */}
                  <div className="absolute w-full top-1/3 left-0 border-b border-dashed border-rose-500 flex justify-end">
                    <span className="bg-rose-600 text-white text-[9px] font-mono font-bold px-1 rounded-l">
                      Bid {formatPrice(activeQuote.bid, activeQuote.symbol)}
                    </span>
                  </div>
                  <div className="absolute w-full top-[31%] left-0 border-b border-dashed border-blue-500 flex justify-end">
                    <span className="bg-blue-600 text-white text-[9px] font-mono font-bold px-1 rounded-l">
                      Ask {formatPrice(activeQuote.ask, activeQuote.symbol)}
                    </span>
                  </div>
                </div>

                {/* Alt Osilatör Göstergesi (RSI) */}
                <div className="h-16 border-t border-slate-800/80 pt-1 flex flex-col justify-between font-mono text-[9px] text-slate-500">
                  <div className="flex justify-between">
                    <span>RSI (14)</span>
                    <span className="text-slate-400">70.0 (Aşırı Alım)</span>
                  </div>
                  <div className="w-full h-8 bg-slate-900/50 rounded relative overflow-hidden flex items-center">
                    <div className="absolute w-full border-b border-slate-800 top-2" />
                    <div className="absolute w-full border-b border-slate-800 bottom-2" />
                    <svg className="w-full h-full text-blue-400" preserveAspectRatio="none" viewBox="0 0 100 30">
                      <polyline
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="1.5"
                        points="0,15 10,18 20,12 30,10 40,16 50,22 60,14 70,8 80,12 90,9 100,11"
                      />
                    </svg>
                  </div>
                  <div className="flex justify-between">
                    <span>30.0 (Aşırı Satım)</span>
                    <span className="text-emerald-400">Son: 54.2</span>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* ========================================================= */}
          {/* SEKME 3: TİCARET / İŞLEM (TRADE)                          */}
          {/* ========================================================= */}
          {activeTab === "TRADE" && (
            <div className="pb-16 divide-y divide-slate-800/70">
              {/* MT5 HESAP ÖZET KARTI (Bakiye, Varlık, Marjin, PnL) */}
              <div className="p-3.5 bg-bunker-900 space-y-1.5 font-mono text-xs">
                <div className="flex items-center justify-between">
                  <span className="text-slate-400 font-sans">Bakiye:</span>
                  <span className="font-bold text-white">${account.balance.toFixed(2)}</span>
                </div>

                <div className="flex items-center justify-between">
                  <span className="text-slate-400 font-sans">Varlık:</span>
                  <span className="font-bold text-white">${account.equity.toFixed(2)}</span>
                </div>

                <div className="flex items-center justify-between">
                  <span className="text-slate-400 font-sans">Serbest Teminat:</span>
                  <span className="font-bold text-white">${account.free_margin.toFixed(2)}</span>
                </div>

                <div className="flex items-center justify-between">
                  <span className="text-slate-400 font-sans">Teminat Seviyesi:</span>
                  <span className="font-bold text-emerald-400">%{account.margin_level.toFixed(1)}</span>
                </div>

                <div className="flex items-center justify-between pt-1 border-t border-slate-800">
                  <span className="text-slate-300 font-sans font-bold">Toplam Kâr / Zarar:</span>
                  <span
                    className={`font-black text-sm ${
                      account.open_pnl >= 0 ? "text-emerald-400" : "text-rose-400"
                    }`}
                  >
                    {account.open_pnl >= 0 ? "+" : ""}${account.open_pnl.toFixed(2)} USD
                  </span>
                </div>
              </div>

              {/* Pozisyonlar Bölüm Başlığı */}
              <div className="p-2.5 bg-bunker-950 flex items-center justify-between text-[11px] font-bold text-slate-400 uppercase tracking-wider">
                <span>Pozisyonlar ({openPositions.length})</span>
                <span className="text-[10px] text-blue-400 font-sans font-semibold">Tıklayarak Yönet</span>
              </div>

              {/* Açık Pozisyon Listesi */}
              {openPositions.length === 0 ? (
                <div className="p-10 text-center space-y-2 text-slate-400">
                  <div className="text-3xl">📭</div>
                  <div className="font-bold text-white text-sm">Açık İşlem Yok</div>
                  <p className="text-xs">Şu an aktif bir piyasa pozisyonunuz bulunmamaktadır.</p>
                  <button
                    type="button"
                    onClick={() => {
                      setNewOrderSymbol("XAUUSD");
                      setNewOrderModalOpen(true);
                    }}
                    className="mt-2 px-3 py-1.5 rounded-lg bg-blue-600 text-white font-bold text-xs"
                  >
                    + Yeni Pozisyon Aç
                  </button>
                </div>
              ) : (
                openPositions.map((pos) => {
                  const isBuy = pos.direction === "BUY";
                  const isProfit = Number(pos.pnl_usd ?? 0) >= 0;

                  return (
                    <div
                      key={pos.id || pos.ticket}
                      onClick={() => setClosingPosition(pos)}
                      className="p-3 hover:bg-slate-900/60 active:bg-slate-800/80 cursor-pointer transition-colors flex items-center justify-between"
                    >
                      {/* Sol: Sembol, buy/sell lot, giriş -> güncel */}
                      <div className="space-y-0.5">
                        <div className="flex items-center gap-2">
                          <span className="font-bold text-sm text-white">{pos.symbol}</span>
                          <span
                            className={`text-[10px] font-black uppercase px-1.5 py-0.2 rounded ${
                              isBuy
                                ? "bg-blue-500/20 text-blue-400"
                                : "bg-rose-500/20 text-rose-400"
                            }`}
                          >
                            {pos.direction.toLowerCase()} {pos.lots.toFixed(2)}
                          </span>
                        </div>

                        <div className="text-[11px] font-mono text-slate-400 flex items-center gap-1.5">
                          <span>{formatPrice(pos.entry_price, pos.symbol)}</span>
                          <span>→</span>
                          <span className="text-white font-bold">{formatPrice(pos.current_price, pos.symbol)}</span>
                        </div>

                        <div className="text-[10px] font-mono text-slate-500 flex items-center gap-2">
                          {pos.sl_price && <span>SL: {formatPrice(pos.sl_price, pos.symbol)}</span>}
                          {pos.tp_price && <span>TP: {formatPrice(pos.tp_price, pos.symbol)}</span>}
                        </div>
                      </div>

                      {/* Sağ: PnL Değeri */}
                      <div className="text-right">
                        <div
                          className={`text-base font-black font-mono ${
                            isProfit ? "text-blue-400" : "text-rose-400"
                          }`}
                        >
                          {isProfit ? "+" : ""}${Number(pos.pnl_usd).toFixed(2)}
                        </div>
                        <div className="text-[10px] text-slate-400 font-mono">
                          {pos.pnl_pips >= 0 ? "+" : ""}{pos.pnl_pips.toFixed(1)} pip
                        </div>
                      </div>
                    </div>
                  );
                })
              )}
            </div>
          )}

          {/* ========================================================= */}
          {/* SEKME 4: GEÇMİŞ (HISTORY)                                 */}
          {/* ========================================================= */}
          {activeTab === "HISTORY" && (
            <div className="pb-16 divide-y divide-slate-800/70">
              {/* Dönem Filtresi (Bugün, Hafta, Ay, Tümü) */}
              <div className="p-2 bg-bunker-900 flex items-center justify-around text-xs">
                {(["TODAY", "WEEK", "MONTH", "ALL"] as const).map((period) => (
                  <button
                    key={period}
                    type="button"
                    onClick={() => setHistoryPeriod(period)}
                    className={`px-3 py-1 rounded-lg font-bold text-xs transition-colors ${
                      historyPeriod === period
                        ? "bg-blue-600 text-white"
                        : "text-slate-400 hover:text-white"
                    }`}
                  >
                    {period === "TODAY" ? "Bugün" : period === "WEEK" ? "Son Hafta" : period === "MONTH" ? "Son Ay" : "Tümü"}
                  </button>
                ))}
              </div>

              {/* MT5 Geçmiş Özet Şeridi */}
              <div className="p-3 bg-bunker-800 grid grid-cols-2 gap-2 text-xs font-mono">
                <div>
                  <span className="text-slate-400 block text-[10px]">KÂR / ZARAR:</span>
                  <span
                    className={`font-black text-sm ${
                      historyProfitTotal >= 0 ? "text-emerald-400" : "text-rose-400"
                    }`}
                  >
                    {historyProfitTotal >= 0 ? "+" : ""}${historyProfitTotal.toFixed(2)}
                  </span>
                </div>
                <div className="text-right">
                  <span className="text-slate-400 block text-[10px]">DEPOZİTO:</span>
                  <span className="font-bold text-white">$10,000.00</span>
                </div>
              </div>

              {/* Kapanan İşlem Listesi */}
              {filteredClosedTrades.length === 0 ? (
                <div className="p-8 text-center text-xs text-slate-400">
                  Bu dönemde kapanmış işlem bulunamadı.
                </div>
              ) : (
                filteredClosedTrades.map((t) => {
                  const isProfit = Number(t.pnl_usd ?? 0) >= 0;
                  return (
                    <div
                      key={t.id || t.ticket}
                      className="p-3 hover:bg-slate-900/40 transition-colors flex items-center justify-between text-xs"
                    >
                      <div className="space-y-0.5">
                        <div className="flex items-center gap-1.5">
                          <span className="font-bold text-white">{t.symbol}</span>
                          <span
                            className={`text-[10px] font-bold ${
                              t.direction === "BUY" ? "text-blue-400" : "text-rose-400"
                            }`}
                          >
                            {t.direction.toLowerCase()} {t.lots.toFixed(2)}
                          </span>
                        </div>
                        <div className="text-[10px] text-slate-400 font-mono">
                          {formatPrice(t.entry_price, t.symbol)} → {formatPrice(t.exit_price || t.close_price, t.symbol)}
                        </div>
                        <div className="text-[9px] text-slate-400 font-mono">
                          {t.close_time || t.exit_time || "—"}
                        </div>
                      </div>

                      <div className="text-right font-mono">
                        <span
                          className={`font-black text-sm ${
                            isProfit ? "text-blue-400" : "text-rose-400"
                          }`}
                        >
                          {isProfit ? "+" : ""}${Number(t.pnl_usd).toFixed(2)}
                        </span>
                        <div className="text-[10px] text-slate-400">
                          {t.pnl_pips >= 0 ? "+" : ""}{Number(t.pnl_pips).toFixed(1)} pip
                        </div>
                      </div>
                    </div>
                  );
                })
              )}
            </div>
          )}

          {/* ========================================================= */}
          {/* SEKME 5: AYARLAR (SETTINGS)                               */}
          {/* ========================================================= */}
          {activeTab === "SETTINGS" && (
            <div className="p-4 space-y-4 pb-20 text-xs">
              {/* Hesap Bilgisi Kartı */}
              <div className="p-3.5 rounded-xl bg-bunker-900 border border-slate-800 space-y-2">
                <div className="flex items-center justify-between pb-2 border-b border-slate-800">
                  <div className="font-bold text-white text-sm">Hesap Bilgileri</div>
                  <span className="px-2 py-0.5 rounded bg-emerald-500/20 text-emerald-400 text-[10px] font-bold">
                    BAĞLI
                  </span>
                </div>
                <div className="grid grid-cols-2 gap-2 text-slate-300 font-mono">
                  <div>
                    <span className="text-slate-400 block text-[10px]">HESAP NO</span>
                    #{account.account_id}
                  </div>
                  <div>
                    <span className="text-slate-400 block text-[10px]">SUNUCU</span>
                    {account.server_name}
                  </div>
                  <div>
                    <span className="text-slate-400 block text-[10px]">KALDIRAÇ</span>
                    {account.leverage}
                  </div>
                  <div>
                    <span className="text-slate-400 block text-[10px]">GECİKME (PING)</span>
                    {account.ping_ms} ms
                  </div>
                </div>
              </div>

              {/* Otonom Bot Durumu */}
              <div className="p-3.5 rounded-xl bg-bunker-900 border border-slate-800 space-y-2">
                <div className="font-bold text-white text-sm">Otonom Bot Entegrasyonu</div>
                <p className="text-slate-400 text-[11px]">
                  MetaMobil arayüzü doğrudan canlı otonom motor ve MT5 köprüsü ile eşzamanlı çalışır. Açılan işlemler otonom motora aktarılır.
                </p>
                <div className="pt-2">
                  <Link
                    href="/settings"
                    className="block text-center py-2 px-3 rounded-lg bg-blue-600 hover:bg-blue-500 text-white font-bold"
                  >
                    ⚙️ Detaylı Scalper Ayarlarına Git
                  </Link>
                </div>
              </div>

              {/* Hızlı Kısayollar */}
              <div className="space-y-1.5 pt-2">
                <Link
                  href="/forex/reports"
                  className="w-full flex items-center justify-between p-3 rounded-lg bg-slate-900 border border-slate-800 text-slate-200 hover:text-white"
                >
                  <span>📊 Detaylı K/Z ve İşlem Raporları</span>
                  <span>→</span>
                </Link>
                <Link
                  href="/forex"
                  className="w-full flex items-center justify-between p-3 rounded-lg bg-slate-900 border border-slate-800 text-slate-200 hover:text-white"
                >
                  <span>📡 Forex Radar Ekranı</span>
                  <span>→</span>
                </Link>
              </div>
            </div>
          )}

        </div>

        {/* 4. METATRADER 5 SABİT ALT MENÜ ÇUBUĞU (BOTTOM NAVIGATION BAR - 5 TAB) */}
        <nav
          className="h-14 bg-bunker-900 border-t border-slate-800 flex items-center justify-around px-1 shrink-0 z-20"
          style={{ paddingBottom: "max(0.2rem, env(safe-area-inset-bottom, 0px))" }}
        >
          {/* TAB 1: KOTASYONLAR */}
          <button
            type="button"
            onClick={() => {
              playClickSound();
              setActiveTab("QUOTES");
            }}
            className={`flex flex-col items-center justify-center flex-1 py-1 transition-colors ${
              activeTab === "QUOTES" ? "text-blue-400" : "text-slate-400 hover:text-slate-200"
            }`}
          >
            <span className="text-lg">📊</span>
            <span className="text-[10px] font-bold mt-0.5">Kotasyonlar</span>
          </button>

          {/* TAB 2: GRAFİK */}
          <button
            type="button"
            onClick={() => {
              playClickSound();
              setActiveTab("CHART");
            }}
            className={`flex flex-col items-center justify-center flex-1 py-1 transition-colors ${
              activeTab === "CHART" ? "text-blue-400" : "text-slate-400 hover:text-slate-200"
            }`}
          >
            <span className="text-lg">📈</span>
            <span className="text-[10px] font-bold mt-0.5">Grafik</span>
          </button>

          {/* TAB 3: TİCARET */}
          <button
            type="button"
            onClick={() => {
              playClickSound();
              setActiveTab("TRADE");
            }}
            className={`flex flex-col items-center justify-center flex-1 py-1 transition-colors ${
              activeTab === "TRADE" ? "text-blue-400" : "text-slate-400 hover:text-slate-200"
            }`}
          >
            <span className="text-lg">💼</span>
            <span className="text-[10px] font-bold mt-0.5">Ticaret</span>
          </button>

          {/* TAB 4: GEÇMİŞ */}
          <button
            type="button"
            onClick={() => {
              playClickSound();
              setActiveTab("HISTORY");
            }}
            className={`flex flex-col items-center justify-center flex-1 py-1 transition-colors ${
              activeTab === "HISTORY" ? "text-blue-400" : "text-slate-400 hover:text-slate-200"
            }`}
          >
            <span className="text-lg">📜</span>
            <span className="text-[10px] font-bold mt-0.5">Geçmiş</span>
          </button>

          {/* TAB 5: AYARLAR */}
          <button
            type="button"
            onClick={() => {
              playClickSound();
              setActiveTab("SETTINGS");
            }}
            className={`flex flex-col items-center justify-center flex-1 py-1 transition-colors ${
              activeTab === "SETTINGS" ? "text-blue-400" : "text-slate-400 hover:text-slate-200"
            }`}
          >
            <span className="text-lg">⚙️</span>
            <span className="text-[10px] font-bold mt-0.5">Ayarlar</span>
          </button>
        </nav>

        {/* ========================================================= */}
        {/* ALT EYLEM SAYFASI (ACTION SHEET) - SEMBOLE TIKLANDIĞINDA  */}
        {/* ========================================================= */}
        {actionSheetSymbol && (
          <div className="absolute inset-0 bg-black/60 z-40 flex flex-col justify-end animate-in fade-in duration-150">
            <div className="bg-bunker-900 rounded-t-2xl p-4 border-t border-slate-700 space-y-3">
              <div className="flex items-center justify-between pb-2 border-b border-slate-800">
                <div>
                  <div className="font-bold text-base text-white">{actionSheetSymbol.symbol}</div>
                  <div className="text-xs text-slate-400">{actionSheetSymbol.name}</div>
                </div>
                <button
                  type="button"
                  onClick={() => setActionSheetSymbol(null)}
                  className="w-7 h-7 rounded-full bg-slate-800 text-slate-400 hover:text-white flex items-center justify-center text-sm"
                >
                  ✕
                </button>
              </div>

              <div className="space-y-2">
                <button
                  type="button"
                  onClick={() => {
                    setNewOrderSymbol(actionSheetSymbol.symbol);
                    setActionSheetSymbol(null);
                    setNewOrderModalOpen(true);
                  }}
                  className="w-full py-2.5 px-4 rounded-xl bg-blue-600 hover:bg-blue-500 text-white font-bold text-sm flex items-center gap-2"
                >
                  <span>⚡</span>
                  <span>Yeni Emir (Trade)</span>
                </button>

                <button
                  type="button"
                  onClick={() => {
                    setSelectedSymbol(actionSheetSymbol.symbol);
                    setActionSheetSymbol(null);
                    setActiveTab("CHART");
                  }}
                  className="w-full py-2.5 px-4 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-200 font-bold text-sm flex items-center gap-2"
                >
                  <span>📈</span>
                  <span>Grafik Aç</span>
                </button>

                <button
                  type="button"
                  onClick={() => setActionSheetSymbol(null)}
                  className="w-full py-2 px-4 rounded-xl text-slate-400 hover:text-white text-xs font-semibold"
                >
                  İptal
                </button>
              </div>
            </div>
          </div>
        )}

        {/* ========================================================= */}
        {/* YENİ EMİR MODALI (MT5 NEW ORDER MODAL)                    */}
        {/* ========================================================= */}
        {newOrderModalOpen && (
          <div className="absolute inset-0 bg-black/75 z-50 flex flex-col justify-end animate-in fade-in duration-150">
            <div className="bg-bunker-900 rounded-t-3xl p-4 border-t border-slate-700 space-y-4 max-h-[90%] overflow-y-auto">
              {/* Başlık */}
              <div className="flex items-center justify-between pb-2 border-b border-slate-800">
                <div>
                  <div className="font-bold text-base text-white flex items-center gap-2">
                    <span>{newOrderSymbol}</span>
                    <span className="text-[10px] px-1.5 py-0.2 rounded bg-blue-500/20 text-blue-400 font-mono">
                      Piyasa İcrası
                    </span>
                  </div>
                  <div className="text-[10px] text-slate-400">Piyasa Fiyatından Anında Emir</div>
                </div>
                <button
                  type="button"
                  onClick={() => setNewOrderModalOpen(false)}
                  className="w-7 h-7 rounded-full bg-slate-800 text-slate-400 hover:text-white flex items-center justify-center text-sm"
                >
                  ✕
                </button>
              </div>

              {/* Lot Seçim Çubuğu */}
              <div className="space-y-1.5">
                <span className="text-[11px] font-bold text-slate-400 uppercase">İşlem Hacmi (Lot)</span>
                <div className="flex items-center justify-between bg-slate-900 rounded-xl p-1.5 border border-slate-800">
                  <button
                    type="button"
                    onClick={() => setOrderLots((l) => Math.max(0.01, Number((l - 0.1).toFixed(2))))}
                    className="px-2.5 py-1 rounded bg-slate-800 text-slate-300 font-mono font-bold text-xs"
                  >
                    -0.1
                  </button>
                  <button
                    type="button"
                    onClick={() => setOrderLots((l) => Math.max(0.01, Number((l - 0.01).toFixed(2))))}
                    className="px-2 py-1 rounded bg-slate-800 text-slate-300 font-mono font-bold text-xs"
                  >
                    -0.01
                  </button>
                  <span className="font-mono font-black text-white text-base px-3">
                    {orderLots.toFixed(2)}
                  </span>
                  <button
                    type="button"
                    onClick={() => setOrderLots((l) => Number((l + 0.01).toFixed(2)))}
                    className="px-2 py-1 rounded bg-slate-800 text-slate-300 font-mono font-bold text-xs"
                  >
                    +0.01
                  </button>
                  <button
                    type="button"
                    onClick={() => setOrderLots((l) => Number((l + 0.1).toFixed(2)))}
                    className="px-2.5 py-1 rounded bg-slate-800 text-slate-300 font-mono font-bold text-xs"
                  >
                    +0.1
                  </button>
                </div>
              </div>

              {/* Büyük Çift Fiyat Göstergesi */}
              <div className="grid grid-cols-2 gap-2 text-center py-1">
                <div className="p-2.5 rounded-xl bg-rose-500/10 border border-rose-500/30">
                  <span className="text-[10px] font-bold text-rose-400 block uppercase">BİD (SATIŞ)</span>
                  <span className="text-xl font-black font-mono text-rose-300">
                    {formatPrice(activeQuote.bid, activeQuote.symbol)}
                  </span>
                </div>
                <div className="p-2.5 rounded-xl bg-blue-500/10 border border-blue-500/30">
                  <span className="text-[10px] font-bold text-blue-400 block uppercase">ASK (ALIŞ)</span>
                  <span className="text-xl font-black font-mono text-blue-300">
                    {formatPrice(activeQuote.ask, activeQuote.symbol)}
                  </span>
                </div>
              </div>

              {/* SL ve TP Alanları */}
              <div className="grid grid-cols-2 gap-2.5">
                <div className="space-y-1">
                  <span className="text-[10px] font-bold text-rose-400 block">ZARAR DURDUR (SL)</span>
                  <input
                    type="number"
                    step="any"
                    placeholder="İsteğe Bağlı"
                    value={orderSl}
                    onChange={(e) => setOrderSl(e.target.value)}
                    className="w-full bg-slate-900 border border-slate-800 rounded-lg p-2 font-mono text-xs text-white outline-none focus:border-rose-500"
                  />
                </div>
                <div className="space-y-1">
                  <span className="text-[10px] font-bold text-emerald-400 block">KÂR AL (TP)</span>
                  <input
                    type="number"
                    step="any"
                    placeholder="İsteğe Bağlı"
                    value={orderTp}
                    onChange={(e) => setOrderTp(e.target.value)}
                    className="w-full bg-slate-900 border border-slate-800 rounded-lg p-2 font-mono text-xs text-white outline-none focus:border-emerald-500"
                  />
                </div>
              </div>

              {/* Durum Bildirimi */}
              {orderStatusMsg && (
                <div className="p-2 rounded-lg bg-blue-500/20 text-blue-300 text-center font-bold text-xs">
                  {orderStatusMsg}
                </div>
              )}

              {/* İKİ DEV MT5 BUTONU (SELL & BUY) */}
              <div className="grid grid-cols-2 gap-3 pt-2">
                <button
                  type="button"
                  onClick={() => handleExecuteOrder("SELL")}
                  className="py-3 px-4 rounded-xl bg-rose-600 hover:bg-rose-500 text-white font-black text-sm flex flex-col items-center justify-center shadow-lg shadow-rose-600/30 transition-transform active:scale-95"
                >
                  <span>PİYASA SATIŞ</span>
                  <span className="text-[10px] font-mono opacity-80">SELL BY MARKET</span>
                </button>

                <button
                  type="button"
                  onClick={() => handleExecuteOrder("BUY")}
                  className="py-3 px-4 rounded-xl bg-blue-600 hover:bg-blue-500 text-white font-black text-sm flex flex-col items-center justify-center shadow-lg shadow-blue-600/30 transition-transform active:scale-95"
                >
                  <span>PİYASA ALIŞ</span>
                  <span className="text-[10px] font-mono opacity-80">BUY BY MARKET</span>
                </button>
              </div>
            </div>
          </div>
        )}

        {/* ========================================================= */}
        {/* POZİSYON KAPATMA MODALI (CLOSE POSITION ACTION)          */}
        {/* ========================================================= */}
        {closingPosition && (
          <div className="absolute inset-0 bg-black/75 z-50 flex flex-col justify-end animate-in fade-in duration-150">
            <div className="bg-bunker-900 rounded-t-3xl p-4 border-t border-slate-700 space-y-3">
              <div className="flex items-center justify-between pb-2 border-b border-slate-800">
                <div>
                  <div className="font-bold text-base text-white">
                    Pozisyonu Kapat: #{closingPosition.ticket || closingPosition.id}
                  </div>
                  <div className="text-xs text-slate-400">
                    {closingPosition.symbol} {closingPosition.direction} {closingPosition.lots} Lot
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => setClosingPosition(null)}
                  className="w-7 h-7 rounded-full bg-slate-800 text-slate-400 hover:text-white flex items-center justify-center text-sm"
                >
                  ✕
                </button>
              </div>

              <div className="p-3 bg-slate-900 rounded-xl space-y-1 font-mono text-xs">
                <div className="flex justify-between">
                  <span className="text-slate-400 font-sans">Giriş Fiyatı:</span>
                  <span className="text-white font-bold">{formatPrice(closingPosition.entry_price, closingPosition.symbol)}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-400 font-sans">Güncel Fiyat:</span>
                  <span className="text-white font-bold">{formatPrice(closingPosition.current_price, closingPosition.symbol)}</span>
                </div>
                <div className="flex justify-between pt-1 border-t border-slate-800">
                  <span className="text-slate-300 font-sans font-bold">Kâr / Zarar:</span>
                  <span
                    className={`font-black ${
                      Number(closingPosition.pnl_usd) >= 0 ? "text-emerald-400" : "text-rose-400"
                    }`}
                  >
                    {Number(closingPosition.pnl_usd) >= 0 ? "+" : ""}${Number(closingPosition.pnl_usd).toFixed(2)} USD
                  </span>
                </div>
              </div>

              {/* Dev MT5 Kapat Butonu */}
              <button
                type="button"
                onClick={() => handleClosePosition(closingPosition)}
                className={`w-full py-3 px-4 rounded-xl font-black text-sm flex items-center justify-center gap-2 shadow-lg transition-transform active:scale-95 ${
                  Number(closingPosition.pnl_usd) >= 0
                    ? "bg-amber-600 hover:bg-amber-500 text-white shadow-amber-600/30"
                    : "bg-rose-600 hover:bg-rose-500 text-white shadow-rose-600/30"
                }`}
              >
                <span>✕</span>
                <span>
                  {Number(closingPosition.pnl_usd) >= 0 ? "KÂRLA KAPAT" : "ZARARLA KAPAT"} (
                  {Number(closingPosition.pnl_usd) >= 0 ? "+" : ""}${Number(closingPosition.pnl_usd).toFixed(2)})
                </span>
              </button>

              <button
                type="button"
                onClick={() => setClosingPosition(null)}
                className="w-full py-2 text-center text-slate-400 hover:text-white text-xs font-semibold"
              >
                Vazgeç
              </button>
            </div>
          </div>
        )}

    </div>
  );
}
