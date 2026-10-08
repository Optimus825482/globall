"use client";

export const dynamic = "force-dynamic";

import React, { useState, useEffect, useMemo, useCallback } from "react";
import Link from "next/link";
import { apiFetch } from "../../lib/api";
import { useTheme } from "../../lib/theme";
import EVShieldModal, { EVShieldStatusResponse } from "../components/EVShieldModal";

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
  exit_reason?: string;
  exit_reason_title?: string;
  close_time?: string;
  exit_time?: string;
  open_time?: string;
  time?: number | string;
  closed_at_ts?: number;
  strategy?: string;
  entry_source?: string;
}

// Strateji kimliği → panelde okunur kısa etiket (backend `strategy` alanı, 2026-10-08).
const STRATEGY_LABELS: Record<string, string> = {
  EMA_ADX_PULLBACK_M5: "EMA+ADX Geri Çekilme (M5)",
  DONCHIAN_ADX: "Donchian Kırılımı",
  M1_M5_RADAR_SCALPER: "Radar Skalper",
  IC_MARKETS_MT5: "IC Markets MT5",
};

function strategyLabel(code?: string): string {
  if (!code) return "-";
  return STRATEGY_LABELS[code] || code;
}

interface KPIStats {
  total_trades: number;
  wins: number;
  losses: number;
  win_rate: number;
  total_pnl_usd: number;
  balance: number;
  equity: number;
  open_positions_count: number;
  open_pnl_usd: number;
}

interface SymbolDailyPerf {
  symbol: string;
  display: string;
  category?: string;
  totalTrades: number;
  closedTrades: number;
  openTrades: number;
  wins: number;
  losses: number;
  winRate: number;
  realizedPnlUsd: number;
  openPnlUsd: number;
  netPnlUsd: number;
  totalPips: number;
}

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

function formatClockTime(timeStr?: string | number, closedAtTs?: number): string {
  if (!timeStr && closedAtTs && typeof closedAtTs === "number" && closedAtTs > 0) {
    const ms = closedAtTs > 1e11 ? closedAtTs : closedAtTs * 1000;
    const d = new Date(ms);
    if (!isNaN(d.getTime())) {
      const hh = String(d.getUTCHours()).padStart(2, "0");
      const mm = String(d.getUTCMinutes()).padStart(2, "0");
      const ss = String(d.getUTCSeconds()).padStart(2, "0");
      return `${hh}:${mm}:${ss}`;
    }
  }
  if (!timeStr) return "—";
  try {
    const raw = String(timeStr).trim();
    const timeMatch = raw.match(/(\d{2}):(\d{2})(?::(\d{2}))?/);
    if (timeMatch) {
      return `${timeMatch[1]}:${timeMatch[2]}:${timeMatch[3] || "00"}`;
    }
    return raw;
  } catch {
    return String(timeStr);
  }
}

// Bulunulan tarihteki işlem zaman damgasını milisaniyeye çevirir (MT5 zaman damgasıyla uyumlu)
function parseTradeTime(t: ClosedTrade | any): number {
  if (typeof t.closed_at_ts === "number" && t.closed_at_ts > 0) {
    return t.closed_at_ts > 1e11 ? t.closed_at_ts : t.closed_at_ts * 1000;
  }
  if (typeof t.time === "number" && t.time > 0) {
    return t.time > 1e11 ? t.time : t.time * 1000;
  }
  const rawStr = t.close_time || t.exit_time || t.time || t.open_time;
  if (!rawStr) return 0;

  const s = String(rawStr).trim();
  const parts = s.match(/^(\d{4})-(\d{2})-(\d{2})[T\s](\d{2}):(\d{2}):?(\d{2})?/);
  if (parts) {
    return Date.UTC(Number(parts[1]), Number(parts[2]) - 1, Number(parts[3]), Number(parts[4]), Number(parts[5]), Number(parts[6] || 0));
  }
  const parsed = new Date(s).getTime();
  return isNaN(parsed) ? 0 : parsed;
}

// Bulunulan tarihteki saat 00:01:00 eşiğini verir (MT5 sunucu takvimiyle uyumlu)
function getToday0001Cutoff(): number {
  const now = new Date();
  return Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate(), 0, 1, 0);
}

