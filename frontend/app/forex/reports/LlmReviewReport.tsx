"use client";

import React, { useCallback, useState } from "react";
import { apiFetch } from "../../lib/api";
import { usePolling } from "../../lib/usePolling";
import { DirectionBadge } from "../../components/ui";

interface Stats {
  closed: number;
  wins?: number;
  tp?: number;
  sl?: number;
  net_pips?: number;
  win_rate?: number | null;
  would_win?: number;
  would_lose?: number;
  avoided_pips?: number;
  missed_pips?: number;
  correct_rate?: number | null;
}

interface Summary {
  days: number;
  total: number;
  approved: number;
  rejected: number;
  errors: number;
  blocked: number;
  tracking: number;
  approved_stats: Stats;
  rejected_stats: Stats;
  net_value_pips: number;
  avg_latency_ms: number;
  calibration: Record<string, { closed: number; wins: number; win_rate: number | null }>;
  by_symbol: Record<string, { approved: number; rejected: number; approved_net_pips: number; rejected_net_pips: number }>;
  calibration_deep?: {
    n: number; note?: string; brier?: number; brier_baseline?: number; brier_skill?: number | null; auc?: number | null; usable?: boolean; saturated?: boolean;
    reliability?: { bin: string; n: number; predicted: number; observed: number }[];
  };
  veto_value?: {
    llm: { vetoed_n: number; vetoed_mean_pips: number | null; passed_n: number; passed_mean_pips: number | null; edge_pips: number | null };
    random_control: { vetoed_n: number; vetoed_mean_pips: number | null; passed_n: number; passed_mean_pips: number | null; edge_pips: number | null };
    exploration: { n: number; mean_pips: number | null };
    verdict: string;
  };
  fail_stats?: { fail_count: number; fail_rate: number; fail_mean_pips: number | null; normal_mean_pips: number | null; alert: boolean; note: string };
}

interface Decision {
  id: number;
  created_at: number;
  symbol: string;
  direction: string;
  strategy_label?: string | null;
  score?: number | null;
  lots?: number | null;
  entry_price?: number | null;
  sl_pips?: number | null;
  tp_pips?: number | null;
  mode?: string | null;
  decision: string;
  confidence?: number | null;
  applied: string;
  summary?: string | null;
  reasons?: string[];
  risks?: string[];
  checks?: Record<string, string>;
  model?: string | null;
  latency_ms?: number | null;
  error?: string | null;
  repeat_count?: number | null;
  executed?: number | null;
  shadow_status?: string | null;
  shadow_pips?: number | null;
  mfe_pips?: number | null;
  mae_pips?: number | null;
  dossier?: string;
}

const APPLIED_TR: Record<string, string> = {
  allowed: "Onaylandı, açıldı",
  blocked: "Engellendi",
  advisory_allow: "Danışman: onay",
  advisory_reject: "Danışman: red (engellemedi)",
  reject_voided: "Red geçersiz sayıldı (yalnız habere dayanıyordu), motor açtı",
  explore_pass: "Kontrollü keşif: veto edilen işlem ölçüm için açıldı",
  fail_open: "LLM yok, motor açtı",
  fail_closed: "LLM yok, engellendi",
  hata: "Hata",
};
const SHADOW_TR: Record<string, string> = {
  TP: "Hedefe gitti",
  SL: "Stopa gitti",
  ZAMAN_ASIMI: "4 saatte kapandı",
  IZLENIYOR: "İzleniyor",
};

const fmtPips = (v?: number | null) => (v == null ? "—" : `${v > 0 ? "+" : ""}${v.toFixed(1)}`);
const pipTone = (v?: number | null) => (v == null || v === 0 ? "text-bunker-muted" : v > 0 ? "text-emerald-400" : "text-rose-400");
const fmtTime = (ts: number) =>
  new Date(ts * 1000).toLocaleString("tr-TR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit" });

function Kpi({ label, value, sub, tone = "text-white" }: { label: string; value: React.ReactNode; sub?: React.ReactNode; tone?: string }) {
  return (
    <div className="rounded-xl border border-bunker-800 bg-bunker-950/60 p-3">
      <p className="text-[10px] uppercase tracking-wider text-bunker-muted font-mono">{label}</p>
      <p className={`mt-1 text-xl font-black font-mono tabular-nums ${tone}`}>{value}</p>
      {sub && <p className="mt-0.5 text-[11px] text-bunker-muted">{sub}</p>}
    </div>
  );
}

