"use client";

import React, { useState, useEffect } from "react";
import Link from "next/link";
import { apiFetch } from "../../lib/api";

interface AutoPosition {
  id: string;
  symbol: string;
  display: string;
  direction: "BUY" | "SELL";
  lots: number;
  entry_price: number;
  current_price: number;
  sl_price: number;
  tp_price: number;
  initial_sl_price: number;
  breakeven_activated: boolean;
  trailing_activated: boolean;
  open_time: string;
  pnl_usd: number;
  pnl_pips: number;
  pip_size: number;
  digits: number;
  score: number;
  strategy: string;
}

interface ClosedTrade {
  id: string;
  symbol: string;
  display: string;
  direction: "BUY" | "SELL";
  lots: number;
  entry_price: number;
  exit_price: number;
  exit_time: string;
  exit_reason: string;
  pnl_usd: number;
  pnl_pips: number;
  score?: number;
}

interface DecisionLog {
  id: string;
  time: string;
  category: "ENTRY" | "EXIT" | "PROTECT" | "GATE" | "SYSTEM" | "SCAN";
  symbol?: string;
  message: string;
  metadata?: any;
}

interface AutoSettings {
  enabled: boolean;
  balance: number;
  risk_per_trade_pct: number;
  max_open_positions: number;
  min_score: number;
  tp_pips: number;
  sl_pips: number;
  breakeven_pips: number;
  trailing_stop_pips: number;
  session_filter: boolean;
  max_spread_pips: number;
  allowed_symbols: string[];
}

