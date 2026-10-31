"use client";

import { useEffect, useState, useCallback } from "react";
import { apiFetch } from "../lib/api";
import { Card, Badge, Button } from "../components/ui";
import SpotChartModal from "./SpotChartModal";

type SignalItem = {
  id: number;
  symbol: string;
  timeframe: string;
  strategy: string;
  strategy_label: string;
  entry_price: number;
  current_price: number;
  target_price: number;
  stop_price: number;
  score: number;
  kdj_j: number | null;
  status: "OPEN" | "WIN_TP" | "LOSS_SL" | "EXPIRED";
  pnl_pct: number;
  mfe_pct: number;
  net_pnl_try: number;
  detected_at: string;
  exit_time: string | null;
  details: {
    note?: string;
    tp_pct?: number;
    sl_pct?: number;
  };
};

type DashboardData = {
  portfolio: {
    initial_balance_try: number;
    current_balance_try: number;
    free_balance_try: number;
    in_positions_try: number;
    realized_pnl_try: number;
    unrealized_pnl_try: number;
    growth_pct: number;
    trade_size_try: number;
    open_positions_count: number;
  };
  metrics: {
    total_signals: number;
    closed_count: number;
    open_count: number;
    win_count: number;
    loss_count: number;
    win_rate_pct: number;
  };
  signals: SignalItem[];
  last_scan_time: number;
};

type ActiveStrategy = {
  code: string;
  label: string;
  score: number;
  description: string;
  evidence: string;
  timeframes: string[];
};

type StrategiesData = {
  count: number;
  symbols_count: number;
  timeframes: Array<{ code: string; label: string; tp_pct: number; sl_pct: number }>;
  trade_size_try: number;
  initial_portfolio_try: number;
  commission_rate: number;
  strategies: ActiveStrategy[];
};

