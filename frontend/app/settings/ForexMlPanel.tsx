"use client";

import React, { useCallback, useEffect, useState } from "react";
import { apiFetch } from "../lib/api";

/**
 * Ayarlar > Forex ML (2026-11-09).
 *
 * NEDEN: forex'e özel eğitim verisi `llm_trade_reviews.features` altında
 * birikiyor (deterministik giriş özellikleri + gölge sonuç) ama veri SUNUCU
 * DB'sinde olduğu için eğitim sunucuda koşmalı. Bu sekme: veri durumunu gösterir,
 * eğitim düğmesi sunucuda koşturur, OOS metriklerini + koşu geçmişini raporlar.
 *
 * DÜRÜSTLÜK: model OOS skill > 0 verene kadar "karar kapısı OLMAMALI" yazar.
 * Artifact JSON'dur (pickle yok); üretim imajı yalın kalır.
 */

interface ForexMlRun {
  id: number; trained_at: number; n_usable: number | null; n_train: number | null;
  n_test: number | null; brier_skill_oos: number | null; ic_test: number | null; verdict: string | null;
}
interface ForexMlStatus {
  dataset_n: number; min_rows: number; test_fraction?: number;
  runs: ForexMlRun[]; artifact_metrics: Record<string, unknown> | null;
}
interface TrainReport {
  trained?: boolean; n_rows?: number; n_usable?: number; n_train?: number; n_test?: number;
  base_rate_train?: number; base_rate_test?: number; brier_train?: number; brier_test?: number;
  brier_skill_oos?: number; ece_test?: number; ic_test?: number; ic_significance?: number;
  verdict?: string; reason?: string; coefficients?: Record<string, number>;
  calibrated_brier_test?: number; calibration_improved?: boolean;
  artifact_path?: string; artifact_error?: string; run_log_error?: string;
  models?: Record<string, { brier_test?: number; brier_skill_oos?: number | null; ic_test?: number | null }>;
  best_model?: string;
  wilson?: { n: number; hit_rate: number; lo: number; hi: number } | null;
  error?: string;
}

const fmt = (v: number | null | undefined, d = 4) => (v == null ? "—" : v.toFixed(d));
const skillCls = (v: number | null | undefined) =>
  v == null ? "text-bunker-muted" : v > 0 ? "text-emerald-300" : "text-rose-300";

