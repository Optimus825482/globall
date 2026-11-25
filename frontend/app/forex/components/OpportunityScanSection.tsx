"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import { apiFetch } from "../../lib/api";
import { usePolling } from "../../lib/usePolling";
import { formatPrice, formatUtc3, toMs } from "../../lib/format";

export interface OpportunityCandidateItem {
  symbol: string;
  display?: string;
  name?: string;
  direction?: string;
  bias?: string;
  summary?: string;
  tv_summary?: string;
  agreement?: number;
  score?: number;
  own_score?: number;
  tv_avg?: number;
  price?: number;
}

export interface OpportunityOpenedItem {
  symbol: string;
  display?: string;
  direction: string;
  lots?: number;
  sl_pips?: number;
  tp_pips?: number;
  risk_usd?: number;
  entry_price?: number;
  cmd_id?: string;
  note?: string;
}

export interface OpportunitySkippedItem {
  symbol: string;
  display?: string;
  reason: string;
}

export interface OpportunityScanSummary {
  enabled: boolean;
  running: boolean;
  intervalMin: number;
  lastRunAt: string | number | null;
  nextRunAt: string | number | null;
  openedCount: number;
  candidatesCount: number;
}

interface OpportunityScanPayload {
  enabled?: boolean;
  running?: boolean;
  interval_minutes?: number;
  interval_min?: number;
  last_run_at?: string | number | null;
  last_run_ts?: number | null;
  scanned_at?: string | number | null;
  next_run_at?: string | number | null;
  next_run_ts?: number | null;
  next_run_in_sec?: number | null;
  weekend?: boolean;
  universe_count?: number;
  candidates?: OpportunityCandidateItem[];
  top_candidates?: OpportunityCandidateItem[];
  scan?: {
    top?: OpportunityCandidateItem[];
    all?: OpportunityCandidateItem[];
  };
  opened?: OpportunityOpenedItem[];
  last_opened?: OpportunityOpenedItem[];
  skipped?: OpportunitySkippedItem[];
  rejected?: OpportunitySkippedItem[];
  last_skipped?: OpportunitySkippedItem[];
  result?: {
    opened?: OpportunityOpenedItem[];
    skipped?: OpportunitySkippedItem[];
  };
  summary_text?: string;
  message?: string;
  error?: string | null;
}

interface OpportunityScanSectionProps {
  onSummaryChange?: (summary: OpportunityScanSummary) => void;
  onOpenChart?: (symbol: string) => void;
}

const INTERVAL_OPTIONS = [5, 10, 15, 30] as const;

function normalizeDirection(raw?: string): "BUY" | "SELL" | "NEUTRAL" {
  const s = String(raw || "").toUpperCase();
  if (s.includes("BUY") || s.includes("LONG") || s.includes("AL")) return "BUY";
  if (s.includes("SELL") || s.includes("SHORT") || s.includes("SAT")) return "SELL";
  return "NEUTRAL";
}

function fmtAgreement(val?: number): string {
  if (typeof val !== "number" || !Number.isFinite(val)) return "—";
  const pct = val <= 1 ? val * 100 : val;
  return `%${Math.round(pct)}`;
}