export default function SpotMonitorPage() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [scanning, setScanning] = useState(false);
  const [activeTab, setActiveTab] = useState<"ACTIVE" | "HISTORY">("ACTIVE");
  const [selectedModalSignal, setSelectedModalSignal] = useState<SignalItem | null>(null);
  const [strategies, setStrategies] = useState<StrategiesData | null>(null);

  useEffect(() => {
    apiFetch("/api/spot-monitor/strategies")
      .then((res) => setStrategies(res as StrategiesData))
      .catch((err) => console.error("Aktif stratejiler yüklenirken hata:", err));
  }, []);

  const loadDashboard = useCallback(async () => {
    try {
      const res = (await apiFetch("/api/spot-monitor/dashboard")) as DashboardData;
      setData(res);
    } catch (err) {
      console.error("Dashboard yüklenirken hata:", err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadDashboard();
    const interval = setInterval(loadDashboard, 15000); // 15 saniyede bir otomatik yenile
    return () => clearInterval(interval);
  }, [loadDashboard]);

  const handleScanNow = async () => {
    setScanning(true);
    try {
      await apiFetch("/api/spot-monitor/scan-now", { method: "POST" });
      setTimeout(async () => {
        await loadDashboard();
        setScanning(false);
      }, 3000);
    } catch (err) {
      console.error("Tarama tetikleme hatası:", err);
      setScanning(false);
    }
  };

  const openSignals = (data?.signals || []).filter((s) => s.status === "OPEN");
  const historySignals = (data?.signals || []).filter((s) => s.status !== "OPEN");

  const pnlColor = (val: number) => {
    if (val > 0) return "text-emerald-400";
    if (val < 0) return "text-rose-400";
    return "text-slate-300";
  };

  return (
    <div className="space-y-6 p-4 md:p-8 max-w-7xl mx-auto">
      {/* BAŞLIK & ŞİMDİ TARA KOKPİTİ */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-bunker-800 pb-5">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-xl md:text-2xl font-mono font-bold text-white tracking-tight">
              Binance TR Spot Monitor
            </h1>
            <Badge tone="info" className="font-mono text-[10px]">MTF LIVE</Badge>
          </div>
          <p className="text-xs text-bunker-muted mt-1">
            KDJ Dip + SuperTrend + EMA50 Sekmesi + BB-KC Sıkışma Kırılımı + STC Döngüsü + Zero-Lag MACD canlı takibi ve 5.000 TL portföy simülatörü.
          </p>
        </div>

        <div className="flex items-center gap-3">
          <Button
            variant="primary"
            onClick={handleScanNow}
            disabled={scanning}
            className="flex items-center gap-2 bg-gradient-to-r from-cyan-600 to-blue-600 hover:from-cyan-500 hover:to-blue-500 text-white font-mono text-xs px-4 py-2"
          >
            <span>{scanning ? "⚡ Taranıyor..." : "🔄 Şimdi Tara"}</span>
          </Button>
        </div>
      </div>

      {/* PORTFÖY SİMÜLASYONU KARTLARI (5.000 TL BAZLI, 300 TL SABİT İŞLEM) */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3.5">
        {/* 1. PORTFÖY BAKİYESİ */}
        <Card className="p-4 bg-bunker-900/90 border-bunker-800">
          <div className="flex items-center justify-between">
            <p className="text-[11px] font-mono uppercase text-bunker-muted">Portföy Bakiyesi</p>
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-bunker-800 text-bunker-muted font-mono">
              Başlangıç: ₺5.000
            </span>
          </div>
          <div className="flex items-baseline gap-2 mt-1.5">
            <span className="text-2xl font-bold font-mono text-white">
              ₺{(data?.portfolio.current_balance_try || 5000).toLocaleString("tr-TR", { minimumFractionDigits: 2 })}
            </span>
          </div>
          <div className="mt-2 pt-2 border-t border-bunker-800/80 flex items-center justify-between text-[11px] font-mono">
            <span className="text-bunker-muted">Serbest Bakiye:</span>
            <span className="text-cyan-400 font-bold">
              ₺{(data?.portfolio.free_balance_try ?? 5000).toLocaleString("tr-TR", { minimumFractionDigits: 2 })}
            </span>
          </div>
        </Card>

        {/* 2. NET PORTFÖY BÜYÜMESİ */}
        <Card className="p-4 bg-bunker-900/90 border-bunker-800">
          <p className="text-[11px] font-mono uppercase text-bunker-muted">Net Portföy Büyümesi</p>
          <div className="flex items-baseline gap-2 mt-1.5">
            <span className={`text-2xl font-bold font-mono ${pnlColor(data?.portfolio.growth_pct || 0)}`}>
              %{data?.portfolio.growth_pct?.toFixed(2) || "0.00"}
            </span>
          </div>
          <div className="mt-2 pt-2 border-t border-bunker-800/80 flex items-center justify-between text-[11px] font-mono">
            <span className="text-bunker-muted">Net Kâr (TL):</span>
            <span className={`font-medium ${pnlColor((data?.portfolio.realized_pnl_try || 0) + (data?.portfolio.unrealized_pnl_try || 0))}`}>
              ₺{((data?.portfolio.realized_pnl_try || 0) + (data?.portfolio.unrealized_pnl_try || 0)).toFixed(2)}
            </span>
          </div>
        </Card>

        {/* 3. İŞLEM BAŞARI ORANI */}
        <Card className="p-4 bg-bunker-900/90 border-bunker-800">
          <p className="text-[11px] font-mono uppercase text-bunker-muted">İşlem Başarı Oranı</p>
          <div className="flex items-baseline gap-2 mt-1.5">
            <span className="text-2xl font-bold font-mono text-cyan-400">
              %{data?.metrics.win_rate_pct?.toFixed(1) || "0.0"}
            </span>
          </div>
          <div className="mt-2 pt-2 border-t border-bunker-800/80 flex items-center justify-between text-[11px] font-mono">
            <span className="text-bunker-muted">Sonuç:</span>
            <span>
              <span className="text-emerald-400 font-medium">{data?.metrics.win_count || 0} Başarılı</span> / <span className="text-rose-400 font-medium">{data?.metrics.loss_count || 0} Stop</span>
            </span>
          </div>
        </Card>

        {/* 4. İŞLEM BÜYÜKLÜĞÜ & POZİSYONDAKİ TUTAR */}
        <Card className="p-4 bg-bunker-900/90 border-bunker-800">
          <p className="text-[11px] font-mono uppercase text-bunker-muted">İşlem Büyüklüğü</p>
          <div className="flex items-baseline gap-2 mt-1.5">
            <span className="text-2xl font-bold font-mono text-amber-400">
              ₺300,00
            </span>
          </div>
          <div className="mt-2 pt-2 border-t border-bunker-800/80 flex items-center justify-between text-[11px] font-mono">
            <span className="text-bunker-muted">Pozisyondaki:</span>
            <span className="text-amber-300 font-medium">
              {data?.portfolio.open_positions_count || 0} Aktif (₺{(data?.portfolio.in_positions_try ?? ((data?.portfolio.open_positions_count || 0) * 300)).toLocaleString("tr-TR", { minimumFractionDigits: 2 })})
            </span>
          </div>
        </Card>
      </div>

      {/* AKTİF TARAMA STRATEJİLERİ (canlı sistemden /strategies ile senkron) */}
      <div className="rounded-xl border border-bunker-800 bg-bunker-900/80 p-4">
        <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
          <div className="flex items-center gap-2">
            <h2 className="font-mono text-xs uppercase tracking-wide text-bunker-muted">
              🔬 Aktif Tarama Stratejileri
            </h2>
            <Badge tone="info" className="font-mono text-[10px]">
              {strategies?.count ?? "..."} strateji aktif
            </Badge>
          </div>
          <p className="text-[10px] font-mono text-bunker-muted">
            {strategies?.symbols_count ?? 18} sembol × {strategies?.timeframes.length ?? 3} TF
            {" · "}₺{strategies?.trade_size_try ?? 300}/işlem
            {" · "}Kom. %{((strategies?.commission_rate ?? 0.0004) * 2 * 100).toFixed(2)} round-trip
          </p>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-2.5">
          {strategies?.strategies.map((st, i) => (
            <div key={st.code} className="rounded-lg border border-bunker-800 bg-bunker-950/60 p-2.5">
              <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-1.5 min-w-0">
                  <span className="inline-flex px-1.5 py-0.5 rounded text-[9px] font-bold bg-bunker-800 text-bunker-muted">
                    #{i + 1}
                  </span>
                  <span className="text-[11px] font-semibold text-slate-200 truncate" title={st.label}>
                    {st.label}
                  </span>
                </div>
                <span className="inline-flex px-1.5 py-0.5 rounded text-[9px] font-bold shrink-0 bg-cyan-950/80 text-cyan-300 border border-cyan-800/50">
                  {st.score.toFixed(0)}p
                </span>
              </div>
              <p className="text-[10px] text-bunker-muted mt-1.5 leading-snug">{st.description}</p>
              <p className="text-[9px] text-emerald-400/80 mt-1 font-mono">📈 {st.evidence}</p>
            </div>
          ))}
        </div>
        <p className="text-[9px] font-mono text-bunker-muted mt-2.5">
          Öncelik sırası yukarıdan aşağıya ilerler; aynı sembolde ilk eşleşen kural sinyal üretir.
          Kâr/stop kademeleri: {strategies?.timeframes.map((t) => `${t.code} (TP %${t.tp_pct}/SL %${t.sl_pct})`).join(" · ")}
        </p>
      </div>

      {/* SEKMELER: AKTİF İŞLEMLER / TARAMA GEÇMİŞİ & BAŞARI TABLOSU */}
      <div className="flex items-center gap-2 border-b border-bunker-800 pb-2">
        <button
          type="button"
          onClick={() => setActiveTab("ACTIVE")}
          className={`px-4 py-2 rounded-lg font-mono text-xs font-semibold transition-colors flex items-center gap-2 ${
            activeTab === "ACTIVE"
              ? "bg-cyan-500/20 text-cyan-300 border border-cyan-500/40"
              : "text-bunker-muted hover:text-white hover:bg-bunker-800"
          }`}
        >
          <span>🎯</span> Aktif Sinyaller ({openSignals.length})
        </button>

        <button
          type="button"
          onClick={() => setActiveTab("HISTORY")}
          className={`px-4 py-2 rounded-lg font-mono text-xs font-semibold transition-colors flex items-center gap-2 ${
            activeTab === "HISTORY"
              ? "bg-cyan-500/20 text-cyan-300 border border-cyan-500/40"
              : "text-bunker-muted hover:text-white hover:bg-bunker-800"
          }`}
        >
          <span>📊</span> Tarama Geçmişi & Kâr Tablosu ({historySignals.length})
        </button>
      </div>

      {/* İÇERİK TABLOSU */}
      <div className="overflow-x-auto rounded-xl border border-bunker-800 bg-bunker-900/80">
        <table className="w-full text-left font-mono text-xs">
          <thead className="bg-bunker-950/80 text-bunker-muted uppercase text-[10px] border-b border-bunker-800">
            <tr>
              <th className="py-3 px-4">Zaman / Sembol</th>
              <th className="py-3 px-4">TF</th>
              <th className="py-3 px-4">Strateji</th>
              <th className="py-3 px-4">Giriş Fiyatı</th>
              <th className="py-3 px-4">Anlık / Çıkış</th>
              <th className="py-3 px-4">Hedef / Stop</th>
              <th className="py-3 px-4">Net Kâr (300₺)</th>
              <th className="py-3 px-4">Durum</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-bunker-800/60">
            {loading ? (
              <tr>
                <td colSpan={8} className="text-center py-10 text-bunker-muted">
                  Veriler yükleniyor...
                </td>
              </tr>
            ) : (activeTab === "ACTIVE" ? openSignals : historySignals).length === 0 ? (
              <tr>
                <td colSpan={8} className="text-center py-10 text-bunker-muted">
                  {activeTab === "ACTIVE"
                    ? "Şu an aktif takip edilen sinyal yok. 'Şimdi Tara' butonuna basabilirsiniz."
                    : "Henüz sonuçlanmış geçmiş işlem kaydı bulunmuyor."}
                </td>
              </tr>
            ) : (
              (activeTab === "ACTIVE" ? openSignals : historySignals).map((s) => {
                const isWin = s.status === "WIN_TP";
                const isLoss = s.status === "LOSS_SL";
                return (
                  <tr key={s.id} className="hover:bg-bunker-800/40 transition-colors">
                    <td className="py-3 px-4">
                      <div className="flex flex-col">
                        <button
                          type="button"
                          onClick={() => setSelectedModalSignal(s)}
                          className="text-left group flex items-center gap-1.5 hover:opacity-90 transition-opacity"
                          title="Canlı Grafik, KDJ ve EMA 50 Göstergelerini Aç"
                        >
                          <span className="font-bold text-white group-hover:text-cyan-400 text-sm underline decoration-dotted decoration-bunker-600 underline-offset-4 cursor-pointer">
                            {s.symbol}
                          </span>
                          <span className="text-xs text-cyan-400 opacity-70 group-hover:opacity-100 group-hover:scale-110 transition-all">
                            📊
                          </span>
                        </button>
                        <span className="text-[10px] text-bunker-muted">
                          {new Date(s.detected_at).toLocaleTimeString("tr-TR", { hour: "2-digit", minute: "2-digit" })}
                        </span>
                      </div>
                    </td>
                    <td className="py-3 px-4">
                      <span className="inline-flex px-1.5 py-0.5 rounded text-[10px] font-bold bg-cyan-950/80 text-cyan-300 border border-cyan-800/50">
                        {s.timeframe}
                      </span>
                    </td>
                    <td className="py-3 px-4">
                      <div className="flex flex-col">
                        <span className="font-medium text-slate-200">{s.strategy_label}</span>
                        {s.details?.note && (
                          <span className="text-[10px] text-bunker-muted">{s.details.note}</span>
                        )}
                      </div>
                    </td>
                    <td className="py-3 px-4 text-slate-300">
                      ₺{s.entry_price > 10 ? s.entry_price.toLocaleString("tr-TR", { minimumFractionDigits: 2 }) : s.entry_price}
                    </td>
                    <td className="py-3 px-4">
                      <span className={`font-bold ${pnlColor(s.pnl_pct)}`}>
                        ₺{s.current_price > 10 ? s.current_price.toLocaleString("tr-TR", { minimumFractionDigits: 2 }) : s.current_price}
                        <span className="text-[10px] ml-1.5">
                          ({s.pnl_pct >= 0 ? "+" : ""}{s.pnl_pct.toFixed(2)}%)
                        </span>
                      </span>
                    </td>
                    <td className="py-3 px-4">
                      <div className="flex flex-col text-[10px]">
                        <span className="text-emerald-400">TP: ₺{s.target_price > 10 ? s.target_price.toLocaleString("tr-TR", { minimumFractionDigits: 2 }) : s.target_price}</span>
                        <span className="text-rose-400">SL: ₺{s.stop_price > 10 ? s.stop_price.toLocaleString("tr-TR", { minimumFractionDigits: 2 }) : s.stop_price}</span>
                      </div>
                    </td>
                    <td className="py-3 px-4">
                      <div className="flex flex-col">
                        <span className={`font-bold ${pnlColor(s.net_pnl_try)}`}>
                          {s.net_pnl_try >= 0 ? "+" : ""}₺{s.net_pnl_try.toFixed(2)}
                        </span>
                        <span className="text-[9px] text-bunker-muted">Net (Kom. Düşülmüş)</span>
                      </div>
                    </td>
                    <td className="py-3 px-4">
                      {s.status === "OPEN" ? (
                        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-bold bg-amber-500/10 text-amber-300 border border-amber-500/30">
                          <span className="w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse" />
                          AÇIK
                        </span>
                      ) : isWin ? (
                        <span className="inline-flex px-2 py-0.5 rounded text-[10px] font-bold bg-emerald-500/20 text-emerald-300 border border-emerald-500/40">
                          🎯 TP ALINDI
                        </span>
                      ) : isLoss ? (
                        <span className="inline-flex px-2 py-0.5 rounded text-[10px] font-bold bg-rose-500/20 text-rose-300 border border-rose-500/40">
                          🛑 STOP OLDU
                        </span>
                      ) : (
                        <span className="inline-flex px-2 py-0.5 rounded text-[10px] font-bold bg-slate-800 text-slate-300">
                          KAPANDI
                        </span>
                      )}
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>

      {/* CANLI GRAFİK & KDJ / EMA 50 AÇILIR PENCERESİ (MODAL) */}
      {selectedModalSignal && (
        <SpotChartModal
          signal={selectedModalSignal}
          onClose={() => setSelectedModalSignal(null)}
        />
      )}
    </div>
  );
}
