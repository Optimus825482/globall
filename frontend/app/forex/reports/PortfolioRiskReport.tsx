"use client";

import React, { useCallback, useState } from "react";
import { apiFetch } from "../../lib/api";
import { usePolling } from "../../lib/usePolling";

interface Snapshot {
  connected: boolean;
  account: { balance?: number; equity?: number; margin?: number; free_margin?: number; leverage?: number; server?: string };
  open_positions: number;
  exposure: { legs: Record<string, number>; usd_net: number; gross: number; missing_prices: string[] };
  heat: { heat_usd: number; heat_pct: number; usd_net_risk_pct: number; by_symbol: Record<string, number>; by_currency: Record<string, number>; no_sl_tickets: unknown[] };
  drawdown: { dd_pct: number; daily_pct: number; weekly_pct: number; level: number; mult: number; kill: boolean; daily_breach: boolean; weekly_breach: boolean };
  risk_budget_remaining_pct: number;
  risk_budget_remaining_usd: number;
  peak_equity: number;
  gate: { mode: string; kill_switch: boolean; limits: Record<string, number> };
}
interface GateSummary { entries_logged: number; would_block: number; blocked_enforced: number; size_reduced: number; by_reason: Record<string, number>; by_symbol: Record<string, number> }
interface GateEntry { id: number; ts: number; symbol: string; direction: string; lots: number; mult: number; decision: string; mode: string; enforced: number; reasons: { code: string; text: string }[] }
interface Excursion {
  n_closed: number; n_open: number; winners: number; losers: number; winner_mae_p80_pips: number | null; winner_mae_median_pips: number | null;
  loser_mfe_median_pips: number | null; winner_minutes_to_mfe_median: number | null; suggested_time_stop_minutes: number | null;
  edge_ratio: number | null; sample_note: string; hint: string;
}
interface SupEvent { id: number; ts: number; ticket: number; symbol: string; kind: string; detail: string; action: string; mode: string }
interface StressRow { label: string; pnl_usd: number; pnl_pct: number; margin_level_after_pct: number | null; worst_position: string | null; breach: boolean }
interface MonteCarlo { n: number; ok: boolean; note?: string; risk_pct?: number; dd_p50?: number; dd_p90?: number; dd_p95?: number; dd_p99?: number; p_dd_over_limit?: number; dd_limit_pct?: number; mean_r?: number }
interface Proposal { ticket: number; symbol?: string; action: string; pct?: number | null; reason?: string; ok?: boolean }

