"use client";

import React, { useCallback, useMemo, useState } from "react";
import Link from "next/link";
import dynamic from "next/dynamic";
import { apiFetch } from "../../lib/api";
import { usePolling } from "../../lib/usePolling";
import { formatPrice, formatUtc3 } from "../../lib/format";

const ForexChartModal = dynamic(() => import("../components/ForexChartModal"), { ssr: false });

type SupervisorMode = "off" | "log" | "act";

interface OpenPositionItem {
  ticket: number;
  symbol: string;
  display?: string;
  direction: "BUY" | "SELL" | string;
  lots: number;
  entry_price: number;
  current_price: number;
  sl_price?: number | null;
  tp_price?: number | null;
  pnl_usd?: number | null;
  pnl_pips?: number | null;
  open_time?: string;
  open_ts?: number;
  strategy?: string;
  strategy_label?: string;
  protection?: string;
}

interface AppliedTicketAction {
  action?: string;
  cmd_action?: string;
  ts?: number | string;
  reason?: string;
  sl?: number | null;
  new_sl?: number | null;
  pct?: number | null;
}

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
  cmd_action?: string;
  sl?: number | null;
  new_sl?: number | null;
  tp?: number | null;
  pct?: number | null;
  reason?: string;
  detail?: string;
  note?: string;
  message?: string;
  applied?: boolean;
  already_applied?: boolean;
  enforced?: boolean;
  status?: string;
  mode?: string;
  source?: string;
  ts?: number | string;
  time?: number | string;
  applied_ts?: number | string;
}

interface SupervisorStatusResponse {
  mode?: SupervisorMode | string;
  llm_enabled?: boolean;
  cooldown_min?: number;
  open_positions_count?: number;
  open_positions?: OpenPositionItem[];
  applied_by_ticket?: Record<string, AppliedTicketAction[] | AppliedTicketAction>;
  open_findings?: OpenFindingItem[] | Record<string, OpenFindingItem[]>;
  recent_actions?: SupervisorActionItem[];
  last_review_at?: number | string | null;
  last_run_ts?: number | null;
  last_llm_ts?: number | null;
  note?: string;
}

interface ReviewResponse {
  proposals?: SupervisorActionItem[];
  rejected?: SupervisorActionItem[];
  applied?: unknown[];
  applied_count?: number;
  note?: string;
  message?: string;
  summary?: string;
}

interface ApplyProposalsResponse {
  applied?: Array<{
    ticket?: number | string;
    symbol?: string;
    action?: string;
    cmd_action?: string;
    reason?: string;
  }>;
  applied_count?: number;
  skipped?: Array<{
    ticket?: number | string;
    symbol?: string;
    action?: string;
    reason?: string;
  }>;
  skipped_count?: number;
  note?: string;
  message?: string;
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
  shortLabel: string;
  badgeCls: string;
  dotCls: string;
} {
  if (mode === "act") {
    return {
      label: "Aktif (Otomatik Uygula)",
      shortLabel: "Aktif",
      badgeCls: "bg-emerald-500/20 text-emerald-300 border-emerald-400/50",
      dotCls: "bg-emerald-400",
    };
  }
  if (mode === "log") {
    return {
      label: "Gölge (Sadece Öner)",
      shortLabel: "Gölge",
      badgeCls: "bg-amber-500/20 text-amber-300 border-amber-400/50",
      dotCls: "bg-amber-400",
    };
  }
  return {
    label: "Kapalı",
    shortLabel: "Kapalı",
    badgeCls: "bg-slate-500/20 text-slate-300 border-slate-500/40",
    dotCls: "bg-slate-400",
  };
}

