"use client";

import React, { useCallback, useMemo, useState } from "react";
import { apiFetch } from "../../lib/api";
import { usePolling } from "../../lib/usePolling";
import { formatUtc3 } from "../../lib/format";

interface SupervisorLogEvent {
  id?: number | string;
  ts: number | string;
  ticket?: number | string | null;
  symbol?: string | null;
  kind?: string | null;
  detail?: string | null;
  action?: string | null;
  mode?: string | null;
}

interface ExcursionStats {
  n_closed?: number;
  n_open?: number;
  winners?: number;
  losers?: number;
  winner_mae_p80_pips?: number | null;
  winner_mae_median_pips?: number | null;
  loser_mfe_median_pips?: number | null;
  loser_mfe_p80_pips?: number | null;
  winner_minutes_to_mfe_median?: number | null;
  suggested_time_stop_minutes?: number | null;
  edge_ratio?: number | null;
  sample_note?: string | null;
  hint?: string | null;
}

interface ScorecardLesson {
  ticket?: number;
  symbol?: string;
  direction?: string;
  session?: string;
  action_taken?: string;
  verdict?: "helpful" | "premature" | "neutral" | string;
  saved_or_missed_usd?: number;
  lesson?: string;
  created_at?: number;
}

interface SupervisorScorecard {
  toplam_degerlendirilen: number;
  faydali_sayisi: number;
  erken_cikis_sayisi: number;
  notr_sayisi: number;
  isabet_orani_pct: number | null;
  net_etki_usd: number;
  son_dersler: ScorecardLesson[];
}

type ActionCategory =
  | "ALL"
  | "tighten_sl"
  | "adjust_tp"
  | "breakeven"
  | "trailing"
  | "partial_close"
  | "close"
  | "hold";

const PERIOD_OPTIONS: Array<{ days: number; label: string }> = [
  { days: 1, label: "Bugün" },
  { days: 7, label: "Son 7 gün" },
  { days: 30, label: "Son 30 gün" },
];

const ACTION_PILLS: Array<{ key: ActionCategory; label: string; cls: string }> = [
  { key: "tighten_sl", label: "SL Sıkılaştır", cls: "bg-sky-500/15 text-sky-300 border-sky-500/40" },
  { key: "adjust_tp", label: "TP Güncelle", cls: "bg-emerald-500/15 text-emerald-300 border-emerald-500/40" },
  { key: "breakeven", label: "BE", cls: "bg-cyan-500/15 text-cyan-300 border-cyan-500/40" },
  { key: "trailing", label: "Trailing", cls: "bg-purple-500/15 text-purple-300 border-purple-500/40" },
  { key: "partial_close", label: "Kısmi Kapat", cls: "bg-amber-500/15 text-amber-300 border-amber-500/40" },
  { key: "close", label: "Kapat", cls: "bg-rose-500/15 text-rose-300 border-rose-500/40" },
  { key: "hold", label: "Tut", cls: "bg-bunker-800 text-bunker-muted border-bunker-700" },
];

interface ParsedEvent {
  raw: SupervisorLogEvent;
  category: Exclude<ActionCategory, "ALL">;
  badgeLabel: string;
  badgeCls: string;
  applied: boolean;
  reason: string;
}

