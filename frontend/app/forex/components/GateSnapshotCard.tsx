"use client";

import { useState } from "react";

// ============================================================================
// KAPISI ANLIK GÖRÜNÜMÜ (2026-10-10) — kokpit paneli
// ============================================================================
// Kaynak: GET /api/forex/auto-paper/gate-snapshot/{symbol}
//
// NEDEN: operatör "BTC neden işlem açmıyor?" sorusunu log akışında arıyordu;
// cevap 18 kapılı zincirin hangi halkasında takıldığıydı. Bu kart, motorun
// KENDİ yardımcı fonksiyonlarının (backend `get_symbol_gate_snapshot`)
// ürettiği kapı-kapı durumu gösterir — panelde ayrı bir kural seti YOKTUR,
// bu yüzden karar akışından kopamaz.
//
// Arka plan: status ∈ {pass, block, na, off}
//   pass  → kapı açıldı, sıradakine geçildi
//   block → giriş bu kapıda DURDU (kırmızı)
//   off   → kapı bu sembol için tasarım gereği kapalı/devre dışı (gri)
//   na    → veri/yön teyidi olmadığından değerlendirilemedi (nötr)
// ============================================================================

export interface GateInfo {
  key: string;
  label: string;
  status: "pass" | "block" | "na" | "off";
  detail: string;
}

export interface GateSnapshot {
  symbol: string;
  generated_at: number;
  action: string;
  verdict: string;
  verdict_level: "ready" | "blocked" | "idle" | "stopped";
  blocking_gate: string | null;
  gates: GateInfo[];
  open_positions: Array<{
    ticket?: number;
    direction: string;
    lots: number;
    entry_price: number;
    current_price: number;
    sl_price: number;
    tp_price: number;
    pnl_usd: number;
    pnl_pips: number;
    breakeven_activated: boolean;
    trailing_activated: boolean;
    open_time: string;
    strategy_label: string;
  }>;
  settings: {
    // Opsiyonel: eski backend sürümlerinde bulunmayabilir — kart o durumda
    // "kapalı" gibi yanlış bir iddia yerine tire gösterir.
    gold_cooldown_sec?: number;
    btc_min_score: number;
    btc_cooldown_sec: number;
    btc_ev_exempt: boolean;
    btc_net_negative_guard_enabled: boolean;
    crypto_sl_atr_mult: number;
    crypto_tp_enabled: boolean;
    crypto_risk_clamp_enabled: boolean;
    loss_streak_limit: number;
    max_positions_per_symbol: number;
    supertrend_filter_enabled: boolean;
    adx_filter_enabled: boolean;
  };
}

const STATUS_STYLE: Record<
  GateInfo["status"],
  { dot: string; text: string; icon: string; ring: string; title: string }
> = {
  block: {
    dot: "bg-rose-500",
    text: "text-rose-300",
    icon: "⛔",
    ring: "border-rose-500/40 bg-rose-500/5",
    title: "ENGELLEDİ",
  },
  pass: {
    dot: "bg-emerald-500",
    text: "text-emerald-300",
    icon: "✓",
    ring: "border-emerald-500/25 bg-emerald-500/5",
    title: "GEÇTİ",
  },
  na: {
    dot: "bg-slate-500",
    text: "text-bunker-muted",
    icon: "○",
    ring: "border-bunker-700/60 bg-bunker-900/40",
    title: "DEĞERLENDİRİLEMEDİ",
  },
  off: {
    dot: "bg-bunker-600",
    text: "text-bunker-muted",
    icon: "—",
    ring: "border-bunker-800 bg-bunker-900/40",
    title: "DEVRE DIŞI",
  },
};

function GateRow({ gate }: { gate: GateInfo }) {
  const st = STATUS_STYLE[gate.status] || STATUS_STYLE.na;
  return (
    <div className={`flex items-start gap-2.5 px-3 py-2 rounded-lg border ${st.ring}`}>
      <span className={`mt-1.5 w-2 h-2 rounded-full shrink-0 ${st.dot} ${gate.status === "block" ? "animate-pulse" : ""}`} />
      <div className="min-w-0 flex-1">
        <div className="flex items-center justify-between gap-2 flex-wrap">
          <span className="text-[11px] font-bold text-white">{gate.label}</span>
          <span className={`text-[9px] font-black tracking-wider ${st.text}`}>
            {st.icon} {st.title}
          </span>
        </div>
        <p className="text-[10px] leading-relaxed text-bunker-300 mt-0.5 select-text">{gate.detail}</p>
      </div>
    </div>
  );
}

