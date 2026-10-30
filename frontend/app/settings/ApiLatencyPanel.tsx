"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { apiFetch } from "../lib/api";
import { useVisibleInterval } from "../lib/useVisibleInterval";

interface RouteStat {
  method: string;
  path: string;
  count: number;
  window: number;
  avg_ms: number;
  p50_ms: number;
  p95_ms: number;
  p99_ms: number;
  max_ms: number;
  last_ms: number;
  errors_5xx: number;
  last_at: number;
}

interface SlowRequest {
  ts: number;
  method: string;
  path: string;
  ms: number;
  status: number;
}

interface LatencySnapshot {
  generated_at: number;
  uptime_sec: number;
  slow_threshold_ms: number;
  db_ping_ms: number | null;
  db_error?: string;
  routes: RouteStat[];
  slow_requests: SlowRequest[];
}

const SHOW_TOP = 15;

const fmtMs = (v: number) => (v >= 1000 ? `${(v / 1000).toFixed(2)} sn` : `${Math.round(v)} ms`);
const fmtUptime = (sec: number) => {
  if (sec < 90) return `${Math.round(sec)} sn`;
  if (sec < 5400) return `${Math.round(sec / 60)} dk`;
  return `${(sec / 3600).toFixed(1)} sa`;
};
// Renk + metin: renk tek başına sinyal olmasın.
const level = (p95: number) => (p95 >= 1000 ? "yavaş" : p95 >= 300 ? "orta" : "hızlı");
const levelClass = (p95: number) =>
  p95 >= 1000 ? "text-rose-400" : p95 >= 300 ? "text-amber-300" : "text-emerald-400";

