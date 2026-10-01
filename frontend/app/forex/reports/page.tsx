"use client";

import React, { useState, useEffect, useMemo } from "react";
import Link from "next/link";
import { apiFetch } from "../../lib/api";

interface ClosedTrade {
  id: string;
  symbol: string;
  display: string;
  direction: "BUY" | "SELL";
  lots: number;
  entry_price: number;
  exit_price: number;
  open_time: string;
  exit_time: string;
  duration_sec?: number;
  duration_human?: string;
  exit_reason: string;
  exit_reason_title?: string;
  pnl_usd: number;
  pnl_pips: number;
  balance_after?: number;
  outcome?: string;
  sl_price?: number;
  tp_price?: number;
  score?: number;
  strategy?: string;
}

interface ReportKPI {
  total_trades: number;
  wins: number;
  losses: number;
  win_rate: number;
  total_pnl_usd: number;
  total_pnl_pips: number;
  gross_profit_usd: number;
  gross_loss_usd: number;
  profit_factor: number;
  avg_trade_usd: number;
  avg_win_usd: number;
  avg_loss_usd: number;
  max_win_usd: number;
  max_loss_usd: number;
  total_lots: number;
  balance: number;
  equity: number;
  open_positions_count: number;
  open_pnl_usd: number;
}

export default function ForexReportsPage() {
  const [trades, setTrades] = useState<ClosedTrade[]>([]);
  const [openPositions, setOpenPositions] = useState<any[]>([]);
  const [kpi, setKpi] = useState<ReportKPI | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [autoRefresh, setAutoRefresh] = useState<boolean>(true);
  const [isExporting, setIsExporting] = useState<boolean>(false);

  // Filtreler
  const [selectedSymbol, setSelectedSymbol] = useState<string>("ALL");
  const [selectedOutcome, setSelectedOutcome] = useState<string>("ALL");
  const [selectedReason, setSelectedReason] = useState<string>("ALL");
  const [searchQuery, setSearchQuery] = useState<string>("");

  const fetchReport = async () => {
    try {
      const qParams = new URLSearchParams();
      if (selectedSymbol !== "ALL") qParams.append("symbol", selectedSymbol);
      if (selectedOutcome !== "ALL") qParams.append("outcome", selectedOutcome);
      if (selectedReason !== "ALL") qParams.append("reason", selectedReason);
      if (searchQuery.trim()) qParams.append("search", searchQuery.trim());

      const url = `/api/forex/auto-paper/trades?${qParams.toString()}`;
      const res = await apiFetch(url);
      if (res) {
        setTrades(res.trades || []);
        setKpi(res.kpi || null);
        setOpenPositions(res.open_positions || []);
      }
    } catch (err) {
      console.error("Forex rapor verisi alınamadı:", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchReport();
  }, [selectedSymbol, selectedOutcome, selectedReason, searchQuery]);

  useEffect(() => {
    if (!autoRefresh) return;
    const interval = setInterval(fetchReport, 3000);
    return () => clearInterval(interval);
  }, [autoRefresh, selectedSymbol, selectedOutcome, selectedReason, searchQuery]);

  // Client-Side CSV İndirme
  const downloadCsv = () => {
    setIsExporting(true);
    try {
      const headers = [
        "Bilet No",
        "Parite",
        "Sembol",
        "Yön",
        "Lot",
        "Radar Skoru",
        "Giriş Fiyatı",
        "Giriş Zamanı (UTC)",
        "Çıkış Fiyatı",
        "Çıkış Zamanı (UTC)",
        "Süre",
        "Çıkış Nedeni",
        "SL Seviyesi",
        "TP Seviyesi",
        "Kâr/Zarar (Pip)",
        "Net Getiri (USD)",
        "Bakiye Sonrası (USD)",
        "Sonuç",
      ];

      const rows = trades.map((t: any) => {
        const pnl = Number(t.pnl_usd ?? t.profit ?? 0);
        const pips = Number(t.pnl_pips ?? 0);
        const balAfter = t.balance_after != null ? Number(t.balance_after) : null;
        return [
          t.id || "-",
          t.display || t.symbol || "-",
          t.symbol || "-",
          t.direction || "BUY",
          t.lots || 0.01,
          t.score || "-",
          t.entry_price || "-",
          t.open_time || "-",
          t.exit_price || "-",
          t.exit_time || "-",
          t.duration_human || (t.duration_sec ? `${t.duration_sec} sn` : "-"),
          t.exit_reason_title || t.exit_reason || "IC Markets MT5",
          t.sl_price || "-",
          t.tp_price || "-",
          `${pips >= 0 ? "+" : ""}${pips.toFixed(1)}`,
          `${pnl >= 0 ? "+" : ""}${pnl.toFixed(2)}`,
          balAfter !== null ? `$${balAfter.toFixed(2)}` : "-",
          pnl >= 0 ? "KAZANÇ (WIN)" : "KAYIP (LOSS)",
        ];
      });

      // Excel uyumluluğu için UTF-8 BOM ve noktalı virgül (;) ayırıcı
      const csvContent =
        "\uFEFF" +
        [headers.join(";"), ...rows.map((r) => r.map((cell) => `"${cell}"`).join(";"))].join("\r\n");

      const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      const dateStr = new Date().toISOString().slice(0, 10);
      link.setAttribute("href", url);
      link.setAttribute("download", `forex_scalper_islemler_${dateStr}.csv`);
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);
    } catch (e) {
      console.error("CSV indirme hatası:", e);
      alert("CSV indirilirken bir hata oluştu.");
    } finally {
      setIsExporting(false);
    }
  };

  // Mevcut sembol listesi
  const availableSymbols = [
    { key: "ALL", label: "Tüm Pariteler" },
    { key: "EURUSD", label: "EUR/USD" },
    { key: "GBPUSD", label: "GBP/USD" },
    { key: "USDJPY", label: "USD/JPY" },
    { key: "XAUUSD", label: "Altın (XAU)" },
    { key: "USDCAD", label: "USD/CAD" },
    { key: "AUDUSD", label: "AUD/USD" },
    { key: "USDCHF", label: "USD/CHF" },
    { key: "NZDUSD", label: "NZD/USD" },
    { key: "XAGUSD", label: "Gümüş (XAG)" },
    { key: "USOIL", label: "Ham Petrol" },
  ];

  return (
    <div className="space-y-6 pb-16 animate-in fade-in duration-300">
      {/* ÜST BAŞLIK & NAVİGASYON */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 p-4 sm:p-5 rounded-2xl bg-gradient-to-r from-blue-950/40 via-slate-900/60 to-cyan-950/40 border border-blue-500/20 backdrop-blur-md shadow-xl">
        <div className="flex items-center gap-3">
          <div className="w-12 h-12 rounded-xl bg-blue-500/20 border border-blue-400/40 flex items-center justify-center text-2xl shadow-[0_0_20px_rgba(59,130,246,0.3)]">
            📊
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-xl sm:text-2xl font-black font-mono text-white tracking-tight">
                Forex İşlem Raporları & Analitik
              </h1>
              <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-blue-500/20 text-blue-400 border border-blue-400/30">
                CSV Dışa Aktarım
              </span>
            </div>
            <p className="text-xs text-bunker-muted mt-0.5">
              Otonom scalper işlemlerinin tüm giriş-çıkış fiyatları, işlem süreleri, pips ve getiri dökümü.
            </p>
          </div>
        </div>

        {/* Aksiyon Butonları */}
        <div className="flex flex-wrap items-center gap-2">
          {/* Canlı Yenileme Toggle */}
          <button
            type="button"
            onClick={() => setAutoRefresh(!autoRefresh)}
            className={`px-3 py-1.5 rounded-xl text-xs font-semibold border flex items-center gap-1.5 transition-all ${
              autoRefresh
                ? "bg-emerald-500/15 text-emerald-300 border-emerald-500/30"
                : "bg-bunker-900 text-bunker-muted border-bunker-800"
            }`}
          >
            <span className={`w-2 h-2 rounded-full ${autoRefresh ? "bg-emerald-400 animate-pulse" : "bg-bunker-600"}`} />
            <span>{autoRefresh ? "Canlı Akış Açık" : "Canlı Akış Duraklatıldı"}</span>
          </button>

          {/* Manuel Yenile */}
          <button
            type="button"
            onClick={fetchReport}
            className="p-2 rounded-xl bg-bunker-900/90 border border-bunker-800 text-bunker-muted hover:text-white transition-colors"
            title="Yenile"
          >
            🔄
          </button>

          {/* CSV İndir Butonu */}
          <button
            type="button"
            onClick={downloadCsv}
            disabled={isExporting || trades.length === 0}
            className="px-4 py-2 rounded-xl bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 text-white font-bold text-xs shadow-lg shadow-blue-900/30 flex items-center gap-2 transition-all disabled:opacity-50"
          >
            <span>📥</span>
            <span>{isExporting ? "Dışa Aktarılıyor…" : "Excel / CSV İndir"}</span>
          </button>
        </div>
      </div>

      {/* KPI PERFORMANS METRİKLERİ KARTLARI */}
      {kpi && (
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
          {/* Toplam İşlem */}
          <div className="p-3.5 rounded-xl bg-bunker-900/80 border border-bunker-800">
            <span className="text-[10px] text-bunker-muted uppercase block font-semibold">Toplam İşlem</span>
            <span className="text-xl font-black text-white">{kpi.total_trades}</span>
            <span className="text-[10px] text-bunker-muted block mt-0.5">
              Hacim: {kpi.total_lots} Lot
            </span>
          </div>

          {/* Kazanma Oranı */}
          <div className="p-3.5 rounded-xl bg-bunker-900/80 border border-bunker-800">
            <span className="text-[10px] text-bunker-muted uppercase block font-semibold">Kazanma Oranı (WR)</span>
            <span
              className={`text-xl font-black ${
                kpi.win_rate >= 50 ? "text-emerald-400" : kpi.win_rate > 0 ? "text-rose-400" : "text-white"
              }`}
            >
              %{kpi.win_rate.toFixed(1)}
            </span>
            <span className="text-[10px] text-bunker-muted block mt-0.5">
              {kpi.wins} Kazan / {kpi.losses} Kayıp
            </span>
          </div>

          {/* Net Getiri (USD & Pips) */}
          <div className="p-3.5 rounded-xl bg-bunker-900/80 border border-bunker-800">
            <span className="text-[10px] text-bunker-muted uppercase block font-semibold">Net Realize Kâr</span>
            <span
              className={`text-xl font-black ${
                kpi.total_pnl_usd >= 0 ? "text-emerald-400" : "text-rose-400"
              }`}
            >
              {kpi.total_pnl_usd >= 0 ? "+" : ""}${kpi.total_pnl_usd.toFixed(2)}
            </span>
            <span className="text-[10px] text-bunker-muted block mt-0.5 font-bold">
              {kpi.total_pnl_pips >= 0 ? "+" : ""}{kpi.total_pnl_pips} Pips
            </span>
          </div>

          {/* Kâr Faktörü */}
          <div className="p-3.5 rounded-xl bg-bunker-900/80 border border-bunker-800">
            <span className="text-[10px] text-bunker-muted uppercase block font-semibold">Kâr Faktörü (PF)</span>
            <span
              className={`text-xl font-black ${
                kpi.profit_factor >= 1.5 ? "text-emerald-400" : kpi.profit_factor >= 1.0 ? "text-yellow-400" : "text-rose-400"
              }`}
            >
              {kpi.profit_factor >= 999 ? "∞" : kpi.profit_factor.toFixed(2)}
            </span>
            <span className="text-[10px] text-bunker-muted block mt-0.5 truncate">
              Kâr: ${kpi.gross_profit_usd} | Z: ${kpi.gross_loss_usd}
            </span>
          </div>

          {/* Ortalama İşlem Getirisi */}
          <div className="p-3.5 rounded-xl bg-bunker-900/80 border border-bunker-800">
            <span className="text-[10px] text-bunker-muted uppercase block font-semibold">Ortalama İşlem</span>
            <span
              className={`text-xl font-black ${
                kpi.avg_trade_usd >= 0 ? "text-emerald-400" : "text-rose-400"
              }`}
            >
              {kpi.avg_trade_usd >= 0 ? "+" : ""}${kpi.avg_trade_usd.toFixed(2)}
            </span>
            <span className="text-[10px] text-bunker-muted block mt-0.5">
              Ort. Kâr: +${kpi.avg_win_usd}
            </span>
          </div>

          {/* Bakiye & Özsermaye */}
          <div className="p-3.5 rounded-xl bg-bunker-900/80 border border-bunker-800">
            <span className="text-[10px] text-bunker-muted uppercase block font-semibold">Nakit Bakiye / Özsermaye</span>
            <span className="text-xl font-black text-white">${kpi.balance.toFixed(2)}</span>
            <span className="text-[10px] text-emerald-400 block mt-0.5">
              Equity: ${kpi.equity.toFixed(2)}
            </span>
          </div>
        </div>
      )}

      {/* AÇIK İŞLEMLER BİLGİLENDİRME BANTI (Varsa) */}
      {openPositions.length > 0 && (
        <div className="p-3 rounded-xl bg-blue-950/30 border border-blue-500/30 flex flex-wrap items-center justify-between gap-3 text-xs">
          <div className="flex items-center gap-2">
            <span className="w-2.5 h-2.5 rounded-full bg-blue-400 animate-ping" />
            <span className="font-bold text-white">
              Şu Anda {openPositions.length} Otonom Pozisyon Canlı Piyasada Açık
            </span>
            <span className="text-bunker-muted">
              ({openPositions.map((p) => {
                const badge = (p.protection === "TRAILING" || p.trailing_activated) ? " [🏃 Trailing]" : (p.protection === "BREAKEVEN" || p.breakeven_activated) ? " [🛡️ BE]" : "";
                return `${p.display || p.symbol} ${p.direction}${badge}`;
              }).join(", ")})
            </span>
          </div>
          <div className="flex items-center gap-3">
            <span className="font-bold text-white">
              Anlık Yüzen Kâr/Zarar:{" "}
              <span className={kpi && kpi.open_pnl_usd >= 0 ? "text-emerald-400" : "text-rose-400"}>
                {kpi && kpi.open_pnl_usd >= 0 ? "+" : ""}${kpi?.open_pnl_usd.toFixed(2)}
              </span>
            </span>
            <Link
              href="/forex/portfolio"
              className="px-2.5 py-1 rounded-lg bg-blue-600/30 text-blue-300 border border-blue-400/40 hover:bg-blue-600/50 text-[11px] font-bold transition-all"
            >
              Canlı Pozisyonları Yönet →
            </Link>
          </div>
        </div>
      )}

      {/* FİLTRELEME & ARAMA ÇUBUĞU */}
      <div className="p-4 rounded-2xl bg-bunker-900/70 border border-bunker-800 space-y-3 shadow-lg">
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 text-xs">
          {/* Arama */}
          <div>
            <label className="text-[11px] text-bunker-muted block mb-1 font-semibold">
              🔍 Bilet No veya Sembol Ara:
            </label>
            <input
              type="text"
              placeholder="Örn: FX-500751, AUD/USD..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full bg-bunker-950 border border-bunker-700 rounded-lg px-3 py-2 text-white placeholder-bunker-600 outline-none focus:border-blue-400 transition-colors"
            />
          </div>

          {/* Parite Seçici */}
          <div>
            <label className="text-[11px] text-bunker-muted block mb-1 font-semibold">
              Parite Filtresi:
            </label>
            <select
              value={selectedSymbol}
              onChange={(e) => setSelectedSymbol(e.target.value)}
              className="w-full bg-bunker-950 border border-bunker-700 rounded-lg px-3 py-2 text-white outline-none focus:border-blue-400 transition-colors"
            >
              {availableSymbols.map((item) => (
                <option key={item.key} value={item.key}>
                  {item.label}
                </option>
              ))}
            </select>
          </div>

          {/* Sonuç Filtresi */}
          <div>
            <label className="text-[11px] text-bunker-muted block mb-1 font-semibold">
              Sonuç Filtresi:
            </label>
            <select
              value={selectedOutcome}
              onChange={(e) => setSelectedOutcome(e.target.value)}
              className="w-full bg-bunker-950 border border-bunker-700 rounded-lg px-3 py-2 text-white outline-none focus:border-blue-400 transition-colors"
            >
              <option value="ALL">Tümü (Kazanç & Kayıp)</option>
              <option value="WIN">Sadece Kazananlar (WIN 🎯)</option>
              <option value="LOSS">Sadece Kaybedenler (LOSS 🛑)</option>
            </select>
          </div>

          {/* Çıkış Nedeni Filtresi */}
          <div>
            <label className="text-[11px] text-bunker-muted block mb-1 font-semibold">
              Çıkış Türü:
            </label>
            <select
              value={selectedReason}
              onChange={(e) => setSelectedReason(e.target.value)}
              className="w-full bg-bunker-950 border border-bunker-700 rounded-lg px-3 py-2 text-white outline-none focus:border-blue-400 transition-colors"
            >
              <option value="ALL">Tüm Çıkışlar</option>
              <option value="TP_HIT">🎯 Kâr Al (Take Profit)</option>
              <option value="SL_HIT">🛑 Zarar Durdur (Stop Loss)</option>
              <option value="BE_HIT">🛡️ Başabaş Koruma (Breakeven)</option>
              <option value="TRAILING_HIT">📈 İz Süren Stop (Trailing)</option>
              <option value="MANUAL">✋ Manuel Kapatma</option>
            </select>
          </div>
        </div>

        {/* Hızlı Filtre Temizle */}
        {(selectedSymbol !== "ALL" || selectedOutcome !== "ALL" || selectedReason !== "ALL" || searchQuery) && (
          <div className="flex items-center gap-2 pt-1 border-t border-bunker-800 text-[11px]">
            <span className="text-bunker-muted">Aktif filtreler uygulanıyor ({trades.length} işlem listelendi)</span>
            <button
              type="button"
              onClick={() => {
                setSelectedSymbol("ALL");
                setSelectedOutcome("ALL");
                setSelectedReason("ALL");
                setSearchQuery("");
              }}
              className="text-blue-400 hover:underline font-bold"
            >
              ✕ Filtreleri Temizle
            </button>
          </div>
        )}
      </div>

      {/* DETAYLI İŞLEMLER TABLOSU */}
      <div className="rounded-2xl border border-bunker-800 bg-bunker-900/70 shadow-2xl overflow-hidden">
        <div className="p-4 border-b border-bunker-800 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="text-lg">📜</span>
            <h2 className="text-sm font-bold text-white uppercase tracking-wider">
              Kapanan İşlemler Tablosu ({trades.length})
            </h2>
          </div>
          <span className="text-xs text-bunker-muted font-mono">
            {trades.length > 0 ? `Son ${trades.length} işlem gösteriliyor` : "Kayıt yok"}
          </span>
        </div>

        {loading ? (
          <div className="p-16 text-center text-bunker-muted font-mono text-sm animate-pulse">
            İşlem verileri yükleniyor…
          </div>
        ) : trades.length === 0 ? (
          <div className="p-16 text-center space-y-3">
            <div className="text-4xl">🏁</div>
            <p className="text-sm font-bold text-white">Henüz kriterlere uyan bir işlem bulunmuyor.</p>
            <p className="text-xs text-bunker-muted max-w-md mx-auto">
              Otonom motor pozisyonları kapatıp hedeflerine (TP, SL, Breakeven) ulaştığında tüm işlemler otomatik olarak bu raporda arşivlenecektir.
            </p>
            <Link
              href="/forex/portfolio"
              className="inline-block mt-2 px-4 py-2 rounded-xl bg-blue-600 hover:bg-blue-500 text-white font-bold text-xs transition-all shadow-md"
            >
              Canlı Portföye Git
            </Link>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs font-mono">
              <thead className="bg-bunker-950/80 text-bunker-muted border-b border-bunker-800 uppercase text-[10px] tracking-wider">
                <tr>
                  <th className="py-3 px-3">Bilet ID</th>
                  <th className="py-3 px-3">Parite</th>
                  <th className="py-3 px-2">Yön</th>
                  <th className="py-3 px-2">Lot</th>
                  <th className="py-3 px-2">Skor</th>
                  <th className="py-3 px-3">Giriş</th>
                  <th className="py-3 px-3">Çıkış</th>
                  <th className="py-3 px-2">Süre</th>
                  <th className="py-3 px-3">Çıkış Tipi</th>
                  <th className="py-3 px-3 text-right">Kâr (Pip)</th>
                  <th className="py-3 px-3 text-right">Net PnL ($)</th>
                  <th className="py-3 px-3 text-right">Sonraki Bakiye</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-bunker-800/60">
                {trades.map((tr: any, idx: number) => {
                  const pnl = Number(tr.pnl_usd ?? tr.profit ?? 0);
                  const isWin = pnl >= 0;
                  const pips = Number(tr.pnl_pips ?? 0);
                  const balAfter = tr.balance_after != null ? Number(tr.balance_after) : null;
                  return (
                    <tr key={tr.id ?? tr.ticket ?? `rep-${idx}`} className="hover:bg-bunker-800/40 transition-colors">
                      {/* Bilet ID */}
                      <td className="py-3 px-3 text-bunker-muted text-[11px] font-bold">
                        {tr.id ?? tr.ticket ?? "-"}
                      </td>

                      {/* Parite & Display */}
                      <td className="py-3 px-3">
                        <span className="font-bold text-white text-xs block">{tr.display || tr.symbol}</span>
                        <span className="text-[10px] text-bunker-muted">{tr.symbol}</span>
                      </td>

                      {/* Yön */}
                      <td className="py-3 px-2">
                        <span
                          className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                            tr.direction === "BUY"
                              ? "bg-emerald-500/15 text-emerald-400 border border-emerald-500/30"
                              : "bg-rose-500/15 text-rose-400 border border-rose-500/30"
                          }`}
                        >
                          {tr.direction || "BUY"}
                        </span>
                      </td>

                      {/* Lot */}
                      <td className="py-3 px-2 font-bold text-white">
                        {tr.lots ?? 0.01}
                      </td>

                      {/* Skor */}
                      <td className="py-3 px-2 text-blue-300 font-semibold">
                        {tr.score ? Number(tr.score).toFixed(0) : "-"}
                      </td>

                      {/* Giriş */}
                      <td className="py-3 px-3">
                        <span className="text-white font-bold block">{tr.entry_price ?? "-"}</span>
                        <span className="text-[10px] text-bunker-muted">{tr.open_time ?? "-"}</span>
                      </td>

                      {/* Çıkış */}
                      <td className="py-3 px-3">
                        <span className="text-white font-bold block">{tr.exit_price ?? "-"}</span>
                        <span className="text-[10px] text-bunker-muted">{tr.exit_time ?? "-"}</span>
                      </td>

                      {/* Süre */}
                      <td className="py-3 px-2 text-bunker-muted text-[11px] whitespace-nowrap">
                        {tr.duration_human || (tr.duration_sec ? `${tr.duration_sec} sn` : "-")}
                      </td>

                      {/* Çıkış Tipi */}
                      <td className="py-3 px-3">
                        <span
                          className={`px-2 py-0.5 rounded text-[10px] font-bold whitespace-nowrap ${
                            tr.exit_reason === "TP_HIT"
                              ? "bg-emerald-500/20 text-emerald-300 border border-emerald-500/30"
                              : tr.exit_reason === "BE_HIT"
                              ? "bg-cyan-500/20 text-cyan-300 border border-cyan-500/30"
                              : tr.exit_reason === "TRAILING_HIT"
                              ? "bg-yellow-500/20 text-yellow-300 border border-yellow-500/30"
                              : tr.exit_reason === "MANUAL"
                              ? "bg-indigo-500/20 text-indigo-300 border border-indigo-500/30"
                              : "bg-rose-500/20 text-rose-300 border border-rose-500/30"
                          }`}
                        >
                          {tr.exit_reason_title || tr.exit_reason || "IC Markets MT5"}
                        </span>
                      </td>

                      {/* Pip */}
                      <td
                        className={`py-3 px-3 text-right font-bold ${
                          pips >= 0 ? "text-emerald-400" : "text-rose-400"
                        }`}
                      >
                        {pips >= 0 ? "+" : ""}
                        {pips.toFixed(1)} p
                      </td>

                      {/* Net USD PnL */}
                      <td
                        className={`py-3 px-3 text-right font-black text-sm ${
                          isWin ? "text-emerald-400" : "text-rose-400"
                        }`}
                      >
                        {isWin ? "+" : ""}
                        ${pnl.toFixed(2)}
                      </td>

                      {/* Sonraki Bakiye */}
                      <td className="py-3 px-3 text-right text-bunker-muted font-bold">
                        {balAfter !== null ? `$${balAfter.toFixed(2)}` : "-"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* ALT BAĞLANTILAR */}
      <div className="flex flex-wrap items-center justify-between gap-4 text-xs text-bunker-muted pt-4 border-t border-bunker-800">
        <div className="flex items-center gap-4">
          <Link href="/forex/portfolio" className="hover:text-blue-400 transition-colors flex items-center gap-1 font-bold">
            ← Otonom Scalper Portföy & Canlı Takip
          </Link>
          <span className="text-bunker-700">|</span>
          <Link href="/forex" className="hover:text-blue-400 transition-colors">
            Forex Radar
          </Link>
        </div>
        <div className="flex items-center gap-4">
          <Link href="/forex/technical-charts" className="hover:text-blue-400 transition-colors">
            4'lü TradingView Çoklu Ekran →
          </Link>
        </div>
      </div>
    </div>
  );
}
