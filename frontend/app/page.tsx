"use client";

// ============================================================================
// GÜNLÜK FOREX İŞLEM VE PERFORMANS KONSOLU (ANA SAYFA)
// 2026-10-07: Uygulama giriş ekranı. Günün otonom Forex scalper işlemlerinin
// başarısını, net kârlılığını (USD ve Pip), kazanma oranını (Win Rate),
// açık pozisyonlarını, sembol bazlı dağılımını ve INVESTING.COM EKONOMİK TAKVİM
// AÇIKLAMALARI VE "NE OLURSA NE OLUR" SENARYO ANALİZİNİ canlı olarak sunar.
// ============================================================================

import React, { useState, useEffect, useMemo, useCallback, useRef } from "react";
import Link from "next/link";
import { apiFetch } from "./lib/api";
import { usePolling } from "./lib/usePolling";
import {
  hasPublishedActual,
  outcomeSide,
  comparisonText,
  labelText,
  basisText,
  directionNoteText,
  isOutcomeVisibleNow,
  selectScenarioBranches,
  branchFallbackReason,
  selectTodaysPublished,
  type CalendarOutcome,
} from "./lib/calendarOutcome";
import EVShieldModal, { EVShieldStatusResponse } from "./forex/components/EVShieldModal";

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
  strategy_label?: string;
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
  balance: number | null;
  equity: number | null;
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
  // Veri açıklaması olup olmadığı ve gerçekleşen senaryo dalı — backend
  // `_update_event_dynamic_fields` her okuma yolunda doldurur. Eski önbellek
  // satırlarında bulunmayabilir (o yüzden opsiyonel).
  has_data?: boolean;
  outcome?: CalendarOutcome | null;
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

// Ekonomik takvim saatleri HER ZAMAN Türkiye saati (UTC+3) — kullanıcı kararı
// 2026-10-14: "haberlerde saat olarak UTC+3'e göre yazsın".
// Kaynak: olayın `date_iso` (UTC). Backend'in `date_str`i yedek olarak kalır.
function formatUtc3Date(iso?: string, fallback: string = ""): string {
  if (!iso) return fallback;
  try {
    const utcMs = new Date(iso).getTime();
    if (!Number.isFinite(utcMs)) return fallback;
    const TR_OFFSET_MS = 3 * 60 * 60 * 1000;
    const trMs = utcMs + TR_OFFSET_MS;
    const tr = new Date(trMs);
    const nowTr = new Date(Date.now() + TR_OFFSET_MS);
    const hh = String(tr.getUTCHours()).padStart(2, "0");
    const mm = String(tr.getUTCMinutes()).padStart(2, "0");
    const time = `${hh}:${mm}`;
    const daysTr = ["Pzt", "Sal", "Çar", "Per", "Cum", "Cmt", "Paz"];
    const monthsTr = ["", "Oca", "Şub", "Mar", "Nis", "May", "Haz", "Tem", "Ağu", "Eyl", "Eki", "Kas", "Ara"];
    const dayDiff = Math.round(
      (Date.UTC(tr.getUTCFullYear(), tr.getUTCMonth(), tr.getUTCDate()) -
        Date.UTC(nowTr.getUTCFullYear(), nowTr.getUTCMonth(), nowTr.getUTCDate())) / 86400000
    );
    if (dayDiff === 0) return `Bugün ${time}`;
    if (dayDiff === 1) return `Yarın ${time}`;
    if (dayDiff === -1) return `Dün ${time}`;
    return `${tr.getUTCDate()} ${monthsTr[tr.getUTCMonth() + 1]} (${daysTr[(tr.getUTCDay() + 6) % 7]}) ${time}`;
  } catch {
    return fallback;
  }
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
    const d3 = new Date(ms + 3 * 3600 * 1000);
    if (!isNaN(d3.getTime())) {
      const hh = String(d3.getUTCHours()).padStart(2, "0");
      const mm = String(d3.getUTCMinutes()).padStart(2, "0");
      const ss = String(d3.getUTCSeconds()).padStart(2, "0");
      return `${hh}:${mm}:${ss}`;
    }
  }
  if (!timeStr) return "—";
  try {
    const raw = String(timeStr).trim();
    if (raw.includes("UTC+3")) {
      const timeMatch = raw.match(/(\d{2}):(\d{2})(?::(\d{2}))?/);
      if (timeMatch) {
        return `${timeMatch[1]}:${timeMatch[2]}:${timeMatch[3] || "00"}`;
      }
    }
    if (raw.includes("UTC")) {
      const timeMatch = raw.match(/(\d{2}):(\d{2})(?::(\d{2}))?/);
      if (timeMatch) {
        const h = String((Number(timeMatch[1]) + 3) % 24).padStart(2, "0");
        return `${h}:${timeMatch[2]}:${timeMatch[3] || "00"}`;
      }
    }
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
    if (s.includes("UTC+3")) {
      return Date.UTC(Number(parts[1]), Number(parts[2]) - 1, Number(parts[3]), Number(parts[4]) - 3, Number(parts[5]), Number(parts[6] || 0));
    }
    return Date.UTC(Number(parts[1]), Number(parts[2]) - 1, Number(parts[3]), Number(parts[4]), Number(parts[5]), Number(parts[6] || 0));
  }
  const parsed = new Date(s).getTime();
  return isNaN(parsed) ? 0 : parsed;
}

// Bulunulan tarihteki saat 00:00:00 UTC+3 eşiğini verir (Türkiye saati UTC+3 takvimiyle tam uyumlu)
function getToday0001Cutoff(): number {
  const now = new Date();
  const utc3Ms = now.getTime() + 3 * 3600 * 1000;
  const d3 = new Date(utc3Ms);
  return Date.UTC(d3.getUTCFullYear(), d3.getUTCMonth(), d3.getUTCDate(), 0, 0, 0) - 3 * 3600 * 1000;
}

interface EventCountdownBadgeProps {
  dateIso?: string;
  dateStr?: string;
  status?: string;
  isPassed?: boolean;
  nowSec: number;
  className?: string;
}

// PERFORMANS (2026-10-08): Takvim tablosundaki her satır eskiden KENDİ 1 sn'lik
// interval'ini kuruyordu (EventCountdownBadge içinde); 20+ olay açıkken saniyede
// 20+ state güncellemesi tüm tabloyu yeniden render ediyordu. Artık tek paylaşımlı
// sayaç bir saniyede bir `nowSec`'i tazeler; geri sayım rozetleri onu okur.
const useSharedNowSec = (active: boolean): number => {
  const [nowSec, setNowSec] = useState<number>(() => Math.floor(Date.now() / 1000));
  useEffect(() => {
    if (!active) return;
    const t = setInterval(() => setNowSec(Math.floor(Date.now() / 1000)), 1000);
    return () => clearInterval(t);
  }, [active]);
  return nowSec;
};