const VERDICT_STYLE: Record<GateSnapshot["verdict_level"], { border: string; bg: string; text: string; icon: string }> = {
  ready: { border: "border-emerald-500/50", bg: "bg-emerald-500/10", text: "text-emerald-300", icon: "🟢" },
  blocked: { border: "border-rose-500/50", bg: "bg-rose-500/10", text: "text-rose-300", icon: "⛔" },
  idle: { border: "border-slate-600/50", bg: "bg-slate-500/10", text: "text-slate-300", icon: "⏸" },
  stopped: { border: "border-bunker-600/50", bg: "bg-bunker-800/60", text: "text-bunker-muted", icon: "⏹" },
};

export default function GateSnapshotCard({
  snapshot,
  loading = false,
  isBtc,
}: {
  snapshot: GateSnapshot | null;
  loading?: boolean;
  isBtc?: boolean;
}) {
  // Akordeon (2026-10-13): zincir 12+ satır yer kapladığı için varsayılan
  // KAPALI. Kanca erken `return`'lerden ÖNCE çağrılmalı (React kuralı), bu
  // yüzden state yukarıda — snapshot yokken de hook sırası sabit kalır.
  const [expanded, setExpanded] = useState(false);
  if (!snapshot && loading) {
    return (
      <div className="p-4 rounded-2xl border border-bunker-800 bg-bunker-950/60 text-center">
        <p className="text-[11px] text-bunker-muted animate-pulse">Kapı zinciri okunuyor…</p>
      </div>
    );
  }
  if (!snapshot) {
    return (
      <div className="p-4 rounded-2xl border border-bunker-800 bg-bunker-950/60 text-center">
        <p className="text-[11px] text-bunker-muted">Kapı verisi alınamadı (backend erişilemez).</p>
      </div>
    );
  }

  const v = VERDICT_STYLE[snapshot.verdict_level] || VERDICT_STYLE.idle;
  const blockedCount = snapshot.gates.filter((g) => g.status === "block").length;
  const passedCount = snapshot.gates.filter((g) => g.status === "pass").length;
  const offCount = snapshot.gates.filter((g) => g.status === "off").length;
  const naCount = snapshot.gates.filter((g) => g.status === "na").length;

  return (
    <div className={`rounded-2xl border ${isBtc ? "border-orange-500/30" : "border-amber-500/30"} bg-bunker-900/70 overflow-hidden shadow-xl`}>
      {/* Başlık — tıklanabilir akordeon düğmesi (varsayılan KAPALI).
          Özet (verdict + sayaçlar) kapalıyken de görünür: operatör "neden
          işlem açılmıyor" cevabını açmadan okuyabilir; zincirin tamamı
          (12+ kapı satırı) yalnız istenince açılır. */}
      <button
        type="button"
        onClick={() => setExpanded((e) => !e)}
        aria-expanded={expanded}
        className={`w-full text-left px-4 py-3 bg-gradient-to-r ${isBtc ? "from-orange-950/30" : "from-amber-950/30"} via-bunker-900 to-transparent hover:via-bunker-800/60 transition-colors`}
      >
        <div className="flex items-center justify-between gap-2 flex-wrap">
          <div className="flex items-center gap-2">
            <span
              className={`text-[10px] text-bunker-muted transition-transform duration-200 ${
                expanded ? "rotate-90" : ""
              }`}
            >
              ▶
            </span>
            <span>🚦</span>
            <h4 className="text-[11px] font-black text-white uppercase tracking-wider">
              Giriş Kapısı Zinciri — Neden İşlem Açmıyor?
            </h4>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-[9px] text-bunker-muted font-mono">
              {passedCount} geçti · {blockedCount} engel · {offCount} devre dışı{naCount ? ` · ${naCount} beklemede` : ""}
            </span>
            <span className="text-[9px] font-bold text-bunker-muted border border-bunker-700 rounded px-1.5 py-0.5">
              {expanded ? "Kapat ▲" : "Detayı Aç ▼"}
            </span>
          </div>
        </div>
        {/* Tek cümlelik verdict — akordeon kapalıyken de görünür */}
        <div className={`mt-2 px-3 py-2 rounded-xl border ${v.border} ${v.bg} flex items-start gap-2`}>
          <span className="text-xs leading-none mt-0.5">{v.icon}</span>
          <p className={`text-[11px] font-bold leading-relaxed ${v.text} select-text`}>{snapshot.verdict}</p>
        </div>
      </button>

      {/* Kapı satırları — yalnız açıkken */}
      {expanded && (
        <div className="p-3 space-y-1.5 border-t border-bunker-800">
          {snapshot.gates.map((g) => (
            <GateRow key={g.key} gate={g} />
          ))}
        </div>
      )}
    </div>
  );
}
