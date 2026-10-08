"use client";

// ============================================================================
// GÜNLÜK FOREX İŞLEM VE PERFORMANS KONSOLU (ANA SAYFA)
// 2026-10-07: Uygulama giriş ekranı. Günün otonom Forex scalper işlemlerinin
// başarısını, net kârlılığını (USD ve Pip), kazanma oranını (Win Rate),
// açık pozisyonlarını, sembol bazlı dağılımını ve INVESTING.COM EKONOMİK TAKVİM
// AÇIKLAMALARI VE "NE OLURSA NE OLUR" SENARYO ANALİZİNİ canlı olarak sunar.
// ============================================================================

import React, { useState, useEffect, useMemo, useCallback } from "react";
import Link from "next/link";
import { apiFetch } from "./lib/api";
import { triggerTestCalendarNotification } from "./lib/notificationSettings";

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
  duration_human?: string;
}

interface KPIStats {
  total_trades: number;
  wins: number;
  losses: number;
  win_rate: number;
  total_pnl_usd: number;
  total_pnl_pips?: number;
  profit_factor?: number;
  profit_factor_infinite?: boolean;
  gross_profit_usd?: number;
  gross_loss_usd?: number;
  balance: number;
  equity: number;
  open_positions_count: number;
  open_pnl_usd: number;
  avg_win_usd?: number;
  avg_loss_usd?: number;
}

