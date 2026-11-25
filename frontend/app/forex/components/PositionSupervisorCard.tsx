"use client";

import React, { useCallback, useMemo, useState } from "react";
import { apiFetch } from "../../lib/api";
import { usePolling } from "../../lib/usePolling";
import { formatUtc3 } from "../../lib/format";

type SupervisorMode = "off" | "log" | "act";

interface OpenFindingItem {
  ticket?: number | string;
  symbol?: string;
  kind?: string;
  detail?: string;
  message?: string;
  reason?: string;
  action?: string;
  severity?: string;
  ts?: number | string;
}

interface SupervisorActionItem {
  id?: string | number;
  ticket?: number | string;
  symbol?: string;
  action?: string;
  pct?: number | null;
  reason?: string;
  detail?: string;
  note?: string;
  message?: string;
  applied?: boolean;
  enforced?: boolean;
  status?: string;
  mode?: string;
  source?: string;
  ts?: number | string;
  time?: number | string;
}

interface SupervisorStatusResponse {
  mode?: SupervisorMode | string;
  llm_enabled?: boolean;
  open_positions_count?: number;
  open_findings?: OpenFindingItem[];
  recent_actions?: SupervisorActionItem[];
  last_review_at?: number | string | null;
  note?: string;
}

interface ReviewResponse {
  proposals?: SupervisorActionItem[];
  rejected?: SupervisorActionItem[];
  applied?: boolean;
  applied_count?: number;
  note?: string;
  message?: string;
  summary?: string;
}

const MODE_OPTIONS: Array<{ value: SupervisorMode; label: string }> = [
  { value: "off", label: "Kapalı" },
  { value: "log", label: "Gölge" },
  { value: "act", label: "Aktif" },
];

function normalizeMode(raw?: string): SupervisorMode {
  const s = String(raw || "").toLowerCase().trim();
  if (s === "act") return "act";
  if (s === "log") return "log";
  return "off";
}

function getModeBadge(mode: SupervisorMode): {
  label: string;
  badgeCls: string;
  dotCls: string;
} {
  if (mode === "act") {
    return {
      label: "Aktif (Otomatik Uygula)",
      badgeCls: "bg-emerald-500/20 text-emerald-300 border-emerald-400/50",
      dotCls: "bg-emerald-400",
    };
  }
  if (mode === "log") {
    return {
      label: "Gölge (Sadece Öner)",
      badgeCls: "bg-amber-500/20 text-amber-300 border-amber-400/50",
      dotCls: "bg-amber-400",
    };
  }
  return {
    label: "Kapalı",
    badgeCls: "bg-slate-500/20 text-slate-300 border-slate-500/40",
    dotCls: "bg-slate-400",
  };
}

function formatActionBadge(
  rawAction?: string,
  pct?: number | null,
): { label: string; cls: string } {
  const a = String(rawAction || "").toLowerCase().trim();
  if (
    a === "be" ||
    a === "breakeven" ||
    a === "move_sl_to_breakeven" ||
    a.includes("breakeven")
  ) {
    return {
      label: "BE",
      cls: "bg-cyan-500/15 text-cyan-300 border-cyan-500/40",
    };
  }
  if (
    a === "tighten_sl" ||
    a === "sl_tighten" ||
    a === "modify_sl" ||
    a === "modify_sltp" ||
    a === "tighten" ||
    a.includes("tighten")
  ) {
    return {
      label: "SL Sıkılaştır",
      cls: "bg-sky-500/15 text-sky-300 border-sky-500/40",
    };
  }
  if (
    a === "start_trailing" ||
    a === "trailing" ||
    a === "enable_trailing" ||
    a === "trail" ||
    a.includes("trail")
  ) {
    return {
      label: "Trailing Başlat",
      cls: "bg-purple-500/15 text-purple-300 border-purple-500/40",
    };
  }
  if (a === "partial_close" || a === "partial" || a.includes("partial")) {
    const suffix = typeof pct === "number" && Number.isFinite(pct) ? ` %${pct}` : "";
    return {
      label: `Kısmi Kapat${suffix}`,
      cls: "bg-amber-500/15 text-amber-300 border-amber-500/40",
    };
  }
  if (a === "close" || a === "close_order") {
    return {
      label: "Kapat",
      cls: "bg-rose-500/15 text-rose-300 border-rose-500/40",
    };
  }
  if (a === "hold" || a === "no_op" || a === "keep" || a === "tut") {
    return {
      label: "Tut",
      cls: "bg-bunker-800 text-bunker-muted border-bunker-700",
    };
  }
  return {
    label: rawAction ? String(rawAction) : "Öneri",
    cls: "bg-bunker-800 text-slate-300 border-bunker-700",
  };
}

