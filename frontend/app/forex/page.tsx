"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import dynamic from "next/dynamic";
import { apiFetch } from "../lib/api";
import { usePolling } from "../lib/usePolling";
import { useLiveMessages, useLiveStatus, type LiveMessage } from "../lib/liveSocket";
import { formatPrice, formatUtc3 } from "../lib/format";
import type { AutoSettings } from "./components/AutoSettingsPanel";
import GateSnapshotCard, { type GateSnapshot } from "./components/GateSnapshotCard";
import OpportunityScanSection, {
  type OpportunityScanSummary,
} from "./components/OpportunityScanSection";

// PERFORMANS: Ağır modallar yalnızca kullanıcı açtığında yüklenir.
const ForexChartModal = dynamic(() => import("./components/ForexChartModal"), { ssr: false });
const AutoSettingsPanel = dynamic(() => import("./components/AutoSettingsPanel"), { ssr: false });
const EVShieldModal = dynamic(() => import("./components/EVShieldModal"), { ssr: false });

interface SessionInfo {
  name: string;
  flag: string;
  city: string;
  active: boolean;
  hours_utc: string;
}

type Tier = "STRONG" | "ACTIVE" | "WATCH" | "WAIT";
type MainTab = "radar" | "opportunity" | "positions";
type CategoryPill = "ALL" | "gold_index" | "crypto" | "forex";

interface ForexCandidate {
  symbol: string;
  display: string;
  name: string;
  category: string;
  price: number;
  bid: number;
  ask: number;
  spread_pips: number;
  error?: string | null;
  score: number;
  trend: string;
  action: "BUY" | "SELL" | "HOLD";
  rsi_5m?: number | null;
  rsi_15m?: number | null;
  macd_verdict: string;
  cmo: number;
  cci: number;
  adx: number;
  supertrend_dir: number;
  htf_trend: string;
  pip_target?: number | null;
  stop_loss_pips?: number | null;
  risk_reward?: string | number | null;
  atr_pips: number;
  tv_symbol: string;
  tier: Tier;
  motor_acar?: boolean;
  skor_gecti?: boolean;
  signal_ready: boolean;
  gate_passed: boolean;
  blocked_by: string[];
  primary_blocker: string | null;
  blocker_text: string;
  required_score?: number | null;
  csm_diff?: number;
  csm_bias?: string;
  fvg_type?: string;
  fvg_gap?: number;
  dss_score?: number;
  dss_tier?: string;
  news_info?: {
    has_active_news?: boolean;
    alignment?: "SUPPORTIVE" | "OPPOSING" | "NEUTRAL" | string;
    badge?: string;
    remaining_min?: number;
    event_title?: string;
    events_count?: number;
  };
}

interface RadarThresholds {
  min_score: number;
  btc_min_score: number;
  commodity_min_score: number;
  max_spread_pips: number;
  adx_filter_enabled: boolean;
  adx_min: number;
  supertrend_filter_enabled: boolean;
  major_session_filter: boolean;
  major_session_utc: string;
  major_min_atr_pips: number;
}

interface ScanNowRow {
  strategy: string;
  strategy_label: string;
  symbol: string;
  display: string;
  status: string;
  action: string | null;
  panel_kapsaminda: boolean;
}

interface ScanNowResponse {
  status: string;
  scanned_at: string;
  total_rows: number;
  candidates_count: number;
  sessions_active: string[];
  entry_hour_blocked: boolean;
  motor_enabled: boolean;
  rows: ScanNowRow[];
}

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
  breakeven_activated?: boolean;
  trailing_activated?: boolean;
  open_time: string;
  pnl_usd: number;
  pnl_pips: number;
  strategy?: string;
}

interface DecisionLog {
  id: string;
  time: string;
  category: string;
  symbol?: string;
  strategy?: string;
  strategy_label?: string;
  message: string;
}

interface MT5Position {
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
  protection?: string;
  protection_label?: string;
  open_time: string;
  strategy?: string;
  strategy_label?: string;
}

interface MT5State {
  connected: boolean;
  auto_trade: boolean;
  account: {
    balance: number;
    equity: number;
    currency: string;
  } | null;
  open_positions: MT5Position[];
}

const TIER_META: Record<Tier, { label: string; badge: string; dot: string; hint: string }> = {
  STRONG: {
    label: "GÜÇLÜ",
    badge: "bg-emerald-500/20 text-emerald-300 border-emerald-400/50",
    dot: "bg-emerald-400",
    hint: "Tüm giriş kapıları açık — otonom motor bu sinyalle işlem açabilir.",
  },
  ACTIVE: {
    label: "AÇIK POZ",
    badge: "bg-blue-500/20 text-blue-300 border-blue-400/50",
    dot: "bg-blue-400",
    hint: "Sinyal onaylı fakat bu sembolde zaten açık pozisyon var.",
  },
  WATCH: {
    label: "İZLE",
    badge: "bg-amber-500/20 text-amber-300 border-amber-400/50",
    dot: "bg-amber-400",
    hint: "Kalite kapıları temiz; yalnızca zamanlama (seans/volatilite) uygun değil.",
  },
  WAIT: {
    label: "BEKLE",
    badge: "bg-bunker-800 text-bunker-muted border-bunker-700",
    dot: "bg-bunker-600",
    hint: "Sinyal giriş kalitesinde değil — engel gerekçesi satırda yazılı.",
  },
};

const ARM_META: Record<string, { label: string; medal: string }> = {
  RADAR: { label: "Klasik Radar", medal: "bg-blue-500/15 text-blue-300 border-blue-500/40" },
  DONCHIAN_ADX: { label: "Donchian ADX", medal: "bg-purple-500/15 text-purple-300 border-purple-500/40" },
  EMA_ADX_PULLBACK_M5: { label: "EMA+ADX", medal: "bg-cyan-500/15 text-cyan-300 border-cyan-500/40" },
  S3_5M: { label: "S3 · 5m", medal: "bg-amber-500/15 text-amber-300 border-amber-500/40" },
  S3_15M: { label: "S3 · 15m", medal: "bg-amber-500/15 text-amber-300 border-amber-500/40" },
  LONDON_BREAKOUT: { label: "London Breakout", medal: "bg-orange-500/15 text-orange-300 border-orange-500/40" },
  LONDON_SIGN: { label: "London Sign", medal: "bg-fuchsia-500/15 text-fuchsia-300 border-fuchsia-500/40" },
  SQUEEZE_KC_M15: { label: "Keltner Squeeze · 15m", medal: "bg-teal-500/15 text-teal-300 border-teal-500/40" },
  COMBO3_M5: { label: "Combo3 · 5m", medal: "bg-rose-500/15 text-rose-300 border-rose-500/40" },
  KOMBO_M5: { label: "Kombo XAU · 5m", medal: "bg-fuchsia-500/15 text-fuchsia-300 border-fuchsia-500/40" },
};

const ARM_ORDER: string[] = [
  "RADAR",
  "LONDON_SIGN",
  "DONCHIAN_ADX",
  "EMA_ADX_PULLBACK_M5",
  "S3_5M",
  "S3_15M",
  "LONDON_BREAKOUT",
  "SQUEEZE_KC_M15",
  "COMBO3_M5",
  "KOMBO_M5",
];

function armMeta(strategy: string) {
  return (
    ARM_META[strategy] || {
      label: strategy || "Bilinmeyen",
      medal: "bg-bunker-800 text-bunker-muted border-bunker-700",
    }
  );
}