interface EconomicEvent {
  id: string;
  title: string;
  original_title?: string;
  country: string;
  currency?: string;
  country_name?: string;
  flag?: string;
  date_str: string;
  date_iso?: string;
  impact: string;
  stars?: number;
  stars_str?: string;
  impact_label: string;
  forecast: string;
  previous: string;
  actual?: string;
  status?: string;
  comment?: string;
  is_passed?: boolean;
  affected_symbols: string[];
  scenario: {
    title: string;
    bullish_trigger: string;
    bullish_outcome: string;
    bearish_trigger: string;
    bearish_outcome: string;
    scalper_tip: string;
    summary_short?: string;
  };
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

function formatClockTime(timeStr?: string): string {
  if (!timeStr) return "—";
  try {
    const d = new Date(timeStr);
    if (!isNaN(d.getTime())) {
      return d.toLocaleTimeString("tr-TR", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
    }
    if (timeStr.includes(" ")) {
      return timeStr.split(" ")[1] || timeStr;
    }
    return timeStr;
  } catch {
    return timeStr;
  }
}

interface EventCountdownBadgeProps {
  dateIso?: string;
  dateStr?: string;
  status?: string;
  isPassed?: boolean;
  className?: string;
}

const EventCountdownBadge = React.memo(function EventCountdownBadge({
  dateIso,
  dateStr,
  status,
  isPassed,
  className = "",
}: EventCountdownBadgeProps) {
  const [now, setNow] = useState<number>(() => Date.now());

  const targetMs = useMemo(() => {
    if (dateIso) {
      const parsed = new Date(dateIso).getTime();
      if (!isNaN(parsed) && parsed > 0) return parsed;
    }
    if (dateStr) {
      const timeMatch = dateStr.match(/(\d{1,2}):(\d{2})/);
      if (timeMatch) {
        const h = parseInt(timeMatch[1], 10);
        const m = parseInt(timeMatch[2], 10);
        const d = new Date();
        d.setHours(h, m, 0, 0);
        if (dateStr.toLowerCase().includes("yarın")) {
          d.setDate(d.getDate() + 1);
        }
        return d.getTime();
      }
    }
    return null;
  }, [dateIso, dateStr]);

  useEffect(() => {
    if (!targetMs) return;
    const interval = setInterval(() => {
      setNow(Date.now());
    }, 1000);
    return () => clearInterval(interval);
  }, [targetMs]);

  if (!targetMs) return null;

  const diffSec = Math.floor((targetMs - now) / 1000);

  // Açıklanmış veya geçmiş olaylar
  if (status === "Açıklandı" || isPassed || diffSec <= 0) {
    return (
      <span
        className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[9px] font-bold font-mono bg-emerald-500/15 text-emerald-300 border border-emerald-500/30 ${className}`}
        title="Olay açıklandı veya saati geçti"
      >
        <span>✓</span>
        <span>Açıklandı</span>
      </span>
    );
  }

  // 1. Durum: 24 saatten fazla (> 86400 sn)
  // "1 gün 4 saat 37 dk kaldı" gibi
  if (diffSec > 86400) {
    const days = Math.floor(diffSec / 86400);
    const rem = diffSec % 86400;
    const hours = Math.floor(rem / 3600);
    const minutes = Math.floor((rem % 3600) / 60);

    return (
      <span
        className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[9px] font-bold font-mono bg-cyan-950/80 text-cyan-300 border border-cyan-500/40 shadow-sm ${className}`}
        title={`${days} gün ${hours} saat ${minutes} dakika kaldı`}
      >
        <span>⏳</span>
        <span>
          {days} gün {hours} saat {minutes} dk kaldı
        </span>
      </span>
    );
  }

  // 2. Durum: 24 saatten az ama 1 saat veya daha fazla (3600 <= diffSec <= 86400)
  // "SS:DD" formatında
  if (diffSec >= 3600) {
    const hours = Math.floor(diffSec / 3600);
    const minutes = Math.floor((diffSec % 3600) / 60);
    const formatted = `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}`;

    return (
      <span
        className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[9px] font-bold font-mono bg-amber-500/20 text-amber-300 border border-amber-400/50 shadow-sm ${className}`}
        title={`${hours} saat ${minutes} dakika kaldı`}
      >
        <span>⏱️</span>
        <span className="tabular-nums tracking-wide">{formatted} kaldı</span>
      </span>
    );
  }

  // 3. Durum: 1 saatten az (< 3600 sn)
  // "DD:SANİYE" formatında DİNAMİK (saniyelik canlı geri sayım)
  const minutes = Math.floor(diffSec / 60);
  const seconds = diffSec % 60;
  const formatted = `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;

  return (
    <span
      className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-[9px] font-black font-mono bg-rose-500/25 text-rose-200 border border-rose-500/70 shadow-[0_0_12px_rgba(244,63,94,0.35)] animate-pulse ${className}`}
      title="KRİTİK: Açıklanmaya 1 saatten az süre kaldı!"
    >
      <span className="w-1.5 h-1.5 rounded-full bg-rose-400 animate-ping shrink-0" />
      <span className="tabular-nums tracking-wider font-extrabold">{formatted} kaldı</span>
    </span>
  );
});

export default function HomePage() {
  const [loading, setLoading] = useState<boolean>(true);
  const [refreshing, setRefreshing] = useState<boolean>(false);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  // Canlı Veriler
  const [openPositions, setOpenPositions] = useState<OpenPosition[]>([]);
  const [closedTrades, setClosedTrades] = useState<ClosedTrade[]>([]);
  const [kpi, setKpi] = useState<KPIStats>({
    total_trades: 0,
    wins: 0,
    losses: 0,
    win_rate: 0,
    total_pnl_usd: 0,
    total_pnl_pips: 0,
    profit_factor: 0,
    balance: 10000,
    equity: 10000,
    open_positions_count: 0,
    open_pnl_usd: 0,
  });

  const [filterOutcome, setFilterOutcome] = useState<"ALL" | "WIN" | "LOSS">("ALL");
  const [tradesPage, setTradesPage] = useState<number>(1);
  const [tradesPageSize, setTradesPageSize] = useState<number>(10);

  // Ekonomik Takvim ve Senaryo Analiz Durumu
  const [calendarEvents, setCalendarEvents] = useState<EconomicEvent[]>([]);
  const [selectedEvent, setSelectedEvent] = useState<EconomicEvent | null>(null);
  const [loadingCalendar, setLoadingCalendar] = useState<boolean>(true);
  const [refreshingCalendar, setRefreshingCalendar] = useState<boolean>(false);
  const [calendarFilterStars, setCalendarFilterStars] = useState<number | "ALL">("ALL");
  const [calendarFilterCurrency, setCalendarFilterCurrency] = useState<string>("ALL");
  const [calendarSearch, setCalendarSearch] = useState<string>("");
  const [calendarLastUpdated, setCalendarLastUpdated] = useState<Date | null>(null);

  // Ekonomik Takvim Verisini Çekme (Investing.com 2 & 3 Yıldızlı Olaylar)
  const fetchCalendar = useCallback(async (forceRefresh = false) => {
    setRefreshingCalendar(true);
    try {
      const url = forceRefresh ? "/api/forex/news?refresh=true" : "/api/forex/news";
      const newsRes = await apiFetch(url).catch(() => null);
      if (newsRes?.news && Array.isArray(newsRes.news)) {
        setCalendarEvents(newsRes.news);
        setCalendarLastUpdated(new Date());
      }
    } catch (err) {
      console.error("Ekonomik takvim yükleme hatası:", err);
    } finally {
      setLoadingCalendar(false);
      setRefreshingCalendar(false);
    }
  }, []);

  // İşlem ve Hesap Verisi Çekme (4 Saniyede Bir Otonom Akış)
  const fetchData = useCallback(async (isSilent = false) => {
    if (!isSilent) setRefreshing(true);
    try {
      const [reportRes, statusRes] = await Promise.all([
        apiFetch("/api/forex/auto-paper/trades?period=today&limit=250"),
        apiFetch("/api/forex/auto-paper/status").catch(() => null),
      ]);

      if (reportRes) {
        if (Array.isArray(reportRes.open_positions)) {
          setOpenPositions(reportRes.open_positions);
        }
        if (Array.isArray(reportRes.trades)) {
          setClosedTrades(reportRes.trades);
        }
        const k = reportRes.kpi || statusRes?.today_kpi;
        if (k) {
          setKpi((prev) => ({
            ...prev,
            total_trades: k.total_trades ?? 0,
            wins: k.won_trades ?? k.wins ?? 0,
            losses: k.lost_trades ?? k.losses ?? 0,
            win_rate: k.win_rate_pct ?? k.win_rate ?? 0,
            total_pnl_usd: statusRes?.daily_pnl ?? k.total_pnl_usd ?? 0,
            total_pnl_pips: statusRes?.daily_pips ?? k.total_pnl_pips ?? 0,
            profit_factor: k.profit_factor ?? 0,
            profit_factor_infinite: !!k.profit_factor_infinite,
            balance: statusRes?.balance ?? k.balance ?? prev.balance,
            equity: statusRes?.equity ?? k.equity ?? prev.equity,
          }));
        }
      } else if (statusRes) {
        const k = statusRes.today_kpi;
        setKpi((prev) => ({
          ...prev,
          total_trades: k?.total_trades ?? 0,
          wins: k?.won_trades ?? 0,
          losses: k?.lost_trades ?? 0,
          win_rate: k?.win_rate_pct ?? 0,
          total_pnl_usd: statusRes.daily_pnl ?? 0,
          total_pnl_pips: statusRes.daily_pips ?? 0,
          profit_factor: k?.profit_factor ?? 0,
          profit_factor_infinite: !!k?.profit_factor_infinite,
          balance: statusRes.balance ?? prev.balance,
          equity: statusRes.equity ?? prev.equity,
        }));
      }

      setLastUpdated(new Date());
    } catch (err) {
      console.error("Ana sayfa Forex verisi yükleme hatası:", err);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  // İlk Yükleme ve Ayrı Periyodik Döngüler
  useEffect(() => {
    fetchData(false);
    fetchCalendar(false);

    // İşlemler her 4 saniyede bir güncellenir
    const tradeInterval = setInterval(() => {
      if (!document.hidden) {
        fetchData(true);
      }
    }, 4000);

    // Ekonomik takvim her 90 saniyede bir güncellenir (Rate limit korumalı)
    const calendarInterval = setInterval(() => {
      if (!document.hidden) {
        fetchCalendar(false);
      }
    }, 90000);

    return () => {
      clearInterval(tradeInterval);
      clearInterval(calendarInterval);
    };
  }, [fetchData, fetchCalendar]);

  // Filtrelenmiş Ekonomik Takvim Olayları
  const filteredCalendarEvents = useMemo(() => {
    return calendarEvents.filter((item) => {
      // Yıldız Filtresi
      if (calendarFilterStars !== "ALL") {
        const itemStars = item.stars || (item.impact === "High" ? 3 : 2);
        if (itemStars !== calendarFilterStars) return false;
      }

      // Para Birimi / Varlık Filtresi
      if (calendarFilterCurrency !== "ALL") {
        const c = (item.currency || item.country || "").toUpperCase();
        if (calendarFilterCurrency === "XAU") {
          if (!item.affected_symbols.includes("XAUUSD")) return false;
        } else if (calendarFilterCurrency === "OIL") {
          if (!item.affected_symbols.includes("USOIL") && !c.includes("CAD")) return false;
        } else {
          if (
            c !== calendarFilterCurrency &&
            !item.affected_symbols.some((s) => s.startsWith(calendarFilterCurrency) || s.endsWith(calendarFilterCurrency))
          ) {
            return false;
          }
        }
      }

      // Arama Filtresi
      if (calendarSearch.trim()) {
        const q = calendarSearch.toLowerCase().trim();
        const inTitle = (item.title || "").toLowerCase().includes(q);
        const inOrig = (item.original_title || "").toLowerCase().includes(q);
        const inCountry = (item.country || "").toLowerCase().includes(q);
        const inSymbols = item.affected_symbols.some((s) => s.toLowerCase().includes(q));
        if (!inTitle && !inOrig && !inCountry && !inSymbols) return false;
      }

      return true;
    });
  }, [calendarEvents, calendarFilterStars, calendarFilterCurrency, calendarSearch]);

  // Hesaplanan Canlı Toplamlar
  const openPnlTotal = useMemo(() => {
    return openPositions.reduce((acc, p) => acc + (Number(p.pnl_usd) || 0), 0);
  }, [openPositions]);

  const openPipsTotal = useMemo(() => {
    return openPositions.reduce((acc, p) => acc + (Number(p.pnl_pips) || 0), 0);
  }, [openPositions]);

  // Açık Pozisyonlar: Aynı semboller bir arada gelecek şekilde sıralı
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

  // Sembol Bazında Günlük Performans Analizi
  const symbolStats = useMemo(() => {
    const map = new Map<string, { symbol: string; trades: number; wins: number; losses: number; pnl_usd: number; pnl_pips: number }>();

    for (const t of closedTrades) {
      const sym = (t.symbol || t.display || "DİĞER").toUpperCase();
      const existing = map.get(sym) || { symbol: sym, trades: 0, wins: 0, losses: 0, pnl_usd: 0, pnl_pips: 0 };
      existing.trades += 1;
      const pnl = Number(t.pnl_usd) || 0;
      existing.pnl_usd += pnl;
      existing.pnl_pips += Number(t.pnl_pips) || 0;
      if (pnl > 0 || t.outcome === "WIN") existing.wins += 1;
      else if (pnl < 0 || t.outcome === "LOSS") existing.losses += 1;
      map.set(sym, existing);
    }

    return Array.from(map.values()).sort((a, b) => b.pnl_usd - a.pnl_usd);
  }, [closedTrades]);

  // Günün En İyi ve En Kötü İşlemleri
  const { bestTrade, worstTrade } = useMemo(() => {
    if (!closedTrades.length) return { bestTrade: null, worstTrade: null };
    let best = closedTrades[0];
    let worst = closedTrades[0];
    for (const t of closedTrades) {
      if ((t.pnl_usd ?? 0) > (best.pnl_usd ?? 0)) best = t;
      if ((t.pnl_usd ?? 0) < (worst.pnl_usd ?? 0)) worst = t;
    }
    return { bestTrade: best, worstTrade: worst };
  }, [closedTrades]);

  // Filtrelenmiş Kapanan İşlemler
  const filteredClosedTrades = useMemo(() => {
    if (filterOutcome === "ALL") return closedTrades;
    return closedTrades.filter((t) => {
      const isWin = (t.pnl_usd ?? 0) > 0 || t.outcome === "WIN";
      return filterOutcome === "WIN" ? isWin : !isWin;
    });
  }, [closedTrades, filterOutcome]);

  const totalTradesPages = Math.max(1, Math.ceil(filteredClosedTrades.length / tradesPageSize));
  const safeTradesPage = Math.min(Math.max(1, tradesPage), totalTradesPages);
  const paginatedClosedTrades = useMemo(() => {
    const startIndex = (safeTradesPage - 1) * tradesPageSize;
    return filteredClosedTrades.slice(startIndex, startIndex + tradesPageSize);
  }, [filteredClosedTrades, safeTradesPage, tradesPageSize]);

  useEffect(() => {
    setTradesPage(1);
  }, [filterOutcome, tradesPageSize]);

  const winRate = kpi.total_trades > 0 ? (kpi.wins / kpi.total_trades) * 100 : 0;
  const isNetProfit = kpi.total_pnl_usd >= 0;

  return (
    <div className="space-y-6 pb-16 font-mono text-white">
      {/* 1. ÜST BAŞLIK VE CANLI DURUM ÇUBUĞU */}
      <header className="p-5 sm:p-6 rounded-2xl bg-gradient-to-r from-blue-950/60 via-bunker-900/90 to-cyan-950/40 border border-blue-500/40 backdrop-blur-md shadow-2xl flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div className="flex items-center gap-3.5">
          <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-blue-500/30 to-cyan-500/20 border border-cyan-400/40 flex items-center justify-center text-3xl shadow-[0_0_20px_rgba(0,240,255,0.35)] shrink-0">
            📊
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-xl sm:text-2xl font-black text-white tracking-tight">
                GÜNLÜK FOREX PERFORMANSI
              </h1>
              <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-cyan-400/20 text-cyan-300 border border-cyan-400/30">
                BUGÜN
              </span>
            </div>
            <p className="text-xs text-bunker-muted mt-1">
              Otonom scalper işlemlerinin anlık başarı oranı, net kârlılık karnesi ve ekonomik takvim analizleri
            </p>
          </div>
        </div>

        <div className="flex items-center gap-3 self-end md:self-auto">
          <div className="flex flex-col text-right">
            <span className="text-[10px] text-bunker-muted">Son Güncelleme</span>
            <span className="text-xs font-bold text-cyan-400">
              {lastUpdated ? lastUpdated.toLocaleTimeString("tr-TR") : "Yükleniyor…"}
            </span>
          </div>

          <button
            type="button"
            onClick={() => fetchData(false)}
            disabled={refreshing}
            className="px-3 py-2 rounded-xl bg-bunker-950/80 border border-cyan-500/30 hover:border-cyan-400 text-cyan-300 text-xs font-bold transition-all shadow-[0_0_10px_rgba(0,240,255,0.15)] active:scale-95 flex items-center gap-1.5 disabled:opacity-50"
          >
            <span className={refreshing ? "animate-spin" : ""}>🔄</span>
            <span>Yenile</span>
          </button>
        </div>
      </header>

      {/* 2. GÜNÜN KARNESİ: ANA METRİKLER (KPI CARDS) */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 px-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="w-2.5 h-2.5 rounded-full bg-emerald-400 animate-pulse" />
          <h2 className="text-sm font-bold uppercase tracking-wider text-white">Günün Başarı Metrikleri</h2>
          <span className="text-[10px] px-2 py-0.5 rounded-full bg-cyan-950/80 border border-cyan-500/30 text-cyan-300 font-semibold">
            Her Gece 00:00'da Otomatik Sıfırlanır (UTC+3)
          </span>
        </div>
        <Link
          href="/forex/reports"
          className="text-xs text-cyan-400 hover:text-cyan-300 hover:underline flex items-center gap-1 font-semibold transition-colors"
        >
          <span>📅 Geçmiş Tarihli Kayıtları İncele</span>
          <span>→</span>
        </Link>
      </div>

      <section className="grid grid-cols-2 lg:grid-cols-4 gap-3 sm:gap-4" aria-label="Günün KPI Göstergeleri">
        {/* KART 1: GÜNLÜK NET PNL */}
        <div className={`p-4 sm:p-5 rounded-2xl border backdrop-blur-md shadow-xl transition-all ${
          isNetProfit
            ? "border-emerald-500/40 bg-gradient-to-br from-emerald-950/40 via-bunker-900/80 to-bunker-950/90 shadow-[0_4px_20px_rgba(16,185,129,0.15)]"
            : "border-rose-500/40 bg-gradient-to-br from-rose-950/40 via-bunker-900/80 to-bunker-950/90 shadow-[0_4px_20px_rgba(244,63,94,0.15)]"
        }`}>
          <div className="flex items-center justify-between">
            <span className="text-xs font-bold uppercase tracking-wider text-bunker-muted">Günün Net Kârı</span>
            <span className="text-lg">{isNetProfit ? "💰" : "📉"}</span>
          </div>
          <div className="mt-2.5">
            <div className={`text-2xl sm:text-3xl font-black tracking-tight ${isNetProfit ? "text-emerald-400" : "text-rose-400"}`}>
              {kpi.total_pnl_usd >= 0 ? `+$${kpi.total_pnl_usd.toFixed(2)}` : `-$${Math.abs(kpi.total_pnl_usd).toFixed(2)}`}
            </div>
            <div className="mt-1 flex items-center justify-between text-[11px] text-bunker-muted">
              <span>Toplam Pip:</span>
              <span className={`font-bold ${((kpi.total_pnl_pips ?? 0) >= 0) ? "text-emerald-300" : "text-rose-300"}`}>
                {(kpi.total_pnl_pips ?? 0) >= 0 ? `+${(kpi.total_pnl_pips ?? 0).toFixed(1)}` : (kpi.total_pnl_pips ?? 0).toFixed(1)} pip
              </span>
            </div>
          </div>
        </div>

        {/* KART 2: BAŞARI ORANI (WIN RATE) */}
        <div className="p-4 sm:p-5 rounded-2xl border border-cyan-500/40 bg-gradient-to-br from-cyan-950/30 via-bunker-900/80 to-bunker-950/90 shadow-xl shadow-[0_4px_20px_rgba(6,182,212,0.1)]">
          <div className="flex items-center justify-between">
            <span className="text-xs font-bold uppercase tracking-wider text-cyan-300">Başarı Oranı (Win Rate)</span>
            <span className="text-lg">🎯</span>
          </div>
          <div className="mt-2.5">
            <div className="text-2xl sm:text-3xl font-black text-white tracking-tight flex items-baseline gap-1.5">
              <span>%{winRate.toFixed(1)}</span>
            </div>
            <div className="mt-1 flex items-center justify-between text-[11px] text-bunker-muted">
              <span className="text-emerald-400 font-bold">{kpi.wins} Kazanılan</span>
              <span className="text-bunker-500">/</span>
              <span className="text-rose-400 font-bold">{kpi.losses} Kayıp</span>
            </div>
          </div>
        </div>

        {/* KART 3: KÂR FAKTÖRÜ (PROFIT FACTOR) */}
        <div className="p-4 sm:p-5 rounded-2xl border border-purple-500/40 bg-gradient-to-br from-purple-950/30 via-bunker-900/80 to-bunker-950/90 shadow-xl">
          <div className="flex items-center justify-between">
            <span className="text-xs font-bold uppercase tracking-wider text-purple-300">Kâr Faktörü (PF)</span>
            <span className="text-lg">⚡</span>
          </div>
          <div className="mt-2.5">
            <div className="text-2xl sm:text-3xl font-black text-purple-200 tracking-tight">
              {kpi.profit_factor_infinite ? "∞ (Kayıpsız)" : (kpi.profit_factor && kpi.profit_factor > 0 ? kpi.profit_factor.toFixed(2) : "—")}
            </div>
            <div className="mt-1 flex items-center justify-between text-[11px] text-bunker-muted">
              <span>Toplam İşlem:</span>
              <span className="text-white font-bold">{kpi.total_trades} adet</span>
            </div>
          </div>
        </div>

        {/* KART 4: BAKİYE VE CANLI VARLIK (EQUITY) */}
        <div className="p-4 sm:p-5 rounded-2xl border border-amber-500/40 bg-gradient-to-br from-amber-950/25 via-bunker-900/80 to-bunker-950/90 shadow-xl">
          <div className="flex items-center justify-between">
            <span className="text-xs font-bold uppercase tracking-wider text-amber-300">Varlık (Equity) &amp; Bakiye</span>
            <span className="text-lg">💼</span>
          </div>
          <div className="mt-2.5">
            <div className="text-2xl sm:text-3xl font-black text-amber-200 tracking-tight">
              ${kpi.equity ? kpi.equity.toFixed(2) : kpi.balance.toFixed(2)}
            </div>
            <div className="mt-1 flex items-center justify-between text-[11px] text-bunker-muted">
              <span>Bakiye:</span>
              <span className="text-white font-bold">${kpi.balance ? kpi.balance.toFixed(2) : "10,000.00"}</span>
            </div>
          </div>
        </div>
      </section>

      {/* 3. BAŞARI ÇUBUĞU VE GÜNÜN ÖNE ÇIKANLARI */}
      <section className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* BAŞARI ÇUBUĞU & İŞLEM DAĞILIMI */}
        <div className="lg:col-span-2 p-5 rounded-2xl bg-bunker-900/80 border border-bunker-800 shadow-xl space-y-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="text-base">📈</span>
              <h2 className="text-sm font-bold text-white uppercase tracking-wider">
                Günün İşlem Başarısı Dağılımı
              </h2>
            </div>
            <span className="text-xs text-bunker-muted">
              Toplam {kpi.total_trades} Kapanan İşlem
            </span>
          </div>

          {/* İlerleme Çubuğu */}
          <div className="space-y-1.5">
            <div className="w-full h-4 rounded-full bg-bunker-950 overflow-hidden flex border border-bunker-800">
              <div
                style={{ width: `${kpi.total_trades > 0 ? (kpi.wins / kpi.total_trades) * 100 : 0}%` }}
                className="h-full bg-gradient-to-r from-emerald-500 to-teal-400 transition-all duration-500 flex items-center justify-center text-[9px] font-black text-black"
                title={`${kpi.wins} Kazanılan İşlem`}
              >
                {kpi.wins > 0 && `${kpi.wins}`}
              </div>
              <div
                style={{ width: `${kpi.total_trades > 0 ? (kpi.losses / kpi.total_trades) * 100 : 0}%` }}
                className="h-full bg-gradient-to-r from-rose-500 to-red-600 transition-all duration-500 flex items-center justify-center text-[9px] font-black text-white"
                title={`${kpi.losses} Kayıp İşlem`}
              >
                {kpi.losses > 0 && `${kpi.losses}`}
              </div>
            </div>
            <div className="flex justify-between text-[11px]">
              <span className="text-emerald-400 font-bold">
                ✓ %{winRate.toFixed(1)} Kazanma (WIN)
              </span>
              <span className="text-rose-400 font-bold">
                ✕ %{(100 - winRate).toFixed(1)} Kayıp (LOSS)
              </span>
            </div>
          </div>

          {/* Hızlı Aksiyon Bağlantıları */}
          <div className="pt-3 border-t border-bunker-800 flex flex-wrap gap-2.5">
            <Link
              href="/forex/portfolio"
              className="px-3 py-1.5 rounded-xl bg-blue-500/10 border border-blue-500/30 text-blue-300 text-xs hover:bg-blue-500/20 transition-all font-bold flex items-center gap-1.5"
            >
              <span>💼</span> Forex Portföy
            </Link>
            <Link
              href="/forex/btc-gold"
              className="px-3 py-1.5 rounded-xl bg-amber-500/10 border border-amber-500/30 text-amber-300 text-xs hover:bg-amber-500/20 transition-all font-bold flex items-center gap-1.5"
            >
              <span>🥇</span> BTC + Altın
            </Link>
            <Link
              href="/forex"
              className="px-3 py-1.5 rounded-xl bg-cyan-500/10 border border-cyan-500/30 text-cyan-300 text-xs hover:bg-cyan-500/20 transition-all font-bold flex items-center gap-1.5"
            >
              <span>📡</span> Radar
            </Link>
            <Link
              href="/forex/reports"
              className="px-3 py-1.5 rounded-xl bg-purple-500/10 border border-purple-500/30 text-purple-300 text-xs hover:bg-purple-500/20 transition-all font-bold flex items-center gap-1.5"
            >
              <span>📋</span> Detaylı Raporlar
            </Link>
            <Link
              href="/settings"
              className="px-3 py-1.5 rounded-xl bg-bunker-800/80 border border-bunker-700 text-bunker-muted hover:text-white text-xs transition-all font-bold flex items-center gap-1.5 ml-auto"
            >
              <span>⚙️</span> Ayarlar
            </Link>
          </div>
        </div>

        {/* GÜNÜN ÖNE ÇIKAN İŞLEMLERİ */}
        <div className="p-5 rounded-2xl bg-bunker-900/80 border border-bunker-800 shadow-xl space-y-3">
          <div className="flex items-center gap-2">
            <span className="text-base">🏆</span>
            <h2 className="text-sm font-bold text-white uppercase tracking-wider">
              Günün Öne Çıkanları
            </h2>
          </div>

          <div className="space-y-2.5 text-xs">
            {/* EN İYİ İŞLEM */}
            <div className="p-2.5 rounded-xl bg-emerald-500/10 border border-emerald-500/30 space-y-1">
              <div className="flex justify-between items-center text-[10px] text-emerald-400 font-bold uppercase">
                <span>Günün En İyi İşlemi</span>
                <span>{bestTrade?.symbol || "—"}</span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-white font-bold">{bestTrade?.direction || "—"} {bestTrade?.lots ? `${bestTrade.lots} Lot` : ""}</span>
                <span className="text-emerald-400 font-black text-sm">
                  {bestTrade ? `+$${(bestTrade.pnl_usd ?? 0).toFixed(2)}` : "—"}
                </span>
              </div>
              <div className="text-[10px] text-bunker-muted flex justify-between">
                <span>{bestTrade?.pnl_pips ? `+${bestTrade.pnl_pips.toFixed(1)} pip` : ""}</span>
                <span>{formatClockTime(bestTrade?.exit_time || bestTrade?.close_time)}</span>
              </div>
            </div>

            {/* EN BÜYÜK KAYIP */}
            <div className="p-2.5 rounded-xl bg-rose-500/10 border border-rose-500/30 space-y-1">
              <div className="flex justify-between items-center text-[10px] text-rose-400 font-bold uppercase">
                <span>Günün En Büyük Kaybı</span>
                <span>{worstTrade?.symbol || "—"}</span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-white font-bold">{worstTrade?.direction || "—"} {worstTrade?.lots ? `${worstTrade.lots} Lot` : ""}</span>
                <span className="text-rose-400 font-black text-sm">
                  {worstTrade ? `-$${Math.abs(worstTrade.pnl_usd ?? 0).toFixed(2)}` : "—"}
                </span>
              </div>
              <div className="text-[10px] text-bunker-muted flex justify-between">
                <span>{worstTrade?.pnl_pips ? `${worstTrade.pnl_pips.toFixed(1)} pip` : ""}</span>
                <span>{formatClockTime(worstTrade?.exit_time || worstTrade?.close_time)}</span>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* 4. EKONOMİK TAKVİM VE MAKRO AÇIKLAMA ANALİZİ (INVESTING.COM 2 & 3 YILDIZ) */}
      <section className="p-5 sm:p-6 rounded-2xl bg-gradient-to-r from-slate-900/90 via-bunker-900/95 to-indigo-950/60 border border-indigo-500/30 shadow-2xl space-y-4">
        {/* Başlık ve Aksiyon Barı */}
        <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-3 border-b border-bunker-800 pb-3">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-indigo-500/20 border border-indigo-400/40 flex items-center justify-center text-xl shrink-0">
              📅
            </div>
            <div>
              <div className="flex items-center gap-2 flex-wrap">
                <h2 className="text-sm sm:text-base font-black text-white tracking-wide uppercase">
                  Ekonomik Takvim (Investing.com 2 &amp; 3 Yıldız)
                </h2>
                <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-amber-500/20 text-amber-300 border border-amber-500/40">
                  ⭐⭐ / ⭐⭐⭐ Kritik Volatilite
                </span>
              </div>
              <p className="text-[11px] text-bunker-muted mt-0.5">
                Investing.com 2 ve 3 yıldızlı makro açıklamalar, etkilenen Forex/Kripto pariteleri ve &quot;Hangi Durumda Nasıl Etkilenir?&quot; senaryoları
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2 flex-wrap">
            <a
              href="https://www.investing.com/economic-calendar"
              target="_blank"
              rel="noopener noreferrer"
              className="px-3 py-1.5 rounded-xl text-xs font-bold bg-amber-500/15 text-amber-300 border border-amber-500/30 hover:bg-amber-500/25 transition-all flex items-center gap-1.5 shadow-sm"
            >
              <span>🌐</span> Investing.com Takvimi ↗
            </a>

            <button
              type="button"
              onClick={() => triggerTestCalendarNotification()}
              className="px-2.5 py-1.5 rounded-xl text-xs font-bold bg-rose-500/15 text-rose-300 border border-rose-500/30 hover:bg-rose-500/25 transition-all flex items-center gap-1.5 shadow-sm"
              title="5 dakika kala çıkacak acil uyarı modalini ve sesini test edin"
            >
              <span>⚡</span> 5 Dk Uyarısını Test Et
            </button>

            <button
              type="button"
              onClick={() => fetchCalendar(true)}
              disabled={refreshingCalendar}
              className="px-3 py-1.5 rounded-xl text-xs font-bold bg-indigo-500/20 text-indigo-300 border border-indigo-500/40 hover:bg-indigo-500/30 transition-all flex items-center gap-1.5 disabled:opacity-50"
            >
              <span className={refreshingCalendar ? "animate-spin" : ""}>🔄</span>
              <span>{refreshingCalendar ? "Yenileniyor…" : "Takvimi Yenile"}</span>
            </button>

            {calendarLastUpdated && (
              <span className="text-[10px] text-bunker-muted hidden md:inline">
                {calendarLastUpdated.toLocaleTimeString("tr-TR", { hour: "2-digit", minute: "2-digit" })}
              </span>
            )}
          </div>
        </div>

        {/* Filtre ve Arama Kontrolleri */}
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-3 pt-1">
          {/* Yıldız Filtreleri */}
          <div className="flex items-center gap-1.5 flex-wrap">
            <span className="text-[11px] text-bunker-muted font-bold mr-1">Önem:</span>
            <button
              type="button"
              onClick={() => setCalendarFilterStars("ALL")}
              className={`px-2.5 py-1 rounded-lg text-xs font-bold transition-all ${
                calendarFilterStars === "ALL"
                  ? "bg-cyan-500/30 text-cyan-200 border border-cyan-400"
                  : "bg-bunker-900 text-bunker-muted border border-bunker-800 hover:text-white"
              }`}
            >
              Tümü ({calendarEvents.length})
            </button>
            <button
              type="button"
              onClick={() => setCalendarFilterStars(3)}
              className={`px-2.5 py-1 rounded-lg text-xs font-bold transition-all ${
                calendarFilterStars === 3
                  ? "bg-rose-500/30 text-rose-200 border border-rose-400"
                  : "bg-bunker-900 text-bunker-muted border border-bunker-800 hover:text-rose-300"
              }`}
            >
              ⭐⭐⭐ 3 Yıldız ({calendarEvents.filter((x) => (x.stars || (x.impact === "High" ? 3 : 2)) === 3).length})
            </button>
            <button
              type="button"
              onClick={() => setCalendarFilterStars(2)}
              className={`px-2.5 py-1 rounded-lg text-xs font-bold transition-all ${
                calendarFilterStars === 2
                  ? "bg-amber-500/30 text-amber-200 border border-amber-400"
                  : "bg-bunker-900 text-bunker-muted border border-bunker-800 hover:text-amber-300"
              }`}
            >
              ⭐⭐ 2 Yıldız ({calendarEvents.filter((x) => (x.stars || (x.impact === "High" ? 3 : 2)) === 2).length})
            </button>
          </div>

          {/* Varlık / Arama Filtresi */}
          <div className="flex items-center gap-2 flex-wrap">
            <div className="flex items-center gap-1 overflow-x-auto scrollbar-none">
              {(["ALL", "USD", "EUR", "GBP", "JPY", "CAD", "XAU", "OIL"] as const).map((code) => {
                const label = code === "ALL" ? "Tümü" : code === "XAU" ? "Altın (XAU)" : code === "OIL" ? "Petrol (OIL)" : code;
                return (
                  <button
                    key={code}
                    type="button"
                    onClick={() => setCalendarFilterCurrency(code)}
                    className={`px-2 py-0.5 rounded text-[10px] font-bold transition-all ${
                      calendarFilterCurrency === code
                        ? "bg-indigo-500 text-white"
                        : "bg-bunker-900/80 text-bunker-muted hover:text-white"
                    }`}
                  >
                    {label}
                  </button>
                );
              })}
            </div>

            <input
              type="text"
              value={calendarSearch}
              onChange={(e) => setCalendarSearch(e.target.value)}
              placeholder="Olay, parite veya ülke ara..."
              className="px-2.5 py-1 rounded-lg bg-bunker-950 border border-bunker-800 text-xs text-white placeholder-bunker-muted focus:border-cyan-400 focus:outline-none w-36 sm:w-44"
            />
          </div>
        </div>

        {/* İçerik Kartları */}
        {loadingCalendar && calendarEvents.length === 0 ? (
          <div className="p-8 text-center text-xs text-bunker-muted animate-pulse font-mono rounded-xl bg-bunker-950/50 border border-bunker-800">
            Investing.com 2 ve 3 yıldızlı ekonomik takvim verileri ve senaryoları yükleniyor…
          </div>
        ) : filteredCalendarEvents.length === 0 ? (
          <div className="p-8 text-center space-y-2 rounded-xl bg-bunker-950/50 border border-bunker-800">
            <p className="text-xs text-bunker-muted font-mono">
              Seçilen filtrelere uygun 2 veya 3 yıldızlı takvim olayı bulunamadı.
            </p>
            <button
              type="button"
              onClick={() => {
                setCalendarFilterStars("ALL");
                setCalendarFilterCurrency("ALL");
                setCalendarSearch("");
              }}
              className="px-3 py-1 rounded text-xs font-bold bg-cyan-500/20 text-cyan-300 border border-cyan-500/40 hover:bg-cyan-500/30"
            >
              Filtreleri Temizle
            </button>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3.5">
            {filteredCalendarEvents.map((item) => {
              const is3Stars = (item.stars || (item.impact === "High" ? 3 : 2)) === 3;
              return (
                <div
                  key={item.id}
                  className={`p-4 rounded-xl border backdrop-blur-md transition-all hover:scale-[1.008] space-y-3 flex flex-col justify-between ${
                    is3Stars
                      ? "border-rose-500/40 bg-gradient-to-b from-rose-950/20 via-bunker-900/90 to-bunker-950 hover:border-rose-400 hover:shadow-[0_0_20px_rgba(244,63,94,0.2)]"
                      : "border-amber-500/35 bg-gradient-to-b from-amber-950/15 via-bunker-900/90 to-bunker-950 hover:border-amber-400 hover:shadow-[0_0_20px_rgba(245,158,11,0.2)]"
                  }`}
                >
                  {/* Kart Üst Barı: Zaman, Geri Sayım ve Yıldız */}
                  <div className="flex flex-wrap items-center justify-between gap-2 border-b border-bunker-800/80 pb-2">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="text-xs font-black text-cyan-300 flex items-center gap-1.5">
                        <span>⏰</span> {item.date_str}
                      </span>
                      <EventCountdownBadge
                        dateIso={item.date_iso}
                        dateStr={item.date_str}
                        status={item.status}
                        isPassed={item.is_passed}
                      />
                      <span
                        className={`px-1.5 py-0.5 rounded text-[9px] font-bold ${
                          item.status === "Açıklandı"
                            ? "bg-emerald-500/20 text-emerald-300 border border-emerald-500/30"
                            : item.is_passed
                            ? "bg-slate-700/40 text-slate-300 border border-slate-600/40"
                            : "bg-cyan-500/20 text-cyan-300 border border-cyan-500/30"
                        }`}
                      >
                        {item.status || "Bekleniyor"}
                      </span>
                    </div>

                    <span
                      className={`px-2 py-0.5 rounded-full text-[9px] font-black uppercase tracking-wider shrink-0 ${
                        is3Stars
                          ? "bg-rose-500/25 text-rose-300 border border-rose-500/50"
                          : "bg-amber-500/25 text-amber-300 border border-amber-500/50"
                      }`}
                    >
                      {is3Stars ? "⭐⭐⭐ 3 YILDIZ (KRİTİK)" : "⭐⭐ 2 YILDIZ (ORTA)"}
                    </span>
                  </div>

                  {/* Olay Başlığı ve Değerler */}
                  <div className="space-y-1.5">
                    <div className="flex items-center gap-1.5 text-xs text-bunker-muted font-bold">
                      <span>{item.flag || "🌐"}</span>
                      <span>{item.country_name || item.country}</span>
                      {item.currency && <span className="text-[10px] text-cyan-400">({item.currency})</span>}
                    </div>

                    <h3 className="font-black text-sm text-white hover:text-cyan-300 transition-colors leading-snug">
                      {item.title}
                    </h3>
                    {item.original_title && item.original_title !== item.title && (
                      <p className="text-[10px] text-bunker-muted italic line-clamp-1">
                        {item.original_title}
                      </p>
                    )}

                    {/* Metrikler */}
                    <div className="grid grid-cols-3 gap-1.5 p-2 rounded-xl bg-bunker-950/80 border border-bunker-800/80 text-center text-[10px]">
                      <div>
                        <div className="text-bunker-muted text-[9px]">Beklenti</div>
                        <div className="font-bold text-cyan-300">{item.forecast || "—"}</div>
                      </div>
                      <div>
                        <div className="text-bunker-muted text-[9px]">Önceki</div>
                        <div className="font-bold text-slate-300">{item.previous || "—"}</div>
                      </div>
                      <div>
                        <div className="text-bunker-muted text-[9px]">Açıklanan</div>
                        <div className={`font-black ${item.actual && item.actual !== "—" ? "text-emerald-400" : "text-bunker-muted"}`}>
                          {item.actual || "—"}
                        </div>
                      </div>
                    </div>
                  </div>

                  {/* Etkilenen Pariteler */}
                  <div className="space-y-1">
                    <div className="text-[10px] uppercase font-bold text-bunker-muted flex items-center gap-1">
                      <span>🎯</span> Etkilenen Pariteler:
                    </div>
                    <div className="flex flex-wrap gap-1">
                      {item.affected_symbols.map((sym) => (
                        <span
                          key={sym}
                          className="px-2 py-0.5 rounded text-[10px] font-black bg-cyan-950/60 text-cyan-300 border border-cyan-500/40"
                        >
                          {sym}
                        </span>
                      ))}
                    </div>
                  </div>

                  {/* ⚡ HANGİ DURUMDA NASIL ETKİLENİR? (ÖZET SENARYO KUTUSU) */}
                  <div className="p-3 rounded-xl bg-bunker-950/90 border border-bunker-800 space-y-2 text-xs">
                    <div className="text-[10px] font-black uppercase tracking-wider text-amber-300 flex items-center justify-between">
                      <span className="flex items-center gap-1">
                        <span>⚡</span> Hangi Durumda Nasıl Etkilenir?
                      </span>
                    </div>

                    {/* Beklenti Üzeri */}
                    <div className="space-y-0.5">
                      <div className="font-bold text-emerald-400 text-[10px] flex items-center gap-1">
                        <span>🟢</span>
                        <span>{item.scenario?.bullish_trigger || "Beklenti Üzeri Gelirse:"}</span>
                      </div>
                      <p className="text-[11px] text-emerald-200/90 pl-3 leading-tight">
                        {item.scenario?.bullish_outcome}
                      </p>
                    </div>

                    {/* Beklenti Altı */}
                    <div className="space-y-0.5 pt-1 border-t border-bunker-800/60">
                      <div className="font-bold text-rose-400 text-[10px] flex items-center gap-1">
                        <span>🔴</span>
                        <span>{item.scenario?.bearish_trigger || "Beklenti Altı Kalırsa:"}</span>
                      </div>
                      <p className="text-[11px] text-rose-200/90 pl-3 leading-tight">
                        {item.scenario?.bearish_outcome}
                      </p>
                    </div>

                    {/* Scalper Notu */}
                    {item.scenario?.scalper_tip && (
                      <div className="pt-1 border-t border-bunker-800/60 text-[10px] text-cyan-300/90 flex items-start gap-1">
                        <span className="shrink-0">💡</span>
                        <span className="italic leading-tight">{item.scenario.scalper_tip}</span>
                      </div>
                    )}
                  </div>

                  {/* Kart Alt Butonu */}
                  <div className="pt-2 border-t border-bunker-800/80 flex items-center justify-between">
                    <span className="text-[10px] text-bunker-muted">
                      Investing 2-3 Yıldız
                    </span>
                    <button
                      type="button"
                      onClick={() => setSelectedEvent(item)}
                      className="px-3 py-1 rounded-lg text-xs font-bold text-cyan-400 bg-cyan-950/40 border border-cyan-500/30 hover:border-cyan-300 hover:text-white transition-all flex items-center gap-1"
                    >
                      Detaylı Analiz &amp; Taktik <span>→</span>
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </section>

      {/* 5. CANLI AÇIK POZİSYONLAR (VARSA) */}
      <section className="space-y-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="w-2.5 h-2.5 rounded-full bg-cyan-400 animate-ping" />
            <h2 className="text-sm font-bold text-white uppercase tracking-wider">
              Canlı Açık Pozisyonlar ({openPositions.length})
            </h2>
          </div>
          {openPositions.length > 0 && (
            <div className="text-xs font-bold">
              Anlık Açık PnL:{" "}
              <span className={openPnlTotal >= 0 ? "text-emerald-400" : "text-rose-400"}>
                {openPnlTotal >= 0 ? `+$${openPnlTotal.toFixed(2)}` : `-$${Math.abs(openPnlTotal).toFixed(2)}`}
              </span>
              {" · "}
              <span className={openPipsTotal >= 0 ? "text-emerald-300" : "text-rose-300"}>
                {openPipsTotal >= 0 ? `+${openPipsTotal.toFixed(1)}` : openPipsTotal.toFixed(1)} pip
              </span>
            </div>
          )}
        </div>

        {openPositions.length === 0 ? (
          <div className="p-6 text-center text-bunker-muted text-xs rounded-2xl bg-bunker-900/50 border border-bunker-800">
            Şu anda açık Forex pozisyonu bulunmuyor. Scalper motoru yeni giriş sinyali gözlemliyor.
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {sortedOpenPositions.map((pos) => {
              const isProfit = (pos.pnl_usd ?? 0) >= 0;
              return (
                <div
                  key={pos.id}
                  className={`p-4 rounded-xl border backdrop-blur-md transition-all ${
                    isProfit
                      ? "border-emerald-500/40 bg-emerald-950/20 shadow-[0_0_12px_rgba(16,185,129,0.1)]"
                      : "border-rose-500/40 bg-rose-950/20 shadow-[0_0_12px_rgba(244,63,94,0.1)]"
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <span className="font-bold text-sm text-white">{pos.symbol}</span>
                    <span
                      className={`px-2 py-0.5 rounded text-[10px] font-black ${
                        pos.direction === "BUY"
                          ? "bg-emerald-500/20 text-emerald-300 border border-emerald-500/40"
                          : "bg-rose-500/20 text-rose-300 border border-rose-500/40"
                      }`}
                    >
                      {pos.direction} {pos.lots} Lot
                    </span>
                  </div>

                  <div className="mt-3 flex items-baseline justify-between">
                    <div className="text-[11px] text-bunker-muted">
                      <div>Giriş: {formatPrice(pos.entry_price, pos.symbol)}</div>
                      <div>Anlık: {formatPrice(pos.current_price, pos.symbol)}</div>
                    </div>
                    <div className="text-right">
                      <div className={`text-lg font-black ${isProfit ? "text-emerald-400" : "text-rose-400"}`}>
                        {pos.pnl_usd >= 0 ? `+$${pos.pnl_usd.toFixed(2)}` : `-$${Math.abs(pos.pnl_usd).toFixed(2)}`}
                      </div>
                      <div className={`text-[10px] font-bold ${pos.pnl_pips >= 0 ? "text-emerald-300" : "text-rose-300"}`}>
                        {pos.pnl_pips >= 0 ? `+${pos.pnl_pips.toFixed(1)}` : pos.pnl_pips.toFixed(1)} pip
                      </div>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </section>

      {/* 6. PARİTE BAZINDA GÜNLÜK KÂR / ZARAR DAĞILIMI */}
      {symbolStats.length > 0 && (
        <section className="p-5 rounded-2xl bg-bunker-900/80 border border-bunker-800 shadow-xl space-y-3">
          <div className="flex items-center gap-2">
            <span className="text-base">🪙</span>
            <h2 className="text-sm font-bold text-white uppercase tracking-wider">
              Parite Bazında Günlük Kâr / Zarar Katkısı
            </h2>
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-2.5">
            {symbolStats.map((item) => {
              const pos = item.pnl_usd >= 0;
              return (
                <div
                  key={item.symbol}
                  className="p-3 rounded-xl bg-bunker-950/70 border border-bunker-800 hover:border-cyan-500/40 transition-all space-y-1"
                >
                  <div className="flex justify-between items-center text-xs font-bold text-white">
                    <span>{item.symbol}</span>
                    <span className="text-[10px] text-bunker-muted">{item.trades} işlem</span>
                  </div>
                  <div className={`text-sm font-black ${pos ? "text-emerald-400" : "text-rose-400"}`}>
                    {pos ? `+$${item.pnl_usd.toFixed(2)}` : `-$${Math.abs(item.pnl_usd).toFixed(2)}`}
                  </div>
                  <div className="text-[10px] text-bunker-muted flex justify-between">
                    <span>%{item.trades > 0 ? ((item.wins / item.trades) * 100).toFixed(0) : 0} Win</span>
                    <span className={item.pnl_pips >= 0 ? "text-emerald-300" : "text-rose-300"}>
                      {item.pnl_pips >= 0 ? `+${item.pnl_pips.toFixed(0)}` : item.pnl_pips.toFixed(0)}p
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
        </section>
      )}

      {/* 7. GÜNÜN KAPANAN İŞLEMLERİ LİSTESİ */}
      <section className="p-5 rounded-2xl bg-bunker-900/80 border border-bunker-800 shadow-xl space-y-4">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <span className="text-base">📜</span>
            <h2 className="text-sm font-bold text-white uppercase tracking-wider">
              Bugün Kapanan İşlemler ({filteredClosedTrades.length})
            </h2>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            {/* Sayfa Başı Kayıt */}
            <div className="flex items-center gap-1.5 bg-bunker-950 px-2.5 py-1 rounded-xl border border-bunker-800 text-[11px] text-bunker-muted">
              <span>Sayfa Başı:</span>
              <select
                value={tradesPageSize}
                onChange={(e) => setTradesPageSize(Number(e.target.value))}
                className="bg-bunker-900 border border-bunker-700 rounded px-1.5 py-0.5 text-white font-bold outline-none cursor-pointer"
              >
                <option value={10}>10</option>
                <option value={20}>20</option>
                <option value={50}>50</option>
              </select>
            </div>

            {/* Filtre Butonları */}
            <div className="flex items-center gap-1 bg-bunker-950 p-1 rounded-xl border border-bunker-800">
              <button
                type="button"
                onClick={() => setFilterOutcome("ALL")}
                className={`px-3 py-1 rounded-lg text-xs font-bold transition-all ${
                  filterOutcome === "ALL" ? "bg-cyan-500/20 text-cyan-300 border border-cyan-400/40" : "text-bunker-muted hover:text-white"
                }`}
              >
                Tümü ({closedTrades.length})
              </button>
              <button
                type="button"
                onClick={() => setFilterOutcome("WIN")}
                className={`px-3 py-1 rounded-lg text-xs font-bold transition-all ${
                  filterOutcome === "WIN" ? "bg-emerald-500/20 text-emerald-300 border border-emerald-500/40" : "text-bunker-muted hover:text-white"
                }`}
              >
                Kazanılan ({kpi.wins})
              </button>
              <button
                type="button"
                onClick={() => setFilterOutcome("LOSS")}
                className={`px-3 py-1 rounded-lg text-xs font-bold transition-all ${
                  filterOutcome === "LOSS" ? "bg-rose-500/20 text-rose-300 border border-rose-500/40" : "text-bunker-muted hover:text-white"
                }`}
              >
                Kayıp ({kpi.losses})
              </button>
            </div>
          </div>
        </div>

        {filteredClosedTrades.length === 0 ? (
          <div className="p-8 text-center text-bunker-muted text-xs">
            {loading ? "İşlem verileri yükleniyor…" : "Bugün için seçilen filtrede kapanmış işlem bulunmuyor."}
          </div>
        ) : (
          <div className="space-y-3">
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs border-collapse">
                <thead>
                  <tr className="border-b border-bunker-800 text-[10px] text-bunker-muted uppercase tracking-wider">
                    <th className="py-2.5 px-3">Zaman</th>
                    <th className="py-2.5 px-3">Parite</th>
                    <th className="py-2.5 px-3">Yön / Lot</th>
                    <th className="py-2.5 px-3 text-right">Giriş / Çıkış</th>
                    <th className="py-2.5 px-3 text-right">Pip</th>
                    <th className="py-2.5 px-3 text-right">Net Getiri ($)</th>
                    <th className="py-2.5 px-3">Çıkış Nedeni</th>
                    <th className="py-2.5 px-3 text-center">Sonuç</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-bunker-800/60 font-mono">
                  {paginatedClosedTrades.map((t) => {
                    const isWin = (t.pnl_usd ?? 0) > 0 || t.outcome === "WIN";
                    return (
                      <tr key={t.id || t.ticket} className="hover:bg-bunker-800/30 transition-colors">
                        <td className="py-2.5 px-3 text-bunker-muted text-[11px]">
                          {formatClockTime(t.exit_time || t.close_time)}
                        </td>
                        <td className="py-2.5 px-3 font-bold text-white">
                          {t.symbol || t.display}
                        </td>
                        <td className="py-2.5 px-3">
                          <span
                            className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${
                              t.direction === "BUY"
                                ? "bg-emerald-500/15 text-emerald-300"
                                : "bg-rose-500/15 text-rose-300"
                            }`}
                          >
                            {t.direction} {t.lots}L
                          </span>
                        </td>
                        <td className="py-2.5 px-3 text-right text-[11px] text-bunker-muted">
                          <div>{formatPrice(t.entry_price, t.symbol)}</div>
                          <div className="text-white">{formatPrice(t.exit_price ?? t.close_price, t.symbol)}</div>
                        </td>
                        <td className="py-2.5 px-3 text-right font-bold">
                          <span className={(t.pnl_pips ?? 0) >= 0 ? "text-emerald-300" : "text-rose-300"}>
                            {(t.pnl_pips ?? 0) >= 0 ? `+${(t.pnl_pips ?? 0).toFixed(1)}` : (t.pnl_pips ?? 0).toFixed(1)}
                          </span>
                        </td>
                        <td className="py-2.5 px-3 text-right font-black text-sm">
                          <span className={isWin ? "text-emerald-400" : "text-rose-400"}>
                            {(t.pnl_usd ?? 0) >= 0 ? `+$${(t.pnl_usd ?? 0).toFixed(2)}` : `-$${Math.abs(t.pnl_usd ?? 0).toFixed(2)}`}
                          </span>
                        </td>
                        <td className="py-2.5 px-3 text-[11px] text-bunker-300 truncate max-w-[140px]" title={t.exit_reason || ""}>
                          {t.exit_reason_title || t.exit_reason || "Pozisyon Kapanışı"}
                        </td>
                        <td className="py-2.5 px-3 text-center">
                          <span
                            className={`px-2 py-0.5 rounded text-[10px] font-black uppercase ${
                              isWin
                                ? "bg-emerald-500/20 text-emerald-300 border border-emerald-500/40"
                                : "bg-rose-500/20 text-rose-300 border border-rose-500/40"
                            }`}
                          >
                            {isWin ? "WIN" : "LOSS"}
                          </span>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            {/* Sayfalandırma (Pagination) Kontrolleri */}
            {filteredClosedTrades.length > 0 && (
              <div className="pt-3 border-t border-bunker-800 flex flex-col sm:flex-row items-center justify-between gap-3 text-xs">
                <div className="text-[11px] text-bunker-muted">
                  Toplam <strong className="text-white">{filteredClosedTrades.length}</strong> işlemden{" "}
                  <strong className="text-cyan-300">
                    {(safeTradesPage - 1) * tradesPageSize + 1} – {Math.min(safeTradesPage * tradesPageSize, filteredClosedTrades.length)}
                  </strong>{" "}
                  arası gösteriliyor (Sayfa {safeTradesPage} / {totalTradesPages})
                </div>

                <div className="flex items-center gap-1.5">
                  <button
                    type="button"
                    onClick={() => setTradesPage(1)}
                    disabled={safeTradesPage <= 1}
                    className="px-2.5 py-1 rounded-lg bg-bunker-950 border border-bunker-800 text-bunker-300 hover:text-white disabled:opacity-30 disabled:pointer-events-none transition-colors"
                    title="İlk Sayfa"
                  >
                    ⏮ İlk
                  </button>
                  <button
                    type="button"
                    onClick={() => setTradesPage((p) => Math.max(1, p - 1))}
                    disabled={safeTradesPage <= 1}
                    className="px-2.5 py-1 rounded-lg bg-bunker-950 border border-bunker-800 text-bunker-300 hover:text-white disabled:opacity-30 disabled:pointer-events-none transition-colors font-bold"
                    title="Önceki Sayfa"
                  >
                    ◀ Önceki
                  </button>

                  <span className="px-3 py-1 rounded-lg bg-cyan-950/80 border border-cyan-500/40 text-cyan-300 font-bold font-mono text-xs">
                    {safeTradesPage} / {totalTradesPages}
                  </span>

                  <button
                    type="button"
                    onClick={() => setTradesPage((p) => Math.min(totalTradesPages, p + 1))}
                    disabled={safeTradesPage >= totalTradesPages}
                    className="px-2.5 py-1 rounded-lg bg-bunker-950 border border-bunker-800 text-bunker-300 hover:text-white disabled:opacity-30 disabled:pointer-events-none transition-colors font-bold"
                    title="Sonraki Sayfa"
                  >
                    Sonraki ▶
                  </button>
                  <button
                    type="button"
                    onClick={() => setTradesPage(totalTradesPages)}
                    disabled={safeTradesPage >= totalTradesPages}
                    className="px-2.5 py-1 rounded-lg bg-bunker-950 border border-bunker-800 text-bunker-300 hover:text-white disabled:opacity-30 disabled:pointer-events-none transition-colors"
                    title="Son Sayfa"
                  >
                    Son ⏭
                  </button>
                </div>
              </div>
            )}
          </div>
        )}
      </section>

      {/* 8. HABER / TAKVİM DETAY VE SENARYO ANALİZ MODALI (PENCERE) */}
      {selectedEvent && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm"
          onClick={() => setSelectedEvent(null)}
          role="dialog"
          aria-modal="true"
        >
          <div
            className="w-full max-w-2xl rounded-2xl border border-indigo-500/40 bg-bunker-950 p-6 shadow-2xl space-y-5 animate-in fade-in zoom-in-95 duration-150 max-h-[90vh] overflow-y-auto"
            onClick={(e) => e.stopPropagation()}
          >
            {/* Modal Başlığı */}
            <div className="flex items-start justify-between gap-4 border-b border-bunker-800 pb-4">
              <div>
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-xl">📅</span>
                  <span
                    className={`px-2.5 py-0.5 rounded-full text-[10px] font-black uppercase tracking-wider ${
                      (selectedEvent.stars || (selectedEvent.impact === "High" ? 3 : 2)) === 3
                        ? "bg-rose-500/20 text-rose-300 border border-rose-500/40"
                        : "bg-amber-500/20 text-amber-300 border border-amber-500/40"
                    }`}
                  >
                    {selectedEvent.impact_label || ((selectedEvent.stars || 2) === 3 ? "⭐⭐⭐ YÜKSEK (3 Yıldız)" : "⭐⭐ ORTA (2 Yıldız)")}
                  </span>
                  <span className="text-xs text-cyan-400 font-bold">
                    ⏰ {selectedEvent.date_str}
                  </span>
                  <EventCountdownBadge
                    dateIso={selectedEvent.date_iso}
                    dateStr={selectedEvent.date_str}
                    status={selectedEvent.status}
                    isPassed={selectedEvent.is_passed}
                  />
                  {selectedEvent.status && (
                    <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-cyan-950 text-cyan-300 border border-cyan-500/30">
                      {selectedEvent.status}
                    </span>
                  )}
                </div>
                <h2 className="text-lg font-black text-white mt-2 leading-tight">
                  {selectedEvent.flag ? `${selectedEvent.flag} ` : ""}{selectedEvent.title}
                </h2>
                {selectedEvent.original_title && (
                  <p className="text-xs text-bunker-muted mt-0.5">
                    Orijinal Adı: {selectedEvent.original_title} ({selectedEvent.country_name || selectedEvent.country})
                  </p>
                )}
              </div>

              <button
                type="button"
                onClick={() => setSelectedEvent(null)}
                className="w-8 h-8 rounded-xl bg-bunker-900 border border-bunker-700 hover:border-white text-bunker-muted hover:text-white flex items-center justify-center text-sm font-bold transition-all shrink-0"
              >
                ✕
              </button>
            </div>

            {/* Veri Özeti & Etkilenen Semboller */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div className="p-3.5 rounded-xl bg-bunker-900/80 border border-bunker-800 space-y-1.5">
                <span className="text-[10px] uppercase font-bold text-bunker-muted">Veri Beklentisi &amp; Sonuç</span>
                <div className="grid grid-cols-3 gap-2 text-xs pt-1">
                  <div>
                    <div className="text-[10px] text-bunker-muted">Beklenti:</div>
                    <strong className="text-cyan-300">{selectedEvent.forecast || "—"}</strong>
                  </div>
                  <div>
                    <div className="text-[10px] text-bunker-muted">Önceki:</div>
                    <strong className="text-white">{selectedEvent.previous || "—"}</strong>
                  </div>
                  <div>
                    <div className="text-[10px] text-bunker-muted">Açıklanan:</div>
                    <strong className={selectedEvent.actual && selectedEvent.actual !== "—" ? "text-emerald-400 font-black" : "text-bunker-muted"}>
                      {selectedEvent.actual || "—"}
                    </strong>
                  </div>
                </div>
              </div>

              <div className="p-3.5 rounded-xl bg-bunker-900/80 border border-bunker-800 space-y-1.5">
                <span className="text-[10px] uppercase font-bold text-bunker-muted">Etkilenen Pariteler</span>
                <div className="flex flex-wrap gap-1.5 pt-1">
                  {selectedEvent.affected_symbols.map((sym) => (
                    <span
                      key={sym}
                      className="px-2.5 py-1 rounded-lg text-[11px] font-black bg-cyan-500/20 text-cyan-300 border border-cyan-500/40"
                    >
                      {sym}
                    </span>
                  ))}
                </div>
              </div>
            </div>

            {/* Gösterge Açıklaması (Varsa) */}
            {selectedEvent.comment && (
              <div className="p-3 rounded-xl bg-bunker-900/60 border border-bunker-800 text-xs text-bunker-muted leading-relaxed">
                <strong className="text-white block text-[11px] mb-0.5">ℹ️ Gösterge Hakkında:</strong>
                {selectedEvent.comment}
              </div>
            )}

            {/* "NE OLURSA NE OLUR?" SENARYO MATRİSİ */}
            <div className="space-y-3">
              <div className="flex items-center gap-2">
                <span className="text-base">⚡</span>
                <h3 className="text-xs font-black uppercase tracking-wider text-amber-300">
                  {selectedEvent.scenario?.title || "Ne Olursa Ne Olur? Senaryo Analizi"}
                </h3>
              </div>

              <div className="space-y-2.5 text-xs">
                {/* OLUMLU / BEKLENTİ ÜZERİ */}
                <div className="p-3.5 rounded-xl bg-emerald-500/10 border border-emerald-500/30 space-y-1">
                  <div className="font-bold text-emerald-400 flex items-center gap-1.5">
                    <span>🟢</span>
                    <span>{selectedEvent.scenario?.bullish_trigger}</span>
                  </div>
                  <p className="text-[11px] text-emerald-200/90 leading-relaxed pl-5">
                    {selectedEvent.scenario?.bullish_outcome}
                  </p>
                </div>

                {/* OLUMSUZ / BEKLENTİ ALTI */}
                <div className="p-3.5 rounded-xl bg-rose-500/10 border border-rose-500/30 space-y-1">
                  <div className="font-bold text-rose-400 flex items-center gap-1.5">
                    <span>🔴</span>
                    <span>{selectedEvent.scenario?.bearish_trigger}</span>
                  </div>
                  <p className="text-[11px] text-rose-200/90 leading-relaxed pl-5">
                    {selectedEvent.scenario?.bearish_outcome}
                  </p>
                </div>

                {/* SCALPER İPUCU */}
                {selectedEvent.scenario?.scalper_tip && (
                  <div className="p-3 rounded-xl bg-cyan-950/30 border border-cyan-500/30 text-[11px] text-cyan-200 space-y-1">
                    <span className="font-bold text-cyan-400 uppercase text-[10px] tracking-wider block">
                      🎯 Scalper Operatör Notu:
                    </span>
                    <p className="leading-relaxed">
                      {selectedEvent.scenario.scalper_tip}
                    </p>
                  </div>
                )}
              </div>
            </div>

            {/* Alt Butonlar */}
            <div className="pt-3 border-t border-bunker-800 flex items-center justify-between gap-3">
              <a
                href="https://www.investing.com/economic-calendar"
                target="_blank"
                rel="noopener noreferrer"
                className="px-3.5 py-1.5 rounded-xl text-xs font-bold text-amber-300 bg-amber-500/10 border border-amber-500/30 hover:bg-amber-500/20 transition-all flex items-center gap-1"
              >
                <span>🌐</span> Investing.com Takvimine Git ↗
              </a>

              <button
                type="button"
                onClick={() => setSelectedEvent(null)}
                className="px-5 py-2 rounded-xl bg-bunker-900 border border-bunker-700 hover:border-cyan-400 text-white text-xs font-bold transition-all"
              >
                Kapat
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
