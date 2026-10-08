"use client";

import React, { useState, useEffect } from "react";
import Link from "next/link";
import { apiFetch } from "../../lib/api";
import { formatUtc3 } from "../../lib/format";

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
  created_at_ts?: number;
  category: "ENTRY" | "EXIT" | "PROTECT" | "GATE" | "SYSTEM" | "SCAN";
  symbol?: string;
  message: string;
  metadata?: any;
}

interface MT5State {
  connected: boolean;
  last_ping_seconds_ago: number | null;
  auto_trade: boolean;
  account: {
    login: number;
    name: string;
    server: string;
    balance: number;
    equity: number;
    margin: number;
    free_margin: number;
    leverage: number;
    currency: string;
  };
  open_positions: Array<{
    ticket: number;
    symbol: string;
    direction: "BUY" | "SELL";
    lots: number;
    entry_price: number;
    current_price: number;
    sl_price: number;
    tp_price: number;
    pnl_usd: number;
    pnl_pips?: number;
    protection?: "TRAILING" | "BREAKEVEN" | "NORMAL";
    protection_label?: string;
    breakeven_activated?: boolean;
    trailing_activated?: boolean;
    open_time: string;
    strategy?: string;
    strategy_label?: string;
  }>;
  closed_deals: Array<{
    ticket: number;
    symbol: string;
    direction: "BUY" | "SELL";
    lots: number;
    price: number;
    profit: number;
    commission: number;
    time: string;
    strategy?: string;
    strategy_label?: string;
  }>;
  pending_commands_count: number;
}

