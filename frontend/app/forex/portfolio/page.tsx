"use client";

import React, { useState, useEffect } from "react";
import { apiFetch } from "../../lib/api";

interface ForexPosition {
  id: string;
  symbol: string;
  display: string;
  type: "BUY" | "SELL";
  lots: number;
  entryPrice: number;
  currentPrice: number;
  slPrice?: number;
  tpPrice?: number;
  openTime: string;
  pnlUsd: number;
  pnlPips: number;
}

const STORAGE_KEY_POS = "forex_demo_positions_v1";
const STORAGE_KEY_BAL = "forex_demo_balance_v1";

export default function ForexPortfolioPage() {
  const [balance, setBalance] = useState<number>(10000.0);
  const [positions, setPositions] = useState<ForexPosition[]>([]);
  const [tickers, setTickers] = useState<any[]>([]);

  // New order form
  const [selectedSym, setSelectedSym] = useState("EURUSD");
  const [orderType, setOrderType] = useState<"BUY" | "SELL">("BUY");
  const [orderLots, setOrderLots] = useState(0.5);
  const [slPips, setSlPips] = useState(25);
  const [tpPips, setTpPips] = useState(50);

  // Load from local storage
  useEffect(() => {
    try {
      const savedBal = localStorage.getItem(STORAGE_KEY_BAL);
      if (savedBal) setBalance(parseFloat(savedBal));

      const savedPos = localStorage.getItem(STORAGE_KEY_POS);
      if (savedPos) setPositions(JSON.parse(savedPos));
    } catch {
      // Storage fallback
    }
  }, []);

  // Save to local storage
  const saveState = (newBal: number, newPos: ForexPosition[]) => {
    setBalance(newBal);
    setPositions(newPos);
    try {
      localStorage.setItem(STORAGE_KEY_BAL, newBal.toString());
      localStorage.setItem(STORAGE_KEY_POS, JSON.stringify(newPos));
    } catch {}
  };

  // Fetch live prices and update PnL
  useEffect(() => {
    const updatePrices = async () => {
      try {
        const res = await apiFetch("/api/forex/tickers");
        if (res && res.tickers) {
          setTickers(res.tickers);

          // Update open position prices
          setPositions((prev) =>
            prev.map((pos) => {
              const tick = res.tickers.find((t: any) => t.symbol === pos.symbol);
              if (!tick) return pos;

              const curPrice = pos.type === "BUY" ? tick.bid : tick.ask;
              const pipSize = tick.pip_size || 0.0001;
              const pnlPips =
                pos.type === "BUY"
                  ? (curPrice - pos.entryPrice) / pipSize
                  : (pos.entryPrice - curPrice) / pipSize;

              // Pip value: $10 per standard lot
              const pipValue = pos.lots * 10.0;
              const pnlUsd = pnlPips * pipValue;

              return {
                ...pos,
                currentPrice: curPrice,
                pnlPips: round(pnlPips, 1),
                pnlUsd: round(pnlUsd, 2),
              };
            })
          );
        }
      } catch (err) {
        console.error("Fiyat güncelleme hatası:", err);
      }
    };

    updatePrices();
    const interval = setInterval(updatePrices, 2000);
    return () => clearInterval(interval);
  }, []);

  const openPosition = () => {
    const tick = tickers.find((t) => t.symbol === selectedSym);
    const entryPrice = tick ? (orderType === "BUY" ? tick.ask : tick.bid) : 1.085;
    const pipSize = tick?.pip_size || 0.0001;

    const slPrice =
      slPips > 0
        ? orderType === "BUY"
          ? entryPrice - slPips * pipSize
          : entryPrice + slPips * pipSize
        : undefined;

    const tpPrice =
      tpPips > 0
        ? orderType === "BUY"
          ? entryPrice + tpPips * pipSize
          : entryPrice - tpPips * pipSize
        : undefined;

    const newPos: ForexPosition = {
      id: "FX-" + Math.floor(100000 + Math.random() * 900000),
      symbol: selectedSym,
      display: tick?.display || selectedSym,
      type: orderType,
      lots: orderLots,
      entryPrice,
      currentPrice: entryPrice,
      slPrice,
      tpPrice,
      openTime: new Date().toLocaleTimeString("tr-TR"),
      pnlUsd: 0.0,
      pnlPips: 0.0,
    };

    saveState(balance, [newPos, ...positions]);
  };

  const closePosition = (id: string) => {
    const pos = positions.find((p) => p.id === id);
    if (!pos) return;

    const newBalance = balance + pos.pnlUsd;
    const remaining = positions.filter((p) => p.id !== id);
    saveState(newBalance, remaining);
  };

  const resetAccount = () => {
    if (confirm("Forex demo hesabını $10,000 bakiyeyle sıfırlamak istiyor musunuz?")) {
      saveState(10000.0, []);
    }
  };

  // Metrics
  const totalOpenPnl = positions.reduce((sum, p) => sum + p.pnlUsd, 0);
  const equity = balance + totalOpenPnl;
  const usedMargin = positions.reduce((sum, p) => sum + p.lots * 1000, 0); // 1:100 leverage assumed
  const freeMargin = equity - usedMargin;
  const marginLevel = usedMargin > 0 ? (equity / usedMargin) * 100 : 0;

  return (
    <div className="space-y-6 pb-12">
      {/* ÜST BİLGİ KARTLARI */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        <div className="p-3.5 rounded-xl bg-bunker-900/80 border border-bunker-800 font-mono">
          <span className="text-[10px] text-bunker-muted uppercase block">Hesap Bakiyesi</span>
          <span className="text-lg font-bold text-white">${balance.toFixed(2)}</span>
        </div>
        <div className="p-3.5 rounded-xl bg-bunker-900/80 border border-bunker-800 font-mono">
          <span className="text-[10px] text-bunker-muted uppercase block">Özsermaye (Equity)</span>
          <span
            className={`text-lg font-bold ${
              equity >= balance ? "text-emerald-400" : "text-rose-400"
            }`}
          >
            ${equity.toFixed(2)}
          </span>
        </div>
        <div className="p-3.5 rounded-xl bg-bunker-900/80 border border-bunker-800 font-mono">
          <span className="text-[10px] text-bunker-muted uppercase block">Açık Kâr / Zarar</span>
          <span
            className={`text-lg font-bold ${
              totalOpenPnl >= 0 ? "text-emerald-400" : "text-rose-400"
            }`}
          >
            {totalOpenPnl >= 0 ? "+" : ""}
            ${totalOpenPnl.toFixed(2)}
          </span>
        </div>
        <div className="p-3.5 rounded-xl bg-bunker-900/80 border border-bunker-800 font-mono">
          <span className="text-[10px] text-bunker-muted uppercase block">Serbest Teminat</span>
          <span className="text-lg font-bold text-cyan-300">${freeMargin.toFixed(2)}</span>
        </div>
        <div className="p-3.5 rounded-xl bg-bunker-900/80 border border-bunker-800 font-mono flex items-center justify-between">
          <div>
            <span className="text-[10px] text-bunker-muted uppercase block">Teminat Seviyesi</span>
            <span className="text-lg font-bold text-white">
              {usedMargin > 0 ? `${marginLevel.toFixed(0)}%` : "—"}
            </span>
          </div>
          <button
            type="button"
            onClick={resetAccount}
            title="Hesabı Sıfırla"
            className="p-1.5 rounded-lg bg-bunker-800 hover:bg-rose-500/20 text-bunker-muted hover:text-rose-400 transition-all text-xs"
          >
            ↺ Sıfırla
          </button>
        </div>
      </div>

      {/* YENİ İŞLEM AÇMA PANELİ */}
      <div className="p-5 rounded-2xl border border-bunker-800 bg-gradient-to-r from-bunker-900/80 to-bunker-950/80 shadow-lg space-y-4 font-mono">
        <div className="flex items-center justify-between border-b border-bunker-800 pb-3">
          <div className="flex items-center gap-2">
            <span className="text-lg">⚡</span>
            <h2 className="text-sm font-bold text-white uppercase tracking-wider">
              Forex Demo İşlem Emri Ver (1:100 Kaldıraç)
            </h2>
          </div>
          <span className="text-xs text-blue-400">Piyasa Emri (Market Execution)</span>
        </div>

        <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
          <div>
            <label className="text-[11px] text-bunker-muted block mb-1">Parite:</label>
            <select
              value={selectedSym}
              onChange={(e) => setSelectedSym(e.target.value)}
              className="w-full bg-bunker-950 border border-bunker-700 rounded-lg px-2.5 py-1.5 text-xs text-white outline-none focus:border-blue-400 font-bold"
            >
              <option value="EURUSD">EUR/USD</option>
              <option value="GBPUSD">GBP/USD</option>
              <option value="USDJPY">USD/JPY</option>
              <option value="XAUUSD">XAU/USD (Altın)</option>
              <option value="AUDUSD">AUD/USD</option>
              <option value="USDCAD">USD/CAD</option>
              <option value="USDCHF">USD/CHF</option>
              <option value="USOIL">WTI Petrol</option>
            </select>
          </div>

          <div>
            <label className="text-[11px] text-bunker-muted block mb-1">İşlem Hacmi (Lot):</label>
            <input
              type="number"
              step="0.01"
              value={orderLots}
              onChange={(e) => setOrderLots(Math.max(0.01, parseFloat(e.target.value) || 0.01))}
              className="w-full bg-bunker-950 border border-bunker-700 rounded-lg px-2.5 py-1.5 text-xs text-white outline-none focus:border-blue-400 font-bold"
            />
          </div>

          <div>
            <label className="text-[11px] text-bunker-muted block mb-1">Stop Loss (Pips):</label>
            <input
              type="number"
              value={slPips}
              onChange={(e) => setSlPips(parseInt(e.target.value) || 0)}
              className="w-full bg-bunker-950 border border-bunker-700 rounded-lg px-2.5 py-1.5 text-xs text-white outline-none focus:border-blue-400"
            />
          </div>

          <div>
            <label className="text-[11px] text-bunker-muted block mb-1">Take Profit (Pips):</label>
            <input
              type="number"
              value={tpPips}
              onChange={(e) => setTpPips(parseInt(e.target.value) || 0)}
              className="w-full bg-bunker-950 border border-bunker-700 rounded-lg px-2.5 py-1.5 text-xs text-white outline-none focus:border-blue-400"
            />
          </div>

          <div className="flex items-end gap-2">
            <button
              type="button"
              onClick={() => {
                setOrderType("BUY");
                setTimeout(openPosition, 50);
              }}
              className="flex-1 py-2 rounded-lg bg-emerald-500/20 text-emerald-400 border border-emerald-500/40 font-bold text-xs hover:bg-emerald-500/30 transition-all shadow-[0_0_10px_rgba(16,185,129,0.2)]"
            >
              ▲ BUY (Al)
            </button>
            <button
              type="button"
              onClick={() => {
                setOrderType("SELL");
                setTimeout(openPosition, 50);
              }}
              className="flex-1 py-2 rounded-lg bg-rose-500/20 text-rose-400 border border-rose-500/40 font-bold text-xs hover:bg-rose-500/30 transition-all shadow-[0_0_10px_rgba(244,63,94,0.2)]"
            >
              ▼ SELL (Sat)
            </button>
          </div>
        </div>
      </div>

      {/* AÇIK POZİSYONLAR TABLOSU */}
      <div className="rounded-2xl border border-bunker-800 bg-bunker-900/70 overflow-hidden shadow-xl font-mono">
        <div className="p-4 border-b border-bunker-800 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="text-lg">📋</span>
            <h3 className="text-sm font-bold text-white uppercase tracking-wider">
              Açık Forex Pozisyonları ({positions.length})
            </h3>
          </div>
        </div>

        {positions.length === 0 ? (
          <div className="p-12 text-center text-bunker-muted text-xs">
            Şu an açık bir Forex pozisyonu bulunmuyor. Yukarıdaki panelden yeni bir işlem açabilirsiniz.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="bg-bunker-950/80 text-bunker-muted uppercase border-b border-bunker-800 text-[10px]">
                <tr>
                  <th className="py-3 px-4">Bilet No</th>
                  <th className="py-3 px-3">Parite</th>
                  <th className="py-3 px-3">Yön</th>
                  <th className="py-3 px-3">Lot</th>
                  <th className="py-3 px-3">Açılış</th>
                  <th className="py-3 px-3">Güncel</th>
                  <th className="py-3 px-3">Pips</th>
                  <th className="py-3 px-3">Kâr / Zarar ($)</th>
                  <th className="py-3 px-4 text-right">Aksiyon</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-bunker-800/60">
                {positions.map((pos) => {
                  const isProfit = pos.pnlUsd >= 0;
                  return (
                    <tr key={pos.id} className="hover:bg-bunker-800/40 transition-colors">
                      <td className="py-3 px-4 text-bunker-muted text-[11px]">{pos.id}</td>
                      <td className="py-3 px-3 font-bold text-white">{pos.display}</td>
                      <td className="py-3 px-3">
                        <span
                          className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                            pos.type === "BUY"
                              ? "bg-emerald-500/15 text-emerald-400 border border-emerald-500/30"
                              : "bg-rose-500/15 text-rose-400 border border-rose-500/30"
                          }`}
                        >
                          {pos.type}
                        </span>
                      </td>
                      <td className="py-3 px-3 font-semibold text-white">{pos.lots} Lot</td>
                      <td className="py-3 px-3 text-bunker-muted">{pos.entryPrice}</td>
                      <td className="py-3 px-3 font-bold text-white">{pos.currentPrice}</td>
                      <td
                        className={`py-3 px-3 font-bold ${
                          pos.pnlPips >= 0 ? "text-emerald-400" : "text-rose-400"
                        }`}
                      >
                        {pos.pnlPips >= 0 ? "+" : ""}
                        {pos.pnlPips} p
                      </td>
                      <td
                        className={`py-3 px-3 font-bold text-sm ${
                          isProfit ? "text-emerald-400" : "text-rose-400"
                        }`}
                      >
                        {isProfit ? "+" : ""}
                        ${pos.pnlUsd.toFixed(2)}
                      </td>
                      <td className="py-3 px-4 text-right">
                        <button
                          type="button"
                          onClick={() => closePosition(pos.id)}
                          className="px-2.5 py-1 rounded-lg bg-rose-500/10 text-rose-400 border border-rose-500/20 hover:bg-rose-500/20 transition-all font-bold text-[11px]"
                        >
                          Kapat ✕
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

function round(val: number, decimals: number): number {
  return Number(Math.round(Number(val + "e" + decimals)) + "e-" + decimals);
}