const MODE_TR: Record<string, string> = { off: "Kapalı", shadow: "Gölge (yalnız günlük)", enforce: "Uygulanıyor", log: "Öneri günlüğü", act: "Komut veriyor" };
const KIND_TR: Record<string, string> = { event_risk: "Olay riski", weekend_risk: "Hafta sonu riski", no_sl: "Stop yok", llm_proposal: "LLM önerisi" };
const money = (v?: number | null) => (v == null ? "—" : `$${v.toLocaleString("tr-TR", { maximumFractionDigits: 0 })}`);
const pct = (v?: number | null, d = 1) => (v == null ? "—" : `%${v.toFixed(d)}`);
const fmtTime = (ts: number) => new Date(ts * 1000).toLocaleString("tr-TR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });

function Kpi({ label, value, sub, tone = "text-white" }: { label: string; value: React.ReactNode; sub?: React.ReactNode; tone?: string }) {
  return (
    <div className="rounded-xl border border-bunker-800 bg-bunker-950/60 p-3">
      <p className="text-[10px] uppercase tracking-wider text-bunker-muted font-mono">{label}</p>
      <p className={`mt-1 text-xl font-black font-mono tabular-nums ${tone}`}>{value}</p>
      {sub && <p className="mt-0.5 text-[11px] text-bunker-muted">{sub}</p>}
    </div>
  );
}

/** Raporlar > Portföy & Risk: maruziyet, ısı, drawdown, risk kapısı günlüğü, pozisyon gözetimi, MAE/MFE ve LLM pozisyon önerisi. */
export default function PortfolioRiskReport() {
  const [snap, setSnap] = useState<Snapshot | null>(null);
  const [gate, setGate] = useState<{ summary: GateSummary; entries: GateEntry[] } | null>(null);
  const [exc, setExc] = useState<Excursion | null>(null);
  const [events, setEvents] = useState<SupEvent[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [proposals, setProposals] = useState<{ proposals: Proposal[]; rejected: Proposal[]; note?: string } | null>(null);
  const [asking, setAsking] = useState(false);
  const [stress, setStress] = useState<Record<string, StressRow> | null>(null);
  const [mc, setMc] = useState<MonteCarlo | null>(null);

  const load = useCallback(async () => {
    try {
      const [s, g, e, l, st, m] = await Promise.all([
        apiFetch("/api/portfolio/risk"),
        apiFetch("/api/portfolio/gate-log?days=7"),
        apiFetch("/api/positions/excursions?days=30"),
        apiFetch("/api/positions/supervisor-log?days=7"),
        apiFetch("/api/portfolio/stress"),
        apiFetch("/api/portfolio/montecarlo?days=90&risk_pct=1"),
      ]);
      setStress((st as { scenarios: Record<string, StressRow> }).scenarios);
      setMc(m as MonteCarlo);
      setSnap(s as Snapshot);
      setGate(g as { summary: GateSummary; entries: GateEntry[] });
      setExc((e as { stats: Excursion }).stats);
      setEvents(((l as { events?: SupEvent[] }).events) ?? []);
      setError("");
    } catch (err) {
      setError(err instanceof Error && err.message ? `Risk verisi alınamadı: ${err.message}` : "Risk verisi alınamadı");
    } finally {
      setLoading(false);
    }
  }, []);
  usePolling(load, 20_000);

  const askLlm = async () => {
    setAsking(true);
    setProposals(null);
    try {
      setProposals((await apiFetch("/api/positions/llm-review", { method: "POST" })) as { proposals: Proposal[]; rejected: Proposal[]; note?: string });
    } catch (err) {
      setError(err instanceof Error && err.message ? `LLM önerisi alınamadı: ${err.message}` : "LLM önerisi alınamadı");
    } finally {
      setAsking(false);
    }
  };

  const dd = snap?.drawdown;
  const ddTone = !dd ? "text-white" : dd.kill ? "text-rose-400" : dd.level > 0 ? "text-amber-300" : "text-emerald-400";
  const card = "rounded-xl border border-bunker-800 bg-bunker-950/60 p-3";
  const th = "px-3 py-2 text-left font-medium text-[10px] uppercase tracking-wider text-bunker-muted";

  return (
    <section className="space-y-4" aria-label="Portföy ve risk raporu">
      <div>
        <h2 className="text-sm font-bold text-white uppercase tracking-wider">Portföy &amp; Risk</h2>
        <p className="mt-0.5 max-w-3xl text-xs text-bunker-muted">
          LLM&apos;den bağımsız deterministik risk katmanı. Varsayılan mod <b>gölge</b>: kapı yalnızca &quot;engellerdi&quot; diye günlüğe yazar, motoru değiştirmez.
          Eşikler araştırmada kaynaksız başlangıç değerleridir; önce gölgede kalibre edin, sonra Ayarlar &gt; Genel Risk&apos;ten &quot;Uygulanıyor&quot;a alın.
        </p>
      </div>
      {error && <div role="alert" className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">{error}</div>}
      {loading && !snap ? (
        <p className="py-10 text-center font-mono text-sm text-bunker-muted animate-pulse">Yükleniyor…</p>
      ) : snap ? (
        <>
          {!snap.connected && (
            <p className="rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
              MT5 köprüsü bağlı değil: hesap ve pozisyon verisi boş görünür.
            </p>
          )}
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <Kpi label="Özsermaye" value={money(snap.account.equity)} sub={`${snap.open_positions} açık pozisyon · tepe ${money(snap.peak_equity)}`} />
            <Kpi label="Tepeden düşüş" value={pct(dd?.dd_pct)} tone={ddTone}
                 sub={dd?.kill ? "KILL eşiği aşıldı" : dd && dd.level > 0 ? `Kademe ${dd.level}: lot ×${dd.mult}` : "Normal"} />
            <Kpi label="Günlük / haftalık" value={`${pct(dd?.daily_pct)} / ${pct(dd?.weekly_pct)}`}
                 tone={dd?.daily_breach || dd?.weekly_breach ? "text-rose-400" : "text-white"} sub="gün/hafta başına göre özsermaye değişimi" />
            <Kpi label="Portföy ısısı" value={pct(snap.heat.heat_pct)} sub={`kalan bütçe ${pct(snap.risk_budget_remaining_pct)} (${money(snap.risk_budget_remaining_usd)})`}
                 tone={snap.heat.heat_pct > (snap.gate.limits.heat_limit_pct ?? 6) ? "text-rose-400" : "text-white"} />
          </div>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            <div className={card}>
              <p className="mb-2 text-xs font-bold text-white">Net para birimi maruziyeti (USD notional)</p>
              {Object.keys(snap.exposure.legs).length === 0 ? (
                <p className="text-xs text-bunker-muted">Açık pozisyon yok.</p>
              ) : (
                <ul className="space-y-1 font-mono text-xs">
                  {Object.entries(snap.exposure.legs).map(([ccy, v]) => (
                    <li key={ccy} className="flex justify-between">
                      <span className="text-bunker-muted">{ccy}</span>
                      <span className={v > 0 ? "text-emerald-400" : "text-rose-400"}>{v > 0 ? "uzun " : "kısa "}{money(Math.abs(v))}</span>
                    </li>
                  ))}
                </ul>
              )}
              <p className="mt-2 text-[11px] text-bunker-muted">
                Net USD riski {pct(snap.heat.usd_net_risk_pct)} (limit {pct(snap.gate.limits.usd_net_limit_pct, 0)}).
                {snap.exposure.missing_prices.length > 0 && ` Fiyatı eksik: ${snap.exposure.missing_prices.join(", ")}.`}
              </p>
              {snap.heat.no_sl_tickets.length > 0 && (
                <p className="mt-1 text-[11px] text-rose-300">{snap.heat.no_sl_tickets.length} pozisyonda stop yok: sınırsız risk.</p>
              )}
            </div>
            <div className={card}>
              <p className="mb-2 text-xs font-bold text-white">Risk kapısı</p>
              <p className="text-xs text-slate-300">
                Mod: <b>{MODE_TR[snap.gate.mode] ?? snap.gate.mode}</b>{snap.gate.kill_switch && <span className="ml-2 rounded bg-rose-500/20 px-1.5 py-0.5 text-rose-300">KILL SWITCH AÇIK</span>}
              </p>
              {gate && (
                <p className="mt-1 text-xs text-slate-300">
                  Son 7 gün: <b>{gate.summary.would_block}</b> işlem &quot;engellerdi&quot;, <b>{gate.summary.blocked_enforced}</b> gerçekten engellendi,{" "}
                  <b>{gate.summary.size_reduced}</b> lot küçültme.
                </p>
              )}
              {gate && Object.keys(gate.summary.by_reason).length > 0 && (
                <ul className="mt-2 flex flex-wrap gap-2 font-mono text-[11px]">
                  {Object.entries(gate.summary.by_reason).map(([k, v]) => (
                    <li key={k} className="rounded border border-bunker-700 px-2 py-0.5 text-bunker-muted">{k}: <span className="text-white">{v}</span></li>
                  ))}
                </ul>
              )}
              <p className="mt-2 text-[11px] text-bunker-muted">
                Limitler: ısı {pct(snap.gate.limits.heat_limit_pct, 0)} · günlük −{pct(snap.gate.limits.daily_loss_pct, 0)} · haftalık −{pct(snap.gate.limits.weekly_loss_pct, 0)} · kill {pct(snap.gate.limits.kill_dd_pct, 0)} ·
                maliyet ≤ {snap.gate.limits.cost_r_max}R
              </p>
            </div>
          </div>

          {stress && (
            <div className="overflow-x-auto rounded-xl border border-bunker-800 bg-bunker-950/60">
              <p className="border-b border-bunker-800 p-3 text-xs font-bold text-white">Stres senaryoları (anlık şok, açık pozisyonlara)</p>
              <table className="w-full text-xs font-mono">
                <thead><tr><th className={th}>Senaryo</th><th className={th}>Zarar</th><th className={th}>% özsermaye</th><th className={th}>Marj sonrası</th><th className={th}>En kötü</th></tr></thead>
                <tbody>
                  {Object.entries(stress).map(([k, r]) => (
                    <tr key={k} className="border-t border-bunker-800/70">
                      <td className="px-3 py-2 text-slate-300">{r.label}</td>
                      <td className={`px-3 py-2 ${r.pnl_usd < 0 ? "text-rose-300" : "text-emerald-300"}`}>{money(r.pnl_usd)}</td>
                      <td className={`px-3 py-2 ${r.breach ? "text-rose-400 font-bold" : "text-white"}`}>{pct(r.pnl_pct)}{r.breach ? " · LİMİT AŞILDI" : ""}</td>
                      <td className="px-3 py-2 text-bunker-muted">{r.margin_level_after_pct == null ? "—" : `%${r.margin_level_after_pct.toFixed(0)}`}</td>
                      <td className="px-3 py-2 text-bunker-muted">{r.worst_position ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="p-3 text-[11px] text-bunker-muted">Şok büyüklükleri ve eşikler (−%5 özsermaye, marj %300) tasarım örneğidir; brokerınızın stop-out seviyesini doğrulayın.</p>
            </div>
          )}

          {mc && (
            <div className={card}>
              <p className="mb-1 text-xs font-bold text-white">Monte Carlo: işlem sırası belirsizliği (blok bootstrap, %{mc.risk_pct ?? 1} risk)</p>
              {mc.ok ? (
                <p className="text-xs text-slate-300">
                  {mc.n} işlem · ort. {mc.mean_r}R · beklenen maks. düşüş: medyan %{mc.dd_p50} · %90 → %{mc.dd_p90} · %95 → %{mc.dd_p95} · %99 → %{mc.dd_p99} ·
                  %{mc.dd_limit_pct} düşüşü aşma olasılığı %{((mc.p_dd_over_limit ?? 0) * 100).toFixed(0)}
                </p>
              ) : (
                <p className="text-xs text-bunker-muted">{mc.note} (şu an {mc.n} işlem)</p>
              )}
            </div>
          )}

          {gate && gate.entries.length > 0 && (
            <div className="overflow-x-auto rounded-xl border border-bunker-800 bg-bunker-950/60">
              <p className="border-b border-bunker-800 p-3 text-xs font-bold text-white">Kapının son kararları</p>
              <table className="w-full text-xs font-mono">
                <thead><tr><th className={th}>Zaman</th><th className={th}>Sembol</th><th className={th}>Karar</th><th className={th}>Sebep</th></tr></thead>
                <tbody>
                  {gate.entries.slice(0, 12).map((e) => (
                    <tr key={e.id} className="border-t border-bunker-800/70">
                      <td className="px-3 py-2 text-bunker-muted">{fmtTime(e.ts)}</td>
                      <td className="px-3 py-2 text-white">{e.symbol} {e.direction}</td>
                      <td className={`px-3 py-2 ${e.decision === "block" ? "text-rose-300" : "text-amber-300"}`}>
                        {e.decision === "block" ? (e.enforced ? "Engellendi" : "Engellerdi") : `Lot ×${e.mult}`}
                      </td>
                      <td className="px-3 py-2 text-slate-300">{e.reasons.map((r) => r.text).join("; ") || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <div className={card}>
            <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
              <p className="text-xs font-bold text-white">MAE / MFE: stop ve zaman-stopu kalibrasyonu</p>
              <button type="button" onClick={() => void askLlm()} disabled={asking}
                      className="min-h-11 sm:min-h-0 rounded-lg border border-cyan-400/50 bg-cyan-500/10 px-3 py-1.5 text-xs font-bold text-cyan-200 hover:bg-cyan-500/20 disabled:opacity-50">
                {asking ? "LLM düşünüyor…" : "LLM'den pozisyon önerisi iste"}
              </button>
            </div>
            {exc && exc.n_closed > 0 ? (
              <ul className="space-y-1 text-xs text-slate-300">
                <li>{exc.n_closed} kapanmış pozisyon ({exc.winners} kazanan, {exc.losers} kaybeden) · {exc.sample_note}</li>
                <li>Kazananların MAE 80. yüzdeliği: <b>{exc.winner_mae_p80_pips ?? "—"} pip</b> (stop adayı) · medyan {exc.winner_mae_median_pips ?? "—"} pip</li>
                <li>Kazananların medyan MFE süresi: <b>{exc.winner_minutes_to_mfe_median?.toFixed(0) ?? "—"} dk</b> → zaman-stopu adayı {exc.suggested_time_stop_minutes ?? "—"} dk</li>
                <li>Kaybedenlerin medyan MFE&apos;si: {exc.loser_mfe_median_pips ?? "—"} pip · edge oranı {exc.edge_ratio ?? "—"}</li>
              </ul>
            ) : (
              <p className="text-xs text-bunker-muted">Henüz kapanmış, örneklenmiş pozisyon yok. Gözetim açık pozisyonları 30 sn&apos;de bir örnekler.</p>
            )}
            {exc && <p className="mt-1 text-[11px] text-bunker-muted">{exc.hint}</p>}
            {proposals && (
              <div className="mt-3 space-y-1 rounded-lg border border-bunker-800 bg-black/20 p-3 text-xs">
                <p className="font-bold text-cyan-200">LLM önerileri (UYGULANMAZ)</p>
                {proposals.proposals.length === 0 && proposals.rejected.length === 0 && <p className="text-bunker-muted">{proposals.note ?? "Öneri yok."}</p>}
                {proposals.proposals.map((p) => (
                  <p key={p.ticket} className="text-slate-300"><span className="font-mono text-white">#{p.ticket} {p.symbol}</span> → {p.action}{p.pct ? ` %${p.pct}` : ""}: {p.reason}</p>
                ))}
                {proposals.rejected.map((p) => (
                  <p key={`r${p.ticket}`} className="text-amber-300"><span className="font-mono">#{p.ticket}</span> reddedildi ({p.action}): {p.reason}</p>
                ))}
              </div>
            )}
          </div>

          <div className="overflow-hidden rounded-xl border border-bunker-800 bg-bunker-950/60">
            <p className="border-b border-bunker-800 p-3 text-xs font-bold text-white">Pozisyon gözetimi olayları (son 7 gün)</p>
            {events.length === 0 ? (
              <p className="p-3 text-xs text-bunker-muted">Olay yok. Gözetim: yüksek etkili veri öncesi, hafta sonu kapanışı öncesi ve stopsuz pozisyonlar için çalışır.</p>
            ) : (
              <ul className="divide-y divide-bunker-800/70">
                {events.slice(0, 20).map((e) => (
                  <li key={e.id} className="grid grid-cols-[7rem_1fr] gap-x-3 px-3 py-2 text-xs sm:grid-cols-[7rem_8rem_1fr_7rem]">
                    <span className="font-mono text-bunker-muted">{fmtTime(e.ts)}</span>
                    <span className="font-mono text-white">{e.symbol} #{e.ticket}</span>
                    <span className="col-span-2 text-slate-300 sm:col-span-1"><b>{KIND_TR[e.kind] ?? e.kind}:</b> {e.detail}</span>
                    <span className="col-span-2 text-right font-mono text-[11px] text-bunker-muted sm:col-span-1">{e.action} · {MODE_TR[e.mode] ?? e.mode}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </>
      ) : null}
    </section>
  );
}