function DecisionBadge({ d }: { d: Decision }) {
  const lowConf = d.decision === "APPROVE" && d.applied === "blocked";   // onay ama güven eşiğin altında
  const cls = lowConf
    ? "bg-amber-500/15 text-amber-300 border-amber-500/40"
    : d.decision === "APPROVE"
      ? "bg-emerald-500/15 text-emerald-300 border-emerald-500/40"
      : d.decision === "REJECT"
        ? "bg-rose-500/15 text-rose-300 border-rose-500/40"
        : "bg-amber-500/15 text-amber-300 border-amber-500/40";
  const label = lowConf ? "DÜŞÜK GÜVEN" : d.decision === "APPROVE" ? "ONAY" : d.decision === "REJECT" ? "RED" : "HATA";
  return <span className={`inline-flex rounded border px-2 py-0.5 text-[10px] font-bold font-mono ${cls}`}>{label}</span>;
}

/** Raporlar > LLM Kararları: işlem öncesi LLM incelemesinin kararları ve gölge sonuçları. */
export default function LlmReviewReport() {
  const [days, setDays] = useState(7);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [rows, setRows] = useState<Decision[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [openId, setOpenId] = useState<number | null>(null);
  const [detail, setDetail] = useState<Decision | null>(null);

  const load = useCallback(async () => {
    try {
      const [s, d] = await Promise.all([
        apiFetch(`/api/llm-review/summary?days=${days}`),
        apiFetch(`/api/llm-review/decisions?days=${days}&limit=200`),
      ]);
      setSummary(s as Summary);
      setRows(Array.isArray((d as { decisions?: Decision[] }).decisions) ? (d as { decisions: Decision[] }).decisions : []);
      setError("");
    } catch (e) {
      setError(e instanceof Error && e.message ? `Kararlar alınamadı: ${e.message}` : "Kararlar alınamadı");
    } finally {
      setLoading(false);
    }
  }, [days]);

  usePolling(load, 30_000);

  const toggle = async (id: number) => {
    if (openId === id) {
      setOpenId(null);
      setDetail(null);
      return;
    }
    setOpenId(id);
    setDetail(null);
    try {
      setDetail((await apiFetch(`/api/llm-review/decisions/${id}`)) as Decision);
    } catch {
      setDetail(null);
    }
  };

  const a = summary?.approved_stats;
  const r = summary?.rejected_stats;
  const btn = (n: number) =>
    `px-3 py-1.5 min-h-11 sm:min-h-0 rounded-lg border font-mono text-xs font-bold transition-all ${
      days === n ? "bg-cyan-500/20 border-cyan-400/60 text-cyan-200" : "bg-bunker-800/80 border-bunker-700 text-bunker-muted hover:text-white"
    }`;

  return (
    <section className="space-y-4" aria-label="LLM kararları raporu">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-sm font-bold text-white uppercase tracking-wider">LLM Trader Kararları</h2>
          <p className="mt-0.5 max-w-3xl text-xs text-bunker-muted">
            Motor her işlemi açmadan önce LLM&apos;e sorar. Her karar için fiyat izlenir: reddedilen işlem sonradan stopa gittiyse LLM haklıdır
            (kaçınılan zarar), hedefe gittiyse kaçırılan kazançtır. Sonuçlar tahmindir (trailing, kısmi kâr ve gerçek spread yok).
          </p>
        </div>
        <div className="flex items-center gap-2" role="group" aria-label="Dönem">
          {[1, 7, 30].map((n) => (
            <button key={n} type="button" className={btn(n)} aria-pressed={days === n} onClick={() => { setDays(n); setLoading(true); }}>
              {n === 1 ? "Bugün" : `Son ${n} gün`}
            </button>
          ))}
        </div>
      </div>

      {error && <div role="alert" className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">{error}</div>}

      {loading && !summary ? (
        <p className="py-10 text-center font-mono text-sm text-bunker-muted animate-pulse">Kararlar yükleniyor…</p>
      ) : summary && summary.total === 0 ? (
        <p className="rounded-xl border border-bunker-800 bg-bunker-900/70 py-10 text-center text-sm text-bunker-muted">
          Bu dönemde LLM incelemesi yok. Ayarlar &gt; Forex Otonom &gt; Genel Risk bölümünden LLM Trader İncelemesi&apos;nin açık olduğunu kontrol edin;
          motor yeni bir işlem açmaya hazırlandığında karar burada görünür.
        </p>
      ) : summary ? (
        <>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <Kpi label="Toplam karar" value={summary.total} sub={`${summary.approved} onay · ${summary.rejected} red · ${summary.errors} LLM yok/hata`} />
            <Kpi label="Engellenen işlem" value={summary.blocked} sub={`ortalama ${(summary.avg_latency_ms / 1000).toFixed(1)} sn düşündü`} tone="text-rose-300" />
            <Kpi
              label="LLM'in net katkısı"
              value={`${fmtPips(summary.net_value_pips)} pip`}
              tone={pipTone(summary.net_value_pips)}
              sub="reddedilenlerin kaçınılan zararı − kaçırılan kazancı"
            />
            <Kpi label="İzlenen (sonucu bekleyen)" value={summary.tracking} sub="fiyat TP/SL'e ya da 4 saate kadar izlenir" tone="text-cyan-300" />
          </div>

          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            <div className="rounded-xl border border-emerald-500/20 bg-bunker-950/60 p-3 space-y-1">
              <p className="text-xs font-bold text-emerald-300">Onaylanan işlemlerin sonucu (gölge)</p>
              {a && a.closed > 0 ? (
                <>
                  <p className="font-mono text-lg font-black text-white">
                    %{a.win_rate?.toFixed(0)} <span className="text-xs font-normal text-bunker-muted">isabet ({a.wins}/{a.closed})</span>
                  </p>
                  <p className="text-xs text-bunker-muted">
                    {a.tp} hedefe, {a.sl} stopa gitti · toplam <span className={pipTone(a.net_pips)}>{fmtPips(a.net_pips)} pip</span>
                  </p>
                </>
              ) : (
                <p className="text-xs text-bunker-muted">Henüz sonuçlanan onay yok.</p>
              )}
            </div>
            <div className="rounded-xl border border-rose-500/20 bg-bunker-950/60 p-3 space-y-1">
              <p className="text-xs font-bold text-rose-300">Reddedilen işlemler: LLM haklı mıydı?</p>
              {r && r.closed > 0 ? (
                <>
                  <p className="font-mono text-lg font-black text-white">
                    %{r.correct_rate?.toFixed(0)} <span className="text-xs font-normal text-bunker-muted">haklı ({r.would_lose}/{r.closed})</span>
                  </p>
                  <p className="text-xs text-bunker-muted">
                    Kaçınılan zarar <span className="text-emerald-400">{fmtPips(r.avoided_pips)} pip</span> · kaçırılan kazanç{" "}
                    <span className="text-rose-400">{fmtPips(-(r.missed_pips ?? 0))} pip</span>
                  </p>
                </>
              ) : (
                <p className="text-xs text-bunker-muted">Henüz sonuçlanan red yok.</p>
              )}
            </div>
          </div>

          {Object.keys(summary.calibration).length > 0 && (
            <div className="rounded-xl border border-bunker-800 bg-bunker-950/60 p-3">
              <p className="mb-2 text-xs font-bold text-white">Güven puanı işe yarıyor mu? (onaylanan işlemlerin isabeti)</p>
              <div className="flex flex-wrap gap-3 font-mono text-xs">
                {["80+", "60-79", "<60", "bilinmiyor"].filter((k) => summary.calibration[k]).map((k) => (
                  <div key={k} className="rounded-lg border border-bunker-800 px-3 py-2">
                    <span className="text-bunker-muted">Güven {k}:</span>{" "}
                    <span className="font-bold text-white">%{summary.calibration[k].win_rate?.toFixed(0) ?? "—"}</span>{" "}
                    <span className="text-bunker-muted">({summary.calibration[k].wins}/{summary.calibration[k].closed})</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {summary.veto_value && (
            <div className="rounded-xl border border-bunker-800 bg-bunker-950/60 p-3 space-y-1">
              <p className="text-xs font-bold text-white">LLM vetosu rastgele vetodan iyi mi?</p>
              <p className="text-xs text-slate-300">{summary.veto_value.verdict}</p>
              <p className="font-mono text-[11px] text-bunker-muted">
                LLM: geçenler {fmtPips(summary.veto_value.llm.passed_mean_pips)} pip (n={summary.veto_value.llm.passed_n}) − veto edilenler {fmtPips(summary.veto_value.llm.vetoed_mean_pips)} pip (n={summary.veto_value.llm.vetoed_n}) = fark {fmtPips(summary.veto_value.llm.edge_pips)}
                {" · "}Rastgele kontrol farkı {fmtPips(summary.veto_value.random_control.edge_pips)}
                {" · "}Kontrollü keşif: {summary.veto_value.exploration.n} işlem, ort. {fmtPips(summary.veto_value.exploration.mean_pips)} pip
              </p>
            </div>
          )}

          {summary.calibration_deep && (
            <div className="rounded-xl border border-bunker-800 bg-bunker-950/60 p-3 space-y-1">
              <p className="text-xs font-bold text-white">Güven puanı kalibrasyonu (Brier / AUC)</p>
              <p className={`text-xs ${summary.calibration_deep.usable ? "text-emerald-300" : "text-amber-300"}`}>{summary.calibration_deep.note}</p>
              {summary.calibration_deep.brier != null && (
                <p className="font-mono text-[11px] text-bunker-muted">
                  n={summary.calibration_deep.n} · Brier {summary.calibration_deep.brier} (taban {summary.calibration_deep.brier_baseline}) · skill {summary.calibration_deep.brier_skill ?? "—"} · AUC {summary.calibration_deep.auc ?? "—"}
                </p>
              )}
              {summary.calibration_deep.reliability && summary.calibration_deep.reliability.length > 0 && (
                <div className="flex flex-wrap gap-2 font-mono text-[11px]">
                  {summary.calibration_deep.reliability.map((b) => (
                    <span key={b.bin} className="rounded border border-bunker-700 px-2 py-1 text-bunker-muted">
                      {b.bin}: öngörülen %{(b.predicted * 100).toFixed(0)} / gerçekleşen %{(b.observed * 100).toFixed(0)} (n={b.n})
                    </span>
                  ))}
                </div>
              )}
            </div>
          )}

          {summary.fail_stats && summary.fail_stats.fail_count > 0 && (
            <div className={`rounded-xl border p-3 text-xs ${summary.fail_stats.alert ? "border-rose-500/40 bg-rose-500/10 text-rose-200" : "border-bunker-800 bg-bunker-950/60 text-slate-300"}`}>
              <p className="font-bold">LLM hata / zaman aşımı: {summary.fail_stats.fail_count} karar (%{(summary.fail_stats.fail_rate * 100).toFixed(0)})</p>
              <p>{summary.fail_stats.note}. Bu işlemlerin ort. gölge sonucu {fmtPips(summary.fail_stats.fail_mean_pips)} pip, normal kararlarınki {fmtPips(summary.fail_stats.normal_mean_pips)} pip (fail-open yanlılığı ölçümü).</p>
            </div>
          )}

          {Object.keys(summary.by_symbol).length > 0 && (
            <div className="overflow-x-auto rounded-xl border border-bunker-800 bg-bunker-950/60">
              <table className="w-full text-xs font-mono tabular-nums">
                <thead>
                  <tr className="text-[10px] uppercase tracking-wider text-bunker-muted">
                    <th scope="col" className="px-3 py-2 text-left font-medium">Sembol</th>
                    <th scope="col" className="px-3 py-2 text-right font-medium">Onay</th>
                    <th scope="col" className="px-3 py-2 text-right font-medium">Onaylananın pip</th>
                    <th scope="col" className="px-3 py-2 text-right font-medium">Red</th>
                    <th scope="col" className="px-3 py-2 text-right font-medium">Reddedilenin pip</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(summary.by_symbol).map(([sym, v]) => (
                    <tr key={sym} className="border-t border-bunker-800/70">
                      <td className="px-3 py-2 font-bold text-white">{sym}</td>
                      <td className="px-3 py-2 text-right">{v.approved}</td>
                      <td className={`px-3 py-2 text-right ${pipTone(v.approved_net_pips)}`}>{fmtPips(v.approved_net_pips)}</td>
                      <td className="px-3 py-2 text-right">{v.rejected}</td>
                      <td className={`px-3 py-2 text-right ${pipTone(v.rejected_net_pips)}`}>{fmtPips(v.rejected_net_pips)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <div className="overflow-hidden rounded-xl border border-bunker-800 bg-bunker-900/70">
            <div className="border-b border-bunker-800 p-3 text-xs font-bold uppercase tracking-wider text-white">Karar geçmişi ({rows.length})</div>
            <ul className="divide-y divide-bunker-800/70">
              {rows.map((d) => (
                <li key={d.id}>
                  <button
                    type="button"
                    onClick={() => void toggle(d.id)}
                    aria-expanded={openId === d.id}
                    className="grid w-full grid-cols-[auto_1fr_auto] items-center gap-x-3 gap-y-1 px-3 py-2.5 text-left hover:bg-bunker-800/40 sm:grid-cols-[7.5rem_9rem_5rem_1fr_9rem]"
                  >
                    <span className="font-mono text-[11px] text-bunker-muted">{fmtTime(d.created_at)}</span>
                    <span className="flex items-center gap-2 font-mono text-xs font-bold text-white">
                      {d.symbol} <DirectionBadge direction={d.direction} />
                    </span>
                    <span className="flex items-center gap-1.5">
                      <DecisionBadge d={d} />
                      <span className="font-mono text-[11px] text-bunker-muted">{d.confidence != null ? `%${d.confidence}` : ""}</span>
                    </span>
                    <span className="col-span-3 min-w-0 truncate text-xs text-slate-300 sm:col-span-1">{d.summary || APPLIED_TR[d.applied] || d.applied}</span>
                    <span className="col-span-3 text-right font-mono text-[11px] sm:col-span-1">
                      <span className="text-bunker-muted">{SHADOW_TR[d.shadow_status ?? ""] ?? d.shadow_status ?? "—"}</span>{" "}
                      <span className={pipTone(d.shadow_pips)}>{d.shadow_status === "IZLENIYOR" && d.shadow_pips == null ? "" : fmtPips(d.shadow_pips)}</span>
                    </span>
                  </button>
                  {openId === d.id && (
                    <div className="space-y-2 bg-black/20 px-4 py-3 text-xs">
                      <p className="text-bunker-muted">
                        {APPLIED_TR[d.applied] ?? d.applied} · {d.strategy_label || "strateji —"} · {d.lots ?? "—"} lot · giriş {d.entry_price ?? "—"} · SL {d.sl_pips ?? "—"} / TP{" "}
                        {d.tp_pips ?? "—"} pip · {d.latency_ms ? `${(d.latency_ms / 1000).toFixed(1)} sn` : ""} {d.model ? `· ${d.model}` : ""}
                        {d.repeat_count ? ` · aynı karar ${d.repeat_count} kez yeniden kullanıldı` : ""}
                      </p>
                      {d.error && <p className="text-amber-300">LLM hatası: {d.error}</p>}
                      {d.reasons && d.reasons.length > 0 && (
                        <div>
                          <p className="font-bold text-white">Gerekçeler</p>
                          <ul className="list-disc pl-5 text-slate-300">{d.reasons.map((x, i) => <li key={i}>{x}</li>)}</ul>
                        </div>
                      )}
                      {d.risks && d.risks.length > 0 && (
                        <div>
                          <p className="font-bold text-amber-300">Riskler</p>
                          <ul className="list-disc pl-5 text-slate-300">{d.risks.map((x, i) => <li key={i}>{x}</li>)}</ul>
                        </div>
                      )}
                      {d.checks && Object.keys(d.checks).length > 0 && (
                        <p className="flex flex-wrap gap-2">
                          {Object.entries(d.checks).map(([k, v]) => (
                            <span key={k} className={`rounded border px-2 py-0.5 font-mono text-[10px] ${v === "olumlu" ? "border-emerald-500/40 text-emerald-300" : v === "olumsuz" ? "border-rose-500/40 text-rose-300" : "border-bunker-700 text-bunker-muted"}`}>
                              {k}: {v}
                            </span>
                          ))}
                        </p>
                      )}
                      {(d.mfe_pips != null || d.mae_pips != null) && (
                        <p className="font-mono text-bunker-muted">
                          Fiyat yolu: en iyi <span className="text-emerald-400">{fmtPips(d.mfe_pips)}</span> · en kötü <span className="text-rose-400">{fmtPips(d.mae_pips)}</span> pip
                        </p>
                      )}
                      {detail?.id === d.id && detail.dossier && (
                        <details className="rounded border border-bunker-800">
                          <summary className="cursor-pointer px-2 py-1 font-mono text-[11px] text-cyan-300">LLM&apos;e verilen veri (dosya)</summary>
                          <pre className="max-h-72 overflow-auto whitespace-pre-wrap break-words p-2 font-mono text-[10px] text-bunker-muted">{detail.dossier}</pre>
                        </details>
                      )}
                    </div>
                  )}
                </li>
              ))}
            </ul>
          </div>
        </>
      ) : null}
    </section>
  );
}
