"use client";

import { useCallback, useState } from "react";
import { apiFetch } from "../../lib/api";
import { usePolling } from "../../lib/usePolling";

/**
 * Raporlar > Gölge Modlar (2026-11-09).
 *
 * Sistemde kararı DEĞİŞTİRMEDEN ölçüm yapan mekanizmalar tek ekranda:
 * LLM karar gölgesi, ML kalibrasyonu, geometri gölgesi, portföy risk kapısı,
 * kanıt kapısı (Wilson). Her satır: mod, örnek ilerlemesi (n/needed), ne ölçtüğü
 * ve notu. Hiçbir sayı uydurulmaz — veri yoksa `—` görünür.
 */

interface ShadowItem {
  key: string; label: string; mode: string; active: boolean; measures: string;
  n: number | null; needed: number | null; ready: boolean;
  progress_pct: number | null; metric: string | null; note: string;
  detail_endpoint: string | null;
}
interface ShadowReport {
  generated_at: number; count: number; active_shadow: number;
  ready_for_decision: number; items: ShadowItem[]; note: string; error?: string;
}

const MODE_TR: Record<string, { t: string; c: string }> = {
  on: { t: "AÇIK", c: "border-emerald-500/40 bg-emerald-500/10 text-emerald-300" },
  shadow: { t: "GÖLGE", c: "border-cyan-500/40 bg-cyan-500/10 text-cyan-200" },
  enforce: { t: "ENFORCE (karar değişir)", c: "border-amber-500/40 bg-amber-500/10 text-amber-200" },
  off: { t: "KAPALI", c: "border-bunker-700 bg-bunker-800/60 text-bunker-muted" },
  unknown: { t: "BİLİNMİYOR", c: "border-rose-500/40 bg-rose-500/10 text-rose-300" },
};

export default function ShadowModesReport() {
  const [report, setReport] = useState<ShadowReport | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      setReport((await apiFetch("/api/reports/shadow-summary")) as ShadowReport);
      setError("");
    } catch (e) {
      setError(e instanceof Error && e.message ? `Gölge raporu alınamadı: ${e.message}` : "Gölge raporu alınamadı");
    }
  }, []);
  usePolling(load, 60_000);

  return (
    <section className="space-y-4" aria-label="Gölge modlar raporu">
      <div>
        <h2 className="text-sm font-bold text-white uppercase tracking-wider">Gölge Modlar</h2>
        <p className="mt-0.5 max-w-3xl text-xs text-bunker-muted">
          <b className="text-white">Gölge = kararı DEĞİŞTİRMEZ</b>, yalnız ölçer. Her satır bir mekanizmanın
          kaç örnek topladığını ve karar eşiğine ne kadar yaklaştığını gösterir. <b className="text-amber-200">ENFORCE</b>{" "}
          yazan bir kapı kararı gerçekten değiştirir; <b className="text-cyan-200">GÖLGE</b> yalnız “engellerdi” diye loglar.
        </p>
      </div>

      {error && <p role="alert" className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">{error}</p>}

      {report && (
        <div className="grid gap-3 sm:grid-cols-3">
          <div className="rounded-xl border border-bunker-800 bg-bunker-900/60 p-3">
            <p className="font-mono text-2xs uppercase tracking-wide text-bunker-muted">İzlenen mekanizma</p>
            <p className="mt-1 font-mono text-lg font-bold text-white">{report.count ?? "—"}</p>
          </div>
          <div className="rounded-xl border border-bunker-800 bg-bunker-900/60 p-3">
            <p className="font-mono text-2xs uppercase tracking-wide text-bunker-muted">Aktif gölge</p>
            <p className="mt-1 font-mono text-lg font-bold text-cyan-200">{report.active_shadow ?? "—"}</p>
          </div>
          <div className="rounded-xl border border-bunker-800 bg-bunker-900/60 p-3">
            <p className="font-mono text-2xs uppercase tracking-wide text-bunker-muted">Karara hazır</p>
            <p className={`mt-1 font-mono text-lg font-bold ${report.ready_for_decision ? "text-emerald-300" : "text-white"}`}>
              {report.ready_for_decision ?? 0}
            </p>
          </div>
        </div>
      )}

      <div className="space-y-2">
        {(report?.items || []).map((it) => {
          const mode = MODE_TR[it.mode] || MODE_TR.unknown;
          const pct = it.progress_pct;
          return (
            <div key={it.key} className="rounded-xl border border-bunker-800 bg-bunker-900/60 p-3">
              <div className="flex flex-wrap items-center gap-2">
                <span className={`rounded border px-2 py-0.5 font-mono text-2xs font-bold ${mode.c}`}>{mode.t}</span>
                <h3 className="text-xs font-bold text-white">{it.label}</h3>
                {it.ready && (
                  <span className="rounded border border-emerald-500/40 bg-emerald-500/10 px-2 py-0.5 font-mono text-2xs font-bold text-emerald-300">
                    KARAR EŞİĞİ DOLDU
                  </span>
                )}
                <span className="ml-auto font-mono text-2xs text-bunker-muted">
                  {it.needed != null ? `${it.n ?? 0} / ${it.needed} örnek` : it.metric || "—"}
                </span>
              </div>
              <p className="mt-1.5 text-2xs text-bunker-muted">{it.measures}</p>
              {pct != null && (
                <div className="mt-2 h-1.5 w-full overflow-hidden rounded bg-bunker-800" role="progressbar"
                  aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(pct)}>
                  <div className={`h-full ${it.ready ? "bg-emerald-400" : "bg-cyan-400/70"}`} style={{ width: `${Math.max(2, pct)}%` }} />
                </div>
              )}
              {it.note && <p className="mt-1.5 text-2xs text-bunker-muted/80">{it.note}</p>}
              {it.detail_endpoint && (
                <p className="mt-1 font-mono text-2xs text-cyan-300/70">detay: {it.detail_endpoint}</p>
              )}
            </div>
          );
        })}
      </div>

      {report?.note && <p className="text-2xs text-bunker-muted/80">{report.note}</p>}
      {report?.error && <p role="alert" className="text-2xs text-rose-300">{report.error}</p>}
    </section>
  );
}