function isActionApplied(item: SupervisorActionItem, fallbackApplied?: boolean): boolean {
  if (typeof item.applied === "boolean") return item.applied;
  if (typeof item.enforced === "boolean") return item.enforced;
  const st = String(item.status || "").toLowerCase();
  if (st === "applied" || st === "uygulandı" || st === "executed") return true;
  if (st === "proposed" || st === "öneri" || st === "shadow") return false;
  const rawAct = String(item.action || "").toLowerCase();
  if (rawAct.startsWith("komut:")) return true;
  if (typeof fallbackApplied === "boolean") return fallbackApplied;
  return false;
}

function formatFindingKind(kind?: string): string | null {
  const k = String(kind || "").toLowerCase();
  if (!k) return null;
  if (k.includes("event")) return "Haber Riski";
  if (k.includes("weekend")) return "Hafta Sonu";
  if (k.includes("no_sl")) return "Stop Yok";
  if (k.includes("atr")) return "Volatilite Sıçraması";
  if (k.includes("yapi") || k.includes("structure")) return "Yapı Kırılımı";
  if (k.includes("dxy")) return "DXY Çelişkisi";
  if (k.includes("ilerleme") || k.includes("stale")) return "Bayat İşlem";
  if (k.includes("invalidation")) return "Tez Bozulması";
  return kind || null;
}

