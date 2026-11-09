"use client";

import { useCallback, useState } from "react";
import { apiFetch, apiRequest, API_BASE } from "../../lib/api";
import { usePolling } from "../../lib/usePolling";

/**
 * Raporlar > ML Kalibrasyonu (2026-11-09).
 *
 * NE GÖSTERİR: modelin ürettiği "isabet olasılığı" DÜRÜST MÜ?
 *   - Ham vs kalibre Brier / ECE (izotonik eğri)
 *   - **OUT-OF-SAMPLE** metrikler — asıl kanıt budur. İzotonik eğri tanımı gereği
 *     EĞİTİM verisinde ECE'yi ~0 yapar; ekranda "ECE 0.38 → 0.00" görmek
 *     iyileşme değil yanılsamadır (aynı tuzak LLM güven kalibrasyonunda yaşandı).
 *   - Güvenilirlik kovaları (hangi güven aralığı aşırı güvenli)
 *   - Eşik eğrisi: eşik → kapsam / isabet / lift
 *   - Canlı sayaçlar (kaç gözlem, kaç çekimserlik)
 *
 * CSV: ham veri (tahmin + gerçekleşen sonuç) backend'den indirilir. Panel ile
 * CSV AYNI modülden (`app/ml_calibration_report`) beslenir → dosya ile ekran
 * birbirini tutar.
 */

interface Bins { lo: number; hi: number; samples: number; confidence: number; accuracy: number; gap: number }
interface Curve { threshold: number; n: number; coverage: number; hit_rate: number | null; lift: number | null; avg_r: number | null }
interface Oos {
  available: boolean; reason?: string; n_train?: number; n_test?: number; base_rate_test?: number;
  raw?: { brier: number | null; ece: number | null };
  calibrated?: { brier: number | null; ece: number | null };
  brier_skill_raw?: number | null; brier_skill_calibrated?: number | null; improved?: boolean;
}
interface Report {
  samples: number; fitted: boolean; reason?: string; rows_total?: number;
  base_rate?: number; break_even?: number; break_even_reachable?: boolean;
  avg_win_r?: number; avg_loss_r?: number;
  metrics_raw?: { brier?: number | null; log_loss?: number | null; ece?: number | null };
  metrics_calibrated?: { brier?: number | null; log_loss?: number | null; ece?: number | null };
  brier_skill_raw?: number | null; brier_skill_calibrated?: number | null;
  bins?: Bins[]; threshold_curve?: Curve[]; out_of_sample?: Oos;
  counters?: Record<string, unknown>;
  artifact?: { available: boolean; reason?: string; samples?: number; brier_skill_calibrated?: number | null; x_thresholds?: number[]; y_thresholds?: number[] };
  error?: string;
  scope?: string;
  samples_needed?: number;
}

const fmt = (v: number | null | undefined, d = 4) => (v == null ? "—" : v.toFixed(d));
const pct = (v: number | null | undefined) => (v == null ? "—" : `${(v * 100).toFixed(1)}%`);
const skillCls = (v: number | null | undefined) =>
  v == null ? "text-bunker-muted" : v > 0 ? "text-emerald-300" : "text-rose-300";

