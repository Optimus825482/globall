"use client";

import React, { useState, useEffect, useRef, useMemo } from "react";
import Link from "next/link";
import { apiFetch } from "../../lib/api";
import { formatUtc3 } from "../../lib/format";

// --- VERİ TİPLERİ ---
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
  }>;
  pending_commands_count: number;
}

interface TickerData {
  symbol: string;
  display: string;
  name: string;
  category: string;
  tv_symbol: string;
  bid: number;
  ask: number;
  spread_pips: number;
  change_pct: number;
  high: number;
  low: number;
  digits: number;
  pip_size: number;
  score?: number;
  trend?: string;
  action?: string;
  rsi?: number;
  macd_verdict?: string;
  cmo?: number;
  cci?: number;
  adx?: number;
  supertrend_dir?: number;
  atr?: number;
}

interface RadarCandidate {
  symbol: string;
  display: string;
  name: string;
  category: string;
  price: number;
  bid: number;
  ask: number;
  spread_pips: number;
  score: number;
  trend: string;
  action: string;
  rsi_15m: number;
  macd_verdict: string;
  cmo: number;
  cci: number;
  adx: number;
  supertrend_dir: number;
  pip_target: number;
  stop_loss_pips: number;
  risk_reward: string;
  atr_pips: number;
  tv_symbol: string;
}

// --- GAUGE BİLEŞENİ (YARIM DAİRE PROFESYONEL TRİGONOMETRİK KADRAN) ---
function SemiCircleGauge({
  value,
  min = 0,
  max = 100,
  label,
  unit = "",
  zones = [
    { from: 0, to: 40, color: "#ef4444", label: "Ayı / Düşük" },
    { from: 40, to: 65, color: "#eab308", label: "Nötr" },
    { from: 65, to: 100, color: "#10b981", label: "Boğa / Güçlü" },
  ],
  statusText,
}: {
  value: number;
  min?: number;
  max?: number;
  label: string;
  unit?: string;
  zones?: Array<{ from: number; to: number; color: string; label?: string }>;
  statusText?: string;
}) {
  const safeVal = typeof value === "number" && !isNaN(value) ? value : min;
  const clamped = Math.max(min, Math.min(max, safeVal));
  const pct = (clamped - min) / (max - min || 1);

  // Aktif renk belirleme
  const currentZone = zones.find((z) => clamped >= z.from && clamped <= z.to) || zones[zones.length - 1];
  const activeColor = currentZone?.color || "#10b981";

  // Kadran Boyutları
  const cx = 100;
  const cy = 82;
  const radius = 64;
  const strokeWidth = 8;
  const circumference = Math.PI * radius; // 201.06
  const strokeDashoffset = circumference * (1 - pct);

  // Saf Trigonometri ile İbre Koordinatları (CSS transform-origin hatalarını %100 önler)
  // pct = 0 -> Sol (180°), pct = 0.5 -> Tepe (90°), pct = 1 -> Sağ (0°)
  const needleLength = 50;
  const tipX = cx - Math.cos(pct * Math.PI) * needleLength;
  const tipY = cy - Math.sin(pct * Math.PI) * needleLength;

  // İbrenin taban genişliği (İnce şık üçgen ibre)
  const baseWidth = 3.5;
  const perpX = -Math.sin(pct * Math.PI) * baseWidth;
  const perpY = Math.cos(pct * Math.PI) * baseWidth;

  // Ark üzerindeki parlayan nokta (Glow indicator pin)
  const arcPinX = cx - Math.cos(pct * Math.PI) * radius;
  const arcPinY = cy - Math.sin(pct * Math.PI) * radius;

  // Kadran üzerindeki referans tikleri (0%, 25%, 50%, 75%, 100%)
  const ticks = [0, 0.25, 0.5, 0.75, 1.0].map((t) => {
    const tX1 = cx - Math.cos(t * Math.PI) * (radius - 8);
    const tY1 = cy - Math.sin(t * Math.PI) * (radius - 8);
    const tX2 = cx - Math.cos(t * Math.PI) * (radius + 2);
    const tY2 = cy - Math.sin(t * Math.PI) * (radius + 2);
    return { x1: tX1, y1: tY1, x2: tX2, y2: tY2, t };
  });

  return (
    <div className="flex flex-col items-center justify-between p-3.5 rounded-2xl bg-gradient-to-b from-bunker-900/90 to-bunker-950/90 border border-bunker-800/90 hover:border-bunker-700 shadow-xl transition-all h-full">
      {/* Kadran Başlığı */}
      <div className="text-[11px] font-black tracking-wider uppercase text-bunker-muted mb-1 text-center">
        {label}
      </div>

      {/* SVG Kadran Görünümü */}
      <div className="w-full flex justify-center py-1">
        <svg viewBox="0 0 200 95" className="w-full max-w-[170px] h-[85px] overflow-visible">
          <defs>
            <filter id={`glow-pin-${label.replace(/\s+/g, "")}`} x="-50%" y="-50%" width="200%" height="200%">
              <feDropShadow dx="0" dy="0" stdDeviation="3" floodColor={activeColor} floodOpacity="0.8" />
            </filter>
            <linearGradient id={`grad-arc-${label.replace(/\s+/g, "")}`} x1="0%" y1="0%" x2="100%" y2="0%">
              <stop offset="0%" stopColor="#ef4444" />
              <stop offset="50%" stopColor="#eab308" />
              <stop offset="100%" stopColor="#10b981" />
            </linearGradient>
          </defs>

          {/* Kadran Tik Çizgileri */}
          {ticks.map((tk, idx) => (
            <line
              key={idx}
              x1={tk.x1}
              y1={tk.y1}
              x2={tk.x2}
              y2={tk.y2}
              stroke="#334155"
              strokeWidth={idx === 2 ? 2 : 1.2}
              strokeLinecap="round"
            />
          ))}

          {/* Arka Plan Yay Arkı (Koyu Taban) */}
          <path
            d={`M ${cx - radius},${cy} A ${radius},${radius} 0 0,1 ${cx + radius},${cy}`}
            fill="none"
            stroke="#1e293b"
            strokeWidth={strokeWidth}
            strokeLinecap="round"
          />

          {/* Değer Yay Arkı (Renkli İlerleme) */}
          <path
            d={`M ${cx - radius},${cy} A ${radius},${radius} 0 0,1 ${cx + radius},${cy}`}
            fill="none"
            stroke={activeColor}
            strokeWidth={strokeWidth}
            strokeDasharray={circumference}
            strokeDashoffset={strokeDashoffset}
            strokeLinecap="round"
            className="transition-all duration-500 ease-out"
          />

          {/* Ark Üzerindeki Parlayan Nokta (Pin) */}
          <circle
            cx={arcPinX}
            cy={arcPinY}
            r={5}
            fill="#ffffff"
            stroke={activeColor}
            strokeWidth={2}
            filter={`url(#glow-pin-${label.replace(/\s+/g, "")})`}
            className="transition-all duration-500 ease-out"
          />

          {/* Üçgen İbre (Needle - Trigonometrik Poligon) */}
          <path
            d={`M ${cx - perpX},${cy - perpY} L ${tipX},${tipY} L ${cx + perpX},${cy + perpY} Z`}
            fill="#ffffff"
            className="transition-all duration-500 ease-out drop-shadow-[0_0_3px_rgba(255,255,255,0.6)]"
          />

          {/* Merkez Pivot Göbeği */}
          <circle cx={cx} cy={cy} r={6.5} fill="#0f172a" stroke="#ffffff" strokeWidth={1.5} />
          <circle cx={cx} cy={cy} r={3} fill={activeColor} />

          {/* Min & Max Küçük Skala Etiketleri */}
          <text x={cx - radius - 2} y={cy + 11} fill="#64748b" fontSize="8" fontWeight="bold" textAnchor="middle">
            {min}
          </text>
          <text x={cx + radius + 2} y={cy + 11} fill="#64748b" fontSize="8" fontWeight="bold" textAnchor="middle">
            {max}
          </text>
        </svg>
      </div>

      {/* Rakam ve Durum Rozeti (SVG DIŞINDA, İBREDEN BAĞIMSIZ VE TERTEMİZ) */}
      <div className="flex flex-col items-center justify-center mt-1 w-full">
        <div className="flex items-baseline justify-center gap-0.5">
          <span className="text-xl font-black font-mono tracking-tight text-white drop-shadow-md">
            {clamped.toFixed(1)}
          </span>
          {unit && <span className="text-[10px] text-bunker-muted font-bold font-mono">{unit}</span>}
        </div>

        {/* Durum Rozeti */}
        <span
          className="mt-1 px-2.5 py-0.5 rounded-full text-[10px] font-black border tracking-wider transition-colors shadow-sm"
          style={{
            backgroundColor: `${activeColor}20`,
            borderColor: `${activeColor}50`,
            color: activeColor,
          }}
        >
          {statusText || currentZone?.label || "Aktif"}
        </span>
      </div>
    </div>
  );
}

