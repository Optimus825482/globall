"use client";

import { useEffect, useState, useCallback, useMemo } from "react";
import { apiFetch } from "../lib/api";
import { Card, Badge, Button } from "../components/ui";
import SpotChartModal from "./SpotChartModal";

type SignalItem = {
  id: number;
  symbol: string;
  timeframe: string;
  strategy: string;
  strategy_label: string;
  entry_price: number;
  current_price: number;
  target_price: number;
  stop_price: number;
  score: number;
  kdj_j: number | null;
  status: "OPEN" | "WIN_TP" | "LOSS_SL" | "EXPIRED" | "MANUAL_CLOSED" | string;
  pnl_pct: number;
  mfe_pct: number;
  net_pnl_try: number;
  detected_at: string;
  exit_time: string | null;
  details: {
    note?: string;
    tp_pct?: number;
    sl_pct?: number;
  };
};

type DashboardData = {
  portfolio: {
    initial_balance_try: number;
    current_balance_try: number;
    free_balance_try: number;
    in_positions_try: number;
    realized_pnl_try: number;
    unrealized_pnl_try: number;
    growth_pct: number;
    trade_size_try: number;
    open_positions_count: number;
  };
  metrics: {
    total_signals: number;
    closed_count: number;
    open_count: number;
    win_count: number;
    loss_count: number;
    win_rate_pct: number;
  };
  signals: SignalItem[];
  last_scan_time: number;
};

type LiveStats = {
  trades: number;
  open: number;
  wins: number;
  losses: number;
  expired: number;
  win_rate: number | null;
  pf: number | null;
  net_pnl_try: number;
  kill: boolean;
};

type ActiveStrategy = {
  code: string;
  label: string;
  score: number;
  description: string;
  evidence: string;
  timeframes: string[];
  enabled: boolean;
  tp_sl_override?: Record<string, { tp_pct: number; sl_pct: number }>;
  live?: LiveStats | null;
};

type StrategiesData = {
  count: number;
  active_count: number;
  kill_count: number;
  symbols_count: number;
  timeframes: Array<{ code: string; label: string; tp_pct: number; sl_pct: number }>;
  trade_size_try: number;
  initial_portfolio_try: number;
  commission_rate: number;
  strategies: ActiveStrategy[];
};

