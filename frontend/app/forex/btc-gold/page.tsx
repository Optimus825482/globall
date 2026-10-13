"use client";

import React, { useState, useEffect, useRef, useMemo } from "react";
import Link from "next/link";
import { apiFetch } from "../../lib/api";
import { usePolling } from "../../lib/usePolling";
import { formatUtc3 } from "../../lib/format";
import GateSnapshotCard, { type GateSnapshot } from "../components/GateSnapshotCard";

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
  /** Ham MACD histogramı (fiyat birimi) — yön barı `atr` ile böler. */
  macd_hist?: number;
  volatility?: string;
  updated_at?: number;
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
  /** Ham MACD histogramı (fiyat birimi). `atr` alanıyla bölünüp ölçeksizleştirilir. */
  macd_hist?: number;
  /** Ham ATR (fiyat birimi) — yön barının ölçek böleni. */
  atr?: number;
}

/** Sembol bazlı KPI dilimi — backend `per_symbol_today` / `per_symbol_all_time`. */
interface SymbolKpi {
  symbol: string;
  display: string;
  trades: number;
  wins: number;
  losses: number;
  win_rate: number;
  pnl_usd: number;
  pnl_pips: number;
  open_count: number;
  open_pnl_usd: number;
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

// --- DİNAMİK YÖN BARI (ORTASI NÖTR · SAĞ BUY · SOL SELL) ---
// Veri UYDURMAZ: değeri motorun kendi ürettiği MACD histogramının ATR'ye oranı
// belirler (bkz. eşik vs. tick üretimi). +1 tam boğa, -1 tam ayı, 0 nötr.
// Neden "ölçeksiz": XAU histogramı $ biriminde, BTC de $ biriminde ama ATR'leri
// kıyaslanamaz — ATR'ye bölmek ikisini de aynı -1..+1 ölçeğine taşır.
// Nötr ölü bölge (±0.12) kasıtlı: küçük histogram salınımı "sinyal" sayılmasın.
const NEUTRAL_DEAD_ZONE = 0.12;

function DirectionBar({
  value,
  detail,
  hasData,
}: {
  /** -1 (tam SATIŞ) … 0 (nötr) … +1 (tam ALIŞ) */
  value: number;
  detail: string;
  hasData: boolean;
}) {
  const clamped = Math.max(-1, Math.min(1, isNaN(value) ? 0 : value));
  const posPct = 50 + clamped * 50; // 0% = sol uç, 50% = orta, 100% = sağ uç
  const isBuy = clamped > NEUTRAL_DEAD_ZONE;
  const isSell = clamped < -NEUTRAL_DEAD_ZONE;
  const tone = !hasData
    ? "text-bunker-muted"
    : isBuy
    ? "text-emerald-300"
    : isSell
    ? "text-rose-300"
    : "text-slate-300";
  const verdict = !hasData ? "VERİ YOK" : isBuy ? "ALIŞ YÖNÜ" : isSell ? "SATIŞ YÖNÜ" : "NÖTR / BEKLE";
  const needleColor = !hasData ? "#64748b" : isBuy ? "#10b981" : isSell ? "#f43f5e" : "#94a3b8";

  return (
    <div className="p-3 rounded-xl bg-bunker-950/80 border border-bunker-800/80">
      <div className="flex items-center justify-between gap-2 mb-2">
        <span className="text-[10px] font-black text-bunker-muted uppercase tracking-wider">
          🎯 Yön Göstergesi — Dinamik Momentum
        </span>
        <span className={`text-[10px] font-black tracking-wide ${tone}`}>{verdict}</span>
      </div>

      {/* Ray: sol kırmızı (SELL) → orta gri (NÖTR) → sağ yeşil (BUY).
          Renkler satır içi CSS olarak verilir: `bg-gradient-*` sınıfları açık
          temada `html.light [class*="bg-gradient-"]` kuralıyla beyaza
          düzleştirildiği için ray tamamen kayboluyordu (2026-10-13). */}
      <div className="relative h-3 rounded-full overflow-hidden border border-bunker-800/80 shadow-inner">
        <div className="absolute inset-0 flex">
          <div className="w-1/2 h-full" style={{ background: "linear-gradient(90deg, rgba(225,29,72,0.75), rgba(244,63,94,0.10))" }} />
          <div className="w-1/2 h-full" style={{ background: "linear-gradient(90deg, rgba(16,185,129,0.10), rgba(5,150,105,0.75))" }} />
        </div>
        {/* Nötr ölü bölge işareti — ortadaki gri şerit */}
        <div
          className="absolute top-0 h-full bg-slate-500/35 border-x border-slate-400/40"
          style={{ left: `${50 - NEUTRAL_DEAD_ZONE * 50}%`, width: `${NEUTRAL_DEAD_ZONE * 100}%` }}
        />
        {/* Orta çizgi */}
        <div className="absolute left-1/2 top-0 h-full w-px bg-slate-300/50" />
        {/* İbre */}
        <div
          className="absolute top-[-2px] h-[16px] w-[3px] rounded-full transition-all duration-700 ease-out shadow-[0_0_8px_rgba(255,255,255,0.35)]"
          style={{ left: `calc(${posPct}% - 1.5px)`, background: needleColor }}
        />
      </div>

      <div className="flex items-center justify-between text-[9px] font-mono mt-1.5">
        <span className="text-rose-300/80 font-bold">◀ SELL</span>
        <span className="text-slate-400 font-bold">NÖTR</span>
        <span className="text-emerald-300/80 font-bold">BUY ▶</span>
      </div>
      <p className="text-[10px] text-bunker-300 mt-1.5 text-center">{detail}</p>
    </div>
  );
}

// --- SEMBOL BAŞARI ORANI (BUGÜN & TÜM ZAMANLAR) ---
// Kullanıcı isteği (2026-10-13): "başarı oranlarını o günkü ve tüm zamanlar
// olmak üzere ayrı ayrı". İki blok AYNI defterden gelir (backend
// `per_symbol_today` ve `per_symbol_all_time`), bu yüzden sayıları tutarlıdır.
function WinRateBlock({
  title,
  kpi,
  accent,
}: {
  title: string;
  kpi: SymbolKpi | null;
  accent: string;
}) {
  const trades = kpi?.trades ?? 0;
  const wins = kpi?.wins ?? 0;
  const losses = kpi?.losses ?? 0;
  const rate = kpi?.win_rate ?? 0;
  const pnlUsd = kpi?.pnl_usd ?? 0;
  const pnlPips = kpi?.pnl_pips ?? 0;
  const hasTrades = trades > 0;
  const tone = !hasTrades
    ? "text-bunker-muted"
    : rate >= 50
    ? "text-emerald-300"
    : "text-rose-300";
  return (
    <div className="p-2.5 rounded-xl bg-bunker-950/80 border border-bunker-800/80">
      <div className="flex items-center justify-between gap-2">
        <span className={`text-[9px] font-black uppercase tracking-wider ${accent}`}>{title}</span>
        <span className={`text-sm font-black font-mono ${tone}`}>
          {hasTrades ? `%${rate.toFixed(1)}` : "—"}
        </span>
      </div>
      <div className="text-[9px] text-bunker-muted font-mono mt-0.5">
        {hasTrades ? `${wins}K / ${losses}Z (${trades} İşlem)` : "Kapanan işlem yok"}
      </div>
      <div className="text-[9px] font-mono mt-1 flex items-center gap-1.5">
        <span className="text-bunker-muted">NET KÂRLILIK</span>
        {hasTrades ? (
          <>
            <span className={pnlUsd >= 0 ? "text-emerald-400 font-bold" : "text-rose-400 font-bold"}>
              {pnlUsd >= 0 ? "+" : ""}${pnlUsd.toFixed(2)}
            </span>
            <span className={pnlPips >= 0 ? "text-emerald-400/80" : "text-rose-400/80"}>
              {pnlPips >= 0 ? "+" : ""}{pnlPips.toFixed(1)} pip
            </span>
          </>
        ) : (
          <span className="text-bunker-muted">—</span>
        )}
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

  // Dolgu RENGİ artık sınıf değil, doğrudan hex: `.progress-fill` CSS'i
  // `--progress-color` değişkeninden hem düz rengi hem gradienti üretir.
  // (2026-10-13: açık temada `bg-gradient-*` sınıfları beyaza düzleştiriliyordu
  // → bar boş görünüyordu. Sabit hex bu tuzağı tamamen kaldırır.)
  const fillColors: Record<string, string> = {
    emerald: "#10b981",
    amber: "#f59e0b",
    rose: "#f43f5e",
    cyan: "#22d3ee",
    blue: "#3b82f6",
    purple: "#a855f7",
    gradient: "#22d3ee",
  };
  const fillColor = fillColors[barColor] || fillColors.emerald;

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
            className="progress-fill h-full rounded-full transition-all duration-700 ease-out"
            style={{ width: `${clampedPct}%`, ["--progress-color" as string]: fillColor }}
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

// --- DİNAMİK DXY PANOSU (2026-10-13) ---
// Kullanıcı isteği: "piyasa notunun ÜST kısmına dinamik DXY değerini gösteren
// progress bar ve değeri yazalım." Rejim (USD_STRONG/WEAK/NEUTRAL) + canlı
// endeks seviyesi + RSI + günlük değişim tek şeritte gösterilir.
//
// Bar yorumu: dolar GÜCÜNÜ soldan sağa ölçer. Sabit bir bant (94–110) kullanılır:
// DXY pratikte bu aralıkta salınır. Değer bandın DIŞINA çıkarsa bant değeri
// kapsayacak şekilde genişletilir — aksi hâlde bar uçta çakılı kalır ve
// gerçek seviye yanlış okunur (sessiz yanıltma).
const DXY_BAND_MIN = 94.0;
const DXY_BAND_MAX = 110.0;

interface DxyPanelData {
  regime?: string;
  trend?: string;
  score?: number;
  rsi?: number;
  cmo?: number;
  change_pct?: number;
  price?: number;
}

function DxyProgressPanel({ dxy }: { dxy: DxyPanelData }) {
  const price = Number(dxy.price || 0);
  const regime = dxy.regime || "USD_NEUTRAL";
  const trend = dxy.trend || "NEUTRAL";
  const changePct = Number(dxy.change_pct || 0);
  const rsi = Number(dxy.rsi ?? 50);

  const hasPrice = price > 0;
  // Bant değeri kapsamıyorsa genişlet (bar uçta çakılı kalmasın).
  const bandMin = hasPrice ? Math.min(DXY_BAND_MIN, price - 0.5) : DXY_BAND_MIN;
  const bandMax = hasPrice ? Math.max(DXY_BAND_MAX, price + 0.5) : DXY_BAND_MAX;
  const bandSpan = Math.max(0.001, bandMax - bandMin);
  const pct = Math.max(0, Math.min(100, ((price - bandMin) / bandSpan) * 100));
  // Nötr (sıkışık dolar) referansı: 100.0 seviyesi — endeksin klasik pivotu.
  const neutralPct = Math.max(0, Math.min(100, ((100.0 - bandMin) / bandSpan) * 100));

  // Rejim → renk ve etiket. Zayıf dolar altın/BTC için RÜZGÂR (yeşil),
  // güçlü dolar TERS RÜZGÂR (kırmızı), sıkışık nötr (amber).
  const isWeak = regime === "USD_WEAK";
  const isStrong = regime === "USD_STRONG";
  const fillColor = isWeak ? "#10b981" : isStrong ? "#f43f5e" : "#f59e0b";
  const regimeLabel = isWeak
    ? "DOLAR ZAYIF — ALTIN & BTC LEHİNE"
    : isStrong
    ? "DOLAR GÜÇLÜ — ALTIN & BTC ALEYHİNE"
    : "DOLAR SIKIŞIK — YÖNSÜZ";
  const toneText = isWeak ? "text-emerald-300" : isStrong ? "text-rose-300" : "text-amber-300";
  const trendIcon = trend === "BULLISH" ? "▲" : trend === "BEARISH" ? "▼" : "◆";
  const changeTone =
    changePct > 0 ? "text-emerald-300" : changePct < 0 ? "text-rose-300" : "text-bunker-muted";

  return (
    <div className="p-3 rounded-xl bg-bunker-950/80 border border-bunker-800 flex flex-col gap-2">
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <span className="text-[10px] font-black text-bunker-muted uppercase tracking-wider flex items-center gap-1.5">
          <span>💵</span>
          <span>DXY — ABD Dolar Endeksi</span>
        </span>
        <span className={`text-[10px] font-black tracking-wide ${toneText}`}>● {regimeLabel}</span>
      </div>

      <div className="flex items-end justify-between gap-3 flex-wrap">
        <div className="flex items-baseline gap-2.5">
          <span className="text-2xl font-black font-mono text-white leading-none">
            {hasPrice ? price.toFixed(2) : "—"}
          </span>
          <span className={`text-xs font-bold font-mono ${changeTone}`}>
            {trendIcon} {changePct >= 0 ? "+" : ""}
            {changePct.toFixed(2)}%
          </span>
        </div>
        <div className="flex items-center gap-3 text-[10px] font-mono text-bunker-muted">
          <span>
            RSI <span className="text-bunker-200 font-bold">{rsi.toFixed(1)}</span>
          </span>
          <span>
            Skor <span className="text-bunker-200 font-bold">{Number(dxy.score ?? 0).toFixed(0)}</span>
          </span>
        </div>
      </div>

      {/* Dinamik progress bar: sol = zayıf dolar bandın altı, sağ = güçlü dolar */}
      <div>
        <div className="w-full h-3 rounded-full bg-bunker-900 border border-bunker-800/80 p-0.5 overflow-hidden relative shadow-inner">
          {/* Nötr (sıkışık) merkez işareti — 100.0 endeks pivodu */}
          <div
            className="absolute top-0 h-full w-px bg-slate-400/40 z-10"
            style={{ left: `${neutralPct}%` }}
          />
          {hasPrice && (
            <div
              className="progress-fill h-full rounded-full transition-all duration-700 ease-out"
              style={{ width: `${pct}%`, ["--progress-color" as string]: fillColor }}
            />
          )}
        </div>
        <div className="flex items-center justify-between text-[9px] text-bunker-muted font-mono mt-1">
          <span className="text-emerald-300/80 font-bold">◀ ZAYIF DOLAR (altın lehine)</span>
          <span className="text-rose-300/80 font-bold">GÜÇLÜ DOLAR (altın aleyhine) ▶</span>
        </div>
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
  const [realizedPnlPips, setRealizedPnlPips] = useState<number>(0.0);
  const [winRate, setWinRate] = useState<number>(0.0);
  const [totalTrades, setTotalTrades] = useState<number>(0);
  const [wins, setWins] = useState<number>(0);
  const [losses, setLosses] = useState<number>(0);
  // BUGÜN kırılımı: tüm zamanlar KPI'larından ayrı tutulur (kullanıcı ikisini
  // yan yana istedi). Kaynak aynı defterdir — backend `daily_*` alanları.
  const [dailyWinRate, setDailyWinRate] = useState<number>(0.0);
  const [dailyTrades, setDailyTrades] = useState<number>(0);
  const [dailyWins, setDailyWins] = useState<number>(0);
  const [dailyLosses, setDailyLosses] = useState<number>(0);
  const [dailyPnlUsd, setDailyPnlUsd] = useState<number>(0.0);
  const [dailyPnlPips, setDailyPnlPips] = useState<number>(0.0);
  // Sembol bazlı KPI dilimleri (backend `per_symbol_today` / `per_symbol_all_time`).
  // İkisi AYNI defterden türetilir; panel ikisini yan yana gösterir.
  const [perSymbolToday, setPerSymbolToday] = useState<SymbolKpi[]>([]);
  const [perSymbolAllTime, setPerSymbolAllTime] = useState<SymbolKpi[]>([]);

  const [openPositions, setOpenPositions] = useState<AutoPosition[]>([]);
  const [closedTrades, setClosedTrades] = useState<ClosedTrade[]>([]);
  const [decisionLogs, setDecisionLogs] = useState<DecisionLog[]>([]);
  const [sessions, setSessions] = useState<any[]>([]);

  // Canlı Gösterge / Ticker / Radar Verileri
  const [tickers, setTickers] = useState<Record<string, TickerData>>({});
  const [radarMap, setRadarMap] = useState<Record<string, RadarCandidate>>({});

  // Motor ayarları kokpit kartlarında ARTIK KULLANILMIYOR: "24s Günlük Fiyat
  // Aralığı", "Spread Emniyet Skalası" ve "Risk / Ödül Skalası" barları
  // kaldırıldığında TP/SL/spread hedeflerini okuyan tek yer kalmadı. Ayar
  // düzenleme zaten /forex/ayarlar sayfasında; burada tutmak ölü durum olurdu.

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

  // Otomatik Yorum (backend'de üretilen insan-okur analiz — 60 sn'de bir yenilenir)
  interface SymbolComment {
    symbol: string;
    display?: string;
    action?: string;
    score?: number;
    strength_label?: string;
    /** Kısa trend etiketi (ör. "Güçlü Trend"), 2026-10-13'te eklendi. */
    trend_label?: string;
    comment: string;
  }
  const [autoComment, setAutoComment] = useState<{
    interval_sec?: number;
    generated_at?: number;
    market_note?: string;
    /** Dinamik DXY panosu (backend `get_dxy_regime()` çıktısı; veri yoksa null). */
    dxy?: {
      regime?: string;
      trend?: string;
      score?: number;
      rsi?: number;
      cmo?: number;
      change_pct?: number;
      price?: number;
      updated_at?: number;
    } | null;
    symbols?: Record<string, SymbolComment>;
  } | null>(null);

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
        setRealizedPnlPips(res.realized_pnl_pips ?? 0.0);
        setTotalTrades(res.total_trades ?? 0);
        setWins(res.wins ?? 0);
        setLosses(res.losses ?? 0);
        setWinRate(res.win_rate ?? 0.0);
        setDailyWinRate(res.daily_win_rate ?? 0.0);
        setDailyTrades(res.daily_trades ?? 0);
        setDailyWins(res.daily_wins ?? 0);
        setDailyLosses(res.daily_losses ?? 0);
        setDailyPnlUsd(res.daily_pnl ?? 0.0);
        setDailyPnlPips(res.daily_pips ?? 0.0);
        setPerSymbolToday(
          (res.per_symbol_today || []).filter((k: SymbolKpi) => symFilter.has(String(k.symbol).toUpperCase()))
        );
        setPerSymbolAllTime(
          (res.per_symbol_all_time || []).filter((k: SymbolKpi) => symFilter.has(String(k.symbol).toUpperCase()))
        );

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

  // PERFORMANS (2026-10-08): 1.5 sn'lik dört-endpoint'li döngü (1) arka planda
  // da dönüyordu ve (2) tur tamamlanmadan yenisi başlıyordu. usePolling ile
  // sekme arka plana geçince tamamen durur, üst üste binme engellenir; aralık
  // 3 sn'ye çıkarıldı (backend teknik önbelleği zaten 15 sn'de tazeleniyor —
  // 1.5 sn'lik sorgu görsel fark üretmiyordu, yalnız CPU/ağ yakıyordu).
  usePolling(fetchAllData, 3000);

  // Otomatik yorum: 60 sn'de bir backend'den insan-okur analiz çeker
  // (gösterge verisi ana döngüyle zaten canlı; yorum metni sakin kalsın diye ayrı yavaş döngü)
  const fetchComment = async () => {
    try {
      const res = await apiFetch("/api/forex/btc-gold/comment");
      if (res) setAutoComment(res);
    } catch (err) {
      console.error("Otomatik yorum hatası:", err);
    }
  };
  usePolling(fetchComment, 60000);

  // Kapısı anlık görünümü (2026-10-10): motorun KENDİ kapı zinciri durumunu
  // kapı-kapı çeker. Ana döngüden ayrı çünkü snapshot ucu kendi 2 sn TTL
  // önbelleğini taşır ve status akışından bağımsız yanıt verir.
  const [gateSnapshots, setGateSnapshots] = useState<Record<string, GateSnapshot>>({});
  const [gateLoading, setGateLoading] = useState<boolean>(true);
  const fetchGateSnapshots = async () => {
    try {
      const results = await Promise.all(
        allowedSymbols.map(async (sym) => {
          const res = await apiFetch(`/api/forex/auto-paper/gate-snapshot/${sym}`);
          return [sym, res] as const;
        })
      );
      setGateSnapshots(Object.fromEntries(results.filter(([, r]) => r)));
    } catch (err) {
      console.error("Kapı görünümü hatası:", err);
    } finally {
      setGateLoading(false);
    }
  };
  usePolling(fetchGateSnapshots, 3000);

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
  const totalOpenPnl = (mt5.open_positions || []).reduce(
    (acc, p) => acc + Number(p.pnl_usd ?? (p as any).profit ?? 0),
    0
  );
  const totalOpenCount = mt5.open_positions?.length || 0;

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
                <span className="text-amber-400 font-bold text-sm">· ODAKLI İZLEME KOKPİTİ</span>
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

      {/* HESAP METRİKLERİ KARTLARI */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
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
            {totalOpenCount} açık MT5 işlemi
          </span>
        </div>

        {/* Başarı oranı — BUGÜN ve TÜM ZAMANLAR ayrı ayrı (kullanıcı isteği
            2026-10-13). İki blok AYNI defterden gelir (backend `daily_*` ve
            üst-düzey alanlar), bu yüzden sayılar birbirini tutar; "bugün"
            tanımı UTC gece yarısıdır (rapor ekranının UTC+3'ünden farklı). */}
        <div className="p-3.5 rounded-xl bg-bunker-900/80 border border-bunker-800 shadow-sm">
          <div className="flex items-center justify-between gap-1">
            <span className="text-[10px] text-bunker-muted uppercase block">Başarı Oranı</span>
            <span className="text-[8px] font-bold px-1.5 py-0.5 rounded bg-blue-500/15 text-blue-300 border border-blue-400/30">
              BUGÜN / TÜM Z.
            </span>
          </div>

          <div className="mt-1 space-y-1.5">
            <div className="flex items-baseline justify-between gap-2">
              <span className="text-[9px] font-bold text-bunker-muted uppercase shrink-0">Bugün</span>
              <span className="text-sm font-bold text-yellow-400 font-mono">%{dailyWinRate.toFixed(1)}</span>
            </div>
            <div className="text-[9px] text-bunker-muted font-mono leading-tight">
              {dailyWins}K / {dailyLosses}Z ({dailyTrades} İşlem)
            </div>
            <div className="text-[9px] font-mono leading-tight">
              <span className="text-bunker-muted">Net: </span>
              <span className={dailyPnlUsd >= 0 ? "text-emerald-400" : "text-rose-400"}>
                {dailyPnlUsd >= 0 ? "+" : ""}${dailyPnlUsd.toFixed(2)}
              </span>
              <span className="text-bunker-muted"> · </span>
              <span className={dailyPnlPips >= 0 ? "text-emerald-400/80" : "text-rose-400/80"}>
                {dailyPnlPips >= 0 ? "+" : ""}{dailyPnlPips.toFixed(1)} pip
              </span>
            </div>
          </div>

          <div className="mt-2 pt-2 border-t border-bunker-800 space-y-1.5">
            <div className="flex items-baseline justify-between gap-2">
              <span className="text-[9px] font-bold text-bunker-muted uppercase shrink-0">Tüm Zamanlar</span>
              <span className="text-sm font-bold text-cyan-300 font-mono">%{winRate.toFixed(1)}</span>
            </div>
            <div className="text-[9px] text-bunker-muted font-mono leading-tight">
              {wins}K / {losses}Z ({totalTrades} İşlem)
            </div>
            <div className="text-[9px] font-mono leading-tight">
              <span className="text-bunker-muted">Net: </span>
              <span className={realizedPnlUsd >= 0 ? "text-emerald-400" : "text-rose-400"}>
                {realizedPnlUsd >= 0 ? "+" : ""}${realizedPnlUsd.toFixed(2)}
              </span>
              <span className="text-bunker-muted"> · </span>
              <span className={realizedPnlPips >= 0 ? "text-emerald-400/80" : "text-rose-400/80"}>
                {realizedPnlPips >= 0 ? "+" : ""}{realizedPnlPips.toFixed(1)} pip
              </span>
            </div>
          </div>
        </div>

        {/* "Kaldıraç & Sunucu" kartı kaldırıldı (kullanıcı isteği 2026-10-13:
            "BUNU KALDIR GEREK YOK") — sabit 1:5000 / ICMarketsSC-Demo bilgisi
            portföy sayfasında zaten var, bu sayfada tekrar değeri yoktu. */}

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
              <span>Açık IC Markets MT5 Pozisyonları ({totalOpenCount})</span>
            </h2>
            <span className="text-[10px] text-amber-400 font-bold px-2 py-0.5 rounded bg-amber-500/15 border border-amber-500/30">
              {totalOpenCount} Aktif MT5 Pozisyonu
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

        {mt5.open_positions?.length === 0 ? (
          <div className="p-8 text-center text-bunker-muted text-xs space-y-1">
            <p className="text-sm font-semibold text-white">Şu an açık bir IC Markets MT5 pozisyonu bulunmuyor.</p>
            <p className="text-bunker-muted">
              {autoEnabled
                ? "Otonom scalper motoru XAUUSD ve BTCUSD sinyallerini denetliyor. Koşullar sağlandığında emir doğrudan MT5 hesabınızda açılacaktır."
                : "Otonom motor durdurulmuş durumda. Yukarıdan '▶ Otonom Scalper'ı Başlat' butonuna basabilir veya aşağıdaki kokpitten hızlı manuel işlem açabilirsiniz."}
            </p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="bg-bunker-950/80 text-bunker-muted uppercase border-b border-bunker-800 text-[10px]">
                <tr>
                  <th className="py-3 px-4">Bilet No</th>
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
                        #{p.ticket}
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

        {/* DİNAMİK DXY PANOSU — piyasa notunun ÜSTÜNDE (kullanıcı isteği 2026-10-13).
            Canlı DXY seviyesi + rejim + dinamik progress bar. DXY verisi yoksa
            (backend `dxy: null`) bileşen hiç gösterilmez; tire/yanlış sayı yok. */}
        {autoComment?.dxy && <DxyProgressPanel dxy={autoComment.dxy} />}

        {/* Ortak Piyasa Notu (DXY + seans + fiyat kaynağı) */}
        {autoComment?.market_note && (
          <div className="p-2.5 rounded-xl bg-bunker-950/80 border border-bunker-800 flex items-start gap-2">
            <span className="text-sm leading-none mt-0.5">🌍</span>
            <p className="text-[11px] leading-relaxed text-bunker-300">{autoComment.market_note}</p>
          </div>
        )}

        {/* 2 SÜTUNLU KOKPİT GRİDİ (XAUUSD & BTCUSD) */}
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
          {allowedSymbols.map((sym) => {
            const isGold = sym === "XAUUSD";
            const candidate = radarMap[sym];
            const tick = tickers[sym];

            // ANLIK DURUM TAZELİĞİ (2026-10-10): eskiden canlı veri gelmediğinde
            // bile kart varsayılan sayılarla (72.0 skor / 58.4 RSI / 68450 fiyat)
            // "sağlıklı" görünüyordu; operatör bunları canlı sanıyordu. Artık
            // canlı kaynak yoksa sayılar soluk gösterilir ve açıkça işaretlenir.
            const hasLive = Boolean(tick || candidate);
            const tickAgeSec =
              typeof tick?.updated_at === "number"
                ? Math.max(0, Math.floor(Date.now() / 1000 - tick.updated_at))
                : null;
            const dataStale = tickAgeSec !== null && tickAgeSec > 30;

            // Motor kapı zinciri (aynı sayfadaki GateSnapshotCard ile aynı kaynak):
            // "sinyal var" ile "emir açılacak" aynı şey değil — rozet bunu ayırır.
            const gate = gateSnapshots[sym] || null;
            const gateReady = gate?.verdict_level === "ready";
            const gateHalted = gate?.verdict_level === "blocked" || gate?.verdict_level === "stopped";
            const blockingLabel =
              gate?.gates?.find((g) => g.key === gate.blocking_gate)?.label || null;

            // Kapı kayıtlarını anahtarla indeksle — anlık durum şeridi bu veriyi
            // tekrar hesaplamaz, motorun kendi ölçtüğü değeri gösterir.
            const gateMap: Record<string, { status: string; detail: string }> = {};
            for (const g of gate?.gates || []) gateMap[g.key] = { status: g.status, detail: g.detail };
            const gs = gate?.settings;

            // Eşik MOTORDAN gelir: skor kapısının detayı motorun kendi cümlesidir
            // ("50.8 < 78 (min_score 78)"), bu yüzden eşiği oradan okuyoruz.
            // XAU'nun eşiği motorda sabit 78.0 olduğu için ayardan okumak yanlış olurdu.
            // İki biçim var: geçen kapı "96.0 ≥ 76 (...)" / engelleyen "50.8 < 78 (...)".
            // Karşılaştırma işaretinden sonraki sayı iki durumda da eşiktir.
            const scoreThreshold =
              Number((gateMap["score"]?.detail || "").match(/[<>≥≤]\s*([\d.]+)/)?.[1]) || null;
            // Soğuma süresi: ayardan; ayar alanı yoksa (eski backend) kapı
            // cümlesindeki "… 60 sn kuralı" ifadesinden okunur — panel tire
            // göstermek yerine motorun gerçekte uyguladığı kuralı yazar.
            const cooldownSec =
              (isGold ? gs?.gold_cooldown_sec : gs?.btc_cooldown_sec) ??
              Number((gateMap["cooldown"]?.detail || "").match(/(\d+(?:\.\d+)?)\s*sn/)?.[1]);

            // Rakamlar & Değerler
            const curPrice = tick?.ask || candidate?.price || (isGold ? 2735.6 : 68450.0);
            const bidPrice = tick?.bid || candidate?.bid || curPrice;
            const askPrice = tick?.ask || candidate?.ask || curPrice;
            const spreadPips = tick?.spread_pips ?? candidate?.spread_pips ?? (isGold ? 1.5 : 12.0);
            const changePct = tick?.change_pct ?? 0.45;

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

            // --- DİNAMİK YÖN (2026-10-13) ---------------------------------
            // MACD histogramının ATR'ye oranı ham momentumu verir; -1..+1'e
            // sıkıştırılır. XAU ile BTC'nin histogram büyüklükleri kıyaslanamaz
            // (farklı fiyat/ATR ölçeği), ATR'ye bölmek bu ölçek farkını siler.
            const clamp1 = (v: number) => Math.max(-1, Math.min(1, isNaN(v) ? 0 : v));
            const macdHist = Number(candidate?.macd_hist ?? tick?.macd_hist ?? 0);
            const atrRaw = Number(candidate?.atr ?? tick?.atr ?? 0);
            const momentumNorm = atrRaw > 0 ? clamp1(macdHist / atrRaw) : 0;
            // Yön barı TEK göstergeye bağlanmaz (o zaman gürültüye açık olurdu):
            // trend + SuperTrend + MACD momentum + RSI konumu + CMO'nun eşit
            // ağırlıklı ortalamasıdır. Hepsi motorun canlı ürettiği alanlardır.
            const trendSign = trend === "BULLISH" ? 1 : trend === "BEARISH" ? -1 : 0;
            const stSign = supertrendDir > 0 ? 1 : supertrendDir < 0 ? -1 : 0;
            const rsiNorm = clamp1((rsi - 50) / 50);
            const cmoNorm = clamp1(cmo / 50);
            const dirScore = hasLive
              ? (trendSign + stSign + momentumNorm + rsiNorm + cmoNorm) / 5
              : 0;
            const dirDetail = hasLive
              ? `Trend ${trend === "BULLISH" ? "Boğa" : trend === "BEARISH" ? "Ayı" : "Yatay"} · SuperTrend ${
                  supertrendDir > 0 ? "Boğa" : "Ayı"
                } · MACD ${macdHist >= 0 ? "+" : ""}${(atrRaw > 0 ? macdHist / atrRaw : 0).toFixed(2)} ATR · RSI ${rsi.toFixed(0)}`
              : "Canlı veri bekleniyor";

            // MACD momentum barının yüzdesi: 50 = nötr, 100 = tam boğa, 0 = tam ayı.
            const macdBarPct = 50 + momentumNorm * 50;

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

                    {/* Sinyal Rozeti + Kapı Durumu (2026-10-10)
                        Sinyal = göstergelerin yönü. Kapı = emrin gerçekten açılıp
                        açılmayacağı. Eskiden yalnız sinyal rozeti vardı; operatör
                        "GÜÇLÜ ALIŞ" görüp emir gelmeyince motoru bozuk sanıyordu.
                        Artık ikisi ayrı gösterilir ve sinyal yeşilken kapı kırmızıysa
                        bunun bir çelişki değil, engel olduğu tek bakışta anlaşılır. */}
                    <div className="text-right space-y-1">
                      <span
                        className={`inline-block px-3 py-1 rounded-xl text-xs font-black border tracking-wider shadow-md ${
                          action === "BUY"
                            ? "bg-emerald-500/20 text-emerald-300 border-emerald-400/50 shadow-[0_0_12px_rgba(16,185,129,0.3)]"
                            : action === "SELL"
                            ? "bg-rose-500/20 text-rose-300 border-rose-400/50 shadow-[0_0_12px_rgba(244,63,94,0.3)]"
                            : "bg-bunker-800 text-bunker-muted border-bunker-700"
                        }`}
                      >
                        {action === "BUY" ? "⚡ GÜÇLÜ ALIŞ (BUY)" : action === "SELL" ? "🔻 GÜÇLÜ SATIŞ (SELL)" : "⏸ BEKLEMEDE (HOLD)"}
                      </span>
                      <div className="flex flex-col items-end gap-1">
                        {gate ? (
                          <span
                            title={gate.verdict}
                            className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-lg text-[9px] font-black border tracking-wide ${
                              gateReady
                                ? "bg-emerald-500/15 text-emerald-300 border-emerald-400/40"
                                : gateHalted
                                ? "bg-rose-500/15 text-rose-300 border-rose-400/40"
                                : "bg-slate-500/15 text-slate-300 border-slate-500/40"
                            }`}
                          >
                            {gateReady
                              ? "🟢 GİRİŞ HAZIR — EMİR AÇILABİLİR"
                              : gateHalted
                              ? `⛔ GİRİŞ ENGELLİ${blockingLabel ? ` — ${blockingLabel}` : ""}`
                              : "⏸ SİNYAL YOK — BEKLEMEDE"}
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-lg text-[9px] font-bold border border-bunker-700 bg-bunker-950 text-bunker-muted">
                            ◦ Kapı durumu okunuyor…
                          </span>
                        )}
                        {/* Veri tazeliği: bayat/kopuk veride sayılar canlı sanılmasın */}
                        {!hasLive ? (
                          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-lg text-[9px] font-bold border border-rose-500/40 bg-rose-500/10 text-rose-300">
                            ⚠ CANLI VERİ YOK — değerler örnek varsayılan
                          </span>
                        ) : dataStale ? (
                          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-lg text-[9px] font-bold border border-amber-500/40 bg-amber-500/10 text-amber-300">
                            🕐 VERİ {tickAgeSec}sn ESKİ
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-lg text-[9px] font-bold border border-emerald-500/30 bg-emerald-500/10 text-emerald-400">
                            ● CANLI ({tickAgeSec !== null ? `${tickAgeSec}sn` : "taze"})
                          </span>
                        )}
                      </div>
                    </div>
                  </div>

                  {/* Fiyat Şeridi */}
                  <div
                    className={`mt-4 p-3 rounded-xl bg-bunker-950/90 border border-bunker-800/80 flex items-center justify-between flex-wrap gap-2 ${
                      hasLive && !dataStale ? "" : "opacity-60"
                    }`}
                  >
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

                  {/* ANLIK MOTOR DURUM ŞERİDİ (2026-10-10)
                      Motorun kendi ölçtüğü kapı verisinden tek satırlık özet:
                      skor/eşik, seri-SL sayacı, soğuma süresi, pozisyon sayısı.
                      Amaç: "sinyal 96 ama emir gelmiyor" sorusunun cevabını
                      log akışına inmeden kartın üstünde görebilmek. Değerler
                      UYDURULMAZ; kapı verisi yoksa tire gösterilir. */}
                  {gate && (
                    <div className="mt-2 flex items-stretch gap-1.5 text-center">
                      {(() => {
                        const gScore = gateMap["score"];
                        const scoreHidden = gScore?.status === "off" || gScore?.status === "na";
                        // Skor MOTORUN ölçtüğü değerdir (kapı detayının başındaki
                        // sayı); ticker'daki kopya biraz geriden gelebiliyor.
                        const engineScore = Number((gScore?.detail || "").match(/^\s*([\d.]+)/)?.[1]);
                        const shownScore = Number.isFinite(engineScore) ? engineScore : score;
                        const lossStreakDetail = gateMap["loss_streak"]?.detail || "";
                        const streakNow = Number(lossStreakDetail.match(/(\d+)\s*\//)?.[1] ?? 0);
                        const cdBlocked = gateMap["cooldown"]?.status === "block";
                        const cells: Array<{ k: string; label: string; value: string; tone: string }> = [
                          {
                            k: "score",
                            label: isGold ? "SKOR / EŞİK" : "SKOR / BTC EŞİĞİ",
                            value:
                              scoreThreshold !== null && !scoreHidden
                                ? `${shownScore.toFixed(0)} / ${scoreThreshold.toFixed(0)}`
                                : `${shownScore.toFixed(0)} / —`,
                            tone:
                              scoreThreshold !== null && shownScore >= scoreThreshold
                                ? "text-emerald-300"
                                : "text-rose-300",
                          },
                          {
                            k: "sl",
                            label: "SERİ-SL",
                            value: `${streakNow} / ${gs?.loss_streak_limit ?? "—"}`,
                            tone: streakNow > 0 ? "text-amber-300" : "text-emerald-300",
                          },
                          {
                            k: "cd",
                            label: isGold ? "SOĞUMA (ALTIN)" : "SOĞUMA (BTC)",
                            value: cdBlocked
                              ? "AKTİF"
                              : !Number.isFinite(cooldownSec)
                              ? "—"
                              : cooldownSec === 0
                              ? "kapalı"
                              : `${(cooldownSec as number).toFixed(0)}sn`,
                            tone: cdBlocked ? "text-rose-300" : "text-emerald-300",
                          },
                          {
                            k: "pos",
                            label: "POZİSYON",
                            value: `${gate.open_positions.length} / ${gs?.max_positions_per_symbol ?? "—"}`,
                            tone: (gateMap["position_limit"]?.status ?? "") === "block" ? "text-rose-300" : "text-emerald-300",
                          },
                          {
                            k: "spread",
                            label: "SPREAD KAPISI",
                            value: (gateMap["spread"]?.detail || "—").split("/")[0].trim(),
                            tone:
                              gateMap["spread"]?.status === "block"
                                ? "text-rose-300"
                                : gateMap["spread"]?.status === "pass"
                                ? "text-emerald-300"
                                : "text-bunker-muted",
                          },
                        ];
                        return cells.map((c) => (
                          <div
                            key={c.k}
                            className="flex-1 min-w-0 px-1.5 py-1.5 rounded-lg bg-bunker-950/70 border border-bunker-800"
                          >
                            <span className="block text-[8px] text-bunker-muted uppercase tracking-wider truncate">
                              {c.label}
                            </span>
                            <span className={`block text-[11px] font-black font-mono ${c.tone}`}>{c.value}</span>
                          </div>
                        ));
                      })()}
                    </div>
                  )}
                </div>

                {/* 2. GAUGELER BÖLÜMÜ (İbreli Yarım Daire SVG Göstergeler)
                    Veri yokken/solukken bölüm soluklaştırılır: ibreler varsayılan
                    sayıları gösterdiğinde canlı sanılmasın. */}
                <div
                  className={`p-4 border-b border-bunker-800 bg-bunker-950/40 ${
                    hasLive && !dataStale ? "" : "opacity-60"
                  }`}
                >
                  <div className="text-[11px] font-bold text-white uppercase tracking-wider mb-2.5 flex items-center gap-1.5">
                    <span>🧭</span>
                    <span>Hassas İbreli Göstergeler (Cockpit Gauges)</span>
                  </div>

                  {/* Yön barı — bloğun EN ÜSTÜNDE: ortası NÖTR, sağ BUY, sol SELL.
                      Değeri motorun canlı göstergelerinden türetilir (bkz. dirScore). */}
                  <div className="mb-2.5">
                    <DirectionBar value={dirScore} detail={dirDetail} hasData={hasLive} />
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

                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                    {/* Bar: MACD Histogram & Momentum (gerçek ATR-normalize histogram) */}
                    <ProgressBarCard
                      title="MACD Momentum"
                      icon="🌊"
                      valueText={macdVerdict}
                      subText="Momentum Yönü"
                      percentage={macdBarPct}
                      leftLabel="Ayı Satış"
                      rightLabel="Boğa Alış"
                      barColor={momentumNorm > NEUTRAL_DEAD_ZONE ? "emerald" : momentumNorm < -NEUTRAL_DEAD_ZONE ? "rose" : "amber"}
                    />

                    {/* Bar: Volatilite & Osilatörler (CMO & CCI) */}
                    <ProgressBarCard
                      title="Chande (CMO) & CCI"
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

                {/* 3b. SEMBOL BAŞARI ORANI — BUGÜN & TÜM ZAMANLAR (2026-10-13)
                    Kullanıcı isteği: başarı oranı her sembolde iki dönem için
                    ayrı gösterilir. Kaynak backend `per_symbol_today` /
                    `per_symbol_all_time`; ikisi aynı defterden → tutarlı. */}
                <div className="px-4 pb-1">
                  <div className="text-[11px] font-bold text-white uppercase tracking-wider mb-2 flex items-center gap-1.5">
                    <span>🏆</span>
                    <span>{sym} Başarı Oranı</span>
                  </div>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
                    <WinRateBlock
                      title="BUGÜN"
                      kpi={perSymbolToday.find((k) => k.symbol.toUpperCase() === sym) || null}
                      accent="text-blue-300"
                    />
                    <WinRateBlock
                      title="TÜM ZAMANLAR"
                      kpi={perSymbolAllTime.find((k) => k.symbol.toUpperCase() === sym) || null}
                      accent="text-cyan-300"
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

                {/* KAPISI ANLIK GÖRÜNÜMÜ — motorun kendi kapı zinciri durumu (2026-10-10) */}
                <div className="px-4 pb-4">
                  <GateSnapshotCard
                    snapshot={gateSnapshots[sym] || null}
                    loading={gateLoading}
                    isBtc={!isGold}
                  />
                </div>

                {/* OTOMATİK YORUM — sade ve net (2026-10-13)
                    Backend metni 2-4 kısa cümleye indirildi; panelde önce
                    "ne oluyor" tek satırda, sonra açıklama okunur. Rozet yalnız
                    gerçekten bir eylem varsa (BUY/SELL) gösterilir. */}
                {(() => {
                  const c = autoComment?.symbols?.[sym];
                  const hasSignal = c?.action === "BUY" || c?.action === "SELL";
                  const badgeCls =
                    c?.action === "BUY"
                      ? "bg-emerald-500/15 text-emerald-300 border-emerald-500/40"
                      : "bg-rose-500/15 text-rose-300 border-rose-500/40";
                  const summary = hasSignal
                    ? `${c?.trend_label || "Sinyal"} — ${c?.action === "BUY" ? "alış" : "satış"} yönü`
                    : "Belirgin bir yön yok — izlemede";
                  return (
                    <div className="mx-4 mb-4 p-3.5 rounded-xl bg-bunker-950/70 border border-bunker-700/60">
                      <div className="flex items-center justify-between gap-2 mb-2 flex-wrap">
                        <div className="flex items-center gap-2">
                          <span className="text-sm leading-none">🤖</span>
                          <span className="text-[10px] font-black uppercase tracking-wider text-bunker-300">
                            Otomatik Yorum
                          </span>
                          {hasSignal && (
                            <span className={`px-1.5 py-0.5 rounded text-[9px] font-black border ${badgeCls}`}>
                              {c?.action}
                            </span>
                          )}
                        </div>
                        <span className="text-[9px] text-bunker-muted">60 sn'de bir yenilenir</span>
                      </div>

                      <p className="text-[13px] font-bold text-white leading-snug">{summary}</p>
                      <p className="text-[12px] leading-relaxed text-bunker-300 select-text mt-1">
                        {c?.comment || "Yorum hazırlanıyor…"}
                      </p>
                      {typeof c?.score === "number" && c.score > 0 && (
                        <p className="text-[10px] text-bunker-muted mt-1.5 font-mono">
                          Güç: {c.strength_label} ({c.score}/100)
                        </p>
                      )}
                    </div>
                  );
                })()}
              </div>
            );
          })}
        </div>
      </div>

      {/* =========================================================================
          3. ALT KISIM: CANLI LOG AKIŞI (TERMINAL & STREAM)
      ========================================================================= */}
      <div className="w-full">
        {/* CANLI LOG AKIŞI (Terminal Konsolu - Tam Genişlik) */}
        <div className="w-full rounded-2xl border border-bunker-800 bg-bunker-950 p-4 shadow-2xl flex flex-col h-[480px]">
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

            <div className="flex items-center gap-3">
              <Link
                href="/forex/reports"
                className="text-[10px] font-bold text-amber-400 hover:text-amber-300 transition-colors flex items-center gap-1"
              >
                <span>📜 Kapanan İşlem Raporları</span>
                <span>→</span>
              </Link>
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