// --- RAKAMSAL PROGRESS BARLI KART BİLEŞENİ ---
function ProgressBarCard({
  title,
  valueText,
  subText,
  percentage,
  leftLabel,
  rightLabel,
  barColor = "emerald",
  icon,
}: {
  title: string;
  valueText: string | React.ReactNode;
  subText?: string | React.ReactNode;
  percentage: number;
  leftLabel?: string;
  rightLabel?: string;
  barColor?: "emerald" | "amber" | "rose" | "cyan" | "blue" | "purple" | "gradient";
  icon?: string;
}) {
  const clampedPct = Math.max(0, Math.min(100, isNaN(percentage) ? 0 : percentage));

  const colorClasses: Record<string, string> = {
    emerald: "from-emerald-600 to-emerald-400 bg-emerald-500",
    amber: "from-amber-600 to-amber-400 bg-amber-500",
    rose: "from-rose-600 to-rose-400 bg-rose-500",
    cyan: "from-cyan-600 to-cyan-400 bg-cyan-400",
    blue: "from-blue-600 to-blue-400 bg-blue-500",
    purple: "from-purple-600 to-purple-400 bg-purple-500",
    gradient: "from-rose-500 via-amber-400 to-emerald-400 bg-gradient-to-r",
  };

  return (
    <div className="p-3.5 rounded-xl bg-bunker-950/80 border border-bunker-800/80 hover:border-bunker-700 transition-all flex flex-col justify-between shadow-sm">
      <div className="flex items-center justify-between gap-2 mb-1.5">
        <span className="text-[11px] font-bold text-bunker-muted uppercase tracking-wider flex items-center gap-1.5">
          {icon && <span className="text-xs">{icon}</span>}
          <span>{title}</span>
        </span>
        <div className="font-mono text-xs font-black text-white">{valueText}</div>
      </div>

      {/* Progress Bar Container */}
      <div className="my-1.5">
        <div className="w-full h-2.5 rounded-full bg-bunker-900 border border-bunker-800/80 p-0.5 overflow-hidden relative shadow-inner">
          <div
            className={`h-full rounded-full transition-all duration-700 ease-out bg-gradient-to-r ${
              colorClasses[barColor] || colorClasses.emerald
            }`}
            style={{ width: `${clampedPct}%` }}
          />
        </div>
      </div>

      {/* Alt Etiketler */}
      <div className="flex items-center justify-between text-[10px] text-bunker-muted mt-0.5 font-mono">
        <span>{leftLabel || "0%"}</span>
        {subText && <span className="font-sans font-semibold text-bunker-300">{subText}</span>}
        <span>{rightLabel || "100%"}</span>
      </div>
    </div>
  );
}

