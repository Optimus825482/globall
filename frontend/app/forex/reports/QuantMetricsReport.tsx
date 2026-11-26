"use client";

import React, { useEffect, useState } from "react";
import { apiFetch, API_BASE } from "../../lib/api";
import { showToast } from "../../components/AppToast";

interface TearSheetData {
  trade_count: number;
  net_pnl_usd: number;
  total_return_pct: number;
  win_rate_pct: number;
  profit_factor: number | null;
  expectancy_usd: number;
  payoff_ratio: number | null;
  sharpe: number;
  sortino: number;
  calmar: number;
  max_drawdown_pct: number;
  max_drawdown_usd: number;
  avg_win_usd: number;
  avg_loss_usd: number;
  best_trade_usd: number;
  worst_trade_usd: number;
  win_loss_distribution: Array<{ bucket: string; count: number }>;
  by_strategy: Record<string, { count: number; wins: number; win_rate_pct: number; net_pnl_usd: number }>;
  by_symbol: Record<string, { count: number; wins: number; win_rate_pct: number; net_pnl_usd: number }>;
}

interface H1H4ScannerRow {
  ts?: number;
  symbol?: string;
  strategy?: string;
  strategy_label?: string;
  signal?: string;
  price?: number;
  sl_pips?: number;
  tp_pips?: number;
  reason?: string;
}

interface AuditPayload {
  tearsheet?: TearSheetData;
  scans?: {
    opportunity_scan?: {
      h1_h4_scanners?: H1H4ScannerRow[];
    };
  };
  meta_filter?: {
    total_evaluated: number;
    avg_meta_prob: number;
    model_meta?: { trained?: boolean; n_samples?: number; accuracy?: number | null };
    by_verdict?: Record<string, number>;
  };
  episodic_reflections?: {
    total_stored: number;
    recent_wins: number;
    recent_losses: number;
    items: Array<{
      symbol: string;
      direction: string;
      strategy: string;
      outcome: string;
      pnl_usd: number;
      lesson: string;
    }>;
  };
}

