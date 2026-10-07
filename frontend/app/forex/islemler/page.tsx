"use client";

import React, { useState, useEffect, useMemo, useCallback } from "react";
import Link from "next/link";
import { apiFetch } from "../../lib/api";

interface OpenPosition {
  id: string;
  ticket?: number;
  symbol: string;
  display?: string;
  direction: "BUY" | "SELL";
  lots: number;
  entry_price: number;
  current_price: number;
  sl_price?: number;
  tp_price?: number;
  pnl_usd: number;
  pnl_pips: number;
  open_time?: string;
  category?: string;
}

interface ClosedTrade {
  id: string;
  ticket?: number;
  symbol: string;
  display?: string;
  direction: "BUY" | "SELL";
  lots: number;
  entry_price?: number;
  exit_price?: number;
  close_price?: number;
  pnl_usd: number;
  pnl_pips: number;
  outcome?: "WIN" | "LOSS" | "BE";
  exit_reason?: string;
  exit_reason_title?: string;
  close_time?: string;
  exit_time?: string;
  open_time?: string;
}

interface KPIStats {
  total_trades: number;
  wins: number;
  losses: number;
  win_rate: number;
  total_pnl_usd: number;
  balance: number;
  equity: number;
  open_positions_count: number;
  open_pnl_usd: number;
}

function formatPrice(v?: number | null, symbol: string = ""): string {
  if (v == null || !Number.isFinite(v) || v <= 0) return "—";
  const s = symbol.toUpperCase();
  if (s.includes("JPY")) return v.toFixed(3);
  if (
    s.includes("XAU") ||
    s.includes("GOLD") ||
    s.includes("NAS") ||
    s.includes("US30") ||
    s.includes("SPX") ||
    s.includes("BTC") ||
    s.includes("ETH") ||
    s.includes("OIL")
  ) {
    return v.toFixed(2);
  }
  return v.toFixed(5);
}