export default function ForexPortfolioPage({ symbols, title }: { symbols?: string[]; title?: string } = {}) {
  // symbols verilirse bu sayfa YALNIZ bu sembolleri gösterir (aynı konsol, daraltılmış görünüm).
  // İşlem izni backend'deki allowed_symbols ile yönetilir — bu filtre yalnızca görünümdür.
  const symFilter: Set<string> | null = symbols ? new Set(symbols.map((s) => s.toUpperCase())) : null;
  // IC Markets MT5 Canlı Köprü Durumu
  const [mt5, setMt5] = useState<MT5State>({
    connected: false,
    last_ping_seconds_ago: null,
    auto_trade: false,
    account: {
      login: 53077151,
      name: "ERKAN ERDEM",
      server: "ICMarketsSC-Demo",
      balance: 1000.0,
      equity: 1000.0,
      margin: 0.0,
      free_margin: 1000.0,
      leverage: 5000,
      currency: "USD",
    },
    open_positions: [],
    closed_deals: [],
    pending_commands_count: 0,
  });
  const [isTogglingMt5, setIsTogglingMt5] = useState(false);
  const [mt5Message, setMt5Message] = useState<string | null>(null);
  const [showMt5Guide, setShowMt5Guide] = useState(false);

  // Otonom Sistem Durumu
  const [autoStatus, setAutoStatus] = useState<string>("Yükleniyor…");
  const [autoEnabled, setAutoEnabled] = useState<boolean>(false);
  const [balance, setBalance] = useState<number>(1000.0);
  const [equity, setEquity] = useState<number>(1000.0);
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

  // Parametre paneli 2026-10-07'de /forex/ayarlar sayfasına taşındı —
  // bu sayfa yalnızca izler, motor ayarlarını düzenlemez.
  const [showManualForm, setShowManualForm] = useState(false);

  // Manuel İşlem Formu (symbols verilirse varsayılan ilk izinli sembol olur)
  const [manualSym, setManualSym] = useState(symbols && symbols.length ? symbols[0] : "EURUSD");
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
        setOpenPositions((res.open_positions || []).filter(
          (p: AutoPosition) => !symFilter || symFilter.has(String(p.symbol).toUpperCase())
        ));
        setClosedTrades((res.closed_trades || []).filter(
          (t: ClosedTrade) => !symFilter || symFilter.has(String(t.symbol).toUpperCase())
        ));
        // Sembolsüz global mesajlar (SCAN özeti, SYSTEM) kalır; filtre dışı sembollü satırlar gizlenir
        setDecisionLogs((res.decision_logs || []).filter(
          (l: DecisionLog) => !symFilter || !l.symbol || symFilter.has(String(l.symbol).toUpperCase())
        ));
        setSessions(res.sessions || []);
      }
    } catch (err) {
      console.error("Forex auto-paper status alınamadı:", err);
    }

    try {
      const mt5Res = await apiFetch("/api/forex/mt5/status");
      if (mt5Res) {
        setMt5(mt5Res);
      }
    } catch (err) {
      // MT5 köprüsü sorgulama
    }
  };

  useEffect(() => {
    fetchStatus();
    const interval = setInterval(fetchStatus, 1500);
    return () => clearInterval(interval);
  }, []);

  // MT5 Otomatik Emir İletimini Aç / Kapat
  const toggleMt5Auto = async () => {
    setIsTogglingMt5(true);
    try {
      const nextState = !mt5.auto_trade;
      const res = await apiFetch("/api/forex/mt5/toggle-auto", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ auto_trade: nextState }),
      });
      if (res) {
        setMt5((prev) => ({ ...prev, auto_trade: res.auto_trade }));
        setMt5Message(
          res.auto_trade
            ? "⚡ IC Markets MT5 otomatik emir iletimi AÇILDI. Scalper sinyalleri gerçek MT5 Demo hesabınızda açılacak."
            : "🛑 IC Markets MT5 otomatik emir iletimi DURDURULDU."
        );
        setTimeout(() => setMt5Message(null), 5000);
      }
    } catch (err) {
      console.error("MT5 toggle hatası:", err);
    } finally {
      setIsTogglingMt5(false);
    }
  };

  // MT5 Belirli Bileti Kapat
  const closeMt5Ticket = async (ticket: number) => {
    if (!confirm(`Bilet #${ticket} nolu IC Markets MT5 pozisyonunu kapatmak istiyor musunuz?`)) return;
    try {
      await apiFetch("/api/forex/mt5/close", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ticket }),
      });
      setMt5Message(`Bilet #${ticket} kapatma emri MT5 köprüsüne iletildi.`);
      setTimeout(() => setMt5Message(null), 4000);
      fetchStatus();
    } catch (err) {
      console.error("MT5 close hatası:", err);
    }
  };

  // Tüm MT5 Pozisyonlarını Tek Tıkla Kapat
  const closeAllMt5Positions = async () => {
    const count = mt5.open_positions?.length || 0;
    if (!confirm(`Açık olan TÜM (${count}) IC Markets MT5 pozisyonunu tek seferde kapatmak istiyor musunuz?`)) return;
    try {
      await apiFetch("/api/forex/mt5/close-all", {
        method: "POST",
      });
      setMt5Message(`🛑 Tüm (${count}) MT5 pozisyonunu kapatma emri köprüye iletildi.`);
      setTimeout(() => setMt5Message(null), 5000);
      fetchStatus();
    } catch (err) {
      console.error("MT5 close-all hatası:", err);
    }
  };

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

  // Kapanan İşlemleri CSV Olarak İndir
  const downloadCsv = () => {
    try {
      const headers = [
        "Bilet No",
        "Parite",
        "Sembol",
        "Yön",
        "Lot",
        "Giriş Fiyatı",
        "Çıkış Fiyatı",
        "Kapanış Zamanı (UTC+3)",
        "Çıkış Nedeni",
        "Kâr/Zarar (Pip)",
        "Net Getiri (USD)",
        "Sonuç",
      ];
      const rows = closedTrades.map((t) => [
        t.id,
        t.display || t.symbol,
        t.symbol,
        t.direction,
        t.lots,
        t.entry_price,
        t.exit_price,
        formatUtc3(t.exit_time),
        t.exit_reason,
        `${t.pnl_pips >= 0 ? "+" : ""}${t.pnl_pips}`,
        `${t.pnl_usd >= 0 ? "+" : ""}${t.pnl_usd.toFixed(2)}`,
        t.pnl_usd >= 0 ? "KAZANÇ (WIN)" : "KAYIP (LOSS)",
      ]);
      const csvContent =
        "\uFEFF" +
        [headers.join(";"), ...rows.map((r) => r.map((cell) => `"${cell}"`).join(";"))].join("\r\n");
      const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      const dateStr = new Date().toISOString().slice(0, 10);
      link.setAttribute("href", url);
      link.setAttribute("download", `forex_scalper_kapanan_islemler_${dateStr}.csv`);
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);
    } catch (e) {
      console.error("CSV indirme hatası:", e);
      alert("CSV indirilirken bir hata oluştu.");
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
      <div className="p-5 rounded-2xl bg-white dark:bg-gradient-to-r dark:from-emerald-950/40 dark:via-bunker-900/90 dark:to-blue-950/40 border border-slate-300 dark:border-emerald-500/40 shadow-sm dark:shadow-2xl flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div className="flex items-center gap-3.5">
          <div className="w-13 h-13 rounded-2xl bg-emerald-500/15 border border-emerald-500/30 flex items-center justify-center text-3xl shadow-[0_0_20px_rgba(16,185,129,0.2)]">
            🤖
          </div>
          <div>
            <div className="flex items-center gap-2 flex-wrap">
              <h1 className="text-xl font-black text-slate-900 dark:text-white tracking-tight">
                {title || "IC MARKETS MT5 · MERKEZİ OTONOM İZLEME"}
              </h1>
              <span
                className={`px-2.5 py-0.5 rounded-full text-[11px] font-bold border transition-all ${
                  autoEnabled
                    ? "bg-emerald-50 text-emerald-800 border-emerald-400 dark:bg-emerald-500/20 dark:text-emerald-400 dark:border-emerald-500/40 shadow-sm animate-pulse"
                    : "bg-slate-100 text-slate-700 border-slate-300 dark:bg-bunker-800 dark:text-bunker-muted dark:border-bunker-700"
                }`}
              >
                {autoEnabled ? "● OTONOM ÇALIŞIYOR" : "○ OTONOM DURDURULDU"}
              </span>
              <span
                className={`px-2.5 py-0.5 rounded-full text-[10px] font-bold border ${
                  mt5.connected
                    ? "bg-emerald-50 text-emerald-800 border-emerald-400 dark:bg-emerald-500/20 dark:text-emerald-300 dark:border-emerald-500/40"
                    : "bg-rose-50 text-rose-800 border-rose-300 dark:bg-rose-500/20 dark:text-rose-300 dark:border-rose-500/40"
                }`}
              >
                {mt5.connected
                  ? `🟢 MT5 KÖPRÜ BAĞLI (${mt5.last_ping_seconds_ago !== null ? `${mt5.last_ping_seconds_ago}s önce` : "Canlı"})`
                  : "⚪ MT5 KÖPRÜSÜ ÇEVRİMDIŞI"}
              </span>
            </div>
            <p className="text-xs text-slate-700 dark:text-bunker-muted font-semibold mt-1">
              Tüm sembollerin merkezi otonom izleme konsolu · Hesap: <span className="text-sky-600 dark:text-cyan-300 font-bold font-mono">{mt5.account?.login || 53077151}</span> ({mt5.account?.server || "ICMarketsSC-Demo"}) · Sahip: <span className="text-slate-900 dark:text-white font-bold">{mt5.account?.name || "ERKAN ERDEM"}</span> · M1 / M5 Çoklu Zaman Dilimi & Dinamik SL
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

          {mt5.open_positions && mt5.open_positions.length > 0 && (
            <button
              type="button"
              onClick={closeAllMt5Positions}
              className="px-3.5 py-2 rounded-xl bg-rose-600/25 border border-rose-500/50 text-rose-300 hover:bg-rose-600/40 transition-all text-xs font-bold flex items-center gap-1.5 shadow-sm"
            >
              <span>🛑 Tüm MT5 Pozisyonlarını Kapat ({mt5.open_positions.length})</span>
            </button>
          )}

          <button
            type="button"
            onClick={() => setShowMt5Guide(!showMt5Guide)}
            className="px-3 py-2 rounded-xl bg-bunker-900 border border-bunker-800 text-bunker-muted hover:text-blue-400 text-xs flex items-center gap-1"
          >
            <span>ℹ️ Rehber</span>
          </button>
        </div>
      </div>

      {/* Rehber / Yardım Paneli */}
      {showMt5Guide && (
        <div className="p-4 rounded-xl bg-bunker-950 border border-blue-500/30 text-xs text-bunker-muted space-y-2">
          <div className="font-bold text-white flex items-center gap-1.5">
            <span>🚀 IC Markets MT5 Köprüsü Nasıl Çalışır?</span>
          </div>
          <ol className="list-decimal list-inside space-y-1.5 text-[11px] leading-relaxed">
            <li>Bilgisayarınızda proje klasöründeki <span className="text-emerald-400 font-mono font-bold">run_mt5_bridge.bat</span> dosyasını çift tıklayarak çalıştırın.</li>
            <li>Açılan konsol penceresi, bilgisayarınızdaki IC Markets MT5 terminaline otomatik olarak bağlanır (<span className="text-cyan-300 font-mono">53077151</span> hesabı).</li>
            <li>MetaTrader 5 terminalinde üst menüdeki <span className="text-yellow-400 font-bold">&quot;Algo Trading&quot; (Otomatik İşlem)</span> butonunun yeşil yandığından emin olun (Komut dosyasında otomatik yapılandırıldı).</li>
            <li>Yukarıdaki <span className="text-emerald-400 font-bold">&quot;Otonom Scalper&apos;ı Başlat&quot;</span> butonuna bastığınızda, sistemin tespit ettiği tüm teyitli sinyaller doğrudan IC Markets demo hesabınızda canlı piyasa emri olarak açılır, kârda başabaş (BE) ve dinamik iz süren stop (Trailing) uygulanır!</li>
          </ol>
        </div>
      )}

      {/* IC MARKETS MT5 CANLI METRİKLERİ */}
      {(() => {
        const liveBal = Number(mt5.account?.balance ?? balance ?? 1000.0);
        const liveEq = Number(mt5.account?.equity ?? liveBal);
        const liveMargin = Number(mt5.account?.free_margin ?? liveBal);
        const livePnl = (mt5.open_positions || []).reduce((acc, p) => acc + Number(p.pnl_usd ?? (p as any).profit ?? 0), 0);
        return (
          <div className="grid grid-cols-2 md:grid-cols-6 gap-3">
            <div className="p-3.5 rounded-xl bg-white dark:bg-bunker-900/80 border border-slate-300 dark:border-bunker-800 shadow-sm">
              <span className="text-[11px] font-bold text-slate-700 dark:text-bunker-muted uppercase block">IC Markets Bakiye</span>
              <span className="text-lg font-black text-emerald-600 dark:text-emerald-400 font-mono">
                ${liveBal.toFixed(2)} <span className="text-xs font-normal text-slate-500 dark:text-bunker-muted">{mt5.account?.currency || "USD"}</span>
              </span>
              <span className="text-[10px] font-semibold text-slate-600 dark:text-bunker-muted block mt-0.5">Kapanan net MT5 bakiye</span>
            </div>

            <div className="p-3.5 rounded-xl bg-white dark:bg-bunker-900/80 border border-slate-300 dark:border-bunker-800 shadow-sm">
              <span className="text-[11px] font-bold text-slate-700 dark:text-bunker-muted uppercase block">Özsermaye (Equity)</span>
              <span className={`text-lg font-black font-mono ${liveEq >= liveBal ? "text-sky-600 dark:text-cyan-300" : "text-rose-600 dark:text-rose-400"}`}>
                ${liveEq.toFixed(2)}
              </span>
              <span className="text-[10px] font-semibold text-slate-600 dark:text-bunker-muted block mt-0.5">Serbest: ${liveMargin.toFixed(2)}</span>
            </div>

            <div className="p-3.5 rounded-xl bg-white dark:bg-bunker-900/80 border border-slate-300 dark:border-bunker-800 shadow-sm">
              <span className="text-[11px] font-bold text-slate-700 dark:text-bunker-muted uppercase block">Açık MT5 PnL (Anlık)</span>
              <span className={`text-lg font-black font-mono ${livePnl >= 0 ? "text-emerald-600 dark:text-emerald-400" : "text-rose-600 dark:text-rose-400"}`}>
                {livePnl >= 0 ? "+" : ""}${livePnl.toFixed(2)}
              </span>
              <span className="text-[10px] font-semibold text-slate-600 dark:text-bunker-muted block mt-0.5">{mt5.open_positions?.length || 0} açık MT5 işlemi</span>
            </div>

            <div className="p-3.5 rounded-xl bg-white dark:bg-bunker-900/80 border border-slate-300 dark:border-bunker-800 shadow-sm">
              <span className="text-[11px] font-bold text-slate-700 dark:text-bunker-muted uppercase block">Hesap / Sunucu</span>
              <span className="text-base font-black text-slate-900 dark:text-white tracking-wide">
                {mt5.account?.login || 53077151}
              </span>
              <span className="text-[10px] font-bold text-emerald-700 dark:text-emerald-400 block mt-0.5 truncate">{mt5.account?.server || "ICMarketsSC-Demo"}</span>
            </div>

            <div className="p-3.5 rounded-xl bg-white dark:bg-bunker-900/80 border border-slate-300 dark:border-bunker-800 shadow-sm">
              <span className="text-[11px] font-bold text-slate-700 dark:text-bunker-muted uppercase block">Kaldıraç & Sahip</span>
              <span className="text-base font-black text-amber-600 dark:text-yellow-300">
                1:{mt5.account?.leverage || 5000}
              </span>
              <span className="text-[10px] font-bold text-slate-800 dark:text-bunker-muted block mt-0.5 truncate">{mt5.account?.name || "ERKAN ERDEM"}</span>
            </div>

            <div className="p-3.5 rounded-xl bg-white dark:bg-bunker-900/80 border border-slate-300 dark:border-bunker-800 shadow-sm">
              <span className="text-[11px] font-bold text-slate-700 dark:text-bunker-muted uppercase block">Aktif Seanslar</span>
              <div className="flex items-center gap-1 mt-1 overflow-x-auto">
                {activeSessions.length > 0 ? (
                  activeSessions.map((s) => (
                    <span
                      key={s.name}
                      className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-emerald-50 text-emerald-800 border border-emerald-300 dark:bg-emerald-500/15 dark:text-emerald-400 dark:border-emerald-500/30 whitespace-nowrap"
                    >
                      {s.flag} {s.name}
                    </span>
                  ))
                ) : (
                  <span className="text-[11px] font-semibold text-slate-600 dark:text-bunker-muted">24/5 Açık</span>
                )}
              </div>
            </div>
          </div>
        );
      })()}

      {/* CANLI IC MARKETS MT5 AÇIK POZİSYONLARI */}
      <div className="rounded-2xl border border-slate-300 dark:border-bunker-800 bg-white dark:bg-bunker-900/70 overflow-hidden shadow-sm dark:shadow-xl">
        <div className="p-4 border-b border-slate-200 dark:border-bunker-800 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <span className="text-lg">⚡</span>
            <h2 className="text-sm font-black text-slate-900 dark:text-white uppercase tracking-wider flex items-center gap-2">
              <span>Canlı IC Markets MT5 Açık Pozisyonları ({mt5.open_positions?.length || 0})</span>
            </h2>
            <span className="text-[10px] text-emerald-800 dark:text-emerald-400 font-bold px-2 py-0.5 rounded bg-emerald-50 dark:bg-emerald-500/15 border border-emerald-300 dark:border-emerald-500/30">
              ICMarketsSC-Demo · 53077151
            </span>
          </div>

          <div className="flex items-center gap-3">
            {mt5.open_positions && mt5.open_positions.length > 0 && (
              <button
                type="button"
                onClick={closeAllMt5Positions}
                className="px-3 py-1 rounded-lg bg-rose-50 dark:bg-rose-600/25 border border-rose-300 dark:border-rose-500/50 text-rose-700 dark:text-rose-300 hover:bg-rose-100 text-xs font-bold transition-all flex items-center gap-1.5 shadow-sm"
              >
                <span>🛑 Tüm MT5 Pozisyonlarını Kapat ({mt5.open_positions.length})</span>
              </button>
            )}
            <span className="text-xs text-blue-600 dark:text-blue-400 font-bold animate-pulse">
              {autoEnabled ? "Canlı Takip Devrede" : "Otonom Beklemede"}
            </span>
          </div>
        </div>

        {(!mt5.open_positions || mt5.open_positions.length === 0) ? (
          <div className="p-12 text-center text-slate-600 dark:text-bunker-muted text-xs space-y-1">
            <p className="text-sm font-bold text-slate-900 dark:text-white">Şu an açık bir IC Markets MT5 pozisyonu bulunmuyor.</p>
            <p className="text-slate-600 dark:text-bunker-muted font-medium">
              {autoEnabled
                ? "Otonom scalper radar sinyallerini ve seans fırsatlarını denetliyor. Sinyal geldiğinde emir anında IC Markets hesabınızda açılır."
                : "Otonom motor şu an durdurulmuş durumda. Başlatmak için yukarıdaki '▶ Otonom Scalper'ı Başlat' butonunu kullanabilirsiniz."}
            </p>
          </div>
        ) : (
          <>
            {/* Masaüstü Tablo Görünümü */}
            <div className="hidden md:block overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead className="bg-slate-100 dark:bg-bunker-950/80 text-slate-800 dark:text-bunker-muted uppercase border-b border-slate-300 dark:border-bunker-800 text-[11px] font-black">
                  <tr>
                    <th className="py-3 px-4">Bilet</th>
                    <th className="py-3 px-3">Parite</th>
                    <th className="py-3 px-3">Yön</th>
                    <th className="py-3 px-3">Koruma / Rozet</th>
                    <th className="py-3 px-3">Lot</th>
                    <th className="py-3 px-3">Giriş Fiyatı</th>
                    <th className="py-3 px-3">Güncel Fiyat</th>
                    <th className="py-3 px-3">SL / TP Seviyeleri</th>
                    <th className="py-3 px-3">Kâr ($ / Pip)</th>
                    <th className="py-3 px-4 text-right">Aksiyon</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-200 dark:divide-bunker-800/60">
                  {mt5.open_positions.map((p) => {
                    const pnlVal = Number(p.pnl_usd ?? (p as any).profit ?? 0);
                    const isProfit = pnlVal >= 0;
                    const isTrailing = p.protection === "TRAILING" || !!p.trailing_activated;
                    const isBE = (p.protection === "BREAKEVEN" || !!p.breakeven_activated) && !isTrailing;

                    return (
                      <tr key={p.ticket} className="hover:bg-slate-50 dark:hover:bg-bunker-800/40 transition-colors">
                        <td className="py-3 px-4 font-mono text-[11px] text-sky-600 dark:text-cyan-300 font-black">#{p.ticket}</td>
                        <td className="py-3 px-3">
                          <div className="flex items-center gap-1.5">
                            <span className="font-black text-slate-900 dark:text-white text-sm">{p.symbol}</span>
                            {(p.strategy_label || (p as any).strategy) && (
                              <span className="px-1.5 py-0.5 rounded text-[9px] font-bold bg-purple-100 text-purple-800 border border-purple-300 dark:bg-purple-900/40 dark:text-purple-300 dark:border-purple-600/50 whitespace-nowrap">
                                {p.strategy_label || (p as any).strategy}
                              </span>
                            )}
                          </div>
                        </td>
                        <td className="py-3 px-3">
                          <span
                            className={`px-2 py-0.5 rounded text-[10px] font-black ${
                              p.direction === "BUY"
                                ? "bg-emerald-50 text-emerald-800 border border-emerald-300 dark:bg-emerald-500/15 dark:text-emerald-400 dark:border-emerald-500/30"
                                : "bg-rose-50 text-rose-800 border border-rose-300 dark:bg-rose-500/15 dark:text-rose-400 dark:border-rose-500/30"
                            }`}
                          >
                            {p.direction}
                          </span>
                        </td>

                        {/* DİNAMİK ROZET (TRAILING / BREAKEVEN / SABİT SL) */}
                        <td className="py-3 px-3">
                          {isTrailing ? (
                            <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-black bg-amber-50 text-amber-900 border border-amber-300 dark:bg-gradient-to-r dark:from-amber-500/25 dark:via-orange-500/30 dark:to-amber-500/20 dark:text-amber-300 dark:border-amber-400/50 shadow-sm tracking-wide">
                              <span className="text-xs">🏃</span>
                              <span>TRAILING STOP</span>
                            </span>
                          ) : isBE ? (
                            <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-bold bg-sky-50 text-sky-900 border border-sky-300 dark:bg-cyan-500/20 dark:text-cyan-300 dark:border-cyan-400/40 shadow-sm tracking-wide">
                              <span className="text-xs">🛡️</span>
                              <span>BAŞABAŞ (BE)</span>
                              <span className="text-[9px] px-1 py-0.2 rounded bg-sky-200 text-sky-900 dark:bg-cyan-400/20 dark:text-cyan-200 font-bold">SIFIR RİSK</span>
                            </span>
                          ) : (
                            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-bold bg-slate-100 text-slate-700 border border-slate-300 dark:bg-bunker-800 dark:text-bunker-muted dark:border-bunker-700/60">
                              <span>🛑 Sabit SL</span>
                            </span>
                          )}
                        </td>

                        <td className="py-3 px-3 font-bold text-slate-900 dark:text-white">{p.lots} Lot</td>
                        <td className="py-3 px-3 font-mono font-semibold text-slate-800 dark:text-bunker-muted">{p.entry_price}</td>
                        <td className="py-3 px-3 font-black font-mono text-slate-900 dark:text-white">{p.current_price}</td>

                        {/* SL / TP SEVİYELERİ (KORUMA VURGULARIYLA) */}
                        <td className="py-3 px-3 font-mono text-xs">
                          <div className="flex flex-col gap-0.5">
                            <div className="flex items-center gap-1.5">
                              {isTrailing ? (
                                <span className="text-amber-300 font-bold flex items-center gap-1">
                                  <span>SL: {p.sl_price || "-"}</span>
                                  <span className="text-[9px] font-sans font-bold px-1 py-0.2 rounded bg-amber-500/20 border border-amber-500/30 text-amber-200">
                                    🏃 Takipte
                                  </span>
                                </span>
                              ) : isBE ? (
                                <span className="text-cyan-300 font-bold flex items-center gap-1">
                                  <span>SL: {p.sl_price || "-"}</span>
                                  <span className="text-[9px] font-sans font-bold px-1 py-0.2 rounded bg-cyan-500/20 border border-cyan-500/30 text-cyan-200">
                                    🛡️ BE Kilitli
                                  </span>
                                </span>
                              ) : (
                                <span className="text-rose-300">SL: {p.sl_price || "-"}</span>
                              )}
                            </div>
                            <span className="text-emerald-300">TP: {p.tp_price || "-"}</span>
                          </div>
                        </td>

                        {/* KÂR ($ / PİP) */}
                        <td className={`py-3 px-3 font-mono ${isProfit ? "text-emerald-400" : "text-rose-400"}`}>
                          <div className="font-bold text-sm">
                            {isProfit ? "+" : ""}${pnlVal.toFixed(2)}
                          </div>
                          {p.pnl_pips != null && (
                            <div className={`text-[10px] font-semibold ${Number(p.pnl_pips) >= 0 ? "text-emerald-400" : "text-rose-400"}`}>
                              {Number(p.pnl_pips) >= 0 ? "+" : ""}{Number(p.pnl_pips).toFixed(1)} p
                            </div>
                          )}
                        </td>

                        <td className="py-3 px-4 text-right">
                          <button
                            type="button"
                            onClick={() => closeMt5Ticket(p.ticket)}
                            className="px-2.5 py-1 rounded-lg bg-rose-500/15 border border-rose-500/30 text-rose-300 hover:bg-rose-500/25 transition-all font-bold text-[11px]"
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

            {/* Mobil Kart Görünümü */}
            <div className="md:hidden space-y-3 p-3">
              {mt5.open_positions.map((p) => {
                const pnlVal = Number(p.pnl_usd ?? (p as any).profit ?? 0);
                const isProfit = pnlVal >= 0;
                const isTrailing = p.protection === "TRAILING" || !!p.trailing_activated;
                const isBE = (p.protection === "BREAKEVEN" || !!p.breakeven_activated) && !isTrailing;

                return (
                  <div
                    key={p.ticket}
                    className="p-3.5 rounded-2xl border border-bunker-800 bg-bunker-900/90 shadow-lg font-mono text-xs space-y-2.5"
                  >
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-bold text-white">{p.symbol}</span>
                        <span className="text-[10px] font-mono text-cyan-300">#{p.ticket}</span>
                      </div>
                      <span
                        className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                          p.direction === "BUY"
                            ? "bg-emerald-500/15 text-emerald-400 border border-emerald-500/30"
                            : "bg-rose-500/15 text-rose-400 border border-rose-500/30"
                        }`}
                      >
                        {p.direction} · {p.lots} Lot
                      </span>
                    </div>

                    {/* Koruma Durumu Rozeti */}
                    <div>
                      {isTrailing ? (
                        <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[10px] font-black bg-amber-500/20 text-amber-300 border border-amber-400/40">
                          🏃 TRAILING STOP
                        </span>
                      ) : isBE ? (
                        <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[10px] font-bold bg-cyan-500/20 text-cyan-300 border border-cyan-400/40">
                          🛡️ BAŞABAŞ KİLİTLİ
                        </span>
                      ) : (
                        <span className="text-[10px] text-bunker-muted">🛑 Sabit Stop</span>
                      )}
                    </div>

                    {/* Kâr / Zarar */}
                    <div className="flex items-center justify-between p-2 rounded-xl bg-bunker-950/70 border border-bunker-800/80">
                      <div>
                        <span className="text-[10px] text-bunker-muted block">Anlık Getiri</span>
                        <span className={`text-base font-bold ${isProfit ? "text-emerald-400" : "text-rose-400"}`}>
                          {isProfit ? "+" : ""}${pnlVal.toFixed(2)}
                        </span>
                      </div>
                      {p.pnl_pips != null && (
                        <div className="text-right">
                          <span className="text-[10px] text-bunker-muted block">Pip Değeri</span>
                          <span className={`text-sm font-bold ${Number(p.pnl_pips) >= 0 ? "text-emerald-400" : "text-rose-400"}`}>
                            {Number(p.pnl_pips) >= 0 ? "+" : ""}{Number(p.pnl_pips).toFixed(1)} p
                          </span>
                        </div>
                      )}
                    </div>

                    {/* Fiyatlar ve Seviyeler */}
                    <div className="grid grid-cols-2 gap-2 text-[11px] pt-1 border-t border-bunker-800/60">
                      <div>
                        <span className="text-bunker-muted">Giriş: </span>
                        <span className="text-white font-bold">{p.entry_price}</span>
                      </div>
                      <div className="text-right">
                        <span className="text-bunker-muted">Güncel: </span>
                        <span className="text-white font-bold">{p.current_price}</span>
                      </div>
                      <div>
                        <span className="text-rose-300">SL: </span>
                        <span className="text-slate-200">{p.sl_price || "-"}</span>
                      </div>
                      <div className="text-right">
                        <span className="text-emerald-300">TP: </span>
                        <span className="text-slate-200">{p.tp_price || "-"}</span>
                      </div>
                    </div>

                    <button
                      type="button"
                      onClick={() => closeMt5Ticket(p.ticket)}
                      className="w-full py-2 rounded-xl bg-rose-500/20 hover:bg-rose-500/30 border border-rose-500/40 text-rose-200 font-bold text-xs transition-colors touch-target active:scale-95 flex items-center justify-center gap-1.5 shadow-sm"
                    >
                      <span>🛑</span>
                      <span>Pozisyonu Kapat</span>
                    </button>
                  </div>
                );
              })}
            </div>
          </>
        )}
      </div>

      {/* KARAR GÜNLÜĞÜ (DECISION STREAM) VE GEÇMİŞ İŞLEMLER */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Canlı Otonom Karar & Tarama Günlüğü */}
        <div className="rounded-2xl border border-slate-300 dark:border-bunker-800 bg-white dark:bg-bunker-900/70 p-4 shadow-sm dark:shadow-xl flex flex-col h-[420px]">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between border-b border-slate-200 dark:border-bunker-800 pb-2.5 mb-2 gap-2">
            <div className="flex items-center gap-2">
              <span className="text-base">📜</span>
              <h3 className="text-xs font-black text-slate-900 dark:text-white uppercase tracking-wider">
                Otonom Karar & Tarama Akışı (Decision Stream)
              </h3>
            </div>
            <span className="text-[10px] font-bold text-slate-600 dark:text-bunker-muted">
              {decisionLogs.length} Olay Kaydedildi
            </span>
          </div>

          {/* Kategori Filtre Butonları */}
          <div className="flex items-center gap-1.5 overflow-x-auto pb-2 mb-2 border-b border-slate-200 dark:border-bunker-800/60 scrollbar-none text-[10px]">
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
                      ? "bg-blue-600 text-white shadow-sm"
                      : "bg-slate-100 text-slate-700 hover:text-slate-900 border border-slate-200 dark:bg-bunker-950/60 dark:text-bunker-muted dark:hover:text-white dark:border-transparent"
                  }`}
                >
                  <span>{tab.icon}</span>
                  <span>{tab.label}</span>
                  <span className="opacity-80 text-[9px]">({count})</span>
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

              // En son log her zaman en üstte (azalan sıralama)
              const sorted = [...filtered].sort((a, b) => {
                const tsA = a.created_at_ts ?? 0;
                const tsB = b.created_at_ts ?? 0;
                if (tsA && tsB && tsA !== tsB) return tsB - tsA;
                return (b.time || "").localeCompare(a.time || "");
              });

              const catColors: Record<string, string> = {
                SCAN: "border-sky-300 bg-sky-50 text-sky-950 dark:border-sky-500/30 dark:bg-sky-500/10 dark:text-sky-200",
                ENTRY: "border-emerald-300 bg-emerald-50 text-emerald-950 dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-300",
                EXIT: "border-blue-300 bg-blue-50 text-blue-950 dark:border-blue-500/30 dark:bg-blue-500/10 dark:text-blue-300",
                PROTECT: "border-cyan-300 bg-cyan-50 text-cyan-950 dark:border-cyan-500/30 dark:bg-cyan-500/10 dark:text-cyan-300",
                GATE: "border-amber-300 bg-amber-50 text-amber-950 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-300",
                SYSTEM: "border-slate-300 bg-slate-100 text-slate-800 dark:border-bunker-700 dark:bg-bunker-800/40 dark:text-bunker-muted",
              };

              const catIcons: Record<string, string> = {
                SCAN: "🔍",
                ENTRY: "⚡",
                EXIT: "🎯",
                PROTECT: "🛡️",
                GATE: "⛔",
                SYSTEM: "⚙️",
              };

              return sorted.map((log) => {
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
                      {((log as any).strategy_label || (log as any).metadata?.strategy_label) && (
                        <span className="mr-1.5 px-1.5 py-0.5 rounded text-[9px] font-bold bg-purple-100 text-purple-900 border border-purple-300 dark:bg-purple-900/40 dark:text-purple-300 dark:border-purple-600/50 whitespace-nowrap inline-block">
                          🎯 {(log as any).strategy_label || (log as any).metadata?.strategy_label}
                        </span>
                      )}
                      <span>{log.message}</span>
                    </div>
                    <span className="text-[10px] opacity-70 whitespace-nowrap">{formatUtc3(log.time)}</span>
                  </div>
                );
              });
            })()}
          </div>
        </div>

        {/* Kapanan İşlemler Geçmişi */}
        <div className="rounded-2xl border border-slate-300 dark:border-bunker-800 bg-white dark:bg-bunker-900/70 p-4 shadow-sm dark:shadow-xl flex flex-col h-[420px]">
          <div className="flex items-center justify-between border-b border-slate-200 dark:border-bunker-800 pb-3 mb-2">
            <div className="flex items-center gap-2">
              <span className="text-base">🏁</span>
              <h3 className="text-xs font-black text-slate-900 dark:text-white uppercase tracking-wider">
                Kapanan Scalp İşlemleri ({closedTrades.length})
              </h3>
            </div>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={downloadCsv}
                disabled={closedTrades.length === 0}
                className="px-2.5 py-1 rounded-lg text-[10px] font-bold bg-blue-50 text-blue-700 border border-blue-300 hover:bg-blue-100 dark:bg-blue-600/30 dark:text-blue-300 dark:border-blue-400/40 dark:hover:bg-blue-600/50 transition-all disabled:opacity-40 flex items-center gap-1 shadow-sm"
                title="Kapanan İşlemleri CSV İndir"
              >
                <span>📥</span>
                <span>CSV</span>
              </button>
              <Link
                href="/forex/reports"
                className="px-2.5 py-1 rounded-lg text-[10px] font-bold bg-slate-100 hover:bg-slate-200 text-slate-800 border border-slate-300 dark:bg-bunker-800 dark:hover:bg-bunker-700 dark:text-white dark:border-transparent transition-all flex items-center gap-1"
                title="Tüm İşlem Raporları ve Analitik"
              >
                <span>📊</span>
                <span>Raporlar →</span>
              </Link>
            </div>
          </div>

          <div className="flex-1 overflow-y-auto space-y-2 pr-1 text-xs">
            {closedTrades.length === 0 ? (
              <div className="text-center py-10 text-slate-500 dark:text-bunker-muted font-medium">
                Henüz kapanmış bir işlem bulunmuyor.
              </div>
            ) : (
              closedTrades.map((tr: any, idx: number) => {
                const pnlVal = Number(tr.pnl_usd ?? tr.profit ?? 0);
                const isWin = pnlVal >= 0;
                const pnlPips = tr.pnl_pips != null ? Number(tr.pnl_pips) : null;
                const keyId = tr.id ?? tr.ticket ?? `deal-${idx}`;
                const symDisplay = tr.display ?? tr.symbol ?? "FX";
                const dir = tr.direction ?? "BUY";
                const lotsVal = tr.lots ?? 0.01;
                const entryP = tr.entry_price ?? tr.price ?? "-";
                const exitP = tr.exit_price ?? tr.price ?? "-";
                const timeStr = tr.exit_time ?? tr.time ?? "-";
                const reasonStr = tr.exit_reason_title ?? tr.exit_reason ?? "IC Markets MT5";

                return (
                  <div
                    key={keyId}
                    className="p-2.5 rounded-lg border border-slate-200 dark:border-bunker-800 bg-slate-50/70 dark:bg-bunker-950/60 flex items-center justify-between hover:border-slate-300 dark:hover:border-bunker-700 transition-colors"
                  >
                    <div>
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="font-black text-slate-900 dark:text-white text-xs">{symDisplay}</span>
                        <span
                          className={`px-1.5 py-0.2 rounded text-[9px] font-black ${
                            dir === "BUY"
                              ? "bg-emerald-50 text-emerald-800 border border-emerald-300 dark:bg-emerald-500/15 dark:text-emerald-400"
                              : "bg-rose-50 text-rose-800 border border-rose-300 dark:bg-rose-500/15 dark:text-rose-400"
                          }`}
                        >
                          {dir}
                        </span>
                        {(tr.strategy_label || tr.strategy) && (
                          <span className="px-1.5 py-0.2 rounded text-[9px] font-bold bg-indigo-50 text-indigo-900 border border-indigo-300 dark:bg-indigo-900/40 dark:text-indigo-300 dark:border-indigo-600/50">
                            {tr.strategy_label || tr.strategy}
                          </span>
                        )}
                        <span className="text-[10px] font-semibold text-slate-700 dark:text-bunker-muted">{lotsVal} Lot</span>
                        <span className="text-[10px] px-1.5 py-0.2 rounded bg-slate-200 dark:bg-bunker-800 text-slate-700 dark:text-bunker-muted font-bold">
                          {reasonStr}
                        </span>
                      </div>
                      <div className="text-[10px] text-slate-600 dark:text-bunker-muted font-medium mt-0.5">
                        Giriş: {entryP} → Çıkış: {exitP} ({formatUtc3(timeStr)})
                      </div>
                    </div>

                    <div className="text-right">
                      <div
                        className={`font-black text-xs ${
                          isWin ? "text-emerald-600 dark:text-emerald-400" : "text-rose-600 dark:text-rose-400"
                        }`}
                      >
                        {isWin ? "+" : ""}${pnlVal.toFixed(2)}
                      </div>
                      {pnlPips !== null && (
                        <div
                          className={`text-[10px] font-bold ${
                            pnlPips >= 0 ? "text-emerald-700 dark:text-emerald-400" : "text-rose-700 dark:text-rose-400"
                          }`}
                        >
                          {pnlPips >= 0 ? "+" : ""}
                          {pnlPips} p
                        </div>
                      )}
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </div>
      </div>

      {/* ALT BAĞLANTILAR */}
      <div className="flex flex-wrap items-center justify-between gap-3 text-xs text-bunker-muted pt-2 border-t border-bunker-800">
        <div className="flex items-center gap-4">
          <Link href="/forex" className="hover:text-blue-400 transition-colors">
            ← Forex Radar & Canlı Piyasa
          </Link>
          <span className="text-bunker-700">|</span>
          <Link href="/forex/reports" className="hover:text-blue-300 font-bold text-blue-400 transition-colors flex items-center gap-1">
            📊 Tüm İşlem Raporları & CSV İndir →
          </Link>
        </div>
        <Link href="/forex/technical-charts" className="hover:text-blue-400 transition-colors">
          4'lü TradingView Çoklu Ekran →
        </Link>
      </div>
    </div>
  );
}