// --- ANA SAYFA BİLEŞENİ ---
export default function BtcGoldForexPage() {
  const allowedSymbols = useMemo(() => ["XAUUSD", "BTCUSD"], []);
  const symFilter = useMemo(() => new Set(["XAUUSD", "BTCUSD"]), []);

  // MT5 Durumu
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
  const [mt5Message, setMt5Message] = useState<string | null>(null);

  // Otonom Sistem Durumu
  const [autoStatus, setAutoStatus] = useState<string>("Yükleniyor…");
  const [autoEnabled, setAutoEnabled] = useState<boolean>(false);
  const [balance, setBalance] = useState<number>(1000.0);
  const [equity, setEquity] = useState<number>(1000.0);
  const [openPnlUsd, setOpenPnlUsd] = useState<number>(0.0);
  const [openPnlPips, setOpenPnlPips] = useState<number>(0.0);
  const [realizedPnlUsd, setRealizedPnlUsd] = useState<number>(0.0);
  const [winRate, setWinRate] = useState<number>(0.0);
  const [totalTrades, setTotalTrades] = useState<number>(0);
  const [wins, setWins] = useState<number>(0);
  const [losses, setLosses] = useState<number>(0);

  const [openPositions, setOpenPositions] = useState<AutoPosition[]>([]);
  const [closedTrades, setClosedTrades] = useState<ClosedTrade[]>([]);
  const [decisionLogs, setDecisionLogs] = useState<DecisionLog[]>([]);
  const [sessions, setSessions] = useState<any[]>([]);

  // Canlı Gösterge / Ticker / Radar Verileri
  const [tickers, setTickers] = useState<Record<string, TickerData>>({});
  const [radarMap, setRadarMap] = useState<Record<string, RadarCandidate>>({});

  // Parametre Formu
  const [showSettings, setShowSettings] = useState(false);
  const [isSavingSettings, setIsSavingSettings] = useState(false);
  const [saveSuccessMsg, setSaveSuccessMsg] = useState<string | null>(null);
  const [appliedSettings, setAppliedSettings] = useState<AutoSettings>({
    enabled: false,
    balance: 1000.0,
    risk_per_trade_pct: 1.0,
    max_open_positions: 3,
    min_score: 70.0,
    tp_pips: 25.0,
    sl_pips: 15.0,
    breakeven_pips: 8.0,
    trailing_stop_pips: 12.0,
    session_filter: false,
    max_spread_pips: 3.0,
    allowed_symbols: ["XAUUSD", "BTCUSD"],
  });
  const [formSettings, setFormSettings] = useState<AutoSettings>({ ...appliedSettings });

  // Canlı Log Filtresi ve Otomatik Kaydırma
  const [logFilter, setLogFilter] = useState<string>("ALL");
  const [logSymbolFilter, setLogSymbolFilter] = useState<string>("ALL");
  const [autoScroll, setAutoScroll] = useState<boolean>(true);
  const logContainerRef = useRef<HTMLDivElement>(null);

  // Manuel Hızlı İşlem Durumu (Lot büyüklüğü seçimi)
  const [quickLots, setQuickLots] = useState<Record<string, number>>({
    XAUUSD: 0.1,
    BTCUSD: 0.05,
  });
  const [quickTradeMsg, setQuickTradeMsg] = useState<string | null>(null);

  // --- VERİ ÇEKME DÖNGÜSÜ ---
  const fetchAllData = async () => {
    // 1. Otonom Durum ve İşlemler
    try {
      const res = await apiFetch("/api/forex/auto-paper/status");
      if (res) {
        setAutoStatus(res.status || "Hazır");
        setAutoEnabled(Boolean(res.enabled));
        setBalance(res.balance ?? 1000.0);
        setEquity(res.equity ?? res.balance ?? 1000.0);
        setOpenPnlUsd(res.open_pnl_usd ?? 0.0);
        setOpenPnlPips(res.open_pnl_pips ?? 0.0);
        setRealizedPnlUsd(res.realized_pnl_usd ?? 0.0);
        setTotalTrades(res.total_trades ?? 0);
        setWins(res.wins ?? 0);
        setLosses(res.losses ?? 0);
        setWinRate(res.win_rate ?? 0.0);

        setOpenPositions(
          (res.open_positions || []).filter((p: AutoPosition) => symFilter.has(String(p.symbol).toUpperCase()))
        );
        setClosedTrades(
          (res.closed_trades || []).filter((t: ClosedTrade) => symFilter.has(String(t.symbol).toUpperCase()))
        );
        setDecisionLogs(
          (res.decision_logs || []).filter(
            (l: DecisionLog) => !l.symbol || symFilter.has(String(l.symbol).toUpperCase())
          )
        );
        setSessions(res.sessions || []);
        if (res.settings) {
          setAppliedSettings(res.settings);
        }
      }
    } catch (err) {
      console.error("Auto paper status hatası:", err);
    }

    // 2. MT5 Durumu
    try {
      const mt5Res = await apiFetch("/api/forex/mt5/status");
      if (mt5Res) {
        setMt5({
          ...mt5Res,
          open_positions: (mt5Res.open_positions || []).filter((p: any) =>
            symFilter.has(String(p.symbol).toUpperCase())
          ),
          closed_deals: (mt5Res.closed_deals || []).filter((d: any) =>
            symFilter.has(String(d.symbol).toUpperCase())
          ),
        });
      }
    } catch (err) {
      // MT5 offline olabilir
    }

    // 3. Canlı Radar ve Ticker Göstergeleri
    try {
      const radarRes = await apiFetch("/api/forex/radar");
      if (radarRes && radarRes.candidates) {
        const map: Record<string, RadarCandidate> = {};
        for (const c of radarRes.candidates) {
          if (symFilter.has(c.symbol.toUpperCase())) {
            map[c.symbol.toUpperCase()] = c;
          }
        }
        setRadarMap(map);
      }
    } catch (err) {
      console.error("Radar göstergeleri hatası:", err);
    }

    try {
      const tickersRes = await apiFetch("/api/forex/tickers");
      if (tickersRes && tickersRes.tickers) {
        const tMap: Record<string, TickerData> = {};
        for (const t of tickersRes.tickers) {
          if (symFilter.has(t.symbol.toUpperCase())) {
            tMap[t.symbol.toUpperCase()] = t;
          }
        }
        setTickers(tMap);
      }
    } catch (err) {
      console.error("Tickers verisi hatası:", err);
    }
  };

  useEffect(() => {
    fetchAllData();
    const interval = setInterval(fetchAllData, 1500);
    return () => clearInterval(interval);
  }, []);

  // Otomatik kaydırma
  useEffect(() => {
    if (autoScroll && logContainerRef.current) {
      logContainerRef.current.scrollTop = 0;
    }
  }, [decisionLogs, autoScroll]);

  // --- EYLEMLER ---
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

  const closeMt5Ticket = async (ticket: number) => {
    if (!confirm(`Bilet #${ticket} nolu MT5 pozisyonunu kapatmak istiyor musunuz?`)) return;
    try {
      await apiFetch("/api/forex/mt5/close", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ticket }),
      });
      setMt5Message(`Bilet #${ticket} kapatma emri MT5 köprüsüne iletildi.`);
      setTimeout(() => setMt5Message(null), 4000);
      fetchAllData();
    } catch (err) {
      console.error("MT5 close hatası:", err);
    }
  };

  const closeAllMt5Positions = async () => {
    const count = mt5.open_positions?.length || 0;
    if (!confirm(`Açık olan TÜM (${count}) IC Markets MT5 pozisyonunu tek seferde kapatmak istiyor musunuz?`)) return;
    try {
      await apiFetch("/api/forex/mt5/close-all", { method: "POST" });
      setMt5Message(`🛑 Tüm (${count}) MT5 pozisyonunu kapatma emri köprüye iletildi.`);
      setTimeout(() => setMt5Message(null), 5000);
      fetchAllData();
    } catch (err) {
      console.error("MT5 close-all hatası:", err);
    }
  };

  const closeAutoPosition = async (id: string) => {
    try {
      await apiFetch("/api/forex/auto-paper/close-position", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id }),
      });
      fetchAllData();
    } catch (err) {
      console.error("Auto pozisyon kapatma hatası:", err);
    }
  };

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
        allowed_symbols: ["XAUUSD", "BTCUSD"], // Yalnızca bu iki sembole kilitli
      };

      const res = await apiFetch("/api/forex/auto-paper/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (res && res.status === "ok") {
        setAppliedSettings(res.settings);
        setFormSettings(res.settings);
        setSaveSuccessMsg("✓ XAUUSD & BTCUSD parametreleri başarıyla güncellendi!");
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

  const handleQuickTrade = async (symbol: string, direction: "BUY" | "SELL") => {
    const lots = quickLots[symbol] || 0.1;
    try {
      const res = await apiFetch("/api/forex/mt5/order", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          symbol,
          action: direction,
          lots,
          comment: `Manual Quick Scalp ${symbol}`,
        }),
      });
      if (res) {
        setQuickTradeMsg(`⚡ ${symbol} ${direction} ${lots} Lot emri MT5 köprüsüne iletildi!`);
        setTimeout(() => setQuickTradeMsg(null), 4000);
        fetchAllData();
      }
    } catch (err) {
      console.error("Hızlı emir iletimi hatası:", err);
      setQuickTradeMsg(`⚠️ Emir iletilemedi: MT5 köprüsü kontrol edilsin.`);
      setTimeout(() => setQuickTradeMsg(null), 4000);
    }
  };

  const downloadCsv = () => {
    try {
      const headers = [
        "Bilet No",
        "Sembol",
        "Yön",
        "Lot",
        "Giriş Fiyatı",
        "Çıkış Fiyatı",
        "Kapanış Zamanı (UTC+3)",
        "Çıkış Nedeni",
        "Kâr/Zarar (Pip)",
        "Net Getiri (USD)",
      ];
      const rows = closedTrades.map((t) => [
        t.id,
        t.symbol,
        t.direction,
        t.lots,
        t.entry_price,
        t.exit_price,
        formatUtc3(t.exit_time),
        t.exit_reason,
        `${t.pnl_pips >= 0 ? "+" : ""}${t.pnl_pips}`,
        `${t.pnl_usd >= 0 ? "+" : ""}${t.pnl_usd.toFixed(2)}`,
      ]);
      const csvContent =
        "\uFEFF" +
        [headers.join(";"), ...rows.map((r) => r.map((cell) => `"${cell}"`).join(";"))].join("\r\n");
      const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      const dateStr = new Date().toISOString().slice(0, 10);
      link.setAttribute("href", url);
      link.setAttribute("download", `btc_gold_forex_islemler_${dateStr}.csv`);
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);
    } catch (e) {
      console.error("CSV indirme hatası:", e);
    }
  };

  const activeSessions = sessions.filter((s) => s.active);
  const liveBal = Number(mt5.account?.balance ?? balance ?? 1000.0);
  const liveEq = Number(mt5.account?.equity ?? liveBal);
  const liveMargin = Number(mt5.account?.free_margin ?? liveBal);
  const totalOpenPnl = (mt5.open_positions || []).reduce((acc, p) => acc + Number(p.pnl_usd ?? 0), 0) + openPnlUsd;

  return (
    <div className="space-y-6 pb-16 font-mono selection:bg-amber-500/30 selection:text-amber-200">
      {/* =========================================================================
          1. ÜST KISIM: BAŞLIK, OTONOM/MT5 KONTROL PANELİ VE İŞLEMLER LİSTESİ
      ========================================================================= */}
      <div className="p-5 rounded-2xl bg-gradient-to-r from-amber-950/30 via-bunker-900/90 to-blue-950/40 border border-amber-500/40 backdrop-blur-md shadow-2xl flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div className="flex items-center gap-3.5">
          <div className="w-13 h-13 rounded-2xl bg-gradient-to-br from-amber-500/25 to-yellow-600/30 border border-amber-400/50 flex items-center justify-center text-3xl shadow-[0_0_25px_rgba(245,158,11,0.35)]">
            🥇
          </div>
          <div>
            <div className="flex items-center gap-2 flex-wrap">
              <h1 className="text-xl font-black text-white tracking-tight flex items-center gap-2">
                <span>XAUUSD &amp; BTCUSD</span>
                <span className="text-amber-400 font-bold text-sm">· ÖZEL KOMUTA KOKPİTİ</span>
              </h1>
              <span
                className={`px-2.5 py-0.5 rounded-full text-[11px] font-bold border transition-all ${
                  autoEnabled
                    ? "bg-emerald-500/20 text-emerald-400 border-emerald-500/40 shadow-[0_0_12px_rgba(16,185,129,0.3)] animate-pulse"
                    : "bg-bunker-800 text-bunker-muted border-bunker-700"
                }`}
              >
                {autoEnabled ? "● OTONOM AKTİF" : "○ DURDURULDU"}
              </span>
              <span
                className={`px-2.5 py-0.5 rounded-full text-[10px] font-bold border ${
                  mt5.connected
                    ? "bg-emerald-500/20 text-emerald-300 border-emerald-500/40 shadow-[0_0_10px_rgba(16,185,129,0.25)]"
                    : "bg-rose-500/20 text-rose-300 border-rose-500/40"
                }`}
              >
                {mt5.connected
                  ? `🟢 IC MARKETS DEMO (${mt5.last_ping_seconds_ago !== null ? `${mt5.last_ping_seconds_ago}s` : "Canlı"})`
                  : "⚪ MT5 KÖPRÜ ÇEVRİMDIŞI"}
              </span>
            </div>
            <p className="text-xs text-bunker-muted mt-1">
              Hedef Varlıklar: <span className="text-amber-300 font-bold">Ons Altın (XAUUSD)</span> &amp;{" "}
              <span className="text-orange-400 font-bold">Bitcoin (BTCUSD)</span> · Hesap:{" "}
              <span className="text-cyan-300 font-bold">{mt5.account?.login || 53077151}</span> · Dinamik Breakeven &amp; Trailing Stop
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
            onClick={() => setShowSettings(!showSettings)}
            className="px-3.5 py-2 rounded-xl bg-bunker-900 border border-bunker-700 text-white hover:border-amber-400 transition-all text-xs font-bold flex items-center gap-1.5 shadow-sm"
          >
            <span>⚙️ Parametreler</span>
          </button>

          {mt5.open_positions && mt5.open_positions.length > 0 && (
            <button
              type="button"
              onClick={closeAllMt5Positions}
              className="px-3.5 py-2 rounded-xl bg-rose-600/25 border border-rose-500/50 text-rose-300 hover:bg-rose-600/40 transition-all text-xs font-bold flex items-center gap-1.5 shadow-sm"
            >
              <span>🛑 Tüm Pozisyonları Kapat ({mt5.open_positions.length})</span>
            </button>
          )}

          <button
            type="button"
            onClick={downloadCsv}
            disabled={closedTrades.length === 0}
            className="px-3 py-2 rounded-xl bg-bunker-900 border border-bunker-800 text-bunker-muted hover:text-white text-xs font-bold flex items-center gap-1 disabled:opacity-40"
            title="CSV Dışa Aktar"
          >
            <span>📥 CSV</span>
          </button>
        </div>
      </div>

      {/* Mesaj Bildirimleri */}
      {mt5Message && (
        <div className="p-3 rounded-xl bg-blue-500/20 border border-blue-500/40 text-blue-300 text-xs font-bold animate-fadeIn">
          {mt5Message}
        </div>
      )}
      {quickTradeMsg && (
        <div className="p-3 rounded-xl bg-amber-500/20 border border-amber-500/40 text-amber-300 text-xs font-bold animate-fadeIn">
          {quickTradeMsg}
        </div>
      )}

      {/* PARAMETRE AYARLARI PANELİ (Açılır/Kapanır) */}
      {showSettings && (
        <form
          onSubmit={saveSettings}
          className="p-5 rounded-2xl bg-bunker-900/95 border border-amber-500/40 shadow-2xl space-y-4 animate-in fade-in slide-in-from-top-2 duration-200"
        >
          <div className="flex items-center justify-between border-b border-bunker-800 pb-3">
            <div className="flex items-center gap-2">
              <span className="text-amber-400 font-bold">⚙️</span>
              <h3 className="text-sm font-bold text-white uppercase tracking-wider">
                XAUUSD &amp; BTCUSD Scalping Risk &amp; Çıkış Parametreleri
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
              <label className="text-[11px] text-bunker-muted block mb-1">İşlem Başına Risk (%):</label>
              <input
                type="number"
                step="0.1"
                min="0.1"
                max="20.0"
                value={formSettings.risk_per_trade_pct ?? ""}
                onChange={(e) =>
                  setFormSettings({ ...formSettings, risk_per_trade_pct: parseFloat(e.target.value) || 1.0 })
                }
                className="w-full bg-bunker-950 border border-bunker-700 rounded-lg px-2.5 py-1.5 text-white font-bold outline-none focus:border-amber-400"
              />
              <span className="text-[10px] text-bunker-muted">Dinamik lot büyüklüğü</span>
            </div>

            <div>
              <label className="text-[11px] text-bunker-muted block mb-1">Kâr Al (TP Pips):</label>
              <input
                type="number"
                min="5"
                max="100"
                value={formSettings.tp_pips ?? ""}
                onChange={(e) =>
                  setFormSettings({ ...formSettings, tp_pips: parseFloat(e.target.value) || 25.0 })
                }
                className="w-full bg-bunker-950 border border-bunker-700 rounded-lg px-2.5 py-1.5 text-emerald-400 font-bold outline-none focus:border-amber-400"
              />
              <span className="text-[10px] text-bunker-muted">Hedeflenen scalp kârı</span>
            </div>

            <div>
              <label className="text-[11px] text-bunker-muted block mb-1">Zarar Durdur (SL Pips):</label>
              <input
                type="number"
                min="5"
                max="50"
                value={formSettings.sl_pips ?? ""}
                onChange={(e) =>
                  setFormSettings({ ...formSettings, sl_pips: parseFloat(e.target.value) || 15.0 })
                }
                className="w-full bg-bunker-950 border border-bunker-700 rounded-lg px-2.5 py-1.5 text-rose-400 font-bold outline-none focus:border-amber-400"
              />
              <span className="text-[10px] text-bunker-muted">Maksimum kayıp mesafesi</span>
            </div>

            <div>
              <label className="text-[11px] text-bunker-muted block mb-1">Başabaş Kilit (BE Pips):</label>
              <input
                type="number"
                min="2"
                max="30"
                value={formSettings.breakeven_pips ?? ""}
                onChange={(e) =>
                  setFormSettings({ ...formSettings, breakeven_pips: parseFloat(e.target.value) || 8.0 })
                }
                className="w-full bg-bunker-950 border border-bunker-700 rounded-lg px-2.5 py-1.5 text-cyan-300 font-bold outline-none focus:border-amber-400"
              />
              <span className="text-[10px] text-bunker-muted">+8 pips kârda stop girişe çekilir</span>
            </div>

            <div>
              <label className="text-[11px] text-bunker-muted block mb-1">İz Süren Stop (Trailing Pips):</label>
              <input
                type="number"
                min="4"
                max="40"
                value={formSettings.trailing_stop_pips ?? ""}
                onChange={(e) =>
                  setFormSettings({ ...formSettings, trailing_stop_pips: parseFloat(e.target.value) || 12.0 })
                }
                className="w-full bg-bunker-950 border border-bunker-700 rounded-lg px-2.5 py-1.5 text-yellow-300 font-bold outline-none focus:border-amber-400"
              />
              <span className="text-[10px] text-bunker-muted">Trend uzarsa kârı korur</span>
            </div>

            <div>
              <label className="text-[11px] text-bunker-muted block mb-1">Min. Radar Skoru (50-98):</label>
              <input
                type="number"
                min="50"
                max="98"
                value={formSettings.min_score ?? ""}
                onChange={(e) =>
                  setFormSettings({ ...formSettings, min_score: parseFloat(e.target.value) || 70.0 })
                }
                className="w-full bg-bunker-950 border border-bunker-700 rounded-lg px-2.5 py-1.5 text-white font-bold outline-none focus:border-amber-400"
              />
              <span className="text-[10px] text-bunker-muted">Yalnızca yüksek teyitli işlemler</span>
            </div>

            <div>
              <label className="text-[11px] text-bunker-muted block mb-1">Max. Spread Limiti:</label>
              <input
                type="number"
                step="0.5"
                min="0.5"
                max="25.0"
                value={formSettings.max_spread_pips ?? ""}
                onChange={(e) =>
                  setFormSettings({ ...formSettings, max_spread_pips: parseFloat(e.target.value) || 3.0 })
                }
                className="w-full bg-bunker-950 border border-bunker-700 rounded-lg px-2.5 py-1.5 text-white font-bold outline-none focus:border-amber-400"
              />
              <span className="text-[10px] text-bunker-muted">Spread yüksekse işlem açılmaz</span>
            </div>

            <div>
              <label className="text-[11px] text-bunker-muted block mb-1">Max. Açık Pozisyon:</label>
              <input
                type="number"
                min="1"
                max="10"
                value={formSettings.max_open_positions ?? ""}
                onChange={(e) =>
                  setFormSettings({ ...formSettings, max_open_positions: parseInt(e.target.value) || 3 })
                }
                className="w-full bg-bunker-950 border border-bunker-700 rounded-lg px-2.5 py-1.5 text-white font-bold outline-none focus:border-amber-400"
              />
              <span className="text-[10px] text-bunker-muted">Aynı anda en fazla işlem</span>
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
              className="px-4 py-1.5 rounded-lg bg-amber-600 hover:bg-amber-500 text-white font-bold text-xs shadow-md transition-all disabled:opacity-50"
            >
              {isSavingSettings ? "Kaydediliyor…" : "Kaydet ve Uygula"}
            </button>
          </div>
        </form>
      )}

      {/* HESAP METRİKLERİ KARTLARI */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
        <div className="p-3.5 rounded-xl bg-bunker-900/80 border border-bunker-800 shadow-sm">
          <span className="text-[10px] text-bunker-muted uppercase block">IC Markets Bakiye</span>
          <span className="text-lg font-bold text-emerald-400 font-mono">
            ${liveBal.toFixed(2)} <span className="text-xs font-normal text-bunker-muted">{mt5.account?.currency || "USD"}</span>
          </span>
          <span className="text-[9px] text-bunker-muted block mt-0.5">Kapanan net bakiye</span>
        </div>

        <div className="p-3.5 rounded-xl bg-bunker-900/80 border border-bunker-800 shadow-sm">
          <span className="text-[10px] text-bunker-muted uppercase block">Özsermaye (Equity)</span>
          <span className={`text-lg font-bold font-mono ${liveEq >= liveBal ? "text-cyan-300" : "text-rose-400"}`}>
            ${liveEq.toFixed(2)}
          </span>
          <span className="text-[9px] text-bunker-muted block mt-0.5">Serbest: ${liveMargin.toFixed(2)}</span>
        </div>

        <div className="p-3.5 rounded-xl bg-bunker-900/80 border border-bunker-800 shadow-sm">
          <span className="text-[10px] text-bunker-muted uppercase block">Açık PnL (Anlık)</span>
          <span className={`text-lg font-bold font-mono ${totalOpenPnl >= 0 ? "text-emerald-400" : "text-rose-400"}`}>
            {totalOpenPnl >= 0 ? "+" : ""}${totalOpenPnl.toFixed(2)}
          </span>
          <span className="text-[9px] text-bunker-muted block mt-0.5">
            {mt5.open_positions?.length + openPositions.length} açık işlem
          </span>
        </div>

        <div className="p-3.5 rounded-xl bg-bunker-900/80 border border-bunker-800 shadow-sm">
          <span className="text-[10px] text-bunker-muted uppercase block">Başarı Oranı (Win Rate)</span>
          <span className="text-lg font-bold text-yellow-400 font-mono">
            %{winRate.toFixed(1)}
          </span>
          <span className="text-[9px] text-bunker-muted block mt-0.5">
            {wins}K / {losses}Z ({totalTrades} İşlem)
          </span>
        </div>

        <div className="p-3.5 rounded-xl bg-bunker-900/80 border border-bunker-800 shadow-sm">
          <span className="text-[10px] text-bunker-muted uppercase block">Kaldıraç &amp; Sunucu</span>
          <span className="text-base font-bold text-white tracking-wide">
            1:{mt5.account?.leverage || 5000}
          </span>
          <span className="text-[9px] text-emerald-400 block mt-0.5 truncate">{mt5.account?.server || "ICMarketsSC-Demo"}</span>
        </div>

        <div className="p-3.5 rounded-xl bg-bunker-900/80 border border-bunker-800 shadow-sm">
          <span className="text-[10px] text-bunker-muted uppercase block">Aktif Seanslar</span>
          <div className="flex items-center gap-1 mt-1 overflow-x-auto">
            {activeSessions.length > 0 ? (
              activeSessions.map((s) => (
                <span
                  key={s.name}
                  className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-emerald-500/15 text-emerald-400 border border-emerald-500/30 whitespace-nowrap"
                >
                  {s.flag} {s.name}
                </span>
              ))
            ) : (
              <span className="text-[11px] text-bunker-muted">24/5 Açık</span>
            )}
          </div>
        </div>
      </div>

      {/* CANLI AÇIK İŞLEMLER LİSTESİ (MT5 & OTONOM PAPER) */}
      <div className="rounded-2xl border border-bunker-800 bg-bunker-900/70 overflow-hidden shadow-xl">
        <div className="p-4 border-b border-bunker-800 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <span className="text-lg">⚡</span>
            <h2 className="text-sm font-bold text-white uppercase tracking-wider flex items-center gap-2">
              <span>Açık İşlemler Listesi (XAUUSD &amp; BTCUSD)</span>
            </h2>
            <span className="text-[10px] text-amber-400 font-bold px-2 py-0.5 rounded bg-amber-500/15 border border-amber-500/30">
              {mt5.open_positions?.length + openPositions.length} Aktif Pozisyon
            </span>
          </div>

          <div className="flex items-center gap-3">
            {mt5.open_positions && mt5.open_positions.length > 0 && (
              <button
                type="button"
                onClick={closeAllMt5Positions}
                className="px-3 py-1 rounded-lg bg-rose-600/25 border border-rose-500/50 text-rose-300 hover:bg-rose-600/40 text-xs font-bold transition-all flex items-center gap-1.5 shadow-sm"
              >
                <span>🛑 Tüm MT5 Kapat ({mt5.open_positions.length})</span>
              </button>
            )}
            <span className="text-xs text-blue-400 font-bold animate-pulse">
              {autoEnabled ? "● Canlı Scalper Devrede" : "○ Otonom Beklemede"}
            </span>
          </div>
        </div>

        {mt5.open_positions?.length === 0 && openPositions.length === 0 ? (
          <div className="p-8 text-center text-bunker-muted text-xs space-y-1">
            <p className="text-sm font-semibold text-white">Şu an açık bir XAUUSD veya BTCUSD pozisyonu bulunmuyor.</p>
            <p className="text-bunker-muted">
              {autoEnabled
                ? "Otonom scalper motoru XAUUSD ve BTCUSD sinyallerini denetliyor. Koşullar sağlandığında emir otomatik açılacaktır."
                : "Otonom motor durdurulmuş durumda. Yukarıdan '▶ Otonom Scalper'ı Başlat' butonuna basabilir veya aşağıdaki kokpitten hızlı manuel işlem açabilirsiniz."}
            </p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="bg-bunker-950/80 text-bunker-muted uppercase border-b border-bunker-800 text-[10px]">
                <tr>
                  <th className="py-3 px-4">Bilet/ID</th>
                  <th className="py-3 px-3">Sembol</th>
                  <th className="py-3 px-3">Yön</th>
                  <th className="py-3 px-3">Koruma Durumu</th>
                  <th className="py-3 px-3">Lot</th>
                  <th className="py-3 px-3">Giriş Fiyatı</th>
                  <th className="py-3 px-3">Güncel Fiyat</th>
                  <th className="py-3 px-3">SL / TP Seviyeleri</th>
                  <th className="py-3 px-3">Anlık Kâr</th>
                  <th className="py-3 px-4 text-right">Aksiyon</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-bunker-800/60 font-mono">
                {/* MT5 Pozisyonları */}
                {mt5.open_positions.map((p) => {
                  const pnlVal = Number(p.pnl_usd ?? (p as any).profit ?? 0);
                  const isProfit = pnlVal >= 0;
                  const isTrailing = p.protection === "TRAILING" || !!p.trailing_activated;
                  const isBE = (p.protection === "BREAKEVEN" || !!p.breakeven_activated) && !isTrailing;

                  return (
                    <tr key={`mt5-${p.ticket}`} className="hover:bg-bunker-800/40 transition-colors">
                      <td className="py-3 px-4 text-[11px] text-cyan-300 font-bold">
                        #{p.ticket} <span className="text-[9px] text-bunker-muted font-normal">(MT5)</span>
                      </td>
                      <td className="py-3 px-3 font-bold text-white text-sm">
                        <span className="flex items-center gap-1.5">
                          <span>{p.symbol === "XAUUSD" ? "🥇" : "₿"}</span>
                          <span>{p.symbol}</span>
                        </span>
                      </td>
                      <td className="py-3 px-3">
                        <span
                          className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                            p.direction === "BUY"
                              ? "bg-emerald-500/15 text-emerald-400 border border-emerald-500/30"
                              : "bg-rose-500/15 text-rose-400 border border-rose-500/30"
                          }`}
                        >
                          {p.direction}
                        </span>
                      </td>
                      <td className="py-3 px-3 font-sans">
                        {isTrailing ? (
                          <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[10px] font-bold bg-amber-500/20 text-amber-300 border border-amber-400/40 animate-pulse">
                            <span>🏃 TRAILING STOP</span>
                          </span>
                        ) : isBE ? (
                          <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[10px] font-bold bg-cyan-500/20 text-cyan-300 border border-cyan-400/40">
                            <span>🛡️ BAŞABAŞ (BE)</span>
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] text-bunker-muted bg-bunker-800 border border-bunker-700">
                            <span>🛑 Sabit SL</span>
                          </span>
                        )}
                      </td>
                      <td className="py-3 px-3 font-semibold text-white">{p.lots} Lot</td>
                      <td className="py-3 px-3 text-bunker-muted">{p.entry_price}</td>
                      <td className="py-3 px-3 font-bold text-white">{p.current_price}</td>
                      <td className="py-3 px-3 text-xs">
                        <div className="flex flex-col gap-0.5">
                          <span className="text-rose-300">SL: {p.sl_price || "-"}</span>
                          <span className="text-emerald-300">TP: {p.tp_price || "-"}</span>
                        </div>
                      </td>
                      <td className={`py-3 px-3 ${isProfit ? "text-emerald-400" : "text-rose-400"}`}>
                        <div className="font-bold text-sm">
                          {isProfit ? "+" : ""}${pnlVal.toFixed(2)}
                        </div>
                        {p.pnl_pips != null && (
                          <div className="text-[10px] font-semibold">
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

                {/* Auto-Paper Pozisyonları (Varsa) */}
                {openPositions.map((p, pIdx) => {
                  const pnlVal = Number(p.pnl_usd ?? (p as any).profit ?? 0);
                  const isProfit = pnlVal >= 0;
                  const rawId = String(p.id ?? (p as any).ticket ?? `paper-${pIdx}`);
                  const displayId = rawId.length > 6 ? rawId.slice(-6) : rawId;
                  const pnlPips = p.pnl_pips != null && !isNaN(Number(p.pnl_pips)) ? Number(p.pnl_pips) : null;

                  return (
                    <tr key={`auto-${rawId}-${pIdx}`} className="hover:bg-bunker-800/40 transition-colors">
                      <td className="py-3 px-4 text-[11px] text-amber-300 font-bold">
                        #{displayId} <span className="text-[9px] text-bunker-muted font-normal">(Paper)</span>
                      </td>
                      <td className="py-3 px-3 font-bold text-white text-sm">
                        <span className="flex items-center gap-1.5">
                          <span>{p.symbol === "XAUUSD" ? "🥇" : "₿"}</span>
                          <span>{p.symbol}</span>
                        </span>
                      </td>
                      <td className="py-3 px-3">
                        <span
                          className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                            p.direction === "BUY"
                              ? "bg-emerald-500/15 text-emerald-400 border border-emerald-500/30"
                              : "bg-rose-500/15 text-rose-400 border border-rose-500/30"
                          }`}
                        >
                          {p.direction}
                        </span>
                      </td>
                      <td className="py-3 px-3 font-sans">
                        {p.trailing_activated ? (
                          <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-amber-500/20 text-amber-300">
                            🏃 TRAILING
                          </span>
                        ) : p.breakeven_activated ? (
                          <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-cyan-500/20 text-cyan-300">
                            🛡️ BE
                          </span>
                        ) : (
                          <span className="px-2 py-0.5 rounded text-[10px] text-bunker-muted bg-bunker-800">
                            🛑 Sabit SL
                          </span>
                        )}
                      </td>
                      <td className="py-3 px-3 font-semibold text-white">{p.lots} Lot</td>
                      <td className="py-3 px-3 text-bunker-muted">{p.entry_price}</td>
                      <td className="py-3 px-3 font-bold text-white">{p.current_price}</td>
                      <td className="py-3 px-3 text-xs">
                        <span className="text-rose-300">SL: {p.sl_price || "-"}</span> |{" "}
                        <span className="text-emerald-300">TP: {p.tp_price || "-"}</span>
                      </td>
                      <td className={`py-3 px-3 ${isProfit ? "text-emerald-400" : "text-rose-400"}`}>
                        <div className="font-bold text-sm">
                          {isProfit ? "+" : ""}${pnlVal.toFixed(2)}
                        </div>
                        {pnlPips !== null && (
                          <div className="text-[10px]">
                            {pnlPips >= 0 ? "+" : ""}{pnlPips.toFixed(1)} p
                          </div>
                        )}
                      </td>
                      <td className="py-3 px-4 text-right">
                        <button
                          type="button"
                          onClick={() => closeAutoPosition(rawId)}
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
        )}
      </div>

      {/* =========================================================================
          2. ORTA KISIM: XAUUSD VE BTCUSD İÇİN ÖZEL GÖSTERGELER & GAUGELER & PROGRESS BARLI KARTLAR
      ========================================================================= */}
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="text-xl">🎛️</span>
            <h2 className="text-base font-black text-white uppercase tracking-wider">
              Anlık Göstergeler, İbreli Gaugelar &amp; Dinamik Progress Barlar
            </h2>
          </div>
          <span className="text-xs text-bunker-muted">
            Canlı Yenileme: <span className="text-emerald-400 font-bold">1.5 saniye</span>
          </span>
        </div>

        {/* 2 SÜTUNLU KOKPİT GRİDİ (XAUUSD & BTCUSD) */}
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
          {allowedSymbols.map((sym) => {
            const isGold = sym === "XAUUSD";
            const candidate = radarMap[sym];
            const tick = tickers[sym];

            // Rakamlar & Değerler
            const curPrice = tick?.ask || candidate?.price || (isGold ? 2735.6 : 68450.0);
            const bidPrice = tick?.bid || candidate?.bid || curPrice;
            const askPrice = tick?.ask || candidate?.ask || curPrice;
            const spreadPips = tick?.spread_pips ?? candidate?.spread_pips ?? (isGold ? 1.5 : 12.0);
            const changePct = tick?.change_pct ?? 0.45;
            const dayHigh = tick?.high || curPrice * 1.008;
            const dayLow = tick?.low || curPrice * 0.992;

            // Günlük Fiyat Aralığı Yüzdesi (Progress bar için)
            const rangeSpan = dayHigh - dayLow || 1;
            const rangePct = Math.max(0, Math.min(100, ((curPrice - dayLow) / rangeSpan) * 100));

            // İndikatörler
            const score = candidate?.score ?? tick?.score ?? 72.0;
            const trend = candidate?.trend ?? tick?.trend ?? "BULLISH";
            const action = candidate?.action ?? tick?.action ?? (trend === "BULLISH" ? "BUY" : "HOLD");
            const rsi = candidate?.rsi_15m ?? tick?.rsi ?? 58.4;
            const adx = candidate?.adx ?? tick?.adx ?? 28.5;
            const supertrendDir = candidate?.supertrend_dir ?? tick?.supertrend_dir ?? 1;
            const macdVerdict = candidate?.macd_verdict ?? tick?.macd_verdict ?? "POZİTİF (Alım Güçleniyor)";
            const cmo = candidate?.cmo ?? tick?.cmo ?? 18.0;
            const cci = candidate?.cci ?? tick?.cci ?? 75.0;
            const atrPips = candidate?.atr_pips ?? 18.5;
            const tpTarget = candidate?.pip_target ?? appliedSettings.tp_pips;
            const slTarget = candidate?.stop_loss_pips ?? appliedSettings.sl_pips;
            const rrRatio = candidate?.risk_reward ?? `1:${(tpTarget / (slTarget || 1)).toFixed(2)}`;

            // Spread Güvenlik Yüzdesi (Limit 3.0 veya ayar)
            const maxSpreadAllowed = appliedSettings.max_spread_pips || (isGold ? 3.0 : 25.0);
            const spreadSafetyPct = Math.min(100, (spreadPips / maxSpreadAllowed) * 100);

            // Renk Şeması
            const cardBorder = isGold ? "border-amber-500/40" : "border-orange-500/40";
            const headerGradient = isGold
              ? "from-amber-950/40 via-bunker-900 to-amber-950/20"
              : "from-orange-950/40 via-bunker-900 to-orange-950/20";
            const accentText = isGold ? "text-amber-400" : "text-orange-400";

            return (
              <div
                key={sym}
                className={`rounded-2xl border ${cardBorder} bg-bunker-900/80 shadow-2xl overflow-hidden flex flex-col justify-between`}
              >
                {/* 1. Kokpit Başlık & Canlı Fiyat Alanı */}
                <div className={`p-4 bg-gradient-to-r ${headerGradient} border-b border-bunker-800`}>
                  <div className="flex items-center justify-between gap-3">
                    <div className="flex items-center gap-3">
                      <div className="w-12 h-12 rounded-xl bg-bunker-950/80 border border-bunker-700/80 flex items-center justify-center text-2xl shadow-md">
                        {isGold ? "🥇" : "₿"}
                      </div>
                      <div>
                        <div className="flex items-center gap-2">
                          <h3 className="text-base font-black text-white tracking-wide">
                            {isGold ? "ONS ALTIN / USD" : "BITCOIN / USD"}
                          </h3>
                          <span className={`px-2 py-0.5 rounded text-[10px] font-black border ${accentText} bg-bunker-950`}>
                            {sym}
                          </span>
                        </div>
                        <span className="text-[11px] text-bunker-muted">
                          {isGold ? "Kıymetli Maden & Güvenli Liman (Commodity)" : "Kripto Öncüsü & Dijital Altın (Crypto)"}
                        </span>
                      </div>
                    </div>

                    {/* Sinyal Rozeti */}
                    <div className="text-right">
                      <span
                        className={`inline-block px-3 py-1 rounded-xl text-xs font-black border tracking-wider shadow-md ${
                          action === "BUY"
                            ? "bg-emerald-500/20 text-emerald-300 border-emerald-400/50 shadow-[0_0_12px_rgba(16,185,129,0.3)] animate-pulse"
                            : action === "SELL"
                            ? "bg-rose-500/20 text-rose-300 border-rose-400/50 shadow-[0_0_12px_rgba(244,63,94,0.3)] animate-pulse"
                            : "bg-bunker-800 text-bunker-muted border-bunker-700"
                        }`}
                      >
                        {action === "BUY" ? "⚡ GÜÇLÜ ALIŞ (BUY)" : action === "SELL" ? "🔻 GÜÇLÜ SATIŞ (SELL)" : "⏸ BEKLEMEDE (HOLD)"}
                      </span>
                    </div>
                  </div>

                  {/* Fiyat Şeridi */}
                  <div className="mt-4 p-3 rounded-xl bg-bunker-950/90 border border-bunker-800/80 flex items-center justify-between flex-wrap gap-2">
                    <div>
                      <span className="text-[10px] text-bunker-muted uppercase block">Canlı Piyasa Fiyatı</span>
                      <div className="flex items-baseline gap-2">
                        <span className="text-2xl font-black font-mono text-white tracking-tight drop-shadow">
                          ${curPrice.toLocaleString(undefined, { minimumFractionDigits: isGold ? 2 : 1, maximumFractionDigits: isGold ? 2 : 1 })}
                        </span>
                        <span
                          className={`text-xs font-bold font-mono ${
                            changePct >= 0 ? "text-emerald-400" : "text-rose-400"
                          }`}
                        >
                          {changePct >= 0 ? "▲ +" : "▼ "}
                          {changePct.toFixed(2)}%
                        </span>
                      </div>
                    </div>

                    <div className="flex items-center gap-4 text-xs font-mono">
                      <div>
                        <span className="text-[10px] text-bunker-muted block">BID</span>
                        <span className="text-emerald-400 font-bold">{bidPrice}</span>
                      </div>
                      <div className="text-bunker-700">|</div>
                      <div>
                        <span className="text-[10px] text-bunker-muted block">ASK</span>
                        <span className="text-rose-400 font-bold">{askPrice}</span>
                      </div>
                      <div className="text-bunker-700">|</div>
                      <div>
                        <span className="text-[10px] text-bunker-muted block">SPREAD</span>
                        <span className="text-cyan-300 font-bold">{spreadPips} p</span>
                      </div>
                    </div>
                  </div>
                </div>

                {/* 2. GAUGELER BÖLÜMÜ (İbreli Yarım Daire SVG Göstergeler) */}
                <div className="p-4 border-b border-bunker-800 bg-bunker-950/40">
                  <div className="text-[11px] font-bold text-white uppercase tracking-wider mb-2.5 flex items-center gap-1.5">
                    <span>🧭</span>
                    <span>Hassas İbreli Göstergeler (Cockpit Gauges)</span>
                  </div>

                  <div className="grid grid-cols-3 gap-2.5">
                    {/* Gauge 1: Radar Skoru */}
                    <SemiCircleGauge
                      value={score}
                      min={0}
                      max={100}
                      label="Radar Skoru"
                      unit="/100"
                      zones={[
                        { from: 0, to: 45, color: "#ef4444" },
                        { from: 45, to: 68, color: "#eab308" },
                        { from: 68, to: 100, color: "#10b981" },
                      ]}
                      statusText={score >= 70 ? "Yüksek Teyit" : score >= 50 ? "Nötr Seviye" : "Düşük Güven"}
                    />

                    {/* Gauge 2: RSI */}
                    <SemiCircleGauge
                      value={rsi}
                      min={0}
                      max={100}
                      label="RSI (15M)"
                      zones={[
                        { from: 0, to: 30, color: "#8b5cf6" },
                        { from: 30, to: 70, color: "#06b6d4" },
                        { from: 70, to: 100, color: "#f43f5e" },
                      ]}
                      statusText={rsi < 30 ? "Aşırı Satım" : rsi > 70 ? "Aşırı Alım" : "Dengeli Bölge"}
                    />

                    {/* Gauge 3: ADX Trend Gücü */}
                    <SemiCircleGauge
                      value={adx}
                      min={0}
                      max={60}
                      label="ADX Gücü"
                      zones={[
                        { from: 0, to: 20, color: "#64748b" },
                        { from: 20, to: 35, color: "#3b82f6" },
                        { from: 35, to: 60, color: "#10b981" },
                      ]}
                      statusText={adx > 30 ? "Güçlü Trend" : adx > 20 ? "Oluşan Trend" : "Yatay / Sıkışma"}
                    />
                  </div>
                </div>

                {/* 3. PROGRESS BARLI RAKAMSAL KARTLAR */}
                <div className="p-4 space-y-3">
                  <div className="text-[11px] font-bold text-white uppercase tracking-wider mb-1 flex items-center gap-1.5">
                    <span>📊</span>
                    <span>Rakamsal Parametre Barları (Progress Bars)</span>
                  </div>

                  {/* Bar 1: Günlük 24s Fiyat Aralığı (Low - High Range) */}
                  <ProgressBarCard
                    title="24s Günlük Fiyat Aralığı"
                    icon="📈"
                    valueText={`$${curPrice.toFixed(isGold ? 2 : 1)} (%${rangePct.toFixed(0)})`}
                    subText={`Aralık: $${(dayHigh - dayLow).toFixed(isGold ? 2 : 1)}`}
                    percentage={rangePct}
                    leftLabel={`Low: $${dayLow.toFixed(isGold ? 2 : 1)}`}
                    rightLabel={`High: $${dayHigh.toFixed(isGold ? 2 : 1)}`}
                    barColor="gradient"
                  />

                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                    {/* Bar 2: MACD Histogram & Momentum */}
                    <ProgressBarCard
                      title="MACD Momentum"
                      icon="🌊"
                      valueText={macdVerdict}
                      subText="Momentum Yönü"
                      percentage={trend === "BULLISH" ? 85 : trend === "BEARISH" ? 15 : 50}
                      leftLabel="Ayı Satış"
                      rightLabel="Boğa Alış"
                      barColor={trend === "BULLISH" ? "emerald" : trend === "BEARISH" ? "rose" : "amber"}
                    />

                    {/* Bar 3: Spread Emniyeti */}
                    <ProgressBarCard
                      title="Spread Emniyet Skalası"
                      icon="🛡️"
                      valueText={`${spreadPips} / ${maxSpreadAllowed} p`}
                      subText={spreadPips <= maxSpreadAllowed ? "✓ İşleme Uygun" : "⚠️ Yüksek Spread"}
                      percentage={spreadSafetyPct}
                      leftLabel="0 pips"
                      rightLabel={`${maxSpreadAllowed} pips`}
                      barColor={spreadSafetyPct > 80 ? "rose" : spreadSafetyPct > 50 ? "amber" : "emerald"}
                    />

                    {/* Bar 4: Hedef Risk/Ödül Oranı */}
                    <ProgressBarCard
                      title="Risk / Ödül Skalası"
                      icon="🎯"
                      valueText={rrRatio}
                      subText={`TP: +${tpTarget}p | SL: -${slTarget}p`}
                      percentage={Math.min(100, (tpTarget / ((tpTarget + slTarget) || 1)) * 100)}
                      leftLabel={`SL: ${slTarget}p`}
                      rightLabel={`TP: ${tpTarget}p`}
                      barColor="cyan"
                    />

                    {/* Bar 5: Volatilite & Osilatörler (CMO & CCI) */}
                    <ProgressBarCard
                      title="Chande (CMO) &amp; CCI"
                      icon="⚡"
                      valueText={`CMO: ${cmo.toFixed(1)} | CCI: ${cci.toFixed(0)}`}
                      subText={cmo > 0 ? "Pozitif İvme" : "Negatif İvme"}
                      percentage={Math.max(0, Math.min(100, (cmo + 50)))}
                      leftLabel="-50"
                      rightLabel="+50"
                      barColor={cmo >= 0 ? "emerald" : "rose"}
                    />
                  </div>
                </div>

                {/* 4. HIZLI EMİR & LOT BUTONLARI (Kullanıcı Dostu Tek Tıkla Scalp) */}
                <div className="p-4 bg-bunker-950/80 border-t border-bunker-800 flex flex-col sm:flex-row items-center justify-between gap-3">
                  <div className="flex items-center gap-2">
                    <span className="text-[11px] text-bunker-muted font-bold">Hızlı Lot:</span>
                    {[0.05, 0.1, 0.25, 0.5, 1.0].map((lt) => (
                      <button
                        key={lt}
                        type="button"
                        onClick={() => setQuickLots({ ...quickLots, [sym]: lt })}
                        className={`px-2 py-0.5 rounded text-[10px] font-bold border transition-all ${
                          quickLots[sym] === lt
                            ? "bg-amber-500/25 text-amber-300 border-amber-400"
                            : "bg-bunker-900 text-bunker-muted border-bunker-800 hover:text-white"
                        }`}
                      >
                        {lt}
                      </button>
                    ))}
                  </div>

                  <div className="flex items-center gap-2 w-full sm:w-auto">
                    <button
                      type="button"
                      onClick={() => handleQuickTrade(sym, "BUY")}
                      className="flex-1 sm:flex-initial px-4 py-2 rounded-xl bg-emerald-500/20 hover:bg-emerald-500/30 text-emerald-300 border border-emerald-500/40 font-bold text-xs flex items-center justify-center gap-1.5 transition-all shadow-[0_0_12px_rgba(16,185,129,0.2)]"
                    >
                      <span>▲ HIZLI BUY</span>
                      <span className="text-[10px] opacity-80 font-mono">({quickLots[sym] || 0.1} Lot)</span>
                    </button>

                    <button
                      type="button"
                      onClick={() => handleQuickTrade(sym, "SELL")}
                      className="flex-1 sm:flex-initial px-4 py-2 rounded-xl bg-rose-500/20 hover:bg-rose-500/30 text-rose-300 border border-rose-500/40 font-bold text-xs flex items-center justify-center gap-1.5 transition-all shadow-[0_0_12px_rgba(244,63,94,0.2)]"
                    >
                      <span>▼ HIZLI SELL</span>
                      <span className="text-[10px] opacity-80 font-mono">({quickLots[sym] || 0.1} Lot)</span>
                    </button>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* =========================================================================
          3. ALT KISIM: CANLI LOG AKIŞI (TERMINAL & STREAM) VE KAPANAN İŞLEMLER
      ========================================================================= */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Sol 2 Kolon: CANLI LOG AKIŞI (Terminal Konsolu) */}
        <div className="lg:col-span-2 rounded-2xl border border-bunker-800 bg-bunker-950 p-4 shadow-2xl flex flex-col h-[480px]">
          {/* Header */}
          <div className="flex flex-col sm:flex-row sm:items-center justify-between border-b border-bunker-800/80 pb-3 mb-2 gap-2">
            <div className="flex items-center gap-2.5">
              <span className="relative flex h-3 w-3">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
                <span className="relative inline-flex rounded-full h-3 w-3 bg-emerald-500"></span>
              </span>
              <h3 className="text-xs font-black text-white uppercase tracking-wider flex items-center gap-2">
                <span>CANLI LOG &amp; KARAR AKIŞI</span>
                <span className="text-[10px] text-amber-400 font-normal">· XAUUSD &amp; BTCUSD</span>
              </h3>
            </div>

            <div className="flex items-center gap-2">
              <label className="text-[10px] text-bunker-muted flex items-center gap-1.5 cursor-pointer select-none">
                <input
                  type="checkbox"
                  checked={autoScroll}
                  onChange={(e) => setAutoScroll(e.target.checked)}
                  className="rounded bg-bunker-900 border-bunker-700 text-amber-500 focus:ring-0 cursor-pointer"
                />
                <span>Oto-Kaydır</span>
              </label>
              <span className="text-[10px] text-bunker-muted">({decisionLogs.length} Kayıt)</span>
            </div>
          </div>

          {/* Filtre Butonları */}
          <div className="flex items-center justify-between flex-wrap gap-2 pb-2 mb-2 border-b border-bunker-800/60 text-[10px]">
            {/* Kategori Filtresi */}
            <div className="flex items-center gap-1 overflow-x-auto scrollbar-none">
              {[
                { id: "ALL", label: "Tümü", icon: "🌐" },
                { id: "ENTRY", label: "Girişler", icon: "⚡" },
                { id: "PROTECT", label: "Koruma", icon: "🛡️" },
                { id: "EXIT", label: "Çıkışlar", icon: "🎯" },
                { id: "GATE", label: "Engeller", icon: "⛔" },
                { id: "SCAN", label: "Taramalar", icon: "🔍" },
              ].map((tab) => (
                <button
                  key={tab.id}
                  type="button"
                  onClick={() => setLogFilter(tab.id)}
                  className={`px-2 py-1 rounded-md transition-all font-bold whitespace-nowrap flex items-center gap-1 ${
                    logFilter === tab.id
                      ? "bg-amber-500/20 text-amber-300 border border-amber-400/40 shadow-sm"
                      : "bg-bunker-900 text-bunker-muted hover:text-white border border-transparent"
                  }`}
                >
                  <span>{tab.icon}</span>
                  <span>{tab.label}</span>
                </button>
              ))}
            </div>

            {/* Sembol Filtresi */}
            <div className="flex items-center gap-1">
              {["ALL", "XAUUSD", "BTCUSD"].map((sym) => (
                <button
                  key={sym}
                  type="button"
                  onClick={() => setLogSymbolFilter(sym)}
                  className={`px-2 py-0.5 rounded text-[10px] font-bold border transition-all ${
                    logSymbolFilter === sym
                      ? "bg-blue-600/30 text-blue-300 border-blue-400/50"
                      : "bg-bunker-900 text-bunker-muted border-bunker-800 hover:text-white"
                  }`}
                >
                  {sym === "ALL" ? "Her İkisi" : sym === "XAUUSD" ? "🥇 Altın" : "₿ BTC"}
                </button>
              ))}
            </div>
          </div>

          {/* Log Listesi (Terminal) */}
          <div
            ref={logContainerRef}
            className="flex-1 overflow-y-auto space-y-1.5 pr-1 font-mono text-[11px] select-text"
          >
            {(() => {
              let filtered = decisionLogs;
              if (logFilter !== "ALL") {
                filtered = filtered.filter((l) => l.category === logFilter);
              }
              if (logSymbolFilter !== "ALL") {
                filtered = filtered.filter((l) => l.symbol?.toUpperCase() === logSymbolFilter);
              }

              if (filtered.length === 0) {
                return (
                  <div className="text-center py-20 text-bunker-muted text-xs">
                    Bu filtreye ait bir kayıt henüz bulunmuyor.
                  </div>
                );
              }

              const sorted = [...filtered].sort((a, b) => {
                const tsA = a.created_at_ts ?? 0;
                const tsB = b.created_at_ts ?? 0;
                if (tsA && tsB && tsA !== tsB) return tsB - tsA;
                return (b.time || "").localeCompare(a.time || "");
              });

              const catBadgeStyles: Record<string, string> = {
                SCAN: "text-sky-300 bg-sky-950/60 border-sky-500/30",
                ENTRY: "text-emerald-300 bg-emerald-950/60 border-emerald-500/40 font-bold",
                EXIT: "text-blue-300 bg-blue-950/60 border-blue-500/30",
                PROTECT: "text-cyan-300 bg-cyan-950/60 border-cyan-500/30 font-bold",
                GATE: "text-amber-300 bg-amber-950/60 border-amber-500/30",
                SYSTEM: "text-bunker-muted bg-bunker-900 border-bunker-800",
              };

              return sorted.map((log) => {
                const isGold = log.symbol === "XAUUSD";
                const isBtc = log.symbol === "BTCUSD";

                return (
                  <div
                    key={log.id}
                    className="p-2 rounded-lg bg-bunker-900/60 border border-bunker-800/80 hover:border-bunker-700 transition-colors flex items-start justify-between gap-2"
                  >
                    <div className="flex items-start gap-2 flex-1">
                      <span className="text-bunker-muted text-[10px] whitespace-nowrap opacity-75 mt-0.5">
                        {formatUtc3(log.time)}
                      </span>

                      <span
                        className={`px-1.5 py-0.2 rounded text-[9px] uppercase border tracking-wider whitespace-nowrap ${
                          catBadgeStyles[log.category] || "text-bunker-muted bg-bunker-900 border-bunker-800"
                        }`}
                      >
                        {log.category}
                      </span>

                      {log.symbol && (
                        <span
                          className={`px-1.5 py-0.2 rounded text-[9px] font-bold border whitespace-nowrap ${
                            isGold
                              ? "bg-amber-500/15 text-amber-300 border-amber-500/30"
                              : isBtc
                              ? "bg-orange-500/15 text-orange-300 border-orange-500/30"
                              : "bg-bunker-800 text-white border-bunker-700"
                          }`}
                        >
                          {isGold ? "🥇 XAUUSD" : isBtc ? "₿ BTCUSD" : log.symbol}
                        </span>
                      )}

                      <span className="text-bunker-200 leading-snug flex-1 break-words">{log.message}</span>
                    </div>
                  </div>
                );
              });
            })()}
          </div>
        </div>

        {/* Sağ 1 Kolon: KAPANAN SCALP İŞLEMLERİ */}
        <div className="rounded-2xl border border-bunker-800 bg-bunker-900/70 p-4 shadow-xl flex flex-col h-[480px]">
          <div className="flex items-center justify-between border-b border-bunker-800 pb-3 mb-2">
            <div className="flex items-center gap-2">
              <span className="text-base">🏁</span>
              <h3 className="text-xs font-bold text-white uppercase tracking-wider">
                Kapanan İşlemler ({closedTrades.length})
              </h3>
            </div>
            <Link
              href="/forex/reports"
              className="text-[10px] font-bold text-amber-400 hover:text-amber-300 transition-colors"
            >
              Raporlar →
            </Link>
          </div>

          <div className="flex-1 overflow-y-auto space-y-2 pr-1 text-xs">
            {closedTrades.length === 0 ? (
              <div className="text-center py-20 text-bunker-muted">
                Henüz kapanmış bir işlem bulunmuyor.
              </div>
            ) : (
              closedTrades.map((tr: any, idx: number) => {
                const pnlVal = Number(tr.pnl_usd ?? tr.profit ?? 0);
                const isWin = pnlVal >= 0;
                const pnlPips = tr.pnl_pips != null ? Number(tr.pnl_pips) : null;
                const keyId = tr.id ?? tr.ticket ?? `deal-${idx}`;
                const symDisplay = tr.symbol ?? "FX";
                const dir = tr.direction ?? "BUY";
                const lotsVal = tr.lots ?? 0.01;
                const reasonStr = tr.exit_reason_title ?? tr.exit_reason ?? "Kâr Al / SL";

                return (
                  <div
                    key={keyId}
                    className="p-2.5 rounded-lg border border-bunker-800 bg-bunker-950/60 flex items-center justify-between hover:border-bunker-700 transition-colors"
                  >
                    <div>
                      <div className="flex items-center gap-1.5">
                        <span className="font-bold text-white text-xs">{symDisplay}</span>
                        <span
                          className={`px-1.5 py-0.2 rounded text-[9px] font-bold ${
                            dir === "BUY"
                              ? "bg-emerald-500/15 text-emerald-400"
                              : "bg-rose-500/15 text-rose-400"
                          }`}
                        >
                          {dir}
                        </span>
                        <span className="text-[10px] text-bunker-muted">{lotsVal} Lot</span>
                      </div>
                      <div className="text-[10px] text-bunker-muted mt-0.5 truncate max-w-[170px]">
                        {reasonStr}
                      </div>
                    </div>

                    <div className="text-right">
                      <div className={`font-bold font-mono text-xs ${isWin ? "text-emerald-400" : "text-rose-400"}`}>
                        {isWin ? "+" : ""}${pnlVal.toFixed(2)}
                      </div>
                      {pnlPips !== null && (
                        <div
                          className={`text-[10px] font-mono ${
                            pnlPips >= 0 ? "text-emerald-400" : "text-rose-400"
                          }`}
                        >
                          {pnlPips >= 0 ? "+" : ""}{pnlPips} p
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

      {/* ALT GEZİNTİ BAĞLANTILARI */}
      <div className="flex flex-wrap items-center justify-between gap-3 text-xs text-bunker-muted pt-2 border-t border-bunker-800">
        <div className="flex items-center gap-4">
          <Link href="/forex" className="hover:text-amber-400 transition-colors">
            ← Genel Forex &amp; Emtia Radar
          </Link>
          <span className="text-bunker-700">|</span>
          <Link href="/forex/portfolio" className="hover:text-amber-400 transition-colors">
            Tüm Pariteler Portföy Konsolu
          </Link>
        </div>
        <Link href="/forex/technical-charts" className="hover:text-amber-400 transition-colors">
          4'lü TradingView Ekranı →
        </Link>
      </div>
    </div>
  );
}