function optNum(v: unknown): number | null {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

function supertrendText(dir: number): { text: string; tone: string } {
  if (dir > 0) return { text: "▲ BOĞA", tone: "text-emerald-400" };
  if (dir < 0) return { text: "▼ AYI", tone: "text-rose-400" };
  return { text: "—", tone: "text-bunker-muted" };
}

function adxTone(adx: number): string {
  if (adx >= 25) return "text-emerald-400";
  if (adx >= 20) return "text-yellow-400";
  return "text-bunker-muted";
}

function fmtRsi(c: { rsi_5m?: number | null; rsi_15m?: number | null }): string {
  const n = optNum(c.rsi_5m) ?? optNum(c.rsi_15m);
  return n == null ? "—" : n.toFixed(0);
}

function fmtTp(v: unknown): string {
  const n = optNum(v);
  return n == null ? "—" : `+${n}p`;
}

function fmtSl(v: unknown): string {
  const n = optNum(v);
  return n == null ? "—" : `-${n}p`;
}

function fmtRr(v: unknown): string {
  if (typeof v === "number" && Number.isFinite(v)) return String(v);
  if (typeof v === "string" && v.trim()) return v.trim();
  return "—";
}

function radarQuote(c: { bid?: number | null; ask?: number | null; price?: number | null; error?: string | null }): {
  text: string;
  failed: boolean;
} {
  const err = typeof c.error === "string" ? c.error.trim() : "";
  const bid = formatPrice(c.bid);
  const ask = formatPrice(c.ask);
  if (err && bid === "—" && ask === "—") return { text: err, failed: true };
  if (bid !== "—" && ask !== "—") return { text: `${bid} / ${ask}`, failed: false };
  return { text: formatPrice(c.price), failed: false };
}

function motorOpens(c: { motor_acar?: boolean; tier?: string }): boolean {
  if (typeof c.motor_acar === "boolean") return c.motor_acar;
  return c.tier === "STRONG";
}

function scorePassed(c: ForexCandidate): boolean {
  if (typeof c.skor_gecti === "boolean") return c.skor_gecti;
  const req = optNum(c.required_score);
  return req != null && c.score >= req;
}

function scoreTone(score: number, required: number | null, passed: boolean): string {
  if (passed) return "text-emerald-400";
  if (required != null && score >= required - 10) return "text-yellow-400";
  return "text-bunker-muted";
}

function fmtUsd(v: number): string {
  const sign = v > 0 ? "+" : v < 0 ? "-" : "";
  return `${sign}$${Math.abs(v).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function matchesCategoryPill(c: ForexCandidate, pill: CategoryPill): boolean {
  if (pill === "ALL") return true;
  const sym = c.symbol.toUpperCase();
  const isCrypto = c.category === "crypto" || ["BTCUSD", "ETHUSD", "XRPUSD"].includes(sym);
  const isGoldIndex =
    c.category === "commodity" ||
    c.category === "index" ||
    sym.includes("XAU") ||
    sym.includes("US30") ||
    sym.includes("NAS100") ||
    sym.includes("USTEC");
  if (pill === "crypto") return isCrypto;
  if (pill === "gold_index") return isGoldIndex;
  if (pill === "forex") return !isCrypto && !isGoldIndex;
  return true;
}

const DEFAULT_SETTINGS: AutoSettings = {
  enabled: false,
  balance: 1000,
  risk_per_trade_pct: 1.0,
  max_open_positions: 5,
  min_score: 75,
  tp_pips: 25,
  sl_pips: 15,
  breakeven_pips: 10,
  trailing_stop_pips: 12,
  session_filter: true,
  max_spread_pips: 3.0,
  allowed_symbols: ["XAUUSD", "BTCUSD", "US30", "NAS100", "AUDCAD"],
};

export default function ForexRadarPage() {
  // Sekme durumu (URL ?tab= ile senkronize)
  const [activeTab, setActiveTab] = useState<MainTab>("radar");

  useEffect(() => {
    if (typeof window === "undefined") return;
    const params = new URLSearchParams(window.location.search);
    const t = params.get("tab");
    if (t === "opportunity" || t === "positions" || t === "radar") {
      setActiveTab(t);
    }
  }, []);

  const selectTab = useCallback((next: MainTab) => {
    setActiveTab(next);
    if (typeof window !== "undefined") {
      const url = new URL(window.location.href);
      if (next === "radar") url.searchParams.delete("tab");
      else url.searchParams.set("tab", next);
      window.history.replaceState({}, "", url.toString());
    }
  }, []);

  // Radar & Piyasa verileri
  const [candidates, setCandidates] = useState<ForexCandidate[]>([]);
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [scanNote, setScanNote] = useState<string>("");
  const [thresholds, setThresholds] = useState<RadarThresholds | null>(null);
  const [csm, setCsm] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [radarError, setRadarError] = useState("");
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  // Otonom motor & MT5 durumu
  const [autoEnabled, setAutoEnabled] = useState(false);
  const [togglingAuto, setTogglingAuto] = useState(false);
  const [appliedSettings, setAppliedSettings] = useState<AutoSettings>(DEFAULT_SETTINGS);
  const [paperBalance, setPaperBalance] = useState<number>(1000);
  const [paperEquity, setPaperEquity] = useState<number>(1000);
  const [dailyPnlUsd, setDailyPnlUsd] = useState<number>(0);
  const [openPnlUsd, setOpenPnlUsd] = useState<number>(0);
  const [paperPositions, setPaperPositions] = useState<AutoPosition[]>([]);
  const [decisionLogs, setDecisionLogs] = useState<DecisionLog[]>([]);
  const [mt5, setMt5] = useState<MT5State>({
    connected: false,
    auto_trade: false,
    account: null,
    open_positions: [],
  });

  // Çoklu strateji taraması
  const [scanning, setScanning] = useState(false);
  const [scanNowResult, setScanNowResult] = useState<ScanNowResponse | null>(null);
  const [armFilter, setArmFilter] = useState<string>("ALL");
  const [notice, setNotice] = useState<{ ok: boolean; text: string } | null>(null);

  // Periyodik fırsat taraması özeti (KPI + sekme etiketi için)
  const [oppSummary, setOppSummary] = useState<OpportunityScanSummary>({
    enabled: false,
    running: false,
    intervalMin: 10,
    lastRunAt: null,
    nextRunAt: null,
    openedCount: 0,
    candidatesCount: 0,
  });

  // Canlı Radar filtreleri
  const [categoryPill, setCategoryPill] = useState<CategoryPill>("ALL");
  const [onlyReady, setOnlyReady] = useState<boolean>(false);
  const [directionFilter, setDirectionFilter] = useState<"ALL" | "BUY" | "SELL">("ALL");
  const [searchQuery, setSearchQuery] = useState<string>("");

  // Modallar & Kapı Anlık Görünümü
  const [chartModalCandidate, setChartModalCandidate] = useState<ForexCandidate | null>(null);
  const [chartModalSymbol, setChartModalSymbol] = useState<{
    symbol: string;
    display?: string;
    action?: "BUY" | "SELL" | "HOLD";
  } | null>(null);
  const [showSettingsModal, setShowSettingsModal] = useState(false);
  const [showEVShieldModal, setShowEVShieldModal] = useState(false);
  const [gateModalSymbol, setGateModalSymbol] = useState<string | null>(null);
  const [gateSnapshot, setGateSnapshot] = useState<GateSnapshot | null>(null);
  const [gateLoading, setGateLoading] = useState(false);

  useEffect(() => {
    if (!gateModalSymbol) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") setGateModalSymbol(null);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [gateModalSymbol]);

  // Hızlı Lot Hesaplayıcı
  const [calcBalance, setCalcBalance] = useState<number>(10000);
  const [calcRiskPct, setCalcRiskPct] = useState<number>(1.0);
  const [calcSlPips, setCalcSlPips] = useState<number>(20);
  const [calcSymbol, setCalcSymbol] = useState<string>("EURUSD");
  const [calcResult, setCalcResult] = useState<any>(null);
  const [calcError, setCalcError] = useState("");
  const [lotCalcOpen, setLotCalcOpen] = useState(false);

  const flashNotice = useCallback((text: string, ok = true) => {
    setNotice({ ok, text });
  }, []);

  // --- VERİ ÇEKME ---
  const applyAutoStatus = useCallback((res: any) => {
    if (!res || typeof res !== "object") return;
    setAutoEnabled(Boolean(res.enabled));
    if (res.settings && typeof res.settings === "object") {
      setAppliedSettings((prev) => ({ ...prev, ...res.settings, enabled: Boolean(res.enabled) }));
    }
    if (typeof res.balance === "number") setPaperBalance(res.balance);
    if (typeof res.equity === "number") setPaperEquity(res.equity);
    else if (typeof res.balance === "number") setPaperEquity(res.balance);
    if (typeof res.daily_pnl === "number") setDailyPnlUsd(res.daily_pnl);
    if (typeof res.open_pnl_usd === "number") setOpenPnlUsd(res.open_pnl_usd);
    if (Array.isArray(res.open_positions)) setPaperPositions(res.open_positions);
    if (Array.isArray(res.decision_logs)) setDecisionLogs(res.decision_logs);
  }, []);

  // WS canlı fx_state dinleyicisi & bağlantı durumu
  const wsStatus = useLiveStatus();
  useLiveMessages(
    useCallback(
      (msg: LiveMessage) => {
        if (msg.type === "fx_state" && msg.data) {
          applyAutoStatus(msg.data);
        }
      },
      [applyAutoStatus],
    ),
  );

  const fetchRadar = useCallback(async () => {
    try {
      const data = await apiFetch("/api/forex/radar");
      if (data && Array.isArray(data.candidates)) {
        setCandidates(data.candidates);
        setSessions(data.sessions || []);
        setScanNote(data.scan_note || "");
        setThresholds(data.thresholds || null);
        setCsm(data.csm || null);
        setLastUpdated(new Date());
        setRadarError("");
      }
    } catch (err) {
      const detail = err instanceof Error ? err.message : "Radar verisi alınamadı";
      setRadarError(`Radar verisi alınamadı: ${detail}`);
    } finally {
      setLoading(false);
    }
  }, []);

  const fetchEngineAndMt5 = useCallback(async () => {
    const [statusRes, mt5Res] = await Promise.allSettled([
      apiFetch("/api/forex/auto-paper/status"),
      apiFetch("/api/forex/mt5/status"),
    ]);
    if (statusRes.status === "fulfilled" && statusRes.value) {
      applyAutoStatus(statusRes.value);
    }
    if (mt5Res.status === "fulfilled" && mt5Res.value) {
      setMt5({
        connected: Boolean(mt5Res.value.connected),
        auto_trade: Boolean(mt5Res.value.auto_trade),
        account: mt5Res.value.account ?? null,
        open_positions: Array.isArray(mt5Res.value.open_positions) ? mt5Res.value.open_positions : [],
      });
    }
  }, [applyAutoStatus]);

  const fetchStrategyScan = useCallback(async () => {
    try {
      const res = await apiFetch("/api/forex/auto-paper/strategy-scan");
      if (res && res.rows) setScanNowResult(res);
    } catch {
      /* ikincil bilgi, sessiz geç */
    }
  }, []);

  // İlk açılışta fırsat taraması KPI özeti için tek yoklama (sekme kapalıyken de güncel kalsın)
  const fetchOppSummary = useCallback(async () => {
    try {
      const res = await apiFetch("/api/forex/opportunity-scan/latest");
      if (res && typeof res === "object") {
        const rawInt = res.interval_minutes ?? res.interval_min;
        const intervalMin =
          typeof rawInt === "number" && Number.isFinite(rawInt) && rawInt > 0 ? rawInt : 10;
        const openedArr = res.opened ?? res.result?.opened ?? res.last_opened ?? [];
        const candArr = res.candidates ?? res.top_candidates ?? res.scan?.top ?? [];
        setOppSummary({
          enabled: Boolean(res.enabled),
          running: Boolean(res.running),
          intervalMin,
          lastRunAt: res.last_run_at ?? res.last_run_ts ?? res.scanned_at ?? null,
          nextRunAt: res.next_run_at ?? res.next_run_ts ?? null,
          openedCount: Array.isArray(openedArr) ? openedArr.length : 0,
          candidatesCount: Array.isArray(candArr) ? candArr.length : 0,
        });
      }
    } catch {
      /* endpoint henüz hazır değilse varsayılan 10 dk gösterilir */
    }
  }, []);

  usePolling(fetchRadar, 3000);
  usePolling(fetchEngineAndMt5, 5000);
  usePolling(fetchStrategyScan, 8000);
  usePolling(fetchOppSummary, 15_000, { enabled: activeTab !== "opportunity" });

  // Lot hesaplayıcı
  useEffect(() => {
    if (!lotCalcOpen) return;
    let cancelled = false;
    (async () => {
      try {
        const res = await apiFetch("/api/forex/calculate-lot", {
          method: "POST",
          body: JSON.stringify({
            account_balance: calcBalance,
            risk_percentage: calcRiskPct,
            stop_loss_pips: calcSlPips,
            symbol: calcSymbol,
          }),
        });
        if (!cancelled) {
          setCalcResult(res);
          setCalcError("");
        }
      } catch (err) {
        if (!cancelled) {
          setCalcResult(null);
          setCalcError(err instanceof Error ? err.message : "Lot hesaplanamadı");
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [lotCalcOpen, calcBalance, calcRiskPct, calcSlPips, calcSymbol]);

  // --- EYLEMLER ---
  const toggleAutoTrade = async () => {
    setTogglingAuto(true);
    try {
      const next = !autoEnabled;
      const res = await apiFetch("/api/forex/auto-paper/toggle", {
        method: "POST",
        body: JSON.stringify({ enabled: next }),
      });
      setAutoEnabled(Boolean(res?.enabled ?? next));
      flashNotice(
        (res?.enabled ?? next)
          ? "Otonom Forex motoru açıldı."
          : "Otonom Forex motoru durduruldu.",
        true,
      );
      void fetchEngineAndMt5();
    } catch (err) {
      flashNotice(
        `Motor durumu değiştirilemedi: ${err instanceof Error ? err.message : "Hata"}`,
        false,
      );
    } finally {
      setTogglingAuto(false);
    }
  };

  const runScanNow = async () => {
    setScanning(true);
    try {
      const res = await apiFetch("/api/forex/auto-paper/scan-now", { method: "POST" });
      setArmFilter("ALL");
      setScanNowResult(res);
      const rows = Number(res?.total_rows ?? res?.rows?.length ?? 0);
      const cands = Number(res?.candidates_count ?? 0);
      flashNotice(`Tarama tamamlandı: ${cands}/${rows} kol canlı aday üretti.`, true);
      void fetchRadar();
    } catch (err) {
      flashNotice(
        `Tarama başarısız: ${err instanceof Error ? err.message : "Hata"}`,
        false,
      );
    } finally {
      setScanning(false);
    }
  };

  const openGateSnapshot = async (symbol: string) => {
    setGateModalSymbol(symbol);
    setGateSnapshot(null);
    setGateLoading(true);
    try {
      const res = (await apiFetch(`/api/forex/auto-paper/gate-snapshot/${encodeURIComponent(symbol)}`)) as GateSnapshot;
      setGateSnapshot(res);
    } catch (err) {
      flashNotice(
        `${symbol} kapı durumu alınamadı: ${err instanceof Error ? err.message : "Hata"}`,
        false,
      );
      setGateModalSymbol(null);
    } finally {
      setGateLoading(false);
    }
  };

  const openChartBySymbol = useCallback(
    (symbol: string, action?: "BUY" | "SELL" | "HOLD", display?: string) => {
      const upper = symbol.trim().toUpperCase();
      if (!upper) return;
      const found = candidates.find((c) => c.symbol.toUpperCase() === upper);
      if (found) {
        setChartModalSymbol(null);
        setChartModalCandidate(found);
      } else {
        setChartModalCandidate(null);
        setChartModalSymbol({ symbol: upper, display: display || upper, action });
      }
    },
    [candidates],
  );

  const closeMt5Position = async (ticket: number) => {
    if (!window.confirm(`#${ticket} numaralı MT5 pozisyonunu kapatmak istiyor musunuz?`)) return;
    try {
      await apiFetch("/api/forex/mt5/close", {
        method: "POST",
        body: JSON.stringify({ ticket }),
      });
      flashNotice(`#${ticket} kapatma emri MT5 köprüsüne iletildi.`, true);
      void fetchEngineAndMt5();
    } catch (err) {
      flashNotice(
        `Pozisyon kapatılamadı: ${err instanceof Error ? err.message : "Hata"}`,
        false,
      );
    }
  };

  // --- HESAPLANMIŞ VERİLER ---
  const strongSignals = useMemo(
    () => candidates.filter((c) => motorOpens(c)),
    [candidates],
  );

  const watchCount = useMemo(
    () => candidates.filter((c) => c.tier === "WATCH").length,
    [candidates],
  );

  const activeSessions = useMemo(
    () => sessions.filter((s) => s.active),
    [sessions],
  );

  const visibleCandidates = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();
    return candidates.filter((c) => {
      if (!matchesCategoryPill(c, categoryPill)) return false;
      if (onlyReady && !(motorOpens(c) || c.tier === "WATCH" || c.tier === "ACTIVE")) return false;
      if (directionFilter !== "ALL" && c.action !== directionFilter) return false;
      if (q && !`${c.display} ${c.symbol} ${c.name}`.toLowerCase().includes(q)) return false;
      return true;
    });
  }, [candidates, categoryPill, onlyReady, directionFilter, searchQuery]);

  const filtersActive =
    categoryPill !== "ALL" || onlyReady || directionFilter !== "ALL" || searchQuery.trim() !== "";

  const displayBalance = mt5.connected && mt5.account ? mt5.account.balance : paperBalance;
  const displayEquity = mt5.connected && mt5.account ? mt5.account.equity : paperEquity;
  const totalOpenPositions = mt5.connected ? mt5.open_positions.length : paperPositions.length;
  const totalFloatingPnl = mt5.connected
    ? mt5.open_positions.reduce((acc, p) => acc + (Number(p.pnl_usd) || 0), 0)
    : openPnlUsd;

  const armStats = useMemo(() => {
    const rows = scanNowResult?.rows || [];
    const byArm = new Map<string, { strategy: string; total: number; candidates: number }>();
    for (const r of rows) {
      const key = r.strategy || "—";
      const cur = byArm.get(key) || { strategy: key, total: 0, candidates: 0 };
      cur.total += 1;
      if (r.action) cur.candidates += 1;
      byArm.set(key, cur);
    }
    const known = ARM_ORDER.filter((a) => byArm.has(a)).map((a) => byArm.get(a)!);
    const unknown = [...byArm.values()]
      .filter((a) => !ARM_ORDER.includes(a.strategy))
      .sort((x, y) => x.strategy.localeCompare(y.strategy));
    return [...known, ...unknown];
  }, [scanNowResult]);

  const visibleScanRows = useMemo(() => {
    const rows = scanNowResult?.rows || [];
    return armFilter === "ALL" ? rows : rows.filter((r) => r.strategy === armFilter);
  }, [scanNowResult, armFilter]);

  // Klavye sekme navigasyonu (APG tabs pattern)
  const tabOrder: MainTab[] = ["radar", "opportunity", "positions"];
  const handleTabKeyDown = (e: React.KeyboardEvent<HTMLButtonElement>, current: MainTab) => {
    const idx = tabOrder.indexOf(current);
    if (e.key === "ArrowRight") {
      e.preventDefault();
      selectTab(tabOrder[(idx + 1) % tabOrder.length]);
    } else if (e.key === "ArrowLeft") {
      e.preventDefault();
      selectTab(tabOrder[(idx - 1 + tabOrder.length) % tabOrder.length]);
    }
  };

  return (
    <div className="space-y-5 pb-12">
      {/* 1. KOMPAKT ÜST BAŞLIK ÇUBUĞU */}
      <header className="p-3.5 sm:p-4 rounded-2xl border border-bunker-800 bg-bunker-900/80 backdrop-blur-md shadow-lg">
        <div className="flex flex-col xl:flex-row xl:items-center justify-between gap-3">
          {/* Sol: Başlık + Bağlantı + Aktif Seans */}
          <div className="flex flex-wrap items-center gap-2.5 min-w-0">
            <h1 className="text-lg sm:text-xl font-bold font-mono text-white tracking-tight">
              Forex Radar &amp; Otonom Motor
            </h1>

            {/* MT5 / WS Canlı Durum */}
            <span
              className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full border font-mono text-2xs font-bold ${
                mt5.connected
                  ? "bg-emerald-500/15 border-emerald-500/40 text-emerald-300"
                  : wsStatus === "open"
                    ? "bg-cyan-500/15 border-cyan-500/40 text-cyan-300"
                    : "bg-bunker-800 border-bunker-700 text-bunker-muted"
              }`}
              title={`MT5: ${mt5.connected ? "Bağlı" : "Bağlı değil"} · Canlı Akış: ${wsStatus}`}
            >
              <span
                className={`w-2 h-2 rounded-full ${
                  mt5.connected
                    ? "bg-emerald-400 animate-pulse"
                    : wsStatus === "open"
                      ? "bg-cyan-400"
                      : "bg-bunker-600"
                }`}
                aria-hidden="true"
              />
              {mt5.connected ? "MT5 CANLI" : wsStatus === "open" ? "WS CANLI" : "BEKLEMEDE"}
            </span>

            {/* Aktif Seans Pili */}
            <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full border border-bunker-700 bg-bunker-950/70 font-mono text-2xs text-bunker-muted">
              {activeSessions.length > 0 ? (
                <>
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" aria-hidden="true" />
                  <span className="text-white font-semibold">
                    {activeSessions.map((s) => `${s.flag} ${s.name}`).join(" · ")}
                  </span>
                </>
              ) : (
                <span>Seans dışı / 7/24 Kripto</span>
              )}
            </span>

            {lastUpdated && (
              <span className="font-mono text-2xs text-bunker-muted tabular-nums hidden sm:inline">
                {lastUpdated.toLocaleTimeString("tr-TR")}
              </span>
            )}
          </div>

          {/* Sağ: Temiz Eylem Kontrolleri */}
          <div className="flex flex-wrap items-center gap-2">
            {/* Otonom Motor Toggle */}
            <button
              type="button"
              disabled={togglingAuto}
              aria-pressed={autoEnabled}
              onClick={() => void toggleAutoTrade()}
              className={`min-h-10 px-3 rounded-lg border font-mono text-xs font-bold transition-colors inline-flex items-center gap-2 disabled:opacity-50 ${
                autoEnabled
                  ? "bg-emerald-500/20 border-emerald-400/50 text-emerald-300 hover:bg-emerald-500/30"
                  : "bg-bunker-800 border-bunker-700 text-bunker-muted hover:text-white"
              }`}
              title="Otonom Forex motorunu aç veya duraklat"
            >
              <span
                className={`w-2 h-2 rounded-full ${autoEnabled ? "bg-emerald-400" : "bg-bunker-600"}`}
                aria-hidden="true"
              />
              {autoEnabled ? "Otonom AÇIK" : "Otonom KAPALI"}
            </button>

            {/* Şimdi Tara */}
            <button
              type="button"
              onClick={() => void runScanNow()}
              disabled={scanning}
              className="min-h-10 px-3.5 rounded-lg font-mono text-xs font-bold bg-cyan-400 text-bunker-950 hover:bg-sky-400 disabled:bg-bunker-700 disabled:text-bunker-muted disabled:cursor-not-allowed transition-colors inline-flex items-center gap-2"
              title="Tüm strateji kollarını tek turda tarar"
            >
              {scanning ? (
                <>
                  <span className="inline-block w-3 h-3 border-2 border-bunker-950/40 border-t-bunker-950 rounded-full animate-spin" />
                  Taranıyor…
                </>
              ) : (
                "Şimdi Tara"
              )}
            </button>

            {/* Ayarlar */}
            <button
              type="button"
              onClick={() => setShowSettingsModal(true)}
              className="min-h-10 px-3 rounded-lg border border-bunker-700 bg-bunker-950/80 text-white hover:border-cyan-400/50 hover:text-cyan-300 font-mono text-xs font-bold transition-colors"
            >
              Ayarlar
            </button>

            {/* EV Kalkanı */}
            <button
              type="button"
              onClick={() => setShowEVShieldModal(true)}
              className="min-h-10 px-3 rounded-lg border border-bunker-700 bg-bunker-950/80 text-amber-300 hover:border-amber-400/50 hover:bg-amber-500/10 font-mono text-xs font-bold transition-colors"
            >
              EV Kalkanı
            </button>

            {/* Ekonomik Takvim */}
            <Link
              href="/forex/calendar"
              className="min-h-10 px-3 rounded-lg border border-bunker-700 bg-bunker-950/80 text-bunker-muted hover:text-white hover:border-bunker-600 font-mono text-xs font-bold transition-colors inline-flex items-center"
            >
              Takvim
            </Link>
          </div>
        </div>
      </header>

      {/* Bildirim / Hata Satırı */}
      {notice && (
        <div
          role="status"
          className={`px-4 py-2.5 rounded-xl border font-mono text-xs flex items-center justify-between gap-2 ${
            notice.ok
              ? "bg-emerald-500/10 border-emerald-500/40 text-emerald-300"
              : "bg-rose-500/10 border-rose-500/40 text-rose-300"
          }`}
        >
          <span>{notice.text}</span>
          <button
            type="button"
            onClick={() => setNotice(null)}
            aria-label="Bildirimi kapat"
            className="text-xs opacity-75 hover:opacity-100 px-1.5"
          >
            ✕
          </button>
        </div>
      )}

      {/* 2. KOMPAKT 4-KPI ŞERİDİ */}
      <section aria-label="Özet Göstergeler" className="grid grid-cols-2 lg:grid-cols-4 gap-3 font-mono tabular-nums">
        {/* KPI 1: Bakiye / Özsermaye & Günlük K/Z */}
        <div className="p-3.5 rounded-2xl border border-bunker-800 bg-bunker-900/75 space-y-1">
          <div className="flex items-center justify-between text-2xs text-bunker-muted uppercase">
            <span>{mt5.connected ? "MT5 Özsermaye" : "Bakiye / Özsermaye"}</span>
            <span className={dailyPnlUsd >= 0 ? "text-emerald-400 font-bold" : "text-rose-400 font-bold"}>
              Gün: {fmtUsd(dailyPnlUsd)}
            </span>
          </div>
          <div className="text-lg sm:text-xl font-black text-white">
            ${displayEquity.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
          </div>
          <div className="text-2xs text-bunker-muted">
            Bakiye: ${displayBalance.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
          </div>
        </div>

        {/* KPI 2: Açık Pozisyonlar */}
        <button
          type="button"
          onClick={() => selectTab("positions")}
          className="text-left p-3.5 rounded-2xl border border-bunker-800 bg-bunker-900/75 hover:border-bunker-700 transition-colors space-y-1"
        >
          <div className="flex items-center justify-between text-2xs text-bunker-muted uppercase">
            <span>Açık Pozisyonlar</span>
            <span className="text-cyan-300">{mt5.connected ? "MT5" : "Paper"}</span>
          </div>
          <div className="flex items-baseline gap-2">
            <span className="text-lg sm:text-xl font-black text-white">{totalOpenPositions}</span>
            <span
              className={`text-sm font-bold ${
                totalFloatingPnl > 0
                  ? "text-emerald-400"
                  : totalFloatingPnl < 0
                    ? "text-rose-400"
                    : "text-bunker-muted"
              }`}
            >
              {fmtUsd(totalFloatingPnl)}
            </span>
          </div>
          <div className="text-2xs text-bunker-muted">Anlık yüzen K/Z · detay için tıkla</div>
        </button>

        {/* KPI 3: Güçlü Radar Sinyali */}
        <button
          type="button"
          onClick={() => {
            selectTab("radar");
            if (strongSignals.length > 0) setOnlyReady(true);
          }}
          className={`text-left p-3.5 rounded-2xl border transition-colors space-y-1 ${
            strongSignals.length > 0
              ? "border-emerald-500/40 bg-emerald-950/20 hover:border-emerald-400/60"
              : "border-bunker-800 bg-bunker-900/75 hover:border-bunker-700"
          }`}
        >
          <div className="flex items-center justify-between text-2xs text-bunker-muted uppercase">
            <span>Güçlü Radar Sinyali</span>
            <span className="text-amber-300">{watchCount} izle</span>
          </div>
          <div className="text-lg sm:text-xl font-black text-emerald-400">
            {strongSignals.length}
          </div>
          <div className="text-2xs text-bunker-muted truncate">
            {strongSignals.length > 0
              ? strongSignals.map((s) => s.display).slice(0, 3).join(", ")
              : `${candidates.length} sembol taranıyor`}
          </div>
        </button>

        {/* KPI 4: Otonom Fırsat Taraması */}
        <button
          type="button"
          onClick={() => selectTab("opportunity")}
          className="text-left p-3.5 rounded-2xl border border-bunker-800 bg-bunker-900/75 hover:border-cyan-500/40 transition-colors space-y-1"
        >
          <div className="flex items-center justify-between text-2xs text-bunker-muted uppercase">
            <span>Fırsat Taraması</span>
            <span
              className={`font-bold ${
                oppSummary.enabled ? "text-emerald-400" : "text-bunker-muted"
              }`}
            >
              {oppSummary.enabled ? `AKTİF (${oppSummary.intervalMin} dk)` : "PASİF"}
            </span>
          </div>
          <div className="flex items-baseline gap-2">
            <span className="text-lg sm:text-xl font-black text-white">
              {oppSummary.openedCount}
            </span>
            <span className="text-2xs text-bunker-muted">son turda açılan</span>
          </div>
          <div className="text-2xs text-bunker-muted truncate">
            {oppSummary.lastRunAt ? formatUtc3(oppSummary.lastRunAt) : "Henüz çalıştırılmadı"}
          </div>
        </button>
      </section>

      {/* 3. TEMİZ 3-SEKMELİ SEGMENTED NAVİGASYON */}
      <div
        role="tablist"
        aria-label="Forex Radar Bölümleri"
        className="section-tabs"
      >
        <button
          type="button"
          role="tab"
          id="tab-radar"
          aria-selected={activeTab === "radar"}
          aria-controls="panel-radar"
          onClick={() => selectTab("radar")}
          onKeyDown={(e) => handleTabKeyDown(e, "radar")}
          className={activeTab === "radar" ? "active" : ""}
        >
          Canlı Radar
          {strongSignals.length > 0 && (
            <span className="ml-1.5 px-1.5 py-0.5 rounded-full bg-emerald-500/20 text-emerald-300 text-2xs tabular-nums">
              {strongSignals.length}
            </span>
          )}
        </button>

        <button
          type="button"
          role="tab"
          id="tab-opportunity"
          aria-selected={activeTab === "opportunity"}
          aria-controls="panel-opportunity"
          onClick={() => selectTab("opportunity")}
          onKeyDown={(e) => handleTabKeyDown(e, "opportunity")}
          className={activeTab === "opportunity" ? "active" : ""}
        >
          Fırsat Taraması ({oppSummary.intervalMin} dk)
          {oppSummary.enabled && (
            <span className="ml-1.5 inline-block w-1.5 h-1.5 rounded-full bg-emerald-400 align-middle" />
          )}
        </button>

        <button
          type="button"
          role="tab"
          id="tab-positions"
          aria-selected={activeTab === "positions"}
          aria-controls="panel-positions"
          onClick={() => selectTab("positions")}
          onKeyDown={(e) => handleTabKeyDown(e, "positions")}
          className={activeTab === "positions" ? "active" : ""}
        >
          Açık Pozisyonlar &amp; Özet
          {totalOpenPositions > 0 && (
            <span className="ml-1.5 px-1.5 py-0.5 rounded-full bg-cyan-500/20 text-cyan-300 text-2xs tabular-nums">
              {totalOpenPositions}
            </span>
          )}
        </button>
      </div>

      {/* ================================================================== */}
      {/* SEKME 1: CANLI RADAR                                               */}
      {/* ================================================================== */}
      {activeTab === "radar" && (
        <div
          id="panel-radar"
          role="tabpanel"
          aria-labelledby="tab-radar"
          className="space-y-4"
        >
          {/* GÜÇLÜ SİNYALLER (İŞLEME HAZIR) */}
          {strongSignals.length > 0 && (
            <section
              aria-label="İşleme Hazır Güçlü Sinyaller"
              className="rounded-2xl border border-emerald-500/35 bg-emerald-950/15 overflow-hidden shadow-lg"
            >
              <div className="px-4 py-3 border-b border-emerald-500/20 flex flex-wrap items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" aria-hidden="true" />
                  <h2 className="font-mono text-xs font-bold text-emerald-300 uppercase tracking-wider">
                    Güçlü Sinyaller (İşleme Hazır · {strongSignals.length})
                  </h2>
                </div>
                <span className="font-mono text-2xs text-bunker-muted">
                  Tüm giriş kapıları açık
                </span>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3 p-3">
                {strongSignals.map((c) => {
                  const isBuy = c.action === "BUY";
                  return (
                    <div
                      key={c.symbol}
                      className={`p-3.5 rounded-xl border font-mono space-y-2.5 tabular-nums ${
                        isBuy
                          ? "bg-emerald-950/25 border-emerald-500/40"
                          : "bg-rose-950/25 border-rose-500/40"
                      }`}
                    >
                      <div className="flex items-start justify-between gap-2">
                        <div className="min-w-0">
                          <div className="flex items-center gap-1.5 flex-wrap">
                            <button
                              type="button"
                              onClick={() => {
                                setChartModalSymbol(null);
                                setChartModalCandidate(c);
                              }}
                              title={`${c.display} canlı grafiğini aç`}
                              className="font-bold text-white text-base hover:text-cyan-300 hover:underline decoration-cyan-400/60 underline-offset-2 text-left transition-colors cursor-pointer"
                            >
                              {c.display}
                            </button>
                            {c.dss_tier === "A+" && (
                              <span className="text-2xs px-1.5 py-0.5 rounded font-black bg-amber-500/25 border border-amber-400/60 text-amber-200">
                                A+
                              </span>
                            )}
                          </div>
                          <div className="text-2xs text-bunker-muted truncate">{c.name}</div>
                        </div>
                        <span
                          className={`px-2.5 py-1 rounded-md text-2xs font-bold border shrink-0 ${
                            isBuy
                              ? "bg-emerald-500/20 text-emerald-300 border-emerald-400/50"
                              : "bg-rose-500/20 text-rose-300 border-rose-400/50"
                          }`}
                        >
                          {isBuy ? "▲ BUY" : "▼ SELL"}
                        </span>
                      </div>

                      {c.news_info?.has_active_news && (
                        <div
                          className={`px-2 py-1 rounded-lg border text-2xs font-bold flex items-center justify-between gap-2 ${
                            c.news_info.alignment === "SUPPORTIVE"
                              ? "bg-amber-500/15 border-amber-500/40 text-amber-300"
                              : "bg-rose-500/15 border-rose-500/40 text-rose-300"
                          }`}
                        >
                          <span className="truncate">{c.news_info.badge || c.news_info.event_title}</span>
                          {c.news_info.remaining_min != null && (
                            <span className="shrink-0">{c.news_info.remaining_min.toFixed(0)} dk</span>
                          )}
                        </div>
                      )}

                      <div className="grid grid-cols-4 gap-2 p-2 rounded-lg bg-bunker-950/70 border border-bunker-800/80 text-2xs">
                        <div>
                          <span className="text-bunker-muted block">SKOR</span>
                          <span className="text-sm font-black text-emerald-400">{c.score.toFixed(1)}</span>
                        </div>
                        <div>
                          <span className="text-bunker-muted block">TP / SL</span>
                          <span className="font-bold text-white">
                            <span className="text-emerald-400">{fmtTp(c.pip_target)}</span>
                            {" / "}
                            <span className="text-rose-400">{fmtSl(c.stop_loss_pips)}</span>
                          </span>
                        </div>
                        <div>
                          <span className="text-bunker-muted block">SPREAD</span>
                          <span className="text-cyan-400 font-bold">{c.spread_pips}p</span>
                        </div>
                        <div>
                          <span className="text-bunker-muted block">ATR</span>
                          <span className="text-white font-bold">{c.atr_pips}p</span>
                        </div>
                      </div>

                      <div className="flex items-center justify-between gap-2 pt-1 border-t border-bunker-800/60 text-2xs">
                        <span className={`font-bold truncate ${radarQuote(c).failed ? "text-rose-300" : "text-white"}`}>
                          {radarQuote(c).text}
                        </span>
                        <div className="flex items-center gap-1.5 shrink-0">
                          <button
                            type="button"
                            onClick={() => void openGateSnapshot(c.symbol)}
                            className="px-2.5 py-1.5 rounded-lg bg-bunker-800 border border-bunker-700 text-bunker-muted hover:text-white font-bold transition-colors"
                          >
                            Kapılar
                          </button>
                          <button
                            type="button"
                            onClick={() => setChartModalCandidate(c)}
                            className="px-3 py-1.5 rounded-lg bg-blue-600/30 border border-blue-400/40 text-blue-300 font-bold hover:bg-blue-600/50 hover:text-white transition-colors"
                          >
                            Grafik
                          </button>
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            </section>
          )}

          {/* PİYASA TARAMA TABLOSU */}
          <section className="rounded-2xl border border-bunker-800 bg-bunker-900/75 overflow-hidden shadow-lg">
            {/* Filtre Çubuğu */}
            <div className="p-3.5 border-b border-bunker-800 flex flex-col lg:flex-row lg:items-center justify-between gap-3">
              {/* Kategori Pilleri */}
              <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label="Kategori Filtresi">
                {(
                  [
                    { id: "ALL", label: "Tümü" },
                    { id: "gold_index", label: "Altın & Endeks" },
                    { id: "crypto", label: "Kripto" },
                    { id: "forex", label: "Forex" },
                  ] as const
                ).map((cat) => (
                  <button
                    key={cat.id}
                    type="button"
                    aria-pressed={categoryPill === cat.id}
                    onClick={() => setCategoryPill(cat.id)}
                    className={`min-h-9 px-3 rounded-lg border font-mono text-xs font-bold transition-colors ${
                      categoryPill === cat.id
                        ? "bg-cyan-500/20 border-cyan-400/60 text-cyan-200"
                        : "bg-bunker-950/70 border-bunker-800 text-bunker-muted hover:text-white"
                    }`}
                  >
                    {cat.label}
                  </button>
                ))}
              </div>

              {/* Arama + Hazır Sinyal Toggle + Yön */}
              <div className="flex flex-wrap items-center gap-2 font-mono text-xs">
                <input
                  type="search"
                  placeholder="Sembol ara…"
                  aria-label="Sembol ara"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="min-h-9 bg-bunker-950 border border-bunker-700 rounded-lg px-2.5 py-1 text-white placeholder-bunker-600 outline-none focus:border-cyan-400 w-36"
                />

                <button
                  type="button"
                  aria-pressed={onlyReady}
                  onClick={() => setOnlyReady((v) => !v)}
                  className={`min-h-9 px-2.5 rounded-lg border text-xs font-bold transition-colors ${
                    onlyReady
                      ? "bg-emerald-500/20 border-emerald-400/50 text-emerald-300"
                      : "bg-bunker-950 border-bunker-700 text-bunker-muted hover:text-white"
                  }`}
                >
                  Sadece Hazır Sinyaller
                </button>

                <select
                  value={directionFilter}
                  aria-label="Yön filtresi"
                  onChange={(e) => setDirectionFilter(e.target.value as "ALL" | "BUY" | "SELL")}
                  className="min-h-9 bg-bunker-950 border border-bunker-700 rounded-lg px-2 py-1 text-white outline-none focus:border-cyan-400"
                >
                  <option value="ALL">Tüm Yönler</option>
                  <option value="BUY">▲ BUY</option>
                  <option value="SELL">▼ SELL</option>
                </select>

                {filtersActive && (
                  <button
                    type="button"
                    onClick={() => {
                      setCategoryPill("ALL");
                      setOnlyReady(false);
                      setDirectionFilter("ALL");
                      setSearchQuery("");
                    }}
                    className="text-cyan-400 hover:underline font-bold px-1"
                  >
                    Temizle
                  </button>
                )}

                <span className="text-2xs text-bunker-muted tabular-nums ml-auto lg:ml-1">
                  {visibleCandidates.length}/{candidates.length}
                </span>
              </div>
            </div>

            {radarError && candidates.length > 0 && (
              <p role="alert" className="px-4 py-2 font-mono text-xs text-rose-300 border-b border-rose-500/30 bg-rose-500/10">
                {radarError} Son başarılı tarama ekranda duruyor.
              </p>
            )}

            {loading && candidates.length === 0 ? (
              <div className="p-12 text-center font-mono text-sm text-bunker-muted">
                <div className="inline-block w-6 h-6 border-2 border-cyan-400 border-t-transparent rounded-full animate-spin mb-2" />
                <p>Forex pariteleri taranıyor…</p>
              </div>
            ) : radarError && candidates.length === 0 ? (
              <div role="alert" className="p-12 text-center space-y-3 font-mono">
                <p className="text-sm font-bold text-rose-300">{radarError}</p>
                <button
                  type="button"
                  onClick={() => {
                    setLoading(true);
                    void fetchRadar();
                  }}
                  className="px-4 py-2 rounded-lg bg-rose-500/20 border border-rose-400/40 text-rose-200 font-bold text-xs"
                >
                  Tekrar Dene
                </button>
              </div>
            ) : visibleCandidates.length === 0 ? (
              <div className="p-12 text-center space-y-2 font-mono">
                <p className="text-sm font-bold text-white">
                  {filtersActive ? "Bu filtreyle eşleşen sembol yok." : "Radar şu an sembol döndürmedi."}
                </p>
                {filtersActive && (
                  <p className="text-xs text-bunker-muted">
                    Filtreleri temizleyip tüm sembolleri görebilirsiniz.
                  </p>
                )}
              </div>
            ) : (
              <>
                {/* Masaüstü Temiz Tablo */}
                <div className="hidden md:block overflow-x-auto">
                  <table className="w-full text-left font-mono text-xs tabular-nums">
                    <thead className="bg-bunker-950/80 text-bunker-muted uppercase border-b border-bunker-800 text-2xs tracking-wider">
                      <tr>
                        <th className="py-3 px-4">Sembol</th>
                        <th className="py-3 px-3">Fiyat</th>
                        <th className="py-3 px-3">Yön</th>
                        <th className="py-3 px-3">Skor</th>
                        <th className="py-3 px-3">Spread / ATR</th>
                        <th className="py-3 px-3">Durum / Engel</th>
                        <th className="py-3 px-4 text-right">Grafik</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-bunker-800/60">
                      {visibleCandidates.map((c) => {
                        const isBuy = c.action === "BUY";
                        const isSell = c.action === "SELL";
                        const meta = TIER_META[c.tier];
                        const st = supertrendText(c.supertrend_dir);
                        return (
                          <tr
                            key={c.symbol}
                            onClick={() => setChartModalCandidate(c)}
                            className={`cursor-pointer hover:bg-bunker-800/40 transition-colors ${
                              c.tier === "STRONG" ? "bg-emerald-950/20" : ""
                            }`}
                          >
                            {/* Sembol */}
                            <td className="py-3 px-4">
                              <div className="flex items-center gap-2">
                                <button
                                  type="button"
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    setChartModalSymbol(null);
                                    setChartModalCandidate(c);
                                  }}
                                  title={`${c.display} canlı grafiğini aç`}
                                  className="font-bold text-white text-sm hover:text-cyan-300 hover:underline decoration-cyan-400/60 underline-offset-2 text-left transition-colors cursor-pointer"
                                >
                                  {c.display}
                                </button>
                                <span
                                  className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-2xs font-bold border ${meta.badge}`}
                                  title={meta.hint}
                                >
                                  <span className={`w-1.5 h-1.5 rounded-full ${meta.dot}`} />
                                  {meta.label}
                                </span>
                              </div>
                              <div className="text-2xs text-bunker-muted truncate max-w-[160px]">
                                {c.name} · <span className={adxTone(c.adx)}>ADX {c.adx.toFixed(0)}</span> ·{" "}
                                <span className={st.tone}>{st.text}</span> · RSI {fmtRsi(c)}
                              </div>
                            </td>

                            {/* Fiyat */}
                            <td className={`py-3 px-3 font-semibold whitespace-nowrap ${radarQuote(c).failed ? "text-rose-300" : "text-white"}`}>
                              {radarQuote(c).text}
                              <div className="text-2xs text-bunker-muted">
                                TP {fmtTp(c.pip_target)} / SL {fmtSl(c.stop_loss_pips)}
                              </div>
                            </td>

                            {/* Yön */}
                            <td className="py-3 px-3 whitespace-nowrap">
                              {isBuy || isSell ? (
                                <span
                                  className={`inline-flex items-center px-2.5 py-1 rounded-md text-2xs font-bold border ${
                                    isBuy
                                      ? "bg-emerald-500/15 text-emerald-400 border-emerald-500/30"
                                      : "bg-rose-500/15 text-rose-400 border-rose-500/30"
                                  }`}
                                >
                                  {isBuy ? "▲ BUY" : "▼ SELL"}
                                </span>
                              ) : (
                                <span className="inline-flex items-center px-2.5 py-1 rounded-md text-2xs font-bold bg-bunker-800 text-bunker-muted border border-bunker-700">
                                  BEKLE
                                </span>
                              )}
                            </td>

                            {/* Skor */}
                            <td className="py-3 px-3 whitespace-nowrap">
                              <div className="flex items-center gap-2">
                                <div className="w-12 bg-bunker-800 rounded-full h-1.5 overflow-hidden">
                                  <div
                                    className={`h-full rounded-full ${
                                      scorePassed(c) ? "bg-emerald-400" : "bg-blue-400"
                                    }`}
                                    style={{ width: `${Math.min(100, Math.max(0, c.score))}%` }}
                                  />
                                </div>
                                <span className={`font-bold ${scoreTone(c.score, optNum(c.required_score), scorePassed(c))}`}>
                                  {c.score.toFixed(1)}
                                </span>
                              </div>
                              <div className="text-2xs text-bunker-muted">
                                eşik {optNum(c.required_score) ?? "—"}
                              </div>
                            </td>

                            {/* Spread / ATR */}
                            <td className="py-3 px-3 whitespace-nowrap">
                              <span className="text-cyan-400 font-bold">{c.spread_pips}p</span>
                              <span className="text-bunker-600"> / </span>
                              <span className="text-white">{c.atr_pips}p</span>
                              <div className="text-2xs text-bunker-muted">R/R {fmtRr(c.risk_reward)}</div>
                            </td>

                            {/* Durum / Engel */}
                            <td className="py-3 px-3">
                              {c.primary_blocker ? (
                                <button
                                  type="button"
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    void openGateSnapshot(c.symbol);
                                  }}
                                  className="text-left text-2xs text-amber-300/90 hover:text-amber-200 hover:underline max-w-[210px] leading-snug block"
                                  title="Kapı anlık görünümünü aç"
                                >
                                  {c.blocker_text}
                                </button>
                              ) : (
                                <button
                                  type="button"
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    void openGateSnapshot(c.symbol);
                                  }}
                                  className="text-2xs text-emerald-400 font-bold hover:underline"
                                >
                                  Tüm kapılar açık
                                </button>
                              )}
                            </td>

                            {/* Grafik */}
                            <td className="py-3 px-4 text-right whitespace-nowrap">
                              <button
                                type="button"
                                onClick={(e) => {
                                  e.stopPropagation();
                                  setChartModalCandidate(c);
                                }}
                                className="px-2.5 py-1.5 rounded-lg bg-blue-500/15 text-blue-300 border border-blue-400/30 hover:bg-blue-500/30 hover:text-white transition-colors font-bold text-2xs"
                              >
                                Grafik
                              </button>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>

                {/* Mobil Kart Görünümü */}
                <div className="md:hidden space-y-2.5 p-3 font-mono tabular-nums">
                  {visibleCandidates.map((c) => {
                    const isBuy = c.action === "BUY";
                    const isSell = c.action === "SELL";
                    const meta = TIER_META[c.tier];
                    return (
                      <div
                        key={c.symbol}
                        className={`p-3.5 rounded-xl border space-y-2 ${
                          c.tier === "STRONG"
                            ? "border-emerald-500/40 bg-emerald-950/20"
                            : "border-bunker-800 bg-bunker-950/60"
                        }`}
                      >
                        <div className="flex items-center justify-between gap-2">
                          <div className="flex items-center gap-2 min-w-0">
                            <button
                              type="button"
                              onClick={() => {
                                setChartModalSymbol(null);
                                setChartModalCandidate(c);
                              }}
                              title={`${c.display} canlı grafiğini aç`}
                              className="font-bold text-white text-sm hover:text-cyan-300 hover:underline decoration-cyan-400/60 underline-offset-2 text-left transition-colors cursor-pointer"
                            >
                              {c.display}
                            </button>
                            {isBuy || isSell ? (
                              <span
                                className={`px-2 py-0.5 rounded text-2xs font-bold border ${
                                  isBuy
                                    ? "bg-emerald-500/15 text-emerald-400 border-emerald-500/30"
                                    : "bg-rose-500/15 text-rose-400 border-rose-500/30"
                                }`}
                              >
                                {isBuy ? "▲ BUY" : "▼ SELL"}
                              </span>
                            ) : (
                              <span className="px-2 py-0.5 rounded text-2xs font-bold bg-bunker-800 text-bunker-muted border border-bunker-700">
                                BEKLE
                              </span>
                            )}
                          </div>
                          <span className={`px-2 py-0.5 rounded text-2xs font-bold border ${meta.badge}`}>
                            {meta.label}
                          </span>
                        </div>

                        <div className="grid grid-cols-3 gap-2 text-2xs p-2 rounded-lg bg-bunker-900/80 border border-bunker-800">
                          <div>
                            <span className="text-bunker-muted block">SKOR</span>
                            <span className={`font-bold ${scoreTone(c.score, optNum(c.required_score), scorePassed(c))}`}>
                              {c.score.toFixed(1)}
                            </span>
                          </div>
                          <div>
                            <span className="text-bunker-muted block">SPREAD/ATR</span>
                            <span className="text-cyan-400 font-bold">
                              {c.spread_pips}p / {c.atr_pips}p
                            </span>
                          </div>
                          <div>
                            <span className="text-bunker-muted block">FİYAT</span>
                            <span className="text-white font-bold truncate block">{formatPrice(c.price)}</span>
                          </div>
                        </div>

                        {c.primary_blocker && (
                          <div className="text-2xs text-amber-300/90 leading-snug">
                            {c.blocker_text}
                          </div>
                        )}

                        <div className="flex items-center justify-end gap-2 pt-1">
                          <button
                            type="button"
                            onClick={() => void openGateSnapshot(c.symbol)}
                            className="min-h-9 px-3 rounded-lg bg-bunker-800 border border-bunker-700 text-bunker-muted hover:text-white text-2xs font-bold"
                          >
                            Kapılar
                          </button>
                          <button
                            type="button"
                            onClick={() => setChartModalCandidate(c)}
                            className="min-h-9 px-3 rounded-lg bg-blue-600/30 border border-blue-400/40 text-blue-300 text-2xs font-bold"
                          >
                            Grafik
                          </button>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </>
            )}
          </section>
        </div>
      )}

      {/* ================================================================== */}
      {/* SEKME 2: PERİYODİK FIRSAT TARAMASI                                 */}
      {/* ================================================================== */}
      {activeTab === "opportunity" && (
        <div
          id="panel-opportunity"
          role="tabpanel"
          aria-labelledby="tab-opportunity"
        >
          <OpportunityScanSection
            onSummaryChange={setOppSummary}
            onOpenChart={openChartBySymbol}
          />
        </div>
      )}

      {/* ================================================================== */}
      {/* SEKME 3: AÇIK POZİSYONLAR & ÖZET                                   */}
      {/* ================================================================== */}
      {activeTab === "positions" && (
        <div
          id="panel-positions"
          role="tabpanel"
          aria-labelledby="tab-positions"
          className="space-y-4"
        >
          {/* AÇIK POZİSYONLAR */}
          <section className="rounded-2xl border border-bunker-800 bg-bunker-900/75 overflow-hidden shadow-lg">
            <div className="px-4 py-3 border-b border-bunker-800 flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <h2 className="font-mono text-xs font-bold text-white uppercase tracking-wider">
                  Açık Pozisyonlar ({totalOpenPositions})
                </h2>
                <span className="font-mono text-2xs px-2 py-0.5 rounded bg-bunker-800 text-cyan-300 border border-bunker-700">
                  {mt5.connected ? "IC Markets MT5" : "Paper Simülasyon"}
                </span>
              </div>
              <div className="flex flex-wrap items-center gap-3">
                <Link
                  href="/forex/pozisyon-doktoru"
                  className="font-mono text-2xs font-bold px-2.5 py-1 rounded-lg border border-cyan-500/40 bg-cyan-500/10 text-cyan-300 hover:bg-cyan-500/20 transition-colors"
                >
                  AI Pozisyon Doktoru →
                </Link>
                <Link
                  href="/forex/portfolio"
                  className="font-mono text-2xs font-bold text-cyan-300 hover:underline"
                >
                  Tam Portföy Konsolu →
                </Link>
              </div>
            </div>

            {mt5.connected ? (
              mt5.open_positions.length === 0 ? (
                <p className="p-10 text-center font-mono text-xs text-bunker-muted">
                  Şu an açık MT5 pozisyonu yok.
                </p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-left font-mono text-xs tabular-nums">
                    <thead className="bg-bunker-950/80 text-bunker-muted uppercase border-b border-bunker-800 text-2xs">
                      <tr>
                        <th className="py-3 px-4">Sembol</th>
                        <th className="py-3 px-3">Yön / Lot</th>
                        <th className="py-3 px-3">Giriş / Anlık</th>
                        <th className="py-3 px-3">SL / TP</th>
                        <th className="py-3 px-3">Strateji</th>
                        <th className="py-3 px-3 text-right">Anlık K/Z</th>
                        <th className="py-3 px-4 text-right">İşlem</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-bunker-800/60">
                      {mt5.open_positions.map((p) => {
                        const isBuy = p.direction === "BUY";
                        return (
                          <tr key={p.ticket} className="hover:bg-bunker-800/30">
                            <td className="py-3 px-4 font-bold text-white">
                              <button
                                type="button"
                                onClick={() => openChartBySymbol(p.symbol, p.direction)}
                                title={`${p.symbol} canlı grafiğini aç`}
                                className="font-bold text-white hover:text-cyan-300 hover:underline decoration-cyan-400/60 underline-offset-2 text-left transition-colors cursor-pointer"
                              >
                                {p.symbol}
                              </button>
                              <div className="text-2xs text-bunker-muted">#{p.ticket}</div>
                            </td>
                            <td className="py-3 px-3 whitespace-nowrap">
                              <span
                                className={`px-2 py-0.5 rounded text-2xs font-bold border ${
                                  isBuy
                                    ? "bg-emerald-500/15 text-emerald-300 border-emerald-500/30"
                                    : "bg-rose-500/15 text-rose-300 border-rose-500/30"
                                }`}
                              >
                                {p.direction}
                              </span>
                              <span className="ml-2 text-white font-bold">{p.lots} lot</span>
                            </td>
                            <td className="py-3 px-3 whitespace-nowrap text-white">
                              {formatPrice(p.entry_price)} → {formatPrice(p.current_price)}
                            </td>
                            <td className="py-3 px-3 whitespace-nowrap text-2xs">
                              <span className="text-rose-400">{formatPrice(p.sl_price)}</span>
                              {" / "}
                              <span className="text-emerald-400">{formatPrice(p.tp_price)}</span>
                            </td>
                            <td className="py-3 px-3">
                              <span className="px-2 py-0.5 rounded bg-bunker-800 border border-bunker-700 text-2xs text-bunker-muted">
                                {p.strategy_label || p.strategy || "Manuel"}
                              </span>
                            </td>
                            <td
                              className={`py-3 px-3 text-right font-bold whitespace-nowrap ${
                                p.pnl_usd >= 0 ? "text-emerald-400" : "text-rose-400"
                              }`}
                            >
                              {fmtUsd(p.pnl_usd)}
                            </td>
                            <td className="py-3 px-4 text-right whitespace-nowrap">
                              <button
                                type="button"
                                onClick={() => void closeMt5Position(p.ticket)}
                                className="px-2.5 py-1 rounded-lg bg-rose-500/15 border border-rose-500/40 text-rose-300 hover:bg-rose-500/30 text-2xs font-bold transition-colors"
                              >
                                Kapat
                              </button>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )
            ) : paperPositions.length === 0 ? (
              <p className="p-10 text-center font-mono text-xs text-bunker-muted">
                Şu an açık paper pozisyonu yok.
              </p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-left font-mono text-xs tabular-nums">
                  <thead className="bg-bunker-950/80 text-bunker-muted uppercase border-b border-bunker-800 text-2xs">
                    <tr>
                      <th className="py-3 px-4">Sembol</th>
                      <th className="py-3 px-3">Yön / Lot</th>
                      <th className="py-3 px-3">Giriş / Anlık</th>
                      <th className="py-3 px-3">SL / TP</th>
                      <th className="py-3 px-3">Strateji</th>
                      <th className="py-3 px-4 text-right">Anlık K/Z</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-bunker-800/60">
                    {paperPositions.map((p) => {
                      const isBuy = p.direction === "BUY";
                      return (
                        <tr key={p.id} className="hover:bg-bunker-800/30">
                          <td className="py-3 px-4 font-bold text-white">
                            <button
                              type="button"
                              onClick={() => openChartBySymbol(p.symbol, p.direction, p.display)}
                              title={`${p.display || p.symbol} canlı grafiğini aç`}
                              className="font-bold text-white hover:text-cyan-300 hover:underline decoration-cyan-400/60 underline-offset-2 text-left transition-colors cursor-pointer"
                            >
                              {p.display || p.symbol}
                            </button>
                          </td>
                          <td className="py-3 px-3 whitespace-nowrap">
                            <span
                              className={`px-2 py-0.5 rounded text-2xs font-bold border ${
                                isBuy
                                  ? "bg-emerald-500/15 text-emerald-300 border-emerald-500/30"
                                  : "bg-rose-500/15 text-rose-300 border-rose-500/30"
                              }`}
                            >
                              {p.direction}
                            </span>
                            <span className="ml-2 text-white font-bold">{p.lots} lot</span>
                          </td>
                          <td className="py-3 px-3 whitespace-nowrap text-white">
                            {formatPrice(p.entry_price)} → {formatPrice(p.current_price)}
                          </td>
                          <td className="py-3 px-3 whitespace-nowrap text-2xs">
                            <span className="text-rose-400">{formatPrice(p.sl_price)}</span>
                            {" / "}
                            <span className="text-emerald-400">{formatPrice(p.tp_price)}</span>
                          </td>
                          <td className="py-3 px-3">
                            <span className="px-2 py-0.5 rounded bg-bunker-800 border border-bunker-700 text-2xs text-bunker-muted">
                              {p.strategy || "RADAR"}
                            </span>
                          </td>
                          <td
                            className={`py-3 px-4 text-right font-bold whitespace-nowrap ${
                              p.pnl_usd >= 0 ? "text-emerald-400" : "text-rose-400"
                            }`}
                          >
                            {fmtUsd(p.pnl_usd)}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          {/* DARALTILABİLİR İKİNCİL DETAYLAR */}
          <div className="space-y-3">
            {/* 1. Seanslar, Eşik Kuralları & CSM Güç Matrisi */}
            <details className="group rounded-2xl border border-bunker-800 bg-bunker-900/70 overflow-hidden">
              <summary className="cursor-pointer px-4 py-3 font-mono text-xs font-bold text-white flex items-center justify-between select-none hover:bg-bunker-800/40">
                <span>Piyasa Seansları, Giriş Eşikleri &amp; Para Birimi Güç Matrisi (CSM)</span>
                <span className="text-bunker-muted text-2xs group-open:rotate-180 transition-transform">▼</span>
              </summary>
              <div className="p-4 border-t border-bunker-800 space-y-4 font-mono">
                {/* Seanslar */}
                {sessions.length > 0 && (
                  <div className="flex flex-wrap gap-2">
                    {sessions.map((s) => (
                      <div
                        key={s.name}
                        className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border text-xs ${
                          s.active
                            ? "bg-emerald-500/15 border-emerald-500/40 text-emerald-300"
                            : "bg-bunker-950/70 border-bunker-800 text-bunker-muted"
                        }`}
                      >
                        <span aria-hidden="true">{s.flag}</span>
                        <span className="font-bold">{s.name}</span>
                        <span className="text-2xs">({s.hours_utc})</span>
                      </div>
                    ))}
                  </div>
                )}

                {/* Eşikler */}
                {thresholds && (
                  <div className="flex flex-wrap gap-x-4 gap-y-1.5 text-2xs text-bunker-muted">
                    <span>Min Skor: <strong className="text-white">{thresholds.min_score}</strong></span>
                    <span>Emtia: <strong className="text-white">{thresholds.commodity_min_score}</strong></span>
                    <span>BTC: <strong className="text-white">{thresholds.btc_min_score}</strong></span>
                    <span>Max Spread: <strong className="text-white">{thresholds.max_spread_pips}p</strong></span>
                    <span>ADX: <strong className="text-white">{thresholds.adx_filter_enabled ? `≥${thresholds.adx_min}` : "kapalı"}</strong></span>
                    <span>SuperTrend: <strong className="text-white">{thresholds.supertrend_filter_enabled ? "açık" : "kapalı"}</strong></span>
                    <span>Min ATR: <strong className="text-white">{thresholds.major_min_atr_pips}p</strong></span>
                  </div>
                )}

                {scanNote && <p className="text-2xs text-bunker-muted">{scanNote}</p>}

                {/* CSM Matrisi */}
                {csm && Array.isArray(csm.ranking) && csm.ranking.length > 0 && (
                  <div className="grid grid-cols-4 sm:grid-cols-8 gap-2 tabular-nums">
                    {csm.ranking.map(([curr, score]: [string, number], idx: number) => (
                      <div
                        key={curr}
                        className={`p-2 rounded-xl border text-center ${
                          idx === 0
                            ? "bg-emerald-950/40 border-emerald-500/50"
                            : idx === csm.ranking.length - 1
                              ? "bg-rose-950/40 border-rose-500/50"
                              : "bg-bunker-950/60 border-bunker-800"
                        }`}
                      >
                        <div className="text-2xs text-bunker-muted">#{idx + 1}</div>
                        <div className="text-sm font-black text-white">{curr}</div>
                        <div className={`text-xs font-bold ${score > 0 ? "text-emerald-400" : "text-rose-400"}`}>
                          {score > 0 ? `+${score.toFixed(1)}` : score.toFixed(1)}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </details>

            {/* 2. Çoklu Strateji Tarama Kolları */}
            {scanNowResult && (
              <details className="group rounded-2xl border border-bunker-800 bg-bunker-900/70 overflow-hidden">
                <summary className="cursor-pointer px-4 py-3 font-mono text-xs font-bold text-white flex items-center justify-between select-none hover:bg-bunker-800/40">
                  <span>
                    Çoklu Strateji Tarama Kolları ({scanNowResult.candidates_count}/{scanNowResult.total_rows} canlı aday)
                  </span>
                  <span className="text-bunker-muted text-2xs group-open:rotate-180 transition-transform">▼</span>
                </summary>
                <div className="p-4 border-t border-bunker-800 space-y-3 font-mono">
                  <div className="flex flex-wrap gap-1.5">
                    <button
                      type="button"
                      onClick={() => setArmFilter("ALL")}
                      className={`px-2 py-1 rounded-lg border text-2xs font-bold ${
                        armFilter === "ALL"
                          ? "bg-emerald-500/20 border-emerald-400/60 text-emerald-200"
                          : "bg-bunker-950 border-bunker-800 text-bunker-muted hover:text-white"
                      }`}
                    >
                      TÜMÜ · {scanNowResult.total_rows}
                    </button>
                    {armStats.map((a) => {
                      const meta = armMeta(a.strategy);
                      const on = armFilter === a.strategy;
                      return (
                        <button
                          key={a.strategy}
                          type="button"
                          onClick={() => setArmFilter(on ? "ALL" : a.strategy)}
                          className={`px-2 py-1 rounded-lg border text-2xs font-bold ${
                            on
                              ? "bg-emerald-500/20 border-emerald-400/60 text-emerald-200"
                              : a.candidates > 0
                                ? meta.medal
                                : "bg-bunker-950 border-bunker-800 text-bunker-muted hover:text-white"
                          }`}
                        >
                          {meta.label} · {a.total}
                          {a.candidates > 0 && <span className="ml-1 text-emerald-300">★{a.candidates}</span>}
                        </button>
                      );
                    })}
                  </div>

                  <div className="space-y-1 max-h-72 overflow-y-auto">
                    {visibleScanRows.map((r, i) => {
                      const meta = armMeta(r.strategy);
                      return (
                        <div
                          key={`${r.strategy}-${r.symbol}-${i}`}
                          className={`flex items-center gap-2 px-2.5 py-1.5 rounded-lg text-xs border ${
                            r.action
                              ? "bg-emerald-500/10 border-emerald-500/30"
                              : "bg-bunker-950/60 border-bunker-800"
                          }`}
                        >
                          <span className={`px-1.5 py-0.5 rounded text-2xs font-bold shrink-0 border ${meta.medal}`}>
                            {meta.label}
                          </span>
                          <span className="font-bold text-white shrink-0">{r.display}</span>
                          {r.action && (
                            <span className={`font-bold shrink-0 ${r.action === "BUY" ? "text-emerald-400" : "text-rose-400"}`}>
                              {r.action === "BUY" ? "▲ BUY" : "▼ SELL"}
                            </span>
                          )}
                          <span className="text-bunker-muted truncate">{r.status}</span>
                        </div>
                      );
                    })}
                  </div>
                </div>
              </details>
            )}

            {/* 3. Son Otonom Karar Logları */}
            <details className="group rounded-2xl border border-bunker-800 bg-bunker-900/70 overflow-hidden">
              <summary className="cursor-pointer px-4 py-3 font-mono text-xs font-bold text-white flex items-center justify-between select-none hover:bg-bunker-800/40">
                <span>Son Otonom Karar Logları ({decisionLogs.length})</span>
                <span className="text-bunker-muted text-2xs group-open:rotate-180 transition-transform">▼</span>
              </summary>
              <div className="p-4 border-t border-bunker-800 space-y-1.5 max-h-72 overflow-y-auto font-mono text-2xs">
                {decisionLogs.length === 0 ? (
                  <p className="text-bunker-muted">Henüz karar logu kaydı yok.</p>
                ) : (
                  decisionLogs.slice(0, 30).map((log, i) => (
                    <div
                      key={log.id || i}
                      className="flex flex-wrap items-baseline gap-2 px-2.5 py-1.5 rounded-lg bg-bunker-950/60 border border-bunker-800/80"
                    >
                      <span className="text-bunker-muted shrink-0">{formatUtc3(log.time)}</span>
                      <span className="px-1.5 py-0.5 rounded bg-bunker-800 text-cyan-300 font-bold shrink-0">
                        {log.category}
                      </span>
                      {log.symbol && <span className="font-bold text-white shrink-0">{log.symbol}</span>}
                      <span className="text-bunker-muted break-words">{log.message}</span>
                    </div>
                  ))
                )}
              </div>
            </details>

            {/* 4. Hızlı Lot & Risk Hesaplayıcı */}
            <details
              id="lot-calculator"
              open={lotCalcOpen}
              onToggle={(e) => setLotCalcOpen((e.currentTarget as HTMLDetailsElement).open)}
              className="group rounded-2xl border border-bunker-800 bg-bunker-900/70 overflow-hidden"
            >
              <summary className="cursor-pointer px-4 py-3 font-mono text-xs font-bold text-white flex items-center justify-between select-none hover:bg-bunker-800/40">
                <span>Forex Lot &amp; Risk Boyutlandırma Hesaplayıcısı</span>
                <span className="text-bunker-muted text-2xs group-open:rotate-180 transition-transform">▼</span>
              </summary>
              <div className="p-4 border-t border-bunker-800 space-y-4 font-mono">
                <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                  <div>
                    <label className="block text-2xs text-bunker-muted mb-1">Bakiye ($ USD)</label>
                    <input
                      type="number"
                      value={calcBalance}
                      onChange={(e) => setCalcBalance(Number(e.target.value) || 0)}
                      className="w-full bg-bunker-950 border border-bunker-700 rounded-lg px-2.5 py-1.5 text-xs text-white outline-none focus:border-cyan-400"
                    />
                  </div>
                  <div>
                    <label className="block text-2xs text-bunker-muted mb-1">Risk (%)</label>
                    <input
                      type="number"
                      step="0.1"
                      value={calcRiskPct}
                      onChange={(e) => setCalcRiskPct(Number(e.target.value) || 0)}
                      className="w-full bg-bunker-950 border border-bunker-700 rounded-lg px-2.5 py-1.5 text-xs text-white outline-none focus:border-cyan-400"
                    />
                  </div>
                  <div>
                    <label className="block text-2xs text-bunker-muted mb-1">Stop Loss (Pips)</label>
                    <input
                      type="number"
                      value={calcSlPips}
                      onChange={(e) => setCalcSlPips(Number(e.target.value) || 0)}
                      className="w-full bg-bunker-950 border border-bunker-700 rounded-lg px-2.5 py-1.5 text-xs text-white outline-none focus:border-cyan-400"
                    />
                  </div>
                  <div>
                    <label className="block text-2xs text-bunker-muted mb-1">Parite</label>
                    <select
                      value={calcSymbol}
                      onChange={(e) => setCalcSymbol(e.target.value)}
                      className="w-full bg-bunker-950 border border-bunker-700 rounded-lg px-2.5 py-1.5 text-xs text-white outline-none focus:border-cyan-400"
                    >
                      {["EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "USDCAD", "NZDUSD", "GBPJPY", "EURJPY", "XAUUSD", "BTCUSD", "NAS100", "US30"].map(
                        (s) => (
                          <option key={s} value={s}>
                            {s}
                          </option>
                        ),
                      )}
                    </select>
                  </div>
                </div>

                {calcError && <p role="alert" className="text-xs text-rose-300">{calcError}</p>}

                {calcResult && (
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-3 p-3 rounded-xl bg-bunker-950/70 border border-bunker-800 text-xs tabular-nums">
                    <div>
                      <span className="text-bunker-muted text-2xs block">RİSK TUTARI</span>
                      <span className="text-sm font-bold text-rose-400">
                        ${calcResult.risk_amount_usd?.toFixed(2)}
                      </span>
                    </div>
                    <div>
                      <span className="text-bunker-muted text-2xs block">STANDART LOT</span>
                      <span className="text-sm font-bold text-cyan-300">{calcResult.standard_lots} Lot</span>
                    </div>
                    <div>
                      <span className="text-bunker-muted text-2xs block">MİNİ LOT</span>
                      <span className="text-sm font-bold text-white">{calcResult.mini_lots} Mini</span>
                    </div>
                    <div>
                      <span className="text-bunker-muted text-2xs block">MİKRO LOT</span>
                      <span className="text-sm font-bold text-white">{calcResult.micro_lots} Mikro</span>
                    </div>
                  </div>
                )}
              </div>
            </details>
          </div>
        </div>
      )}

      {/* ================================================================== */}
      {/* MODALLAR                                                           */}
      {/* ================================================================== */}

      {/* Profesyonel Grafik Modalı */}
      {(chartModalCandidate || chartModalSymbol) && (
        <ForexChartModal
          candidate={chartModalCandidate}
          symbol={chartModalSymbol?.symbol}
          display={chartModalSymbol?.display}
          action={chartModalSymbol?.action}
          onClose={() => {
            setChartModalCandidate(null);
            setChartModalSymbol(null);
          }}
          onOpenLotCalculator={(sym, sl) => {
            setCalcSymbol(sym);
            setCalcSlPips(sl);
            setLotCalcOpen(true);
            selectTab("positions");
            setChartModalCandidate(null);
            setChartModalSymbol(null);
            window.setTimeout(() => {
              document.getElementById("lot-calculator")?.scrollIntoView({ behavior: "smooth" });
            }, 100);
          }}
        />
      )}

      {/* Otonom Motor Ayarlar Paneli */}
      {showSettingsModal && (
        <AutoSettingsPanel
          show={showSettingsModal}
          onClose={() => setShowSettingsModal(false)}
          appliedSettings={appliedSettings}
          onSaved={(saved) => {
            setAppliedSettings(saved);
            setAutoEnabled(Boolean(saved.enabled));
            flashNotice("Otonom motor ayarları güncellendi.", true);
            void fetchEngineAndMt5();
          }}
        />
      )}

      {/* EV Kalkanı Modalı */}
      {showEVShieldModal && (
        <EVShieldModal
          isOpen={showEVShieldModal}
          onClose={() => setShowEVShieldModal(false)}
          onUpdated={() => {
            void fetchRadar();
            void fetchEngineAndMt5();
          }}
        />
      )}

      {/* Kapı Anlık Görünümü (GateSnapshotCard) Modalı */}
      {gateModalSymbol && (
        <div
          role="dialog"
          aria-modal="true"
          aria-label={`${gateModalSymbol} Giriş Kapıları`}
          className="fixed inset-0 z-50 flex items-center justify-center p-3 sm:p-5 bg-black/75 backdrop-blur-sm"
          onClick={(e) => {
            if (e.target === e.currentTarget) setGateModalSymbol(null);
          }}
        >
          <div className="relative w-full max-w-3xl max-h-[88vh] overflow-y-auto rounded-2xl border border-bunker-700 bg-bunker-950 p-4 shadow-2xl space-y-3">
            <div className="flex items-center justify-between border-b border-bunker-800 pb-2.5">
              <h3 className="font-mono text-sm font-bold text-white">
                {gateModalSymbol} — Giriş Kapıları Anlık Görünümü
              </h3>
              <button
                type="button"
                onClick={() => setGateModalSymbol(null)}
                aria-label="Kapat"
                className="min-h-8 min-w-8 rounded-lg bg-bunker-800 text-bunker-muted hover:text-white font-mono text-xs font-bold"
              >
                ✕
              </button>
            </div>

            {gateLoading || !gateSnapshot ? (
              <div className="p-8 text-center font-mono text-xs text-bunker-muted">
                <div className="inline-block w-5 h-5 border-2 border-cyan-400 border-t-transparent rounded-full animate-spin mb-2" />
                <p>Kapı durumu yükleniyor…</p>
              </div>
            ) : (
              <GateSnapshotCard snapshot={gateSnapshot} />
            )}
          </div>
        </div>
      )}
    </div>
  );
}