function formatClockTime(timeStr?: string): string {
  if (!timeStr) return "—";
  try {
    const d = new Date(timeStr);
    if (!isNaN(d.getTime())) {
      return d.toLocaleTimeString("tr-TR", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
    }
    // "2026-10-07 14:22:10" formatı
    if (timeStr.includes(" ")) {
      return timeStr.split(" ")[1] || timeStr;
    }
    return timeStr;
  } catch {
    return timeStr;
  }
}

export default function ForexIslemlerPage() {
  // Tema Durumu: Kullanıcı isteği doğrultusunda varsayılan "Açık Mod" (Light Mode), ancak Koyu Mod da seçilebilir
  const [isLightMode, setIsLightMode] = useState<boolean>(true);
  const [loading, setLoading] = useState<boolean>(true);
  const [refreshing, setRefreshing] = useState<boolean>(false);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  // Veri Durumları
  const [openPositions, setOpenPositions] = useState<OpenPosition[]>([]);
  const [closedTrades, setClosedTrades] = useState<ClosedTrade[]>([]);
  const [kpi, setKpi] = useState<KPIStats>({
    total_trades: 0,
    wins: 0,
    losses: 0,
    win_rate: 0,
    total_pnl_usd: 0,
    balance: 10000,
    equity: 10000,
    open_positions_count: 0,
    open_pnl_usd: 0,
  });

  // Kapanan İşlemler Filtresi
  const [filterOutcome, setFilterOutcome] = useState<"ALL" | "WIN" | "LOSS">("ALL");

  // Kapatma Onay Modalı
  const [closingTarget, setClosingTarget] = useState<OpenPosition | null>(null);
  const [isClosing, setIsClosing] = useState<boolean>(false);
  const [actionMessage, setActionMessage] = useState<{ type: "success" | "error"; text: string } | null>(null);

  // Tema Tercihini Yerel Hafızadan Yükle
  useEffect(() => {
    try {
      const savedTheme = localStorage.getItem("forex_theme_preference");
      if (savedTheme === "dark") {
        setIsLightMode(false);
      } else if (savedTheme === "light") {
        setIsLightMode(true);
      }
    } catch {}
  }, []);

  const toggleTheme = () => {
    setIsLightMode((prev) => {
      const next = !prev;
      try {
        localStorage.setItem("forex_theme_preference", next ? "light" : "dark");
      } catch {}
      return next;
    });
  };

  // Veri Yükleme
  const fetchData = useCallback(async (isSilent = false) => {
    if (!isSilent) setRefreshing(true);
    try {
      // 1. İşlem Raporları & Pozisyonlar
      const reportRes = await apiFetch("/api/forex/auto-paper/trades?period=today&limit=200");
      if (reportRes) {
        if (Array.isArray(reportRes.open_positions)) {
          setOpenPositions(reportRes.open_positions);
        }
        if (Array.isArray(reportRes.trades)) {
          setClosedTrades(reportRes.trades);
        }
        if (reportRes.kpi) {
          setKpi((prev) => ({
            ...prev,
            ...reportRes.kpi,
          }));
        }
      }

      // 2. Canlı Durum & Bakiye
      const statusRes = await apiFetch("/api/forex/auto-paper/status");
      if (statusRes) {
        setKpi((prev) => ({
          ...prev,
          balance: statusRes.balance ?? prev.balance,
          equity: statusRes.equity ?? prev.equity,
          daily_pnl: statusRes.daily_pnl ?? prev.total_pnl_usd,
        }));
      }

      setLastUpdated(new Date());
    } catch (err) {
      console.error("Forex işlemler verisi çekme hatası:", err);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    fetchData(false);
    // Her 3 saniyede bir otomatik dinamik yenileme
    const timer = setInterval(() => {
      if (!document.hidden) {
        fetchData(true);
      }
    }, 3000);
    return () => clearInterval(timer);
  }, [fetchData]);

  // Manuel Pozisyon Kapatma
  const handleConfirmClose = async () => {
    if (!closingTarget) return;
    setIsClosing(true);
    try {
      await apiFetch("/api/forex/auto-paper/close-position", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id: closingTarget.id }),
      });
      setActionMessage({
        type: "success",
        text: `✅ ${closingTarget.display || closingTarget.symbol} pozisyonu başarıyla kapatıldı.`,
      });
      setClosingTarget(null);
      fetchData(false);
      setTimeout(() => setActionMessage(null), 4000);
    } catch (err: any) {
      setActionMessage({
        type: "error",
        text: `❌ Pozisyon kapatılırken hata oluştu: ${err?.message || "Sunucu yanıt vermedi"}`,
      });
    } finally {
      setIsClosing(false);
    }
  };

  // Dinamik Açık PnL Toplamları
  const openSummary = useMemo(() => {
    let totalPnlUsd = 0;
    let totalPnlPips = 0;
    for (const p of openPositions) {
      totalPnlUsd += Number(p.pnl_usd ?? 0);
      totalPnlPips += Number(p.pnl_pips ?? 0);
    }
    return {
      pnlUsd: totalPnlUsd,
      pnlPips: totalPnlPips,
      count: openPositions.length,
    };
  }, [openPositions]);

  // Filtrelenmiş Kapanan İşlemler
  const filteredClosedTrades = useMemo(() => {
    return closedTrades.filter((t) => {
      if (filterOutcome === "ALL") return true;
      const isWin = Number(t.pnl_usd ?? 0) >= 0 || t.outcome === "WIN";
      if (filterOutcome === "WIN") return isWin;
      if (filterOutcome === "LOSS") return !isWin;
      return true;
    });
  }, [closedTrades, filterOutcome]);

  // Dinamik Tema Stilleri
  const theme = useMemo(() => {
    if (isLightMode) {
      return {
        wrapper: "bg-slate-100 text-slate-800 min-h-screen",
        cardBg: "bg-white border-slate-200/90 shadow-sm",
        headerBg: "bg-gradient-to-r from-blue-50/90 via-white to-indigo-50/90 border-blue-200/80 shadow-sm",
        kpiCard: "bg-white border-slate-200/90 shadow-sm text-slate-900",
        tableHeader: "bg-slate-100/90 text-slate-600 border-slate-200 text-[11px]",
        tableRow: "hover:bg-slate-50 transition-colors border-slate-100",
        textPrimary: "text-slate-900 font-bold",
        textSecondary: "text-slate-500",
        badgeBg: "bg-slate-100 text-slate-700 border-slate-200",
        accentBorder: "border-slate-200",
        profitBg: "bg-emerald-50 text-emerald-700 border-emerald-300 font-bold",
        lossBg: "bg-rose-50 text-rose-700 border-rose-300 font-bold",
      };
    }
    return {
      wrapper: "bg-[#080c14] text-white min-h-screen",
      cardBg: "bg-bunker-900/90 border-bunker-800 shadow-xl",
      headerBg: "bg-gradient-to-r from-blue-950/40 via-slate-900/60 to-indigo-950/40 border-blue-500/20 shadow-lg",
      kpiCard: "bg-bunker-900/80 border-bunker-800 shadow-lg text-white",
      tableHeader: "bg-bunker-950/80 text-bunker-muted border-bunker-800 text-[11px]",
      tableRow: "hover:bg-bunker-800/40 transition-colors border-bunker-800/60",
      textPrimary: "text-white font-bold",
      textSecondary: "text-bunker-muted",
      badgeBg: "bg-bunker-800 text-bunker-300 border-bunker-700",
      accentBorder: "border-bunker-800",
      profitBg: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30 font-bold",
      lossBg: "bg-rose-500/15 text-rose-400 border-rose-500/30 font-bold",
    };
  }, [isLightMode]);

  return (
    <div className={`space-y-4 pb-16 font-mono transition-colors duration-200 ${theme.wrapper}`}>
      
      {/* 1. ÜST BAŞLIK & TEMA / YENİLEME ÇUBUĞU */}
      <div className={`p-4 rounded-2xl border flex flex-wrap items-center justify-between gap-3 ${theme.headerBg}`}>
        <div className="flex items-center gap-3">
          <div className="w-11 h-11 rounded-xl bg-blue-500/20 border border-blue-400/40 flex items-center justify-center text-2xl shadow-[0_0_16px_rgba(59,130,246,0.25)] shrink-0">
            ⚡
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-base sm:text-lg font-black tracking-tight">
                FOREX CANLI İŞLEM İZLEME
              </h1>
              <span className="flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-bold bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 border border-emerald-500/30">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
                CANLI AKIŞ
              </span>
            </div>
            <p className={`text-xs mt-0.5 ${theme.textSecondary}`}>
              Açık ve Kapanan Forex İşlemleri · Anlık Dinamik K/Z (PnL) &amp; Günlük Başarı
            </p>
          </div>
        </div>

        {/* Sağ Kontroller: Açık/Koyu Mod Butonu & Manuel Yenileme */}
        <div className="flex items-center gap-2 text-xs">
          {/* TEMA SEÇİCİ TOGGLE */}
          <button
            type="button"
            onClick={toggleTheme}
            className={`px-3 py-1.5 rounded-xl border font-bold flex items-center gap-1.5 transition-all shadow-sm ${
              isLightMode
                ? "bg-amber-50 text-amber-900 border-amber-300 hover:bg-amber-100"
                : "bg-bunker-800 text-blue-300 border-bunker-700 hover:bg-bunker-750"
            }`}
            title="Açık Mod / Koyu Mod Değiştir"
          >
            <span>{isLightMode ? "☀️" : "🌙"}</span>
            <span>{isLightMode ? "Açık Mod" : "Koyu Mod"}</span>
          </button>

          {/* YENİLEME BUTONU */}
          <button
            type="button"
            onClick={() => fetchData(false)}
            disabled={refreshing}
            className={`px-3 py-1.5 rounded-xl border font-bold flex items-center gap-1.5 transition-all shadow-sm ${
              isLightMode
                ? "bg-white text-slate-700 border-slate-300 hover:bg-slate-50"
                : "bg-bunker-800 text-white border-bunker-700 hover:bg-bunker-750"
            }`}
          >
            <span className={refreshing ? "animate-spin" : ""}>🔄</span>
            <span className="hidden sm:inline">Yenile</span>
          </button>

          {lastUpdated && (
            <span className={`text-[10px] hidden md:inline ml-1 ${theme.textSecondary}`}>
              {lastUpdated.toLocaleTimeString("tr-TR")}
            </span>
          )}
        </div>
      </div>

      {/* BİLDİRİM MESAJI */}
      {actionMessage && (
        <div
          className={`p-3 rounded-xl border text-xs font-bold transition-all ${
            actionMessage.type === "success"
              ? "bg-emerald-50 border-emerald-300 text-emerald-800 dark:bg-emerald-950/40 dark:border-emerald-500/40 dark:text-emerald-300"
              : "bg-rose-50 border-rose-300 text-rose-800 dark:bg-rose-950/40 dark:border-rose-500/40 dark:text-rose-300"
          }`}
        >
          {actionMessage.text}
        </div>
      )}

      {/* 2. EN ÜST DASHBOARD & GÜNLÜK BAŞARI KARTLARI (4'LÜ GRID) */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
        
        {/* KART 1: GÜNÜN BAŞARI ORANI (%) */}
        <div className={`p-4 rounded-2xl border ${theme.kpiCard}`}>
          <div className="flex items-center justify-between">
            <span className={`text-[11px] font-bold uppercase tracking-wider ${theme.textSecondary}`}>
              Günün Başarı Oranı
            </span>
            <span className="text-lg">🎯</span>
          </div>
          <div className="mt-2 flex items-baseline gap-2">
            <span className="text-2xl sm:text-3xl font-black text-emerald-600 dark:text-emerald-400">
              %{kpi.win_rate.toFixed(1)}
            </span>
            <span className={`text-xs ${theme.textSecondary}`}>
              ({kpi.wins}K / {kpi.losses}Z)
            </span>
          </div>
          <div className="mt-2.5 w-full bg-slate-200 dark:bg-bunker-800 h-2 rounded-full overflow-hidden">
            <div
              className="bg-emerald-500 h-full rounded-full transition-all duration-500"
              style={{ width: `${Math.min(100, Math.max(0, kpi.win_rate))}%` }}
            />
          </div>
          <div className={`mt-1.5 text-[10px] flex justify-between ${theme.textSecondary}`}>
            <span>{kpi.total_trades} Toplam İşlem</span>
            <span>{kpi.wins} Başarılı Kapanış</span>
          </div>
        </div>

        {/* KART 2: GÜNLÜK NET KÂRLILIK DURUMU */}
        <div className={`p-4 rounded-2xl border ${theme.kpiCard}`}>
          <div className="flex items-center justify-between">
            <span className={`text-[11px] font-bold uppercase tracking-wider ${theme.textSecondary}`}>
              Bugünkü Net K/Z
            </span>
            <span className="text-lg">💰</span>
          </div>
          <div className="mt-2 flex items-baseline gap-2">
            <span
              className={`text-2xl sm:text-3xl font-black ${
                kpi.total_pnl_usd >= 0
                  ? "text-emerald-600 dark:text-emerald-400"
                  : "text-rose-600 dark:text-rose-400"
              }`}
            >
              {kpi.total_pnl_usd >= 0 ? "+" : ""}${kpi.total_pnl_usd.toFixed(2)}
            </span>
          </div>
          <div className="mt-2.5 flex items-center justify-between text-xs">
            <span className={`text-[11px] ${theme.textSecondary}`}>
              Gerçekleşen Günlük Bilanço
            </span>
            <span
              className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                kpi.total_pnl_usd >= 0 ? theme.profitBg : theme.lossBg
              }`}
            >
              {kpi.total_pnl_usd >= 0 ? "▲ NET KÂR" : "▼ NET ZARAR"}
            </span>
          </div>
        </div>

        {/* KART 3: ANLIK HESAP BAKİYESİ */}
        <div className={`p-4 rounded-2xl border ${theme.kpiCard}`}>
          <div className="flex items-center justify-between">
            <span className={`text-[11px] font-bold uppercase tracking-wider ${theme.textSecondary}`}>
              Hesap Bakiyesi
            </span>
            <span className="text-lg">🏛️</span>
          </div>
          <div className="mt-2 flex items-baseline gap-2">
            <span className="text-2xl sm:text-3xl font-black">
              ${kpi.balance.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
            </span>
          </div>
          <div className="mt-2.5 flex items-center justify-between text-xs">
            <span className={`text-[11px] ${theme.textSecondary}`}>
              Özkaynak (Equity):
            </span>
            <span className="font-bold text-blue-600 dark:text-blue-400 text-xs">
              ${kpi.equity.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
            </span>
          </div>
        </div>

        {/* KART 4: TOPLAM AÇIK İŞLEMLERİN PnL'İ */}
        <div className={`p-4 rounded-2xl border ${theme.kpiCard}`}>
          <div className="flex items-center justify-between">
            <span className={`text-[11px] font-bold uppercase tracking-wider ${theme.textSecondary}`}>
              Açık İşlemler PnL
            </span>
            <span className="text-lg">📊</span>
          </div>
          <div className="mt-2 flex items-baseline gap-2">
            <span
              className={`text-2xl sm:text-3xl font-black ${
                openSummary.pnlUsd >= 0
                  ? "text-emerald-600 dark:text-emerald-400"
                  : "text-rose-600 dark:text-rose-400"
              }`}
            >
              {openSummary.pnlUsd >= 0 ? "+" : ""}${openSummary.pnlUsd.toFixed(2)}
            </span>
            <span
              className={`text-xs font-bold ${
                openSummary.pnlPips >= 0
                  ? "text-emerald-600 dark:text-emerald-400"
                  : "text-rose-600 dark:text-rose-400"
              }`}
            >
              ({openSummary.pnlPips >= 0 ? "+" : ""}{openSummary.pnlPips.toFixed(1)}p)
            </span>
          </div>
          <div className="mt-2.5 flex items-center justify-between text-xs">
            <span className={`text-[11px] ${theme.textSecondary}`}>
              {openSummary.count} Aktif Açık Pozisyon
            </span>
            <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-blue-500/10 text-blue-600 dark:text-blue-400 border border-blue-400/30">
              YÜZEN K/Z
            </span>
          </div>
        </div>

      </div>

      {/* 3. AÇIK OLAN FOREX İŞLEMLERİ TABLOSU / KARTLARI */}
      <div className={`rounded-2xl border overflow-hidden ${theme.cardBg}`}>
        <div className="p-3.5 sm:p-4 border-b flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <span className="text-lg">💼</span>
            <h2 className={`text-sm font-bold uppercase tracking-wide ${theme.textPrimary}`}>
              Açık Olan Forex İşlemleri
            </h2>
            <span className={`px-2 py-0.5 rounded text-xs font-bold ${theme.badgeBg}`}>
              {openPositions.length} Açık Pozisyon
            </span>
          </div>

          <div className="flex items-center gap-2 text-xs">
            <span className={theme.textSecondary}>Toplam Anlık K/Z:</span>
            <span
              className={`px-2.5 py-1 rounded-lg border font-bold ${
                openSummary.pnlUsd >= 0 ? theme.profitBg : theme.lossBg
              }`}
            >
              {openSummary.pnlUsd >= 0 ? "+" : ""}${openSummary.pnlUsd.toFixed(2)}
            </span>
          </div>
        </div>

        {loading ? (
          <div className="p-12 text-center text-xs">
            <div className="inline-block w-6 h-6 border-2 border-blue-500 border-t-transparent rounded-full animate-spin mb-2" />
            <p className={theme.textSecondary}>Açık pozisyonlar taranıyor…</p>
          </div>
        ) : openPositions.length === 0 ? (
          <div className="p-10 text-center space-y-2">
            <div className="text-3xl">☕</div>
            <p className={`text-sm font-bold ${theme.textPrimary}`}>
              Şu an açık forex işlemi bulunmuyor.
            </p>
            <p className={`text-xs ${theme.textSecondary}`}>
              Otonom motor radar filtrelerini ve onay sinyallerini taramaya devam ediyor.
            </p>
            <div className="pt-2">
              <Link
                href="/forex"
                className="px-3 py-1.5 rounded-lg bg-blue-600 text-white font-bold text-xs hover:bg-blue-500 transition-colors inline-block"
              >
                📡 Forex Radarına Git
              </Link>
            </div>
          </div>
        ) : (
          <>
            {/* Masaüstü Tablo Görünümü */}
            <div className="hidden md:block overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead className={`uppercase border-b ${theme.tableHeader}`}>
                  <tr>
                    <th className="py-3 px-4">Sembol / Parite</th>
                    <th className="py-3 px-3">Yön</th>
                    <th className="py-3 px-3">Lot</th>
                    <th className="py-3 px-3">Giriş Fiyatı</th>
                    <th className="py-3 px-3">Güncel Fiyat</th>
                    <th className="py-3 px-4">Anlık Kâr / Zarar (PnL)</th>
                    <th className="py-3 px-3">Hedef / Stop</th>
                    <th className="py-3 px-4 text-right">İşlem</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 dark:divide-bunker-800/60">
                  {openPositions.map((p) => {
                    const isBuy = p.direction === "BUY";
                    const isProfitable = Number(p.pnl_usd ?? 0) >= 0;
                    return (
                      <tr key={p.id || p.ticket} className={theme.tableRow}>
                        <td className="py-3.5 px-4">
                          <div className="flex items-center gap-2">
                            <span className="font-bold text-sm">
                              {p.display || p.symbol}
                            </span>
                            {p.category && (
                              <span className="text-[10px] px-1.5 py-0.5 rounded bg-slate-100 dark:bg-bunker-800 text-slate-500 dark:text-bunker-muted uppercase">
                                {p.category}
                              </span>
                            )}
                          </div>
                          {p.open_time && (
                            <div className={`text-[10px] ${theme.textSecondary}`}>
                              {formatClockTime(p.open_time)}
                            </div>
                          )}
                        </td>

                        <td className="py-3.5 px-3">
                          <span
                            className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-md text-[11px] font-bold ${
                              isBuy
                                ? "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 border border-emerald-500/30"
                                : "bg-rose-500/15 text-rose-600 dark:text-rose-400 border border-rose-500/30"
                            }`}
                          >
                            {isBuy ? "▲ AL" : "▼ SAT"}
                          </span>
                        </td>

                        <td className="py-3.5 px-3 font-bold text-sm">
                          {p.lots.toFixed(2)} <span className="text-[11px] font-normal">Lot</span>
                        </td>

                        <td className="py-3.5 px-3 font-semibold">
                          {formatPrice(p.entry_price, p.symbol)}
                        </td>

                        <td className="py-3.5 px-3 font-bold">
                          {formatPrice(p.current_price, p.symbol)}
                        </td>

                        <td className="py-3.5 px-4 whitespace-nowrap">
                          <div
                            className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-lg border text-sm font-black ${
                              isProfitable ? theme.profitBg : theme.lossBg
                            }`}
                          >
                            <span>{isProfitable ? "+" : ""}${Number(p.pnl_usd).toFixed(2)}</span>
                            <span className="text-xs font-semibold opacity-85">
                              ({p.pnl_pips >= 0 ? "+" : ""}{Number(p.pnl_pips).toFixed(1)}p)
                            </span>
                          </div>
                        </td>

                        <td className="py-3.5 px-3 whitespace-nowrap text-[11px]">
                          <div>TP: <strong className="text-emerald-600 dark:text-emerald-400">{formatPrice(p.tp_price, p.symbol)}</strong></div>
                          <div>SL: <strong className="text-rose-600 dark:text-rose-400">{formatPrice(p.sl_price, p.symbol)}</strong></div>
                        </td>

                        <td className="py-3.5 px-4 text-right">
                          <button
                            type="button"
                            onClick={() => setClosingTarget(p)}
                            className="px-3 py-1.5 rounded-lg bg-rose-500/15 text-rose-600 dark:text-rose-400 border border-rose-500/30 font-bold hover:bg-rose-500/25 transition-all text-xs"
                          >
                            ✕ Kapat
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            {/* Mobil Kart Görünümü (Tamamen Mobil Onaylı) */}
            <div className="md:hidden space-y-3 p-3">
              {openPositions.map((p) => {
                const isBuy = p.direction === "BUY";
                const isProfitable = Number(p.pnl_usd ?? 0) >= 0;
                return (
                  <div
                    key={p.id || p.ticket}
                    className={`p-3.5 rounded-xl border space-y-2.5 shadow-sm ${
                      isLightMode ? "bg-slate-50 border-slate-200" : "bg-bunker-950/80 border-bunker-800"
                    }`}
                  >
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <span className="font-bold text-base">
                          {p.display || p.symbol}
                        </span>
                        <span
                          className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                            isBuy
                              ? "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 border border-emerald-500/30"
                              : "bg-rose-500/15 text-rose-600 dark:text-rose-400 border border-rose-500/30"
                          }`}
                        >
                          {isBuy ? "▲ AL" : "▼ SAT"}
                        </span>
                      </div>
                      <span className="font-bold text-sm">
                        {p.lots.toFixed(2)} Lot
                      </span>
                    </div>

                    <div className="flex items-center justify-between text-xs pt-1 border-t border-slate-200 dark:border-bunker-800/80">
                      <div>
                        <span className={`text-[10px] block ${theme.textSecondary}`}>GİRİŞ</span>
                        <span className="font-semibold">{formatPrice(p.entry_price, p.symbol)}</span>
                      </div>
                      <div className="text-right">
                        <span className={`text-[10px] block ${theme.textSecondary}`}>GÜNCEL</span>
                        <span className="font-bold">{formatPrice(p.current_price, p.symbol)}</span>
                      </div>
                    </div>

                    <div className="flex items-center justify-between pt-2 border-t border-slate-200 dark:border-bunker-800/80">
                      <div
                        className={`px-3 py-1 rounded-lg border text-sm font-black ${
                          isProfitable ? theme.profitBg : theme.lossBg
                        }`}
                      >
                        {isProfitable ? "+" : ""}${Number(p.pnl_usd).toFixed(2)} ({p.pnl_pips >= 0 ? "+" : ""}{Number(p.pnl_pips).toFixed(1)}p)
                      </div>

                      <button
                        type="button"
                        onClick={() => setClosingTarget(p)}
                        className="px-3.5 py-1.5 rounded-lg bg-rose-500/15 text-rose-600 dark:text-rose-400 border border-rose-500/30 font-bold text-xs"
                      >
                        ✕ Kapat
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          </>
        )}
      </div>

      {/* 4. KAPANAN FOREX İŞLEMLERİ TABLOSU / GEÇMİŞ */}
      <div className={`rounded-2xl border overflow-hidden ${theme.cardBg}`}>
        <div className="p-3.5 sm:p-4 border-b flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <span className="text-lg">📋</span>
            <h2 className={`text-sm font-bold uppercase tracking-wide ${theme.textPrimary}`}>
              Kapanan Forex İşlemleri ({filteredClosedTrades.length}/{closedTrades.length})
            </h2>
          </div>

          {/* Filtreleme Butonları */}
          <div className="flex items-center gap-1.5 text-xs">
            <button
              type="button"
              onClick={() => setFilterOutcome("ALL")}
              className={`px-2.5 py-1 rounded-lg font-bold border transition-all ${
                filterOutcome === "ALL"
                  ? "bg-blue-600 text-white border-blue-600"
                  : `${theme.badgeBg} hover:opacity-80`
              }`}
            >
              Tümü ({closedTrades.length})
            </button>
            <button
              type="button"
              onClick={() => setFilterOutcome("WIN")}
              className={`px-2.5 py-1 rounded-lg font-bold border transition-all ${
                filterOutcome === "WIN"
                  ? "bg-emerald-600 text-white border-emerald-600"
                  : `${theme.badgeBg} hover:opacity-80`
              }`}
            >
              Kârlılar ({kpi.wins})
            </button>
            <button
              type="button"
              onClick={() => setFilterOutcome("LOSS")}
              className={`px-2.5 py-1 rounded-lg font-bold border transition-all ${
                filterOutcome === "LOSS"
                  ? "bg-rose-600 text-white border-rose-600"
                  : `${theme.badgeBg} hover:opacity-80`
              }`}
            >
              Zararlılar ({kpi.losses})
            </button>
          </div>
        </div>

        {closedTrades.length === 0 ? (
          <div className="p-10 text-center space-y-1">
            <p className={`text-sm font-bold ${theme.textPrimary}`}>
              Bugün henüz kapanan forex işlemi bulunmuyor.
            </p>
            <p className={`text-xs ${theme.textSecondary}`}>
              Açık pozisyonlar kâr/stop seviyelerine ulaştığında burada listelenecektir.
            </p>
          </div>
        ) : filteredClosedTrades.length === 0 ? (
          <div className="p-8 text-center text-xs">
            <p className={theme.textSecondary}>Bu filtreye uygun kapanan işlem bulunamadı.</p>
          </div>
        ) : (
          <>
            {/* Masaüstü Tablo Görünümü */}
            <div className="hidden md:block overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead className={`uppercase border-b ${theme.tableHeader}`}>
                  <tr>
                    <th className="py-3 px-4">Sembol / Parite</th>
                    <th className="py-3 px-3">Yön</th>
                    <th className="py-3 px-3">Lot</th>
                    <th className="py-3 px-3">Kapanış Saati</th>
                    <th className="py-3 px-4">Net Kâr / Zarar</th>
                    <th className="py-3 px-3">Net Pip</th>
                    <th className="py-3 px-4 text-right">Durum / Sebep</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 dark:divide-bunker-800/60">
                  {filteredClosedTrades.map((t) => {
                    const isBuy = t.direction === "BUY";
                    const isProfitable = Number(t.pnl_usd ?? 0) >= 0;
                    return (
                      <tr key={t.id || t.ticket || Math.random()} className={theme.tableRow}>
                        <td className="py-3.5 px-4 font-bold text-sm">
                          {t.display || t.symbol}
                        </td>

                        <td className="py-3.5 px-3">
                          <span
                            className={`inline-flex items-center gap-1 px-2.5 py-0.5 rounded text-[11px] font-bold ${
                              isBuy
                                ? "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 border border-emerald-500/30"
                                : "bg-rose-500/15 text-rose-600 dark:text-rose-400 border border-rose-500/30"
                            }`}
                          >
                            {isBuy ? "▲ AL" : "▼ SAT"}
                          </span>
                        </td>

                        <td className="py-3.5 px-3 font-semibold">
                          {t.lots.toFixed(2)} Lot
                        </td>

                        <td className={`py-3.5 px-3 ${theme.textSecondary}`}>
                          {formatClockTime(t.close_time || t.exit_time)}
                        </td>

                        <td className="py-3.5 px-4 whitespace-nowrap">
                          <span
                            className={`inline-flex items-center px-2.5 py-1 rounded-lg border font-black text-sm ${
                              isProfitable ? theme.profitBg : theme.lossBg
                            }`}
                          >
                            {isProfitable ? "+" : ""}${Number(t.pnl_usd).toFixed(2)}
                          </span>
                        </td>

                        <td className="py-3.5 px-3 font-bold">
                          <span className={isProfitable ? "text-emerald-600 dark:text-emerald-400" : "text-rose-600 dark:text-rose-400"}>
                            {t.pnl_pips >= 0 ? "+" : ""}{Number(t.pnl_pips).toFixed(1)}p
                          </span>
                        </td>

                        <td className="py-3.5 px-4 text-right">
                          <span
                            className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase ${
                              isProfitable
                                ? "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400"
                                : "bg-rose-500/15 text-rose-600 dark:text-rose-400"
                            }`}
                          >
                            {t.exit_reason_title || t.exit_reason || (isProfitable ? "KÂR ALINDI" : "STOP LOSS")}
                          </span>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            {/* Mobil Kart Görünümü (Tamamen Mobil Onaylı) */}
            <div className="md:hidden space-y-2.5 p-3">
              {filteredClosedTrades.map((t) => {
                const isBuy = t.direction === "BUY";
                const isProfitable = Number(t.pnl_usd ?? 0) >= 0;
                return (
                  <div
                    key={t.id || t.ticket || Math.random()}
                    className={`p-3 rounded-xl border flex items-center justify-between shadow-sm ${
                      isLightMode ? "bg-slate-50 border-slate-200" : "bg-bunker-950/80 border-bunker-800"
                    }`}
                  >
                    <div>
                      <div className="flex items-center gap-1.5">
                        <span className="font-bold text-sm">{t.display || t.symbol}</span>
                        <span
                          className={`px-1.5 py-0.2 rounded text-[10px] font-bold ${
                            isBuy ? "text-emerald-600 dark:text-emerald-400" : "text-rose-600 dark:text-rose-400"
                          }`}
                        >
                          {isBuy ? "AL" : "SAT"}
                        </span>
                        <span className={`text-[11px] ${theme.textSecondary}`}>{t.lots.toFixed(2)}L</span>
                      </div>
                      <div className={`text-[10px] mt-0.5 ${theme.textSecondary}`}>
                        {formatClockTime(t.close_time || t.exit_time)} · {t.exit_reason_title || (isProfitable ? "TP" : "SL")}
                      </div>
                    </div>

                    <div className="text-right">
                      <div
                        className={`inline-block px-2.5 py-0.5 rounded-lg border text-sm font-black ${
                          isProfitable ? theme.profitBg : theme.lossBg
                        }`}
                      >
                        {isProfitable ? "+" : ""}${Number(t.pnl_usd).toFixed(2)}
                      </div>
                      <div className="text-[10px] font-bold opacity-80 mt-0.5">
                        {t.pnl_pips >= 0 ? "+" : ""}{Number(t.pnl_pips).toFixed(1)}p
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </>
        )}
      </div>

      {/* 5. POZİSYON KAPATMA ONAY MODALI */}
      {closingTarget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm animate-in fade-in duration-150">
          <div
            className={`w-full max-w-sm rounded-2xl border p-5 space-y-4 shadow-2xl ${
              isLightMode ? "bg-white border-slate-300 text-slate-900" : "bg-bunker-900 border-bunker-700 text-white"
            }`}
          >
            <div className="flex items-center justify-between border-b pb-3 border-slate-200 dark:border-bunker-800">
              <h3 className="font-bold text-sm">Pozisyon Kapatma Onayı</h3>
              <button
                type="button"
                onClick={() => setClosingTarget(null)}
                className="text-slate-400 hover:text-slate-600 dark:hover:text-white font-bold"
              >
                ✕
              </button>
            </div>

            <div className="space-y-2 text-xs">
              <p>Aşağıdaki açık forex pozisyonunu anlık piyasa fiyatından kapatmak üzeresiniz:</p>
              <div
                className={`p-3 rounded-xl border space-y-1 font-bold ${
                  isLightMode ? "bg-slate-50 border-slate-200" : "bg-bunker-950 border-bunker-800"
                }`}
              >
                <div>Sembol: <span className="text-blue-500">{closingTarget.display || closingTarget.symbol}</span></div>
                <div>Yön: <span>{closingTarget.direction === "BUY" ? "▲ AL (BUY)" : "▼ SAT (SELL)"}</span></div>
                <div>Lot: <span>{closingTarget.lots} Lot</span></div>
                <div>Anlık K/Z: <span className={closingTarget.pnl_usd >= 0 ? "text-emerald-500" : "text-rose-500"}>
                  {closingTarget.pnl_usd >= 0 ? "+" : ""}${Number(closingTarget.pnl_usd).toFixed(2)}
                </span></div>
              </div>
            </div>

            <div className="flex items-center justify-end gap-2 pt-2">
              <button
                type="button"
                onClick={() => setClosingTarget(null)}
                disabled={isClosing}
                className="px-3.5 py-1.5 rounded-xl border border-slate-300 dark:border-bunker-700 text-xs font-bold hover:bg-slate-100 dark:hover:bg-bunker-800 transition-colors"
              >
                Vazgeç
              </button>
              <button
                type="button"
                onClick={handleConfirmClose}
                disabled={isClosing}
                className="px-4 py-1.5 rounded-xl bg-rose-600 text-white text-xs font-bold hover:bg-rose-500 transition-colors shadow-sm flex items-center gap-1.5"
              >
                {isClosing && <span className="w-3 h-3 border-2 border-white border-t-transparent rounded-full animate-spin" />}
                <span>Evet, Kapat</span>
              </button>
            </div>
          </div>
        </div>
      )}

    </div>
  );
}