function fmtCountdown(remainingSec: number): string {
  if (!Number.isFinite(remainingSec) || remainingSec <= 0) return "Şimdi";
  const mins = Math.floor(remainingSec / 60);
  const secs = Math.floor(remainingSec % 60);
  return `${String(mins).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
}

export default function OpportunityScanSection({
  onSummaryChange,
  onOpenChart,
}: OpportunityScanSectionProps) {
  const [data, setData] = useState<OpportunityScanPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>("");
  const [toggling, setToggling] = useState(false);
  const [runningManual, setRunningManual] = useState(false);
  const [notice, setNotice] = useState<{ ok: boolean; text: string } | null>(null);
  const [nowMs, setNowMs] = useState<number>(() => Date.now());

  const enabled = Boolean(data?.enabled);
  const isBackendRunning = Boolean(data?.running);
  const intervalMin = useMemo(() => {
    const raw = data?.interval_minutes ?? data?.interval_min;
    return typeof raw === "number" && Number.isFinite(raw) && raw > 0 ? raw : 10;
  }, [data]);

  const lastRunAt = data?.last_run_at ?? data?.last_run_ts ?? data?.scanned_at ?? null;
  const nextRunAt = data?.next_run_at ?? data?.next_run_ts ?? null;

  const candidates = useMemo<OpportunityCandidateItem[]>(() => {
    if (Array.isArray(data?.candidates) && data.candidates.length > 0) return data.candidates;
    if (Array.isArray(data?.top_candidates) && data.top_candidates.length > 0) return data.top_candidates;
    if (Array.isArray(data?.scan?.top) && data.scan.top.length > 0) return data.scan.top;
    if (Array.isArray(data?.scan?.all) && data.scan.all.length > 0) return data.scan.all.slice(0, 8);
    return [];
  }, [data]);

  const opened = useMemo<OpportunityOpenedItem[]>(() => {
    if (Array.isArray(data?.opened)) return data.opened;
    if (Array.isArray(data?.result?.opened)) return data.result.opened;
    if (Array.isArray(data?.last_opened)) return data.last_opened;
    return [];
  }, [data]);

  const skipped = useMemo<OpportunitySkippedItem[]>(() => {
    if (Array.isArray(data?.skipped)) return data.skipped;
    if (Array.isArray(data?.rejected)) return data.rejected;
    if (Array.isArray(data?.result?.skipped)) return data.result.skipped;
    if (Array.isArray(data?.last_skipped)) return data.last_skipped;
    return [];
  }, [data]);

  const fetchLatest = useCallback(async () => {
    try {
      const res = (await apiFetch("/api/forex/opportunity-scan/latest")) as OpportunityScanPayload;
      if (res && typeof res === "object") {
        setData(res);
        setError("");
      }
    } catch (err) {
      const detail = err instanceof Error ? err.message : "Fırsat taraması verisi alınamadı";
      setError(`Fırsat taraması durumu alınamadı: ${detail}`);
    } finally {
      setLoading(false);
    }
  }, []);

  usePolling(fetchLatest, 10_000);

  // Sync summary up to parent KPI strip and tab badge
  useEffect(() => {
    if (!onSummaryChange) return;
    onSummaryChange({
      enabled,
      running: isBackendRunning || runningManual,
      intervalMin,
      lastRunAt,
      nextRunAt,
      openedCount: opened.length,
      candidatesCount: candidates.length,
    });
  }, [
    onSummaryChange,
    enabled,
    isBackendRunning,
    runningManual,
    intervalMin,
    lastRunAt,
    nextRunAt,
    opened.length,
    candidates.length,
  ]);

  // Countdown tick only when auto-scan is enabled
  usePolling(() => setNowMs(Date.now()), enabled ? 1000 : null, { runOnVisible: true });

  const remainingSec = useMemo(() => {
    if (!enabled) return null;
    if (nextRunAt) {
      const targetMs =
        typeof nextRunAt === "number" ? toMs(nextRunAt) : Date.parse(String(nextRunAt));
      if (Number.isFinite(targetMs) && targetMs > 0) {
        return Math.max(0, Math.round((targetMs - nowMs) / 1000));
      }
    }
    if (typeof data?.next_run_in_sec === "number" && Number.isFinite(data.next_run_in_sec)) {
      return Math.max(0, data.next_run_in_sec);
    }
    return null;
  }, [enabled, nextRunAt, data?.next_run_in_sec, nowMs]);

  const handleToggle = async (nextEnabled: boolean, nextInterval: number) => {
    setToggling(true);
    setNotice(null);
    try {
      const res = (await apiFetch("/api/forex/opportunity-scan/toggle", {
        method: "POST",
        body: JSON.stringify({
          enabled: nextEnabled,
          interval_min: nextInterval,
        }),
      })) as OpportunityScanPayload;
      if (res && typeof res === "object") {
        setData((prev) => ({ ...prev, ...res, enabled: res.enabled ?? nextEnabled, interval_minutes: res.interval_minutes ?? res.interval_min ?? nextInterval }));
      }
      setNotice({
        ok: true,
        text: nextEnabled
          ? `Periyodik fırsat taraması açıldı (${nextInterval} dk aralıkla).`
          : "Periyodik fırsat taraması duraklatıldı.",
      });
      setError("");
    } catch (err) {
      const detail = err instanceof Error ? err.message : "Ayar güncellenemedi";
      setNotice({ ok: false, text: `Güncelleme başarısız: ${detail}` });
    } finally {
      setToggling(false);
    }
  };

  const handleManualRun = async () => {
    setRunningManual(true);
    setNotice(null);
    try {
      const res = (await apiFetch("/api/forex/opportunity-scan/run", {
        method: "POST",
      })) as OpportunityScanPayload;
      if (res && typeof res === "object") {
        setData((prev) => ({ ...prev, ...res }));
      }
      await fetchLatest();
      setNotice({
        ok: true,
        text: "Manuel fırsat taraması tamamlandı.",
      });
    } catch (err) {
      const detail = err instanceof Error ? err.message : "Tarama başlatılamadı";
      setNotice({ ok: false, text: `Tarama başarısız: ${detail}` });
    } finally {
      setRunningManual(false);
    }
  };

  const busy = runningManual || isBackendRunning;

  return (
    <section aria-label="Periyodik Fırsat Taraması" className="space-y-4">
      {/* ÜST KONTROL ÇUBUĞU */}
      <div className="p-4 rounded-2xl border border-bunker-800 bg-bunker-900/75 shadow-lg space-y-3">
        <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-2.5 min-w-0">
            <span
              className={`w-2.5 h-2.5 rounded-full shrink-0 ${
                busy
                  ? "bg-cyan-400 animate-ping"
                  : enabled
                    ? "bg-emerald-400"
                    : "bg-bunker-600"
              }`}
              aria-hidden="true"
            />
            <div className="min-w-0">
              <h2 className="font-mono text-sm font-bold text-white tracking-tight">
                Otonom Fırsat Taraması ({intervalMin} dk)
              </h2>
              <p className="font-mono text-2xs text-bunker-muted">
                TradingView + 8 dilimli derin analiz + çok katmanlı risk/haber kapıları (DEMO)
                {data?.weekend ? " · Hafta Sonu Kripto Modu" : ""}
              </p>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            {/* Aç/Kapat Düğmesi */}
            <button
              type="button"
              disabled={toggling}
              aria-pressed={enabled}
              onClick={() => void handleToggle(!enabled, intervalMin)}
              className={`min-h-10 px-3.5 rounded-lg border font-mono text-xs font-bold transition-colors flex items-center gap-2 disabled:opacity-50 ${
                enabled
                  ? "bg-emerald-500/20 border-emerald-400/50 text-emerald-300 hover:bg-emerald-500/30"
                  : "bg-bunker-800/90 border-bunker-700 text-bunker-muted hover:text-white hover:border-bunker-600"
              }`}
            >
              <span
                className={`w-2 h-2 rounded-full ${enabled ? "bg-emerald-400" : "bg-bunker-600"}`}
                aria-hidden="true"
              />
              {enabled ? "Oto-Tarama AÇIK" : "Oto-Tarama KAPALI"}
            </button>

            {/* Aralık Seçici */}
            <label className="inline-flex items-center gap-1.5 font-mono text-2xs text-bunker-muted">
              <span className="sr-only">Tarama aralığı</span>
              <select
                value={intervalMin}
                disabled={toggling}
                onChange={(e) => {
                  const next = Number(e.target.value) || 10;
                  void handleToggle(enabled, next);
                }}
                aria-label="Tarama aralığı"
                className="min-h-10 bg-bunker-950 border border-bunker-700 rounded-lg px-2.5 py-1.5 font-mono text-xs text-white focus:border-cyan-400 outline-none"
              >
                {INTERVAL_OPTIONS.map((m) => (
                  <option key={m} value={m}>
                    {m} dk
                  </option>
                ))}
              </select>
            </label>

            {/* Şimdi Tara */}
            <button
              type="button"
              disabled={busy}
              onClick={() => void handleManualRun()}
              className="min-h-10 px-4 rounded-lg font-mono text-xs font-bold bg-cyan-400 text-bunker-950 hover:bg-sky-400 disabled:bg-bunker-700 disabled:text-bunker-muted disabled:cursor-not-allowed transition-colors inline-flex items-center gap-2"
            >
              {busy ? (
                <>
                  <span className="inline-block w-3 h-3 border-2 border-bunker-950/40 border-t-bunker-950 rounded-full animate-spin" />
                  Taranıyor…
                </>
              ) : (
                "Şimdi Tara"
              )}
            </button>
          </div>
        </div>

        {/* Zamanlama Meta Şeridi */}
        <div className="flex flex-wrap items-center justify-between gap-2 pt-2.5 border-t border-bunker-800/70 font-mono text-2xs text-bunker-muted tabular-nums">
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
            <span>
              Son Tarama:{" "}
              <strong className="text-white">
                {lastRunAt ? formatUtc3(lastRunAt) : "Henüz çalıştırılmadı"}
              </strong>
            </span>
            <span>
              Sonraki Tur:{" "}
              <strong className={enabled ? "text-cyan-300" : "text-bunker-muted"}>
                {enabled
                  ? remainingSec != null
                    ? fmtCountdown(remainingSec)
                    : `${intervalMin} dk içinde`
                  : "Duraklatıldı"}
              </strong>
            </span>
            {typeof data?.universe_count === "number" && data.universe_count > 0 && (
              <span>
                Evren: <strong className="text-white">{data.universe_count} sembol</strong>
              </span>
            )}
          </div>
          <div className="flex items-center gap-3">
            <span>
              Aday: <strong className="text-white">{candidates.length}</strong>
            </span>
            <span>
              Açılan: <strong className="text-emerald-400">{opened.length}</strong>
            </span>
            <span>
              Elenen: <strong className="text-amber-300">{skipped.length}</strong>
            </span>
          </div>
        </div>
      </div>

      {notice && (
        <p
          role="status"
          className={`px-4 py-2.5 rounded-xl border font-mono text-xs ${
            notice.ok
              ? "bg-emerald-500/10 border-emerald-500/40 text-emerald-300"
              : "bg-rose-500/10 border-rose-500/40 text-rose-300"
          }`}
        >
          {notice.text}
        </p>
      )}

      {error && (
        <div
          role="alert"
          className="px-4 py-3 rounded-xl border border-rose-500/40 bg-rose-500/10 text-rose-300 font-mono text-xs flex flex-wrap items-center justify-between gap-2"
        >
          <span>{error}</span>
          <button
            type="button"
            onClick={() => void fetchLatest()}
            className="px-3 py-1 rounded-lg bg-rose-500/20 border border-rose-400/40 font-bold hover:bg-rose-500/30"
          >
            Tekrar Dene
          </button>
        </div>
      )}

      {loading && !data ? (
        <div className="p-10 rounded-2xl border border-bunker-800 bg-bunker-900/60 text-center font-mono text-xs text-bunker-muted">
          <div className="inline-block w-5 h-5 border-2 border-cyan-400 border-t-transparent rounded-full animate-spin mb-2" />
          <p>Fırsat taraması durumu yükleniyor…</p>
        </div>
      ) : (
        /* 3 TEMİZ KART / LİSTE */
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          {/* 1. EN NET YÖNLÜ ADAYLAR */}
          <div className="rounded-2xl border border-bunker-800 bg-bunker-900/70 overflow-hidden flex flex-col">
            <div className="px-4 py-3 border-b border-bunker-800 flex items-center justify-between gap-2">
              <h3 className="font-mono text-xs font-bold text-white uppercase tracking-wider">
                En Net Yönlü Adaylar
              </h3>
              <span className="font-mono text-2xs px-2 py-0.5 rounded-md bg-cyan-500/15 border border-cyan-500/30 text-cyan-300 font-bold tabular-nums">
                {candidates.length}
              </span>
            </div>

            <div className="p-3 space-y-2 flex-1">
              {candidates.length === 0 ? (
                <p className="py-8 text-center font-mono text-xs text-bunker-muted">
                  Henüz yönlü aday listesi yok. &ldquo;Şimdi Tara&rdquo; ile tarama başlatabilirsiniz.
                </p>
              ) : (
                candidates.map((c, idx) => {
                  const dir = normalizeDirection(c.direction || c.bias || c.summary || c.tv_summary);
                  const tvText = c.tv_summary || c.summary || "—";
                  const scoreVal = typeof c.own_score === "number" ? c.own_score : c.score;
                  return (
                    <div
                      key={`${c.symbol}-${idx}`}
                      className="p-3 rounded-xl border border-bunker-800 bg-bunker-950/60 hover:border-bunker-700 transition-colors font-mono space-y-1.5"
                    >
                      <div className="flex items-center justify-between gap-2">
                        <div className="flex items-center gap-2 min-w-0">
                          <span className="font-bold text-sm text-white truncate">
                            {c.display || c.symbol}
                          </span>
                          <span
                            className={`px-2 py-0.5 rounded text-2xs font-bold border ${
                              dir === "BUY"
                                ? "bg-emerald-500/15 text-emerald-300 border-emerald-500/40"
                                : dir === "SELL"
                                  ? "bg-rose-500/15 text-rose-300 border-rose-500/40"
                                  : "bg-bunker-800 text-bunker-muted border-bunker-700"
                            }`}
                          >
                            {dir === "BUY" ? "▲ BUY" : dir === "SELL" ? "▼ SELL" : "NÖTR"}
                          </span>
                        </div>
                        {onOpenChart && (
                          <button
                            type="button"
                            onClick={() => onOpenChart(c.symbol)}
                            className="px-2 py-1 rounded-md bg-blue-500/10 border border-blue-400/25 text-blue-300 hover:bg-blue-500/25 hover:text-white text-2xs font-bold transition-colors"
                          >
                            Grafik
                          </button>
                        )}
                      </div>

                      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 text-2xs text-bunker-muted tabular-nums">
                        <span>
                          TV: <strong className="text-white">{tvText}</strong>
                        </span>
                        <span>
                          Uyum: <strong className="text-cyan-300">{fmtAgreement(c.agreement)}</strong>
                        </span>
                        <span>
                          Skor:{" "}
                          <strong className="text-white">
                            {typeof scoreVal === "number" && Number.isFinite(scoreVal)
                              ? scoreVal.toFixed(1)
                              : "—"}
                          </strong>
                        </span>
                        {typeof c.price === "number" && Number.isFinite(c.price) && (
                          <span className="text-white">{formatPrice(c.price)}</span>
                        )}
                      </div>
                    </div>
                  );
                })
              )}
            </div>
          </div>

          {/* 2. SON TURDA AÇILAN İŞLEMLER */}
          <div className="rounded-2xl border border-bunker-800 bg-bunker-900/70 overflow-hidden flex flex-col">
            <div className="px-4 py-3 border-b border-bunker-800 flex items-center justify-between gap-2">
              <h3 className="font-mono text-xs font-bold text-white uppercase tracking-wider">
                Son Turda Açılan İşlemler
              </h3>
              <span className="font-mono text-2xs px-2 py-0.5 rounded-md bg-emerald-500/15 border border-emerald-500/30 text-emerald-300 font-bold tabular-nums">
                {opened.length}
              </span>
            </div>

            <div className="p-3 space-y-2 flex-1">
              {opened.length === 0 ? (
                <p className="py-8 text-center font-mono text-xs text-bunker-muted">
                  Son turda tüm kapılardan geçen yeni işlem açılmadı.
                </p>
              ) : (
                opened.map((o, idx) => {
                  const isBuy = normalizeDirection(o.direction) === "BUY";
                  return (
                    <div
                      key={`${o.symbol}-${o.cmd_id || idx}`}
                      className={`p-3 rounded-xl border font-mono space-y-1.5 ${
                        isBuy
                          ? "bg-emerald-950/20 border-emerald-500/35"
                          : "bg-rose-950/20 border-rose-500/35"
                      }`}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <div className="flex items-center gap-2">
                          <span className="font-bold text-sm text-white">
                            {o.display || o.symbol}
                          </span>
                          <span
                            className={`px-2 py-0.5 rounded text-2xs font-bold border ${
                              isBuy
                                ? "bg-emerald-500/20 text-emerald-300 border-emerald-400/50"
                                : "bg-rose-500/20 text-rose-300 border-rose-400/50"
                            }`}
                          >
                            {isBuy ? "▲ BUY" : "▼ SELL"}
                          </span>
                        </div>
                        <span className="text-xs font-bold text-cyan-300 tabular-nums">
                          {typeof o.lots === "number" ? `${o.lots} lot` : "—"}
                        </span>
                      </div>

                      <div className="grid grid-cols-3 gap-2 text-2xs tabular-nums p-2 rounded-lg bg-bunker-950/70 border border-bunker-800/70">
                        <div>
                          <span className="text-bunker-muted block">STOP (SL)</span>
                          <span className="text-rose-400 font-bold">
                            {typeof o.sl_pips === "number" ? `-${o.sl_pips.toFixed(0)}p` : "—"}
                          </span>
                        </div>
                        <div>
                          <span className="text-bunker-muted block">HEDEF (TP)</span>
                          <span className="text-emerald-400 font-bold">
                            {typeof o.tp_pips === "number" ? `+${o.tp_pips.toFixed(0)}p` : "—"}
                          </span>
                        </div>
                        <div>
                          <span className="text-bunker-muted block">RİSK</span>
                          <span className="text-white font-bold">
                            {typeof o.risk_usd === "number" ? `$${o.risk_usd.toFixed(2)}` : "—"}
                          </span>
                        </div>
                      </div>

                      {o.note && (
                        <p className="text-2xs text-bunker-muted leading-snug break-words">
                          {o.note}
                        </p>
                      )}
                    </div>
                  );
                })
              )}
            </div>
          </div>

          {/* 3. ELENEN ADAYLAR VE NEDENLERİ */}
          <div className="rounded-2xl border border-bunker-800 bg-bunker-900/70 overflow-hidden flex flex-col">
            <div className="px-4 py-3 border-b border-bunker-800 flex items-center justify-between gap-2">
              <h3 className="font-mono text-xs font-bold text-white uppercase tracking-wider">
                Elenen Adaylar ve Nedenleri
              </h3>
              <span className="font-mono text-2xs px-2 py-0.5 rounded-md bg-amber-500/15 border border-amber-500/30 text-amber-300 font-bold tabular-nums">
                {skipped.length}
              </span>
            </div>

            <div className="p-3 space-y-2 flex-1 max-h-[420px] overflow-y-auto">
              {skipped.length === 0 ? (
                <p className="py-8 text-center font-mono text-xs text-bunker-muted">
                  Son turda elenen aday kaydı yok.
                </p>
              ) : (
                skipped.map((s, idx) => (
                  <div
                    key={`${s.symbol}-${idx}`}
                    className="p-2.5 rounded-xl border border-amber-500/20 bg-amber-950/15 font-mono space-y-1"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-bold text-xs text-white">
                        {s.display || s.symbol}
                      </span>
                      <span className="text-2xs px-1.5 py-0.5 rounded bg-amber-500/15 text-amber-300 border border-amber-500/30 font-bold">
                        ELENDİ
                      </span>
                    </div>
                    <p className="text-2xs text-amber-200/90 leading-snug break-words">
                      {s.reason}
                    </p>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