function classifyAction(rawAction?: string | null, pct?: number | null): {
  category: Exclude<ActionCategory, "ALL">;
  label: string;
  cls: string;
} {
  const a = String(rawAction || "").toLowerCase().trim();
  if (a === "adjust_tp" || a.includes("adjust_tp") || a === "modify_tp") {
    return {
      category: "adjust_tp",
      label: "TP Güncelle",
      cls: "bg-emerald-500/15 text-emerald-300 border-emerald-500/40",
    };
  }
  if (a.includes("breakeven") || a === "be" || a === "move_sl_to_breakeven") {
    return { category: "breakeven", label: "BE", cls: "bg-cyan-500/15 text-cyan-300 border-cyan-500/40" };
  }
  if (a.includes("trail")) {
    return { category: "trailing", label: "Trailing", cls: "bg-purple-500/15 text-purple-300 border-purple-500/40" };
  }
  if (a.includes("partial") || a.includes("close_partial")) {
    const suffix = typeof pct === "number" && Number.isFinite(pct) ? ` %${pct}` : "";
    return {
      category: "partial_close",
      label: `Kısmi Kapat${suffix}`,
      cls: "bg-amber-500/15 text-amber-300 border-amber-500/40",
    };
  }
  if (a === "komut:modify_sltp" || a === "modify_sltp") {
    return {
      category: "tighten_sl",
      label: "SL/TP Güncelle",
      cls: "bg-sky-500/15 text-sky-300 border-sky-500/40",
    };
  }
  if (a.includes("tighten") || a.includes("modify_sl")) {
    return { category: "tighten_sl", label: "SL Sıkılaştır", cls: "bg-sky-500/15 text-sky-300 border-sky-500/40" };
  }
  if (a === "close" || a === "close_order" || a === "komut:close_order") {
    return { category: "close", label: "Kapat", cls: "bg-rose-500/15 text-rose-300 border-rose-500/40" };
  }
  return { category: "hold", label: "Tut", cls: "bg-bunker-800 text-bunker-muted border-bunker-700" };
}

function parseSupervisorEvent(ev: SupervisorLogEvent): ParsedEvent {
  let effectiveAction = String(ev.action || "");
  let reason = String(ev.detail || "");
  let pct: number | null = null;
  let appliedFromJson: boolean | null = null;

  if (reason.trim().startsWith("{")) {
    try {
      const parsed = JSON.parse(reason) as {
        proposal?: { action?: string; reason?: string; pct?: number };
        applied_cmd?: { action?: string } | null;
        reason?: string;
      };
      if (parsed && typeof parsed === "object") {
        if (parsed.proposal?.action) {
          effectiveAction = parsed.proposal.action;
        }
        if (typeof parsed.proposal?.pct === "number") {
          pct = parsed.proposal.pct;
        }
        if (parsed.applied_cmd) {
          appliedFromJson = true;
        }
        reason = parsed.proposal?.reason || parsed.reason || reason;
      }
    } catch {
      // Ham metin olarak göster
    }
  }

  const rawActLow = String(ev.action || "").toLowerCase();
  const modeLow = String(ev.mode || "").toLowerCase();
  const applied =
    appliedFromJson === true ||
    rawActLow.startsWith("komut:") ||
    modeLow === "act" ||
    modeLow === "applied";

  const clsInfo = classifyAction(effectiveAction, pct);

  return {
    raw: ev,
    category: clsInfo.category,
    badgeLabel: clsInfo.label,
    badgeCls: clsInfo.cls,
    applied,
    reason: reason || "—",
  };
}

function fmtPip(v?: number | null): string {
  if (typeof v !== "number" || !Number.isFinite(v)) return "—";
  return `${v.toFixed(1)} pip`;
}

function fmtUsd(v?: number | null): string {
  if (typeof v !== "number" || !Number.isFinite(v)) return "—";
  const sign = v >= 0 ? "+" : "-";
  return `${sign}$${Math.abs(v).toFixed(2)}`;
}

function formatSessionLabel(raw?: string | null): string {
  const s = String(raw || "").toUpperCase().trim();
  if (!s) return "—";
  if (s === "ASYA") return "Asya";
  if (s === "LONDRA") return "Londra";
  if (s === "LONDRA_NY_KESISIM") return "Londra–NY Kesişim";
  if (s === "NEW_YORK") return "New York";
  return s.replace(/_/g, " ");
}

function getVerdictBadge(verdict?: string | null): { label: string; cls: string } {
  const v = String(verdict || "").toLowerCase().trim();
  if (v === "helpful" || v === "faydali" || v === "faydalı") {
    return {
      label: "Faydalı",
      cls: "bg-emerald-500/15 border-emerald-500/40 text-emerald-300",
    };
  }
  if (v === "premature" || v === "erken_cikis" || v === "erken çıkış") {
    return {
      label: "Erken Çıkış",
      cls: "bg-amber-500/15 border-amber-500/40 text-amber-300",
    };
  }
  return {
    label: "Nötr",
    cls: "bg-slate-500/15 border-slate-500/40 text-slate-300",
  };
}

