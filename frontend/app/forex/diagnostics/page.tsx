"use client";

import { useCallback, useEffect, useState } from "react";
import { apiFetch } from "../../lib/api";

type BucketStat = { count: number; loss_usd: number; avg_loss_usd?: number };

export default function ForexDiagnosticsPage() {
  const [period, setPeriod] = useState<"today" | "7d" | "all">("today");
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [decisionFilter, setDecisionFilter] = useState<string>("ALL");
  const [copied, setCopied] = useState(false);

  const loadAudit = useCallback(async (p: string = period) => {
    setLoading(true);
    setError(null);
    try {
      const res = await apiFetch(`/api/forex/diagnostics/today-audit?period=${encodeURIComponent(p)}&limit=200`);
      setData(res);
    } catch (e: any) {
      setError(e?.message || "Teşhis verisi alınamadı");
    } finally {
      setLoading(false);
    }
  }, [period]);

  useEffect(() => {
    loadAudit(period);
  }, [period, loadAudit]);

  const handleCopyJson = async () => {
    if (!data) return;
    try {
      await navigator.clipboard.writeText(JSON.stringify(data, null, 2));
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // ignore clipboard errors
    }
  };

  const acc = data?.account || {};
  const ts = data?.trades_summary || {};
  const opp = data?.scans?.opportunity_scan || {};
  const evBlocked: any[] = data?.scans?.ev_shield_blocked || [];
  const lf = data?.losing_trades_forensics || {};
  const decisions: any[] = data?.decisions?.items || [];
  const filteredDecisions = decisionFilter === "ALL"
    ? decisions
    : decisions.filter((d) => String(d.category || "").toUpperCase() === decisionFilter);

  return (
    <div className="p-4 sm:p-6 max-w-7xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
        <div>
          <h1 className="font-mono text-xl sm:text-2xl font-bold text-white tracking-tight">
            Teşhis &amp; Zarar Analizi
          </h1>
          <p className="text-xs sm:text-sm text-bunker-muted mt-0.5">
            Taramalar, karar günlüğü, EV Kalkanı ve zararla kapanan işlemlerin kök-neden kırılımı
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {(["today", "7d", "all"] as const).map((p) => (
            <button
              key={p}
              type="button"
              onClick={() => setPeriod(p)}
              className={`px-3 py-1.5 rounded-lg font-mono text-xs font-bold border transition-colors ${
                period === p
                  ? "bg-neon-green/15 border-neon-green/40 text-neon-green"
                  : "bg-bunker-900 border-bunker-700 text-bunker-muted hover:text-white"
              }`}
            >
              {p === "today" ? "Bugün" : p === "7d" ? "Son 7 Gün" : "Tümü"}
            </button>
          ))}
          <button
            type="button"
            onClick={() => loadAudit(period)}
            disabled={loading}
            className="px-3 py-1.5 rounded-lg font-mono text-xs font-bold bg-cyan-500/15 border border-cyan-400/40 text-cyan-300 hover:bg-cyan-500/25 disabled:opacity-50"
          >
            {loading ? "Yükleniyor..." : "Yenile"}
          </button>
          <button
            type="button"
            onClick={handleCopyJson}
            disabled={!data}
            className="px-3 py-1.5 rounded-lg font-mono text-xs font-bold bg-bunker-800 border border-bunker-700 text-white hover:border-bunker-500 disabled:opacity-40"
          >
            {copied ? "Kopyalandı ✓" : "JSON Kopyala"}
          </button>
        </div>
      </div>

      {error && (
        <div className="p-4 rounded-xl bg-red-500/10 border border-red-500/30 text-red-300 font-mono text-sm">
          {error}
        </div>
      )}

      {/* KPI Cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <div className="p-4 rounded-xl bg-bunker-900/90 border border-bunker-800">
          <p className="font-mono text-2xs uppercase text-bunker-muted">Özkaynak / Bakiye</p>
          <p className="font-mono text-lg sm:text-xl font-bold text-white mt-1">
            ${Number(acc.equity ?? 0).toFixed(2)}
          </p>
          <p className="font-mono text-xs text-bunker-muted mt-0.5">
            Bakiye: ${Number(acc.balance ?? 0).toFixed(2)} · Açık: {acc.open_positions_count ?? 0}
          </p>
        </div>

        <div className="p-4 rounded-xl bg-bunker-900/90 border border-bunker-800">
          <p className="font-mono text-2xs uppercase text-bunker-muted">Net K/Z ({period === "today" ? "Bugün" : period})</p>
          <p className={`font-mono text-lg sm:text-xl font-bold mt-1 ${(ts.net_pnl_usd ?? 0) >= 0 ? "text-neon-green" : "text-red-400"}`}>
            {(ts.net_pnl_usd ?? 0) >= 0 ? "+" : ""}${Number(ts.net_pnl_usd ?? 0).toFixed(2)}
          </p>
          <p className="font-mono text-xs text-bunker-muted mt-0.5">
            Brüt: +${Number(ts.gross_profit_usd ?? 0).toFixed(2)} / -${Number(ts.gross_loss_usd ?? 0).toFixed(2)}
          </p>
        </div>

        <div className="p-4 rounded-xl bg-bunker-900/90 border border-bunker-800">
          <p className="font-mono text-2xs uppercase text-bunker-muted">Başarı Oranı / PF</p>
          <p className="font-mono text-lg sm:text-xl font-bold text-cyan-300 mt-1">
            %{Number(ts.win_rate_pct ?? 0).toFixed(1)} · PF {ts.profit_factor ?? "—"}
          </p>
          <p className="font-mono text-xs text-bunker-muted mt-0.5">
            {ts.wins ?? 0} Kâr / {ts.losses ?? 0} Zarar ({ts.closed_count ?? 0} işlem)
          </p>
        </div>

        <div className="p-4 rounded-xl bg-bunker-900/90 border border-bunker-800">
          <p className="font-mono text-2xs uppercase text-bunker-muted">Fırsat Taraması / EV Bloke</p>
          <p className="font-mono text-lg sm:text-xl font-bold text-white mt-1">
            {opp.scanned_count ?? 0} taranan · {evBlocked.length} bloke
          </p>
          <p className="font-mono text-xs text-bunker-muted mt-0.5">
            Açılan: {(opp.opened || []).length} · Atlanan: {(opp.skipped || []).length}
          </p>
        </div>
      </div>

      {/* Scans & EV Shield */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="p-4 rounded-xl bg-bunker-900/90 border border-bunker-800 space-y-3">
          <h2 className="font-mono text-sm font-bold text-cyan-300 uppercase tracking-wider">
            Son Fırsat Taraması ({opp.status || "—"})
          </h2>
          {Object.keys(opp.skipped_by_reason || {}).length > 0 ? (
            <div className="flex flex-wrap gap-2">
              {Object.entries(opp.skipped_by_reason as Record<string, number>).map(([reason, cnt]) => (
                <span key={reason} className="px-2.5 py-1 rounded-lg bg-bunker-950 border border-bunker-700 font-mono text-xs text-amber-300">
                  {reason}: <strong>{cnt}</strong>
                </span>
              ))}
            </div>
          ) : (
            <p className="text-xs text-bunker-muted font-mono">Atlanan aday yok.</p>
          )}
          <div className="space-y-1.5 max-h-52 overflow-y-auto">
            {(opp.skipped || []).map((s: any, idx: number) => (
              <div key={`${s.symbol}-${idx}`} className="flex items-center justify-between gap-2 text-xs font-mono px-2.5 py-1.5 rounded-lg bg-bunker-950/70 border border-bunker-800">
                <span className="text-white font-bold">{s.symbol}</span>
                <span className="text-bunker-muted truncate">{s.reason}</span>
              </div>
            ))}
          </div>
        </div>

        <div className="p-4 rounded-xl bg-bunker-900/90 border border-bunker-800 space-y-3">
          <h2 className="font-mono text-sm font-bold text-red-400 uppercase tracking-wider">
            EV Kalkanı Bloke Semboller ({evBlocked.length})
          </h2>
          {evBlocked.length === 0 ? (
            <p className="text-xs text-bunker-muted font-mono">Şu anda EV Kalkanı ile bloke edilen sembol yok.</p>
          ) : (
            <div className="space-y-2">
              {evBlocked.map((b: any) => (
                <div key={b.symbol} className="p-2.5 rounded-lg bg-red-500/10 border border-red-500/25 flex items-center justify-between gap-2 font-mono text-xs">
                  <div>
                    <span className="text-white font-bold">{b.display || b.symbol}</span>
                    <p className="text-red-300/90 text-2xs mt-0.5">{b.reason}</p>
                  </div>
                  <div className="text-right shrink-0">
                    <span className="text-red-400 font-bold">${Number(b.net_usd ?? 0).toFixed(2)}</span>
                    <p className="text-bunker-muted text-2xs">WR %{Number(b.win_rate ?? 0).toFixed(1)} ({b.n} işlem)</p>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Losing Trades Root-Cause Breakdown */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="p-4 rounded-xl bg-bunker-900/90 border border-bunker-800 space-y-2.5">
          <h3 className="font-mono text-xs font-bold text-white uppercase tracking-wider">Stratejiye Göre Zarar</h3>
          {Object.entries((lf.by_strategy || {}) as Record<string, BucketStat>).map(([k, v]) => (
            <div key={k} className="flex items-center justify-between text-xs font-mono py-1 border-b border-bunker-800/70">
              <span className="text-bunker-muted truncate pr-2">{k}</span>
              <span className="text-red-400 font-bold shrink-0">
                ${v.loss_usd.toFixed(2)} <span className="text-bunker-muted font-normal">({v.count})</span>
              </span>
            </div>
          ))}
        </div>

        <div className="p-4 rounded-xl bg-bunker-900/90 border border-bunker-800 space-y-2.5">
          <h3 className="font-mono text-xs font-bold text-white uppercase tracking-wider">Sembole Göre Zarar</h3>
          <div className="max-h-56 overflow-y-auto space-y-1">
            {Object.entries((lf.by_symbol || {}) as Record<string, BucketStat>).map(([k, v]) => (
              <div key={k} className="flex items-center justify-between text-xs font-mono py-1 border-b border-bunker-800/70">
                <span className="text-white font-bold">{k}</span>
                <span className="text-red-400 font-bold">
                  ${v.loss_usd.toFixed(2)} <span className="text-bunker-muted font-normal">({v.count})</span>
                </span>
              </div>
            ))}
          </div>
        </div>

        <div className="p-4 rounded-xl bg-bunker-900/90 border border-bunker-800 space-y-2.5">
          <h3 className="font-mono text-xs font-bold text-white uppercase tracking-wider">Kapanış Sebebi &amp; Yön</h3>
          {Object.entries((lf.by_reason || {}) as Record<string, BucketStat>).map(([k, v]) => (
            <div key={k} className="flex items-center justify-between text-xs font-mono py-1 border-b border-bunker-800/70">
              <span className="text-bunker-muted truncate pr-2">{k}</span>
              <span className="text-red-400 font-bold shrink-0">${v.loss_usd.toFixed(2)} ({v.count})</span>
            </div>
          ))}
          <div className="pt-2 space-y-1">
            {Object.entries((lf.by_direction || {}) as Record<string, BucketStat>).map(([k, v]) => (
              <div key={k} className="flex items-center justify-between text-xs font-mono">
                <span className={k === "SELL" ? "text-red-300 font-bold" : "text-neon-green font-bold"}>{k}</span>
                <span className="text-red-400 font-bold">${v.loss_usd.toFixed(2)} ({v.count})</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Losing Trades Table */}
      <div className="p-4 rounded-xl bg-bunker-900/90 border border-bunker-800 space-y-3">
        <h2 className="font-mono text-sm font-bold text-white uppercase tracking-wider">
          Zararla Kapanan İşlemler ({lf.total_losses ?? 0} · ${Number(lf.total_loss_usd ?? 0).toFixed(2)})
        </h2>
        <div className="overflow-x-auto">
          <table className="w-full text-left font-mono text-xs">
            <thead>
              <tr className="border-b border-bunker-800 text-bunker-muted">
                <th className="py-2 pr-3">Sembol</th>
                <th className="py-2 pr-3">Yön</th>
                <th className="py-2 pr-3">Strateji</th>
                <th className="py-2 pr-3">Lot</th>
                <th className="py-2 pr-3">Giriş → Çıkış</th>
                <th className="py-2 pr-3">Sebep</th>
                <th className="py-2 text-right">Zarar</th>
              </tr>
            </thead>
            <tbody>
              {(lf.trades || []).map((t: any, i: number) => (
                <tr key={`${t.ticket || i}`} className="border-b border-bunker-800/50 hover:bg-bunker-800/30">
                  <td className="py-2 pr-3 font-bold text-white">{t.symbol}</td>
                  <td className={`py-2 pr-3 font-bold ${t.direction === "SELL" ? "text-red-400" : "text-neon-green"}`}>{t.direction}</td>
                  <td className="py-2 pr-3 text-bunker-muted">{t.strategy_label || t.strategy}</td>
                  <td className="py-2 pr-3 text-white">{t.lots}</td>
                  <td className="py-2 pr-3 text-bunker-muted">{t.entry_price} → {t.exit_price}</td>
                  <td className="py-2 pr-3 text-amber-300">{t.reason}</td>
                  <td className="py-2 text-right font-bold text-red-400">${Number(t.pnl_usd).toFixed(2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Decision Logs */}
      <div className="p-4 rounded-xl bg-bunker-900/90 border border-bunker-800 space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="font-mono text-sm font-bold text-white uppercase tracking-wider">
            Son Karar Günlüğü ({filteredDecisions.length})
          </h2>
          <div className="flex gap-1.5">
            {["ALL", "GATE", "ENTRY", "SCAN"].map((cat) => (
              <button
                key={cat}
                type="button"
                onClick={() => setDecisionFilter(cat)}
                className={`px-2.5 py-1 rounded-md font-mono text-2xs font-bold border ${
                  decisionFilter === cat
                    ? "bg-cyan-500/20 border-cyan-400/50 text-cyan-300"
                    : "bg-bunker-950 border-bunker-800 text-bunker-muted hover:text-white"
                }`}
              >
                {cat}
              </button>
            ))}
          </div>
        </div>
        <div className="space-y-1.5 max-h-80 overflow-y-auto">
          {filteredDecisions.slice(0, 80).map((d: any, idx: number) => (
            <div key={`${d.id || idx}-${idx}`} className="p-2 rounded-lg bg-bunker-950/70 border border-bunker-800/80 font-mono text-xs flex flex-col sm:flex-row sm:items-center gap-1.5 sm:gap-3">
              <span className="text-bunker-muted text-2xs shrink-0">{d.time}</span>
              <span className={`px-1.5 py-0.5 rounded text-2xs font-bold shrink-0 w-fit ${
                d.category === "GATE" ? "bg-amber-500/15 text-amber-300"
                : d.category === "ENTRY" ? "bg-neon-green/15 text-neon-green"
                : "bg-bunker-800 text-bunker-muted"
              }`}>
                {d.category}
              </span>
              <span className="text-white break-words">{d.message}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
