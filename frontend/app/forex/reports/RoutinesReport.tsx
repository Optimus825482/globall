"use client";

import { useCallback, useState } from "react";
import { apiFetch } from "../../lib/api";
import { usePolling } from "../../lib/usePolling";

/**
 * Raporlar > Rutinler (2026-11-10).
 *
 * Sunucu tarafı rutinler: gölge modlar / kanıt kapsamı / kalibrasyon anlık görüntüleri.
 * Her satır: ad, aralık, son çalışma, süre, durum ve son sonucun özeti. `requires_mt5`
 * işaretli rutinler sunucuda KOŞMAZ (terminal yok) — köprü makinesinde çalıştırılır.
 * Sayı uydurulmaz: çalışmamışsa "hiç çalışmadı" yazar.
 */

interface Routine {
  name: string;
  description: string;
  interval_sec: number;
  requires_mt5: boolean;
  output_note: string;
  tags: string[];
  last_run_ts: number | null;
  last_ok: boolean | null;
  last_duration_ms: number | null;
  last_result: Record<string, unknown> | null;
}
interface RoutinesPayload {
  count: number;
  routines: Routine[];
}

function fmtInterval(sec: number): string {
  if (sec >= 86400) return `${Math.round(sec / 86400)} gün`;
  if (sec >= 3600) return `${Math.round(sec / 3600)} saat`;
  return `${Math.max(1, Math.round(sec / 60))} dk`;
}

function fmtAgo(ts: number | null): string {
  if (!ts) return "hiç çalışmadı";
  const d = Math.max(0, Date.now() / 1000 - ts);
  if (d < 60) return `${Math.round(d)} sn önce`;
  if (d < 3600) return `${Math.round(d / 60)} dk önce`;
  if (d < 86400) return `${Math.round(d / 3600)} sa önce`;
  return `${Math.round(d / 86400)} gün önce`;
}

export default function RoutinesReport() {
  const [data, setData] = useState<RoutinesPayload | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState<string>("");
  const [notice, setNotice] = useState("");

  const load = useCallback(async () => {
    try {
      setData((await apiFetch("/api/system/routines")) as RoutinesPayload);
      setError("");
    } catch (e) {
      setError(e instanceof Error && e.message ? `Rutinler alınamadı: ${e.message}` : "Rutinler alınamadı");
    }
  }, []);
  usePolling(load, 60_000);

  const runNow = useCallback(async (name: string) => {
    setBusy(name);
    setNotice("");
    try {
      const res = (await apiFetch(`/api/system/routines/${encodeURIComponent(name)}/run`, {
        method: "POST",
      })) as { ok?: boolean; skipped?: boolean; error?: string; duration_ms?: number };
      setNotice(
        res?.skipped
          ? `${name}: atlandı (${res?.error || "vade dolmadı"})`
          : `${name}: ${res?.ok ? "tamam" : "hata"} · ${res?.duration_ms ?? "?"} ms`,
      );
      await load();
    } catch (e) {
      setNotice(`${name}: çalıştırılamadı (${e instanceof Error ? e.message : "hata"})`);
    } finally {
      setBusy("");
    }
  }, [load]);

  return (
    <section className="space-y-4" aria-label="Rutinler raporu">
      <div>
        <h2 className="text-sm font-bold text-white uppercase tracking-wider">Rutinler</h2>
        <p className="mt-0.5 max-w-3xl text-xs text-bunker-muted">
          Ölçüm/rapor işleri <b className="text-white">otomatik</b> koşar ve her sonuç{" "}
          <code className="font-mono text-2xs text-cyan-300">routine_runs</code> tablosuna yazılır — böylece
          &laquo;geçen haftaya göre ne değişti&raquo; sorusu zaman serisinden okunur.{" "}
          <b className="text-amber-200">MT5 gerekli</b> işaretli rutinler sunucuda koşmaz (terminal yok).
        </p>
      </div>

      {error && <p role="alert" className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">{error}</p>}
      {notice && <p className="rounded-lg border border-cyan-500/40 bg-cyan-500/10 px-3 py-2 text-xs text-cyan-200">{notice}</p>}

      <div className="space-y-2">
        {(data?.routines || []).map((r) => {
          const ok = r.last_ok;
          const badge = ok === null
            ? { t: "HİÇ ÇALIŞMADI", c: "border-bunker-700 bg-bunker-800/60 text-bunker-muted" }
            : ok
              ? { t: "TAMAM", c: "border-emerald-500/40 bg-emerald-500/10 text-emerald-300" }
              : { t: "HATA", c: "border-rose-500/40 bg-rose-500/10 text-rose-300" };
          return (
            <div key={r.name} className="rounded-xl border border-bunker-800 bg-bunker-900/60 p-3">
              <div className="flex flex-wrap items-center gap-2">
                <span className={`rounded border px-2 py-0.5 font-mono text-2xs font-bold ${badge.c}`}>{badge.t}</span>
                <h3 className="font-mono text-xs font-bold text-white">{r.name}</h3>
                <span className="rounded border border-bunker-700 bg-bunker-800/60 px-2 py-0.5 font-mono text-2xs text-bunker-muted">
                  her {fmtInterval(r.interval_sec)}
                </span>
                {r.requires_mt5 && (
                  <span className="rounded border border-amber-500/40 bg-amber-500/10 px-2 py-0.5 font-mono text-2xs font-bold text-amber-200">
                    MT5 gerekli
                  </span>
                )}
                <span className="ml-auto font-mono text-2xs text-bunker-muted">{fmtAgo(r.last_run_ts)}</span>
                <button
                  type="button"
                  onClick={() => runNow(r.name)}
                  disabled={busy === r.name || r.requires_mt5}
                  title={r.requires_mt5 ? "Sunucuda MT5 yok — köprü makinesinde koşulur" : "Şimdi çalıştır"}
                  className="min-h-11 sm:min-h-0 rounded-lg border border-cyan-500/40 bg-cyan-500/10 px-3 py-1 font-mono text-2xs font-bold text-cyan-200 disabled:opacity-40"
                >
                  {busy === r.name ? "…" : "Şimdi çalıştır"}
                </button>
              </div>
              <p className="mt-1.5 text-2xs text-bunker-muted">{r.description}</p>
              {r.last_duration_ms != null && (
                <p className="mt-1 font-mono text-2xs text-bunker-muted/80">son süre: {r.last_duration_ms} ms</p>
              )}
              {r.output_note && <p className="mt-0.5 font-mono text-2xs text-cyan-300/70">çıktı: {r.output_note}</p>}
              {r.last_result && Object.keys(r.last_result).length > 0 && (
                <pre className="mt-2 max-h-28 overflow-auto rounded-lg border border-bunker-800 bg-bunker-950/60 p-2 font-mono text-2xs text-bunker-muted">
{JSON.stringify(r.last_result, null, 1)}
                </pre>
              )}
            </div>
          );
        })}
        {data && data.routines.length === 0 && (
          <p className="text-xs text-bunker-muted">Kayıtlı rutin yok.</p>
        )}
      </div>
    </section>
  );
}