export default function ForexIslemlerPage() {
  // Global Tema Context'i
  const { isLight: isLightMode, toggleTheme } = useTheme();
  const [loading, setLoading] = useState<boolean>(true);
  const [refreshing, setRefreshing] = useState<boolean>(false);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  // Sekme Seçimi: Varsayılan "OPEN" (Açık Pozisyonlar) - Kullanıcı isteği: Arayüz kalabalığını önleme
  const [activeTab, setActiveTab] = useState<"OPEN" | "CLOSED">("OPEN");

  // Veri Durumları
  const [openPositions, setOpenPositions] = useState<OpenPosition[]>([]);
  const [closedTrades, setClosedTrades] = useState<ClosedTrade[]>([]);
  const [kpi, setKpi] = useState<KPIStats>({
    total_trades: 0,
    wins: 0,
    losses: 0,
    win_rate: 0,
    total_pnl_usd: 0,
    balance: 10000,
    equity: 10000,
    open_positions_count: 0,
    open_pnl_usd: 0,
  });

  // Kapanan İşlemler Filtresi & Sayfalama (Dinamik Sayfa Başı Kayıt: 10/20/50)
  const [filterOutcome, setFilterOutcome] = useState<"ALL" | "WIN" | "LOSS">("ALL");
  const [currentPage, setCurrentPage] = useState<number>(1);
  const [pageSize, setPageSize] = useState<number>(10);

  // Sembol EV Kalkanı Modalı & Durumu
  const [evShieldModalOpen, setEvShieldModalOpen] = useState<boolean>(false);
  const [evShieldStatus, setEvShieldStatus] = useState<EVShieldStatusResponse | null>(null);

  // Veri Yükleme (Günün 00:01 Sonrası İşlemleri ve Canlı Pozisyonlar)
  const fetchData = useCallback(async (isSilent = false) => {
    if (!isSilent) setRefreshing(true);
    try {
      const [reportRes, statusRes] = await Promise.all([
        apiFetch("/api/forex/auto-paper/trades?period=today&limit=250"),
        apiFetch("/api/forex/auto-paper/status").catch(() => null),
      ]);

      if (reportRes) {
        // Canlı açık pozisyonlar
        if (Array.isArray(reportRes.open_positions)) {
          setOpenPositions(reportRes.open_positions);
        }

        // Bulunulan tarihteki saat 00:01'den sonraki kapanan işlemleri filtrele
        const cutoff0001 = getToday0001Cutoff();
        let validTrades: ClosedTrade[] = [];
        if (Array.isArray(reportRes.trades)) {
          validTrades = reportRes.trades.filter((t: ClosedTrade) => {
            const ts = parseTradeTime(t);
            return ts >= cutoff0001;
          });
          setClosedTrades(validTrades);
        }

        // Günün 00:01 sonrası başarı metriklerini (KPI) hesapla
        let winsCount = 0;
        let lossesCount = 0;
        let totalPnl = 0;
        for (const t of validTrades) {
          const pnl = Number(t.pnl_usd ?? 0);
          totalPnl += pnl;
          if (pnl > 0 || t.outcome === "WIN") {
            winsCount += 1;
          } else if (pnl < 0 || t.outcome === "LOSS") {
            lossesCount += 1;
          }
        }
        const totalTradesCount = validTrades.length;
        const winRatePct = totalTradesCount > 0 ? (winsCount / totalTradesCount) * 100 : 0;

        setKpi((prev) => ({
          ...prev,
          total_trades: totalTradesCount,
          wins: winsCount,
          losses: lossesCount,
          win_rate: winRatePct,
          total_pnl_usd: totalPnl,
          balance: statusRes?.balance ?? reportRes.kpi?.balance ?? prev.balance,
          equity: statusRes?.equity ?? reportRes.kpi?.equity ?? prev.equity,
          open_positions_count: Array.isArray(reportRes.open_positions) ? reportRes.open_positions.length : prev.open_positions_count,
        }));
      } else if (statusRes) {
        const k = statusRes.today_kpi;
        setKpi((prev) => ({
          ...prev,
          total_trades: k?.total_trades ?? 0,
          wins: k?.won_trades ?? 0,
          losses: k?.lost_trades ?? 0,
          win_rate: k?.win_rate_pct ?? 0,
          total_pnl_usd: statusRes.daily_pnl ?? 0,
          balance: statusRes.balance ?? prev.balance,
          equity: statusRes.equity ?? prev.equity,
        }));
      }

      if (statusRes?.ev_shield) {
        setEvShieldStatus(statusRes.ev_shield);
      }

      setLastUpdated(new Date());
    } catch (err) {
      console.error("Forex işlemler verisi çekme hatası:", err);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    fetchData(false);
    const timer = setInterval(() => {
      if (!document.hidden) {
        fetchData(true);
      }
    }, 3000);
    return () => clearInterval(timer);
  }, [fetchData]);

  // Dinamik Açık PnL Toplamları
  const openSummary = useMemo(() => {
    let totalPnlUsd = 0;
    let totalPnlPips = 0;
    for (const p of openPositions) {
      totalPnlUsd += Number(p.pnl_usd ?? 0);
      totalPnlPips += Number(p.pnl_pips ?? 0);
    }
    return {
      pnlUsd: totalPnlUsd,
      pnlPips: totalPnlPips,
      count: openPositions.length,
    };
  }, [openPositions]);

  // Açık Pozisyonlar: Aynı semboller alt alta gelecek şekilde sembole göre sıralı liste
  const sortedOpenPositions = useMemo(() => {
    return [...openPositions].sort((a, b) => {
      const symA = (a.symbol || a.display || "").toUpperCase();
      const symB = (b.symbol || b.display || "").toUpperCase();
      if (symA !== symB) {
        return symA.localeCompare(symB);
      }
      const timeA = a.open_time ? new Date(a.open_time).getTime() : 0;
      const timeB = b.open_time ? new Date(b.open_time).getTime() : 0;
      return timeB - timeA;
    });
  }, [openPositions]);

  // Günün İşlem Açılan Sembollerinin Başarı ve Kârlılık Performansı (Yan Yana 3 Kart)
  const symbolPerformanceList = useMemo<SymbolDailyPerf[]>(() => {
    const map = new Map<string, SymbolDailyPerf>();

    const getOrCreate = (sym: string, display?: string, cat?: string) => {
      if (!map.has(sym)) {
        map.set(sym, {
          symbol: sym,
          display: display || sym,
          category: cat,
          totalTrades: 0,
          closedTrades: 0,
          openTrades: 0,
          wins: 0,
          losses: 0,
          winRate: 0,
          realizedPnlUsd: 0,
          openPnlUsd: 0,
          netPnlUsd: 0,
          totalPips: 0,
        });
      }
      return map.get(sym)!;
    };

    // 1. Kapanan işlemler
    for (const t of closedTrades) {
      const item = getOrCreate(t.symbol, t.display);
      item.totalTrades += 1;
      item.closedTrades += 1;
      const pnl = Number(t.pnl_usd ?? 0);
      const pips = Number(t.pnl_pips ?? 0);
      item.realizedPnlUsd += pnl;
      item.totalPips += pips;
      if (pnl > 0 || t.outcome === "WIN") {
        item.wins += 1;
      } else if (pnl < 0 || t.outcome === "LOSS") {
        item.losses += 1;
      }
    }

    // 2. Açık pozisyonlar
    for (const p of openPositions) {
      const item = getOrCreate(p.symbol, p.display, p.category);
      item.totalTrades += 1;
      item.openTrades += 1;
      const pnl = Number(p.pnl_usd ?? 0);
      const pips = Number(p.pnl_pips ?? 0);
      item.openPnlUsd += pnl;
      item.totalPips += pips;
    }

    // 3. Oranları hesapla - YALNIZCA İŞLEM AÇILMIŞ SEMBOLLER (totalTrades > 0)
    // İşlem açılmamış sembollerin kartları tamamen gizlenir
    const list = Array.from(map.values())
      .filter((item) => item.totalTrades > 0 && (item.closedTrades > 0 || item.openTrades > 0))
      .map((item) => {
        const winRate =
          item.closedTrades > 0
            ? (item.wins / item.closedTrades) * 100
            : item.openPnlUsd >= 0
            ? 100
            : 0;
        const netPnlUsd = item.realizedPnlUsd + item.openPnlUsd;
        return {
          ...item,
          winRate,
          netPnlUsd,
        };
      });

    // En çok işlem gören sembolden başlayarak azalan sırada sırala (en çok işlem gören en üstte)
    return list.sort((a, b) => {
      if (b.totalTrades !== a.totalTrades) {
        return b.totalTrades - a.totalTrades;
      }
      if (b.netPnlUsd !== a.netPnlUsd) {
        return b.netPnlUsd - a.netPnlUsd;
      }
      return b.winRate - a.winRate;
    });
  }, [closedTrades, openPositions]);

  // Filtrelenmiş Kapanan İşlemler
  const filteredClosedTrades = useMemo(() => {
    return closedTrades.filter((t) => {
      if (filterOutcome === "ALL") return true;
      const isWin = Number(t.pnl_usd ?? 0) >= 0 || t.outcome === "WIN";
      if (filterOutcome === "WIN") return isWin;
      if (filterOutcome === "LOSS") return !isWin;
      return true;
    });
  }, [closedTrades, filterOutcome]);

  // Sayfalama (Dinamik sayfa başı kayıt ile)
  const totalPages = Math.max(1, Math.ceil(filteredClosedTrades.length / pageSize));
  const safeCurrentPage = Math.min(Math.max(1, currentPage), totalPages);
  const paginatedClosedTrades = useMemo(() => {
    const startIndex = (safeCurrentPage - 1) * pageSize;
    return filteredClosedTrades.slice(startIndex, startIndex + pageSize);
  }, [filteredClosedTrades, safeCurrentPage, pageSize]);

  const handleFilterChange = (filter: "ALL" | "WIN" | "LOSS") => {
    setFilterOutcome(filter);
    setCurrentPage(1);
  };

  // Dinamik Tema Stilleri
  const theme = useMemo(() => {
    if (isLightMode) {
      return {
        wrapper: "bg-slate-100 text-slate-800 min-h-screen",
        cardBg: "bg-white border-slate-200/90 shadow-sm",
        headerBg: "bg-gradient-to-r from-blue-50/90 via-white to-indigo-50/90 border-blue-200/80 shadow-sm",
        kpiCard: "bg-white border-slate-200/90 shadow-sm text-slate-900",
        tableHeader: "bg-slate-100/90 text-slate-600 border-slate-200 text-[11px]",
        tableRow: "hover:bg-slate-50 transition-colors border-slate-100",
        textPrimary: "text-slate-900 font-bold",
        textSecondary: "text-slate-500",
        badgeBg: "bg-slate-100 text-slate-700 border-slate-200",
        accentBorder: "border-slate-200",
        profitBg: "bg-emerald-50 text-emerald-700 border-emerald-300 font-bold",
        lossBg: "bg-rose-50 text-rose-700 border-rose-300 font-bold",
        pageActive: "bg-blue-600 text-white border-blue-600",
        pageInactive: "bg-white text-slate-700 border-slate-300 hover:bg-slate-50",
      };
    }
    return {
      wrapper: "bg-[#080c14] text-white min-h-screen",
      cardBg: "bg-bunker-900/90 border-bunker-800 shadow-xl",
      headerBg: "bg-gradient-to-r from-blue-950/40 via-slate-900/60 to-indigo-950/40 border-blue-500/20 shadow-lg",
      kpiCard: "bg-bunker-900/80 border-bunker-800 shadow-lg text-white",
      tableHeader: "bg-bunker-950/80 text-bunker-muted border-bunker-800 text-[11px]",
      tableRow: "hover:bg-bunker-800/40 transition-colors border-bunker-800/60",
      textPrimary: "text-white font-bold",
      textSecondary: "text-bunker-muted",
      badgeBg: "bg-bunker-800 text-bunker-300 border-bunker-700",
      accentBorder: "border-bunker-800",
      profitBg: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30 font-bold",
      lossBg: "bg-rose-500/15 text-rose-400 border-rose-500/30 font-bold",
      pageActive: "bg-blue-600 text-white border-blue-500",
      pageInactive: "bg-bunker-800 text-bunker-300 border-bunker-700 hover:bg-bunker-750",
    };
  }, [isLightMode]);

  return (
    <div className={`space-y-4 pb-16 font-mono transition-colors duration-200 ${theme.wrapper}`}>
      
      {/* 1. ÜST BAŞLIK & TEMA / YENİLEME ÇUBUĞU */}
      <div className={`p-4 rounded-2xl border flex flex-wrap items-center justify-between gap-3 ${theme.headerBg}`}>
        <div className="flex items-center gap-3">
          <div className="w-11 h-11 rounded-xl bg-blue-500/20 border border-blue-400/40 flex items-center justify-center text-2xl shadow-[0_0_16px_rgba(59,130,246,0.25)] shrink-0">
            ⚡
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-base sm:text-lg font-black tracking-tight">
                FOREX CANLI İŞLEM İZLEME
              </h1>
              <span className="flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-bold bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 border border-emerald-500/30">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
                CANLI AKIŞ
              </span>
            </div>
            <p className={`text-xs mt-0.5 ${theme.textSecondary}`}>
              Açık ve 00:01 Sonrası Kapanan Forex İşlemleri · Anlık Dinamik K/Z (PnL) &amp; Sembol Başarıları
            </p>
          </div>
        </div>

        {/* Sağ Kontroller: Açık/Koyu Mod Butonu & Manuel Yenileme */}
        <div className="flex items-center gap-2 text-xs">
          <button
            type="button"
            onClick={() => setEvShieldModalOpen(true)}
            className={`px-3 py-1.5 rounded-xl border font-bold flex items-center gap-1.5 transition-all shadow-sm ${
              (evShieldStatus?.blocked_count ?? 0) > 0
                ? "bg-rose-500/20 text-rose-700 dark:text-rose-300 border-rose-500/50 ring-2 ring-rose-500/40 animate-pulse"
                : isLightMode
                ? "bg-white text-slate-800 border-slate-300 hover:bg-slate-50"
                : "bg-bunker-800 text-white border-bunker-700 hover:bg-bunker-750"
            }`}
            title="Sembol EV Kalkanı ve Muafiyet Listesi"
          >
            <span>🛡️ EV Kalkanı</span>
            {(evShieldStatus?.blocked_count ?? 0) > 0 && (
              <span className="px-1.5 py-0.2 rounded-full text-[10px] bg-rose-600 text-white font-black">
                {evShieldStatus?.blocked_count}
              </span>
            )}
          </button>

          <button
            type="button"
            onClick={toggleTheme}
            className={`px-3 py-1.5 rounded-xl border font-bold flex items-center gap-1.5 transition-all shadow-sm ${
              isLightMode
                ? "bg-amber-50 text-amber-900 border-amber-300 hover:bg-amber-100"
                : "bg-bunker-800 text-blue-300 border-bunker-700 hover:bg-bunker-750"
            }`}
            title="Açık Mod / Koyu Mod Değiştir"
          >
            <span>{isLightMode ? "☀️" : "🌙"}</span>
            <span>{isLightMode ? "Açık Mod" : "Koyu Mod"}</span>
          </button>

          <button
            type="button"
            onClick={() => fetchData(false)}
            disabled={refreshing}
            className={`px-3 py-1.5 rounded-xl border font-bold flex items-center gap-1.5 transition-all shadow-sm ${
              isLightMode
                ? "bg-white text-slate-700 border-slate-300 hover:bg-slate-50"
                : "bg-bunker-800 text-white border-bunker-700 hover:bg-bunker-750"
            }`}
          >
            <span className={refreshing ? "animate-spin" : ""}>🔄</span>
            <span className="hidden sm:inline">Yenile</span>
          </button>

          {lastUpdated && (
            <span className={`text-[10px] hidden md:inline ml-1 ${theme.textSecondary}`}>
              {lastUpdated.toLocaleTimeString("tr-TR")}
            </span>
          )}
        </div>
      </div>

      {/* EV KALKANI UYARI BANNERI */}
      {evShieldStatus && evShieldStatus.blocked_count > 0 && (
        <div
          className={`p-3.5 rounded-2xl border flex flex-col sm:flex-row sm:items-center justify-between gap-3 shadow-md ${
            isLightMode
              ? "bg-rose-50 border-rose-300 ring-1 ring-rose-200"
              : "bg-rose-950/30 border-rose-800/80 ring-1 ring-rose-900/40"
          }`}
        >
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-rose-500/20 border border-rose-500/40 flex items-center justify-center text-lg shrink-0 animate-pulse">
              🛡️
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span className="text-xs font-black uppercase text-rose-700 dark:text-rose-300">
                  Sembol EV Kalkanı: {evShieldStatus.blocked_count} Sembol Dinlenmede
                </span>
              </div>
              <p className="text-xs mt-0.5 text-slate-700 dark:text-slate-300 font-medium">
                {evShieldStatus.symbols
                  .filter((s) => s.is_blocked)
                  .map((s) => `${s.display} (${s.net_usd < 0 ? `-$${Math.abs(s.net_usd).toFixed(2)}` : `$${s.net_usd}`})`)
                  .join(", ")}{" "}
                akut kayıp nedeniyle yeni girişlere kapatıldı.
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={() => setEvShieldModalOpen(true)}
            className="px-3.5 py-1.5 rounded-xl text-xs font-black bg-rose-600 hover:bg-rose-500 text-white shadow-sm transition-all flex items-center gap-1.5 shrink-0 self-start sm:self-auto active:scale-95"
          >
            <span>🛡️ Kalkanı İncele &amp; İptal Et</span>
            <span>↗</span>
          </button>
        </div>
      )}

      {/* 2. EN ÜST DASHBOARD & GÜNLÜK BAŞARI KARTLARI (4'LÜ GRID) */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 px-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="w-2.5 h-2.5 rounded-full bg-emerald-400 animate-pulse" />
          <h2 className={`text-sm font-bold uppercase tracking-wider ${theme.textPrimary}`}>
            Günün Başarı Metrikleri
          </h2>
          <span className="text-[10px] px-2 py-0.5 rounded-full bg-cyan-950/80 border border-cyan-500/30 text-cyan-300 font-semibold">
            Günün İşlemleri (00:01 Sonrası) · Canlı Akış (UTC+3)
          </span>
        </div>
        <Link
          href="/forex/reports"
          className="text-xs text-blue-500 dark:text-cyan-400 hover:underline flex items-center gap-1 font-semibold transition-colors"
        >
          <span>📅 Geçmiş Tarihli Kayıtları İncele</span>
          <span>→</span>
        </Link>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
        
        {/* KART 1: GÜNÜN BAŞARI ORANI (%) */}
        <div className={`p-4 rounded-2xl border ${theme.kpiCard}`}>
          <div className="flex items-center justify-between">
            <span className={`text-[11px] font-bold uppercase tracking-wider ${theme.textSecondary}`}>
              Günün Başarı Oranı
            </span>
            <span className="text-lg">🎯</span>
          </div>
          <div className="mt-2 flex items-baseline gap-2">
            <span className="text-2xl sm:text-3xl font-black text-emerald-600 dark:text-emerald-400">
              %{kpi.win_rate.toFixed(1)}
            </span>
            <span className={`text-xs ${theme.textSecondary}`}>
              ({kpi.wins}K / {kpi.losses}Z)
            </span>
          </div>
          <div className="mt-2.5 w-full bg-slate-200 dark:bg-bunker-800 h-2 rounded-full overflow-hidden">
            <div
              className="bg-emerald-500 h-full rounded-full transition-all duration-500"
              style={{ width: `${Math.min(100, Math.max(0, kpi.win_rate))}%` }}
            />
          </div>
          <div className={`mt-1.5 text-[10px] flex justify-between ${theme.textSecondary}`}>
            <span>{kpi.total_trades} Toplam İşlem</span>
            <span>{kpi.wins} Başarılı Kapanış</span>
          </div>
        </div>

        {/* KART 2: GÜNLÜK NET KÂRLILIK DURUMU */}
        <div className={`p-4 rounded-2xl border ${theme.kpiCard}`}>
          <div className="flex items-center justify-between">
            <span className={`text-[11px] font-bold uppercase tracking-wider ${theme.textSecondary}`}>
              Bugünkü Net K/Z
            </span>
            <span className="text-lg">💰</span>
          </div>
          <div className="mt-2 flex items-baseline gap-2">
            <span
              className={`text-2xl sm:text-3xl font-black ${
                kpi.total_pnl_usd >= 0
                  ? "text-emerald-600 dark:text-emerald-400"
                  : "text-rose-600 dark:text-rose-400"
              }`}
            >
              {kpi.total_pnl_usd >= 0 ? "+" : ""}${kpi.total_pnl_usd.toFixed(2)}
            </span>
          </div>
          <div className="mt-2.5 flex items-center justify-between text-xs">
            <span className={`text-[11px] ${theme.textSecondary}`}>
              Gerçekleşen Günlük Bilanço
            </span>
            <span
              className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                kpi.total_pnl_usd >= 0 ? theme.profitBg : theme.lossBg
              }`}
            >
              {kpi.total_pnl_usd >= 0 ? "▲ NET KÂR" : "▼ NET ZARAR"}
            </span>
          </div>
        </div>

        {/* KART 3: ÖZKAYNAK & HESAP BAKİYESİ (Kullanıcı İsteği: Büyük Olan Özkaynak) */}
        <div className={`p-4 rounded-2xl border ${theme.kpiCard}`}>
          <div className="flex items-center justify-between">
            <span className={`text-[11px] font-bold uppercase tracking-wider ${theme.textSecondary}`}>
              Özkaynak (Equity)
            </span>
            <span className="text-lg">🏛️</span>
          </div>
          <div className="mt-2 flex items-baseline gap-2">
            <span className="text-2xl sm:text-3xl font-black text-blue-600 dark:text-blue-400">
              ${kpi.equity.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
            </span>
          </div>
          <div className="mt-2.5 flex items-center justify-between text-xs">
            <span className={`text-[11px] ${theme.textSecondary}`}>
              Hesap Bakiyesi:
            </span>
            <span className="font-bold text-slate-800 dark:text-slate-200 text-xs">
              ${kpi.balance.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
            </span>
          </div>
        </div>

        {/* KART 4: TOPLAM AÇIK İŞLEMLERİN PnL'İ */}
        <div className={`p-4 rounded-2xl border ${theme.kpiCard}`}>
          <div className="flex items-center justify-between">
            <span className={`text-[11px] font-bold uppercase tracking-wider ${theme.textSecondary}`}>
              Açık İşlemler PnL
            </span>
            <span className="text-lg">📊</span>
          </div>
          <div className="mt-2 flex items-baseline gap-2">
            <span
              className={`text-2xl sm:text-3xl font-black ${
                openSummary.pnlUsd >= 0
                  ? "text-emerald-600 dark:text-emerald-400"
                  : "text-rose-600 dark:text-rose-400"
              }`}
            >
              {openSummary.pnlUsd >= 0 ? "+" : ""}${openSummary.pnlUsd.toFixed(2)}
            </span>
            <span
              className={`text-xs font-bold ${
                openSummary.pnlPips >= 0
                  ? "text-emerald-600 dark:text-emerald-400"
                  : "text-rose-600 dark:text-rose-400"
              }`}
            >
              ({openSummary.pnlPips >= 0 ? "+" : ""}{openSummary.pnlPips.toFixed(1)}p)
            </span>
          </div>
          <div className="mt-2.5 flex items-center justify-between text-xs">
            <span className={`text-[11px] ${theme.textSecondary}`}>
              {openSummary.count} Aktif Açık Pozisyon
            </span>
            <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-blue-500/10 text-blue-600 dark:text-blue-400 border border-blue-400/30">
              YÜZEN K/Z
            </span>
          </div>
        </div>

      </div>

      {/* 2.5 TAB SEÇİCİ (AÇIK POZİSYONLAR / KAPANAN İŞLEMLER) */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b pb-3 border-slate-200 dark:border-bunker-800">
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setActiveTab("OPEN")}
            className={`px-4 py-2 rounded-xl text-xs sm:text-sm font-bold flex items-center gap-2 transition-all shadow-sm ${
              activeTab === "OPEN"
                ? "bg-blue-600 text-white shadow-blue-500/25"
                : isLightMode
                ? "bg-white text-slate-600 border border-slate-200 hover:bg-slate-100"
                : "bg-bunker-900 text-bunker-muted border border-bunker-800 hover:bg-bunker-800 hover:text-white"
            }`}
          >
            <span>💼</span>
            <span>Açık Pozisyonlar</span>
            <span
              className={`px-2 py-0.5 rounded-full text-[11px] font-black ${
                activeTab === "OPEN"
                  ? "bg-white/20 text-white"
                  : isLightMode
                  ? "bg-slate-100 text-slate-700"
                  : "bg-bunker-800 text-bunker-muted"
              }`}
            >
              {openPositions.length}
            </span>
          </button>

          <button
            type="button"
            onClick={() => setActiveTab("CLOSED")}
            className={`px-4 py-2 rounded-xl text-xs sm:text-sm font-bold flex items-center gap-2 transition-all shadow-sm ${
              activeTab === "CLOSED"
                ? "bg-blue-600 text-white shadow-blue-500/25"
                : isLightMode
                ? "bg-white text-slate-600 border border-slate-200 hover:bg-slate-100"
                : "bg-bunker-900 text-bunker-muted border border-bunker-800 hover:bg-bunker-800 hover:text-white"
            }`}
          >
            <span>📜</span>
            <span>Kapanan İşlemler</span>
            <span
              className={`px-2 py-0.5 rounded-full text-[11px] font-black ${
                activeTab === "CLOSED"
                  ? "bg-white/20 text-white"
                  : isLightMode
                  ? "bg-slate-100 text-slate-700"
                  : "bg-bunker-800 text-bunker-muted"
              }`}
            >
              {closedTrades.length}
            </span>
          </button>
        </div>

        <Link
          href="/forex/reports"
          className="text-xs font-bold text-blue-600 dark:text-cyan-400 hover:underline flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-blue-500/20 bg-blue-500/5 hover:bg-blue-500/10 transition-colors"
        >
          <span>📊 Detaylı Raporlar &amp; Analiz</span>
          <span>→</span>
        </Link>
      </div>

      {activeTab === "OPEN" && (
        <>
      {/* 3. AÇIK OLAN FOREX İŞLEMLERİ (KULLANICI İSTEĞİ: KAPAT BUTONU KALDIRILDI) */}
      <div className={`rounded-2xl border overflow-hidden ${theme.cardBg}`}>
        <div className="p-3.5 sm:p-4 border-b flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <span className="text-lg">💼</span>
            <h2 className={`text-sm font-bold uppercase tracking-wide ${theme.textPrimary}`}>
              Açık Olan Forex İşlemleri
            </h2>
            <span className={`px-2 py-0.5 rounded text-xs font-bold ${theme.badgeBg}`}>
              {openPositions.length} Açık Pozisyon
            </span>
          </div>

          <div className="flex items-center gap-2 text-xs">
            <span className={theme.textSecondary}>Toplam Anlık K/Z:</span>
            <span
              className={`px-2.5 py-1 rounded-lg border font-bold ${
                openSummary.pnlUsd >= 0 ? theme.profitBg : theme.lossBg
              }`}
            >
              {openSummary.pnlUsd >= 0 ? "+" : ""}${openSummary.pnlUsd.toFixed(2)}
            </span>
          </div>
        </div>

        {loading ? (
          <div className="p-12 text-center text-xs">
            <div className="inline-block w-6 h-6 border-2 border-blue-500 border-t-transparent rounded-full animate-spin mb-2" />
            <p className={theme.textSecondary}>Açık pozisyonlar taranıyor…</p>
          </div>
        ) : openPositions.length === 0 ? (
          <div className="p-10 text-center space-y-2">
            <div className="text-3xl">☕</div>
            <p className={`text-sm font-bold ${theme.textPrimary}`}>
              Şu an açık forex işlemi bulunmuyor.
            </p>
            <p className={`text-xs ${theme.textSecondary}`}>
              Otonom motor radar filtrelerini ve onay sinyallerini taramaya devam ediyor.
            </p>
            <div className="pt-2">
              <Link
                href="/forex"
                className="px-3 py-1.5 rounded-lg bg-blue-600 text-white font-bold text-xs hover:bg-blue-500 transition-colors inline-block"
              >
                📡 Forex Radarına Git
              </Link>
            </div>
          </div>
        ) : (
          <>
            {/* Masaüstü Tablo Görünümü */}
            <div className="hidden md:block overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead className={`uppercase border-b ${theme.tableHeader}`}>
                  <tr>
                    <th className="py-3 px-4">Sembol / Parite</th>
                    <th className="py-3 px-3">Strateji</th>
                    <th className="py-3 px-3">Yön</th>
                    <th className="py-3 px-3">Lot</th>
                    <th className="py-3 px-3">Giriş Fiyatı</th>
                    <th className="py-3 px-3">Güncel Fiyat</th>
                    <th className="py-3 px-4">Anlık Kâr / Zarar (PnL)</th>
                    <th className="py-3 px-4 text-right">Hedef / Stop</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 dark:divide-bunker-800/60">
                  {sortedOpenPositions.map((p) => {
                    const isBuy = p.direction === "BUY";
                    const isProfitable = Number(p.pnl_usd ?? 0) >= 0;
                    return (
                      <tr key={p.id || p.ticket} className={theme.tableRow}>
                        <td className="py-3.5 px-4">
                          <div className="flex items-center gap-2">
                            <span className="font-bold text-sm">
                              {p.display || p.symbol}
                            </span>
                            {p.category && (
                              <span className="text-[10px] px-1.5 py-0.5 rounded bg-slate-100 dark:bg-bunker-800 text-slate-500 dark:text-bunker-muted uppercase">
                                {p.category}
                              </span>
                            )}
                          </div>
                          {p.open_time && (
                            <div className={`text-[10px] ${theme.textSecondary}`}>
                              {formatClockTime(p.open_time)}
                            </div>
                          )}
                        </td>

                        {/* Strateji */}
                        <td className="py-3.5 px-3">
                          <span className={`inline-flex items-center px-2 py-0.5 rounded text-[10px] font-bold whitespace-nowrap border ${
                            p.strategy === "EMA_ADX_PULLBACK_M5"
                              ? "bg-amber-500/15 text-amber-600 dark:text-amber-300 border-amber-500/30"
                              : p.strategy === "DONCHIAN_ADX"
                              ? "bg-violet-500/15 text-violet-600 dark:text-violet-300 border-violet-500/30"
                              : p.strategy === "M1_M5_RADAR_SCALPER"
                              ? "bg-sky-500/15 text-sky-600 dark:text-sky-300 border-sky-500/30"
                              : "bg-slate-500/10 text-slate-500 dark:text-bunker-muted border-slate-500/20"
                          }`}>
                            {strategyLabel(p.strategy)}
                          </span>
                        </td>

                        {/* İşlem Tipi: BUY / SELL */}
                        <td className="py-3.5 px-3">
                          <span
                            className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-md text-[11px] font-bold ${
                              isBuy
                                ? "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 border border-emerald-500/30"
                                : "bg-rose-500/15 text-rose-600 dark:text-rose-400 border border-rose-500/30"
                            }`}
                          >
                            {isBuy ? "▲ BUY" : "▼ SELL"}
                          </span>
                        </td>

                        <td className="py-3.5 px-3 font-bold text-sm">
                          {p.lots.toFixed(2)} <span className="text-[11px] font-normal">Lot</span>
                        </td>

                        <td className="py-3.5 px-3 font-semibold">
                          {formatPrice(p.entry_price, p.symbol)}
                        </td>

                        <td className="py-3.5 px-3 font-bold">
                          {formatPrice(p.current_price, p.symbol)}
                        </td>

                        <td className="py-3.5 px-4 whitespace-nowrap">
                          <div
                            className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-lg border text-sm font-black ${
                              isProfitable ? theme.profitBg : theme.lossBg
                            }`}
                          >
                            <span>{isProfitable ? "+" : ""}${Number(p.pnl_usd).toFixed(2)}</span>
                            <span className="text-xs font-semibold opacity-85">
                              ({p.pnl_pips >= 0 ? "+" : ""}{Number(p.pnl_pips).toFixed(1)}p)
                            </span>
                          </div>
                        </td>

                        <td className="py-3.5 px-4 text-right whitespace-nowrap text-[11px]">
                          <div>TP: <strong className="text-emerald-600 dark:text-emerald-400">{formatPrice(p.tp_price, p.symbol)}</strong></div>
                          <div>SL: <strong className="text-rose-600 dark:text-rose-400">{formatPrice(p.sl_price, p.symbol)}</strong></div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            {/* Mobil Kart Görünümü */}
            <div className="md:hidden space-y-3 p-3">
              {sortedOpenPositions.map((p) => {
                const isBuy = p.direction === "BUY";
                const isProfitable = Number(p.pnl_usd ?? 0) >= 0;
                return (
                  <div
                    key={p.id || p.ticket}
                    className={`p-3.5 rounded-xl border space-y-2.5 shadow-sm ${
                      isLightMode ? "bg-slate-50 border-slate-200" : "bg-bunker-950/80 border-bunker-800"
                    }`}
                  >
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <span className="font-bold text-base">
                          {p.display || p.symbol}
                        </span>
                        <span
                          className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                            isBuy
                              ? "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 border border-emerald-500/30"
                              : "bg-rose-500/15 text-rose-600 dark:text-rose-400 border border-rose-500/30"
                          }`}
                        >
                          {isBuy ? "▲ BUY" : "▼ SELL"}
                        </span>
                      </div>
                      <span className="font-bold text-sm">
                        {p.lots.toFixed(2)} Lot
                      </span>
                    </div>

                    <div className="flex items-center justify-between text-xs pt-1 border-t border-slate-200 dark:border-bunker-800/80">
                      <div>
                        <span className={`text-[10px] block ${theme.textSecondary}`}>GİRİŞ</span>
                        <span className="font-semibold">{formatPrice(p.entry_price, p.symbol)}</span>
                      </div>
                      <div className="text-right">
                        <span className={`text-[10px] block ${theme.textSecondary}`}>GÜNCEL</span>
                        <span className="font-bold">{formatPrice(p.current_price, p.symbol)}</span>
                      </div>
                    </div>

                    <div className="flex items-center justify-between pt-2 border-t border-slate-200 dark:border-bunker-800/80">
                      <div
                        className={`px-3 py-1 rounded-lg border text-sm font-black ${
                          isProfitable ? theme.profitBg : theme.lossBg
                        }`}
                      >
                        {isProfitable ? "+" : ""}${Number(p.pnl_usd).toFixed(2)} ({p.pnl_pips >= 0 ? "+" : ""}{Number(p.pnl_pips).toFixed(1)}p)
                      </div>
                      <div className="text-right text-[11px] leading-tight">
                        <span className="text-emerald-600 dark:text-emerald-400 font-bold block">TP {formatPrice(p.tp_price, p.symbol)}</span>
                        <span className="text-rose-600 dark:text-rose-400 font-bold block">SL {formatPrice(p.sl_price, p.symbol)}</span>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </>
        )}
      </div>

      {/* 4. GÜNÜN İŞLEM AÇILAN SEMBOLLERİ (YAN YANA 3 KART DÜZENİ) */}
      <div className={`p-4 rounded-2xl border space-y-3 ${theme.cardBg}`}>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <span className="text-lg">🏆</span>
            <div>
              <h2 className={`text-sm font-bold uppercase tracking-wide ${theme.textPrimary}`}>
                Günün İşlem Gören Sembolleri &amp; Başarı Oranları
              </h2>
              <p className={`text-[11px] ${theme.textSecondary}`}>
                Bugün saat 00:01'den sonra en çok işlem gören sembolden azalan sıraya göre başarı ve kârlılık oranları (İşlem açılmamış semboller gizlenir)
              </p>
            </div>
          </div>
          <span className={`px-2 py-0.5 rounded text-xs font-bold ${theme.badgeBg}`}>
            {symbolPerformanceList.length} İşlem Gören Sembol
          </span>
        </div>

        {symbolPerformanceList.length === 0 ? (
          <div className="p-8 text-center text-xs rounded-xl border border-dashed border-slate-200 dark:border-bunker-800">
            <p className="font-bold text-slate-700 dark:text-slate-300 text-sm">
              Bugün 00:01'den sonra henüz işlem açılmış sembol bulunmamaktadır.
            </p>
            <p className={`mt-1 ${theme.textSecondary}`}>
              Yeni bir pozisyon açıldığında veya işlem tamamlandığında o sembole ait performans kartı otomatik olarak burada görünecektir.
            </p>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3.5">
            {symbolPerformanceList.map((item, idx) => {
              const isNetProfitable = item.netPnlUsd >= 0;
              const winRateColor =
                item.winRate >= 60
                  ? "text-emerald-600 dark:text-emerald-400"
                  : item.winRate >= 45
                  ? "text-amber-500"
                  : "text-rose-600 dark:text-rose-400";

              return (
                <div
                  key={item.symbol}
                  className={`p-3.5 rounded-xl border flex flex-col justify-between transition-all hover:shadow-md ${
                    isLightMode ? "bg-slate-50 border-slate-200 hover:border-blue-300" : "bg-bunker-950/70 border-bunker-800 hover:border-blue-500/40"
                  }`}
                >
                  {/* Başlık ve Kategori */}
                  <div className="flex items-center justify-between pb-2 border-b border-slate-200 dark:border-bunker-800/80">
                    <div className="flex items-center gap-2">
                      <span className="w-5 h-5 rounded-md bg-blue-500/10 text-blue-600 dark:text-blue-400 text-[10px] font-black flex items-center justify-center border border-blue-500/20 shrink-0">
                        #{idx + 1}
                      </span>
                      <span className="font-bold text-sm tracking-wide">
                        {item.display || item.symbol}
                      </span>
                      {item.category && (
                        <span className="text-[10px] px-1.5 py-0.2 rounded bg-slate-200/70 dark:bg-bunker-800 text-slate-600 dark:text-bunker-muted font-bold uppercase">
                          {item.category}
                        </span>
                      )}
                    </div>
                    {item.openTrades > 0 && (
                      <span className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-blue-500/15 text-blue-600 dark:text-blue-400 border border-blue-400/30">
                        {item.openTrades} Açık
                      </span>
                    )}
                  </div>

                  {/* Başarı Yüzdesi & Kârlılık */}
                  <div className="grid grid-cols-2 gap-2 py-2.5">
                    <div>
                      <span className={`text-[10px] block font-bold ${theme.textSecondary}`}>
                        BAŞARI ORANI
                      </span>
                      <div className="flex items-baseline gap-1 mt-0.5">
                        <span className={`text-xl font-black ${winRateColor}`}>
                          %{item.winRate.toFixed(1)}
                        </span>
                      </div>
                      <span className={`text-[10px] block mt-0.5 ${theme.textSecondary}`}>
                        {item.wins}K / {item.losses}Z ({item.totalTrades} İşlem)
                      </span>
                    </div>

                    <div className="text-right">
                      <span className={`text-[10px] block font-bold ${theme.textSecondary}`}>
                        NET KÂRLILIK
                      </span>
                      <div className="flex items-baseline justify-end gap-1 mt-0.5">
                        <span
                          className={`text-xl font-black ${
                            isNetProfitable ? "text-emerald-600 dark:text-emerald-400" : "text-rose-600 dark:text-rose-400"
                          }`}
                        >
                          {isNetProfitable ? "+" : ""}${item.netPnlUsd.toFixed(2)}
                        </span>
                      </div>
                      <span className={`text-[10px] font-bold block mt-0.5 ${isNetProfitable ? "text-emerald-600 dark:text-emerald-400" : "text-rose-600 dark:text-rose-400"}`}>
                        {item.totalPips >= 0 ? "+" : ""}{item.totalPips.toFixed(1)} pip
                      </span>
                    </div>
                  </div>

                  {/* İlerleme Çubuğu */}
                  <div className="w-full bg-slate-200 dark:bg-bunker-800 h-1.5 rounded-full overflow-hidden mt-1">
                    <div
                      className={`h-full rounded-full transition-all duration-300 ${
                        item.winRate >= 50 ? "bg-emerald-500" : "bg-rose-500"
                      }`}
                      style={{ width: `${Math.min(100, Math.max(0, item.winRate))}%` }}
                    />
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
        </>
      )}

      {/* 5. KAPANAN FOREX İŞLEMLERİ TABLOSU (DATA TABLE & PAGINATION 20'ŞERLİ) */}
      {activeTab === "CLOSED" && (
      <div className={`rounded-2xl border overflow-hidden ${theme.cardBg}`}>
        <div className="p-3.5 sm:p-4 border-b flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <span className="text-lg">📋</span>
            <h2 className={`text-sm font-bold uppercase tracking-wide ${theme.textPrimary}`}>
              Kapanan Forex İşlemleri (00:01 Sonrası - {filteredClosedTrades.length} İşlem)
            </h2>
          </div>

          {/* Filtreleme & Sayfa Boyutu Butonları */}
          <div className="flex flex-wrap items-center gap-2 text-xs">
            {/* Sayfa Başı Kayıt Seçici */}
            <div className={`flex items-center gap-1.5 px-2.5 py-1 rounded-lg border text-xs font-semibold ${theme.badgeBg}`}>
              <span className={theme.textSecondary}>Sayfa Başı:</span>
              <select
                value={pageSize}
                onChange={(e) => {
                  setPageSize(Number(e.target.value));
                  setCurrentPage(1);
                }}
                className={`bg-transparent font-bold outline-none cursor-pointer ${theme.textPrimary}`}
              >
                <option value={10} className="bg-slate-900 text-white">10</option>
                <option value={20} className="bg-slate-900 text-white">20</option>
                <option value={50} className="bg-slate-900 text-white">50</option>
              </select>
            </div>

            <div className="flex items-center gap-1.5">
              <button
                type="button"
                onClick={() => handleFilterChange("ALL")}
                className={`px-2.5 py-1 rounded-lg font-bold border transition-all ${
                  filterOutcome === "ALL"
                    ? "bg-blue-600 text-white border-blue-600"
                    : `${theme.badgeBg} hover:opacity-80`
                }`}
              >
                Tümü ({closedTrades.length})
              </button>
              <button
                type="button"
                onClick={() => handleFilterChange("WIN")}
                className={`px-2.5 py-1 rounded-lg font-bold border transition-all ${
                  filterOutcome === "WIN"
                    ? "bg-emerald-600 text-white border-emerald-600"
                    : `${theme.badgeBg} hover:opacity-80`
                }`}
              >
                Kârlılar ({kpi.wins})
              </button>
              <button
                type="button"
                onClick={() => handleFilterChange("LOSS")}
                className={`px-2.5 py-1 rounded-lg font-bold border transition-all ${
                  filterOutcome === "LOSS"
                    ? "bg-rose-600 text-white border-rose-600"
                    : `${theme.badgeBg} hover:opacity-80`
                }`}
              >
                Zararlılar ({kpi.losses})
              </button>
            </div>
          </div>
        </div>

        {closedTrades.length === 0 ? (
          <div className="p-10 text-center space-y-1">
            <p className={`text-sm font-bold ${theme.textPrimary}`}>
              Bugün saat 00:01'den sonra henüz kapanan forex işlemi bulunmuyor.
            </p>
            <p className={`text-xs ${theme.textSecondary}`}>
              Açık pozisyonlar kâr/stop seviyelerine ulaştığında burada listelenecektir.
            </p>
          </div>
        ) : filteredClosedTrades.length === 0 ? (
          <div className="p-8 text-center text-xs">
            <p className={theme.textSecondary}>Bu filtreye uygun kapanan işlem bulunamadı.</p>
          </div>
        ) : (
          <>
            {/* Masaüstü Tablo Görünümü */}
            <div className="hidden md:block overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead className={`uppercase border-b ${theme.tableHeader}`}>
                  <tr>
                    <th className="py-3 px-4">Sembol / Parite</th>
                    <th className="py-3 px-3">Strateji</th>
                    <th className="py-3 px-3">Yön</th>
                    <th className="py-3 px-3">Lot</th>
                    <th className="py-3 px-3">Kapanış Saati (UTC+3)</th>
                    <th className="py-3 px-4">Net Kâr / Zarar</th>
                    <th className="py-3 px-3">Net Pip</th>
                    <th className="py-3 px-4 text-right">Durum / Sebep</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 dark:divide-bunker-800/60">
                  {paginatedClosedTrades.map((t) => {
                    const isBuy = t.direction === "BUY";
                    const isProfitable = Number(t.pnl_usd ?? 0) >= 0;
                    return (
                      <tr key={t.id || t.ticket || Math.random()} className={theme.tableRow}>
                        <td className="py-3.5 px-4 font-bold text-sm">
                          {t.display || t.symbol}
                        </td>

                        <td className="py-3.5 px-3">
                          <span className={`inline-flex items-center px-2 py-0.5 rounded text-[10px] font-bold whitespace-nowrap border ${
                            t.strategy === "EMA_ADX_PULLBACK_M5"
                              ? "bg-amber-500/15 text-amber-600 dark:text-amber-300 border-amber-500/30"
                              : t.strategy === "DONCHIAN_ADX"
                              ? "bg-violet-500/15 text-violet-600 dark:text-violet-300 border-violet-500/30"
                              : t.strategy === "M1_M5_RADAR_SCALPER"
                              ? "bg-sky-500/15 text-sky-600 dark:text-sky-300 border-sky-500/30"
                              : "bg-slate-500/10 text-slate-500 dark:text-bunker-muted border-slate-500/20"
                          }`}>
                            {strategyLabel(t.strategy)}
                          </span>
                        </td>

                        <td className="py-3.5 px-3">
                          <span
                            className={`inline-flex items-center gap-1 px-2.5 py-0.5 rounded text-[11px] font-bold ${
                              isBuy
                                ? "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 border border-emerald-500/30"
                                : "bg-rose-500/15 text-rose-600 dark:text-rose-400 border border-rose-500/30"
                            }`}
                          >
                            {isBuy ? "▲ BUY" : "▼ SELL"}
                          </span>
                        </td>

                        <td className="py-3.5 px-3 font-semibold">
                          {t.lots.toFixed(2)} Lot
                        </td>

                        <td className={`py-3.5 px-3 font-semibold ${theme.textSecondary}`}>
                          {formatClockTime(t.close_time || t.exit_time || t.time, t.closed_at_ts)}
                        </td>

                        <td className="py-3.5 px-4 whitespace-nowrap">
                          <span
                            className={`inline-flex items-center px-2.5 py-1 rounded-lg border font-black text-sm ${
                              isProfitable ? theme.profitBg : theme.lossBg
                            }`}
                          >
                            {isProfitable ? "+" : ""}${Number(t.pnl_usd).toFixed(2)}
                          </span>
                        </td>

                        <td className="py-3.5 px-3 font-bold">
                          <span className={isProfitable ? "text-emerald-600 dark:text-emerald-400" : "text-rose-600 dark:text-rose-400"}>
                            {t.pnl_pips >= 0 ? "+" : ""}{Number(t.pnl_pips).toFixed(1)}p
                          </span>
                        </td>

                        <td className="py-3.5 px-4 text-right">
                          <span
                            className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase ${
                              isProfitable
                                ? "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400"
                                : "bg-rose-500/15 text-rose-600 dark:text-rose-400"
                            }`}
                          >
                            {t.exit_reason_title || t.exit_reason || (isProfitable ? "KÂR ALINDI" : "STOP LOSS")}
                          </span>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            {/* Mobil Kart Görünümü */}
            <div className="md:hidden space-y-2.5 p-3">
              {paginatedClosedTrades.map((t) => {
                const isBuy = t.direction === "BUY";
                const isProfitable = Number(t.pnl_usd ?? 0) >= 0;
                return (
                  <div
                    key={t.id || t.ticket || Math.random()}
                    className={`p-3 rounded-xl border flex items-center justify-between shadow-sm ${
                      isLightMode ? "bg-slate-50 border-slate-200" : "bg-bunker-950/80 border-bunker-800"
                    }`}
                  >
                    <div>
                      <div className="flex items-center gap-1.5">
                        <span className="font-bold text-sm">{t.display || t.symbol}</span>
                        <span
                          className={`px-1.5 py-0.2 rounded text-[10px] font-bold ${
                            isBuy ? "text-emerald-600 dark:text-emerald-400" : "text-rose-600 dark:text-rose-400"
                          }`}
                        >
                          {isBuy ? "BUY" : "SELL"}
                        </span>
                        <span className={`text-[11px] ${theme.textSecondary}`}>{t.lots.toFixed(2)}L</span>
                      </div>
                      <div className={`text-[10px] mt-0.5 ${theme.textSecondary}`}>
                        {formatClockTime(t.close_time || t.exit_time || t.time, t.closed_at_ts)} · {t.exit_reason_title || (isProfitable ? "TP" : "SL")}
                      </div>
                    </div>

                    <div className="text-right">
                      <div
                        className={`inline-block px-2.5 py-0.5 rounded-lg border text-sm font-black ${
                          isProfitable ? theme.profitBg : theme.lossBg
                        }`}
                      >
                        {isProfitable ? "+" : ""}${Number(t.pnl_usd).toFixed(2)}
                      </div>
                      <div className="text-[10px] font-bold opacity-80 mt-0.5">
                        {t.pnl_pips >= 0 ? "+" : ""}{Number(t.pnl_pips).toFixed(1)}p
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>

            {/* SAYFALAMA (PAGINATION) BARI */}
            {filteredClosedTrades.length > 0 && (
              <div className="p-3 sm:p-3.5 border-t flex flex-col sm:flex-row items-center justify-between gap-3 text-xs">
                <span className={`text-center sm:text-left ${theme.textSecondary}`}>
                  Toplam {filteredClosedTrades.length} işlemden{" "}
                  <strong>
                    {(safeCurrentPage - 1) * pageSize + 1} – {Math.min(safeCurrentPage * pageSize, filteredClosedTrades.length)}
                  </strong>{" "}
                  arası gösteriliyor (Sayfa {safeCurrentPage} / {totalPages})
                </span>

                <div className="flex items-center gap-1 sm:gap-1.5 flex-wrap justify-center">
                  <button
                    type="button"
                    onClick={() => setCurrentPage(1)}
                    disabled={safeCurrentPage <= 1}
                    className={`px-2.5 py-1 rounded-lg border font-bold transition-all disabled:opacity-40 disabled:pointer-events-none ${theme.pageInactive}`}
                  >
                    « İlk
                  </button>
                  <button
                    type="button"
                    onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
                    disabled={safeCurrentPage <= 1}
                    className={`px-2.5 py-1 rounded-lg border font-bold transition-all disabled:opacity-40 disabled:pointer-events-none ${theme.pageInactive}`}
                  >
                    ‹ Önceki
                  </button>

                  {/* Sayfa Butonları */}
                  {Array.from({ length: totalPages }, (_, i) => i + 1)
                    .filter((p) => p === 1 || p === totalPages || Math.abs(p - safeCurrentPage) <= 1)
                    .map((p, idx, arr) => (
                      <React.Fragment key={p}>
                        {idx > 0 && arr[idx - 1] !== p - 1 && (
                          <span className={`px-1 ${theme.textSecondary}`}>…</span>
                        )}
                        <button
                          type="button"
                          onClick={() => setCurrentPage(p)}
                          className={`w-7 h-7 rounded-lg border font-bold transition-all ${
                            safeCurrentPage === p ? theme.pageActive : theme.pageInactive
                          }`}
                        >
                          {p}
                        </button>
                      </React.Fragment>
                    ))}

                  <button
                    type="button"
                    onClick={() => setCurrentPage((p) => Math.min(totalPages, p + 1))}
                    disabled={safeCurrentPage >= totalPages}
                    className={`px-2.5 py-1 rounded-lg border font-bold transition-all disabled:opacity-40 disabled:pointer-events-none ${theme.pageInactive}`}
                  >
                    Sonraki ›
                  </button>
                  <button
                    type="button"
                    onClick={() => setCurrentPage(totalPages)}
                    disabled={safeCurrentPage >= totalPages}
                    className={`px-2.5 py-1 rounded-lg border font-bold transition-all disabled:opacity-40 disabled:pointer-events-none ${theme.pageInactive}`}
                  >
                    Son »
                  </button>
                </div>
              </div>
            )}
          </>
        )}
      </div>
      )}

      {/* EV KALKANI VE MUAFİYET MODALI */}
      <EVShieldModal
        isOpen={evShieldModalOpen}
        onClose={() => setEvShieldModalOpen(false)}
        onUpdated={() => fetchData(true)}
      />
    </div>
  );
}