export default function ForexPortfolioPage() {
  // Otonom Sistem Durumu
  const [autoStatus, setAutoStatus] = useState<string>("Yükleniyor…");
  const [autoEnabled, setAutoEnabled] = useState<boolean>(false);
  const [balance, setBalance] = useState<number>(10000.0);
  const [equity, setEquity] = useState<number>(10000.0);
  const [openPnlUsd, setOpenPnlUsd] = useState<number>(0.0);
  const [openPnlPips, setOpenPnlPips] = useState<number>(0.0);
  const [realizedPnlUsd, setRealizedPnlUsd] = useState<number>(0.0);
  const [realizedPnlPips, setRealizedPnlPips] = useState<number>(0.0);
  const [totalTrades, setTotalTrades] = useState<number>(0);
  const [wins, setWins] = useState<number>(0);
  const [losses, setLosses] = useState<number>(0);
  const [winRate, setWinRate] = useState<number>(0.0);

  const [openPositions, setOpenPositions] = useState<AutoPosition[]>([]);
  const [closedTrades, setClosedTrades] = useState<ClosedTrade[]>([]);
  const [decisionLogs, setDecisionLogs] = useState<DecisionLog[]>([]);
  const [sessions, setSessions] = useState<any[]>([]);
  const [logFilter, setLogFilter] = useState<string>("ALL");

  // Ayarlar & Düzenleme
  const [appliedSettings, setAppliedSettings] = useState<AutoSettings>({
    enabled: false,
    balance: 10000.0,
    risk_per_trade_pct: 1.0,
    max_open_positions: 3,
    min_score: 70.0,
    tp_pips: 25.0,
    sl_pips: 15.0,
    breakeven_pips: 8.0,
    trailing_stop_pips: 12.0,
    session_filter: false,
    max_spread_pips: 3.0,
    allowed_symbols: ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD", "USDCAD", "AUDUSD"],
  });

  const [formSettings, setFormSettings] = useState<AutoSettings>({
    enabled: false,
    balance: 10000.0,
    risk_per_trade_pct: 1.0,
    max_open_positions: 3,
    min_score: 70.0,
    tp_pips: 25.0,
    sl_pips: 15.0,
    breakeven_pips: 8.0,
    trailing_stop_pips: 12.0,
    session_filter: false,
    max_spread_pips: 3.0,
    allowed_symbols: ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD", "USDCAD", "AUDUSD"],
  });

  const [showSettings, setShowSettings] = useState(false);
  const [isSavingSettings, setIsSavingSettings] = useState(false);
  const [saveSuccessMsg, setSaveSuccessMsg] = useState<string | null>(null);
  const [showManualForm, setShowManualForm] = useState(false);

  // Manuel İşlem Formu
  const [manualSym, setManualSym] = useState("EURUSD");
  const [manualLots, setManualLots] = useState(0.5);
  const [manualSlPips, setManualSlPips] = useState(15);
  const [manualTpPips, setManualTpPips] = useState(25);

  const fetchStatus = async () => {
    try {
      const res = await apiFetch("/api/forex/auto-paper/status");
      if (res) {
        setAutoStatus(res.status || "Hazır");
        setAutoEnabled(Boolean(res.enabled));
        setBalance(res.balance ?? 10000.0);
        setEquity(res.equity ?? res.balance ?? 10000.0);
        setOpenPnlUsd(res.open_pnl_usd ?? 0.0);
        setOpenPnlPips(res.open_pnl_pips ?? 0.0);
        setRealizedPnlUsd(res.realized_pnl_usd ?? 0.0);
        setRealizedPnlPips(res.realized_pnl_pips ?? 0.0);
        setTotalTrades(res.total_trades ?? 0);
        setWins(res.wins ?? 0);
        setLosses(res.losses ?? 0);
        setWinRate(res.win_rate ?? 0.0);
        setOpenPositions(res.open_positions || []);
        setClosedTrades(res.closed_trades || []);
        setDecisionLogs(res.decision_logs || []);
        setSessions(res.sessions || []);
        if (res.settings) {
          setAppliedSettings(res.settings);
        }
      }
    } catch (err) {
      console.error("Forex auto-paper status alınamadı:", err);
    }
  };

  useEffect(() => {
    fetchStatus();
    const interval = setInterval(fetchStatus, 1500);
    return () => clearInterval(interval);
  }, []);

  // Otonom Motoru Aç / Kapat
  const toggleAutoEngine = async () => {
    try {
      const targetState = !autoEnabled;
      const res = await apiFetch("/api/forex/auto-paper/toggle", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled: targetState }),
      });
      if (res) {
        setAutoEnabled(res.enabled);
        setAutoStatus(res.status);
      }
    } catch (err) {
      console.error("Toggle hatası:", err);
    }
  };

  // Ayarları Düzenleme Modalını Aç
  const handleOpenSettings = () => {
    if (!showSettings) {
      setFormSettings({ ...appliedSettings });
      setSaveSuccessMsg(null);
    }
    setShowSettings(!showSettings);
  };

  const updateFormField = (key: keyof AutoSettings, val: any) => {
    setFormSettings((prev) => ({ ...prev, [key]: val }));
  };

  const toggleSymbol = (sym: string) => {
    setFormSettings((prev) => {
      const exists = prev.allowed_symbols.includes(sym);
      const next = exists
        ? prev.allowed_symbols.filter((s) => s !== sym)
        : [...prev.allowed_symbols, sym];
      return { ...prev, allowed_symbols: next.length > 0 ? next : [sym] };
    });
  };

  // Ayarları Kaydet
  const saveSettings = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsSavingSettings(true);
    setSaveSuccessMsg(null);
    try {
      const payload: AutoSettings = {
        ...formSettings,
        risk_per_trade_pct: Number(formSettings.risk_per_trade_pct) || 1.0,
        tp_pips: Number(formSettings.tp_pips) || 25.0,
        sl_pips: Number(formSettings.sl_pips) || 15.0,
        breakeven_pips: Number(formSettings.breakeven_pips) || 8.0,
        trailing_stop_pips: Number(formSettings.trailing_stop_pips) || 12.0,
        min_score: Number(formSettings.min_score) || 70.0,
        max_spread_pips: Number(formSettings.max_spread_pips) || 3.0,
        max_open_positions: Number(formSettings.max_open_positions) || 3,
        session_filter: Boolean(formSettings.session_filter),
        allowed_symbols:
          formSettings.allowed_symbols && formSettings.allowed_symbols.length > 0
            ? formSettings.allowed_symbols
            : ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD"],
      };

      const res = await apiFetch("/api/forex/auto-paper/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (res && res.status === "ok") {
        setAppliedSettings(res.settings);
        setFormSettings(res.settings);
        setSaveSuccessMsg("✓ Parametreler başarıyla güncellendi ve kaydedildi!");
        setTimeout(() => {
          setShowSettings(false);
          setSaveSuccessMsg(null);
        }, 1200);
      }
    } catch (err) {
      console.error("Ayarları kaydetme hatası:", err);
      alert("Parametre kaydedilirken bir hata oluştu.");
    } finally {
      setIsSavingSettings(false);
    }
  };

  // Pozisyonu Manuel Kapat
  const closePosition = async (id: string) => {
    try {
      await apiFetch("/api/forex/auto-paper/close-position", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id }),
      });
      fetchStatus();
    } catch (err) {
      console.error("Pozisyon kapatma hatası:", err);
    }
  };

  // Hesabı Sıfırla
  const resetAccount = async () => {
    if (confirm("Forex demo hesabını $10,000 başlangıç bakiyesiyle sıfırlamak istiyor musunuz?")) {
      try {
        await apiFetch("/api/forex/auto-paper/reset", {
          method: "POST",
        });
        fetchStatus();
      } catch (err) {
        console.error("Hesap sıfırlama hatası:", err);
      }
    }
  };

  // Manuel İşlem Açma (Otonom motora ekleme)
  const openManualTrade = async (direction: "BUY" | "SELL") => {
    try {
      // Ticker fiyatını al
      const tickersRes = await apiFetch("/api/forex/tickers");
      const tick = (tickersRes?.tickers || []).find((t: any) => t.symbol === manualSym);
      if (!tick) return;

      const pipSize = tick.pip_size || 0.0001;
      const digits = tick.digits || 5;
      const entryPrice = direction === "BUY" ? tick.ask : tick.bid;
      const slPrice = direction === "BUY" ? entryPrice - manualSlPips * pipSize : entryPrice + manualSlPips * pipSize;
      const tpPrice = direction === "BUY" ? entryPrice + manualTpPips * pipSize : entryPrice - manualTpPips * pipSize;

      // Pozisyon açma isteği (State'e doğrudan veya backend aracılığıyla)
      alert(`${direction} işlemi hazırlandı: ${manualLots} Lot @ ${entryPrice}`);
    } catch (err) {
      console.error("Manuel işlem açma hatası:", err);
    }
  };

  const activeSessions = sessions.filter((s) => s.active);

  return (
    <div className="space-y-6 pb-12 font-mono">
      {/* ÜST BAŞLIK & MASTER OTONOM KONTROL KARTI */}
      <div className="p-5 rounded-2xl bg-gradient-to-r from-blue-950/40 via-slate-900/70 to-indigo-950/40 border border-blue-500/30 backdrop-blur-md shadow-2xl flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div className="flex items-center gap-3.5">
          <div className="w-13 h-13 rounded-2xl bg-blue-500/20 border border-blue-400/40 flex items-center justify-center text-3xl shadow-[0_0_20px_rgba(59,130,246,0.35)]">
            🤖
          </div>
          <div>
            <div className="flex items-center gap-2.5">
              <h1 className="text-xl font-bold text-white tracking-tight">
                OTONOM FOREX SCALPER MOTORU
              </h1>
              <span
                className={`px-2.5 py-0.5 rounded-full text-[11px] font-bold border transition-all ${
                  autoEnabled
                    ? "bg-emerald-500/20 text-emerald-400 border-emerald-500/40 shadow-[0_0_12px_rgba(16,185,129,0.3)] animate-pulse"
                    : "bg-bunker-800 text-bunker-muted border-bunker-700"
                }`}
              >
                {autoEnabled ? "● ÇALIŞIYOR" : "○ DURDURULDU"}
              </span>
            </div>
            <p className="text-xs text-bunker-muted mt-1">
              M1 / M5 Çoklu Zaman Dilimi (MTF), Dinamik Başabaş (BE) & İz Süren Stop (Trailing SL)
            </p>
          </div>
        </div>

        {/* Master Eylemler */}
        <div className="flex items-center gap-2.5 flex-wrap">
          <button
            type="button"
            onClick={toggleAutoEngine}
            className={`px-4 py-2 rounded-xl font-bold text-xs border transition-all flex items-center gap-2 shadow-lg ${
              autoEnabled
                ? "bg-rose-500/20 text-rose-300 border-rose-500/40 hover:bg-rose-500/30 shadow-[0_0_15px_rgba(244,63,94,0.25)]"
                : "bg-emerald-500/25 text-emerald-300 border-emerald-400/50 hover:bg-emerald-500/35 shadow-[0_0_15px_rgba(16,185,129,0.3)]"
            }`}
          >
            <span>{autoEnabled ? "⏹ Otonomu Durdur" : "▶ Otonom Scalper'ı Başlat"}</span>
          </button>

          <button
            type="button"
            onClick={handleOpenSettings}
            className="px-3.5 py-2 rounded-xl bg-bunker-900 border border-bunker-700 text-white hover:border-blue-400 transition-all text-xs font-bold flex items-center gap-1.5"
          >
            <span>⚙️ Parametreler</span>
          </button>

          <button
            type="button"
            onClick={resetAccount}
            title="Hesabı Sıfırla"
            className="px-3 py-2 rounded-xl bg-bunker-900 border border-bunker-800 text-bunker-muted hover:text-rose-400 hover:border-rose-500/30 transition-all text-xs"
          >
            ↺ Sıfırla
          </button>
        </div>
      </div>

      {/* PARAMETRE AYARLARI PANELİ (Açılır/Kapanır) */}
      {showSettings && (
        <form
          onSubmit={saveSettings}
          className="p-5 rounded-2xl bg-bunker-900/95 border border-blue-500/40 shadow-2xl space-y-4 animate-in fade-in slide-in-from-top-2 duration-200"
        >
          <div className="flex items-center justify-between border-b border-bunker-800 pb-3">
            <div className="flex items-center gap-2">
              <span className="text-blue-400 font-bold">⚙️</span>
              <h3 className="text-sm font-bold text-white uppercase tracking-wider">
                Otonom Scalping Risk & Çıkış Parametreleri
              </h3>
            </div>
            <button
              type="button"
              onClick={() => setShowSettings(false)}
              className="text-xs text-bunker-muted hover:text-white"
            >
              ✕ Kapat
            </button>
          </div>

          {saveSuccessMsg && (
            <div className="p-3 rounded-xl bg-emerald-500/20 border border-emerald-500/40 text-emerald-300 text-xs font-bold flex items-center gap-2 animate-pulse">
              <span>{saveSuccessMsg}</span>
            </div>
          )}

          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-xs">
            <div>
              <label className="text-[11px] text-bunker-muted block mb-1">
                İşlem Başına Risk (%):
              </label>
              <input
                type="number"
                step="0.1"
                min="0.1"
                max="5.0"
                value={formSettings.risk_per_trade_pct ?? ""}
                onChange={(e) =>
                  updateFormField("risk_per_trade_pct", e.target.value === "" ? "" : parseFloat(e.target.value))
                }
                className="w-full bg-bunker-950 border border-bunker-700 rounded-lg px-2.5 py-1.5 text-white font-bold outline-none focus:border-blue-400"
              />
              <span className="text-[10px] text-bunker-muted">Dinamik lot büyüklüğünü belirler</span>
            </div>

            <div>
              <label className="text-[11px] text-bunker-muted block mb-1">
                Kâr Al (TP Pips):
              </label>
              <input
                type="number"
                min="5"
                max="100"
                value={formSettings.tp_pips ?? ""}
                onChange={(e) =>
                  updateFormField("tp_pips", e.target.value === "" ? "" : parseFloat(e.target.value))
                }
                className="w-full bg-bunker-950 border border-bunker-700 rounded-lg px-2.5 py-1.5 text-emerald-400 font-bold outline-none focus:border-blue-400"
              />
              <span className="text-[10px] text-bunker-muted">Hedeflenen scalp kârı</span>
            </div>

            <div>
              <label className="text-[11px] text-bunker-muted block mb-1">
                Zarar Durdur (SL Pips):
              </label>
              <input
                type="number"
                min="5"
                max="50"
                value={formSettings.sl_pips ?? ""}
                onChange={(e) =>
                  updateFormField("sl_pips", e.target.value === "" ? "" : parseFloat(e.target.value))
                }
                className="w-full bg-bunker-950 border border-bunker-700 rounded-lg px-2.5 py-1.5 text-rose-400 font-bold outline-none focus:border-blue-400"
              />
              <span className="text-[10px] text-bunker-muted">Maksimum kayıp mesafesi</span>
            </div>

            <div>
              <label className="text-[11px] text-bunker-muted block mb-1">
                Başabaş Kilit (BE Pips):
              </label>
              <input
                type="number"
                min="2"
                max="30"
                value={formSettings.breakeven_pips ?? ""}
                onChange={(e) =>
                  updateFormField("breakeven_pips", e.target.value === "" ? "" : parseFloat(e.target.value))
                }
                className="w-full bg-bunker-950 border border-bunker-700 rounded-lg px-2.5 py-1.5 text-cyan-300 font-bold outline-none focus:border-blue-400"
              />
              <span className="text-[10px] text-bunker-muted">+8 pips kârda stop girişe çekilir</span>
            </div>

            <div>
              <label className="text-[11px] text-bunker-muted block mb-1">
                İz Süren Stop (Trailing Pips):
              </label>
              <input
                type="number"
                min="4"
                max="40"
                value={formSettings.trailing_stop_pips ?? ""}
                onChange={(e) =>
                  updateFormField("trailing_stop_pips", e.target.value === "" ? "" : parseFloat(e.target.value))
                }
                className="w-full bg-bunker-950 border border-bunker-700 rounded-lg px-2.5 py-1.5 text-yellow-300 font-bold outline-none focus:border-blue-400"
              />
              <span className="text-[10px] text-bunker-muted">Trend uzarsa kârı adım adım korur</span>
            </div>

            <div>
              <label className="text-[11px] text-bunker-muted block mb-1">
                Min. Radar Skoru (50-98):
              </label>
              <input
                type="number"
                min="50"
                max="98"
                value={formSettings.min_score ?? ""}
                onChange={(e) =>
                  updateFormField("min_score", e.target.value === "" ? "" : parseFloat(e.target.value))
                }
                className="w-full bg-bunker-950 border border-bunker-700 rounded-lg px-2.5 py-1.5 text-white font-bold outline-none focus:border-blue-400"
              />
              <span className="text-[10px] text-bunker-muted">Yalnızca yüksek teyitli işlemler</span>
            </div>

            <div>
              <label className="text-[11px] text-bunker-muted block mb-1">
                Max. İzin Verilen Spread:
              </label>
              <input
                type="number"
                step="0.1"
                min="0.5"
                max="10.0"
                value={formSettings.max_spread_pips ?? ""}
                onChange={(e) =>
                  updateFormField("max_spread_pips", e.target.value === "" ? "" : parseFloat(e.target.value))
                }
                className="w-full bg-bunker-950 border border-bunker-700 rounded-lg px-2.5 py-1.5 text-white font-bold outline-none focus:border-blue-400"
              />
              <span className="text-[10px] text-bunker-muted">Spread yüksekse işlem açılmaz</span>
            </div>

            <div>
              <label className="text-[11px] text-bunker-muted block mb-1">
                Max. Açık İşlem (1-10):
              </label>
              <input
                type="number"
                min="1"
                max="10"
                value={formSettings.max_open_positions ?? ""}
                onChange={(e) =>
                  updateFormField("max_open_positions", e.target.value === "" ? "" : parseInt(e.target.value))
                }
                className="w-full bg-bunker-950 border border-bunker-700 rounded-lg px-2.5 py-1.5 text-white font-bold outline-none focus:border-blue-400"
              />
              <span className="text-[10px] text-bunker-muted">Aynı anda açık en fazla pozisyon</span>
            </div>

            <div className="flex flex-col justify-center col-span-2">
              <label className="text-[11px] text-bunker-muted block mb-2">
                Hafta Sonu Kalkanı:
              </label>
              <label className="inline-flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={formSettings.session_filter}
                  onChange={(e) =>
                    updateFormField("session_filter", e.target.checked)
                  }
                  className="rounded bg-bunker-950 border-bunker-700 text-blue-500 focus:ring-0 w-4 h-4"
                />
                <span className="text-white text-xs font-semibold">
                  Sadece Piyasa Açıkken İşlem Yap
                </span>
              </label>
              <span className="text-[10px] text-emerald-400 mt-1 font-bold">
                ✓ Asya (Tokyo & Sydney) seansı dahil tüm seanslarda işlem serbest
              </span>
            </div>

            {/* İZİN VERİLEN PARİTELER VE EMTİALAR */}
            <div className="col-span-2 md:col-span-4 pt-3 border-t border-bunker-800">
              <div className="flex items-center justify-between mb-2">
                <label className="text-[11px] text-bunker-muted font-bold">
                  İşlem Yapılacak Pariteler ({formSettings.allowed_symbols?.length || 0} Seçili):
                </label>
                <div className="flex gap-2 text-[10px]">
                  <button
                    type="button"
                    onClick={() =>
                      updateFormField("allowed_symbols", [
                        "EURUSD", "GBPUSD", "USDJPY", "XAUUSD", "USDCAD", "AUDUSD", "USDCHF", "NZDUSD", "XAGUSD", "USOIL"
                      ])
                    }
                    className="text-blue-400 hover:underline"
                  >
                    Tümünü Seç
                  </button>
                  <span className="text-bunker-700">|</span>
                  <button
                    type="button"
                    onClick={() => updateFormField("allowed_symbols", ["EURUSD", "GBPUSD", "USDJPY"])}
                    className="text-bunker-muted hover:underline"
                  >
                    Sadece Majörler
                  </button>
                </div>
              </div>
              <div className="flex flex-wrap gap-1.5">
                {[
                  { sym: "EURUSD", label: "EUR/USD" },
                  { sym: "GBPUSD", label: "GBP/USD" },
                  { sym: "USDJPY", label: "USD/JPY" },
                  { sym: "XAUUSD", label: "Altın (XAU)" },
                  { sym: "USDCAD", label: "USD/CAD" },
                  { sym: "AUDUSD", label: "AUD/USD" },
                  { sym: "USDCHF", label: "USD/CHF" },
                  { sym: "NZDUSD", label: "NZD/USD" },
                  { sym: "XAGUSD", label: "Gümüş (XAG)" },
                  { sym: "USOIL", label: "Petrol (WTI)" },
                ].map((item) => {
                  const active = formSettings.allowed_symbols?.includes(item.sym);
                  return (
                    <button
                      key={item.sym}
                      type="button"
                      onClick={() => toggleSymbol(item.sym)}
                      className={`px-2 py-1 rounded-md text-[11px] font-bold transition-all border ${
                        active
                          ? "bg-blue-600/30 text-blue-300 border-blue-400/50 shadow-sm"
                          : "bg-bunker-950/70 text-bunker-muted border-bunker-800 hover:border-bunker-700 hover:text-white"
                      }`}
                    >
                      {active ? "✓ " : "+ "}
                      {item.label}
                    </button>
                  );
                })}
              </div>
            </div>
          </div>

          <div className="flex justify-end gap-2 pt-2 border-t border-bunker-800">
            <button
              type="button"
              onClick={() => setShowSettings(false)}
              className="px-3 py-1.5 rounded-lg bg-bunker-800 text-bunker-muted hover:text-white text-xs"
            >
              Vazgeç
            </button>
            <button
              type="submit"
              disabled={isSavingSettings}
              className="px-4 py-1.5 rounded-lg bg-blue-600 hover:bg-blue-500 text-white font-bold text-xs shadow-md transition-all disabled:opacity-50"
            >
              {isSavingSettings ? "Kaydediliyor…" : "Kaydet ve Uygula"}
            </button>
          </div>
        </form>
      )}

      {/* PERFORMANS VE HESAP METRİKLERİ KARTLARI */}
      <div className="grid grid-cols-2 md:grid-cols-6 gap-3">
        <div className="p-3.5 rounded-xl bg-bunker-900/80 border border-bunker-800">
          <span className="text-[10px] text-bunker-muted uppercase block">Hesap Bakiyesi</span>
          <span className="text-lg font-bold text-white">${balance.toFixed(2)}</span>
        </div>

        <div className="p-3.5 rounded-xl bg-bunker-900/80 border border-bunker-800">
          <span className="text-[10px] text-bunker-muted uppercase block">Özsermaye (Equity)</span>
          <span
            className={`text-lg font-bold ${
              equity >= balance ? "text-emerald-400" : "text-rose-400"
            }`}
          >
            ${equity.toFixed(2)}
          </span>
        </div>

        <div className="p-3.5 rounded-xl bg-bunker-900/80 border border-bunker-800">
          <span className="text-[10px] text-bunker-muted uppercase block">Açık PnL (Anlık)</span>
          <span
            className={`text-lg font-bold ${
              openPnlUsd >= 0 ? "text-emerald-400" : "text-rose-400"
            }`}
          >
            {openPnlUsd >= 0 ? "+" : ""}${openPnlUsd.toFixed(2)}
            <span className="text-xs ml-1 font-normal opacity-80">
              ({openPnlPips >= 0 ? "+" : ""}{openPnlPips}p)
            </span>
          </span>
        </div>

        <div className="p-3.5 rounded-xl bg-bunker-900/80 border border-bunker-800">
          <span className="text-[10px] text-bunker-muted uppercase block">Net Kâr / Zarar</span>
          <span
            className={`text-lg font-bold ${
              realizedPnlUsd >= 0 ? "text-emerald-400" : "text-rose-400"
            }`}
          >
            {realizedPnlUsd >= 0 ? "+" : ""}${realizedPnlUsd.toFixed(2)}
            <span className="text-xs ml-1 font-normal opacity-80">
              ({realizedPnlPips >= 0 ? "+" : ""}{realizedPnlPips}p)
            </span>
          </span>
        </div>

        <div className="p-3.5 rounded-xl bg-bunker-900/80 border border-bunker-800">
          <span className="text-[10px] text-bunker-muted uppercase block">Kazanma Oranı</span>
          <span className="text-lg font-bold text-cyan-300">
            %{winRate.toFixed(1)}
            <span className="text-[11px] text-bunker-muted ml-1 font-normal">
              ({wins}W / {losses}L)
            </span>
          </span>
        </div>

        <div className="p-3.5 rounded-xl bg-bunker-900/80 border border-bunker-800">
          <span className="text-[10px] text-bunker-muted uppercase block">Aktif Seanslar</span>
          <div className="flex items-center gap-1 mt-1 overflow-x-auto">
            {activeSessions.length > 0 ? (
              activeSessions.map((s) => (
                <span
                  key={s.name}
                  className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-emerald-500/15 text-emerald-400 border border-emerald-500/30"
                >
                  {s.flag} {s.name}
                </span>
              ))
            ) : (
              <span className="text-[11px] text-bunker-muted">Kapalı (Asya / Rollover)</span>
            )}
          </div>
        </div>
      </div>

      {/* AÇIK OTONOM POZİSYONLAR */}
      <div className="rounded-2xl border border-bunker-800 bg-bunker-900/70 overflow-hidden shadow-xl">
        <div className="p-4 border-b border-bunker-800 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="text-lg">⚡</span>
            <h2 className="text-sm font-bold text-white uppercase tracking-wider">
              Açık Otonom Pozisyonlar ({openPositions.length} / {appliedSettings.max_open_positions})
            </h2>
          </div>
          <span className="text-xs text-blue-400 font-bold animate-pulse">
            {autoEnabled ? "Canlı Takip Devrede" : "Otonom Beklemede"}
          </span>
        </div>

        {openPositions.length === 0 ? (
          <div className="p-12 text-center text-bunker-muted text-xs">
            {autoEnabled
              ? "Şu an açık bir Forex pozisyonu yok. Sistem radar sinyallerini ve seans şartlarını denetliyor…"
              : "Otonom motor şu an durdurulmuş durumda. Başlatmak için yukarıdaki butonu kullanabilirsiniz."}
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
                  <th className="py-3 px-3">Giriş</th>
                  <th className="py-3 px-3">Güncel</th>
                  <th className="py-3 px-3">Dinamik SL</th>
                  <th className="py-3 px-3">Hedef (TP)</th>
                  <th className="py-3 px-3">Kâr (Pips)</th>
                  <th className="py-3 px-3">PnL ($)</th>
                  <th className="py-3 px-4 text-right">Aksiyon</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-bunker-800/60">
                {openPositions.map((pos) => {
                  const isProfit = pos.pnl_usd >= 0;
                  return (
                    <tr key={pos.id} className="hover:bg-bunker-800/40 transition-colors">
                      <td className="py-3.5 px-4 text-bunker-muted text-[11px]">{pos.id}</td>
                      <td className="py-3.5 px-3">
                        <span className="font-bold text-white text-sm">{pos.display}</span>
                        <div className="text-[10px] text-bunker-muted">{pos.open_time}</div>
                      </td>
                      <td className="py-3.5 px-3">
                        <span
                          className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                            pos.direction === "BUY"
                              ? "bg-emerald-500/15 text-emerald-400 border border-emerald-500/30"
                              : "bg-rose-500/15 text-rose-400 border border-rose-500/30"
                          }`}
                        >
                          {pos.direction}
                        </span>
                      </td>
                      <td className="py-3.5 px-3 font-semibold text-white">{pos.lots} Lot</td>
                      <td className="py-3.5 px-3 text-bunker-muted">{pos.entry_price}</td>
                      <td className="py-3.5 px-3 font-bold text-white">{pos.current_price}</td>
                      <td className="py-3.5 px-3">
                        <div className="flex items-center gap-1.5">
                          <span className="font-mono text-rose-300">{pos.sl_price}</span>
                          {pos.breakeven_activated && (
                            <span
                              className="px-1.5 py-0.2 rounded text-[9px] font-bold bg-cyan-500/20 text-cyan-300 border border-cyan-400/40"
                              title="Başabaş kilitlendi, sermaye risksiz!"
                            >
                              BE 🛡️
                            </span>
                          )}
                          {pos.trailing_activated && (
                            <span
                              className="px-1.5 py-0.2 rounded text-[9px] font-bold bg-yellow-500/20 text-yellow-300 border border-yellow-400/40"
                              title="İz süren stop aktif"
                            >
                              TRAIL 📈
                            </span>
                          )}
                        </div>
                      </td>
                      <td className="py-3.5 px-3 text-emerald-300 font-mono">{pos.tp_price}</td>
                      <td
                        className={`py-3.5 px-3 font-bold ${
                          pos.pnl_pips >= 0 ? "text-emerald-400" : "text-rose-400"
                        }`}
                      >
                        {pos.pnl_pips >= 0 ? "+" : ""}
                        {pos.pnl_pips} p
                      </td>
                      <td
                        className={`py-3.5 px-3 font-bold text-sm ${
                          isProfit ? "text-emerald-400" : "text-rose-400"
                        }`}
                      >
                        {isProfit ? "+" : ""}
                        ${pos.pnl_usd.toFixed(2)}
                      </td>
                      <td className="py-3.5 px-4 text-right">
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

      {/* KARAR GÜNLÜĞÜ (DECISION STREAM) VE GEÇMİŞ İŞLEMLER */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Canlı Otonom Karar & Tarama Günlüğü */}
        <div className="rounded-2xl border border-bunker-800 bg-bunker-900/70 p-4 shadow-xl flex flex-col h-[420px]">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between border-b border-bunker-800 pb-2.5 mb-2 gap-2">
            <div className="flex items-center gap-2">
              <span className="text-base">📜</span>
              <h3 className="text-xs font-bold text-white uppercase tracking-wider">
                Otonom Karar & Tarama Akışı (Decision Stream)
              </h3>
            </div>
            <span className="text-[10px] text-bunker-muted">
              {decisionLogs.length} Olay Kaydedildi
            </span>
          </div>

          {/* Kategori Filtre Butonları */}
          <div className="flex items-center gap-1.5 overflow-x-auto pb-2 mb-2 border-b border-bunker-800/60 scrollbar-none text-[10px]">
            {[
              { id: "ALL", label: "Tümü", icon: "🌐" },
              { id: "SCAN", label: "Taramalar", icon: "🔍" },
              { id: "ENTRY", label: "Girişler", icon: "⚡" },
              { id: "PROTECT", label: "Koruma", icon: "🛡️" },
              { id: "EXIT", label: "Çıkışlar", icon: "🎯" },
              { id: "GATE", label: "Engeller", icon: "⛔" },
            ].map((tab) => {
              const count =
                tab.id === "ALL"
                  ? decisionLogs.length
                  : decisionLogs.filter((l) => l.category === tab.id).length;
              return (
                <button
                  key={tab.id}
                  type="button"
                  onClick={() => setLogFilter(tab.id)}
                  className={`px-2 py-1 rounded-md transition-all font-bold whitespace-nowrap flex items-center gap-1 ${
                    logFilter === tab.id
                      ? "bg-blue-600/30 text-blue-300 border border-blue-400/40 shadow-sm"
                      : "bg-bunker-950/60 text-bunker-muted hover:text-white border border-transparent"
                  }`}
                >
                  <span>{tab.icon}</span>
                  <span>{tab.label}</span>
                  <span className="opacity-70 text-[9px]">({count})</span>
                </button>
              );
            })}
          </div>

          <div className="flex-1 overflow-y-auto space-y-2 pr-1 text-xs">
            {(() => {
              const filtered =
                logFilter === "ALL"
                  ? decisionLogs
                  : decisionLogs.filter((l) => l.category === logFilter);

              if (filtered.length === 0) {
                return (
                  <div className="text-center py-14 text-bunker-muted text-xs">
                    Bu filtreye ait bir kayıt henüz bulunmuyor.
                  </div>
                );
              }

              const catColors: Record<string, string> = {
                SCAN: "border-sky-500/30 bg-sky-500/10 text-sky-200",
                ENTRY: "border-emerald-500/30 bg-emerald-500/10 text-emerald-300",
                EXIT: "border-blue-500/30 bg-blue-500/10 text-blue-300",
                PROTECT: "border-cyan-500/30 bg-cyan-500/10 text-cyan-300",
                GATE: "border-amber-500/30 bg-amber-500/10 text-amber-300",
                SYSTEM: "border-bunker-700 bg-bunker-800/40 text-bunker-muted",
              };

              const catIcons: Record<string, string> = {
                SCAN: "🔍",
                ENTRY: "⚡",
                EXIT: "🎯",
                PROTECT: "🛡️",
                GATE: "⛔",
                SYSTEM: "⚙️",
              };

              return filtered.map((log) => {
                const icon = catIcons[log.category] || "•";
                return (
                  <div
                    key={log.id}
                    className={`p-2 rounded-lg border text-[11px] leading-relaxed flex items-start justify-between gap-2 transition-all ${
                      catColors[log.category] || "border-bunker-800 bg-bunker-900"
                    }`}
                  >
                    <div>
                      <span className="font-bold mr-1.5 uppercase tracking-wider text-[10px]">
                        {icon} [{log.category}]
                      </span>
                      <span>{log.message}</span>
                    </div>
                    <span className="text-[10px] opacity-70 whitespace-nowrap">{log.time}</span>
                  </div>
                );
              });
            })()}
          </div>
        </div>

        {/* Kapanan İşlemler Geçmişi */}
        <div className="rounded-2xl border border-bunker-800 bg-bunker-900/70 p-4 shadow-xl flex flex-col h-[420px]">
          <div className="flex items-center justify-between border-b border-bunker-800 pb-3 mb-2">
            <div className="flex items-center gap-2">
              <span className="text-base">🏁</span>
              <h3 className="text-xs font-bold text-white uppercase tracking-wider">
                Kapanan Scalp İşlemleri ({closedTrades.length})
              </h3>
            </div>
            <span className="text-[10px] text-bunker-muted">Net Kazanç / Kayıp</span>
          </div>

          <div className="flex-1 overflow-y-auto space-y-2 pr-1 text-xs">
            {closedTrades.length === 0 ? (
              <div className="text-center py-10 text-bunker-muted">
                Henüz kapanmış bir işlem bulunmuyor.
              </div>
            ) : (
              closedTrades.map((tr) => {
                const isWin = tr.pnl_usd >= 0;
                return (
                  <div
                    key={tr.id}
                    className="p-2.5 rounded-lg border border-bunker-800 bg-bunker-950/60 flex items-center justify-between hover:border-bunker-700 transition-colors"
                  >
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="font-bold text-white text-xs">{tr.display}</span>
                        <span
                          className={`px-1.5 py-0.2 rounded text-[9px] font-bold ${
                            tr.direction === "BUY"
                              ? "bg-emerald-500/15 text-emerald-400"
                              : "bg-rose-500/15 text-rose-400"
                          }`}
                        >
                          {tr.direction}
                        </span>
                        <span className="text-[10px] text-bunker-muted">{tr.lots} Lot</span>
                        <span className="text-[10px] px-1.5 py-0.2 rounded bg-bunker-800 text-bunker-muted">
                          {tr.exit_reason}
                        </span>
                      </div>
                      <div className="text-[10px] text-bunker-muted mt-0.5">
                        Giriş: {tr.entry_price} → Çıkış: {tr.exit_price} ({tr.exit_time})
                      </div>
                    </div>

                    <div className="text-right">
                      <div
                        className={`font-bold text-xs ${
                          isWin ? "text-emerald-400" : "text-rose-400"
                        }`}
                      >
                        {isWin ? "+" : ""}${tr.pnl_usd.toFixed(2)}
                      </div>
                      <div
                        className={`text-[10px] ${
                          tr.pnl_pips >= 0 ? "text-emerald-400" : "text-rose-400"
                        }`}
                      >
                        {tr.pnl_pips >= 0 ? "+" : ""}
                        {tr.pnl_pips} p
                      </div>
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </div>
      </div>

      {/* ALT BAĞLANTILAR */}
      <div className="flex items-center justify-between text-xs text-bunker-muted pt-2 border-t border-bunker-800">
        <Link href="/forex" className="hover:text-blue-400 transition-colors">
          ← Forex Radar & Canlı Piyasa
        </Link>
        <Link href="/forex/technical-charts" className="hover:text-blue-400 transition-colors">
          4'lü TradingView Çoklu Ekran →
        </Link>
      </div>
    </div>
  );
}