export default function ForexMlPanel() {
  const [status, setStatus] = useState<ForexMlStatus | null>(null);
  const [report, setReport] = useState<TrainReport | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      setStatus((await apiFetch("/api/system/forex-ml")) as ForexMlStatus);
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Forex ML durumu alınamadı");
    }
  }, []);

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { void load(); }, []);

  const train = async () => {
    setBusy(true);
    setError("");
    try {
      const res = await apiFetch("/api/system/forex-ml/train?min_rows=120", { method: "POST" });
      setReport(res as TrainReport);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Eğitim başlatılamadı");
    } finally {
      setBusy(false);
    }
  };

  const last = report || (status?.artifact_metrics as TrainReport | null | undefined);
  const th = "px-2 py-1.5 text-left font-mono text-2xs uppercase tracking-wide text-bunker-muted";
  const td = "px-2 py-1.5 font-mono text-xs text-white";

  return (
    <section className="space-y-4" aria-label="Forex ML">
      <div>
        <h2 className="text-sm font-bold text-white uppercase tracking-wider">Forex ML — işlem dosyası özelliklerinden isabet modeli</h2>
        <p className="mt-0.5 max-w-3xl text-xs text-bunker-muted">
          Her LLM kararında kaydedilen deterministik giriş özellikleri (seans, üst dilim uyumu,
          seviye mesafesi, EMA uzantısı, spread/ATR, haber dakikası) + o kararın <b className="text-white">gölge sonucu</b>{" "}
          → lojistik model. Veri sunucu DB&apos;sinde olduğu için eğitim <b className="text-white">sunucuda</b> koşar.
          Split <b className="text-white">kronolojik</b> (ilk %70 eğitim, son %30 test) — zaman sızıntısı yok.
          Artifact JSON&apos;dur (pickle yok).
        </p>
      </div>

      {error && <p role="alert" className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">{error}</p>}

      <div className="grid gap-3 sm:grid-cols-3">
        <div className="rounded-xl border border-bunker-800 bg-bunker-900/60 p-3">
          <p className="font-mono text-2xs uppercase tracking-wide text-bunker-muted">Eğitim verisi (features + sonuç dolu)</p>
          <p className={`mt-1 font-mono text-lg font-bold ${(status?.dataset_n ?? 0) >= (status?.min_rows ?? 120) ? "text-emerald-300" : "text-amber-300"}`}>
            {status?.dataset_n ?? "—"}
          </p>
          <p className="mt-0.5 text-2xs text-bunker-muted">en az {status?.min_rows ?? 120} satır gerekli</p>
        </div>
        <div className="rounded-xl border border-bunker-800 bg-bunker-900/60 p-3">
          <p className="font-mono text-2xs uppercase tracking-wide text-bunker-muted">Eğitim koşusu</p>
          <p className="mt-1 font-mono text-lg font-bold text-white">{status?.runs?.length ?? 0}</p>
          <p className="mt-0.5 text-2xs text-bunker-muted">son koşullar aşağıda loglanır</p>
        </div>
        <div className="rounded-xl border border-bunker-800 bg-bunker-900/60 p-3">
          <p className="font-mono text-2xs uppercase tracking-wide text-bunker-muted">OOS Brier skill</p>
          <p className={`mt-1 font-mono text-lg font-bold ${skillCls(last?.brier_skill_oos)}`}>
            {fmt(last?.brier_skill_oos, 3)}
          </p>
          <p className="mt-0.5 text-2xs text-bunker-muted">&gt; 0 = test yarısında bilgi var</p>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={train}
          disabled={busy}
          className="ui-button ui-button-compact ui-button-secondary"
        >
          {busy ? "Sunucuda eğitiliyor…" : "Forex ML eğit + OOS test"}
        </button>
        <span className="text-2xs text-bunker-muted">
          Yalnız ölçüm + kayıt: model karar kapısı DEĞİL. Kapı için replay A/B gerekir.
        </span>
      </div>

      {report && (
        <div className="space-y-3">
          {!report.trained ? (
            <div className="rounded-lg border border-amber-500/40 bg-amber-500/10 p-2.5 text-xs text-amber-200">
              Eğitim yapılmadı: {report.reason || report.error || "bilinmeyen sebep"}
            </div>
          ) : (
            <>
              <div className={`rounded-lg border p-2.5 text-xs ${
                (report.brier_skill_oos ?? 0) > 0
                  ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-200"
                  : "border-amber-500/40 bg-amber-500/10 text-amber-200"}`}>
                <b>{report.verdict}</b>
                <div className="mt-1 text-2xs opacity-80">
                  Karar kapısı olarak kullanmak için replay A/B gerekir (chandelier/P1 disiplini).
                  Artifact: {report.artifact_path || "—"}
                </div>
              </div>

              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                {[
                  { k: "Satırlar (eğitim/test)", v: `${report.n_train} / ${report.n_test}` },
                  { k: "Brier (eğitim / test)", v: `${fmt(report.brier_train)} / ${fmt(report.brier_test)}` },
                  { k: "ECE (test)", v: fmt(report.ece_test) },
                  { k: "IC (test, Spearman)", v: fmt(report.ic_test, 3) },
                ].map((c) => (
                  <div key={c.k} className="rounded-lg border border-bunker-700 bg-bunker-950/50 p-2">
                    <p className="font-mono text-2xs text-bunker-muted">{c.k}</p>
                    <p className="mt-0.5 font-mono text-sm text-white">{c.v}</p>
                  </div>
                ))}
              </div>

              {report.calibrated_brier_test != null && (
                <p className="text-2xs text-bunker-muted">
                  İzotonik kalibrasyon (test): {fmt(report.calibrated_brier_test)} —{" "}
                  {report.calibration_improved ? "Brier'ı iyileştirdi" : "iyileştirmedi"}
                </p>
              )}

              {report.models && (
                <div className="rounded-xl border border-bunker-800 bg-bunker-900/60 p-3">
                  <h3 className="font-mono text-2xs uppercase tracking-wide text-bunker-muted">
                    Model kıyası (aynı veri, aynı kronolojik split — Databricks Big Book 3e s58: tabular → boosting)
                  </h3>
                  <table className="mt-2 w-full">
                    <thead>
                      <tr><th className={th}>model</th><th className={th}>Brier (test)</th><th className={th}>OOS skill</th><th className={th}>IC (test)</th><th className={th}></th></tr>
                    </thead>
                    <tbody>
                      {Object.entries(report.models).map(([name, m]) => (
                        <tr key={name} className="border-t border-bunker-800">
                          <td className={td}>
                            {name === "logistic" ? "Lojistik (JSON artifact)" : "Hist Gradient Boosting"}
                          </td>
                          <td className={td}>{fmt(m.brier_test)}</td>
                          <td className={`${td} ${skillCls(m.brier_skill_oos)}`}>{fmt(m.brier_skill_oos, 3)}</td>
                          <td className={td}>{fmt(m.ic_test, 3)}</td>
                          <td className={td}>
                            {report.best_model === name && (
                              <span className="rounded border border-emerald-500/40 bg-emerald-500/10 px-2 py-0.5 font-mono text-2xs font-bold text-emerald-300">
                                EN İYİ
                              </span>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  <p className="mt-2 text-2xs text-bunker-muted">
                    Skorlayıcı (gölge) yalnız lojistik artifact&apos;ını okur; boosting modeli kıyas amaçlıdır ve
                    kaydedilmez (kalıcılık için joblib/pickle kararı ayrıca verilir).
                  </p>
                </div>
              )}

              <div className="rounded-xl border border-bunker-800 bg-bunker-900/60 p-3">
                <h3 className="font-mono text-2xs uppercase tracking-wide text-bunker-muted">
                  Katsayılar (standartlaştırılmış — pozitif = isabet olasılığını artırıyor)
                </h3>
                <table className="mt-2 w-full">
                  <thead>
                    <tr><th className={th}>özellik</th><th className={th}>katsayı</th></tr>
                  </thead>
                  <tbody>
                    {Object.entries(report.coefficients || {})
                      .sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]))
                      .map(([name, v]) => (
                        <tr key={name} className="border-t border-bunker-800">
                          <td className={td}>{name}</td>
                          <td className={`${td} ${v > 0 ? "text-emerald-300" : "text-rose-300"}`}>
                            {v > 0 ? "+" : ""}{v.toFixed(3)}
                          </td>
                        </tr>
                      ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
          {(report.run_log_error || report.artifact_error) && (
            <p className="text-2xs text-amber-300">
              kayıt uyarısı: {report.run_log_error || report.artifact_error}
            </p>
          )}
        </div>
      )}

      {(status?.runs?.length ?? 0) > 0 && (
        <div className="rounded-xl border border-bunker-800 bg-bunker-900/60 p-3">
          <h3 className="font-mono text-2xs uppercase tracking-wide text-bunker-muted">Eğitim koşusu geçmişi (log)</h3>
          <table className="mt-2 w-full">
            <thead>
              <tr><th className={th}>zaman (UTC+3)</th><th className={th}>satır</th><th className={th}>eğit/test</th><th className={th}>OOS skill</th><th className={th}>hüküm</th></tr>
            </thead>
            <tbody>
              {(status?.runs || []).map((r) => (
                <tr key={r.id} className="border-t border-bunker-800">
                  <td className={td}>{new Date((r.trained_at || 0) * 1000).toLocaleString("tr-TR")}</td>
                  <td className={td}>{r.n_usable ?? "—"}</td>
                  <td className={td}>{r.n_train ?? "—"}/{r.n_test ?? "—"}</td>
                  <td className={`${td} ${skillCls(r.brier_skill_oos)}`}>{fmt(r.brier_skill_oos, 3)}</td>
                  <td className="px-2 py-1.5 text-2xs text-bunker-muted">{(r.verdict || "").slice(0, 60)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