export default function SpotMonitorPage() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [scanning, setScanning] = useState(false);
  const [activeTab, setActiveTab] = useState<"ACTIVE" | "HISTORY" | "SYMBOLS" | "STRATEGIES">("ACTIVE");
  const [selectedModalSignal, setSelectedModalSignal] = useState<SignalItem | null>(null);
  const [strategies, setStrategies] = useState<StrategiesData | null>(null);
  const [togglingCode, setTogglingCode] = useState<string | null>(null);
  const [closingId, setClosingId] = useState<number | null>(null);
  const [closingAll, setClosingAll] = useState(false);

  // Tarih Filtresi
  type DatePreset = "ALL" | "TODAY" | "24H" | "7D" | "CUSTOM";
  const [dateFilter, setDateFilter] = useState<DatePreset>("ALL");
  const [customStartDate, setCustomStartDate] = useState<string>("");
  const [customEndDate, setCustomEndDate] = useState<string>("");

  // Sayfalama
  const [currentPage, setCurrentPage] = useState<number>(1);
  const [pageSize, setPageSize] = useState<number>(10);

  // Kart Sıralama
  const [symbolSort, setSymbolSort] = useState<"pnl" | "winrate" | "trades">("pnl");
  const [strategySort, setStrategySort] = useState<"pnl" | "winrate" | "trades">("pnl");

  useEffect(() => {
    const loadStrategies = () =>
      apiFetch("/api/spot-monitor/strategies")
        .then((res) => setStrategies(res as StrategiesData))
        .catch((err) => console.error("Aktif stratejiler yüklenirken hata:", err));
    loadStrategies();
    const interval = setInterval(loadStrategies, 60000); // canlı strateji istatistikleri 60 sn'de bir yenilenir
    return () => clearInterval(interval);
  }, []);

  const toggleStrategy = async (code: string, enabled: boolean) => {
    setTogglingCode(code);
    try {
      await apiFetch(`/api/spot-monitor/strategies/${code}/toggle?enabled=${enabled}`, { method: "POST" });
      setStrategies((prev) =>
        prev
          ? {
              ...prev,
              active_count: prev.active_count + (enabled ? 1 : -1),
              strategies: prev.strategies.map((s) => (s.code === code ? { ...s, enabled } : s)),
            }
          : prev
      );
    } catch (err) {
      console.error("Strateji aç/kapa hatası:", err);
    } finally {
      setTogglingCode(null);
    }
  };

  const loadDashboard = useCallback(async () => {
    try {
      const res = (await apiFetch("/api/spot-monitor/dashboard")) as DashboardData;
      setData(res);
    } catch (err) {
      console.error("Dashboard yüklenirken hata:", err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadDashboard();
    const interval = setInterval(loadDashboard, 15000); // 15 saniyede bir otomatik yenile
    return () => clearInterval(interval);
  }, [loadDashboard]);

  const handleScanNow = async () => {
    setScanning(true);
    try {
      await apiFetch("/api/spot-monitor/scan-now", { method: "POST" });
      setTimeout(async () => {
        await loadDashboard();
        setScanning(false);
      }, 3000);
    } catch (err) {
      console.error("Tarama tetikleme hatası:", err);
      setScanning(false);
    }
  };

  const handleClosePosition = async (id: number) => {
    setClosingId(id);
    try {
      await apiFetch(`/api/spot-monitor/close/${id}`, { method: "POST" });
      await loadDashboard();
    } catch (err) {
      console.error("Pozisyon kapatma hatası:", err);
    } finally {
      setClosingId(null);
    }
  };

  const handleCloseAllPositions = async () => {
    if (!window.confirm("Tüm açık simülatör pozisyonlarını anlık piyasa fiyatından kapatmak istediğinize emin misiniz?")) {
      return;
    }
    setClosingAll(true);
    try {
      await apiFetch("/api/spot-monitor/close-all", { method: "POST" });
      await loadDashboard();
    } catch (err) {
      console.error("Tümünü kapatma hatası:", err);
    } finally {
      setClosingAll(false);
    }
  };

  const openSignals = useMemo(() => (data?.signals || []).filter((s) => s.status === "OPEN"), [data]);
  const historySignals = useMemo(() => (data?.signals || []).filter((s) => s.status !== "OPEN"), [data]);

  const filteredHistory = useMemo(() => {
    if (dateFilter === "ALL") return historySignals;

    const now = new Date();
    let startTs = 0;
    let endTs = Number.MAX_SAFE_INTEGER;

    if (dateFilter === "TODAY") {
      const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
      startTs = today.getTime();
    } else if (dateFilter === "24H") {
      startTs = now.getTime() - 24 * 60 * 60 * 1000;
    } else if (dateFilter === "7D") {
      startTs = now.getTime() - 7 * 24 * 60 * 60 * 1000;
    } else if (dateFilter === "CUSTOM") {
      if (customStartDate) {
        startTs = new Date(customStartDate + "T00:00:00").getTime();
      }
      if (customEndDate) {
        endTs = new Date(customEndDate + "T23:59:59").getTime();
      }
    }

    return historySignals.filter((s) => {
      const d = new Date(s.detected_at).getTime();
      return d >= startTs && d <= endTs;
    });
  }, [historySignals, dateFilter, customStartDate, customEndDate]);

  const totalPages = Math.max(1, Math.ceil(filteredHistory.length / pageSize));
  const validCurrentPage = Math.min(currentPage, totalPages);
  const pagedHistorySignals = useMemo(() => {
    const start = (validCurrentPage - 1) * pageSize;
    return filteredHistory.slice(start, start + pageSize);
  }, [filteredHistory, validCurrentPage, pageSize]);

  interface SymbolStats {
    symbol: string;
    totalTrades: number;
    winCount: number;
    lossCount: number;
    expiredCount: number;
    manualCount: number;
    winRate: number;
    totalNetPnl: number;
    totalPnlPct: number;
    avgNetPnl: number;
    bestPnl: number;
    worstPnl: number;
  }

  const symbolStatsList = useMemo(() => {
    const map = new Map<string, SymbolStats>();

    for (const s of filteredHistory) {
      if (!map.has(s.symbol)) {
        map.set(s.symbol, {
          symbol: s.symbol,
          totalTrades: 0,
          winCount: 0,
          lossCount: 0,
          expiredCount: 0,
          manualCount: 0,
          winRate: 0,
          totalNetPnl: 0,
          totalPnlPct: 0,
          avgNetPnl: 0,
          bestPnl: -Infinity,
          worstPnl: Infinity,
        });
      }
      const st = map.get(s.symbol)!;
      st.totalTrades += 1;
      const net = s.net_pnl_try || 0;
      st.totalNetPnl += net;
      st.totalPnlPct += s.pnl_pct || 0;

      if (net > 0) st.winCount += 1;
      else st.lossCount += 1;

      if (s.status === "EXPIRED" || s.status === "EXPIRED_TIME") st.expiredCount += 1;
      if (s.status === "MANUAL_CLOSED") st.manualCount += 1;

      if (net > st.bestPnl) st.bestPnl = net;
      if (net < st.worstPnl) st.worstPnl = net;
    }

    const list = Array.from(map.values()).map((st) => ({
      ...st,
      winRate: st.totalTrades > 0 ? (st.winCount / st.totalTrades) * 100 : 0,
      avgNetPnl: st.totalTrades > 0 ? st.totalNetPnl / st.totalTrades : 0,
      bestPnl: st.bestPnl === -Infinity ? 0 : st.bestPnl,
      worstPnl: st.worstPnl === Infinity ? 0 : st.worstPnl,
    }));

    if (symbolSort === "pnl") {
      list.sort((a, b) => b.totalNetPnl - a.totalNetPnl);
    } else if (symbolSort === "winrate") {
      list.sort((a, b) => b.winRate - a.winRate);
    } else {
      list.sort((a, b) => b.totalTrades - a.totalTrades);
    }

    return list;
  }, [filteredHistory, symbolSort]);

  interface StrategyStats {
    strategyCode: string;
    strategyLabel: string;
    totalTrades: number;
    winCount: number;
    lossCount: number;
    expiredCount: number;
    manualCount: number;
    winRate: number;
    totalNetPnl: number;
    totalPnlPct: number;
    avgNetPnl: number;
    grossProfit: number;
    grossLoss: number;
    profitFactor: number;
    bestSymbol: string;
    bestSymbolPnl: number;
  }

  const strategyStatsList = useMemo(() => {
    const map = new Map<string, StrategyStats & { symbolPnlMap: Record<string, number> }>();

    for (const s of filteredHistory) {
      const code = s.strategy || "unknown";
      if (!map.has(code)) {
        map.set(code, {
          strategyCode: code,
          strategyLabel: s.strategy_label || code,
          totalTrades: 0,
          winCount: 0,
          lossCount: 0,
          expiredCount: 0,
          manualCount: 0,
          winRate: 0,
          totalNetPnl: 0,
          totalPnlPct: 0,
          avgNetPnl: 0,
          grossProfit: 0,
          grossLoss: 0,
          profitFactor: 0,
          bestSymbol: "-",
          bestSymbolPnl: -Infinity,
          symbolPnlMap: {},
        });
      }
      const st = map.get(code)!;
      st.totalTrades += 1;
      const net = s.net_pnl_try || 0;
      st.totalNetPnl += net;
      st.totalPnlPct += s.pnl_pct || 0;

      if (net > 0) {
        st.winCount += 1;
        st.grossProfit += net;
      } else {
        st.lossCount += 1;
        st.grossLoss += Math.abs(net);
      }

      if (s.status === "EXPIRED" || s.status === "EXPIRED_TIME") st.expiredCount += 1;
      if (s.status === "MANUAL_CLOSED") st.manualCount += 1;

      st.symbolPnlMap[s.symbol] = (st.symbolPnlMap[s.symbol] || 0) + net;
    }

    const list = Array.from(map.values()).map((st) => {
      let bestSym = "-";
      let bestSymPnl = -Infinity;
      for (const [sym, pnl] of Object.entries(st.symbolPnlMap)) {
        if (pnl > bestSymPnl) {
          bestSymPnl = pnl;
          bestSym = sym;
        }
      }

      const pf = st.grossLoss > 0 ? st.grossProfit / st.grossLoss : (st.grossProfit > 0 ? 99.9 : 0);

      return {
        strategyCode: st.strategyCode,
        strategyLabel: st.strategyLabel,
        totalTrades: st.totalTrades,
        winCount: st.winCount,
        lossCount: st.lossCount,
        expiredCount: st.expiredCount,
        manualCount: st.manualCount,
        winRate: st.totalTrades > 0 ? (st.winCount / st.totalTrades) * 100 : 0,
        totalNetPnl: st.totalNetPnl,
        totalPnlPct: st.totalPnlPct,
        avgNetPnl: st.totalTrades > 0 ? st.totalNetPnl / st.totalTrades : 0,
        grossProfit: st.grossProfit,
        grossLoss: st.grossLoss,
        profitFactor: pf,
        bestSymbol: bestSym,
        bestSymbolPnl: bestSymPnl === -Infinity ? 0 : bestSymPnl,
      };
    });

    if (strategySort === "pnl") {
      list.sort((a, b) => b.totalNetPnl - a.totalNetPnl);
    } else if (strategySort === "winrate") {
      list.sort((a, b) => b.winRate - a.winRate);
    } else {
      list.sort((a, b) => b.totalTrades - a.totalTrades);
    }

    return list;
  }, [filteredHistory, strategySort]);

  const pnlColor = (val: number) => {
    if (val > 0) return "text-emerald-400";
    if (val < 0) return "text-rose-400";
    return "text-slate-300";
  };

  return (
    <div className="space-y-6 p-4 md:p-8 max-w-7xl mx-auto">
      {/* BAŞLIK & ŞİMDİ TARA KOKPİTİ */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-bunker-800 pb-5">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-xl md:text-2xl font-mono font-bold text-white tracking-tight">
              Binance TR Spot Monitor
            </h1>
            <Badge tone="info" className="font-mono text-[10px]">MTF LIVE</Badge>
          </div>
          <p className="text-xs text-bunker-muted mt-1">
            KDJ Dip + SuperTrend + EMA50 Sekmesi + BB-KC Sıkışma Kırılımı + STC Döngüsü + Zero-Lag MACD canlı takibi ve 5.000 TL portföy simülatörü.
          </p>
        </div>

        <div className="flex items-center gap-3">
          <Button
            variant="primary"
            onClick={handleScanNow}
            disabled={scanning}
            className="flex items-center gap-2 bg-gradient-to-r from-cyan-600 to-blue-600 hover:from-cyan-500 hover:to-blue-500 text-white font-mono text-xs px-4 py-2"
          >
            <span>{scanning ? "⚡ Taranıyor..." : "🔄 Şimdi Tara"}</span>
          </Button>
        </div>
      </div>

      {/* PORTFÖY SİMÜLASYONU KARTLARI (5.000 TL BAZLI, 300 TL SABİT İŞLEM) */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3.5">
        {/* 1. PORTFÖY BAKİYESİ */}
        <Card className="p-4 bg-bunker-900/90 border-bunker-800">
          <div className="flex items-center justify-between">
            <p className="text-[11px] font-mono uppercase text-bunker-muted">Portföy Bakiyesi</p>
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-bunker-800 text-bunker-muted font-mono">
              Başlangıç: ₺5.000
            </span>
          </div>
          <div className="flex items-baseline gap-2 mt-1.5">
            <span className="text-2xl font-bold font-mono text-white">
              ₺{(data?.portfolio.current_balance_try || 5000).toLocaleString("tr-TR", { minimumFractionDigits: 2 })}
            </span>
          </div>
          <div className="mt-2 pt-2 border-t border-bunker-800/80 flex items-center justify-between text-[11px] font-mono">
            <span className="text-bunker-muted">Serbest Bakiye:</span>
            <span className="text-cyan-400 font-bold">
              ₺{(data?.portfolio.free_balance_try ?? 5000).toLocaleString("tr-TR", { minimumFractionDigits: 2 })}
            </span>
          </div>
        </Card>

        {/* 2. NET PORTFÖY BÜYÜMESİ */}
        <Card className="p-4 bg-bunker-900/90 border-bunker-800">
          <p className="text-[11px] font-mono uppercase text-bunker-muted">Net Portföy Büyümesi</p>
          <div className="flex items-baseline gap-2 mt-1.5">
            <span className={`text-2xl font-bold font-mono ${pnlColor(data?.portfolio.growth_pct || 0)}`}>
              %{data?.portfolio.growth_pct?.toFixed(2) || "0.00"}
            </span>
          </div>
          <div className="mt-2 pt-2 border-t border-bunker-800/80 flex items-center justify-between text-[11px] font-mono">
            <span className="text-bunker-muted">Net Kâr (TL):</span>
            <span className={`font-medium ${pnlColor((data?.portfolio.realized_pnl_try || 0) + (data?.portfolio.unrealized_pnl_try || 0))}`}>
              ₺{((data?.portfolio.realized_pnl_try || 0) + (data?.portfolio.unrealized_pnl_try || 0)).toFixed(2)}
            </span>
          </div>
        </Card>

        {/* 3. İŞLEM BAŞARI ORANI */}
        <Card className="p-4 bg-bunker-900/90 border-bunker-800">
          <p className="text-[11px] font-mono uppercase text-bunker-muted">İşlem Başarı Oranı</p>
          <div className="flex items-baseline gap-2 mt-1.5">
            <span className="text-2xl font-bold font-mono text-cyan-400">
              %{data?.metrics.win_rate_pct?.toFixed(1) || "0.0"}
            </span>
          </div>
          <div className="mt-2 pt-2 border-t border-bunker-800/80 flex items-center justify-between text-[11px] font-mono">
            <span className="text-bunker-muted">Sonuç:</span>
            <span>
              <span className="text-emerald-400 font-medium">{data?.metrics.win_count || 0} Başarılı</span> / <span className="text-rose-400 font-medium">{data?.metrics.loss_count || 0} Stop</span>
            </span>
          </div>
        </Card>

        {/* 4. İŞLEM BÜYÜKLÜĞÜ & POZİSYONDAKİ TUTAR */}
        <Card className="p-4 bg-bunker-900/90 border-bunker-800">
          <p className="text-[11px] font-mono uppercase text-bunker-muted">İşlem Büyüklüğü</p>
          <div className="flex items-baseline gap-2 mt-1.5">
            <span className="text-2xl font-bold font-mono text-amber-400">
              ₺300,00
            </span>
          </div>
          <div className="mt-2 pt-2 border-t border-bunker-800/80 flex items-center justify-between text-[11px] font-mono">
            <span className="text-bunker-muted">Pozisyondaki:</span>
            <span className="text-amber-300 font-medium">
              {data?.portfolio.open_positions_count || 0} Aktif (₺{(data?.portfolio.in_positions_try ?? ((data?.portfolio.open_positions_count || 0) * 300)).toLocaleString("tr-TR", { minimumFractionDigits: 2 })})
            </span>
          </div>
        </Card>
      </div>

      {/* AKTİF TARAMA STRATEJİLERİ (canlı sistemden /strategies ile senkron) */}
      <div className="rounded-xl border border-bunker-800 bg-bunker-900/80 p-4">
        <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
          <div className="flex items-center gap-2">
            <h2 className="font-mono text-xs uppercase tracking-wide text-bunker-muted">
              🔬 Tarama Stratejileri
            </h2>
            <Badge tone="info" className="font-mono text-[10px]">
              {strategies ? `${strategies.active_count}/${strategies.count} aktif` : "..."}
            </Badge>
            {strategies && strategies.kill_count > 0 && (
              <Badge tone="negative" className="font-mono text-[10px]">
                ⚠️ {strategies.kill_count} kill kriteri
              </Badge>
            )}
          </div>
          <p className="text-[10px] font-mono text-bunker-muted">
            {strategies?.symbols_count ?? 18} sembol × {strategies?.timeframes.length ?? 3} TF
            {" · "}₺{strategies?.trade_size_try ?? 300}/işlem
            {" · "}Kom. %{((strategies?.commission_rate ?? 0.0004) * 2 * 100).toFixed(2)} round-trip
          </p>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-2.5">
          {strategies?.strategies.map((st, i) => (
            <div
              key={st.code}
              className={`rounded-lg border bg-bunker-950/60 p-2.5 transition-opacity ${
                st.enabled ? "border-bunker-800" : "border-bunker-800/50 opacity-55"
              }`}
            >
              <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-1.5 min-w-0">
                  <span className="inline-flex px-1.5 py-0.5 rounded text-[9px] font-bold bg-bunker-800 text-bunker-muted">
                    #{i + 1}
                  </span>
                  <span className={`text-[11px] font-semibold truncate ${st.enabled ? "text-slate-200" : "text-bunker-muted"}`} title={st.label}>
                    {st.label}
                  </span>
                </div>
                <div className="flex items-center gap-1.5 shrink-0">
                  <span className="inline-flex px-1.5 py-0.5 rounded text-[9px] font-bold bg-cyan-950/80 text-cyan-300 border border-cyan-800/50">
                    {st.score.toFixed(0)}p
                  </span>
                  <button
                    type="button"
                    onClick={() => toggleStrategy(st.code, !st.enabled)}
                    disabled={togglingCode === st.code}
                    title={st.enabled ? "Otomatik taramayı duraklat (pasifleştir)" : "Otomatik taramaya dahil et (aktifleştir)"}
                    className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[9px] font-bold border transition-colors cursor-pointer disabled:opacity-50 ${
                      st.enabled
                        ? "bg-emerald-500/15 text-emerald-300 border-emerald-500/40 hover:bg-emerald-500/25"
                        : "bg-bunker-800 text-bunker-muted border-bunker-700 hover:text-slate-300"
                    }`}
                  >
                    <span className={`w-1.5 h-1.5 rounded-full ${st.enabled ? "bg-emerald-400 animate-pulse" : "bg-bunker-600"}`} />
                    {togglingCode === st.code ? "..." : st.enabled ? "AKTİF" : "PASİF"}
                  </button>
                </div>
              </div>
              <p className="text-[10px] text-bunker-muted mt-1.5 leading-snug">{st.description}</p>
              {st.tp_sl_override && Object.keys(st.tp_sl_override).length > 0 && (
                <p className="text-[9px] text-amber-300/90 mt-1 font-mono">
                  🎯 Opt. kademe: {Object.entries(st.tp_sl_override).map(([tf, o]) => `${tf} TP %${o.tp_pct}/SL %${o.sl_pct}`).join(" · ")}
                </p>
              )}
              <p className="text-[9px] text-emerald-400/80 mt-1 font-mono">📈 {st.evidence}</p>
              {st.live && st.live.trades > 0 && (
                <p className={`text-[9px] font-mono mt-1 ${st.live.kill ? "text-rose-400 font-bold" : "text-cyan-400/80"}`}>
                  🔴 Canlı: {st.live.trades} işlem ({st.live.open} açık) · WR %{st.live.win_rate?.toFixed(1) ?? "—"} · PF {st.live.pf?.toFixed(2) ?? "—"} ·{" "}
                  <span className={st.live.net_pnl_try >= 0 ? "text-emerald-400" : "text-rose-400"}>
                    {st.live.net_pnl_try >= 0 ? "+" : ""}₺{st.live.net_pnl_try.toFixed(2)}
                  </span>
                  {st.live.kill && " · ⚠️ KILL KRİTERİ (PF<1.0, ≥20 işlem)"}
                </p>
              )}
            </div>
          ))}
        </div>
        <p className="text-[9px] font-mono text-bunker-muted mt-2.5">
          Öncelik sırası yukarıdan aşağıya ilerler; aynı sembolde ilk eşleşen kural sinyal üretir.
          Pasif (PASİF) durumdaki stratejiler otomatik tarama döngüsünde devre dışıdır ve ayar kalıcıdır.
          Kâr/stop kademeleri: {strategies?.timeframes.map((t) => `${t.code} (TP %${t.tp_pct}/SL %${t.sl_pct})`).join(" · ")}
        </p>
      </div>

      {/* SEKMELER: AKTİF İŞLEMLER / TARAMA GEÇMİŞİ / SEMBOL BAŞARISI / STRATEJİ BAŞARISI */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-bunker-800 pb-2">
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => setActiveTab("ACTIVE")}
            className={`px-3.5 py-2 rounded-lg font-mono text-xs font-semibold transition-colors flex items-center gap-1.5 cursor-pointer ${
              activeTab === "ACTIVE"
                ? "bg-cyan-500/20 text-cyan-300 border border-cyan-500/40"
                : "text-bunker-muted hover:text-white hover:bg-bunker-800"
            }`}
          >
            <span>🎯</span> Aktif Sinyaller ({openSignals.length})
          </button>

          <button
            type="button"
            onClick={() => {
              setActiveTab("HISTORY");
              setCurrentPage(1);
            }}
            className={`px-3.5 py-2 rounded-lg font-mono text-xs font-semibold transition-colors flex items-center gap-1.5 cursor-pointer ${
              activeTab === "HISTORY"
                ? "bg-cyan-500/20 text-cyan-300 border border-cyan-500/40"
                : "text-bunker-muted hover:text-white hover:bg-bunker-800"
            }`}
          >
            <span>📊</span> Tarama Geçmişi ({filteredHistory.length})
          </button>

          <button
            type="button"
            onClick={() => setActiveTab("SYMBOLS")}
            className={`px-3.5 py-2 rounded-lg font-mono text-xs font-semibold transition-colors flex items-center gap-1.5 cursor-pointer ${
              activeTab === "SYMBOLS"
                ? "bg-cyan-500/20 text-cyan-300 border border-cyan-500/40"
                : "text-bunker-muted hover:text-white hover:bg-bunker-800"
            }`}
          >
            <span>🪙</span> Sembol Başarısı ({symbolStatsList.length})
          </button>

          <button
            type="button"
            onClick={() => setActiveTab("STRATEGIES")}
            className={`px-3.5 py-2 rounded-lg font-mono text-xs font-semibold transition-colors flex items-center gap-1.5 cursor-pointer ${
              activeTab === "STRATEGIES"
                ? "bg-cyan-500/20 text-cyan-300 border border-cyan-500/40"
                : "text-bunker-muted hover:text-white hover:bg-bunker-800"
            }`}
          >
            <span>🔬</span> Strateji Başarısı ({strategyStatsList.length})
          </button>
        </div>

        {activeTab === "ACTIVE" && openSignals.length > 0 && (
          <button
            type="button"
            onClick={handleCloseAllPositions}
            disabled={closingAll}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg font-mono text-xs font-bold bg-rose-500/20 text-rose-300 hover:bg-rose-500/30 border border-rose-500/40 transition-colors disabled:opacity-50 cursor-pointer"
            title="Tüm açık simülatör pozisyonlarını anlık piyasa fiyatından kapat"
          >
            <span>{closingAll ? "⏳ Kapatılıyor..." : `⚠️ Tümünü Kapat (${openSignals.length})`}</span>
          </button>
        )}
      </div>

      {/* TARİH FİLTRESİ (Geçmiş, Sembol ve Strateji sekmelerinde geçerli) */}
      {activeTab !== "ACTIVE" && (
        <div className="flex flex-wrap items-center justify-between gap-3 p-3 rounded-xl bg-bunker-900/90 border border-bunker-800 text-xs font-mono">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-bunker-muted uppercase text-[10px] font-bold">📅 Tarih Filtresi:</span>
            <div className="inline-flex rounded-lg p-0.5 bg-bunker-950 border border-bunker-800">
              {(["ALL", "TODAY", "24H", "7D", "CUSTOM"] as const).map((preset) => {
                const labels: Record<string, string> = {
                  ALL: "Tümü",
                  TODAY: "Bugün",
                  "24H": "Son 24s",
                  "7D": "Son 7 Gün",
                  CUSTOM: "Özel",
                };
                const isActive = dateFilter === preset;
                return (
                  <button
                    key={preset}
                    type="button"
                    onClick={() => {
                      setDateFilter(preset);
                      setCurrentPage(1);
                    }}
                    className={`px-2.5 py-1 rounded-md text-[11px] font-semibold transition-colors cursor-pointer ${
                      isActive
                        ? "bg-cyan-500/20 text-cyan-300 border border-cyan-500/40 shadow-sm"
                        : "text-bunker-muted hover:text-white"
                    }`}
                  >
                    {labels[preset]}
                  </button>
                );
              })}
            </div>

            {dateFilter === "CUSTOM" && (
              <div className="flex items-center gap-1.5 text-[11px] ml-1">
                <input
                  type="date"
                  value={customStartDate}
                  onChange={(e) => {
                    setCustomStartDate(e.target.value);
                    setCurrentPage(1);
                  }}
                  className="px-2 py-0.5 rounded bg-bunker-950 border border-bunker-700 text-slate-200 text-xs font-mono focus:border-cyan-500 focus:outline-none"
                />
                <span className="text-bunker-muted">-</span>
                <input
                  type="date"
                  value={customEndDate}
                  onChange={(e) => {
                    setCustomEndDate(e.target.value);
                    setCurrentPage(1);
                  }}
                  className="px-2 py-0.5 rounded bg-bunker-950 border border-bunker-700 text-slate-200 text-xs font-mono focus:border-cyan-500 focus:outline-none"
                />
              </div>
            )}
          </div>

          <div className="text-bunker-muted text-[11px]">
            İşlem Sayısı: <span className="font-bold text-white">{filteredHistory.length}</span>{" "}
            <span className="text-bunker-muted/60">(Toplam: {historySignals.length})</span>
          </div>
        </div>
      )}

      {/* 1. SEKME: AKTİF SİNYALLER TABLOSU */}
      {activeTab === "ACTIVE" && (
        <div className="overflow-x-auto rounded-xl border border-bunker-800 bg-bunker-900/80">
          <table className="w-full text-left font-mono text-xs">
            <thead className="bg-bunker-950/80 text-bunker-muted uppercase text-[10px] border-b border-bunker-800">
              <tr>
                <th className="py-3 px-4">Zaman / Sembol</th>
                <th className="py-3 px-4">TF</th>
                <th className="py-3 px-4">Strateji</th>
                <th className="py-3 px-4">Giriş Fiyatı</th>
                <th className="py-3 px-4">Anlık Fiyat</th>
                <th className="py-3 px-4">Hedef / Stop</th>
                <th className="py-3 px-4">Net Kâr (300₺)</th>
                <th className="py-3 px-4">Durum</th>
                <th className="py-3 px-4 text-right">İşlem</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-bunker-800/60">
              {loading ? (
                <tr>
                  <td colSpan={9} className="text-center py-10 text-bunker-muted">
                    Veriler yükleniyor...
                  </td>
                </tr>
              ) : openSignals.length === 0 ? (
                <tr>
                  <td colSpan={9} className="text-center py-10 text-bunker-muted">
                    Şu an aktif takip edilen sinyal yok. Yukarıdaki &apos;Şimdi Tara&apos; butonuna basabilirsiniz.
                  </td>
                </tr>
              ) : (
                openSignals.map((s) => (
                  <tr key={s.id} className="hover:bg-bunker-800/40 transition-colors">
                    <td className="py-3 px-4">
                      <div className="flex flex-col">
                        <button
                          type="button"
                          onClick={() => setSelectedModalSignal(s)}
                          className="text-left group flex items-center gap-1.5 hover:opacity-90 transition-opacity"
                          title="Canlı Grafik, KDJ ve EMA 50 Göstergelerini Aç"
                        >
                          <span className="font-bold text-white group-hover:text-cyan-400 text-sm underline decoration-dotted decoration-bunker-600 underline-offset-4 cursor-pointer">
                            {s.symbol}
                          </span>
                          <span className="text-xs text-cyan-400 opacity-70 group-hover:opacity-100 group-hover:scale-110 transition-all">
                            📊
                          </span>
                        </button>
                        <span className="text-[10px] text-bunker-muted">
                          {new Date(s.detected_at).toLocaleTimeString("tr-TR", { hour: "2-digit", minute: "2-digit" })}
                        </span>
                      </div>
                    </td>
                    <td className="py-3 px-4">
                      <span className="inline-flex px-1.5 py-0.5 rounded text-[10px] font-bold bg-cyan-950/80 text-cyan-300 border border-cyan-800/50">
                        {s.timeframe}
                      </span>
                    </td>
                    <td className="py-3 px-4">
                      <div className="flex flex-col">
                        <span className="font-medium text-slate-200">{s.strategy_label}</span>
                        {s.details?.note && (
                          <span className="text-[10px] text-bunker-muted">{s.details.note}</span>
                        )}
                      </div>
                    </td>
                    <td className="py-3 px-4 text-slate-300">
                      ₺{s.entry_price > 10 ? s.entry_price.toLocaleString("tr-TR", { minimumFractionDigits: 2 }) : s.entry_price}
                    </td>
                    <td className="py-3 px-4">
                      <span className={`font-bold ${pnlColor(s.pnl_pct)}`}>
                        ₺{s.current_price > 10 ? s.current_price.toLocaleString("tr-TR", { minimumFractionDigits: 2 }) : s.current_price}
                        <span className="text-[10px] ml-1.5">
                          ({s.pnl_pct >= 0 ? "+" : ""}{s.pnl_pct.toFixed(2)}%)
                        </span>
                      </span>
                    </td>
                    <td className="py-3 px-4">
                      <div className="flex flex-col text-[10px]">
                        <span className="text-emerald-400">TP: ₺{s.target_price > 10 ? s.target_price.toLocaleString("tr-TR", { minimumFractionDigits: 2 }) : s.target_price}</span>
                        <span className="text-rose-400">SL: ₺{s.stop_price > 10 ? s.stop_price.toLocaleString("tr-TR", { minimumFractionDigits: 2 }) : s.stop_price}</span>
                      </div>
                    </td>
                    <td className="py-3 px-4">
                      <div className="flex flex-col">
                        <span className={`font-bold ${pnlColor(s.net_pnl_try)}`}>
                          {s.net_pnl_try >= 0 ? "+" : ""}₺{s.net_pnl_try.toFixed(2)}
                        </span>
                        <span className="text-[9px] text-bunker-muted">Net (Kom. Düşülmüş)</span>
                      </div>
                    </td>
                    <td className="py-3 px-4">
                      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-bold bg-amber-500/10 text-amber-300 border border-amber-500/30">
                        <span className="w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse" />
                        AÇIK
                      </span>
                    </td>
                    <td className="py-3 px-4 text-right">
                      <button
                        type="button"
                        onClick={() => handleClosePosition(s.id)}
                        disabled={closingId === s.id}
                        className="inline-flex items-center gap-1 px-2.5 py-1 rounded text-[10px] font-bold bg-rose-500/15 text-rose-300 hover:bg-rose-500/30 border border-rose-500/40 transition-colors disabled:opacity-50 cursor-pointer"
                        title="Bu pozisyonu anlık piyasa fiyatından kapat"
                      >
                        {closingId === s.id ? "..." : "✕ Kapat"}
                      </button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      )}

      {/* 2. SEKME: GEÇMİŞ & KÂR TABLOSU (Sayfalamalı ve Tarih Filtreli) */}
      {activeTab === "HISTORY" && (
        <div className="rounded-xl border border-bunker-800 bg-bunker-900/80 overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-left font-mono text-xs">
              <thead className="bg-bunker-950/80 text-bunker-muted uppercase text-[10px] border-b border-bunker-800">
                <tr>
                  <th className="py-3 px-4">Zaman / Sembol</th>
                  <th className="py-3 px-4">TF</th>
                  <th className="py-3 px-4">Strateji</th>
                  <th className="py-3 px-4">Giriş Fiyatı</th>
                  <th className="py-3 px-4">Çıkış Fiyatı</th>
                  <th className="py-3 px-4">Hedef / Stop</th>
                  <th className="py-3 px-4">Net Kâr (300₺)</th>
                  <th className="py-3 px-4">Sonuç Durumu</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-bunker-800/60">
                {loading ? (
                  <tr>
                    <td colSpan={8} className="text-center py-10 text-bunker-muted">
                      Veriler yükleniyor...
                    </td>
                  </tr>
                ) : filteredHistory.length === 0 ? (
                  <tr>
                    <td colSpan={8} className="text-center py-10 text-bunker-muted">
                      Seçilen tarih aralığında tamamlanmış işlem kaydı bulunmuyor.
                    </td>
                  </tr>
                ) : (
                  pagedHistorySignals.map((s) => {
                    const isWin = (s.net_pnl_try || 0) > 0;
                    return (
                      <tr key={s.id} className="hover:bg-bunker-800/40 transition-colors">
                        <td className="py-3 px-4">
                          <div className="flex flex-col">
                            <button
                              type="button"
                              onClick={() => setSelectedModalSignal(s)}
                              className="text-left group flex items-center gap-1.5 hover:opacity-90 transition-opacity"
                              title="Grafiği ve Göstergeleri Aç"
                            >
                              <span className="font-bold text-white group-hover:text-cyan-400 text-sm underline decoration-dotted decoration-bunker-600 underline-offset-4 cursor-pointer">
                                {s.symbol}
                              </span>
                              <span className="text-xs text-cyan-400 opacity-70 group-hover:opacity-100 group-hover:scale-110 transition-all">
                                📊
                              </span>
                            </button>
                            <span className="text-[10px] text-bunker-muted">
                              {new Date(s.detected_at).toLocaleDateString("tr-TR", { day: "2-digit", month: "2-digit" })}{" "}
                              {new Date(s.detected_at).toLocaleTimeString("tr-TR", { hour: "2-digit", minute: "2-digit" })}
                            </span>
                          </div>
                        </td>
                        <td className="py-3 px-4">
                          <span className="inline-flex px-1.5 py-0.5 rounded text-[10px] font-bold bg-cyan-950/80 text-cyan-300 border border-cyan-800/50">
                            {s.timeframe}
                          </span>
                        </td>
                        <td className="py-3 px-4">
                          <div className="flex flex-col">
                            <span className="font-medium text-slate-200">{s.strategy_label}</span>
                            {s.details?.note && (
                              <span className="text-[10px] text-bunker-muted">{s.details.note}</span>
                            )}
                          </div>
                        </td>
                        <td className="py-3 px-4 text-slate-300">
                          ₺{s.entry_price > 10 ? s.entry_price.toLocaleString("tr-TR", { minimumFractionDigits: 2 }) : s.entry_price}
                        </td>
                        <td className="py-3 px-4">
                          <span className={`font-bold ${pnlColor(s.pnl_pct)}`}>
                            ₺{s.current_price > 10 ? s.current_price.toLocaleString("tr-TR", { minimumFractionDigits: 2 }) : s.current_price}
                            <span className="text-[10px] ml-1.5">
                              ({s.pnl_pct >= 0 ? "+" : ""}{s.pnl_pct.toFixed(2)}%)
                            </span>
                          </span>
                        </td>
                        <td className="py-3 px-4">
                          <div className="flex flex-col text-[10px]">
                            <span className="text-emerald-400">TP: ₺{s.target_price > 10 ? s.target_price.toLocaleString("tr-TR", { minimumFractionDigits: 2 }) : s.target_price}</span>
                            <span className="text-rose-400">SL: ₺{s.stop_price > 10 ? s.stop_price.toLocaleString("tr-TR", { minimumFractionDigits: 2 }) : s.stop_price}</span>
                          </div>
                        </td>
                        <td className="py-3 px-4">
                          <div className="flex flex-col">
                            <span className={`font-bold ${pnlColor(s.net_pnl_try)}`}>
                              {s.net_pnl_try >= 0 ? "+" : ""}₺{s.net_pnl_try.toFixed(2)}
                            </span>
                            <span className="text-[9px] text-bunker-muted">Net (Kom. Düşülmüş)</span>
                          </div>
                        </td>
                        <td className="py-3 px-4">
                          {s.status === "WIN_TP" ? (
                            <span className="inline-flex px-2 py-0.5 rounded text-[10px] font-bold bg-emerald-500/20 text-emerald-300 border border-emerald-500/40">
                              🎯 TP ALINDI
                            </span>
                          ) : s.status === "LOSS_SL" ? (
                            <span className="inline-flex px-2 py-0.5 rounded text-[10px] font-bold bg-rose-500/20 text-rose-300 border border-rose-500/40">
                              🛑 STOP OLDU
                            </span>
                          ) : s.status === "EXPIRED" || s.status === "EXPIRED_TIME" ? (
                            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-bold bg-amber-950/80 text-amber-300 border border-amber-800/60" title="Zaman aşımıyla piyasa fiyatından kapatıldı">
                              ⏱️ SÜRE AŞIMI
                            </span>
                          ) : s.status === "MANUAL_CLOSED" ? (
                            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-bold bg-blue-950/80 text-blue-300 border border-blue-800/60" title="Kullanıcı tarafından manuel kapatıldı">
                              🖐️ MANUEL
                            </span>
                          ) : (
                            <span className={`inline-flex px-2 py-0.5 rounded text-[10px] font-bold ${isWin ? "bg-emerald-950 text-emerald-300" : "bg-rose-950 text-rose-300"}`}>
                              {s.status}
                            </span>
                          )}
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>

          {/* SAYFALAMA KONTROL ÇUBUĞU */}
          {filteredHistory.length > 0 && (
            <div className="flex flex-wrap items-center justify-between gap-3 p-3.5 bg-bunker-950/80 border-t border-bunker-800 text-xs font-mono text-bunker-muted">
              <div className="flex items-center gap-2">
                <span>Sayfa Başına:</span>
                <select
                  value={pageSize}
                  onChange={(e) => {
                    setPageSize(Number(e.target.value));
                    setCurrentPage(1);
                  }}
                  className="bg-bunker-900 border border-bunker-700 text-white rounded px-2 py-1 text-xs font-mono focus:outline-none"
                >
                  <option value={10}>10</option>
                  <option value={25}>25</option>
                  <option value={50}>50</option>
                </select>
                <span className="ml-2 text-slate-300">
                  Toplam <strong className="text-white">{filteredHistory.length}</strong> işlemden{" "}
                  <strong className="text-cyan-400">
                    {(validCurrentPage - 1) * pageSize + 1} -{" "}
                    {Math.min(validCurrentPage * pageSize, filteredHistory.length)}
                  </strong>{" "}
                  arası gösteriliyor
                </span>
              </div>

              <div className="flex items-center gap-1.5">
                <button
                  type="button"
                  onClick={() => setCurrentPage(1)}
                  disabled={validCurrentPage <= 1}
                  className="px-2.5 py-1 rounded bg-bunker-900 border border-bunker-800 disabled:opacity-30 hover:bg-bunker-800 text-slate-300 cursor-pointer disabled:cursor-not-allowed"
                >
                  « İlk
                </button>
                <button
                  type="button"
                  onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
                  disabled={validCurrentPage <= 1}
                  className="px-2.5 py-1 rounded bg-bunker-900 border border-bunker-800 disabled:opacity-30 hover:bg-bunker-800 text-slate-300 cursor-pointer disabled:cursor-not-allowed"
                >
                  ‹ Önceki
                </button>
                <span className="px-3 py-1 font-bold text-cyan-300 bg-cyan-950/60 rounded border border-cyan-800/50">
                  Sayfa {validCurrentPage} / {totalPages}
                </span>
                <button
                  type="button"
                  onClick={() => setCurrentPage((p) => Math.min(totalPages, p + 1))}
                  disabled={validCurrentPage >= totalPages}
                  className="px-2.5 py-1 rounded bg-bunker-900 border border-bunker-800 disabled:opacity-30 hover:bg-bunker-800 text-slate-300 cursor-pointer disabled:cursor-not-allowed"
                >
                  Sonraki ›
                </button>
                <button
                  type="button"
                  onClick={() => setCurrentPage(totalPages)}
                  disabled={validCurrentPage >= totalPages}
                  className="px-2.5 py-1 rounded bg-bunker-900 border border-bunker-800 disabled:opacity-30 hover:bg-bunker-800 text-slate-300 cursor-pointer disabled:cursor-not-allowed"
                >
                  Son »
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {/* 3. SEKME: SEMBOL BAZLI BAŞARI KARTLARI */}
      {activeTab === "SYMBOLS" && (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-3 p-3 rounded-lg bg-bunker-950/60 border border-bunker-800 text-xs font-mono">
            <span className="text-bunker-muted">
              🪙 Toplam <strong className="text-white">{symbolStatsList.length}</strong> aktif işlem görmüş sembol
            </span>
            <div className="flex items-center gap-1.5">
              <span className="text-bunker-muted text-[11px]">Sırala:</span>
              <button
                type="button"
                onClick={() => setSymbolSort("pnl")}
                className={`px-2.5 py-1 rounded text-[11px] font-semibold cursor-pointer ${
                  symbolSort === "pnl"
                    ? "bg-cyan-500/20 text-cyan-300 border border-cyan-500/40"
                    : "text-bunker-muted hover:text-white bg-bunker-900"
                }`}
              >
                💰 Net Kâr
              </button>
              <button
                type="button"
                onClick={() => setSymbolSort("winrate")}
                className={`px-2.5 py-1 rounded text-[11px] font-semibold cursor-pointer ${
                  symbolSort === "winrate"
                    ? "bg-cyan-500/20 text-cyan-300 border border-cyan-500/40"
                    : "text-bunker-muted hover:text-white bg-bunker-900"
                }`}
              >
                🎯 Kazanma Oranı
              </button>
              <button
                type="button"
                onClick={() => setSymbolSort("trades")}
                className={`px-2.5 py-1 rounded text-[11px] font-semibold cursor-pointer ${
                  symbolSort === "trades"
                    ? "bg-cyan-500/20 text-cyan-300 border border-cyan-500/40"
                    : "text-bunker-muted hover:text-white bg-bunker-900"
                }`}
              >
                📈 İşlem Adedi
              </button>
            </div>
          </div>

          {symbolStatsList.length === 0 ? (
            <div className="p-10 text-center rounded-xl border border-bunker-800 bg-bunker-900/60 text-bunker-muted font-mono text-xs">
              Seçilen tarih aralığında tamamlanmış sembol işlemi bulunmuyor.
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3.5">
              {symbolStatsList.map((st) => {
                const winRateColor =
                  st.winRate >= 60
                    ? "text-emerald-400 bg-emerald-500/10 border-emerald-500/30"
                    : st.winRate >= 40
                    ? "text-amber-400 bg-amber-500/10 border-amber-500/30"
                    : "text-rose-400 bg-rose-500/10 border-rose-500/30";

                const latestSymSignal = (data?.signals || []).find((s) => s.symbol === st.symbol);

                return (
                  <div
                    key={st.symbol}
                    className="p-4 rounded-xl border border-bunker-800 bg-bunker-900/90 flex flex-col justify-between hover:border-bunker-700 transition-colors"
                  >
                    <div>
                      {/* Kart Başlığı: Sembol ve WinRate */}
                      <div className="flex items-center justify-between gap-2 border-b border-bunker-800/80 pb-2.5">
                        <div className="flex items-center gap-1.5">
                          <span className="font-mono text-base font-bold text-white tracking-tight">
                            {st.symbol}
                          </span>
                        </div>
                        <span className={`font-mono text-[11px] font-bold px-2 py-0.5 rounded border ${winRateColor}`}>
                          %{st.winRate.toFixed(1)} Win
                        </span>
                      </div>

                      {/* Net Kâr Büyük Alan */}
                      <div className="mt-3">
                        <p className="text-[10px] font-mono uppercase text-bunker-muted">Toplam Net Kâr (₺)</p>
                        <div className="flex items-baseline gap-2 mt-0.5">
                          <span className={`text-xl font-mono font-bold ${pnlColor(st.totalNetPnl)}`}>
                            {st.totalNetPnl >= 0 ? "+" : ""}₺{st.totalNetPnl.toFixed(2)}
                          </span>
                          <span className={`text-xs font-mono ${pnlColor(st.totalPnlPct)}`}>
                            ({st.totalPnlPct >= 0 ? "+" : ""}{st.totalPnlPct.toFixed(2)}%)
                          </span>
                        </div>
                      </div>

                      {/* Mini Görsel Win / Loss Çubuğu */}
                      <div className="mt-3">
                        <div className="h-2 w-full rounded-full bg-bunker-950 overflow-hidden flex">
                          <div
                            style={{ width: `${st.winRate}%` }}
                            className="bg-emerald-500 h-full transition-all duration-500"
                            title={`Kazanç: %${st.winRate.toFixed(1)}`}
                          />
                          <div
                            style={{ width: `${100 - st.winRate}%` }}
                            className="bg-rose-500 h-full transition-all duration-500"
                            title={`Kayıp: %${(100 - st.winRate).toFixed(1)}`}
                          />
                        </div>
                      </div>

                      {/* İstatistik Satırları */}
                      <div className="mt-3.5 space-y-1.5 font-mono text-[11px] border-t border-bunker-800/60 pt-3">
                        <div className="flex items-center justify-between text-bunker-muted">
                          <span>Toplam İşlem:</span>
                          <span className="text-white font-bold">{st.totalTrades}</span>
                        </div>
                        <div className="flex items-center justify-between text-bunker-muted">
                          <span>Sonuç Dağılımı:</span>
                          <span className="text-slate-300">
                            <span className="text-emerald-400 font-bold">{st.winCount} TP</span>
                            {" · "}
                            <span className="text-rose-400 font-bold">{st.lossCount} SL</span>
                            {st.expiredCount > 0 && <span className="text-amber-400 font-bold"> · {st.expiredCount} Süre</span>}
                            {st.manualCount > 0 && <span className="text-blue-400 font-bold"> · {st.manualCount} Man.</span>}
                          </span>
                        </div>
                        <div className="flex items-center justify-between text-bunker-muted">
                          <span>Ort. Kâr / İşlem:</span>
                          <span className={pnlColor(st.avgNetPnl)}>
                            {st.avgNetPnl >= 0 ? "+" : ""}₺{st.avgNetPnl.toFixed(2)}
                          </span>
                        </div>
                        <div className="flex items-center justify-between text-[10px] text-bunker-muted pt-1">
                          <span>En İyi: <strong className="text-emerald-400">{st.bestPnl >= 0 ? "+" : ""}₺{st.bestPnl.toFixed(2)}</strong></span>
                          <span>En Kötü: <strong className="text-rose-400">₺{st.worstPnl.toFixed(2)}</strong></span>
                        </div>
                      </div>
                    </div>

                    {/* Canlı Grafik Aç Butonu */}
                    {latestSymSignal && (
                      <button
                        type="button"
                        onClick={() => setSelectedModalSignal(latestSymSignal)}
                        className="mt-4 w-full py-1.5 rounded-lg font-mono text-xs font-semibold bg-bunker-800 hover:bg-bunker-700 text-slate-200 border border-bunker-700 transition-colors flex items-center justify-center gap-1.5 cursor-pointer"
                      >
                        <span>📊</span> Canlı Grafiği Aç
                      </button>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      {/* 4. SEKME: STRATEJİ BAZLI BAŞARI KARTLARI */}
      {activeTab === "STRATEGIES" && (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-3 p-3 rounded-lg bg-bunker-950/60 border border-bunker-800 text-xs font-mono">
            <span className="text-bunker-muted">
              🔬 Toplam <strong className="text-white">{strategyStatsList.length}</strong> işlem üretmiş strateji
            </span>
            <div className="flex items-center gap-1.5">
              <span className="text-bunker-muted text-[11px]">Sırala:</span>
              <button
                type="button"
                onClick={() => setStrategySort("pnl")}
                className={`px-2.5 py-1 rounded text-[11px] font-semibold cursor-pointer ${
                  strategySort === "pnl"
                    ? "bg-cyan-500/20 text-cyan-300 border border-cyan-500/40"
                    : "text-bunker-muted hover:text-white bg-bunker-900"
                }`}
              >
                💰 Net Kâr
              </button>
              <button
                type="button"
                onClick={() => setStrategySort("winrate")}
                className={`px-2.5 py-1 rounded text-[11px] font-semibold cursor-pointer ${
                  strategySort === "winrate"
                    ? "bg-cyan-500/20 text-cyan-300 border border-cyan-500/40"
                    : "text-bunker-muted hover:text-white bg-bunker-900"
                }`}
              >
                🎯 Kazanma Oranı
              </button>
              <button
                type="button"
                onClick={() => setStrategySort("trades")}
                className={`px-2.5 py-1 rounded text-[11px] font-semibold cursor-pointer ${
                  strategySort === "trades"
                    ? "bg-cyan-500/20 text-cyan-300 border border-cyan-500/40"
                    : "text-bunker-muted hover:text-white bg-bunker-900"
                }`}
              >
                📈 İşlem Adedi
              </button>
            </div>
          </div>

          {strategyStatsList.length === 0 ? (
            <div className="p-10 text-center rounded-xl border border-bunker-800 bg-bunker-900/60 text-bunker-muted font-mono text-xs">
              Seçilen tarih aralığında tamamlanmış strateji işlemi bulunmuyor.
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3.5">
              {strategyStatsList.map((st) => {
                const winRateColor =
                  st.winRate >= 60
                    ? "text-emerald-400 bg-emerald-500/10 border-emerald-500/30"
                    : st.winRate >= 40
                    ? "text-amber-400 bg-amber-500/10 border-amber-500/30"
                    : "text-rose-400 bg-rose-500/10 border-rose-500/30";

                const pfColor =
                  st.profitFactor >= 1.5
                    ? "text-emerald-400 border-emerald-500/40 bg-emerald-500/10"
                    : st.profitFactor >= 1.0
                    ? "text-amber-400 border-amber-500/40 bg-amber-500/10"
                    : "text-rose-400 border-rose-500/40 bg-rose-500/10";

                return (
                  <div
                    key={st.strategyCode}
                    className="p-4 rounded-xl border border-bunker-800 bg-bunker-900/90 flex flex-col justify-between hover:border-bunker-700 transition-colors"
                  >
                    <div>
                      {/* Kart Başlığı */}
                      <div className="flex items-start justify-between gap-2 border-b border-bunker-800/80 pb-2.5">
                        <div className="min-w-0">
                          <h3 className="font-mono text-sm font-bold text-white truncate" title={st.strategyLabel}>
                            {st.strategyLabel}
                          </h3>
                          <span className="inline-block mt-0.5 text-[9px] font-mono px-1.5 py-0.5 rounded bg-bunker-800 text-bunker-muted">
                            {st.strategyCode}
                          </span>
                        </div>
                        <div className="flex flex-col items-end gap-1 shrink-0">
                          <span className={`font-mono text-[11px] font-bold px-2 py-0.5 rounded border ${winRateColor}`}>
                            %{st.winRate.toFixed(1)} Win
                          </span>
                          <span className={`font-mono text-[10px] font-bold px-1.5 py-0.5 rounded border ${pfColor}`}>
                            PF {st.profitFactor.toFixed(2)}
                          </span>
                        </div>
                      </div>

                      {/* Net Kâr Alanı */}
                      <div className="mt-3">
                        <p className="text-[10px] font-mono uppercase text-bunker-muted">Toplam Net Kâr (₺)</p>
                        <div className="flex items-baseline gap-2 mt-0.5">
                          <span className={`text-xl font-mono font-bold ${pnlColor(st.totalNetPnl)}`}>
                            {st.totalNetPnl >= 0 ? "+" : ""}₺{st.totalNetPnl.toFixed(2)}
                          </span>
                          <span className={`text-xs font-mono ${pnlColor(st.totalPnlPct)}`}>
                            ({st.totalPnlPct >= 0 ? "+" : ""}{st.totalPnlPct.toFixed(2)}%)
                          </span>
                        </div>
                      </div>

                      {/* Mini Görsel Win / Loss Çubuğu */}
                      <div className="mt-3">
                        <div className="h-2 w-full rounded-full bg-bunker-950 overflow-hidden flex">
                          <div
                            style={{ width: `${st.winRate}%` }}
                            className="bg-emerald-500 h-full transition-all duration-500"
                            title={`Kazanç: %${st.winRate.toFixed(1)}`}
                          />
                          <div
                            style={{ width: `${100 - st.winRate}%` }}
                            className="bg-rose-500 h-full transition-all duration-500"
                            title={`Kayıp: %${(100 - st.winRate).toFixed(1)}`}
                          />
                        </div>
                      </div>

                      {/* İstatistik Satırları */}
                      <div className="mt-3.5 space-y-1.5 font-mono text-[11px] border-t border-bunker-800/60 pt-3">
                        <div className="flex items-center justify-between text-bunker-muted">
                          <span>Toplam İşlem:</span>
                          <span className="text-white font-bold">{st.totalTrades}</span>
                        </div>
                        <div className="flex items-center justify-between text-bunker-muted">
                          <span>Dağılım:</span>
                          <span className="text-slate-300">
                            <span className="text-emerald-400 font-bold">{st.winCount} TP</span>
                            {" · "}
                            <span className="text-rose-400 font-bold">{st.lossCount} SL</span>
                            {st.expiredCount > 0 && <span className="text-amber-400 font-bold"> · {st.expiredCount} Süre</span>}
                            {st.manualCount > 0 && <span className="text-blue-400 font-bold"> · {st.manualCount} Man.</span>}
                          </span>
                        </div>
                        <div className="flex items-center justify-between text-bunker-muted">
                          <span>Ort. Getiri / İşlem:</span>
                          <span className={pnlColor(st.avgNetPnl)}>
                            {st.avgNetPnl >= 0 ? "+" : ""}₺{st.avgNetPnl.toFixed(2)}
                          </span>
                        </div>
                        <div className="flex items-center justify-between text-bunker-muted">
                          <span>En İyi Sembol:</span>
                          <span className="text-cyan-300 font-bold">
                            {st.bestSymbol} ({st.bestSymbolPnl >= 0 ? "+" : ""}₺{st.bestSymbolPnl.toFixed(2)})
                          </span>
                        </div>
                        <div className="flex items-center justify-between text-[10px] text-bunker-muted pt-1">
                          <span>Brüt Kazanç: <strong className="text-emerald-400">₺{st.grossProfit.toFixed(2)}</strong></span>
                          <span>Brüt Kayıp: <strong className="text-rose-400">₺{st.grossLoss.toFixed(2)}</strong></span>
                        </div>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      {/* CANLI GRAFİK & KDJ / EMA 50 AÇILIR PENCERESİ (MODAL) */}
      {selectedModalSignal && (
        <SpotChartModal
          signal={selectedModalSignal}
          onClose={() => setSelectedModalSignal(null)}
        />
      )}
    </div>
  );
}
