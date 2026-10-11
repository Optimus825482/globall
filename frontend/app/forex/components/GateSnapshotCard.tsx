"use client";

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

function OpenPositionRow({
  p,
}: {
  p: NonNullable<GateSnapshot["open_positions"]>[number];
}) {
  const isProfit = p.pnl_usd >= 0;
  const protectedLabel = p.trailing_activated
    ? { txt: "TRAILING", cls: "bg-amber-500/15 text-amber-300 border-amber-400/30" }
    : p.breakeven_activated
    ? { txt: "BE", cls: "bg-cyan-500/15 text-cyan-300 border-cyan-400/30" }
    : { txt: "SABİT SL", cls: "bg-bunker-800 text-bunker-muted border-bunker-700" };
  return (
    <div className="p-2.5 rounded-lg bg-bunker-950/70 border border-bunker-800">
      <div className="flex items-center justify-between gap-2 flex-wrap mb-1">
        <div className="flex items-center gap-1.5 flex-wrap">
          <span
            className={`px-1.5 py-0.5 rounded text-[9px] font-black ${
              p.direction === "BUY"
                ? "bg-emerald-500/15 text-emerald-400 border border-emerald-500/30"
                : "bg-rose-500/15 text-rose-400 border border-rose-500/30"
            }`}
          >
            {p.direction}
          </span>
          <span className="text-[10px] font-bold text-white font-mono">{p.lots} lot</span>
          <span className={`px-1.5 py-0.5 rounded text-[9px] font-bold border ${protectedLabel.cls}`}>
            {protectedLabel.txt}
          </span>
          {p.ticket ? <span className="text-[9px] text-cyan-300 font-mono">#{p.ticket}</span> : null}
        </div>
        <span className={`text-xs font-black font-mono ${isProfit ? "text-emerald-400" : "text-rose-400"}`}>
          {isProfit ? "+" : ""}${p.pnl_usd.toFixed(2)}
        </span>
      </div>
      <div className="flex items-center justify-between gap-2 text-[9px] text-bunker-muted font-mono flex-wrap">
        <span>Giriş: {p.entry_price}</span>
        <span className={isProfit ? "text-emerald-400/80" : "text-rose-400/80"}>
          {p.pnl_pips >= 0 ? "+" : ""}
          {p.pnl_pips.toFixed(1)}p
        </span>
        <span className="text-rose-300/80">SL: {p.sl_price || "-"}</span>
        <span className="text-emerald-300/80">TP: {p.tp_price || "-"}</span>
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
  loading,
  isBtc,
}: {
  snapshot: GateSnapshot | null;
  loading: boolean;
  isBtc?: boolean;
}) {
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
      {/* Başlık */}
      <div className={`px-4 py-3 border-b border-bunker-800 bg-gradient-to-r ${isBtc ? "from-orange-950/30" : "from-amber-950/30"} via-bunker-900 to-transparent`}>
        <div className="flex items-center justify-between gap-2 flex-wrap">
          <div className="flex items-center gap-2">
            <span>🚦</span>
            <h4 className="text-[11px] font-black text-white uppercase tracking-wider">
              Giriş Kapısı Zinciri — Neden İşlem Açmıyor?
            </h4>
          </div>
          <span className="text-[9px] text-bunker-muted font-mono">
            {passedCount} geçti · {blockedCount} engel · {offCount} devre dışı{naCount ? ` · ${naCount} beklemede` : ""}
          </span>
        </div>
        {/* Tek cümlelik verdict */}
        <div className={`mt-2 px-3 py-2 rounded-xl border ${v.border} ${v.bg} flex items-start gap-2`}>
          <span className="text-xs leading-none mt-0.5">{v.icon}</span>
          <p className={`text-[11px] font-bold leading-relaxed ${v.text} select-text`}>{snapshot.verdict}</p>
        </div>
      </div>

      {/* Kapı satırları */}
      <div className="p-3 space-y-1.5">
        {snapshot.gates.map((g) => (
          <GateRow key={g.key} gate={g} />
        ))}
      </div>

      {/* Uygulanan koruma ayarları — "emir açılırsa nasıl yönetilecek?"
          Kapı zinciri girişi anlatır; bu şerit çıkışı/riski anlatır. BTC'de
          TP'nin kapalı olması ve SL'nin ATR katına bağlı olması operatörün
          en çok şaşırdığı iki gerçek olduğu için açıkça yazılır.
          ÖNEMLİ: hücreler motorun GERÇEK kapsamına göre ayrılır — ATR-SL/TP
          yalnız kriptoda etkilidir (motorda "BTC"/"ETH" koşulu), risk kısıtı
          ise kripto+altında ortak (`is_crypto or is_gold`). XAU kartında
          kripto hücresi göstermek yanlış bilgi olurdu. */}
      {(() => {
        const s = snapshot.settings;
        const cell = (label: string, value: string, tone: string, on: boolean) => ({
          label,
          value,
          tone,
          on,
        });
        const cryptoCells = isBtc
          ? [
              cell("SL (ATR katı)", `${s.crypto_sl_atr_mult}×`, "text-cyan-300", true),
              cell(
                "Sabit TP",
                s.crypto_tp_enabled ? "AÇIK" : "KAPALI",
                s.crypto_tp_enabled ? "text-emerald-300" : "text-amber-300",
                s.crypto_tp_enabled
              ),
              cell(
                "EV Muafiyeti",
                s.btc_ev_exempt ? "MUAF" : "TABİ",
                s.btc_ev_exempt ? "text-amber-300" : "text-emerald-300",
                !s.btc_ev_exempt
              ),
              cell(
                "Net-Negatif Freni",
                s.btc_net_negative_guard_enabled ? "AÇIK" : "KAPALI",
                s.btc_net_negative_guard_enabled ? "text-amber-300" : "text-bunker-muted",
                s.btc_net_negative_guard_enabled
              ),
            ]
          : [];
        const cdSec = isBtc ? s.btc_cooldown_sec : s.gold_cooldown_sec;
        const commonCells = [
          cell(
            "Kapanış Soğuması",
            cdSec == null ? "—" : cdSec > 0 ? `${cdSec}s` : "kapalı",
            cdSec == null ? "text-bunker-muted" : cdSec > 0 ? "text-cyan-300" : "text-amber-300",
            (cdSec ?? 0) > 0
          ),
          cell(
            "Risk Kısıtı",
            s.crypto_risk_clamp_enabled ? "AÇIK" : "KAPALI",
            s.crypto_risk_clamp_enabled ? "text-emerald-300" : "text-rose-300",
            s.crypto_risk_clamp_enabled
          ),
          cell(
            "SuperTrend Teyidi",
            s.supertrend_filter_enabled ? "AÇIK" : "KAPALI",
            s.supertrend_filter_enabled ? "text-emerald-300" : "text-amber-300",
            s.supertrend_filter_enabled
          ),
          cell(
            "ADX Kalkanı",
            s.adx_filter_enabled ? "AÇIK" : "KAPALI",
            s.adx_filter_enabled ? "text-emerald-300" : "text-bunker-muted",
            s.adx_filter_enabled
          ),
        ];
        return (
          <div className="px-3 pb-3">
            <div className="text-[10px] font-black text-bunker-muted uppercase tracking-wider pt-1 pb-1.5">
              Uygulanan Koruma Ayarları
            </div>
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-1.5">
              {[...cryptoCells, ...commonCells].map((it) => (
                <div
                  key={it.label}
                  className={`px-2 py-1.5 rounded-lg border ${
                    it.on ? "border-bunker-700 bg-bunker-950/70" : "border-bunker-800 bg-bunker-950/40"
                  }`}
                >
                  <span className="block text-[8px] text-bunker-muted uppercase tracking-wider truncate">
                    {it.label}
                  </span>
                  <span className={`block text-[11px] font-black font-mono ${it.tone}`}>{it.value}</span>
                </div>
              ))}
            </div>
          </div>
        );
      })()}

      {/* Açık pozisyonlar */}
      {snapshot.open_positions.length > 0 && (
        <div className="px-3 pb-3 space-y-1.5">
          <div className="text-[10px] font-black text-bunker-muted uppercase tracking-wider pt-1">
            {snapshot.symbol} Açık Pozisyonlar ({snapshot.open_positions.length})
          </div>
          {snapshot.open_positions.map((p, i) => (
            <OpenPositionRow key={`${p.ticket || "pos"}-${i}`} p={p} />
          ))}
        </div>
      )}
    </div>
  );
}