export default function QuantMetricsReport() {
  const [period, setPeriod] = useState<"today" | "week" | "all">("today");
  const [data, setData] = useState<AuditPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [training, setTraining] = useState(false);

  const loadData = async (p = period) => {
    setLoading(true);
    try {
      const body = await apiFetch(`/api/forex/diagnostics/today-audit?period=${p}&limit=50`);
      if (body && typeof body === "object") {
        setData(body as AuditPayload);
      }
    } catch {
      showToast("Quant ölçüm raporu alınamadı", "error");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData(period);
  }, [period]);

  const handleTrainMeta = async () => {
    setTraining(true);
    try {
      const body = await apiFetch("/api/forex/diagnostics/meta-train", { method: "POST" });
      if (body?.ok) {
        showToast(`ML Meta-Model eğitildi (${body.n_samples} işlem, doğruluk %${Math.round((body.accuracy || 0) * 100)})`, "success");
        loadData(period);
      } else {
        showToast(body?.reason || "Eğitim için yeterli kapalı işlem yok", "info");
      }
    } catch {
      showToast("ML model eğitimi başarısız oldu", "error");
    } finally {
      setTraining(false);
    }
  };

  const ts = data?.tearsheet;
  const mf = data?.meta_filter;
  const er = data?.episodic_reflections;
  const maxBucket = Math.max(1, ...(ts?.win_loss_distribution || []).map((b) => b.count));

  return (
    <div className="space-y-5">
      {/* Üst kontrol çubuğu */}
      <div className="flex flex-wrap items-center justify-between gap-3 bg-bunker-900/70 border border-bunker-800 rounded-xl p-4">
        <div className="flex flex-wrap items-center gap-2">
          {([["today", "Bugün"], ["week", "Son 7 Gün"], ["all", "Tüm Geçmiş"]] as const).map(([k, lbl]) => (
            <button
              key={k}
              type="button"
              onClick={() => setPeriod(k)}
              className={`px-3 py-1.5 rounded-lg text-xs font-mono font-bold border transition-colors ${
                period === k
                  ? "bg-blue-500/20 border-blue-400/60 text-blue-200"
                  : "bg-bunker-800 border-bunker-700 text-bunker-muted hover:text-white"
              }`}
            >
              {lbl}
            </button>
          ))}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <a
            href={`${API_BASE}/api/forex/diagnostics/tearsheet.html?period=${period}`}
            target="_blank"
            rel="noopener noreferrer"
            className="px-3 py-1.5 rounded-lg text-xs font-bold bg-indigo-600/80 hover:bg-indigo-500 text-white transition-colors"
          >
            📊 HTML Tear-Sheet Aç
          </a>
          <button
            type="button"
            onClick={handleTrainMeta}
            disabled={training}
            className="px-3 py-1.5 rounded-lg text-xs font-bold bg-emerald-600/80 hover:bg-emerald-500 text-white transition-colors disabled:opacity-50"
          >
            {training ? "Eğitiliyor…" : "🧠 ML Meta-Model Eğit"}
          </button>
          <button
            type="button"
            onClick={() => loadData(period)}
            className="px-3 py-1.5 rounded-lg text-xs font-bold bg-bunker-800 border border-bunker-700 text-bunker-muted hover:text-white"
          >
            ↻ Yenile
          </button>
        </div>
      </div>

      {loading && !ts ? (
        <div className="text-center py-10 text-sm text-bunker-muted">Ölçüm verileri yükleniyor…</div>
      ) : (
        <>
          {/* QuantStats KPI Kartları */}
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
            {[
              { lbl: "Net PnL", val: `$${(ts?.net_pnl_usd ?? 0).toFixed(2)}`, cls: (ts?.net_pnl_usd ?? 0) >= 0 ? "text-emerald-400" : "text-rose-400" },
              { lbl: "Profit Factor", val: ts?.profit_factor != null ? String(ts.profit_factor) : "—", cls: (ts?.profit_factor ?? 0) >= 1.2 ? "text-emerald-400" : "text-amber-300" },
              { lbl: "Sharpe / Sortino", val: `${(ts?.sharpe ?? 0).toFixed(2)} / ${(ts?.sortino ?? 0).toFixed(2)}`, cls: "text-cyan-300" },
              { lbl: "Max Drawdown", val: `${(ts?.max_drawdown_pct ?? 0).toFixed(2)}% ($${(ts?.max_drawdown_usd ?? 0).toFixed(2)})`, cls: "text-rose-400" },
              { lbl: "Expectancy / İşlem", val: `$${(ts?.expectancy_usd ?? 0).toFixed(2)} (${ts?.trade_count ?? 0} işl.)`, cls: (ts?.expectancy_usd ?? 0) >= 0 ? "text-emerald-400" : "text-rose-400" },
            ].map((c) => (
              <div key={c.lbl} className="bg-bunker-900/80 border border-bunker-800 rounded-xl p-3">
                <div className="text-[11px] text-bunker-muted uppercase">{c.lbl}</div>
                <div className={`text-base font-mono font-bold mt-1 ${c.cls}`}>{c.val}</div>
              </div>
            ))}
          </div>

          {/* Win/Loss Dağılımı + ML Meta-Filter Durumu */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <div className="bg-bunker-900/80 border border-bunker-800 rounded-xl p-4">
              <h3 className="text-xs font-bold uppercase text-bunker-muted mb-3">Win / Loss Dağılımı</h3>
              <div className="space-y-2">
                {(ts?.win_loss_distribution || []).map((b) => (
                  <div key={b.bucket} className="flex items-center gap-3 text-xs font-mono">
                    <span className="w-28 text-bunker-muted">{b.bucket}</span>
                    <div className="flex-1 h-3 bg-bunker-800 rounded overflow-hidden">
                      <div
                        className={`h-full ${b.bucket.includes("-") ? "bg-rose-500/70" : "bg-emerald-500/70"}`}
                        style={{ width: `${Math.round((b.count / maxBucket) * 100)}%` }}
                      />
                    </div>
                    <span className="w-8 text-right font-bold">{b.count}</span>
                  </div>
                ))}
              </div>
            </div>

            <div className="bg-bunker-900/80 border border-bunker-800 rounded-xl p-4">
              <h3 className="text-xs font-bold uppercase text-bunker-muted mb-3">Triple-Barrier ML Meta-Filter</h3>
              <div className="grid grid-cols-2 gap-3 text-xs font-mono">
                <div className="bg-bunker-800/60 rounded-lg p-2.5">
                  <div className="text-bunker-muted">Model Durumu</div>
                  <div className="font-bold mt-1 text-white">
                    {mf?.model_meta?.trained ? `ML Aktif (${mf.model_meta.n_samples} örnek)` : "Kural Prior (Eğitim Bekliyor)"}
                  </div>
                </div>
                <div className="bg-bunker-800/60 rounded-lg p-2.5">
                  <div className="text-bunker-muted">Doğruluk / Ort. Olasılık</div>
                  <div className="font-bold mt-1 text-cyan-300">
                    {mf?.model_meta?.accuracy != null ? `%${Math.round(mf.model_meta.accuracy * 100)}` : "—"} / {((mf?.avg_meta_prob ?? 0) * 100).toFixed(1)}%
                  </div>
                </div>
                <div className="bg-bunker-800/60 rounded-lg p-2.5 col-span-2 flex justify-between">
                  <span>BOOST: <b className="text-emerald-400">{mf?.by_verdict?.BOOST ?? 0}</b></span>
                  <span>PASS: <b className="text-blue-300">{mf?.by_verdict?.PASS ?? 0}</b></span>
                  <span>REDUCE: <b className="text-amber-400">{mf?.by_verdict?.REDUCE ?? 0}</b></span>
                  <span>Toplam: <b>{mf?.total_evaluated ?? 0}</b></span>
                </div>
              </div>
            </div>
          </div>

          {/* Strateji & Sembol Kırılımı */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {[
              { title: "Strateji Bazlı Ölçüm", rows: ts?.by_strategy || {} },
              { title: "Sembol Bazlı Ölçüm", rows: ts?.by_symbol || {} },
            ].map((tbl) => (
              <div key={tbl.title} className="bg-bunker-900/80 border border-bunker-800 rounded-xl p-4 overflow-x-auto">
                <h3 className="text-xs font-bold uppercase text-bunker-muted mb-3">{tbl.title}</h3>
                <table className="w-full text-xs font-mono">
                  <thead>
                    <tr className="text-left text-bunker-muted border-b border-bunker-800">
                      <th className="py-1.5">Ad</th>
                      <th className="py-1.5">İşlem</th>
                      <th className="py-1.5">Win %</th>
                      <th className="py-1.5 text-right">Net PnL</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(tbl.rows).map(([k, v]) => (
                      <tr key={k} className="border-b border-bunker-800/50">
                        <td className="py-1.5 font-bold">{k}</td>
                        <td className="py-1.5">{v.count}</td>
                        <td className="py-1.5">{v.win_rate_pct}%</td>
                        <td className={`py-1.5 text-right font-bold ${v.net_pnl_usd >= 0 ? "text-emerald-400" : "text-rose-400"}`}>
                          ${v.net_pnl_usd.toFixed(2)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ))}
          </div>

          {/* H1/H4 Strateji Monitörü */}
          <div className="bg-bunker-900/80 border border-bunker-800 rounded-xl p-4 overflow-x-auto">
            <h3 className="text-xs font-bold uppercase text-bunker-muted mb-3">
              🛰️ H1 / H4 Strateji Monitörü (Canlı Tarama Durumu)
            </h3>
            {(data?.scans?.opportunity_scan?.h1_h4_scanners || []).length > 0 ? (
              <table className="w-full text-xs font-mono">
                <thead>
                  <tr className="text-left text-bunker-muted border-b border-bunker-800">
                    <th className="py-1.5">Sembol</th>
                    <th className="py-1.5">Strateji</th>
                    <th className="py-1.5">Durum</th>
                    <th className="py-1.5">Fiyat</th>
                    <th className="py-1.5">SL / TP (pip)</th>
                    <th className="py-1.5">Açıklama</th>
                  </tr>
                </thead>
                <tbody>
                  {(data?.scans?.opportunity_scan?.h1_h4_scanners || []).map((r, i) => (
                    <tr key={`${r.symbol}-${r.strategy}-${i}`} className="border-b border-bunker-800/50">
                      <td className="py-1.5 font-bold">{r.symbol}</td>
                      <td className="py-1.5 text-cyan-300">{r.strategy_label || r.strategy}</td>
                      <td className="py-1.5">
                        <span className={`px-2 py-0.5 rounded font-bold ${
                          r.signal === "BUY" ? "bg-emerald-500/20 text-emerald-300" :
                          r.signal === "SELL" ? "bg-rose-500/20 text-rose-300" :
                          "bg-bunker-800 text-bunker-muted"
                        }`}>
                          {r.signal || "HOLD"}
                        </span>
                      </td>
                      <td className="py-1.5">{r.price ?? "—"}</td>
                      <td className="py-1.5">{r.sl_pips ?? "—"} / {r.tp_pips ?? "—"}</td>
                      <td className="py-1.5 text-slate-300">{r.reason || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <div className="text-xs text-bunker-muted">İlk 5 dakikalık otonom tarama turu tamamlandığında H1/H4 strateji durumları burada görünecektir.</div>
            )}
          </div>

          {/* Episodik Dersler (Reflection Loop) */}
          <div className="bg-bunker-900/80 border border-bunker-800 rounded-xl p-4">
            <h3 className="text-xs font-bold uppercase text-bunker-muted mb-3">
              Episodik Hafıza & Çıkarılan Dersler ({er?.total_stored ?? 0} kayıt)
            </h3>
            {er?.items && er.items.length > 0 ? (
              <div className="space-y-2">
                {er.items.map((it, idx) => (
                  <div key={idx} className="text-xs bg-bunker-800/60 border border-bunker-700/60 rounded-lg p-2.5 flex items-start justify-between gap-3">
                    <span className="text-slate-200">{it.lesson}</span>
                    <span className={`font-mono font-bold shrink-0 ${it.pnl_usd >= 0 ? "text-emerald-400" : "text-rose-400"}`}>
                      ${it.pnl_usd.toFixed(2)}
                    </span>
                  </div>
                ))}
              </div>
            ) : (
              <div className="text-xs text-bunker-muted">Henüz kaydedilmiş episodik ders yok; işlemler kapandıkça otomatik dolacaktır.</div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