const EventCountdownBadge = React.memo(function EventCountdownBadge({
  dateIso,
  dateStr,
  status,
  isPassed,
  nowSec,
  className = "",
}: EventCountdownBadgeProps) {
  const targetMs = useMemo(() => {
    if (dateStr) {
      const lower = dateStr.toLowerCase();
      const timeMatch = dateStr.match(/(\d{1,2}):(\d{2})/);
      if (timeMatch) {
        const h = parseInt(timeMatch[1], 10);
        const m = parseInt(timeMatch[2], 10);
        const d = new Date();
        d.setHours(h, m, 0, 0);
        if (lower.includes("yarın")) {
          d.setDate(d.getDate() + 1);
          return d.getTime();
        }
        if (lower.includes("dün")) {
          d.setDate(d.getDate() - 1);
          return d.getTime();
        }
        if (lower.includes("bugün")) {
          return d.getTime();
        }
      }
    }
    if (dateIso) {
      const parsed = new Date(dateIso).getTime();
      if (!isNaN(parsed) && parsed > 0) return parsed;
    }
    return null;
  }, [dateIso, dateStr]);

  if (!targetMs) return null;

  const diffSec = Math.floor((targetMs - nowSec * 1000) / 1000);

  // Açıklanmış olaylar
  if (status === "Açıklandı") {
    return (
      <span
        className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[9px] font-bold font-mono bg-emerald-100 dark:bg-emerald-500/15 text-emerald-800 dark:text-emerald-300 border border-emerald-300 dark:border-emerald-500/30 ${className}`}
        title="Olay açıklandı"
      >
        <span>✓</span>
        <span>Açıklandı</span>
      </span>
    );
  }

  // Saati geldi/geçti ama henüz veri gelmemiş
  if (diffSec <= 0) {
    return (
      <span
        className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[9px] font-bold font-mono bg-amber-100 dark:bg-amber-500/20 text-amber-800 dark:text-amber-300 border border-amber-300 dark:border-amber-400/50 ${className}`}
        title="Saati geldi / Veri açıklanıyor"
      >
        <span>⏱️</span>
        <span>Açıklanıyor</span>
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
        className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[9px] font-bold font-mono bg-cyan-100 dark:bg-cyan-950/80 text-cyan-800 dark:text-cyan-300 border border-cyan-300 dark:border-cyan-500/40 shadow-sm ${className}`}
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
        className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[9px] font-bold font-mono bg-amber-100 dark:bg-amber-500/20 text-amber-800 dark:text-amber-300 border border-amber-300 dark:border-amber-400/50 shadow-sm ${className}`}
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
      className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-[9px] font-black font-mono bg-rose-100 dark:bg-rose-500/25 text-rose-800 dark:text-rose-200 border border-rose-300 dark:border-rose-500/70 shadow-[0_0_12px_rgba(244,63,94,0.35)] animate-pulse ${className}`}
      title="KRİTİK: Açıklanmaya 1 saatten az süre kaldı!"
    >
      <span className="w-1.5 h-1.5 rounded-full bg-rose-500 animate-ping shrink-0" />
      <span className="tabular-nums tracking-wider font-extrabold">{formatted} kaldı</span>
    </span>
  );
});

export default function HomePage() {
  const [loading, setLoading] = useState<boolean>(true);
  const [homeDataError, setHomeDataError] = useState("");
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
    balance: null,
    equity: null,
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

  // Sembol EV Kalkanı Durumu ve Modalı
  const [evShieldModalOpen, setEvShieldModalOpen] = useState<boolean>(false);
  const [evShieldStatus, setEvShieldStatus] = useState<EVShieldStatusResponse | null>(null);

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
          balance: typeof statusRes?.balance === "number"
            ? statusRes.balance
            : (typeof reportRes.kpi?.balance === "number" ? reportRes.kpi.balance : prev.balance),
          equity: typeof statusRes?.equity === "number"
            ? statusRes.equity
            : (typeof reportRes.kpi?.equity === "number" ? reportRes.kpi.equity : prev.equity),
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
          balance: typeof statusRes.balance === "number" ? statusRes.balance : prev.balance,
          equity: typeof statusRes.equity === "number" ? statusRes.equity : prev.equity,
        }));
      }

      if (statusRes?.ev_shield) {
        setEvShieldStatus(statusRes.ev_shield);
      }

      setLastUpdated(new Date());
      setHomeDataError("");
    } catch (err) {
      const detail = err instanceof Error ? err.message : "Hesap verisi alınamadı";
      setHomeDataError(`Hesap verisi alınamadı: ${detail}`);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  // İlk Yükleme ve Ayrı Periyodik Döngüler
  // PERFORMANS (2026-10-08): Çıplak setInterval yerine usePolling — sekme arka
  // plana geçince döngü tamamen durur ve üst üste binen turlar engellenir.
  usePolling(() => fetchData(true), 4000);
  usePolling(() => fetchCalendar(false), 180000);

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

      const q = calendarSearch.trim().toLowerCase();
      if (q) {
        const blob = [
          item.title,
          item.original_title,
          item.currency,
          item.country,
          item.country_name,
          ...(item.affected_symbols || []),
        ]
          .filter(Boolean)
          .join(" ")
          .toLowerCase();
        if (!blob.includes(q)) return false;
      }

        // 2 Yıldızlı Konuşmaları ve Veri İçermeyen Olayları Filtrele (Kullanıcı Talebi)
      const stars = item.stars || (item.impact === "High" ? 3 : 2);
      if (stars === 2) {
        const t = (item.title || "").toLowerCase();
        const ot = (item.original_title || "").toLowerCase();
        const speechKeywords = [
          "speech",
          "speaks",
          "konuşma",
          "konuşması",
          "konuşuyor",
          "testimony",
          "statement",
          "panel",
          "briefing",
        ];
        if (speechKeywords.some((k) => t.includes(k) || ot.includes(k))) {
          return false;
        }

        const isMissingNum = (v?: string | null) =>
          !v || ["", "—", "-", "–", "n/a", "na", "null", "none"].includes(v.trim().toLowerCase());

        // Eğer ne beklenti ne önceki var ve açıklanan rakam da yoksa
        if (isMissingNum(item.forecast) && isMissingNum(item.previous) && !hasPublishedActual(item.actual)) {
          return false;
        }
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

  // PERFORMANS: Takvim geri sayımları için tek paylaşımlı saniyelik sayaç.
  const hasPendingEvents = filteredCalendarEvents.length > 0 || calendarEvents.length > 0;
  const nowSec = useSharedNowSec(hasPendingEvents);

  // Takvim olaylarının zaman damgasını hesaplayan yardımcı fonksiyon
  const getCalendarEventTime = useCallback((e: EconomicEvent, defaultVal = 0): number => {
    // 1. Eğer date_str içinde göreceli gün ("yarın", "dün", "bugün") ve saat varsa bu önceliklidir
    if (e.date_str) {
      const lower = e.date_str.toLowerCase();
      const m = e.date_str.match(/(\d{1,2}):(\d{2})/);
      if (m) {
        const h = parseInt(m[1], 10);
        const min = parseInt(m[2], 10);
        const d = new Date();
        d.setHours(h, min, 0, 0);
        if (lower.includes("yarın")) {
          d.setDate(d.getDate() + 1);
          return d.getTime();
        }
        if (lower.includes("dün")) {
          d.setDate(d.getDate() - 1);
          return d.getTime();
        }
        if (lower.includes("bugün")) {
          return d.getTime();
        }
      }
    }
    // 2. date_iso
    if (e.date_iso) {
      const t = new Date(e.date_iso).getTime();
      if (!isNaN(t) && t > 0) return t;
    }
    return defaultVal;
  }, []);

  // 1. SOL SÜTUN: Açıklanan Olaylar (En son açıklanan en üstte: b - a)
  const publishedCalendarEvents = useMemo(() => {
    return filteredCalendarEvents
      .filter((item) => hasPublishedActual(item.actual) || item.status === "Açıklandı")
      .sort((a, b) => getCalendarEventTime(b, 0) - getCalendarEventTime(a, 0));
  }, [filteredCalendarEvents, getCalendarEventTime]);

  // 2. SAĞ SÜTUN: Sıradaki Açıklanacak Olaylar (Kronolojik yaklaşan sıra: a - b)
  // KESİN KURAL: Yalnızca GELECEKTEKİ (saati henüz gelmemiş), açıklanmamış olaylar yer alır!
  // Dünden kalmış veya saati geçmiş veya açıklanmış olaylar burada ASLA yer alamaz!
  const upcomingCalendarEvents = useMemo(() => {
    const currentMs = nowSec * 1000;
    return filteredCalendarEvents
      .filter((item) => {
        // Zaten açıklanmışsa sıradaki olamaz
        if (hasPublishedActual(item.actual) || item.status === "Açıklandı") return false;

        // Dünden kalan eski bir olay ise sıradaki olamaz
        if (item.date_str && item.date_str.toLowerCase().includes("dün")) return false;

        // Zamanı ŞİMDİ veya geçmişse sıradaki olamaz (saati gelmiş/geçmiş olaylar burada duramaz)
        const eventMs = getCalendarEventTime(item, 0);
        if (eventMs <= currentMs) return false;

        return true;
      })
      .sort((a, b) => getCalendarEventTime(a, 9999999999999) - getCalendarEventTime(b, 9999999999999));
  }, [filteredCalendarEvents, getCalendarEventTime, nowSec]);

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



  // BUGÜN AÇIKLANAN VERİLER: veri içeren, sonucu belirlenmiş ve penceresi açık
  // (aynı UTC+3 günü) olaylar — her biri için ayrı kart. Kaynak `calendarEvents`
  // (filtrelenmemiş): amaç "günün sonuçları", filtrelenmiş tablo değil.
  // Pencere `nowSec` ile değerlendirilir; gün dönümünde YENİ İNTERVAL KURULMAZ,
  // kartlar kendiliğinden düşer (2026-10-08'de kaldırılan satır-başına interval
  // hatasının tekrarını önlemek için bilinçli olarak mevcut sayaç kullanılıyor).
  const nowMs = nowSec * 1000;
  const todaysPublishedEvents = useMemo(
    () => selectTodaysPublished(calendarEvents, nowMs),
    [calendarEvents, nowMs],
  );

  // MODAL TEK DAL: seçili olayın sonucu penceresi içindeyse yalnız gerçekleşen
  // senaryo gösterilir. Karar verilemediğinde (henüz açıklanmadı / eşitlik /
  // ayrıştırılamayan değer) `selectScenarioBranches` iki dalı da geri verir —
  // bilgi gizlenmez, eski davranış korunur.
  const selectedOutcomeSide = outcomeSide(selectedEvent);
  const selectedOutcomeVisible = isOutcomeVisibleNow(
    selectedEvent?.date_iso,
    nowMs,
    selectedEvent?.actual,
  );
  const scenarioBranches = selectScenarioBranches(selectedOutcomeSide, selectedOutcomeVisible);
  // Dal seçilemediyse NEDEN: "henüz açıklanmadı" ile "açıklandı ama eşit"
  // operatör için farklı şeylerdir, aynı mesajı basmak yanıltır.
  const selectedFallbackReason = branchFallbackReason(selectedEvent, nowMs);

  return (
    <div className="space-y-6 pb-16 font-mono text-white">
      {/* 1. ÜST BAŞLIK VE CANLI DURUM ÇUBUĞU */}
      <header className="p-5 sm:p-6 rounded-2xl bg-gradient-to-r from-blue-950/60 via-bunker-900/90 to-cyan-950/40 border border-blue-500/40 backdrop-blur-md shadow-2xl flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div className="flex items-center gap-3.5">
          <div className="w-14 h-14 rounded-2xl bg-cyan-100 dark:bg-gradient-to-br dark:from-blue-500/30 dark:to-cyan-500/20 border border-cyan-300 dark:border-cyan-400/40 flex items-center justify-center text-3xl shadow-sm dark:shadow-[0_0_20px_rgba(0,240,255,0.35)] shrink-0">
            📊
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-xl sm:text-2xl font-black text-slate-900 dark:text-white tracking-tight">
                GÜNLÜK FOREX PERFORMANSI
              </h1>
              <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-cyan-100 dark:bg-cyan-400/20 text-cyan-800 dark:text-cyan-300 border border-cyan-300 dark:border-cyan-400/30">
                BUGÜN
              </span>
            </div>
            <p className="text-xs text-slate-600 dark:text-bunker-muted mt-1">
              Otonom scalper işlemlerinin anlık başarı oranı, net kârlılık karnesi ve ekonomik takvim analizleri
            </p>
          </div>
        </div>

        <div className="flex items-center gap-3 self-end md:self-auto">
          <div className="flex flex-col text-right">
            <span className="text-[10px] text-slate-500 dark:text-bunker-muted">Son Güncelleme</span>
            <span className="text-xs font-bold text-cyan-700 dark:text-cyan-400">
              {lastUpdated ? lastUpdated.toLocaleTimeString("tr-TR") : "Yükleniyor…"}
            </span>
          </div>

          <button
            type="button"
            onClick={() => setEvShieldModalOpen(true)}
            className={`px-3 py-2 rounded-xl border text-xs font-bold transition-all shadow-xs active:scale-95 flex items-center gap-1.5 ${
              (evShieldStatus?.blocked_count ?? 0) > 0
                ? "bg-rose-500/20 border-rose-500/50 text-rose-700 dark:text-rose-300 ring-2 ring-rose-500/40 animate-pulse"
                : "bg-slate-100 dark:bg-bunker-950/80 border-slate-300 dark:border-cyan-500/30 hover:border-cyan-500 text-slate-800 dark:text-cyan-300"
            }`}
            title="Sembol EV Kalkanı Listesi ve Muafiyet Yönetimi"
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
            onClick={() => fetchData(false)}
            disabled={refreshing}
            className="px-3 py-2 rounded-xl bg-slate-100 dark:bg-bunker-950/80 border border-slate-300 dark:border-cyan-500/30 hover:border-cyan-500 text-slate-800 dark:text-cyan-300 text-xs font-bold transition-all shadow-xs dark:shadow-[0_0_10px_rgba(0,240,255,0.15)] active:scale-95 flex items-center gap-1.5 disabled:opacity-50"
          >
            <span className={refreshing ? "animate-spin" : ""}>🔄</span>
            <span>Yenile</span>
          </button>
        </div>
      </header>

      {/* EV KALKANI UYARI BANNERI */}
      {evShieldStatus && evShieldStatus.blocked_count > 0 && (
        <div className="p-4 rounded-2xl border border-rose-400 dark:border-rose-500/50 bg-rose-50/95 dark:bg-gradient-to-r dark:from-rose-950/60 dark:via-bunker-900/95 dark:to-amber-950/40 flex flex-col sm:flex-row sm:items-center justify-between gap-3 shadow-xl ring-1 ring-rose-400/40 transition-all">
          <div className="flex items-center gap-3.5">
            <div className="w-11 h-11 rounded-xl bg-rose-500/20 border border-rose-500/40 flex items-center justify-center text-xl shrink-0 animate-pulse shadow-inner">
              🛡️
            </div>
            <div>
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-xs font-black uppercase tracking-wider text-rose-800 dark:text-rose-300">
                  Sembol EV Kalkanı Devrede
                </span>
                <span className="px-2 py-0.5 rounded text-[10px] font-black bg-rose-600 text-white shadow-xs">
                  {evShieldStatus.blocked_count} Sembol Dinlenmede
                </span>
              </div>
              <p className="text-xs text-slate-800 dark:text-slate-200 font-medium mt-0.5">
                {evShieldStatus.symbols
                  .filter((s) => s.is_blocked)
                  .map((s) => `${s.display} (${s.net_usd < 0 ? `-$${Math.abs(s.net_usd).toFixed(2)}` : `$${s.net_usd}`})`)
                  .join(", ")}{" "}
                akut zarar nedeniyle korumaya alındı. Dilerseniz bugün için muaf tutabilirsiniz.
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={() => setEvShieldModalOpen(true)}
            className="px-4 py-2 rounded-xl text-xs font-black bg-rose-600 hover:bg-rose-500 text-white shadow-md transition-all flex items-center gap-1.5 shrink-0 self-start sm:self-auto active:scale-95"
          >
            <span>🛡️ Kalkanı İncele &amp; Bugün İzin Ver</span>
            <span>↗</span>
          </button>
        </div>
      )}

      {/* 2. GÜNÜN KARNESİ: ANA METRİKLER (KPI CARDS) */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 px-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="w-2.5 h-2.5 rounded-full bg-emerald-500 animate-pulse" />
          <h2 className="text-sm font-bold uppercase tracking-wider text-slate-900 dark:text-white">Günün Başarı Metrikleri</h2>
          <span className="text-[10px] px-2 py-0.5 rounded-full bg-cyan-100 dark:bg-cyan-950/80 border border-cyan-300 dark:border-cyan-500/30 text-cyan-800 dark:text-cyan-300 font-semibold">
            Her Gece 00:00'da Otomatik Sıfırlanır (UTC+3)
          </span>
        </div>
        <Link
          href="/forex/reports"
          className="text-xs text-cyan-700 dark:text-cyan-400 hover:text-cyan-800 dark:hover:text-cyan-300 hover:underline flex items-center gap-1 font-semibold transition-colors"
        >
          <span>📅 Geçmiş Tarihli Kayıtları İncele</span>
          <span>→</span>
        </Link>
      </div>

      <section className="grid grid-cols-2 lg:grid-cols-4 gap-3 sm:gap-4" aria-label="Günün KPI Göstergeleri">
        {/* KART 1: GÜNLÜK NET PNL */}
        <div className={`p-4 sm:p-5 rounded-2xl border backdrop-blur-md shadow-xl transition-all ${
          isNetProfit
            ? "border-emerald-300 dark:border-emerald-500/40 bg-emerald-50/80 dark:bg-gradient-to-br dark:from-emerald-950/40 dark:via-bunker-900/80 dark:to-bunker-950/90 shadow-[0_4px_20px_rgba(16,185,129,0.15)]"
            : "border-rose-300 dark:border-rose-500/40 bg-rose-50/80 dark:bg-gradient-to-br dark:from-rose-950/40 dark:via-bunker-900/80 dark:to-bunker-950/90 shadow-[0_4px_20px_rgba(244,63,94,0.15)]"
        }`}>
          <div className="flex items-center justify-between">
            <span className="text-xs font-bold uppercase tracking-wider text-slate-600 dark:text-bunker-muted">Günün Net Kârı</span>
            <span className="text-lg">{isNetProfit ? "💰" : "📉"}</span>
          </div>
          <div className="mt-2.5">
            <div className={`text-2xl sm:text-3xl font-black tracking-tight ${isNetProfit ? "text-emerald-700 dark:text-emerald-400" : "text-rose-700 dark:text-rose-400"}`}>
              {kpi.total_pnl_usd >= 0 ? `+$${kpi.total_pnl_usd.toFixed(2)}` : `-$${Math.abs(kpi.total_pnl_usd).toFixed(2)}`}
            </div>
            <div className="mt-1 flex items-center justify-between text-[11px] text-slate-600 dark:text-bunker-muted">
              <span>Toplam Pip:</span>
              <span className={`font-bold ${((kpi.total_pnl_pips ?? 0) >= 0) ? "text-emerald-800 dark:text-emerald-300" : "text-rose-800 dark:text-rose-300"}`}>
                {(kpi.total_pnl_pips ?? 0) >= 0 ? `+${(kpi.total_pnl_pips ?? 0).toFixed(1)}` : (kpi.total_pnl_pips ?? 0).toFixed(1)} pip
              </span>
            </div>
          </div>
        </div>

        {/* KART 2: BAŞARI ORANI (WIN RATE) */}
        <div className="p-4 sm:p-5 rounded-2xl border border-cyan-300 dark:border-cyan-500/40 bg-cyan-50/60 dark:bg-gradient-to-br dark:from-cyan-950/30 dark:via-bunker-900/80 dark:to-bunker-950/90 shadow-xl dark:shadow-[0_4px_20px_rgba(6,182,212,0.1)]">
          <div className="flex items-center justify-between">
            <span className="text-xs font-bold uppercase tracking-wider text-cyan-800 dark:text-cyan-300">Başarı Oranı (Win Rate)</span>
            <span className="text-lg">🎯</span>
          </div>
          <div className="mt-2.5">
            <div className="text-2xl sm:text-3xl font-black text-slate-900 dark:text-white tracking-tight flex items-baseline gap-1.5">
              <span>%{winRate.toFixed(1)}</span>
            </div>
            <div className="mt-1 flex items-center justify-between text-[11px] text-slate-600 dark:text-bunker-muted">
              <span className="text-emerald-700 dark:text-emerald-400 font-bold">{kpi.wins} Kazanılan</span>
              <span className="text-slate-400 dark:text-bunker-500">/</span>
              <span className="text-rose-700 dark:text-rose-400 font-bold">{kpi.losses} Kayıp</span>
            </div>
          </div>
        </div>

        {/* KART 3: KÂR FAKTÖRÜ (PROFIT FACTOR) */}
        <div className="p-4 sm:p-5 rounded-2xl border border-purple-300 dark:border-purple-500/40 bg-purple-50/70 dark:bg-gradient-to-br dark:from-purple-950/30 dark:via-bunker-900/80 dark:to-bunker-950/90 shadow-xl">
          <div className="flex items-center justify-between">
            <span className="text-xs font-bold uppercase tracking-wider text-purple-800 dark:text-purple-300">Kâr Faktörü (PF)</span>
            <span className="text-lg">⚡</span>
          </div>
          <div className="mt-2.5">
            <div className="text-2xl sm:text-3xl font-black text-purple-950 dark:text-purple-200 tracking-tight">
              {kpi.profit_factor_infinite ? "∞ (Kayıpsız)" : (kpi.profit_factor && kpi.profit_factor > 0 ? kpi.profit_factor.toFixed(2) : "—")}
            </div>
            <div className="mt-1 flex items-center justify-between text-[11px] text-slate-600 dark:text-bunker-muted">
              <span>Toplam İşlem:</span>
              <span className="text-slate-900 dark:text-white font-bold">{kpi.total_trades} adet</span>
            </div>
          </div>
        </div>

        {/* KART 4: BAKİYE VE CANLI VARLIK (EQUITY) */}
        <div className="p-4 sm:p-5 rounded-2xl border border-amber-300 dark:border-amber-500/40 bg-amber-50/70 dark:bg-gradient-to-br dark:from-amber-950/25 dark:via-bunker-900/80 dark:to-bunker-950/90 shadow-xl">
          <div className="flex items-center justify-between">
            <span className="text-xs font-bold uppercase tracking-wider text-amber-800 dark:text-amber-300">Varlık (Equity) &amp; Bakiye</span>
            <span className="text-lg">💼</span>
          </div>
          <div className="mt-2.5">
            <div className="text-2xl sm:text-3xl font-black text-amber-950 dark:text-amber-200 tracking-tight">
              {kpi.equity == null && kpi.balance == null
                ? "—"
                : `$${Number(kpi.equity ?? kpi.balance).toFixed(2)}`}
            </div>
            <div className="mt-1 flex items-center justify-between text-[11px] text-slate-600 dark:text-bunker-muted">
              <span>Bakiye:</span>
              <span className="text-slate-900 dark:text-white font-bold">
                {kpi.balance == null ? "—" : `$${kpi.balance.toFixed(2)}`}
              </span>
            </div>
            {homeDataError && (
              <p role="alert" className="mt-2 text-[11px] font-bold text-rose-600 dark:text-rose-300">{homeDataError}</p>
            )}
          </div>
        </div>
      </section>

      {/* 3. PARİTE BAZINDA GÜNLÜK KÂR / ZARAR KATKISI */}
      <section className="p-5 rounded-2xl bg-white dark:bg-bunker-900/80 border border-slate-300 dark:border-bunker-800 shadow-xl space-y-3">
        <div className="flex items-center justify-between flex-wrap gap-2">
          <div className="flex items-center gap-2">
            <span className="text-base">🪙</span>
            <h2 className="text-sm font-bold text-slate-900 dark:text-white uppercase tracking-wider">
              Parite Bazında Günlük Kâr / Zarar Katkısı
            </h2>
          </div>
          {symbolStats.length > 0 && (
            <span className="text-xs text-slate-600 dark:text-bunker-muted font-medium">
              {symbolStats.length} Aktif Parite
            </span>
          )}
        </div>

        {symbolStats.length === 0 ? (
          <div className="p-4 text-center text-xs text-slate-500 dark:text-bunker-muted rounded-xl bg-slate-50 dark:bg-bunker-950/40 border border-slate-200 dark:border-bunker-800">
            Bugün henüz kapanan parite işlemi bulunmuyor.
          </div>
        ) : (
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-2.5">
            {symbolStats.map((item) => {
              const pos = item.pnl_usd >= 0;
              return (
                <div
                  key={item.symbol}
                  className={`p-3 rounded-xl transition-all space-y-1 border ${
                    pos
                      ? "bg-slate-50 dark:bg-bunker-950/70 border-emerald-300/60 dark:border-emerald-500/30 hover:border-emerald-500"
                      : "bg-slate-50 dark:bg-bunker-950/70 border-rose-300/60 dark:border-rose-500/30 hover:border-rose-500"
                  }`}
                >
                  <div className="flex justify-between items-center text-xs font-bold text-slate-900 dark:text-white">
                    <span>{item.symbol}</span>
                    <span className="text-[10px] text-slate-500 dark:text-bunker-muted font-mono">{item.trades} işlem</span>
                  </div>
                  <div className={`text-sm font-black ${pos ? "text-emerald-700 dark:text-emerald-400" : "text-rose-700 dark:text-rose-400"}`}>
                    {pos ? `+$${item.pnl_usd.toFixed(2)}` : `-$${Math.abs(item.pnl_usd).toFixed(2)}`}
                  </div>
                  <div className="text-[10px] text-slate-600 dark:text-bunker-muted flex justify-between">
                    <span>%{item.trades > 0 ? ((item.wins / item.trades) * 100).toFixed(0) : 0} Win</span>
                    <span className={item.pnl_pips >= 0 ? "text-emerald-700 dark:text-emerald-300 font-bold" : "text-rose-700 dark:text-rose-300 font-bold"}>
                      {item.pnl_pips >= 0 ? `+${item.pnl_pips.toFixed(0)}` : item.pnl_pips.toFixed(0)}p
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </section>

      {/* 4. GÜNÜN İŞLEM BAŞARISI DAĞILIMI (GÜNÜN ÖNE ÇIKANLARI KALDIRILDI, DÜZGÜN VE MODERN TASARIM) */}
      <section className="p-5 sm:p-6 rounded-2xl bg-white dark:bg-bunker-900/80 border border-slate-300 dark:border-bunker-800 shadow-xl space-y-4">
        {/* Üst Başlık ve Başarı Oranı Rozeti */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-slate-200 dark:border-bunker-800 pb-3">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-tr from-emerald-500/20 to-teal-500/20 border border-emerald-400/40 flex items-center justify-center text-xl shrink-0">
              📈
            </div>
            <div>
              <div className="flex items-center gap-2 flex-wrap">
                <h2 className="text-sm sm:text-base font-bold text-slate-900 dark:text-white uppercase tracking-wider">
                  Günün İşlem Başarısı Dağılımı
                </h2>
                <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-slate-100 dark:bg-bunker-950 text-slate-700 dark:text-bunker-muted border border-slate-200 dark:border-bunker-800">
                  Bugün 00:01 Sonrası
                </span>
              </div>
              <p className="text-[11px] text-slate-600 dark:text-bunker-muted mt-0.5">
                Kapanan scalper işlemlerinin net kârlılık, başarı oranı ve brüt hacim dağılımı.
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2 flex-wrap">
            <span className="px-3 py-1 rounded-xl text-xs font-black bg-slate-100 dark:bg-bunker-950 text-slate-800 dark:text-slate-200 border border-slate-300 dark:border-bunker-800">
              Toplam {kpi.total_trades} İşlem
            </span>
            <span
              className={`px-3 py-1 rounded-xl text-xs font-black border ${
                winRate >= 50
                  ? "bg-emerald-100 dark:bg-emerald-500/20 text-emerald-800 dark:text-emerald-300 border-emerald-300 dark:border-emerald-500/40"
                  : "bg-amber-100 dark:bg-amber-500/20 text-amber-800 dark:text-amber-300 border-amber-300 dark:border-amber-500/40"
              }`}
            >
              %{winRate.toFixed(1)} Kazanma Oranı
            </span>
          </div>
        </div>

        {/* 3 Ana Metrik Kartı: Kazanılan | Kaybedilen | Kâr Faktörü & Net */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3.5">
          {/* Kazanılan İşlemler */}
          <div className="p-3.5 rounded-xl bg-emerald-50/70 dark:bg-emerald-950/20 border border-emerald-300/80 dark:border-emerald-500/30 space-y-1.5">
            <div className="flex items-center justify-between">
              <span className="text-xs font-bold text-emerald-800 dark:text-emerald-400 flex items-center gap-1.5">
                <span>✅</span> Kazanılan (WIN)
              </span>
              <span className="text-xs font-black text-emerald-700 dark:text-emerald-300 bg-emerald-100 dark:bg-emerald-500/20 px-2 py-0.5 rounded-full font-mono">
                {kpi.wins} İşlem
              </span>
            </div>
            <div className="flex items-baseline justify-between pt-1">
              <div>
                <div className="text-[10px] text-slate-500 dark:text-bunker-muted">Brüt Kâr:</div>
                <div className="text-base font-black text-emerald-700 dark:text-emerald-400 font-mono">
                  +${(kpi.gross_profit_usd ?? 0).toFixed(2)}
                </div>
              </div>
              <div className="text-right">
                <div className="text-[10px] text-slate-500 dark:text-bunker-muted">Oran:</div>
                <div className="text-sm font-bold text-emerald-700 dark:text-emerald-300 font-mono">
                  %{winRate.toFixed(1)}
                </div>
              </div>
            </div>
          </div>

          {/* Kaybedilen İşlemler */}
          <div className="p-3.5 rounded-xl bg-rose-50/70 dark:bg-rose-950/20 border border-rose-300/80 dark:border-rose-500/30 space-y-1.5">
            <div className="flex items-center justify-between">
              <span className="text-xs font-bold text-rose-800 dark:text-rose-400 flex items-center gap-1.5">
                <span>❌</span> Kayıp (LOSS)
              </span>
              <span className="text-xs font-black text-rose-700 dark:text-rose-300 bg-rose-100 dark:bg-rose-500/20 px-2 py-0.5 rounded-full font-mono">
                {kpi.losses} İşlem
              </span>
            </div>
            <div className="flex items-baseline justify-between pt-1">
              <div>
                <div className="text-[10px] text-slate-500 dark:text-bunker-muted">Brüt Zarar:</div>
                <div className="text-base font-black text-rose-700 dark:text-rose-400 font-mono">
                  -${Math.abs(kpi.gross_loss_usd ?? 0).toFixed(2)}
                </div>
              </div>
              <div className="text-right">
                <div className="text-[10px] text-slate-500 dark:text-bunker-muted">Oran:</div>
                <div className="text-sm font-bold text-rose-700 dark:text-rose-300 font-mono">
                  %{(kpi.total_trades > 0 ? (kpi.losses / kpi.total_trades) * 100 : 0).toFixed(1)}
                </div>
              </div>
            </div>
          </div>

          {/* Kâr Faktörü & Net Sonuç */}
          <div className="p-3.5 rounded-xl bg-indigo-50/70 dark:bg-indigo-950/20 border border-indigo-300/80 dark:border-indigo-500/30 space-y-1.5">
            <div className="flex items-center justify-between">
              <span className="text-xs font-bold text-indigo-800 dark:text-indigo-400 flex items-center gap-1.5">
                <span>⚡</span> Kâr Faktörü (PF)
              </span>
              <span className="text-xs font-black text-indigo-700 dark:text-indigo-300 bg-indigo-100 dark:bg-indigo-500/20 px-2 py-0.5 rounded-full font-mono">
                {kpi.profit_factor_infinite ? "∞" : (kpi.profit_factor ?? 0).toFixed(2)}
              </span>
            </div>
            <div className="flex items-baseline justify-between pt-1">
              <div>
                <div className="text-[10px] text-slate-500 dark:text-bunker-muted">Net K/Z:</div>
                <div className={`text-base font-black font-mono ${isNetProfit ? "text-emerald-700 dark:text-emerald-400" : "text-rose-700 dark:text-rose-400"}`}>
                  {isNetProfit ? `+$${kpi.total_pnl_usd.toFixed(2)}` : `-$${Math.abs(kpi.total_pnl_usd).toFixed(2)}`}
                </div>
              </div>
              <div className="text-right">
                <div className="text-[10px] text-slate-500 dark:text-bunker-muted">Net Pip:</div>
                <div className={`text-sm font-bold font-mono ${(kpi.total_pnl_pips ?? 0) >= 0 ? "text-emerald-700 dark:text-emerald-300" : "text-rose-700 dark:text-rose-300"}`}>
                  {(kpi.total_pnl_pips ?? 0) >= 0 ? `+${(kpi.total_pnl_pips ?? 0).toFixed(1)}` : (kpi.total_pnl_pips ?? 0).toFixed(1)}p
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* Kalın ve Şık İlerleme / Başarı Çubuğu */}
        <div className="space-y-1.5">
          <div className="flex justify-between items-center text-xs font-bold">
            <span className="text-emerald-700 dark:text-emerald-400 flex items-center gap-1">
              <span>✓</span> %{winRate.toFixed(1)} Kazanma ({kpi.wins} İşlem)
            </span>
            <span className="text-rose-700 dark:text-rose-400 flex items-center gap-1">
              <span>✕</span> %{(kpi.total_trades > 0 ? (kpi.losses / kpi.total_trades) * 100 : 0).toFixed(1)} Kayıp ({kpi.losses} İşlem)
            </span>
          </div>

          <div className="w-full h-5 rounded-full bg-slate-200 dark:bg-bunker-950 overflow-hidden flex border border-slate-300 dark:border-bunker-800 shadow-inner">
            <div
              style={{ width: `${kpi.total_trades > 0 ? (kpi.wins / kpi.total_trades) * 100 : 0}%` }}
              className="h-full bg-gradient-to-r from-emerald-500 to-teal-400 transition-all duration-500 flex items-center justify-center text-[10px] font-black text-slate-900 shadow-sm"
              title={`${kpi.wins} Kazanılan İşlem (%${winRate.toFixed(1)})`}
            >
              {kpi.wins > 0 && `${kpi.wins} WIN`}
            </div>
            <div
              style={{ width: `${kpi.total_trades > 0 ? (kpi.losses / kpi.total_trades) * 100 : 0}%` }}
              className="h-full bg-gradient-to-r from-rose-500 to-red-600 transition-all duration-500 flex items-center justify-center text-[10px] font-black text-white shadow-sm"
              title={`${kpi.losses} Kayıp İşlem`}
            >
              {kpi.losses > 0 && `${kpi.losses} LOSS`}
            </div>
          </div>
        </div>

        {/* Hızlı Aksiyon Bağlantıları */}
        <div className="pt-2.5 border-t border-slate-200 dark:border-bunker-800 flex flex-wrap items-center gap-2">
          <Link
            href="/forex/portfolio"
            className="px-3 py-1.5 rounded-xl bg-blue-100 dark:bg-blue-500/10 border border-blue-300 dark:border-blue-500/30 text-blue-900 dark:text-blue-300 text-xs hover:bg-blue-200 dark:hover:bg-blue-500/20 transition-all font-bold flex items-center gap-1.5 shadow-sm"
          >
            <span>💼</span> Forex Portföy
          </Link>
          <Link
            href="/forex/btc-gold"
            className="px-3 py-1.5 rounded-xl bg-amber-100 dark:bg-amber-500/10 border border-amber-300 dark:border-amber-500/30 text-amber-900 dark:text-amber-300 text-xs hover:bg-amber-200 dark:hover:bg-amber-500/20 transition-all font-bold flex items-center gap-1.5 shadow-sm"
          >
            <span>🥇</span> BTC + Altın
          </Link>
          <Link
            href="/forex"
            className="px-3 py-1.5 rounded-xl bg-cyan-100 dark:bg-cyan-500/10 border border-cyan-300 dark:border-cyan-500/30 text-cyan-900 dark:text-cyan-300 text-xs hover:bg-cyan-200 dark:hover:bg-cyan-500/20 transition-all font-bold flex items-center gap-1.5 shadow-sm"
          >
            <span>📡</span> Radar
          </Link>
          <Link
            href="/forex/reports"
            className="px-3 py-1.5 rounded-xl bg-purple-100 dark:bg-purple-500/10 border border-purple-300 dark:border-purple-500/30 text-purple-900 dark:text-purple-300 text-xs hover:bg-purple-200 dark:hover:bg-purple-500/20 transition-all font-bold flex items-center gap-1.5 shadow-sm"
          >
            <span>📋</span> Detaylı Raporlar
          </Link>
          <Link
            href="/settings"
            className="px-3 py-1.5 rounded-xl bg-slate-100 dark:bg-bunker-800/80 border border-slate-300 dark:border-bunker-700 text-slate-700 dark:text-bunker-muted hover:text-slate-900 dark:hover:text-white text-xs transition-all font-bold flex items-center gap-1.5 ml-auto shadow-sm"
          >
            <span>⚙️</span> Ayarlar
          </Link>
        </div>
      </section>

      {/* 4. EKONOMİK TAKVİM VE MAKRO AÇIKLAMA ANALİZİ (INVESTING.COM 2 & 3 YILDIZ) */}
      <section className="p-5 sm:p-6 rounded-2xl bg-white dark:bg-gradient-to-r dark:from-slate-900/90 dark:via-bunker-900/95 dark:to-indigo-950/60 border border-slate-300 dark:border-indigo-500/30 shadow-2xl space-y-4">
        {/* Başlık ve Aksiyon Barı */}
        <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-3 border-b border-slate-200 dark:border-bunker-800 pb-3">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-indigo-100 dark:bg-indigo-500/20 border border-indigo-300 dark:border-indigo-400/40 flex items-center justify-center text-xl shrink-0">
              📅
            </div>
            <div>
              <div className="flex items-center gap-2 flex-wrap">
                <h2 className="text-sm sm:text-base font-black text-slate-900 dark:text-white tracking-wide uppercase">
                  Ekonomik Takvim (2 &amp; 3 Yıldızlı Kritik Veriler)
                </h2>
                <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-amber-100 dark:bg-amber-500/20 text-amber-900 dark:text-amber-300 border border-amber-300 dark:border-amber-500/40">
                  ⭐⭐ / ⭐⭐⭐ Kritik Volatilite
                </span>
                <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-emerald-100 dark:bg-emerald-500/20 text-emerald-900 dark:text-emerald-300 border border-emerald-300 dark:border-emerald-500/40">
                  ⚡ Otomatik Senkronize (3 Saatte Bir)
                </span>
              </div>
              <p className="text-[11px] text-slate-600 dark:text-bunker-muted mt-0.5">
                Piyasayı hareketlendiren 2 ve 3 yıldızlı kritik makro açıklamalar gün boyunca takip edilir; veritabanından anında sunulur.
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2 flex-wrap">
            <button
              type="button"
              onClick={() => fetchCalendar(true)}
              disabled={refreshingCalendar}
              className="px-3 py-1.5 rounded-xl text-xs font-bold bg-indigo-100 dark:bg-indigo-500/20 text-indigo-950 dark:text-indigo-300 border border-indigo-300 dark:border-indigo-500/40 hover:bg-indigo-200 dark:hover:bg-indigo-500/30 transition-all flex items-center gap-1.5 disabled:opacity-50"
            >
              <span className={refreshingCalendar ? "animate-spin" : ""}>🔄</span>
              <span>{refreshingCalendar ? "Yenileniyor…" : "Takvimi Yenile"}</span>
            </button>

            {calendarLastUpdated && (
              <span className="text-[10px] text-slate-500 dark:text-bunker-muted hidden md:inline">
                {calendarLastUpdated.toLocaleTimeString("tr-TR", { hour: "2-digit", minute: "2-digit" })}
              </span>
            )}
          </div>
        </div>

        {/* Filtre ve Arama Kontrolleri */}
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-3 pt-1">
          {/* Yıldız Filtreleri */}
          <div className="flex items-center gap-1.5 flex-wrap">
            <span className="text-[11px] text-slate-700 dark:text-bunker-muted font-bold mr-1">Önem:</span>
            <button
              type="button"
              onClick={() => setCalendarFilterStars("ALL")}
              className={`px-2.5 py-1 rounded-lg text-xs font-bold transition-all ${
                calendarFilterStars === "ALL"
                  ? "bg-cyan-600 text-white border border-cyan-600 shadow-sm"
                  : "bg-slate-100 dark:bg-bunker-900 text-slate-700 dark:text-bunker-muted border border-slate-300 dark:border-bunker-800 hover:text-slate-900 dark:hover:text-white"
              }`}
            >
              Tümü ({calendarEvents.length})
            </button>
            <button
              type="button"
              onClick={() => setCalendarFilterStars(3)}
              className={`px-2.5 py-1 rounded-lg text-xs font-bold transition-all ${
                calendarFilterStars === 3
                  ? "bg-rose-600 text-white border border-rose-600 shadow-sm"
                  : "bg-slate-100 dark:bg-bunker-900 text-slate-700 dark:text-bunker-muted border border-slate-300 dark:border-bunker-800 hover:text-rose-700 dark:hover:text-rose-300"
              }`}
            >
              ⭐⭐⭐ 3 Yıldız ({calendarEvents.filter((x) => (x.stars || (x.impact === "High" ? 3 : 2)) === 3).length})
            </button>
            <button
              type="button"
              onClick={() => setCalendarFilterStars(2)}
              className={`px-2.5 py-1 rounded-lg text-xs font-bold transition-all ${
                calendarFilterStars === 2
                  ? "bg-amber-600 text-white border border-amber-600 shadow-sm"
                  : "bg-slate-100 dark:bg-bunker-900 text-slate-700 dark:text-bunker-muted border border-slate-300 dark:border-bunker-800 hover:text-amber-700 dark:hover:text-amber-300"
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
                        ? "bg-indigo-600 text-white font-black shadow-sm"
                        : "bg-slate-100 dark:bg-bunker-900/80 text-slate-700 dark:text-bunker-muted hover:text-slate-900 dark:hover:text-white border border-slate-200 dark:border-transparent"
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
              className="px-2.5 py-1 rounded-lg bg-white dark:bg-bunker-950 border border-slate-300 dark:border-bunker-800 text-xs text-slate-900 dark:text-white placeholder-slate-400 dark:placeholder-bunker-muted focus:border-cyan-500 focus:outline-none w-36 sm:w-44"
            />
          </div>
        </div>

        {/* İKİ SÜTUNLU EKONOMİK TAKVİM (SOL: EN SON AÇIKLANANLAR EN ÜSTTE, SAĞ: SIRADAKİ AÇIKLANACAKLAR) */}
        {loadingCalendar && calendarEvents.length === 0 ? (
          <div className="p-8 text-center text-xs text-slate-600 dark:text-bunker-muted animate-pulse font-mono rounded-xl bg-slate-50 dark:bg-bunker-950/50 border border-slate-300 dark:border-bunker-800">
            2 ve 3 yıldızlı kritik ekonomik takvim verileri ve senaryoları yükleniyor…
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
          <div className="grid grid-cols-1 xl:grid-cols-2 gap-4 sm:gap-5 pt-1">
            {/* 1. SOL SÜTUN: AÇIKLANANLAR (EN SON AÇIKLANAN EN ÜSTTE) */}
            <div className="flex flex-col space-y-3">
              <div className="flex items-center justify-between px-3.5 py-2.5 rounded-xl bg-emerald-50/80 dark:bg-emerald-950/30 border border-emerald-300 dark:border-emerald-500/30">
                <div className="flex items-center gap-2">
                  <span className="w-2.5 h-2.5 rounded-full bg-emerald-500 animate-pulse" />
                  <h3 className="text-xs font-black uppercase tracking-wider text-emerald-900 dark:text-emerald-300 flex items-center gap-1.5">
                    <span>📢</span> Açıklanan Veriler
                  </h3>
                </div>
                <div className="flex items-center gap-2">
                  <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-emerald-100 dark:bg-emerald-500/20 text-emerald-800 dark:text-emerald-300 border border-emerald-300 dark:border-emerald-500/30">
                    En son açıklanan en üstte
                  </span>
                  <span className="text-[11px] font-bold font-mono text-emerald-900 dark:text-emerald-400">
                    ({publishedCalendarEvents.length})
                  </span>
                </div>
              </div>

              <div className="max-h-[750px] overflow-y-auto space-y-3 pr-1 scrollbar-thin">
                {publishedCalendarEvents.length === 0 ? (
                  <div className="p-8 text-center text-xs text-slate-500 dark:text-bunker-muted rounded-xl bg-slate-50 dark:bg-bunker-950/40 border border-slate-200 dark:border-bunker-800">
                    Bugün henüz açıklanmış makro veri bulunmuyor veya filtrelere uyan sonuç yok.
                  </div>
                ) : (
                  publishedCalendarEvents.map((item) => {
                    const side = outcomeSide(item);
                    const isBull = side === "bullish";
                    const isBear = side === "bearish";
                    const cmp = comparisonText(item);
                    const label = labelText(item);
                    const basis = basisText(item);
                    const dirNote = directionNoteText(item);
                    const branchOutcome = isBull
                      ? item.scenario?.bullish_outcome
                      : isBear
                      ? item.scenario?.bearish_outcome
                      : item.scenario?.summary_short || item.scenario?.title;
                    const is3Stars = (item.stars || (item.impact === "High" ? 3 : 2)) === 3;

                    return (
                      <div
                        key={`pub-${item.id}`}
                        onClick={() => setSelectedEvent(item)}
                        className={`p-3.5 rounded-xl border transition-all cursor-pointer shadow-sm hover:shadow-md space-y-2.5 ${
                          isBull
                            ? "bg-white dark:bg-bunker-900/90 border-emerald-400 dark:border-emerald-500/40 hover:border-emerald-500"
                            : isBear
                            ? "bg-white dark:bg-bunker-900/90 border-rose-400 dark:border-rose-500/40 hover:border-rose-500"
                            : "bg-white dark:bg-bunker-900/90 border-slate-300 dark:border-bunker-800 hover:border-cyan-500/50"
                        }`}
                        title="Detaylı kartı ve senaryoyu açmak için tıklayın"
                      >
                        {/* Başlık Satırı */}
                        <div className="flex items-start justify-between gap-2">
                          <div className="min-w-0 space-y-0.5">
                            <div className="flex items-center gap-1.5 text-[11px] text-slate-600 dark:text-slate-400 font-bold flex-wrap">
                              <span>{item.flag || "🌐"}</span>
                              <span>{item.country_name || item.country}</span>
                              {item.currency && (
                                <span className="text-[10px] text-indigo-600 dark:text-cyan-400 font-black">
                                  ({item.currency})
                                </span>
                              )}
                              <span className="text-[10px] text-slate-700 dark:text-slate-300 font-mono bg-slate-100 dark:bg-bunker-950 px-1.5 py-0.5 rounded border border-slate-200 dark:border-bunker-800 font-bold">
                                ⏰ {formatUtc3Date(item.date_iso, item.date_str)}
                              </span>
                              <span
                                className={`text-[10px] font-bold px-1.5 py-0.2 rounded ${
                                  is3Stars
                                    ? "text-rose-700 dark:text-rose-400 bg-rose-50 dark:bg-rose-950/40"
                                    : "text-amber-700 dark:text-amber-400 bg-amber-50 dark:bg-amber-950/40"
                                }`}
                              >
                                {is3Stars ? "⭐⭐⭐ 3 Yıldız" : "⭐⭐ 2 Yıldız"}
                              </span>
                            </div>
                            <h4 className="font-extrabold text-slate-900 dark:text-white text-xs leading-snug hover:text-cyan-600 dark:hover:text-cyan-400 transition-colors">
                              {item.title}
                            </h4>
                          </div>

                          {/* Sonuç Rozeti */}
                          <span
                            className={`shrink-0 px-2 py-0.5 rounded-full text-[10px] font-black whitespace-nowrap border ${
                              isBull
                                ? "bg-emerald-100 dark:bg-emerald-500/20 text-emerald-800 dark:text-emerald-300 border-emerald-300 dark:border-emerald-500/40"
                                : isBear
                                ? "bg-rose-100 dark:bg-rose-500/20 text-rose-800 dark:text-rose-300 border-rose-300 dark:border-rose-500/40"
                                : "bg-slate-100 dark:bg-slate-800 text-slate-800 dark:text-slate-200 border-slate-300 dark:border-slate-700"
                            }`}
                          >
                            {isBull ? "🟢 " : isBear ? "🔴 " : "⚪ "}
                            {label || (isBull ? "Olumlu" : isBear ? "Olumsuz" : "Açıklandı")}
                          </span>
                        </div>

                        {/* Beklenti / Önceki / Açıklanan Değerleri */}
                        <div className="grid grid-cols-3 gap-2 text-xs bg-slate-50 dark:bg-bunker-950/60 p-2.5 rounded-lg border border-slate-200/80 dark:border-bunker-800/80">
                          <div>
                            <div className="text-[10px] text-slate-500 dark:text-bunker-muted">Beklenti:</div>
                            <strong className="text-cyan-700 dark:text-cyan-300 font-bold">{item.forecast || "—"}</strong>
                          </div>
                          <div>
                            <div className="text-[10px] text-slate-500 dark:text-bunker-muted">Önceki:</div>
                            <strong className="text-slate-800 dark:text-white font-bold">{item.previous || "—"}</strong>
                          </div>
                          <div>
                            <div className="text-[10px] text-slate-500 dark:text-bunker-muted">Açıklanan:</div>
                            <strong
                              className={`font-black ${
                                isBull
                                  ? "text-emerald-700 dark:text-emerald-400"
                                  : isBear
                                  ? "text-rose-700 dark:text-rose-400"
                                  : "text-slate-900 dark:text-white"
                              }`}
                            >
                              {item.actual || "—"}
                            </strong>
                          </div>
                        </div>

                        {/* Kıyaslama veya Ters Yön Notu */}
                        {cmp && (
                          <div className="text-[10px] font-mono text-slate-700 dark:text-slate-300 bg-slate-100 dark:bg-bunker-950/60 rounded-lg px-2 py-1 border border-slate-200 dark:border-bunker-800">
                            {cmp}
                            {basis && <span className="text-slate-500 dark:text-bunker-muted"> · kıyas: {basis}</span>}
                          </div>
                        )}

                        {dirNote && (
                          <div className="text-[10px] text-rose-800 dark:text-rose-300 bg-rose-50 dark:bg-rose-500/10 rounded-lg px-2 py-1 border border-rose-200 dark:border-rose-500/30">
                            ⚠️ {dirNote}
                          </div>
                        )}

                        {/* Senaryo Açıklaması */}
                        {branchOutcome && (
                          <p className="text-[11px] text-slate-700 dark:text-slate-300 leading-relaxed line-clamp-2">
                            {branchOutcome}
                          </p>
                        )}

                        {/* Alt Butonlar & Etkilenen Semboller */}
                        <div className="flex items-center justify-between gap-2 pt-1 border-t border-slate-200/60 dark:border-bunker-800/60">
                          <div className="flex flex-wrap gap-1 items-center">
                            {item.affected_symbols.map((sym) => (
                              <span
                                key={sym}
                                className="px-1.5 py-0.5 rounded text-[9px] font-black bg-cyan-100 dark:bg-cyan-950/70 text-cyan-800 dark:text-cyan-300 border border-cyan-400/40"
                              >
                                {sym}
                              </span>
                            ))}
                          </div>
                          <button
                            type="button"
                            onClick={(e) => {
                              e.stopPropagation();
                              setSelectedEvent(item);
                            }}
                            className="px-2.5 py-1 rounded-lg text-[11px] font-bold bg-slate-100 dark:bg-bunker-800 text-slate-800 dark:text-slate-200 border border-slate-300 dark:border-bunker-700 hover:bg-slate-200 dark:hover:bg-bunker-700 transition-all shrink-0"
                          >
                            Kart İncele →
                          </button>
                        </div>
                      </div>
                    );
                  })
                )}
              </div>
            </div>

            {/* 2. SAĞ SÜTUN: SIRADAKİ AÇIKLANACAKLAR (KRONOLOJİK / EN YAKIN EN ÜSTTE) */}
            <div className="flex flex-col space-y-3">
              <div className="flex items-center justify-between px-3.5 py-2.5 rounded-xl bg-cyan-50/80 dark:bg-cyan-950/30 border border-cyan-300 dark:border-cyan-500/30">
                <div className="flex items-center gap-2">
                  <span className="w-2.5 h-2.5 rounded-full bg-cyan-500 animate-ping" />
                  <h3 className="text-xs font-black uppercase tracking-wider text-cyan-900 dark:text-cyan-300 flex items-center gap-1.5">
                    <span>⏳</span> Sıradaki Açıklanacaklar
                  </h3>
                </div>
                <div className="flex items-center gap-2">
                  <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-cyan-100 dark:bg-cyan-500/20 text-cyan-800 dark:text-cyan-300 border border-cyan-300 dark:border-cyan-500/30">
                    Yaklaşan Olaylar (Kronolojik)
                  </span>
                  <span className="text-[11px] font-bold font-mono text-cyan-900 dark:text-cyan-400">
                    ({upcomingCalendarEvents.length})
                  </span>
                </div>
              </div>

              <div className="max-h-[750px] overflow-y-auto space-y-3 pr-1 scrollbar-thin">
                {upcomingCalendarEvents.length === 0 ? (
                  <div className="p-8 text-center text-xs text-slate-500 dark:text-bunker-muted rounded-xl bg-slate-50 dark:bg-bunker-950/40 border border-slate-200 dark:border-bunker-800">
                    Bugün için beklenen başka makro veri kalmadı veya filtrelere uyan sonuç yok.
                  </div>
                ) : (
                  upcomingCalendarEvents.map((item) => {
                    const is3Stars = (item.stars || (item.impact === "High" ? 3 : 2)) === 3;
                    return (
                      <div
                        key={`up-${item.id}`}
                        onClick={() => setSelectedEvent(item)}
                        className={`p-3.5 rounded-xl border transition-all cursor-pointer shadow-sm hover:shadow-md space-y-2.5 bg-white dark:bg-bunker-900/90 border-slate-300 dark:border-bunker-800 hover:border-cyan-500/60 ${
                          is3Stars ? "dark:hover:border-rose-500/60" : ""
                        }`}
                        title="Detaylı kartı ve senaryoyu açmak için tıklayın"
                      >
                        {/* Başlık Satırı */}
                        <div className="flex items-start justify-between gap-2">
                          <div className="min-w-0 space-y-0.5">
                            <div className="flex items-center gap-1.5 text-[11px] text-slate-600 dark:text-slate-400 font-bold flex-wrap">
                              <span>{item.flag || "🌐"}</span>
                              <span>{item.country_name || item.country}</span>
                              {item.currency && (
                                <span className="text-[10px] text-indigo-600 dark:text-cyan-400 font-black">
                                  ({item.currency})
                                </span>
                              )}
                              <span className="text-[10px] text-slate-900 dark:text-cyan-300 font-mono font-bold bg-slate-100 dark:bg-bunker-950 px-1.5 py-0.5 rounded border border-slate-200 dark:border-bunker-800">
                                ⏰ {formatUtc3Date(item.date_iso, item.date_str)}
                              </span>
                              <span
                                className={`text-[10px] font-bold px-1.5 py-0.2 rounded ${
                                  is3Stars
                                    ? "text-rose-700 dark:text-rose-400 bg-rose-50 dark:bg-rose-950/40"
                                    : "text-amber-700 dark:text-amber-400 bg-amber-50 dark:bg-amber-950/40"
                                }`}
                              >
                                {is3Stars ? "⭐⭐⭐ 3 Yıldız" : "⭐⭐ 2 Yıldız"}
                              </span>
                            </div>
                            <h4 className="font-extrabold text-slate-900 dark:text-white text-xs leading-snug hover:text-cyan-600 dark:hover:text-cyan-400 transition-colors">
                              {item.title}
                            </h4>
                            {item.original_title && item.original_title !== item.title && (
                              <div className="text-[10px] text-slate-500 dark:text-slate-400 italic line-clamp-1">
                                {item.original_title}
                              </div>
                            )}
                          </div>

                          {/* Geri Sayım Rozeti */}
                          <div className="shrink-0 flex items-center gap-1">
                            <EventCountdownBadge
                              dateIso={item.date_iso}
                              dateStr={formatUtc3Date(item.date_iso, item.date_str)}
                              status={item.status}
                              isPassed={item.is_passed}
                              nowSec={nowSec}
                            />
                          </div>
                        </div>

                        {/* Beklenti / Önceki Değerleri */}
                        <div className="grid grid-cols-2 gap-2 text-xs bg-slate-50 dark:bg-bunker-950/60 p-2.5 rounded-lg border border-slate-200/80 dark:border-bunker-800/80">
                          <div>
                            <div className="text-[10px] text-slate-500 dark:text-bunker-muted">Beklenti:</div>
                            <strong className="text-cyan-700 dark:text-cyan-300 font-bold">{item.forecast || "—"}</strong>
                          </div>
                          <div>
                            <div className="text-[10px] text-slate-500 dark:text-bunker-muted">Önceki:</div>
                            <strong className="text-slate-800 dark:text-white font-bold">{item.previous || "—"}</strong>
                          </div>
                        </div>

                        {/* Senaryo Başlığı / Özeti */}
                        {item.scenario?.summary_short || item.scenario?.title ? (
                          <p className="text-[11px] text-slate-600 dark:text-slate-300 leading-relaxed line-clamp-2 italic">
                            💡 {item.scenario?.summary_short || item.scenario?.title}
                          </p>
                        ) : null}

                        {/* Alt Butonlar & Etkilenen Semboller */}
                        <div className="flex items-center justify-between gap-2 pt-1 border-t border-slate-200/60 dark:border-bunker-800/60">
                          <div className="flex flex-wrap gap-1 items-center">
                            {item.affected_symbols.map((sym) => (
                              <span
                                key={sym}
                                className="px-1.5 py-0.5 rounded text-[9px] font-black bg-cyan-100 dark:bg-cyan-950/70 text-cyan-800 dark:text-cyan-300 border border-cyan-400/40"
                              >
                                {sym}
                              </span>
                            ))}
                          </div>
                          <button
                            type="button"
                            onClick={(e) => {
                              e.stopPropagation();
                              setSelectedEvent(item);
                            }}
                            className="px-2.5 py-1 rounded-lg text-[11px] font-bold bg-cyan-100 dark:bg-cyan-950/60 text-cyan-800 dark:text-cyan-300 border border-cyan-400/50 hover:bg-cyan-200 dark:hover:bg-cyan-900/60 transition-all shrink-0"
                          >
                            Senaryoyu İncele →
                          </button>
                        </div>
                      </div>
                    );
                  })
                )}
              </div>
            </div>
          </div>
        )}
      </section>

      {/* 7. KAPANAN İŞLEMLER RAPOR YÖNLENDİRMESİ & GÜNLÜK ÖZET */}
      <section className="p-4 sm:p-5 rounded-2xl bg-white dark:bg-bunker-900/80 border border-slate-300 dark:border-bunker-800 shadow-xl flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-cyan-100 dark:bg-cyan-500/10 border border-cyan-300 dark:border-cyan-400/30 flex items-center justify-center text-xl shrink-0">
            📜
          </div>
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-sm font-bold text-slate-900 dark:text-white uppercase tracking-wider">
                Geçmiş ve Kapanan İşlem Raporları
              </h2>
              <span className="text-[10px] px-2 py-0.5 rounded-full bg-cyan-100 dark:bg-bunker-950 text-cyan-900 dark:text-cyan-300 border border-cyan-300 dark:border-bunker-800 font-mono font-bold">
                Bugün {closedTrades.length} İşlem Kapandı
              </span>
            </div>
            <p className="text-xs text-slate-600 dark:text-bunker-muted mt-1">
              Kapanan işlemlerin tam dökümü, kâr faktörü, PnL detayları ve filtrelemeleri Raporlar sayfasında listelenmektedir.
            </p>
          </div>
        </div>

        <div className="flex items-center gap-3 shrink-0">
          <div className="hidden md:flex flex-col text-right font-mono text-xs">
            <span className="text-[10px] text-slate-500 dark:text-bunker-muted">Bugün Net K/Z:</span>
            <span className={`font-bold ${kpi.total_pnl_usd >= 0 ? "text-emerald-700 dark:text-emerald-400" : "text-rose-700 dark:text-rose-400"}`}>
              {kpi.total_pnl_usd >= 0 ? `+$${kpi.total_pnl_usd.toFixed(2)}` : `-$${Math.abs(kpi.total_pnl_usd).toFixed(2)}`}
            </span>
          </div>
          <Link
            href="/forex/reports"
            className="px-4 py-2.5 rounded-xl bg-cyan-100 hover:bg-cyan-200 dark:bg-gradient-to-r dark:from-cyan-500/20 dark:to-blue-500/20 dark:hover:from-cyan-500/30 dark:hover:to-blue-500/30 border border-cyan-400 dark:border-cyan-400/40 text-cyan-900 dark:text-cyan-300 font-bold text-xs flex items-center gap-2 transition-all shadow-sm active:scale-95"
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
                    ⏰ {formatUtc3Date(selectedEvent.date_iso, selectedEvent.date_str)}
                  </span>
                  <EventCountdownBadge
                    dateIso={selectedEvent.date_iso}
                    dateStr={formatUtc3Date(selectedEvent.date_iso, selectedEvent.date_str)}
                    status={selectedEvent.status}
                    isPassed={selectedEvent.is_passed}
                    nowSec={nowSec}
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

                {/* Gerçekleşen senaryo + ters aile uyarısı */}
                {selectedOutcomeVisible && selectedOutcomeSide && (
                  <div
                    className={`mt-1.5 px-2 py-1 rounded-lg text-[10px] font-bold border ${
                      selectedOutcomeSide === "bullish"
                        ? "bg-emerald-50 dark:bg-emerald-500/10 text-emerald-800 dark:text-emerald-300 border-emerald-300 dark:border-emerald-500/30"
                        : "bg-rose-50 dark:bg-rose-500/10 text-rose-800 dark:text-rose-300 border-rose-300 dark:border-rose-500/30"
                    }`}
                  >
                    {selectedOutcomeSide === "bullish" ? "🟢" : "🔴"}{" "}
                    {labelText(selectedEvent) || (selectedOutcomeSide === "bullish" ? "Olumlu" : "Olumsuz")}
                    {comparisonText(selectedEvent) && (
                      <span className="font-mono font-medium opacity-90">
                        {" · "}
                        {comparisonText(selectedEvent)}
                      </span>
                    )}
                  </div>
                )}
                {directionNoteText(selectedEvent) && (
                  <div className="mt-1 px-2 py-1 rounded-lg text-[10px] text-amber-900 dark:text-amber-300 bg-amber-50 dark:bg-amber-500/10 border border-amber-300 dark:border-amber-500/30">
                    ⚠️ {directionNoteText(selectedEvent)}
                  </div>
                )}
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

            {/* "NE OLURSA NE OLUR?" SENARYO MATRİSİ
                Karar verilebildiğinde (veri açıklandı + dal belirli) yalnız
                gerçekleşen dal render edilir; diğeri tamamen gizlenir. */}
            <div className="space-y-3">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-base">⚡</span>
                <h3 className="text-xs font-black uppercase tracking-wider text-amber-700 dark:text-amber-300">
                  {selectedEvent.scenario?.title || "Ne Olursa Ne Olur? Senaryo Analizi"}
                </h3>
                {selectedOutcomeVisible && selectedOutcomeSide && (
                  <span
                    className={`px-2 py-0.5 rounded-full text-[10px] font-black border whitespace-nowrap ${
                      selectedOutcomeSide === "bullish"
                        ? "bg-emerald-100 dark:bg-emerald-500/20 text-emerald-800 dark:text-emerald-300 border-emerald-300 dark:border-emerald-500/40"
                        : "bg-rose-100 dark:bg-rose-500/20 text-rose-800 dark:text-rose-300 border-rose-300 dark:border-rose-500/40"
                    }`}
                  >
                    ✅ Gerçekleşen Senaryo
                  </span>
                )}
              </div>

              <div className="space-y-2.5 text-xs">
                {/* OLUMLU / BEKLENTİ ÜZERİ */}
                {scenarioBranches.showBullish && (
                  <div className="p-3.5 rounded-xl bg-emerald-50 dark:bg-emerald-500/10 border border-emerald-400 dark:border-emerald-500/30 space-y-1 shadow-sm">
                    <div className="font-black text-emerald-800 dark:text-emerald-400 flex items-center gap-1.5">
                      <span>🟢</span>
                      <span>{selectedEvent.scenario?.bullish_trigger}</span>
                    </div>
                    <p className="text-[11px] text-emerald-900 dark:text-emerald-200/90 font-medium leading-relaxed pl-5">
                      {selectedEvent.scenario?.bullish_outcome}
                    </p>
                  </div>
                )}

                {/* OLUMSUZ / BEKLENTİ ALTI */}
                {scenarioBranches.showBearish && (
                  <div className="p-3.5 rounded-xl bg-rose-50 dark:bg-rose-500/10 border border-rose-400 dark:border-rose-500/30 space-y-1 shadow-sm">
                    <div className="font-black text-rose-800 dark:text-rose-400 flex items-center gap-1.5">
                      <span>🔴</span>
                      <span>{selectedEvent.scenario?.bearish_trigger}</span>
                    </div>
                    <p className="text-[11px] text-rose-900 dark:text-rose-200/90 font-medium leading-relaxed pl-5">
                      {selectedEvent.scenario?.bearish_outcome}
                    </p>
                  </div>
                )}

                {/* KARAR VERİLEMEDİ: bilgi gizlenmez, NEDENİNİ doğru söyle. */}
                {selectedFallbackReason === "pending" && (
                  <p className="text-[10px] text-slate-500 dark:text-bunker-muted">
                    Veri henüz açıklanmadı — iki senaryo da olasıdır.
                  </p>
                )}
                {selectedFallbackReason === "tie" && (
                  <p className="text-[10px] text-slate-500 dark:text-bunker-muted">
                    Açıklanan değer beklenti/önceki ile aynı — piyasa yönsüz, iki senaryo da gösteriliyor.
                  </p>
                )}
                {selectedFallbackReason === "unparsed" && (
                  <p className="text-[10px] text-slate-500 dark:text-bunker-muted">
                    Açıklanan değer beklenti/önceki ile ayrıştırılamadı — iki senaryo da gösteriliyor.
                  </p>
                )}


              </div>
            </div>

            {/* Alt Butonlar */}
            <div className="pt-3 border-t border-slate-200 dark:border-bunker-800 flex items-center justify-end gap-3">
              <button
                type="button"
                onClick={() => setSelectedEvent(null)}
                className="w-full sm:w-auto px-6 py-2 rounded-xl bg-slate-100 dark:bg-bunker-900 border border-slate-300 dark:border-bunker-700 hover:border-slate-400 dark:hover:border-cyan-400 text-slate-800 dark:text-white text-xs font-bold transition-all shadow-xs"
              >
                Kapat
              </button>
            </div>
          </div>
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