function isHoldAction(rawAction?: string): boolean {
  const a = String(rawAction || "").toLowerCase().trim();
  return !a || a === "hold" || a === "no_op" || a === "keep" || a === "tut";
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
  if (isHoldAction(a)) {
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

function isActionApplied(item: SupervisorActionItem): boolean {
  if (typeof item.applied === "boolean") return item.applied;
  if (typeof item.enforced === "boolean") return item.enforced;
  const st = String(item.status || "").toLowerCase();
  if (st === "applied" || st === "uygulandı" || st === "executed") return true;
  if (st === "proposed" || st === "öneri" || st === "shadow") return false;
  const rawAct = String(item.action || "").toLowerCase();
  if (rawAct.startsWith("komut:")) return true;
  if (item.cmd_action) return true;
  return false;
}

function isAlreadyApplied(item: SupervisorActionItem): boolean {
  if (item.already_applied) return true;
  const st = String(item.status || "").toLowerCase();
  return st === "already_applied" || st === "duplicate";
}

function isProposalActionable(item: SupervisorActionItem): boolean {
  return !isHoldAction(item.action) && !isActionApplied(item) && !isAlreadyApplied(item);
}

function getProposalKey(item: SupervisorActionItem, idx: number): string {
  return `${item.ticket ?? "t"}-${String(item.action ?? "").toLowerCase()}-${idx}`;
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

function flattenFindings(
  raw?: OpenFindingItem[] | Record<string, OpenFindingItem[]>,
  posByTicket?: Map<string, OpenPositionItem>,
): OpenFindingItem[] {
  if (!raw) return [];
  if (Array.isArray(raw)) return raw;
  if (typeof raw === "object") {
    const out: OpenFindingItem[] = [];
    for (const [ticketKey, list] of Object.entries(raw)) {
      if (!Array.isArray(list)) continue;
      const pos = posByTicket?.get(String(ticketKey));
      for (const f of list) {
        out.push({
          ...f,
          ticket: f.ticket ?? ticketKey,
          symbol: f.symbol ?? pos?.symbol,
        });
      }
    }
    return out;
  }
  return [];
}

function fmtUsd(v?: number | null): string {
  if (typeof v !== "number" || !Number.isFinite(v)) return "—";
  const sign = v >= 0 ? "+" : "-";
  return `${sign}$${Math.abs(v).toFixed(2)}`;
}

export default function PositionSupervisorPage() {
  const [statusData, setStatusData] = useState<SupervisorStatusResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [toggling, setToggling] = useState(false);
  const [reviewing, setReviewing] = useState(false);
  const [applying, setApplying] = useState(false);

  const [proposals, setProposals] = useState<SupervisorActionItem[] | null>(null);
  const [selectedKeys, setSelectedKeys] = useState<Set<string>>(() => new Set());
  const [reviewNote, setReviewNote] = useState("");
  const [notice, setNotice] = useState<{ ok: boolean; text: string } | null>(null);
  const [chartSymbol, setChartSymbol] = useState<string | null>(null);

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
      setError(`AI Pozisyon Doktoru durumu alınamadı: ${detail}`);
    } finally {
      setLoading(false);
    }
  }, []);

  usePolling(fetchStatus, 15_000);

  const mode = normalizeMode(statusData?.mode);
  const llmEnabled = Boolean(statusData?.llm_enabled);
  const badge = getModeBadge(mode);

  const openPositions = useMemo<OpenPositionItem[]>(
    () => (Array.isArray(statusData?.open_positions) ? statusData.open_positions : []),
    [statusData],
  );

  const posByTicket = useMemo(() => {
    const map = new Map<string, OpenPositionItem>();
    for (const p of openPositions) {
      if (p.ticket != null) map.set(String(p.ticket), p);
    }
    return map;
  }, [openPositions]);

  const openFindings = useMemo(
    () => flattenFindings(statusData?.open_findings, posByTicket),
    [statusData, posByTicket],
  );

  const recentActions = useMemo<SupervisorActionItem[]>(
    () =>
      (Array.isArray(statusData?.recent_actions) ? statusData.recent_actions : []).filter((a) => {
        const act = String(a?.action || "").trim().toLowerCase();
        return act !== "hold" && act !== "no_op";
      }),
    [statusData],
  );

  const visibleProposals = useMemo(() => {
    if (!proposals) return null;
    return proposals.filter((p) => {
      const act = String(p?.action || "").trim().toLowerCase();
      return act !== "hold" && act !== "no_op";
    });
  }, [proposals]);

  const holdProposals = useMemo(() => {
    if (!proposals) return [];
    return proposals.filter((p) => {
      const act = String(p?.action || "").trim().toLowerCase();
      return act === "hold" || act === "no_op";
    });
  }, [proposals]);

  const appliedByTicket = useMemo(() => {
    const raw = statusData?.applied_by_ticket;
    const map = new Map<string, AppliedTicketAction[]>();
    if (!raw || typeof raw !== "object") return map;
    for (const [k, val] of Object.entries(raw)) {
      if (Array.isArray(val)) {
        map.set(String(k), val);
      } else if (val && typeof val === "object") {
        map.set(String(k), [val]);
      }
    }
    return map;
  }, [statusData]);

  // KPI hesaplamaları
  const openCount =
    typeof statusData?.open_positions_count === "number"
      ? statusData.open_positions_count
      : openPositions.length;

  const totalOpenPnl = useMemo(() => {
    if (openPositions.length === 0) return null;
    return openPositions.reduce((sum, p) => sum + (Number(p.pnl_usd) || 0), 0);
  }, [openPositions]);

  const actionableEntries = useMemo(() => {
    if (!proposals) return [];
    return proposals
      .map((item, idx) => ({ item, idx, key: getProposalKey(item, idx) }))
      .filter(({ item }) => isProposalActionable(item));
  }, [proposals]);

  const selectedEntries = useMemo(
    () => actionableEntries.filter(({ key }) => selectedKeys.has(key)),
    [actionableEntries, selectedKeys],
  );

  const allActionableSelected =
    actionableEntries.length > 0 && selectedEntries.length === actionableEntries.length;

  const appliedRecentCount = useMemo(
    () => recentActions.filter((a) => isActionApplied(a)).length,
    [recentActions],
  );

  const lastReviewTs =
    statusData?.last_review_at ||
    (statusData?.last_llm_ts && statusData.last_llm_ts > 0 ? statusData.last_llm_ts : null) ||
    (statusData?.last_run_ts && statusData.last_run_ts > 0 ? statusData.last_run_ts : null);

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

  const handleReview = async () => {
    setReviewing(true);
    setNotice(null);
    try {
      const res = (await apiFetch("/api/positions/review?apply=false", {
        method: "POST",
      })) as ReviewResponse;

      const nowSec = Math.floor(Date.now() / 1000);
      const nextProposals = (Array.isArray(res?.proposals) ? res.proposals : []).map((p) => ({
        ...p,
        ts: p.ts ?? p.time ?? nowSec,
      }));
      setProposals(nextProposals);
      setSelectedKeys(new Set());
      setReviewNote(res?.note || res?.message || res?.summary || "");

      await fetchStatus();

      const actionableCount = nextProposals.filter(isProposalActionable).length;
      setNotice({
        ok: true,
        text:
          nextProposals.length === 0
            ? "İnceleme tamamlandı — şu an açık pozisyon için yeni öneri üretilmedi."
            : `İnceleme tamamlandı: ${nextProposals.length} karar (${actionableCount} uygulanabilir öneri). Uygulamak istediklerinizi seçin.`,
      });
      setError("");
    } catch (err) {
      const detail = err instanceof Error ? err.message : "İnceleme çalıştırılamadı";
      setNotice({ ok: false, text: `AI incelemesi başarısız: ${detail}` });
    } finally {
      setReviewing(false);
    }
  };

  const toggleSelectKey = (key: string) => {
    setSelectedKeys((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const toggleSelectAll = () => {
    if (allActionableSelected) {
      setSelectedKeys(new Set());
    } else {
      setSelectedKeys(new Set(actionableEntries.map((e) => e.key)));
    }
  };

  const handleApplyProposals = async (scope: "selected" | "all") => {
    const targets = scope === "all" ? actionableEntries : selectedEntries;
    if (targets.length === 0) return;

    setApplying(true);
    setNotice(null);
    try {
      const res = (await apiFetch("/api/positions/apply-proposals", {
        method: "POST",
        body: JSON.stringify({ proposals: targets.map((t) => t.item) }),
      })) as ApplyProposalsResponse;

      const nowSec = Math.floor(Date.now() / 1000);
      const skippedList = Array.isArray(res?.skipped) ? res.skipped : [];
      const appliedList = Array.isArray(res?.applied) ? res.applied : [];
      const appliedCount =
        typeof res?.applied_count === "number"
          ? res.applied_count
          : appliedList.length > 0
            ? appliedList.length
            : Math.max(0, targets.length - skippedList.length);
      const skippedCount =
        typeof res?.skipped_count === "number" ? res.skipped_count : skippedList.length;

      const skippedSig = new Set(
        skippedList.map((s) => `${s.ticket ?? ""}|${String(s.action ?? "").toLowerCase()}`),
      );
      const appliedSig = new Set(
        appliedList.map((a) => `${a.ticket ?? ""}|${String(a.action ?? "").toLowerCase()}`),
      );
      const targetKeySet = new Set(targets.map((t) => t.key));

      setProposals((prev) => {
        if (!prev) return prev;
        return prev.map((p, idx) => {
          const k = getProposalKey(p, idx);
          if (!targetKeySet.has(k)) return p;
          const sig = `${p.ticket ?? ""}|${String(p.action ?? "").toLowerCase()}`;
          if (skippedSig.has(sig)) {
            return { ...p, already_applied: true };
          }
          if (appliedList.length === 0 || appliedSig.has(sig) || appliedCount > 0) {
            return { ...p, applied: true, status: "applied", applied_ts: nowSec, ts: nowSec };
          }
          return p;
        });
      });

      setSelectedKeys((prev) => {
        const next = new Set(prev);
        for (const k of targetKeySet) next.delete(k);
        return next;
      });

      const parts: string[] = [];
      if (appliedCount > 0) parts.push(`${appliedCount} öneri MT5 kuyruğuna eklendi`);
      if (skippedCount > 0) parts.push(`${skippedCount} öneri atlandı`);
      const extraNote = res?.note || res?.message;
      setNotice({
        ok: appliedCount > 0 || skippedCount === 0,
        text: `${parts.join(" · ") || "İşlem tamamlandı"}${extraNote ? ` — ${extraNote}` : "."}`,
      });

      await fetchStatus();
    } catch (err) {
      const detail = err instanceof Error ? err.message : "Öneriler uygulanamadı";
      setNotice({ ok: false, text: `Uygulama başarısız: ${detail}` });
    } finally {
      setApplying(false);
    }
  };

  return (
    <div className="space-y-6 pb-16 animate-in fade-in duration-300">
      {/* ÜST BAŞLIK & KONTROL ŞERİDİ */}
      <header className="rounded-2xl border border-bunker-800 bg-bunker-900/80 p-4 sm:p-5 shadow-lg space-y-4">
        <div className="flex flex-col xl:flex-row xl:items-center justify-between gap-4">
          <div className="space-y-1 min-w-0">
            <div className="flex flex-wrap items-center gap-2.5">
              <span
                className={`w-2.5 h-2.5 rounded-full shrink-0 ${
                  reviewing || applying ? "bg-cyan-400 animate-ping" : badge.dotCls
                }`}
                aria-hidden="true"
              />
              <h1 className="text-xl sm:text-2xl font-black font-mono text-white tracking-tight">
                AI Pozisyon Doktoru
              </h1>
              <span
                className={`font-mono text-2xs font-bold px-2.5 py-0.5 rounded-md border ${badge.badgeCls}`}
              >
                {badge.label}
              </span>
            </div>
            <p className="text-xs text-bunker-muted">
              Açık pozisyonların anlık tez geçersizleşme denetimi ve yapay zeka destekli aksiyon yönetimi
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-2.5">
            {/* Mod Segmented Toggle: Kapalı / Gölge / Aktif */}
            <div
              role="group"
              aria-label="Pozisyon doktoru modu"
              className="inline-flex items-center p-0.5 rounded-xl bg-bunker-950 border border-bunker-800"
            >
              {MODE_OPTIONS.map((opt) => {
                const active = mode === opt.value;
                return (
                  <button
                    key={opt.value}
                    type="button"
                    disabled={toggling || reviewing || applying}
                    aria-pressed={active}
                    onClick={() => void handleToggle({ mode: opt.value })}
                    className={`min-h-9 px-3 rounded-lg font-mono text-xs font-bold transition-colors disabled:opacity-50 ${
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
            <label className="min-h-10 px-3 rounded-xl border border-bunker-800 bg-bunker-950/70 inline-flex items-center gap-2 cursor-pointer select-none font-mono text-xs text-slate-300 hover:border-bunker-700">
              <input
                type="checkbox"
                checked={llmEnabled}
                disabled={toggling || reviewing || applying}
                onChange={(e) => void handleToggle({ llm_enabled: e.target.checked })}
                className="w-3.5 h-3.5 accent-cyan-400 rounded cursor-pointer disabled:opacity-50"
              />
              <span>LLM Otomatik Tetik</span>
            </label>

            {/* Pozisyonları İncele (apply=false) */}
            <button
              type="button"
              disabled={reviewing || applying || toggling}
              onClick={() => void handleReview()}
              className="min-h-10 px-4 rounded-xl bg-gradient-to-r from-cyan-600 to-blue-600 hover:from-cyan-500 hover:to-blue-500 text-white font-mono text-xs font-bold shadow-lg shadow-cyan-950/40 disabled:opacity-50 disabled:cursor-not-allowed transition-all inline-flex items-center gap-2"
            >
              {reviewing ? (
                <>
                  <span className="inline-block w-3.5 h-3.5 border-2 border-white/40 border-t-white rounded-full animate-spin" />
                  <span>Pozisyonlar İnceleniyor…</span>
                </>
              ) : (
                <span>Pozisyonları İncele</span>
              )}
            </button>

            <Link
              href="/forex/reports"
              className="min-h-10 px-3 rounded-xl border border-bunker-800 bg-bunker-950/70 text-bunker-muted hover:text-white font-mono text-xs font-bold inline-flex items-center transition-colors"
            >
              Raporlar →
            </Link>
          </div>
        </div>

        {(notice || error) && (
          <div className="space-y-2 pt-1">
            {notice && (
              <p
                role="status"
                className={`px-3.5 py-2.5 rounded-xl border font-mono text-xs ${
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
                className="px-3.5 py-2.5 rounded-xl border border-rose-500/40 bg-rose-500/10 text-rose-300 font-mono text-xs flex flex-wrap items-center justify-between gap-2"
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
      </header>

      {/* 4-KPI ÖZET ŞERİDİ */}
      <section aria-label="Özet metrikler" className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <div className="rounded-xl border border-bunker-800 bg-bunker-900/80 p-3.5">
          <p className="text-2xs uppercase tracking-wider text-bunker-muted font-mono">
            Açık Pozisyonlar
          </p>
          <p className="mt-1 text-2xl font-black font-mono tabular-nums text-white">
            {openCount}
          </p>
          <p className="mt-0.5 text-2xs font-mono tabular-nums text-bunker-muted">
            Toplam Anlık K/Z:{" "}
            <span
              className={
                totalOpenPnl == null
                  ? "text-bunker-muted"
                  : totalOpenPnl >= 0
                    ? "text-emerald-400 font-bold"
                    : "text-rose-400 font-bold"
              }
            >
              {fmtUsd(totalOpenPnl)}
            </span>
          </p>
        </div>

        <div className="rounded-xl border border-bunker-800 bg-bunker-900/80 p-3.5">
          <p className="text-2xs uppercase tracking-wider text-bunker-muted font-mono">
            Aktif Şart Değişimi Bulgusu
          </p>
          <p
            className={`mt-1 text-2xl font-black font-mono tabular-nums ${
              openFindings.length > 0 ? "text-amber-300" : "text-emerald-400"
            }`}
          >
            {openFindings.length}
          </p>
          <p className="mt-0.5 text-2xs font-mono text-bunker-muted">
            {openFindings.length > 0 ? "Dikkat gerektiren bulgu var" : "Şartlar sağlıklı izleniyor"}
          </p>
        </div>

        <div className="rounded-xl border border-bunker-800 bg-bunker-900/80 p-3.5">
          <p className="text-2xs uppercase tracking-wider text-bunker-muted font-mono">
            Uygulanabilir AI Önerisi
          </p>
          <p
            className={`mt-1 text-2xl font-black font-mono tabular-nums ${
              actionableEntries.length > 0 ? "text-cyan-300" : "text-white"
            }`}
          >
            {actionableEntries.length}
          </p>
          <p className="mt-0.5 text-2xs font-mono text-bunker-muted">
            {proposals === null
              ? "İnceleme bekleniyor"
              : `${proposals.length} toplam karar üretildi`}
          </p>
        </div>

        <div className="rounded-xl border border-bunker-800 bg-bunker-900/80 p-3.5">
          <p className="text-2xs uppercase tracking-wider text-bunker-muted font-mono">
            Uygulanan Aksiyonlar
          </p>
          <p className="mt-1 text-2xl font-black font-mono tabular-nums text-emerald-400">
            {appliedRecentCount}
          </p>
          <p className="mt-0.5 text-2xs font-mono tabular-nums text-bunker-muted truncate">
            Son inceleme:{" "}
            <span className="text-slate-300">
              {lastReviewTs ? formatUtc3(lastReviewTs) : "—"}
            </span>
          </p>
        </div>
      </section>

      {/* İNTERAKTİF AI ÖNERİLERİ PANELİ (ANA ODAK) */}
      <section
        aria-label="İnteraktif AI Önerileri"
        className="rounded-2xl border border-bunker-800 bg-bunker-900/80 shadow-lg overflow-hidden"
      >
        <div className="px-4 py-3.5 border-b border-bunker-800 flex flex-col md:flex-row md:items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="font-mono text-sm font-bold text-white uppercase tracking-wider">
              AI Aksiyon Önerileri
            </h2>
            <span className="font-mono text-2xs px-2 py-0.5 rounded-md bg-cyan-500/15 border border-cyan-500/35 text-cyan-300 font-bold tabular-nums">
              {proposals ? `${proposals.length} karar · ${actionableEntries.length} uygulanabilir` : "Hazır"}
            </span>
          </div>

          {/* Toplu / Seçimli Aksiyon Çubuğu */}
          {proposals && proposals.length > 0 && (
            <div className="flex flex-wrap items-center gap-2">
              <button
                type="button"
                disabled={actionableEntries.length === 0 || applying}
                onClick={toggleSelectAll}
                className="min-h-9 px-3 rounded-lg border border-bunker-700 bg-bunker-950 text-slate-300 hover:text-white hover:border-bunker-600 disabled:opacity-40 font-mono text-2xs font-bold transition-colors"
              >
                {allActionableSelected ? "Seçimi Temizle" : "Tümünü Seç"}
              </button>

              <button
                type="button"
                disabled={selectedEntries.length === 0 || applying}
                onClick={() => void handleApplyProposals("selected")}
                className="min-h-9 px-3.5 rounded-lg border border-cyan-400/50 bg-cyan-500/15 text-cyan-200 hover:bg-cyan-500/25 disabled:opacity-40 disabled:cursor-not-allowed font-mono text-xs font-bold transition-colors inline-flex items-center gap-1.5 tabular-nums"
              >
                {applying ? "Uygulanıyor…" : `Seçilenleri Uygula (${selectedEntries.length})`}
              </button>

              <button
                type="button"
                disabled={actionableEntries.length === 0 || applying}
                onClick={() => void handleApplyProposals("all")}
                className="min-h-9 px-3.5 rounded-lg border border-emerald-400/50 bg-emerald-500/20 text-emerald-200 hover:bg-emerald-500/30 disabled:opacity-40 disabled:cursor-not-allowed font-mono text-xs font-bold transition-colors inline-flex items-center gap-1.5 tabular-nums"
              >
                {applying ? "Uygulanıyor…" : `Tümünü Uygula (${actionableEntries.length})`}
              </button>
            </div>
          )}
        </div>

        <div className="p-4 space-y-3">
          {reviewNote && (
            <p className="px-3 py-2 rounded-xl bg-bunker-950/70 border border-bunker-800 font-mono text-2xs text-bunker-muted">
              {reviewNote}
            </p>
          )}

          {proposals === null ? (
            <div className="py-10 px-4 rounded-xl border border-dashed border-bunker-700 bg-bunker-950/40 text-center space-y-2">
              <p className="font-mono text-xs font-bold text-slate-200">
                Henüz canlı AI incelemesi çalıştırılmadı.
              </p>
              <p className="font-mono text-2xs text-bunker-muted max-w-xl mx-auto">
                Üstteki <span className="text-cyan-300 font-bold">&ldquo;Pozisyonları İncele&rdquo;</span> düğmesine
                basarak açık MT5 pozisyonları için güvenli önizleme önerileri üretin; ardından tek tek veya toplu
                olarak MT5&apos;e uygulayın.
              </p>
            </div>
          ) : !visibleProposals || visibleProposals.length === 0 ? (
            <div className="py-6 px-4 rounded-xl border border-emerald-500/25 bg-emerald-950/10 text-center font-mono text-xs text-emerald-200/90 space-y-1.5">
              <p className="font-bold">✓ Tüm açık pozisyonlar sağlıklı — müdahale gerektiren öneri yok.</p>
              {holdProposals.length > 0 && (
                <p className="text-2xs text-bunker-muted">
                  Müdahale gerekmeyen ({holdProposals.length}):{" "}
                  {holdProposals.map((h) => `${h.symbol || `#${h.ticket ?? "?"}`}`).join(", ")}
                </p>
              )}
            </div>
          ) : (
            <div className="space-y-2.5">
              {visibleProposals.map((item, idx) => {
                const key = getProposalKey(item, idx);
                const actBadge = formatActionBadge(item.action, item.pct);
                const applied = isActionApplied(item);
                const already = isAlreadyApplied(item);
                const actionable = isProposalActionable(item);
                const checked = actionable && selectedKeys.has(key);
                const slVal = item.new_sl ?? item.sl;
                const reasonText =
                  item.reason || item.detail || item.note || item.message || "—";
                const tsVal = applied ? (item.applied_ts ?? item.ts ?? item.time) : (item.ts ?? item.time);

                return (
                  <div
                    key={key}
                    className={`p-3.5 rounded-xl border font-mono transition-colors ${
                      applied
                        ? "border-emerald-500/35 bg-emerald-950/15"
                        : checked
                          ? "border-cyan-400/50 bg-cyan-950/20"
                          : "border-bunker-800 bg-bunker-950/60"
                    }`}
                  >
                    <div className="flex items-start gap-3">
                      <div className="pt-0.5 shrink-0">
                        <input
                          type="checkbox"
                          checked={checked}
                          disabled={!actionable || applying}
                          onChange={() => toggleSelectKey(key)}
                          aria-label={`${item.symbol || "Pozisyon"} #${item.ticket ?? idx} önerisini seç`}
                          className="w-4 h-4 accent-cyan-400 rounded cursor-pointer disabled:opacity-35 disabled:cursor-not-allowed"
                        />
                      </div>

                      <div className="flex-1 min-w-0 space-y-2">
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <div className="flex flex-wrap items-center gap-2 min-w-0">
                            {item.symbol ? (
                              <button
                                type="button"
                                onClick={() => setChartSymbol(item.symbol!)}
                                title={`${item.symbol} canlı grafiğini aç`}
                                className="font-bold text-sm text-white hover:text-cyan-300 hover:underline decoration-cyan-400/60 underline-offset-2 text-left transition-colors cursor-pointer"
                              >
                                {item.symbol}
                              </button>
                            ) : (
                              <span className="font-bold text-sm text-white">—</span>
                            )}
                            {item.ticket != null && (
                              <span className="text-xs text-bunker-muted tabular-nums">
                                #{item.ticket}
                              </span>
                            )}
                            <span
                              className={`px-2 py-0.5 rounded-md border text-2xs font-bold ${actBadge.cls}`}
                            >
                              {actBadge.label}
                            </span>
                            {typeof slVal === "number" && Number.isFinite(slVal) && slVal > 0 && (
                              <span className="px-2 py-0.5 rounded-md bg-bunker-900 border border-bunker-700 text-2xs text-sky-300 tabular-nums">
                                Yeni SL: {formatPrice(slVal)}
                              </span>
                            )}
                            {typeof item.pct === "number" && Number.isFinite(item.pct) && item.pct > 0 && (
                              <span className="px-2 py-0.5 rounded-md bg-bunker-900 border border-bunker-700 text-2xs text-amber-300 tabular-nums">
                                Oran: %{item.pct}
                              </span>
                            )}
                          </div>

                          <span
                            className={`px-2 py-0.5 rounded-md border text-2xs font-bold shrink-0 ${
                              applied
                                ? "bg-emerald-500/15 border-emerald-500/40 text-emerald-300"
                                : already
                                  ? "bg-slate-500/15 border-slate-500/40 text-slate-300"
                                  : "bg-amber-500/15 border-amber-500/40 text-amber-300"
                            }`}
                          >
                            {applied
                              ? "Uygulandı"
                              : already
                                ? "Daha önce uygulandı"
                                : "Öneri"}
                          </span>
                        </div>

                        <p className="text-xs text-slate-200 leading-relaxed break-words">
                          {reasonText}
                        </p>

                        {tsVal != null && (
                          <div className="text-2xs text-bunker-muted tabular-nums pt-1 border-t border-bunker-800/70">
                            {applied ? "Uygulama zamanı:" : "Öneri zamanı:"}{" "}
                            <span className="text-slate-300 font-semibold">
                              {formatUtc3(tsVal)}
                            </span>
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </section>

      {/* 2 SÜTUNLU CANLI İZLEME IZGARASI */}
      {loading && !statusData ? (
        <div className="p-8 rounded-2xl border border-bunker-800 bg-bunker-900/70 text-center font-mono text-xs text-bunker-muted">
          <div className="inline-block w-4 h-4 border-2 border-cyan-400 border-t-transparent rounded-full animate-spin mb-2" />
          <p>Canlı pozisyon ve doktor verileri yükleniyor…</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 xl:grid-cols-12 gap-5">
          {/* SOL SÜTUN: AÇIK MT5 POZİSYONLARI */}
          <section className="xl:col-span-7 rounded-2xl border border-bunker-800 bg-bunker-900/75 shadow-lg overflow-hidden flex flex-col">
            <div className="px-4 py-3 border-b border-bunker-800 flex items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <h2 className="font-mono text-xs font-bold text-white uppercase tracking-wider">
                  Açık MT5 Pozisyonları
                </h2>
                <span className="font-mono text-2xs px-2 py-0.5 rounded-md bg-blue-500/15 border border-blue-500/35 text-blue-300 font-bold tabular-nums">
                  {openPositions.length}
                </span>
              </div>
              <Link
                href="/forex/portfolio"
                className="font-mono text-2xs font-bold text-cyan-300 hover:underline"
              >
                Portföy Konsolu →
              </Link>
            </div>

            {openPositions.length === 0 ? (
              <div className="p-8 text-center font-mono text-xs text-bunker-muted">
                Şu an açık MT5 pozisyonu yok.
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-left border-collapse font-mono text-xs">
                  <thead>
                    <tr className="border-b border-bunker-800 bg-bunker-950/60 text-2xs text-bunker-muted uppercase">
                      <th className="py-2.5 px-3">Sembol / Bilet</th>
                      <th className="py-2.5 px-2">Yön / Lot</th>
                      <th className="py-2.5 px-2">Giriş → Anlık</th>
                      <th className="py-2.5 px-2">SL / TP</th>
                      <th className="py-2.5 px-3 text-right">Anlık K/Z</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-bunker-800/70">
                    {openPositions.map((pos) => {
                      const isBuy = String(pos.direction || "").toUpperCase() === "BUY";
                      const pnl = Number(pos.pnl_usd ?? 0);
                      const appliedList = appliedByTicket.get(String(pos.ticket)) || [];
                      return (
                        <tr key={pos.ticket} className="hover:bg-bunker-800/30 transition-colors">
                          <td className="py-3 px-3 align-top">
                            <button
                              type="button"
                              onClick={() => setChartSymbol(pos.symbol)}
                              title={`${pos.display || pos.symbol} canlı grafiğini aç`}
                              className="font-bold text-white hover:text-cyan-300 hover:underline decoration-cyan-400/60 underline-offset-2 text-left transition-colors cursor-pointer"
                            >
                              {pos.display || pos.symbol}
                            </button>
                            <div className="text-2xs text-bunker-muted tabular-nums">
                              #{pos.ticket}
                            </div>
                            {appliedList.length > 0 && (
                              <div className="flex flex-wrap gap-1 mt-1.5">
                                {appliedList.map((a, i) => {
                                  const b = formatActionBadge(a.action || a.cmd_action, a.pct);
                                  return (
                                    <span
                                      key={`${pos.ticket}-ap-${i}`}
                                      title={a.ts ? `Uygulama: ${formatUtc3(a.ts)}` : a.reason}
                                      className={`px-1.5 py-0.5 rounded border text-2xs font-bold ${b.cls}`}
                                    >
                                      ✓ {b.label}
                                    </span>
                                  );
                                })}
                              </div>
                            )}
                          </td>
                          <td className="py-3 px-2 align-top whitespace-nowrap">
                            <span
                              className={`inline-block px-1.5 py-0.5 rounded border text-2xs font-bold ${
                                isBuy
                                  ? "bg-emerald-500/15 text-emerald-300 border-emerald-500/40"
                                  : "bg-rose-500/15 text-rose-300 border-rose-500/40"
                              }`}
                            >
                              {isBuy ? "BUY" : "SELL"}
                            </span>
                            <div className="text-2xs text-bunker-muted tabular-nums mt-1">
                              {Number(pos.lots || 0).toFixed(2)} lot
                            </div>
                          </td>
                          <td className="py-3 px-2 align-top whitespace-nowrap tabular-nums">
                            <div className="text-slate-300">{formatPrice(pos.entry_price)}</div>
                            <div className="text-2xs text-cyan-300">
                              → {formatPrice(pos.current_price)}
                            </div>
                          </td>
                          <td className="py-3 px-2 align-top whitespace-nowrap text-2xs tabular-nums">
                            <div className="text-rose-400">
                              SL: {pos.sl_price ? formatPrice(pos.sl_price) : "—"}
                            </div>
                            <div className="text-emerald-400">
                              TP: {pos.tp_price ? formatPrice(pos.tp_price) : "—"}
                            </div>
                          </td>
                          <td className="py-3 px-3 align-top text-right whitespace-nowrap tabular-nums">
                            <div
                              className={`font-bold ${
                                pnl >= 0 ? "text-emerald-400" : "text-rose-400"
                              }`}
                            >
                              {fmtUsd(pnl)}
                            </div>
                            {typeof pos.pnl_pips === "number" && Number.isFinite(pos.pnl_pips) && (
                              <div className="text-2xs text-bunker-muted">
                                {pos.pnl_pips >= 0 ? "+" : ""}
                                {pos.pnl_pips.toFixed(1)} pip
                              </div>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          {/* SAĞ SÜTUN: AKTİF BULGULAR + SON KARARLAR */}
          <div className="xl:col-span-5 space-y-5">
            {/* Aktif Şart Değişimi Bulguları */}
            <section className="rounded-2xl border border-bunker-800 bg-bunker-900/75 shadow-lg overflow-hidden">
              <div className="px-4 py-3 border-b border-bunker-800 flex items-center justify-between gap-2">
                <h2 className="font-mono text-xs font-bold text-white uppercase tracking-wider">
                  Aktif Şart Değişimi Bulguları
                </h2>
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

              <div className="p-3.5 space-y-2 max-h-72 overflow-y-auto">
                {openFindings.length === 0 ? (
                  <div className="py-5 px-3 rounded-xl border border-emerald-500/20 bg-emerald-950/10 text-center font-mono text-xs text-bunker-muted">
                    Açık pozisyonlarda şart değişimi tespit edilmedi — pozisyonlar sağlıklı izleniyor.
                  </div>
                ) : (
                  openFindings.map((f, idx) => {
                    const kindLabel = formatFindingKind(f.kind);
                    const detail = f.detail || f.message || f.reason || "Şart değişimi / risk uyarısı";
                    return (
                      <div
                        key={`${f.ticket ?? "t"}-${f.kind ?? idx}-${idx}`}
                        className="p-3 rounded-xl border border-amber-500/30 bg-amber-950/15 font-mono space-y-1"
                      >
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <div className="flex items-center gap-2 min-w-0">
                            {f.symbol ? (
                              <button
                                type="button"
                                onClick={() => setChartSymbol(f.symbol!)}
                                title={`${f.symbol} canlı grafiğini aç`}
                                className="font-bold text-xs text-white hover:text-cyan-300 hover:underline decoration-cyan-400/60 underline-offset-2 text-left transition-colors cursor-pointer"
                              >
                                {f.symbol}
                              </button>
                            ) : (
                              <span className="font-bold text-xs text-white">—</span>
                            )}
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
            </section>

            {/* Son Kararlar & Uygulanan Aksiyonlar */}
            <section className="rounded-2xl border border-bunker-800 bg-bunker-900/75 shadow-lg overflow-hidden">
              <div className="px-4 py-3 border-b border-bunker-800 flex items-center justify-between gap-2">
                <h2 className="font-mono text-xs font-bold text-white uppercase tracking-wider">
                  Son Kararlar &amp; Uygulanan Aksiyonlar
                </h2>
                <span className="font-mono text-2xs px-2 py-0.5 rounded-md bg-cyan-500/15 border border-cyan-500/30 text-cyan-300 font-bold tabular-nums">
                  {recentActions.length}
                </span>
              </div>

              <div className="p-3.5 space-y-2 max-h-96 overflow-y-auto">
                {recentActions.length === 0 ? (
                  <div className="py-5 px-3 rounded-xl border border-bunker-800 bg-bunker-950/50 text-center font-mono text-xs text-bunker-muted">
                    Henüz kaydedilmiş doktor aksiyonu yok.
                  </div>
                ) : (
                  recentActions.slice(0, 20).map((item, idx) => {
                    const actBadge = formatActionBadge(item.action || item.cmd_action, item.pct);
                    const applied = isActionApplied(item);
                    const reasonText =
                      item.reason || item.detail || item.note || item.message || "—";
                    const tsVal = item.applied_ts ?? item.ts ?? item.time;
                    return (
                      <div
                        key={`${item.id ?? item.ticket ?? "act"}-${idx}`}
                        className="p-3 rounded-xl border border-bunker-800 bg-bunker-950/60 font-mono space-y-1.5"
                      >
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <div className="flex flex-wrap items-center gap-1.5 min-w-0">
                            {item.symbol ? (
                              <button
                                type="button"
                                onClick={() => setChartSymbol(item.symbol!)}
                                title={`${item.symbol} canlı grafiğini aç`}
                                className="font-bold text-xs text-white hover:text-cyan-300 hover:underline decoration-cyan-400/60 underline-offset-2 text-left transition-colors cursor-pointer"
                              >
                                {item.symbol}
                              </button>
                            ) : (
                              <span className="font-bold text-xs text-white">—</span>
                            )}
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
                          <span
                            className={`px-1.5 py-0.5 rounded border text-2xs font-bold shrink-0 ${
                              applied
                                ? "bg-emerald-500/15 border-emerald-500/40 text-emerald-300"
                                : "bg-amber-500/15 border-amber-500/40 text-amber-300"
                            }`}
                          >
                            {applied ? "Uygulandı" : "Öneri"}
                          </span>
                        </div>
                        <p className="text-2xs text-slate-300 leading-snug break-words">
                          {reasonText}
                        </p>
                        {tsVal != null && (
                          <div className="text-2xs text-bunker-muted tabular-nums pt-0.5 border-t border-bunker-800/60">
                            {applied ? "Uygulama zamanı:" : "Öneri zamanı:"}{" "}
                            <span className="text-slate-300 font-semibold">
                              {formatUtc3(tsVal)}
                            </span>
                          </div>
                        )}
                      </div>
                    );
                  })
                )}
              </div>
            </section>
          </div>
        </div>
      )}

      {chartSymbol && (
        <ForexChartModal
          symbol={chartSymbol}
          onClose={() => setChartSymbol(null)}
        />
      )}
    </div>
  );
}