function downloadCsv(snapshot: LatencySnapshot) {
  const headers = [
    "Yöntem", "Uç nokta", "Toplam istek", "Örnek", "Ortalama (ms)", "p50 (ms)", "p95 (ms)",
    "p99 (ms)", "Maks (ms)", "Son (ms)", "5xx hata", "Seviye (p95)", "Son istek (UTC)",
  ];
  const rows = snapshot.routes.map((r) => [
    r.method, r.path, r.count, r.window, r.avg_ms, r.p50_ms, r.p95_ms, r.p99_ms, r.max_ms, r.last_ms,
    r.errors_5xx, level(r.p95_ms), new Date(r.last_at * 1000).toISOString(),
  ]);
  // Raporlar sayfasıyla aynı kural: Excel için UTF-8 BOM ve noktalı virgül.
  const csv =
    "﻿" +
    [headers.join(";"), ...rows.map((row) => row.map((cell) => `"${String(cell).replace(/"/g, '""')}"`).join(";"))].join("\r\n");
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  // Dosya adı yerel saatle (sunucu zamanı UTC gelir).
  const gen = new Date(snapshot.generated_at * 1000);
  const stamp = new Date(gen.getTime() - gen.getTimezoneOffset() * 60000).toISOString().slice(0, 16).replace(/[:T]/g, "-");
  a.href = url;
  a.download = `api-gecikmeleri-${stamp}.csv`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

/** Ayarlar → Sistem Sağlığı: backend uç noktalarının sunucu tarafı gecikmesi. */
export default function ApiLatencyPanel() {
  const [data, setData] = useState<LatencySnapshot | null>(null);
  const [error, setError] = useState("");
  const [forbidden, setForbidden] = useState(false);
  const [showAll, setShowAll] = useState(false);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const result = (await apiFetch("/api/system/latency")) as LatencySnapshot;
      setData(result);
      setError("");
      setForbidden(false);
    } catch (e) {
      const msg = e instanceof Error ? e.message : "";
      if (msg.includes("403")) setForbidden(true);
      else setError("Gecikme verisi alınamadı");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);
  useVisibleInterval(() => { void load(); }, 10_000);

  const reset = async () => {
    setBusy(true);
    try {
      await apiFetch("/api/system/latency/reset", { method: "POST" });
      await load();
    } catch {
      setError("Sayaçlar sıfırlanamadı");
    } finally {
      setBusy(false);
    }
  };

  const routes = data?.routes ?? [];
  const visible = useMemo(() => (showAll ? routes : routes.slice(0, SHOW_TOP)), [routes, showAll]);
  const slowCount = routes.filter((r) => r.p95_ms >= 1000).length;
  const btn = "min-h-11 sm:min-h-0 px-3 py-1.5 rounded-lg border border-bunker-700 bg-bunker-800/80 text-xs font-mono font-bold text-white hover:border-cyan-400/60 disabled:opacity-50 transition-colors";

  if (forbidden) {
    return (
      <div className="card">
        <p className="eyebrow">API GECİKMELERİ</p>
        <p className="mt-3 text-xs text-bunker-muted">Bu bölüm yalnız yöneticiye açıktır.</p>
      </div>
    );
  }

  return (
    <div className="card space-y-4" aria-label="API gecikmeleri">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="eyebrow">API GECİKMELERİ</p>
          <p className="mt-1 text-xs text-bunker-muted max-w-2xl">
            Sunucunun isteği işleme süresi (ağ gecikmesi dahil değil). Uç nokta başına son 300 istek, p95&apos;e göre
            yavaştan hızlıya. Sunucu yeniden başlayınca sıfırlanır; 10 saniyede bir yenilenir.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button type="button" className={btn} onClick={() => void load()}>Yenile</button>
          <button type="button" className={btn} disabled={!data || routes.length === 0} onClick={() => data && downloadCsv(data)}>
            CSV indir
          </button>
          <button type="button" className={btn} disabled={busy} onClick={() => void reset()} title="Sayaçları sıfırlar; temiz ölçüm başlatır">
            Sıfırla
          </button>
        </div>
      </div>

      {error && <div role="alert" className="rounded-lg border border-neon-red/40 bg-neon-red/5 px-3 py-2 text-xs text-neon-red">{error}</div>}

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 font-mono">
        <div className="rounded-lg border border-bunker-800 p-3">
          <p className="text-[10px] uppercase tracking-wider text-bunker-muted">Veritabanı gidiş-dönüş</p>
          <p className="mt-1 text-lg font-bold tabular-nums">{data?.db_ping_ms != null ? fmtMs(data.db_ping_ms) : "—"}</p>
        </div>
        <div className="rounded-lg border border-bunker-800 p-3">
          <p className="text-[10px] uppercase tracking-wider text-bunker-muted">Ölçülen uç nokta</p>
          <p className="mt-1 text-lg font-bold tabular-nums">{routes.length}</p>
        </div>
        <div className="rounded-lg border border-bunker-800 p-3">
          <p className="text-[10px] uppercase tracking-wider text-bunker-muted">Yavaş (p95 ≥ 1 sn)</p>
          <p className={`mt-1 text-lg font-bold tabular-nums ${slowCount > 0 ? "text-rose-400" : ""}`}>{slowCount}</p>
        </div>
        <div className="rounded-lg border border-bunker-800 p-3">
          <p className="text-[10px] uppercase tracking-wider text-bunker-muted">Ölçüm süresi</p>
          <p className="mt-1 text-lg font-bold tabular-nums">{data ? fmtUptime(data.uptime_sec) : "—"}</p>
        </div>
      </div>

      {routes.length === 0 ? (
        <p className="text-xs text-bunker-muted">{data ? "Henüz ölçülen istek yok." : "Yükleniyor…"}</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-xs tabular-nums font-mono">
            <thead>
              <tr className="text-[10px] uppercase tracking-wider text-bunker-muted">
                <th scope="col" className="text-left font-medium py-2 pr-3">Uç nokta</th>
                <th scope="col" className="text-right font-medium py-2 px-2">İstek</th>
                <th scope="col" className="text-right font-medium py-2 px-2">Ort.</th>
                <th scope="col" className="text-right font-medium py-2 px-2">p50</th>
                <th scope="col" className="text-right font-medium py-2 px-2">p95</th>
                <th scope="col" className="text-right font-medium py-2 px-2">p99</th>
                <th scope="col" className="text-right font-medium py-2 px-2">Maks.</th>
                <th scope="col" className="text-right font-medium py-2 px-2">5xx</th>
                <th scope="col" className="text-left font-medium py-2 pl-3">Seviye</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((r) => (
                <tr key={`${r.method} ${r.path}`} className="border-t border-bunker-800/70">
                  <td className="py-2 pr-3 whitespace-nowrap">
                    <span className="text-bunker-muted">{r.method}</span> {r.path}
                  </td>
                  <td className="py-2 px-2 text-right">{r.count}</td>
                  <td className="py-2 px-2 text-right">{fmtMs(r.avg_ms)}</td>
                  <td className="py-2 px-2 text-right">{fmtMs(r.p50_ms)}</td>
                  <td className={`py-2 px-2 text-right font-bold ${levelClass(r.p95_ms)}`}>{fmtMs(r.p95_ms)}</td>
                  <td className="py-2 px-2 text-right">{fmtMs(r.p99_ms)}</td>
                  <td className="py-2 px-2 text-right">{fmtMs(r.max_ms)}</td>
                  <td className={`py-2 px-2 text-right ${r.errors_5xx > 0 ? "text-rose-400 font-bold" : "text-bunker-muted"}`}>{r.errors_5xx}</td>
                  <td className={`py-2 pl-3 whitespace-nowrap ${levelClass(r.p95_ms)}`}>{level(r.p95_ms)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {routes.length > SHOW_TOP && (
            <button type="button" className={`${btn} mt-3`} onClick={() => setShowAll((v) => !v)}>
              {showAll ? `İlk ${SHOW_TOP}'i göster` : `Tümünü göster (${routes.length})`}
            </button>
          )}
        </div>
      )}

      {data && data.slow_requests.length > 0 && (
        <div>
          <p className="text-[10px] uppercase tracking-wider text-bunker-muted mb-2 font-mono">
            Son yavaş istekler (≥ {fmtMs(data.slow_threshold_ms)})
          </p>
          <ul className="space-y-1 font-mono text-xs tabular-nums">
            {data.slow_requests.slice(0, 10).map((s, i) => (
              <li key={`${s.ts}-${i}`} className="flex items-center justify-between gap-3">
                <span className="truncate">
                  <span className="text-bunker-muted">{new Date(s.ts * 1000).toLocaleTimeString("tr-TR")}</span>{" "}
                  {s.method} {s.path}
                </span>
                <span className="shrink-0 font-bold text-amber-300">{fmtMs(s.ms)}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
