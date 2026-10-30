"use client";

// ============================================================================
// ANA SAYFA — BUGÜNÜN DURUMU (2026-10-30 sadeleştirme)
// Sıra: durum (KPI) → açık pozisyonlar → sıradaki makro veriler → bugün kapanan
// işlemler → parite katkısı. Ekonomik takvimin tamamı /forex/calendar'dadır;
// burada yalnız "sıradaki" ve "bugün açıklanan" özet satırları gösterilir.
// ============================================================================

import React, { useState, useEffect, useMemo, useCallback } from "react";
import Link from "next/link";
import { apiFetch } from "./lib/api";
import { usePolling } from "./lib/usePolling";
import {
  hasPublishedActual,
  outcomeSide,
  labelText,
  selectTodaysPublished,
  type CalendarOutcome,
} from "./lib/calendarOutcome";
import EVShieldModal, { EVShieldStatusResponse } from "./forex/components/EVShieldModal";
import { Badge, Button, Card } from "./components/ui";

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


// PERFORMANS (2026-10-08): geri sayım için tek paylaşımlı saniyelik sayaç.
const useSharedNowSec = (active: boolean): number => {
  const [nowSec, setNowSec] = useState<number>(() => Math.floor(Date.now() / 1000));
  useEffect(() => {
    if (!active) return;
    const t = setInterval(() => setNowSec(Math.floor(Date.now() / 1000)), 1000);
    return () => clearInterval(t);
  }, [active]);
  return nowSec;
};

/** Olayın saati (TR, UTC+3): "HH:MM". */
function trClock(iso?: string): string {
  const ms = iso ? Date.parse(iso) : NaN;
  if (!Number.isFinite(ms)) return "--:--";
  const d = new Date(ms + 3 * 3600 * 1000);
  return `${String(d.getUTCHours()).padStart(2, "0")}:${String(d.getUTCMinutes()).padStart(2, "0")}`;
}

/** Açıklanmaya kalan süre: >24 sa "1g 4sa", ≥1 sa "02:15 sa", aksi "MM:SS". */
function untilText(targetMs: number, nowMs: number): string {
  const diff = Math.max(0, Math.floor((targetMs - nowMs) / 1000));
  if (diff >= 86400) return `${Math.floor(diff / 86400)}g ${Math.floor((diff % 86400) / 3600)}sa`;
  if (diff >= 3600) return `${String(Math.floor(diff / 3600)).padStart(2, "0")}:${String(Math.floor((diff % 3600) / 60)).padStart(2, "0")} sa`;
  return `${String(Math.floor(diff / 60)).padStart(2, "0")}:${String(diff % 60).padStart(2, "0")}`;
}

const money = (v: number) => `${v >= 0 ? "+" : "−"}$${Math.abs(v).toFixed(2)}`;
const pips = (v: number) => `${v >= 0 ? "+" : "−"}${Math.abs(v).toFixed(1)}`;
const tone = (v: number, neutral = false) =>
  neutral ? "text-white" : v > 0 ? "text-emerald-400" : v < 0 ? "text-rose-400" : "text-white";
const stars = (e: { stars?: number; impact?: string }) => (e.stars || (e.impact === "High" ? 3 : 2)) >= 3 ? "★★★" : "★★";

const Eyebrow = ({ children }: { children: React.ReactNode }) => (
  <h2 className="font-mono text-[11px] font-bold uppercase tracking-[0.14em] text-bunker-muted">{children}</h2>
);

