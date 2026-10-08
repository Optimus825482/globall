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
  time?: number | string;
  closed_at_ts?: number;
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

        // Bulunulan tarihteki saat 00:01'den sonraki kapanan işlemleri filtrele (İşlemler sayfasıyla birebir aynı)
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
        let totalPips = 0;
        let grossProfit = 0;
        let grossLoss = 0;
        for (const t of validTrades) {
          const pnl = Number(t.pnl_usd ?? 0);
          totalPnl += pnl;
          totalPips += Number(t.pnl_pips ?? 0);
          if (pnl > 0 || t.outcome === "WIN") {
            winsCount += 1;
            grossProfit += pnl;
          } else if (pnl < 0 || t.outcome === "LOSS") {
            lossesCount += 1;
            grossLoss += Math.abs(pnl);
          }
        }
        const totalTradesCount = validTrades.length;
        const winRatePct = totalTradesCount > 0 ? (winsCount / totalTradesCount) * 100 : 0;
        const pf = grossLoss > 0 ? Number((grossProfit / grossLoss).toFixed(2)) : (grossProfit > 0 ? 999 : 0);

        setKpi((prev) => ({
          ...prev,
          total_trades: totalTradesCount,
          wins: winsCount,
          losses: lossesCount,
          win_rate: winRatePct,
          total_pnl_usd: totalPnl,
          total_pnl_pips: totalPips,
          profit_factor: pf,
          profit_factor_infinite: pf >= 999,
          gross_profit_usd: grossProfit,
          gross_loss_usd: grossLoss,
          balance: statusRes?.balance ?? reportRes.kpi?.balance ?? prev.balance,
          equity: statusRes?.equity ?? reportRes.kpi?.equity ?? prev.equity,
          open_positions_count: Array.isArray(reportRes.open_positions) ? reportRes.open_positions.length : prev.open_positions_count,
          open_pnl_usd: Array.isArray(reportRes.open_positions)
            ? reportRes.open_positions.reduce((acc: number, p: any) => acc + Number(p.pnl_usd ?? 0), 0)
            : prev.open_pnl_usd,
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

    // Ekonomik takvim veritabanı önbelleğinden anında okunur (3 dakikada bir senkron kontrolü)
    const calendarInterval = setInterval(() => {
      if (!document.hidden) {
        fetchCalendar(false);
      }
    }, 180000);

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
    }).sort((a, b) => {
      // Tarihe göre artan (kronolojik: en erken/en yakın olandan ileriye doğru) sıralama
      const getTime = (e: EconomicEvent): number => {
        if (e.date_iso) {
          const t = new Date(e.date_iso).getTime();
          if (!isNaN(t) && t > 0) return t;
        }
        if (e.date_str) {
          const m = e.date_str.match(/(\d{1,2}):(\d{2})/);
          if (m) {
            const d = new Date();
            d.setHours(parseInt(m[1], 10), parseInt(m[2], 10), 0, 0);
            if (e.date_str.toLowerCase().includes("yarın")) {
              d.setDate(d.getDate() + 1);
            }
            return d.getTime();
          }
        }
        return 9999999999999;
      };
      return getTime(a) - getTime(b);
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
                <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-emerald-500/20 text-emerald-300 border border-emerald-500/40">
                  ⚡ Veritabanı Önbelleği (3 Saatte Bir Otomatik)
                </span>
              </div>
              <p className="text-[11px] text-bunker-muted mt-0.5">
                Investing.com 2 ve 3 yıldızlı makro açıklamalar günde bir ve gün içerisinde 3 saatte bir arka planda çekilir; veritabanından anında sunulur.
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
          <div className="overflow-x-auto rounded-xl border border-slate-300 dark:border-bunker-800 bg-white dark:bg-bunker-900/80 shadow-md">
            <table className="w-full text-left border-collapse text-xs">
              <thead>
                <tr className="border-b border-slate-300 dark:border-bunker-800 bg-slate-100/90 dark:bg-bunker-950/80 text-slate-700 dark:text-slate-300 font-bold uppercase tracking-wider text-[11px]">
                  <th className="py-3 px-3.5 whitespace-nowrap">Tarih &amp; Saat</th>
                  <th className="py-3 px-3 whitespace-nowrap">Yıldız (Önem)</th>
                  <th className="py-3 px-3 whitespace-nowrap">Geri Sayım</th>
                  <th className="py-3 px-4 min-w-[240px]">Haber / Olay Başlığı</th>
                  <th className="py-3 px-3 whitespace-nowrap">Beklenti / Sonuç</th>
                  <th className="py-3 px-3 min-w-[140px]">Etkilenebilecek Semboller</th>
                  <th className="py-3 px-3 text-right whitespace-nowrap">İşlem</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-200 dark:divide-bunker-800/80">
                {filteredCalendarEvents.map((item) => {
                  const is3Stars = (item.stars || (item.impact === "High" ? 3 : 2)) === 3;
                  return (
                    <tr
                      key={item.id}
                      onClick={() => setSelectedEvent(item)}
                      className={`cursor-pointer transition-colors group ${
                        is3Stars
                          ? "hover:bg-rose-500/10 dark:hover:bg-rose-950/20"
                          : "hover:bg-cyan-500/10 dark:hover:bg-cyan-950/20"
                      }`}
                      title="Detaylı senaryo ve strateji analizini kart olarak açmak için tıklayın"
                    >
                      {/* 1. Sütun: Tarih & Saat */}
                      <td className="py-3 px-3.5 whitespace-nowrap">
                        <div className="flex items-center gap-1.5 font-black text-slate-900 dark:text-cyan-300 font-mono text-xs">
                          <span>⏰</span>
                          <span>{item.date_str}</span>
                        </div>
                      </td>

                      {/* 2. Sütun: Yıldız Sayısı */}
                      <td className="py-3 px-3 whitespace-nowrap">
                        <span
                          className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-black tracking-wide ${
                            is3Stars
                              ? "bg-rose-500/20 text-rose-700 dark:text-rose-300 border border-rose-500/40"
                              : "bg-amber-500/20 text-amber-750 dark:text-amber-300 border border-amber-500/40"
                          }`}
                        >
                          {is3Stars ? "⭐⭐⭐ 3 Yıldız" : "⭐⭐ 2 Yıldız"}
                        </span>
                      </td>

                      {/* 3. Sütun: Geri Sayım */}
                      <td className="py-3 px-3 whitespace-nowrap">
                        <div className="flex items-center gap-1.5">
                          <EventCountdownBadge
                            dateIso={item.date_iso}
                            dateStr={item.date_str}
                            status={item.status}
                            isPassed={item.is_passed}
                          />
                          <span
                            className={`px-1.5 py-0.5 rounded text-[9px] font-bold ${
                              item.status === "Açıklandı"
                                ? "bg-emerald-500/20 text-emerald-800 dark:text-emerald-300 border border-emerald-500/40"
                                : item.is_passed
                                ? "bg-slate-200 dark:bg-slate-700/50 text-slate-700 dark:text-slate-300 border border-slate-300 dark:border-slate-600/40"
                                : "bg-cyan-500/20 text-cyan-800 dark:text-cyan-300 border border-cyan-500/40"
                            }`}
                          >
                            {item.status || "Bekleniyor"}
                          </span>
                        </div>
                      </td>

                      {/* 4. Sütun: Başlık */}
                      <td className="py-3 px-4">
                        <div className="space-y-0.5">
                          <div className="flex items-center gap-1.5 text-[11px] text-slate-600 dark:text-slate-400 font-bold">
                            <span>{item.flag || "🌐"}</span>
                            <span>{item.country_name || item.country}</span>
                            {item.currency && (
                              <span className="text-[10px] text-indigo-600 dark:text-cyan-400 font-black">
                                ({item.currency})
                              </span>
                            )}
                          </div>
                          <div className="font-extrabold text-slate-900 dark:text-white group-hover:text-cyan-600 dark:group-hover:text-cyan-300 transition-colors text-xs leading-snug">
                            {item.title}
                          </div>
                          {item.original_title && item.original_title !== item.title && (
                            <div className="text-[10px] text-slate-500 dark:text-slate-400 italic line-clamp-1">
                              {item.original_title}
                            </div>
                          )}
                        </div>
                      </td>

                      {/* Ek Bilgi Sütunu: Beklenti / Önceki / Sonuç */}
                      <td className="py-3 px-3 whitespace-nowrap text-[11px]">
                        <div className="space-y-0.5">
                          <div className="text-slate-600 dark:text-slate-400">
                            Beklenti: <span className="font-bold text-slate-900 dark:text-cyan-300">{item.forecast || "—"}</span>
                          </div>
                          <div className="text-slate-500 dark:text-slate-400">
                            Önceki: <span className="font-medium text-slate-700 dark:text-slate-300">{item.previous || "—"}</span>
                          </div>
                          {item.actual && item.actual !== "—" && (
                            <div className="text-emerald-700 dark:text-emerald-400 font-black">
                              Açıklanan: {item.actual}
                            </div>
                          )}
                        </div>
                      </td>

                      {/* 5. Sütun: Etkilenebilecek Semboller */}
                      <td className="py-3 px-3">
                        <div className="flex flex-wrap gap-1 items-center">
                          {item.affected_symbols.map((sym) => (
                            <span
                              key={sym}
                              className="px-2 py-0.5 rounded text-[10px] font-black bg-cyan-100 dark:bg-cyan-950/70 text-cyan-800 dark:text-cyan-300 border border-cyan-400/50 dark:border-cyan-500/40"
                            >
                              {sym}
                            </span>
                          ))}
                        </div>
                      </td>

                      {/* 6. Sütun: Detaylı Kart Butonu */}
                      <td className="py-3 px-3 text-right whitespace-nowrap">
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            setSelectedEvent(item);
                          }}
                          className="px-2.5 py-1 rounded-lg text-xs font-bold text-cyan-700 dark:text-cyan-300 bg-cyan-100 dark:bg-cyan-950/60 border border-cyan-400/60 dark:border-cyan-500/40 hover:bg-cyan-200 dark:hover:bg-cyan-900/60 transition-all inline-flex items-center gap-1 shadow-sm"
                        >
                          <span>🔍 Kart İncele</span>
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
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

      {/* 7. KAPANAN İŞLEMLER RAPOR YÖNLENDİRMESİ & GÜNLÜK ÖZET */}
      <section className="p-4 sm:p-5 rounded-2xl bg-bunker-900/80 border border-bunker-800 shadow-xl flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-cyan-500/10 border border-cyan-400/30 flex items-center justify-center text-xl shrink-0">
            📜
          </div>
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-sm font-bold text-white uppercase tracking-wider">
                Geçmiş ve Kapanan İşlem Raporları
              </h2>
              <span className="text-[10px] px-2 py-0.5 rounded-full bg-bunker-950 text-cyan-300 border border-bunker-800 font-mono font-bold">
                Bugün {closedTrades.length} İşlem Kapandı
              </span>
            </div>
            <p className="text-xs text-bunker-muted mt-1">
              Kapanan işlemlerin tam dökümü, kâr faktörü, PnL detayları ve filtrelemeleri Raporlar sayfasında listelenmektedir.
            </p>
          </div>
        </div>

        <div className="flex items-center gap-3 shrink-0">
          <div className="hidden md:flex flex-col text-right font-mono text-xs">
            <span className="text-[10px] text-bunker-muted">Bugün Net K/Z:</span>
            <span className={`font-bold ${kpi.total_pnl_usd >= 0 ? "text-emerald-400" : "text-rose-400"}`}>
              {kpi.total_pnl_usd >= 0 ? `+$${kpi.total_pnl_usd.toFixed(2)}` : `-$${Math.abs(kpi.total_pnl_usd).toFixed(2)}`}
            </span>
          </div>
          <Link
            href="/forex/reports"
            className="px-4 py-2.5 rounded-xl bg-gradient-to-r from-cyan-500/20 to-blue-500/20 hover:from-cyan-500/30 hover:to-blue-500/30 border border-cyan-400/40 text-cyan-300 font-bold text-xs flex items-center gap-2 transition-all shadow-sm active:scale-95"
          >
            <span>Tüm Kapanan İşlem Raporları</span>
            <span>→</span>
          </Link>
        </div>
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
            className="w-full max-w-2xl rounded-2xl border border-slate-300 dark:border-indigo-500/40 bg-white dark:bg-bunker-950 p-6 shadow-2xl space-y-5 animate-in fade-in zoom-in-95 duration-150 max-h-[90vh] overflow-y-auto"
            onClick={(e) => e.stopPropagation()}
          >
            {/* Modal Başlığı */}
            <div className="flex items-start justify-between gap-4 border-b border-slate-200 dark:border-bunker-800 pb-4">
              <div>
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-xl">📅</span>
                  <span
                    className={`px-2.5 py-0.5 rounded-full text-[10px] font-black uppercase tracking-wider ${
                      (selectedEvent.stars || (selectedEvent.impact === "High" ? 3 : 2)) === 3
                        ? "bg-rose-500/20 text-rose-700 dark:text-rose-300 border border-rose-500/40"
                        : "bg-amber-500/20 text-amber-800 dark:text-amber-300 border border-amber-500/40"
                    }`}
                  >
                    {selectedEvent.impact_label || ((selectedEvent.stars || 2) === 3 ? "⭐⭐⭐ YÜKSEK (3 Yıldız)" : "⭐⭐ ORTA (2 Yıldız)")}
                  </span>
                  <span className="text-xs text-cyan-800 dark:text-cyan-400 font-bold">
                    ⏰ {selectedEvent.date_str}
                  </span>
                  <EventCountdownBadge
                    dateIso={selectedEvent.date_iso}
                    dateStr={selectedEvent.date_str}
                    status={selectedEvent.status}
                    isPassed={selectedEvent.is_passed}
                  />
                  {selectedEvent.status && (
                    <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-cyan-100 dark:bg-cyan-950 text-cyan-800 dark:text-cyan-300 border border-cyan-400/50 dark:border-cyan-500/30">
                      {selectedEvent.status}
                    </span>
                  )}
                </div>
                <h2 className="text-lg font-black text-slate-900 dark:text-white mt-2 leading-tight">
                  {selectedEvent.flag ? `${selectedEvent.flag} ` : ""}{selectedEvent.title}
                </h2>
                {selectedEvent.original_title && (
                  <p className="text-xs text-slate-500 dark:text-bunker-muted mt-0.5">
                    Orijinal Adı: {selectedEvent.original_title} ({selectedEvent.country_name || selectedEvent.country})
                  </p>
                )}
              </div>

              <button
                type="button"
                onClick={() => setSelectedEvent(null)}
                className="w-8 h-8 rounded-xl bg-slate-100 dark:bg-bunker-900 border border-slate-300 dark:border-bunker-700 hover:border-slate-400 dark:hover:border-white text-slate-700 dark:text-bunker-muted hover:text-slate-900 dark:hover:text-white flex items-center justify-center text-sm font-bold transition-all shrink-0"
              >
                ✕
              </button>
            </div>

            {/* Veri Özeti & Etkilenen Semboller */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {/* Beklenti & Sonuçlar */}
              <div className="p-3.5 rounded-xl bg-slate-100/90 dark:bg-bunker-900/80 border border-slate-300 dark:border-bunker-800 space-y-1.5 shadow-sm">
                <span className="text-[10px] uppercase font-bold text-slate-600 dark:text-bunker-muted">Veri Beklentisi &amp; Sonuç</span>
                <div className="grid grid-cols-3 gap-2 text-xs pt-1">
                  <div>
                    <div className="text-[10px] text-slate-500 dark:text-bunker-muted">Beklenti:</div>
                    <strong className="text-cyan-700 dark:text-cyan-300 font-bold">{selectedEvent.forecast || "—"}</strong>
                  </div>
                  <div>
                    <div className="text-[10px] text-slate-500 dark:text-bunker-muted">Önceki:</div>
                    <strong className="text-slate-800 dark:text-white font-bold">{selectedEvent.previous || "—"}</strong>
                  </div>
                  <div>
                    <div className="text-[10px] text-slate-500 dark:text-bunker-muted">Açıklanan:</div>
                    <strong className={selectedEvent.actual && selectedEvent.actual !== "—" ? "text-emerald-700 dark:text-emerald-400 font-black" : "text-slate-500 dark:text-bunker-muted font-bold"}>
                      {selectedEvent.actual || "—"}
                    </strong>
                  </div>
                </div>
              </div>

              <div className="p-3.5 rounded-xl bg-slate-100/90 dark:bg-bunker-900/80 border border-slate-300 dark:border-bunker-800 space-y-1.5 shadow-sm">
                <span className="text-[10px] uppercase font-bold text-slate-600 dark:text-bunker-muted">Etkilenen Pariteler</span>
                <div className="flex flex-wrap gap-1.5 pt-1">
                  {selectedEvent.affected_symbols.map((sym) => (
                    <span
                      key={sym}
                      className="px-2.5 py-1 rounded-lg text-[11px] font-black bg-cyan-100 dark:bg-cyan-500/20 text-cyan-800 dark:text-cyan-300 border border-cyan-400/60 dark:border-cyan-500/40 shadow-xs"
                    >
                      {sym}
                    </span>
                  ))}
                </div>
              </div>
            </div>

            {/* Gösterge Açıklaması (Varsa) */}
            {selectedEvent.comment && (
              <div className="p-3.5 rounded-xl bg-slate-100/90 dark:bg-bunker-900/60 border border-slate-300 dark:border-bunker-800 text-xs text-slate-700 dark:text-bunker-muted leading-relaxed shadow-sm">
                <strong className="text-slate-900 dark:text-white block text-[11px] font-bold mb-1">ℹ️ Gösterge Hakkında:</strong>
                {selectedEvent.comment}
              </div>
            )}

            {/* "NE OLURSA NE OLUR?" SENARYO MATRİSİ */}
            <div className="space-y-3">
              <div className="flex items-center gap-2">
                <span className="text-base">⚡</span>
                <h3 className="text-xs font-black uppercase tracking-wider text-amber-700 dark:text-amber-300">
                  {selectedEvent.scenario?.title || "Ne Olursa Ne Olur? Senaryo Analizi"}
                </h3>
              </div>

              <div className="space-y-2.5 text-xs">
                {/* OLUMLU / BEKLENTİ ÜZERİ */}
                <div className="p-3.5 rounded-xl bg-emerald-50 dark:bg-emerald-500/10 border border-emerald-400 dark:border-emerald-500/30 space-y-1 shadow-sm">
                  <div className="font-black text-emerald-800 dark:text-emerald-400 flex items-center gap-1.5">
                    <span>🟢</span>
                    <span>{selectedEvent.scenario?.bullish_trigger}</span>
                  </div>
                  <p className="text-[11px] text-emerald-900 dark:text-emerald-200/90 font-medium leading-relaxed pl-5">
                    {selectedEvent.scenario?.bullish_outcome}
                  </p>
                </div>

                {/* OLUMSUZ / BEKLENTİ ALTI */}
                <div className="p-3.5 rounded-xl bg-rose-50 dark:bg-rose-500/10 border border-rose-400 dark:border-rose-500/30 space-y-1 shadow-sm">
                  <div className="font-black text-rose-800 dark:text-rose-400 flex items-center gap-1.5">
                    <span>🔴</span>
                    <span>{selectedEvent.scenario?.bearish_trigger}</span>
                  </div>
                  <p className="text-[11px] text-rose-900 dark:text-rose-200/90 font-medium leading-relaxed pl-5">
                    {selectedEvent.scenario?.bearish_outcome}
                  </p>
                </div>

                {/* SCALPER İPUCU */}
                {selectedEvent.scenario?.scalper_tip && (
                  <div className="p-3.5 rounded-xl bg-cyan-50 dark:bg-cyan-950/30 border border-cyan-400 dark:border-cyan-500/30 text-[11px] text-cyan-950 dark:text-cyan-200 space-y-1 shadow-sm">
                    <span className="font-black text-cyan-800 dark:text-cyan-400 uppercase text-[10px] tracking-wider block">
                      🎯 Scalper Operatör Notu:
                    </span>
                    <p className="leading-relaxed font-semibold">
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