export default function PositionSupervisorReport() {
  const [days, setDays] = useState<number>(7);
  const [events, setEvents] = useState<SupervisorLogEvent[]>([]);
  const [scorecard, setScorecard] = useState<SupervisorScorecard | null>(null);
  const [stats, setStats] = useState<ExcursionStats | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string>("");

  // Tablo filtreleri
  const [actionFilter, setActionFilter] = useState<ActionCategory>("ALL");
  const [modeFilter, setModeFilter] = useState<"ALL" | "APPLIED" | "PROPOSED">("ALL");
  const [search, setSearch] = useState<string>("");

  const load = useCallback(async () => {
    try {
      const [logRes, excRes] = await Promise.all([
        apiFetch(`/api/positions/supervisor-log?days=${days}&limit=300`),
        apiFetch(`/api/positions/excursions?days=${days}`),
      ]);
      const typedLogRes = logRes as {
        events?: SupervisorLogEvent[];
        scorecard?: SupervisorScorecard | null;
      } | null;
      const rawEvents = Array.isArray(typedLogRes?.events) ? typedLogRes.events : [];
      setEvents(rawEvents);
      setScorecard(typedLogRes?.scorecard ?? null);
      setStats(((excRes as { stats?: ExcursionStats })?.stats) || null);
      setError("");
    } catch (e) {
      setError(
        e instanceof Error && e.message
          ? `Pozisyon Doktoru raporu alınamadı: ${e.message}`
          : "Pozisyon Doktoru raporu alınamadı",
      );
    } finally {
      setLoading(false);
    }
  }, [days]);

  usePolling(load, 30_000);

  const parsedEvents = useMemo(() => events.map(parseSupervisorEvent), [events]);

  const appliedCount = useMemo(
    () => parsedEvents.filter((e) => e.applied).length,
    [parsedEvents],
  );
  const proposedCount = parsedEvents.length - appliedCount;

  const breakdownCounts = useMemo(() => {
    const counts: Record<Exclude<ActionCategory, "ALL">, number> = {
      tighten_sl: 0,
      adjust_tp: 0,
      breakeven: 0,
      trailing: 0,
      partial_close: 0,
      close: 0,
      hold: 0,
    };
    for (const e of parsedEvents) {
      counts[e.category] += 1;
    }
    return counts;
  }, [parsedEvents]);

  const filteredEvents = useMemo(() => {
    const q = search.trim().toLowerCase();
    return parsedEvents.filter((e) => {
      if (actionFilter !== "ALL" && e.category !== actionFilter) return false;
      if (modeFilter === "APPLIED" && !e.applied) return false;
      if (modeFilter === "PROPOSED" && e.applied) return false;
      if (q) {
        const hay = `${e.raw.symbol ?? ""} ${e.raw.ticket ?? ""} ${e.badgeLabel} ${e.reason}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
  }, [parsedEvents, actionFilter, modeFilter, search]);

  return (
    <div className="space-y-5">
      {/* DÖNEM SEÇİCİ */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-2xs text-bunker-muted font-mono uppercase tracking-wider font-bold">
            Dönem:
          </span>
          {PERIOD_OPTIONS.map((opt) => {
            const active = days === opt.days;
            return (
              <button
                key={opt.days}
                type="button"
                onClick={() => {
                  setLoading(true);
                  setDays(opt.days);
                }}
                className={`min-h-9 px-3 rounded-lg border font-mono text-xs font-bold transition-colors ${
                  active
                    ? "bg-blue-500/20 border-blue-400/60 text-blue-200"
                    : "bg-bunker-900 border-bunker-800 text-bunker-muted hover:text-white"
                }`}
              >
                {opt.label}
              </button>
            );
          })}
        </div>

        <button
          type="button"
          onClick={() => void load()}
          className="min-h-9 px-3 rounded-lg border border-bunker-800 bg-bunker-900 text-bunker-muted hover:text-white font-mono text-xs font-bold transition-colors"
        >
          ↻ Yenile
        </button>
      </div>

      {error && (
        <div
          role="alert"
          className="px-3.5 py-2.5 rounded-xl border border-rose-500/40 bg-rose-500/10 text-rose-300 font-mono text-xs"
        >
          {error}
        </div>
      )}

      {/* 4 KPI KARTI */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <div className="rounded-xl border border-bunker-800 bg-bunker-950/60 p-3.5">
          <p className="text-2xs uppercase tracking-wider text-bunker-muted font-mono">
            Toplam Karar / Olay
          </p>
          <p className="mt-1 text-2xl font-black font-mono tabular-nums text-white">
            {parsedEvents.length}
          </p>
          <p className="mt-0.5 text-2xs text-bunker-muted font-mono">
            Son {days} gün kaydı
          </p>
        </div>

        <div className="rounded-xl border border-bunker-800 bg-bunker-950/60 p-3.5">
          <p className="text-2xs uppercase tracking-wider text-bunker-muted font-mono">
            Uygulanan Komut
          </p>
          <p className="mt-1 text-2xl font-black font-mono tabular-nums text-emerald-400">
            {appliedCount}
          </p>
          <p className="mt-0.5 text-2xs text-bunker-muted font-mono tabular-nums">
            {parsedEvents.length > 0
              ? `%${((appliedCount / parsedEvents.length) * 100).toFixed(0)} uygulama oranı`
              : "—"}
          </p>
        </div>

        <div className="rounded-xl border border-bunker-800 bg-bunker-950/60 p-3.5">
          <p className="text-2xs uppercase tracking-wider text-bunker-muted font-mono">
            AI Önerisi
          </p>
          <p className="mt-1 text-2xl font-black font-mono tabular-nums text-amber-300">
            {proposedCount}
          </p>
          <p className="mt-0.5 text-2xs text-bunker-muted font-mono">
            Gölge / salt öneri kaydı
          </p>
        </div>

        <div className="rounded-xl border border-bunker-800 bg-bunker-950/60 p-3.5">
          <p className="text-2xs uppercase tracking-wider text-bunker-muted font-mono">
            Kazanan Medyan MAE / MFE
          </p>
          <p className="mt-1 text-lg sm:text-xl font-black font-mono tabular-nums text-cyan-300">
            {fmtPip(stats?.winner_mae_median_pips)} / {fmtPip(stats?.loser_mfe_median_pips)}
          </p>
          <p className="mt-0.5 text-2xs text-bunker-muted font-mono truncate" title={stats?.hint || undefined}>
            {stats?.n_closed != null
              ? `${stats.n_closed} kapalı işlem${stats.edge_ratio != null ? ` · Edge ${stats.edge_ratio}` : ""}`
              : "Örneklem toplanıyor"}
          </p>
        </div>
      </div>

      {/* DOKTOR KARNESİ (KALİBRASYON & EPİZODİK HAFIZA) */}
      <section
        aria-label="Doktor Karnesi"
        className="rounded-2xl border border-bunker-800 bg-bunker-900/75 p-4 shadow-lg space-y-4"
      >
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="min-w-0">
            <h3 className="font-mono text-xs sm:text-sm font-bold text-white uppercase tracking-wider">
              🩺 Doktor Karnesi (Kalibrasyon &amp; Epizodik Hafıza)
            </h3>
            <p className="mt-0.5 text-2xs font-mono text-bunker-muted">
              Kapanan pozisyonlar üzerinden yapay zeka müdahalelerinin gerçek piyasa etkisi ve öğrenilen dersler
            </p>
          </div>
          {scorecard && scorecard.toplam_degerlendirilen > 0 && (
            <span className="font-mono text-2xs px-2 py-0.5 rounded-md border bg-cyan-500/15 border-cyan-500/35 text-cyan-300 font-bold tabular-nums shrink-0">
              {scorecard.toplam_degerlendirilen} yansıma
            </span>
          )}
        </div>

        {/* 4 Stat Kartı */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          <div className="min-w-0 rounded-xl border border-bunker-800 bg-bunker-950/60 p-3.5">
            <p className="text-2xs uppercase tracking-wider text-bunker-muted font-mono">
              Değerlendirilen İşlem
            </p>
            <p className="mt-1 text-2xl font-black font-mono tabular-nums text-white">
              {scorecard?.toplam_degerlendirilen ?? 0}
            </p>
            <p className="mt-0.5 text-2xs text-bunker-muted font-mono">
              Kapanmış yansıma sayısı
            </p>
          </div>

          <div className="min-w-0 rounded-xl border border-bunker-800 bg-bunker-950/60 p-3.5">
            <p className="text-2xs uppercase tracking-wider text-bunker-muted font-mono">
              İsabet Oranı
            </p>
            <p
              className={`mt-1 text-2xl font-black font-mono tabular-nums ${
                scorecard?.isabet_orani_pct == null
                  ? "text-bunker-muted"
                  : scorecard.isabet_orani_pct >= 60
                    ? "text-emerald-400"
                    : scorecard.isabet_orani_pct >= 40
                      ? "text-amber-300"
                      : "text-rose-400"
              }`}
            >
              {scorecard?.isabet_orani_pct != null
                ? `%${scorecard.isabet_orani_pct.toFixed(1)}`
                : "—"}
            </p>
            <p className="mt-0.5 text-2xs text-bunker-muted font-mono">
              Faydalı müdahale başarısı
            </p>
          </div>

          <div className="min-w-0 rounded-xl border border-bunker-800 bg-bunker-950/60 p-3.5">
            <p className="text-2xs uppercase tracking-wider text-bunker-muted font-mono">
              Net Etki
            </p>
            <p
              className={`mt-1 text-2xl font-black font-mono tabular-nums ${
                scorecard == null || scorecard.toplam_degerlendirilen === 0
                  ? "text-bunker-muted"
                  : scorecard.net_etki_usd >= 0
                    ? "text-emerald-400"
                    : "text-rose-400"
              }`}
            >
              {scorecard && scorecard.toplam_degerlendirilen > 0
                ? fmtUsd(scorecard.net_etki_usd)
                : "—"}
            </p>
            <p className="mt-0.5 text-2xs text-bunker-muted font-mono">
              Korunan / kaçırılan toplam $
            </p>
          </div>

          <div className="min-w-0 rounded-xl border border-bunker-800 bg-bunker-950/60 p-3.5">
            <p className="text-2xs uppercase tracking-wider text-bunker-muted font-mono">
              Faydalı / Erken Çıkış
            </p>
            <p className="mt-1 text-2xl font-black font-mono tabular-nums">
              <span className="text-emerald-400">{scorecard?.faydali_sayisi ?? 0}</span>
              <span className="text-bunker-muted mx-1">/</span>
              <span className="text-amber-300">{scorecard?.erken_cikis_sayisi ?? 0}</span>
            </p>
            <p className="mt-0.5 text-2xs text-bunker-muted font-mono tabular-nums">
              Nötr: {scorecard?.notr_sayisi ?? 0}
            </p>
          </div>
        </div>

        {/* Son Öğrenilen Dersler (Epizodik Hafıza) */}
        <div className="space-y-2.5 pt-1 border-t border-bunker-800/80">
          <div className="flex items-center justify-between gap-2">
            <h4 className="font-mono text-2xs font-bold uppercase tracking-wider text-slate-300">
              Son Öğrenilen Dersler (Epizodik Hafıza)
            </h4>
            {scorecard && Array.isArray(scorecard.son_dersler) && scorecard.son_dersler.length > 0 && (
              <span className="font-mono text-2xs text-bunker-muted tabular-nums">
                {scorecard.son_dersler.length} kayıt
              </span>
            )}
          </div>

          {!scorecard || !Array.isArray(scorecard.son_dersler) || scorecard.son_dersler.length === 0 ? (
            <div className="py-5 px-3.5 rounded-xl border border-dashed border-bunker-700 bg-bunker-950/40 text-center font-mono text-xs text-bunker-muted">
              Henüz kapanmış pozisyon yansıması oluşmadı; pozisyonlar kapandıkça otomatik dersler burada birikir.
            </div>
          ) : (
            <div className="space-y-2 max-h-80 overflow-y-auto">
              {scorecard.son_dersler.map((item, idx) => {
                const verdict = getVerdictBadge(item.verdict);
                const impact =
                  typeof item.saved_or_missed_usd === "number" &&
                  Number.isFinite(item.saved_or_missed_usd)
                    ? item.saved_or_missed_usd
                    : null;
                const actionBadge = item.action_taken ? classifyAction(item.action_taken) : null;
                const dirUp = String(item.direction || "").toUpperCase();

                return (
                  <div
                    key={`${item.ticket ?? item.symbol ?? "lesson"}-${item.created_at ?? idx}-${idx}`}
                    className="p-3 rounded-xl border border-bunker-800 bg-bunker-950/60 font-mono space-y-1.5"
                  >
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div className="flex flex-wrap items-center gap-1.5 min-w-0">
                        <span className="font-bold text-xs text-white">
                          {item.symbol || "—"}
                        </span>
                        {item.ticket != null && (
                          <span className="text-2xs text-bunker-muted tabular-nums">
                            #{item.ticket}
                          </span>
                        )}
                        {(dirUp === "BUY" || dirUp === "SELL") && (
                          <span
                            className={`px-1.5 py-0.5 rounded border text-2xs font-bold ${
                              dirUp === "BUY"
                                ? "bg-emerald-500/15 border-emerald-500/40 text-emerald-300"
                                : "bg-rose-500/15 border-rose-500/40 text-rose-300"
                            }`}
                          >
                            {dirUp}
                          </span>
                        )}
                        {item.session && (
                          <span className="px-1.5 py-0.5 rounded border border-bunker-700 bg-bunker-900 text-2xs text-cyan-300">
                            {formatSessionLabel(item.session)}
                          </span>
                        )}
                        {actionBadge && (
                          <span
                            className={`px-1.5 py-0.5 rounded border text-2xs font-bold ${actionBadge.cls}`}
                          >
                            {actionBadge.label}
                          </span>
                        )}
                      </div>

                      <div className="flex items-center gap-2 shrink-0">
                        <span
                          className={`px-2 py-0.5 rounded border text-2xs font-bold ${verdict.cls}`}
                        >
                          {verdict.label}
                        </span>
                        <span
                          className={`text-xs font-bold tabular-nums ${
                            impact == null
                              ? "text-bunker-muted"
                              : impact >= 0
                                ? "text-emerald-400"
                                : "text-rose-400"
                          }`}
                        >
                          {fmtUsd(impact)}
                        </span>
                      </div>
                    </div>

                    <p className="text-2xs text-slate-200 leading-relaxed break-words">
                      {item.lesson || "—"}
                    </p>

                    {item.created_at != null && (
                      <div className="text-2xs text-bunker-muted tabular-nums pt-0.5 border-t border-bunker-800/60">
                        {formatUtc3(item.created_at)}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </section>

      {/* EYLEM DAĞILIMI PİLLERİ + FİLTRE ÇUBUĞU */}
      <div className="p-4 rounded-2xl border border-bunker-800 bg-bunker-900/70 space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-2xs text-bunker-muted font-mono uppercase tracking-wider font-bold mr-1">
            Eylem Dağılımı:
          </span>
          <button
            type="button"
            onClick={() => setActionFilter("ALL")}
            className={`px-2.5 py-1 rounded-lg border font-mono text-2xs font-bold transition-colors tabular-nums ${
              actionFilter === "ALL"
                ? "bg-blue-500/20 border-blue-400/60 text-blue-200"
                : "bg-bunker-950 border-bunker-800 text-bunker-muted hover:text-white"
            }`}
          >
            Tümü ({parsedEvents.length})
          </button>
          {ACTION_PILLS.map((pill) => {
            const active = actionFilter === pill.key;
            const count = breakdownCounts[pill.key as Exclude<ActionCategory, "ALL">];
            return (
              <button
                key={pill.key}
                type="button"
                onClick={() => setActionFilter(active ? "ALL" : pill.key)}
                className={`px-2.5 py-1 rounded-lg border font-mono text-2xs font-bold transition-all tabular-nums ${
                  active ? `${pill.cls} ring-1 ring-white/40` : `${pill.cls} opacity-80 hover:opacity-100`
                }`}
              >
                {pill.label}: {count}
              </button>
            );
          })}
        </div>

        <div className="flex flex-col sm:flex-row sm:items-center gap-2.5 pt-2 border-t border-bunker-800/80">
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Sembol, bilet no veya gerekçe ara…"
            className="min-h-9 flex-1 bg-bunker-950 border border-bunker-700 rounded-lg px-3 py-1.5 font-mono text-xs text-white placeholder-bunker-600 outline-none focus:border-cyan-400"
          />
          <div className="inline-flex items-center p-0.5 rounded-lg bg-bunker-950 border border-bunker-800">
            {(
              [
                ["ALL", "Tümü"],
                ["APPLIED", "Uygulandı"],
                ["PROPOSED", "Öneri"],
              ] as const
            ).map(([k, lbl]) => (
              <button
                key={k}
                type="button"
                onClick={() => setModeFilter(k)}
                className={`min-h-8 px-2.5 rounded-md font-mono text-2xs font-bold transition-colors ${
                  modeFilter === k
                    ? "bg-blue-500/20 text-blue-200 border border-blue-400/50"
                    : "text-bunker-muted hover:text-white border border-transparent"
                }`}
              >
                {lbl}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* GEÇMİŞ KARARLAR TABLOSU */}
      <div className="rounded-2xl border border-bunker-800 bg-bunker-900/75 overflow-hidden shadow-lg">
        <div className="px-4 py-3 border-b border-bunker-800 flex items-center justify-between gap-2">
          <h3 className="font-mono text-xs font-bold text-white uppercase tracking-wider">
            Pozisyon Doktoru Karar Geçmişi
          </h3>
          <span className="font-mono text-2xs text-bunker-muted tabular-nums">
            {filteredEvents.length} / {parsedEvents.length} kayıt
          </span>
        </div>

        {loading && parsedEvents.length === 0 ? (
          <div className="p-8 text-center font-mono text-xs text-bunker-muted">
            Kayıtlar yükleniyor…
          </div>
        ) : filteredEvents.length === 0 ? (
          <div className="p-8 text-center font-mono text-xs text-bunker-muted">
            Seçilen dönem ve filtrelerde Pozisyon Doktoru kaydı bulunamadı.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse font-mono text-xs">
              <thead>
                <tr className="border-b border-bunker-800 bg-bunker-950/60 text-2xs text-bunker-muted uppercase">
                  <th className="py-2.5 px-3 whitespace-nowrap">Zaman (UTC+3)</th>
                  <th className="py-2.5 px-3 whitespace-nowrap">Sembol &amp; Bilet</th>
                  <th className="py-2.5 px-3 whitespace-nowrap">Eylem</th>
                  <th className="py-2.5 px-3 whitespace-nowrap">Mod</th>
                  <th className="py-2.5 px-3">Gerekçe</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-bunker-800/70">
                {filteredEvents.map((ev, idx) => (
                  <tr
                    key={`${ev.raw.id ?? ev.raw.ticket ?? idx}-${idx}`}
                    className="hover:bg-bunker-800/30 transition-colors"
                  >
                    <td className="py-2.5 px-3 whitespace-nowrap text-2xs text-slate-300 tabular-nums">
                      {formatUtc3(ev.raw.ts)}
                    </td>
                    <td className="py-2.5 px-3 whitespace-nowrap">
                      <span className="font-bold text-white">{ev.raw.symbol || "—"}</span>
                      {ev.raw.ticket != null && (
                        <span className="ml-1.5 text-2xs text-bunker-muted tabular-nums">
                          #{ev.raw.ticket}
                        </span>
                      )}
                    </td>
                    <td className="py-2.5 px-3 whitespace-nowrap">
                      <span
                        className={`inline-flex px-2 py-0.5 rounded border text-2xs font-bold ${ev.badgeCls}`}
                      >
                        {ev.badgeLabel}
                      </span>
                    </td>
                    <td className="py-2.5 px-3 whitespace-nowrap">
                      <span
                        className={`inline-flex px-2 py-0.5 rounded border text-2xs font-bold ${
                          ev.applied
                            ? "bg-emerald-500/15 border-emerald-500/40 text-emerald-300"
                            : "bg-amber-500/15 border-amber-500/40 text-amber-300"
                        }`}
                      >
                        {ev.applied ? "Uygulandı" : "Öneri"}
                      </span>
                    </td>
                    <td className="py-2.5 px-3 text-2xs text-slate-300 leading-snug max-w-xl break-words">
                      {ev.reason}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