export default function HomePage() {
  const [homeDataError, setHomeDataError] = useState("");
  const [refreshing, setRefreshing] = useState<boolean>(false);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [loaded, setLoaded] = useState<boolean>(false);

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

  const [calendarEvents, setCalendarEvents] = useState<EconomicEvent[]>([]);

  const [evShieldModalOpen, setEvShieldModalOpen] = useState<boolean>(false);
  const [evShieldStatus, setEvShieldStatus] = useState<EVShieldStatusResponse | null>(null);

  const fetchCalendar = useCallback(async () => {
    try {
      const newsRes = await apiFetch("/api/forex/news").catch(() => null);
      if (newsRes?.news && Array.isArray(newsRes.news)) setCalendarEvents(newsRes.news);
    } catch (err) {
      console.error("Ekonomik takvim yükleme hatası:", err);
    }
  }, []);

  // İşlem ve hesap verisi (4 sn'de bir). Günün penceresi: UTC+3 00:00 sonrası.
  const fetchData = useCallback(async (isSilent = false) => {
    if (!isSilent) setRefreshing(true);
    try {
      const [reportRes, statusRes] = await Promise.all([
        apiFetch("/api/forex/auto-paper/trades?period=today&limit=250"),
        apiFetch("/api/forex/auto-paper/status").catch(() => null),
      ]);

      if (reportRes) {
        if (Array.isArray(reportRes.open_positions)) setOpenPositions(reportRes.open_positions);

        const cutoff = getToday0001Cutoff();
        let validTrades: ClosedTrade[] = [];
        if (Array.isArray(reportRes.trades)) {
          validTrades = reportRes.trades.filter((t: ClosedTrade) => parseTradeTime(t) >= cutoff);
          setClosedTrades(validTrades);
        }

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
        const total = validTrades.length;
        const pf = grossLoss > 0 ? Number((grossProfit / grossLoss).toFixed(2)) : grossProfit > 0 ? 999 : 0;

        setKpi((prev) => ({
          ...prev,
          total_trades: total,
          wins: winsCount,
          losses: lossesCount,
          win_rate: total > 0 ? (winsCount / total) * 100 : 0,
          total_pnl_usd: totalPnl,
          total_pnl_pips: totalPips,
          profit_factor: pf,
          profit_factor_infinite: pf >= 999,
          gross_profit_usd: grossProfit,
          gross_loss_usd: grossLoss,
          balance: typeof statusRes?.balance === "number"
            ? statusRes.balance
            : typeof reportRes.kpi?.balance === "number" ? reportRes.kpi.balance : prev.balance,
          equity: typeof statusRes?.equity === "number"
            ? statusRes.equity
            : typeof reportRes.kpi?.equity === "number" ? reportRes.kpi.equity : prev.equity,
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

      if (statusRes?.ev_shield) setEvShieldStatus(statusRes.ev_shield);
      setLastUpdated(new Date());
      setHomeDataError("");
    } catch (err) {
      const detail = err instanceof Error ? err.message : "Hesap verisi alınamadı";
      setHomeDataError(`Hesap verisi alınamadı: ${detail}`);
    } finally {
      setLoaded(true);
      setRefreshing(false);
    }
  }, []);

  // PERFORMANS (2026-10-08): usePolling sekme arka plandayken durur.
  usePolling(() => fetchData(true), 5000);
  usePolling(() => fetchCalendar(), 180000);

  const nowSec = useSharedNowSec(calendarEvents.length > 0);
  const nowMs = nowSec * 1000;

  const winRate = kpi.total_trades > 0 ? (kpi.wins / kpi.total_trades) * 100 : 0;
  const noTrades = kpi.total_trades === 0;
  const lossShare = kpi.total_trades > 0 ? (kpi.losses / kpi.total_trades) * 100 : 0;
  const pfValue = kpi.profit_factor_infinite ? Infinity : kpi.profit_factor ?? 0;
  const pfTone = noTrades
    ? "text-white"
    : pfValue >= 1.5 ? "text-emerald-400" : pfValue >= 1 ? "text-amber-300" : "text-rose-400";

  const sortedOpenPositions = useMemo(
    () =>
      [...openPositions].sort((a, b) => {
        const symA = (a.symbol || a.display || "").toUpperCase();
        const symB = (b.symbol || b.display || "").toUpperCase();
        if (symA !== symB) return symA.localeCompare(symB);
        return (b.open_time ? Date.parse(b.open_time) || 0 : 0) - (a.open_time ? Date.parse(a.open_time) || 0 : 0);
      }),
    [openPositions],
  );

  const recentClosed = useMemo(
    () => [...closedTrades].sort((a, b) => parseTradeTime(b) - parseTradeTime(a)).slice(0, 8),
    [closedTrades],
  );

  const symbolStats = useMemo(() => {
    const map = new Map<string, { symbol: string; trades: number; wins: number; pnl_usd: number; pnl_pips: number }>();
    for (const t of closedTrades) {
      const sym = (t.symbol || t.display || "DİĞER").toUpperCase();
      const cur = map.get(sym) || { symbol: sym, trades: 0, wins: 0, pnl_usd: 0, pnl_pips: 0 };
      cur.trades += 1;
      const pnl = Number(t.pnl_usd) || 0;
      cur.pnl_usd += pnl;
      cur.pnl_pips += Number(t.pnl_pips) || 0;
      if (pnl > 0 || t.outcome === "WIN") cur.wins += 1;
      map.set(sym, cur);
    }
    return Array.from(map.values()).sort((a, b) => b.pnl_usd - a.pnl_usd);
  }, [closedTrades]);
  const maxAbsPnl = Math.max(1, ...symbolStats.map((s) => Math.abs(s.pnl_usd)));

  // Sıradaki açıklanacak olaylar: saati gelmemiş, açıklanmamış.
  const upcomingEvents = useMemo(
    () =>
      calendarEvents
        .filter((e) => {
          if (hasPublishedActual(e.actual) || e.status === "Açıklandı") return false;
          const t = e.date_iso ? Date.parse(e.date_iso) : NaN;
          return Number.isFinite(t) && t > nowMs;
        })
        .sort((a, b) => Date.parse(a.date_iso as string) - Date.parse(b.date_iso as string))
        .slice(0, 5),
    [calendarEvents, nowMs],
  );
  const publishedToday = useMemo(
    () => selectTodaysPublished(calendarEvents, nowMs).slice(0, 4),
    [calendarEvents, nowMs],
  );

  const shieldBlocked = evShieldStatus?.blocked_count ?? 0;
  const updatedText = lastUpdated ? lastUpdated.toLocaleTimeString("tr-TR") : null;

  return (
    <div className="space-y-5 pb-16 font-mono text-white">
      {/* BAŞLIK */}
      <header className="flex flex-col sm:flex-row sm:items-end justify-between gap-3">
        <div>
          <h1 className="text-xl sm:text-2xl font-bold tracking-tight">Bugünün Durumu</h1>
          <p className="mt-1 text-xs text-bunker-muted">
            Otonom scalper · UTC+3 · rakamlar her gece 00:00&apos;da sıfırlanır
          </p>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <span className="flex items-center gap-1.5 text-[11px] text-bunker-muted mr-1" aria-live="polite">
            <span
              className={`w-1.5 h-1.5 rounded-full ${homeDataError ? "bg-rose-400" : updatedText ? "bg-emerald-400" : "bg-bunker-muted"}`}
              aria-hidden
            />
            {homeDataError ? "Veri alınamadı" : updatedText ? `Güncellendi ${updatedText}` : "Yükleniyor…"}
          </span>
          <Button
            variant={shieldBlocked > 0 ? "danger" : "secondary"}
            onClick={() => setEvShieldModalOpen(true)}
            title="Sembol EV Kalkanı listesi ve muafiyet yönetimi"
            className="min-h-11 sm:min-h-10"
          >
            EV Kalkanı{shieldBlocked > 0 ? ` · ${shieldBlocked}` : ""}
          </Button>
          <Button
            variant="secondary"
            onClick={() => {
              void fetchData(false);
              void fetchCalendar();
            }}
            disabled={refreshing}
            className="min-h-11 sm:min-h-10"
          >
            {refreshing ? "Yenileniyor…" : "Yenile"}
          </Button>
        </div>
      </header>

      {homeDataError && (
        <div role="alert" className="rounded-xl border border-rose-500/40 bg-rose-500/10 px-4 py-3 text-xs text-rose-300">
          {homeDataError}
        </div>
      )}

      {shieldBlocked > 0 && evShieldStatus && (
        <div className="rounded-xl border border-rose-500/40 bg-rose-500/10 px-4 py-3 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <p className="text-xs text-rose-100">
            <strong className="font-bold">{shieldBlocked} sembol EV Kalkanı ile dinlenmede:</strong>{" "}
            {evShieldStatus.symbols
              .filter((s) => s.is_blocked)
              .map((s) => `${s.display} (${money(s.net_usd)})`)
              .join(", ")}
            . Akut zarar nedeniyle korumaya alındı; istersen bugün için muaf tutabilirsin.
          </p>
          <Button variant="danger" onClick={() => setEvShieldModalOpen(true)} className="shrink-0 min-h-11 sm:min-h-10">
            İncele
          </Button>
        </div>
      )}

      {/* DURUM: KPI ŞERİDİ */}
      <Card className="!p-0 overflow-hidden" >
        <section aria-label="Günün göstergeleri" className="grid grid-cols-2 lg:grid-cols-4 divide-bunker-800 [&>*]:border-bunker-800 [&>*:nth-child(odd)]:border-r [&>*:nth-child(-n+2)]:border-b lg:[&>*]:border-b-0 lg:[&>*]:border-r lg:[&>*:last-child]:border-r-0">
          <div className="p-4 sm:p-5">
            <p className="eyebrow">Net K/Z</p>
            <p className={`mt-2 text-2xl sm:text-3xl font-bold tabular-nums ${tone(kpi.total_pnl_usd, noTrades)}`}>
              {noTrades ? "$0.00" : money(kpi.total_pnl_usd)}
            </p>
            <p className="mt-1.5 text-[11px] text-bunker-muted tabular-nums">
              {pips(kpi.total_pnl_pips ?? 0)} pip · {kpi.total_trades} işlem
            </p>
          </div>

          <div className="p-4 sm:p-5">
            <p className="eyebrow">Kazanma oranı</p>
            <p className="mt-2 text-2xl sm:text-3xl font-bold tabular-nums">{noTrades ? "—" : `%${winRate.toFixed(1)}`}</p>
            <p className="mt-1.5 text-[11px] text-bunker-muted tabular-nums">
              <span className={noTrades ? "" : "text-emerald-400"}>{kpi.wins} kazanç</span>
              {" · "}
              <span className={noTrades ? "" : "text-rose-400"}>{kpi.losses} kayıp</span>
            </p>
            <div
              className="mt-2 h-1.5 rounded-full bg-bunker-800 overflow-hidden flex"
              role="img"
              aria-label={`${kpi.wins} kazanç, ${kpi.losses} kayıp`}
            >
              {!noTrades && (
                <>
                  <div className="h-full bg-emerald-500" style={{ width: `${winRate}%` }} />
                  <div className="h-full bg-rose-500" style={{ width: `${lossShare}%` }} />
                </>
              )}
            </div>
          </div>

          <div className="p-4 sm:p-5">
            <p className="eyebrow">Kâr faktörü</p>
            <p className={`mt-2 text-2xl sm:text-3xl font-bold tabular-nums ${pfTone}`}>
              {noTrades ? "—" : kpi.profit_factor_infinite ? "∞" : pfValue.toFixed(2)}
            </p>
            <p className="mt-1.5 text-[11px] text-bunker-muted tabular-nums">
              Brüt +${(kpi.gross_profit_usd ?? 0).toFixed(2)} / −${(kpi.gross_loss_usd ?? 0).toFixed(2)}
            </p>
          </div>

          <div className="p-4 sm:p-5">
            <p className="eyebrow">Özsermaye</p>
            <p className="mt-2 text-2xl sm:text-3xl font-bold tabular-nums">
              {kpi.equity == null && kpi.balance == null ? "—" : `$${Number(kpi.equity ?? kpi.balance).toFixed(2)}`}
            </p>
            <p className="mt-1.5 text-[11px] text-bunker-muted tabular-nums">
              Bakiye {kpi.balance == null ? "—" : `$${kpi.balance.toFixed(2)}`}
              {" · "}Açık{" "}
              <span className={tone(kpi.open_pnl_usd, kpi.open_positions_count === 0)}>
                {kpi.open_positions_count === 0 ? "—" : money(kpi.open_pnl_usd)}
              </span>
            </p>
          </div>
        </section>
      </Card>

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-5">
        {/* AÇIK POZİSYONLAR */}
        <Card className="!p-0 overflow-hidden xl:col-span-2">
          <section aria-labelledby="open-pos-title">
            <div className="flex items-center justify-between gap-2 px-4 sm:px-5 py-3 border-b border-bunker-800">
              <div id="open-pos-title">
                <Eyebrow>Açık pozisyonlar ({sortedOpenPositions.length})</Eyebrow>
              </div>
              {sortedOpenPositions.length > 0 && (
                <span className={`text-xs font-bold tabular-nums ${tone(kpi.open_pnl_usd)}`}>
                  {money(kpi.open_pnl_usd)}
                </span>
              )}
            </div>
            {sortedOpenPositions.length === 0 ? (
              <p className="px-5 py-8 text-center text-xs text-bunker-muted">
                {loaded ? "Şu an açık pozisyon yok." : "Yükleniyor…"}
              </p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-xs tabular-nums">
                  <thead>
                    <tr className="text-[10px] uppercase tracking-wider text-bunker-muted">
                      <th scope="col" className="text-left font-medium px-4 sm:px-5 py-2">Sembol</th>
                      <th scope="col" className="text-left font-medium px-2 py-2">Yön</th>
                      <th scope="col" className="text-right font-medium px-2 py-2">Lot</th>
                      <th scope="col" className="text-right font-medium px-2 py-2">Giriş</th>
                      <th scope="col" className="text-right font-medium px-2 py-2">Güncel</th>
                      <th scope="col" className="text-right font-medium px-2 py-2">SL</th>
                      <th scope="col" className="text-right font-medium px-4 sm:px-5 py-2">K/Z</th>
                    </tr>
                  </thead>
                  <tbody>
                    {sortedOpenPositions.map((p) => {
                      const sym = p.display || p.symbol;
                      return (
                        <tr key={p.id || p.ticket} className="border-t border-bunker-800/70">
                          <td className="px-4 sm:px-5 py-2.5 font-bold whitespace-nowrap">
                            {sym}
                            {p.strategy_label && (
                              <span className="block text-[10px] font-normal text-bunker-muted truncate max-w-[11rem]">{p.strategy_label}</span>
                            )}
                          </td>
                          <td className="px-2 py-2.5">
                            <Badge tone={p.direction === "BUY" ? "info" : "warning"}>{p.direction === "BUY" ? "AL" : "SAT"}</Badge>
                          </td>
                          <td className="px-2 py-2.5 text-right">{p.lots}</td>
                          <td className="px-2 py-2.5 text-right">{formatPrice(p.entry_price, p.symbol)}</td>
                          <td className="px-2 py-2.5 text-right">{formatPrice(p.current_price, p.symbol)}</td>
                          <td className="px-2 py-2.5 text-right text-bunker-muted">{formatPrice(p.sl_price, p.symbol)}</td>
                          <td className={`px-4 sm:px-5 py-2.5 text-right font-bold whitespace-nowrap ${tone(p.pnl_usd)}`}>
                            {money(Number(p.pnl_usd) || 0)}
                            <span className="block text-[10px] font-normal opacity-80">{pips(Number(p.pnl_pips) || 0)} pip</span>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </Card>

        {/* MAKRO VERİLER */}
        <Card className="!p-0 overflow-hidden">
          <section aria-labelledby="macro-title">
            <div className="flex items-center justify-between gap-2 px-4 sm:px-5 py-3 border-b border-bunker-800">
              <div id="macro-title">
                <Eyebrow>Makro veriler</Eyebrow>
              </div>
              <Link href="/forex/calendar" className="inline-flex items-center min-h-11 sm:min-h-0 text-[11px] text-cyan-300 hover:text-cyan-200 hover:underline font-bold">
                Takvimin tamamı →
              </Link>
            </div>

            <div className="px-4 sm:px-5 pt-3 pb-1">
              <p className="text-[10px] uppercase tracking-wider text-bunker-muted">Sıradaki</p>
            </div>
            {upcomingEvents.length === 0 ? (
              <p className="px-5 pb-4 text-xs text-bunker-muted">{calendarEvents.length ? "Yaklaşan kritik veri yok." : "Takvim yükleniyor…"}</p>
            ) : (
              <ul className="px-2 pb-2">
                {upcomingEvents.map((e) => (
                  <li key={e.id}>
                    <Link href="/forex/calendar" className="flex items-center gap-2 rounded-lg px-3 py-2 min-h-11 hover:bg-bunker-800/60 transition-colors">
                      <span className="text-[11px] text-bunker-muted tabular-nums w-10 shrink-0">{trClock(e.date_iso)}</span>
                      <span className="text-[10px] font-bold text-bunker-muted w-8 shrink-0">{(e.currency || e.country || "").toUpperCase().slice(0, 3)}</span>
                      <span className="text-xs flex-1 min-w-0 truncate" title={e.title}>{e.title}</span>
                      <span className={`text-[10px] shrink-0 ${stars(e) === "★★★" ? "text-amber-300" : "text-bunker-muted"}`} aria-label={stars(e) === "★★★" ? "Yüksek etki" : "Orta etki"}>{stars(e)}</span>
                      <span className="text-[11px] font-bold tabular-nums shrink-0 text-cyan-300 w-14 text-right">
                        {untilText(Date.parse(e.date_iso as string), nowMs)}
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            )}

            <div className="px-4 sm:px-5 pt-2 pb-1 border-t border-bunker-800/70">
              <p className="text-[10px] uppercase tracking-wider text-bunker-muted">Bugün açıklananlar</p>
            </div>
            {publishedToday.length === 0 ? (
              <p className="px-5 pb-4 text-xs text-bunker-muted">Yorumlanabilir açıklama henüz yok.</p>
            ) : (
              <ul className="px-2 pb-2">
                {publishedToday.map((e) => {
                  const side = outcomeSide(e);
                  const cur = (e.currency || e.country || "").toUpperCase().slice(0, 3);
                  return (
                    <li key={e.id}>
                      <Link href="/forex/calendar" className="flex items-center gap-2 rounded-lg px-3 py-2 min-h-11 hover:bg-bunker-800/60 transition-colors">
                        <span className="text-[11px] text-bunker-muted tabular-nums w-10 shrink-0">{trClock(e.date_iso)}</span>
                        <span className="text-xs flex-1 min-w-0">
                          <span className="block truncate" title={e.title}>{e.title}</span>
                          <span className="block text-[10px] text-bunker-muted truncate">
                            {labelText(e) || ""} · Açıklanan {e.actual}
                          </span>
                        </span>
                        <span className={`text-[10px] font-bold shrink-0 px-1.5 py-0.5 rounded border ${side === "bullish" ? "text-emerald-300 border-emerald-400/40 bg-emerald-500/10" : "text-rose-300 border-rose-400/40 bg-rose-500/10"}`}>
                          {cur} {side === "bullish" ? "▲ güçlü" : "▼ zayıf"}
                        </span>
                      </Link>
                    </li>
                  );
                })}
              </ul>
            )}
          </section>
        </Card>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-5">
        {/* BUGÜN KAPANAN İŞLEMLER */}
        <Card className="!p-0 overflow-hidden xl:col-span-2">
          <section aria-labelledby="closed-title">
            <div className="flex items-center justify-between gap-2 px-4 sm:px-5 py-3 border-b border-bunker-800">
              <div id="closed-title">
                <Eyebrow>Bugün kapanan işlemler ({closedTrades.length})</Eyebrow>
              </div>
              <Link href="/forex/reports" className="inline-flex items-center min-h-11 sm:min-h-0 text-[11px] text-cyan-300 hover:text-cyan-200 hover:underline font-bold">
                Tüm raporlar →
              </Link>
            </div>
            {recentClosed.length === 0 ? (
              <p className="px-5 py-8 text-center text-xs text-bunker-muted">
                {loaded ? "Bugün henüz kapanan işlem yok." : "Yükleniyor…"}
              </p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-xs tabular-nums">
                  <thead>
                    <tr className="text-[10px] uppercase tracking-wider text-bunker-muted">
                      <th scope="col" className="text-left font-medium px-4 sm:px-5 py-2">Saat</th>
                      <th scope="col" className="text-left font-medium px-2 py-2">Sembol</th>
                      <th scope="col" className="text-left font-medium px-2 py-2">Yön</th>
                      <th scope="col" className="text-right font-medium px-2 py-2">Pip</th>
                      <th scope="col" className="text-right font-medium px-2 py-2">Süre</th>
                      <th scope="col" className="text-right font-medium px-4 sm:px-5 py-2">K/Z</th>
                    </tr>
                  </thead>
                  <tbody>
                    {recentClosed.map((t, i) => {
                      const pnl = Number(t.pnl_usd) || 0;
                      return (
                        <tr key={t.id || `${t.ticket}-${i}`} className="border-t border-bunker-800/70">
                          <td className="px-4 sm:px-5 py-2.5 text-bunker-muted whitespace-nowrap">
                            {formatClockTime(t.close_time || t.exit_time, t.closed_at_ts).slice(0, 5)}
                          </td>
                          <td className="px-2 py-2.5 font-bold whitespace-nowrap">{t.display || t.symbol}</td>
                          <td className="px-2 py-2.5">
                            <Badge tone={t.direction === "BUY" ? "info" : "warning"}>{t.direction === "BUY" ? "AL" : "SAT"}</Badge>
                          </td>
                          <td className={`px-2 py-2.5 text-right ${tone(Number(t.pnl_pips) || 0)}`}>{pips(Number(t.pnl_pips) || 0)}</td>
                          <td className="px-2 py-2.5 text-right text-bunker-muted whitespace-nowrap">{t.duration_human || "—"}</td>
                          <td className={`px-4 sm:px-5 py-2.5 text-right font-bold ${tone(pnl)}`}>{money(pnl)}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </Card>

        {/* PARİTE KATKISI */}
        <Card className="!p-0 overflow-hidden">
          <section aria-labelledby="sym-title">
            <div className="flex items-center justify-between gap-2 px-4 sm:px-5 py-3 border-b border-bunker-800">
              <div id="sym-title">
                <Eyebrow>Parite katkısı</Eyebrow>
              </div>
              {symbolStats.length > 0 && <span className="text-[11px] text-bunker-muted">{symbolStats.length} parite</span>}
            </div>
            {symbolStats.length === 0 ? (
              <p className="px-5 py-8 text-center text-xs text-bunker-muted">{loaded ? "Bugün kapanan işlem yok." : "Yükleniyor…"}</p>
            ) : (
              <ul className="px-4 sm:px-5 py-3 space-y-2.5">
                {symbolStats.slice(0, 8).map((s) => (
                  <li key={s.symbol}>
                    <div className="flex items-baseline justify-between gap-2 text-xs tabular-nums">
                      <span className="font-bold">{s.symbol}</span>
                      <span className="text-[10px] text-bunker-muted">
                        {s.trades} işlem · %{((s.wins / s.trades) * 100).toFixed(0)}
                      </span>
                      <span className={`font-bold ${tone(s.pnl_usd)}`}>{money(s.pnl_usd)}</span>
                    </div>
                    <div className="mt-1 h-1 rounded-full bg-bunker-800 overflow-hidden" aria-hidden>
                      <div
                        className={`h-full ${s.pnl_usd >= 0 ? "bg-emerald-500" : "bg-rose-500"}`}
                        style={{ width: `${Math.max(4, (Math.abs(s.pnl_usd) / maxAbsPnl) * 100)}%` }}
                      />
                    </div>
                  </li>
                ))}
                {symbolStats.length > 8 && (
                  <li className="text-[11px] text-bunker-muted">+{symbolStats.length - 8} parite daha — Raporlar&apos;da</li>
                )}
              </ul>
            )}
          </section>
        </Card>
      </div>

      <EVShieldModal
        isOpen={evShieldModalOpen}
        onClose={() => setEvShieldModalOpen(false)}
        onUpdated={() => fetchData(true)}
      />
    </div>
  );
}