export default function MlCalibrationReport() {
  const [days, setDays] = useState(0);            // 0 = tüm zamanlar
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [csvBusy, setCsvBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setReport((await apiFetch(`/api/reports/ml-calibration?days=${days}`)) as Report);
      setError("");
    } catch (e) {
      setError(e instanceof Error && e.message ? `Kalibrasyon raporu alınamadı: ${e.message}` : "Kalibrasyon raporu alınamadı");
    } finally {
      setLoading(false);
    }
  }, [days]);
  usePolling(load, 60_000);

  const downloadCsv = async () => {
    setCsvBusy(true);
    try {
      const res = await apiRequest(`${API_BASE}/api/reports/ml-calibration/csv?days=${days}`);
      if (!res.ok) throw new Error(`CSV HTTP ${res.status}`);
      const url = URL.createObjectURL(await res.blob());
      const a = document.createElement("a");
      a.href = url;
      a.download = `ml_kalibrasyon_${new Date().toISOString().slice(0, 10)}.csv`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(e instanceof Error ? e.message : "CSV indirilemedi");
    } finally {
      setCsvBusy(false);
    }
  };

  const oos = report?.out_of_sample;
  // HÜKÜM: out-of-sample Brier skill > 0 değilse güven puanı filtre olarak işe yaramaz.
  const verdict: "ok" | "weak" | "none" =
    !report?.fitted || !oos?.available ? "none"
      : (oos.brier_skill_calibrated ?? oos.brier_skill_raw ?? 0) > 0 ? "ok" : "weak";

  const btn = (n: number) =>
    `px-3 py-1.5 min-h-11 sm:min-h-0 rounded-lg border font-mono text-xs font-bold transition-all ${
      days === n ? "bg-cyan-500/20 border-cyan-400/60 text-cyan-200" : "bg-bunker-800/80 border-bunker-700 text-bunker-muted hover:text-white"
    }`;
  const th = "px-2 py-1.5 text-left font-mono text-2xs uppercase tracking-wide text-bunker-muted";
  const td = "px-2 py-1.5 font-mono text-xs text-white";

  return (
    <section className="space-y-4" aria-label="ML olasılık kalibrasyonu raporu">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-sm font-bold text-white uppercase tracking-wider">ML Olasılık Kalibrasyonu</h2>
          {report?.scope ? (
            <p className="mt-1 max-w-3xl text-2xs text-bunker-muted">{report.scope}</p>
          ) : null}
          <p className="mt-0.5 max-w-3xl text-xs text-bunker-muted">
            Modelin “isabet olasılığı” dürüst mü? İzotonik eğri ham güveni gerçek isabete çevirir. Asıl kanıt
            <b className="text-white"> out-of-sample</b> metriklerdir: eğri geçmişte kurulur, gelecekte ölçülür —
            eğitim verisindeki ECE ~0 bir iyileşme değil yanılsamadır.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex items-center gap-2" role="group" aria-label="Dönem">
            {[1, 7, 30, 0].map((n) => (
              <button key={n} type="button" className={btn(n)} aria-pressed={days === n}
                onClick={() => { setDays(n); setLoading(true); }}>
                {n === 0 ? "Tümü" : n === 1 ? "Bugün" : `Son ${n} gün`}
              </button>
            ))}
          </div>
          <button type="button" onClick={downloadCsv} disabled={csvBusy}
            className="ui-button ui-button-compact ui-button-secondary min-h-11 sm:min-h-0">
            {csvBusy ? "İndiriliyor…" : "Ham veriyi CSV indir"}
          </button>
        </div>
      </div>

      {error && <p role="alert" className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">{error}</p>}

      {loading && !report ? (
        <p className="text-xs text-bunker-muted">Yükleniyor…</p>
      ) : !report ? null : report.error ? (
        <p role="alert" className="rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-300">
          Rapor üretilemedi: {report.error}
        </p>
      ) : (
        <>
          {verdict !== "ok" && (
            <div className="rounded-xl border border-amber-500/40 bg-amber-500/10 p-3 space-y-1">
              <p className="text-xs font-bold text-amber-200">
                {verdict === "weak"
                  ? "KANIT ZAYIF: out-of-sample Brier skill ≤ 0 — bu güven puanı işlem FİLTRESİ olarak kullanılamaz."
                  : "HÜKÜM YOK: yeterli değerlendirilmiş örnek yok."}
              </p>
              <p className="text-2xs text-amber-200/80">
                {verdict === "weak"
                  ? "Model kayıt tutmaya devam etsin; karar kapısına bağlanmadan önce örneklem ve OOS skill pozitif olmalı."
                  : report.reason || "Gölge tahminler birikmeye devam ediyor."}
              </p>
            </div>
          )}

          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {[
              { k: "Değerlendirilmiş örnek", v: String(report.samples ?? 0), s: report.rows_total ? `toplam satır ${report.rows_total}` : "" },
              { k: "Taban isabet", v: pct(report.base_rate), s: `break-even ${pct(report.break_even)}` },
              { k: "OOS Brier skill (ham)", v: fmt(oos?.brier_skill_raw, 3), s: oos?.available ? `${oos.n_test} test satırı` : "yetersiz veri", cls: skillCls(oos?.brier_skill_raw) },
              { k: "OOS Brier skill (kalibre)", v: fmt(oos?.brier_skill_calibrated, 3), s: oos?.improved ? "kalibrasyon iyileştirdi" : "iyileşme yok", cls: skillCls(oos?.brier_skill_calibrated) },
            ].map((c) => (
              <div key={c.k} className="rounded-xl border border-bunker-800 bg-bunker-900/60 p-3">
                <p className="font-mono text-2xs uppercase tracking-wide text-bunker-muted">{c.k}</p>
                <p className={`mt-1 font-mono text-lg font-bold ${c.cls || "text-white"}`}>{c.v}</p>
                {c.s && <p className="mt-0.5 text-2xs text-bunker-muted">{c.s}</p>}
              </div>
            ))}
          </div>

          <div className="grid gap-3 lg:grid-cols-2">
            <div className="rounded-xl border border-bunker-800 bg-bunker-900/60 p-3">
              <h3 className="font-mono text-2xs uppercase tracking-wide text-bunker-muted">Metrikler (in-sample / OUT-OF-SAMPLE)</h3>
              <table className="mt-2 w-full">
                <thead>
                  <tr><th className={th}>metrik</th><th className={th}>ham</th><th className={th}>kalibre</th><th className={th}>OOS ham</th><th className={th}>OOS kalibre</th></tr>
                </thead>
                <tbody>
                  {([["Brier", "brier"], ["log-loss", "log_loss"], ["ECE", "ece"]] as const).map(([label, key]) => (
                    <tr key={key} className="border-t border-bunker-800">
                      <td className={td}>{label}</td>
                      <td className={td}>{fmt(report.metrics_raw?.[key])}</td>
                      <td className={td}>{fmt(report.metrics_calibrated?.[key])}</td>
                      <td className={td}>{key === "log_loss" ? "—" : fmt((oos?.raw as Record<string, number | null> | undefined)?.[key])}</td>
                      <td className={td}>{key === "log_loss" ? "—" : fmt((oos?.calibrated as Record<string, number | null> | undefined)?.[key])}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="mt-2 text-2xs text-bunker-muted">
                Küçük olan iyidir. OOS log-loss hesaplanmaz (rapor yalnız Brier/ECE taşır).
              </p>
            </div>

            <div className="rounded-xl border border-bunker-800 bg-bunker-900/60 p-3">
              <h3 className="font-mono text-2xs uppercase tracking-wide text-bunker-muted">Eşik eğrisi (eşiğe kilitlenmek yerine eğri)</h3>
              <table className="mt-2 w-full">
                <thead>
                  <tr><th className={th}>eşik</th><th className={th}>kapsam</th><th className={th}>n</th><th className={th}>isabet</th><th className={th}>lift</th><th className={th}>ort. R</th></tr>
                </thead>
                <tbody>
                  {(report.threshold_curve || []).map((c) => (
                    <tr key={c.threshold} className="border-t border-bunker-800">
                      <td className={td}>{c.threshold.toFixed(2)}</td>
                      <td className={td}>{pct(c.coverage)}</td>
                      <td className={td}>{c.n}</td>
                      <td className={td}>{pct(c.hit_rate)}</td>
                      <td className={`${td} ${c.lift != null && c.lift > 1 ? "text-emerald-300" : ""}`}>{fmt(c.lift, 2)}</td>
                      <td className={td}>{fmt(c.avg_r, 3)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div className="rounded-xl border border-bunker-800 bg-bunker-900/60 p-3">
            <h3 className="font-mono text-2xs uppercase tracking-wide text-bunker-muted">Güvenilirlik kovaları (gap&lt;0 = hâlâ aşırı güvenli)</h3>
            <table className="mt-2 w-full">
              <thead>
                <tr><th className={th}>kova</th><th className={th}>n</th><th className={th}>güven</th><th className={th}>gerçek</th><th className={th}>gap</th></tr>
              </thead>
              <tbody>
                {(report.bins || []).map((b) => (
                  <tr key={`${b.lo}-${b.hi}`} className="border-t border-bunker-800">
                    <td className={td}>{b.lo.toFixed(2)}–{b.hi.toFixed(2)}</td>
                    <td className={td}>{b.samples}</td>
                    <td className={td}>{b.confidence.toFixed(3)}</td>
                    <td className={td}>{b.accuracy.toFixed(3)}</td>
                    <td className={`${td} ${b.gap < 0 ? "text-amber-300" : "text-emerald-300"}`}>{b.gap >= 0 ? "+" : ""}{b.gap.toFixed(3)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="grid gap-3 lg:grid-cols-2">
            <div className="rounded-xl border border-bunker-800 bg-bunker-900/60 p-3">
              <h3 className="font-mono text-2xs uppercase tracking-wide text-bunker-muted">Canlı gözlem sayaçları</h3>
              <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1">
                {Object.entries(report.counters || {}).map(([k, v]) => (
                  <div key={k} className="flex items-baseline justify-between gap-2">
                    <dt className="font-mono text-2xs text-bunker-muted">{k}</dt>
                    <dd className="font-mono text-xs text-white">{typeof v === "number" ? v.toLocaleString("tr-TR") : String(v)}</dd>
                  </div>
                ))}
              </dl>
            </div>
            <div className="rounded-xl border border-bunker-800 bg-bunker-900/60 p-3">
              <h3 className="font-mono text-2xs uppercase tracking-wide text-bunker-muted">Kayıtlı eğri (artefakt)</h3>
              {report.artifact?.available ? (
                <dl className="mt-2 space-y-1">
                  <div className="flex justify-between"><dt className="font-mono text-2xs text-bunker-muted">örnek</dt><dd className="font-mono text-xs text-white">{report.artifact.samples ?? "—"}</dd></div>
                  <div className="flex justify-between"><dt className="font-mono text-2xs text-bunker-muted">kalibre Brier skill</dt><dd className={`font-mono text-xs ${skillCls(report.artifact.brier_skill_calibrated)}`}>{fmt(report.artifact.brier_skill_calibrated, 3)}</dd></div>
                  <div className="flex justify-between"><dt className="font-mono text-2xs text-bunker-muted">eğri noktası</dt><dd className="font-mono text-xs text-white">{report.artifact.x_thresholds?.length ?? 0}</dd></div>
                </dl>
              ) : (
                <p className="mt-2 text-xs text-bunker-muted">{report.artifact?.reason || "Eğri kaydedilmemiş."}</p>
              )}
            </div>
          </div>
        </>
      )}
    </section>
  );
}