export default function PositionSupervisorCard() {
  const [statusData, setStatusData] = useState<SupervisorStatusResponse | null>(null);
  const [manualProposals, setManualProposals] = useState<SupervisorActionItem[] | null>(null);
  const [manualAppliedFlag, setManualAppliedFlag] = useState<boolean>(false);
  const [manualNote, setManualNote] = useState<string>("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [toggling, setToggling] = useState(false);
  const [reviewingMode, setReviewingMode] = useState<null | "dry" | "apply">(null);
  const [notice, setNotice] = useState<{ ok: boolean; text: string } | null>(null);

  const fetchStatus = useCallback(async () => {
    try {
      const res = (await apiFetch(
        "/api/positions/supervisor-status",
      )) as SupervisorStatusResponse;
      if (res && typeof res === "object") {
        setStatusData(res);
        setError("");
      }
    } catch (err) {
      const detail = err instanceof Error ? err.message : "Durum alınamadı";
      setError(`Pozisyon Doktoru durumu alınamadı: ${detail}`);
    } finally {
      setLoading(false);
    }
  }, []);

  usePolling(fetchStatus, 15_000);

  const mode = normalizeMode(statusData?.mode);
  const llmEnabled = Boolean(statusData?.llm_enabled);
  const badge = getModeBadge(mode);

  const openFindings = useMemo<OpenFindingItem[]>(
    () => (Array.isArray(statusData?.open_findings) ? statusData.open_findings : []),
    [statusData],
  );

  const recentActions = useMemo<SupervisorActionItem[]>(
    () => (Array.isArray(statusData?.recent_actions) ? statusData.recent_actions : []),
    [statusData],
  );

  const combinedDecisions = useMemo(() => {
    const items: Array<{ item: SupervisorActionItem; isManual: boolean }> = [];
    const seen = new Set<string>();

    if (Array.isArray(manualProposals)) {
      for (const p of manualProposals) {
        const key = `m-${p.ticket ?? ""}-${p.action ?? ""}-${p.reason ?? ""}`;
        seen.add(key);
        items.push({ item: p, isManual: true });
      }
    }

    for (const a of recentActions) {
      const key = `r-${a.id ?? ""}-${a.ticket ?? ""}-${a.action ?? ""}-${a.ts ?? a.time ?? ""}`;
      if (!seen.has(key)) {
        items.push({ item: a, isManual: false });
      }
    }
    return items.slice(0, 12);
  }, [manualProposals, recentActions]);

  const handleToggle = async (payload: { mode?: SupervisorMode; llm_enabled?: boolean }) => {
    setToggling(true);
    setNotice(null);
    try {
      const res = (await apiFetch("/api/positions/supervisor-toggle", {
        method: "POST",
        body: JSON.stringify(payload),
      })) as SupervisorStatusResponse;
      if (res && typeof res === "object") {
        setStatusData((prev) => ({
          ...prev,
          ...res,
          mode: res.mode ?? payload.mode ?? prev?.mode,
          llm_enabled: res.llm_enabled ?? payload.llm_enabled ?? prev?.llm_enabled,
        }));
      }
      if (payload.mode) {
        const nextBadge = getModeBadge(payload.mode);
        setNotice({ ok: true, text: `Pozisyon Doktoru modu güncellendi: ${nextBadge.label}.` });
      } else if (typeof payload.llm_enabled === "boolean") {
        setNotice({
          ok: true,
          text: payload.llm_enabled
            ? "LLM Otomatik Tetik açıldı."
            : "LLM Otomatik Tetik kapatıldı.",
        });
      }
      setError("");
    } catch (err) {
      const detail = err instanceof Error ? err.message : "Ayar güncellenemedi";
      setNotice({ ok: false, text: `Güncelleme başarısız: ${detail}` });
    } finally {
      setToggling(false);
    }
  };

  const handleReview = async (apply: boolean) => {
    setReviewingMode(apply ? "apply" : "dry");
    setNotice(null);
    try {
      const res = (await apiFetch(`/api/positions/review?apply=${apply ? "true" : "false"}`, {
        method: "POST",
      })) as ReviewResponse;

      const proposals = Array.isArray(res?.proposals) ? res.proposals : [];
      setManualProposals(proposals);
      setManualAppliedFlag(Boolean(res?.applied ?? apply));
      setManualNote(res?.note || res?.message || res?.summary || "");

      await fetchStatus();

      setNotice({
        ok: true,
        text: apply
          ? `İnceleme tamamlandı (${proposals.length} karar değerlendirildi, uygun olanlar MT5'e uygulandı).`
          : `Güvenli inceleme tamamlandı (${proposals.length} AI önerisi üretildi, MT5'e uygulanmadı).`,
      });
      setError("");
    } catch (err) {
      const detail = err instanceof Error ? err.message : "İnceleme çalıştırılamadı";
      setNotice({ ok: false, text: `AI incelemesi başarısız: ${detail}` });
    } finally {
      setReviewingMode(null);
    }
  };

  const reviewing = reviewingMode !== null;

  return (
    <section
      aria-label="AI Pozisyon Doktoru"
      className="rounded-2xl border border-bunker-800 bg-bunker-900/75 shadow-lg overflow-hidden"
    >
      {/* ÜST BAŞLIK & KONTROLLER */}
      <div className="p-4 border-b border-bunker-800 space-y-3">
        <div className="flex flex-col xl:flex-row xl:items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-2.5 min-w-0">
            <span
              className={`w-2.5 h-2.5 rounded-full shrink-0 ${
                reviewing ? "bg-cyan-400 animate-ping" : badge.dotCls
              }`}
              aria-hidden="true"
            />
            <h2 className="font-mono text-sm font-bold text-white tracking-tight">
              AI Pozisyon Doktoru
            </h2>
            <span
              className={`font-mono text-2xs font-bold px-2.5 py-0.5 rounded-md border ${badge.badgeCls}`}
            >
              {badge.label}
            </span>
            {typeof statusData?.open_positions_count === "number" && (
              <span className="font-mono text-2xs text-bunker-muted tabular-nums">
                ({statusData.open_positions_count} açık pozisyon)
              </span>
            )}
          </div>

          <div className="flex flex-wrap items-center gap-2">
            {/* Mod Segmented Toggle: Kapalı / Gölge / Aktif */}
            <div
              role="group"
              aria-label="Pozisyon doktoru modu"
              className="inline-flex items-center p-0.5 rounded-lg bg-bunker-950 border border-bunker-800"
            >
              {MODE_OPTIONS.map((opt) => {
                const active = mode === opt.value;
                return (
                  <button
                    key={opt.value}
                    type="button"
                    disabled={toggling || reviewing}
                    aria-pressed={active}
                    onClick={() => void handleToggle({ mode: opt.value })}
                    className={`min-h-8 px-2.5 rounded-md font-mono text-2xs font-bold transition-colors disabled:opacity-50 ${
                      active
                        ? opt.value === "act"
                          ? "bg-emerald-500/20 text-emerald-300 border border-emerald-400/50"
                          : opt.value === "log"
                            ? "bg-amber-500/20 text-amber-300 border border-amber-400/50"
                            : "bg-slate-500/25 text-white border border-slate-400/40"
                        : "text-bunker-muted hover:text-white border border-transparent"
                    }`}
                  >
                    {opt.label}
                  </button>
                );
              })}
            </div>

            {/* LLM Otomatik Tetik */}
            <label className="min-h-9 px-2.5 rounded-lg border border-bunker-800 bg-bunker-950/70 inline-flex items-center gap-2 cursor-pointer select-none font-mono text-2xs text-slate-300 hover:border-bunker-700">
              <input
                type="checkbox"
                checked={llmEnabled}
                disabled={toggling || reviewing}
                onChange={(e) => void handleToggle({ llm_enabled: e.target.checked })}
                className="w-3.5 h-3.5 accent-cyan-400 rounded cursor-pointer disabled:opacity-50"
              />
              <span>LLM Otomatik Tetik</span>
            </label>

            {/* Şimdi İncele (apply=false) */}
            <button
              type="button"
              disabled={reviewing || toggling}
              onClick={() => void handleReview(false)}
              className="min-h-9 px-3 rounded-lg border border-cyan-500/40 bg-cyan-500/10 text-cyan-300 hover:bg-cyan-500/20 disabled:opacity-50 disabled:cursor-not-allowed font-mono text-xs font-bold transition-colors inline-flex items-center gap-1.5"
            >
              {reviewingMode === "dry" ? (
                <>
                  <span className="inline-block w-3 h-3 border-2 border-cyan-300/40 border-t-cyan-300 rounded-full animate-spin" />
                  İnceleniyor…
                </>
              ) : (
                "Şimdi İncele"
              )}
            </button>

            {/* İncele & Uygula (apply=true) */}
            <button
              type="button"
              disabled={reviewing || toggling}
              onClick={() => void handleReview(true)}
              className="min-h-9 px-3 rounded-lg font-mono text-xs font-bold bg-emerald-500/20 border border-emerald-400/50 text-emerald-300 hover:bg-emerald-500/30 disabled:opacity-50 disabled:cursor-not-allowed transition-colors inline-flex items-center gap-1.5"
            >
              {reviewingMode === "apply" ? (
                <>
                  <span className="inline-block w-3 h-3 border-2 border-emerald-300/40 border-t-emerald-300 rounded-full animate-spin" />
                  Uygulanıyor…
                </>
              ) : (
                "İncele & Uygula"
              )}
            </button>
          </div>
        </div>

        {(notice || error) && (
          <div className="space-y-2">
            {notice && (
              <p
                role="status"
                className={`px-3 py-2 rounded-xl border font-mono text-xs ${
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
                className="px-3 py-2 rounded-xl border border-rose-500/40 bg-rose-500/10 text-rose-300 font-mono text-xs flex flex-wrap items-center justify-between gap-2"
              >
                <span>{error}</span>
                <button
                  type="button"
                  onClick={() => void fetchStatus()}
                  className="px-2.5 py-1 rounded-lg bg-rose-500/20 border border-rose-400/40 font-bold hover:bg-rose-500/30"
                >
                  Tekrar Dene
                </button>
              </div>
            )}
          </div>
        )}
      </div>

      {/* GÖVDE */}
      {loading && !statusData ? (
        <div className="p-6 text-center font-mono text-xs text-bunker-muted">
          <div className="inline-block w-4 h-4 border-2 border-cyan-400 border-t-transparent rounded-full animate-spin mb-2" />
          <p>AI Pozisyon Doktoru durumu yükleniyor…</p>
        </div>
      ) : (
        <div className="p-4 grid grid-cols-1 lg:grid-cols-2 gap-4">
          {/* 1. AKTİF BULGULAR */}
          <div className="rounded-xl border border-bunker-800 bg-bunker-950/60 overflow-hidden flex flex-col">
            <div className="px-3.5 py-2.5 border-b border-bunker-800 flex items-center justify-between gap-2">
              <h3 className="font-mono text-xs font-bold text-white uppercase tracking-wider">
                Aktif Bulgular
              </h3>
              <span
                className={`font-mono text-2xs px-2 py-0.5 rounded-md border font-bold tabular-nums ${
                  openFindings.length > 0
                    ? "bg-amber-500/15 border-amber-500/40 text-amber-300"
                    : "bg-emerald-500/15 border-emerald-500/30 text-emerald-300"
                }`}
              >
                {openFindings.length}
              </span>
            </div>

            <div className="p-3 space-y-2 flex-1 max-h-72 overflow-y-auto">
              {openFindings.length === 0 ? (
                <div className="py-5 px-3 rounded-lg border border-emerald-500/20 bg-emerald-950/10 text-center font-mono text-xs text-bunker-muted">
                  Açık pozisyonlarda şart değişimi tespit edilmedi — pozisyonlar sağlıklı izleniyor.
                </div>
              ) : (
                openFindings.map((f, idx) => {
                  const kindLabel = formatFindingKind(f.kind);
                  const detail = f.detail || f.message || f.reason || "Şart değişimi / risk uyarısı";
                  return (
                    <div
                      key={`${f.ticket ?? "t"}-${f.kind ?? idx}-${idx}`}
                      className="p-2.5 rounded-lg border border-amber-500/30 bg-amber-950/15 font-mono space-y-1"
                    >
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <div className="flex items-center gap-2 min-w-0">
                          <span className="font-bold text-xs text-white">
                            {f.symbol || "—"}
                          </span>
                          {f.ticket != null && (
                            <span className="text-2xs text-bunker-muted tabular-nums">
                              #{f.ticket}
                            </span>
                          )}
                        </div>
                        {kindLabel && (
                          <span className="text-2xs px-1.5 py-0.5 rounded bg-amber-500/15 border border-amber-500/35 text-amber-300 font-bold">
                            {kindLabel}
                          </span>
                        )}
                      </div>
                      <p className="text-2xs text-amber-200/90 leading-snug break-words">
                        {detail}
                      </p>
                    </div>
                  );
                })
              )}
            </div>
          </div>

          {/* 2. SON KARARLAR & ÖNERİLER */}
          <div className="rounded-xl border border-bunker-800 bg-bunker-950/60 overflow-hidden flex flex-col">
            <div className="px-3.5 py-2.5 border-b border-bunker-800 flex items-center justify-between gap-2">
              <h3 className="font-mono text-xs font-bold text-white uppercase tracking-wider">
                Son Kararlar &amp; Öneriler
              </h3>
              <span className="font-mono text-2xs px-2 py-0.5 rounded-md bg-cyan-500/15 border border-cyan-500/30 text-cyan-300 font-bold tabular-nums">
                {combinedDecisions.length}
              </span>
            </div>

            <div className="p-3 space-y-2 flex-1 max-h-72 overflow-y-auto">
              {manualNote && (
                <p className="px-2.5 py-1.5 rounded-lg bg-bunker-900/80 border border-bunker-800 font-mono text-2xs text-bunker-muted">
                  {manualNote}
                </p>
              )}

              {combinedDecisions.length === 0 ? (
                <div className="py-5 px-3 rounded-lg border border-bunker-800 bg-bunker-900/40 text-center font-mono text-xs text-bunker-muted">
                  Henüz karar veya AI önerisi yok. &ldquo;Şimdi İncele&rdquo; ile öneri alabilirsiniz.
                </div>
              ) : (
                combinedDecisions.map(({ item, isManual }, idx) => {
                  const actBadge = formatActionBadge(item.action, item.pct);
                  const applied = isActionApplied(item, isManual ? manualAppliedFlag : undefined);
                  const reasonText =
                    item.reason || item.detail || item.note || item.message || "—";
                  const tsVal = item.ts ?? item.time;
                  return (
                    <div
                      key={`${item.id ?? item.ticket ?? "act"}-${idx}`}
                      className="p-2.5 rounded-lg border border-bunker-800 bg-bunker-900/60 font-mono space-y-1.5"
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
                          <span
                            className={`px-1.5 py-0.5 rounded border text-2xs font-bold ${actBadge.cls}`}
                          >
                            {actBadge.label}
                          </span>
                        </div>

                        <div className="flex items-center gap-1.5 shrink-0">
                          <span
                            className={`px-1.5 py-0.5 rounded border text-2xs font-bold ${
                              applied
                                ? "bg-emerald-500/15 border-emerald-500/40 text-emerald-300"
                                : "bg-amber-500/15 border-amber-500/40 text-amber-300"
                            }`}
                          >
                            {applied ? "Uygulandı" : "Öneri"}
                          </span>
                        </div>
                      </div>

                      <p className="text-2xs text-slate-300 leading-snug break-words">
                        {reasonText}
                      </p>

                      {tsVal != null && (
                        <div className="text-2xs text-bunker-muted tabular-nums">
                          {formatUtc3(tsVal)}
                        </div>
                      )}
                    </div>
                  );
                })
              )}
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
