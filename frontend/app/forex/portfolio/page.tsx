"use client";

import React, { useState, useEffect, useMemo } from "react";
import Link from "next/link";
import { apiFetch } from "../../lib/api";
import { usePolling } from "../../lib/usePolling";
import { formatUtc3 } from "../../lib/format";
import GateSnapshotCard, { type GateSnapshot } from "../components/GateSnapshotCard";
import ForexChartModal, { type ForexCandidateMeta } from "../components/ForexChartModal";

// --- VERİ TİPLERİ ---
interface AutoPosition {
  id: string;
  symbol: string;
  display: string;
  direction: "BUY" | "SELL";
  lots: number;
  entry_price: number;
  current_price: number;
  sl_price: number;
  tp_price: number;
  initial_sl_price: number;
  breakeven_activated: boolean;
  trailing_activated: boolean;
  open_time: string;
  pnl_usd: number;
  pnl_pips: number;
  pip_size: number;
  digits: number;
  score: number;
  strategy: string;
}

interface ClosedTrade {
  id: string;
  symbol: string;
  display: string;
  direction: "BUY" | "SELL";
  lots: number;
  entry_price: number;
  exit_price: number;
  exit_time: string;
  exit_reason: string;
  pnl_usd: number;
  pnl_pips: number;
  score?: number;
}

interface SymbolDailyKpi {
  symbol: string;
  display: string;
  trades: number;
  wins: number;
  losses: number;
  win_rate: number;
  pnl_usd: number;
  pnl_pips: number;
  gross_profit_usd: number;
  gross_loss_usd: number;
  profit_factor: number;
  profit_factor_infinite: boolean;
  avg_pnl_usd: number;
  best_trade_usd: number;
  worst_trade_usd: number;
  open_count: number;
  open_pnl_usd: number;
  last_exit_ts: number | null;
  last_exit_time: string;
  last_exit_reason: string;
}

interface DecisionLog {
  id: string;
  time: string;
  created_at_ts?: number;
  category: "ENTRY" | "EXIT" | "PROTECT" | "GATE" | "SYSTEM" | "SCAN";
  symbol?: string;
  strategy?: string;
  strategy_label?: string;
  message: string;
  metadata?: any;
}

interface MT5State {
  connected: boolean;
  last_ping_seconds_ago: number | null;
  auto_trade: boolean;
  account: {
    login: number;
    name: string;
    server: string;
    balance: number;
    equity: number;
    margin: number;
    free_margin: number;
    leverage: number;
    currency: string;
  } | null;
  open_positions: Array<{
    ticket: number;
    symbol: string;
    direction: "BUY" | "SELL";
    lots: number;
    entry_price: number;
    current_price: number;
    sl_price: number;
    tp_price: number;
    pnl_usd: number;
    pnl_pips?: number;
    protection?: "TRAILING" | "BREAKEVEN" | "NORMAL";
    protection_label?: string;
    breakeven_activated?: boolean;
    trailing_activated?: boolean;
    open_time: string;
    strategy?: string;
    strategy_label?: string;
  }>;
  closed_deals: Array<{
    ticket: number;
    symbol: string;
    direction: "BUY" | "SELL";
    lots: number;
    price: number;
    profit: number;
    commission: number;
    time: string;
    strategy?: string;
    strategy_label?: string;
  }>;
  pending_commands_count: number;
}

type TabKey = "portfolio" | "xauusd" | "forex_tech" | "crypto_tech";

// 7/24 Hafta sonu kripto portföyü sembolleri
const CRYPTO_SYMBOLS = [
  { sym: "BTCUSD", name: "Bitcoin", icon: "₿", digits: 2 },
  { sym: "ETHUSD", name: "Ethereum", icon: "Ξ", digits: 2 },
  { sym: "SOLUSD", name: "Solana", icon: "◎", digits: 4 },
  { sym: "BNBUSD", name: "Binance Coin", icon: "🔶", digits: 3 },
  { sym: "XRPUSD", name: "Ripple", icon: "✕", digits: 4 },
  { sym: "LNKUSD", name: "Chainlink", icon: "🔗", digits: 3 },
  { sym: "UNIUSD", name: "Uniswap", icon: "🦄", digits: 4 },
  { sym: "AVXUSD", name: "Avalanche", icon: "🔺", digits: 4 },
  { sym: "ADAUSD", name: "Cardano", icon: "₳", digits: 5 },
  { sym: "XTZUSD", name: "Tezos", icon: "ꜩ", digits: 5 },
  { sym: "DATAUSD", name: "Streamr", icon: "📡", digits: 4 },
];

export default function ForexPortfolioPage({ symbols, title }: { symbols?: string[]; title?: string } = {}) {
  const symFilter: Set<string> | null = symbols ? new Set(symbols.map((s) => s.toUpperCase())) : null;

  // Sekme yönetimi
  const [activeTab, setActiveTab] = useState<TabKey>("portfolio");

  useEffect(() => {
    if (typeof window !== "undefined") {
      const params = new URLSearchParams(window.location.search);
      const tabParam = params.get("tab");
      if (tabParam === "xauusd" || tabParam === "forex_tech" || tabParam === "crypto_tech") {
        setActiveTab(tabParam);
      }
    }
  }, []);

  // IC Markets MT5 Canlı Köprü Durumu
  const [mt5, setMt5] = useState<MT5State>({
    connected: false,
    last_ping_seconds_ago: null,
    auto_trade: false,
    account: null,
    open_positions: [],
    closed_deals: [],
    pending_commands_count: 0,
  });
  const [isTogglingMt5, setIsTogglingMt5] = useState(false);
  const [mt5Message, setMt5Message] = useState<string | null>(null);
  const [mt5MessageIsError, setMt5MessageIsError] = useState(false);
  const [mt5Error, setMt5Error] = useState("");
  const [showMt5Guide, setShowMt5Guide] = useState(false);

  // Otonom Sistem Durumu
  const [autoStatus, setAutoStatus] = useState<string>("Yükleniyor…");
  const [autoEnabled, setAutoEnabled] = useState<boolean>(false);
  const [balance, setBalance] = useState<number>(1000.0);
  const [equity, setEquity] = useState<number>(1000.0);
  const [openPnlUsd, setOpenPnlUsd] = useState<number>(0.0);
  const [openPnlPips, setOpenPnlPips] = useState<number>(0.0);
  const [realizedPnlUsd, setRealizedPnlUsd] = useState<number>(0.0);
  const [realizedPnlPips, setRealizedPnlPips] = useState<number>(0.0);
  const [totalTrades, setTotalTrades] = useState<number>(0);
  const [wins, setWins] = useState<number>(0);
  const [losses, setLosses] = useState<number>(0);
  const [winRate, setWinRate] = useState<number>(0.0);

  // Bugün KPI'ları
  const [dailyWinRate, setDailyWinRate] = useState<number>(0.0);
  const [dailyTrades, setDailyTrades] = useState<number>(0);
  const [dailyWins, setDailyWins] = useState<number>(0);
  const [dailyLosses, setDailyLosses] = useState<number>(0);
  const [dailyPnlUsd, setDailyPnlUsd] = useState<number>(0.0);
  const [dailyPnlPips, setDailyPnlPips] = useState<number>(0.0);

  const [openPositions, setOpenPositions] = useState<AutoPosition[]>([]);
  const [closedTrades, setClosedTrades] = useState<ClosedTrade[]>([]);
  const [perSymbolToday, setPerSymbolToday] = useState<SymbolDailyKpi[]>([]);
  const [perSymbolAllTime, setPerSymbolAllTime] = useState<SymbolDailyKpi[]>([]);
  const [decisionLogs, setDecisionLogs] = useState<DecisionLog[]>([]);
  const [sessions, setSessions] = useState<any[]>([]);

  // Filtreler (Loglar için)
  const [logFilter, setLogFilter] = useState<string>("ALL");
  const [strategyFilter, setStrategyFilter] = useState<string>("ALL");

  // Teknik Veriler & Radar Adayları & Tickers
  const [radarCandidates, setRadarCandidates] = useState<any[]>([]);
  const [tickers, setTickers] = useState<Record<string, any>>({});
  const [gateSnapshotXAU, setGateSnapshotXAU] = useState<GateSnapshot | null>(null);
  const [chartModalCandidate, setChartModalCandidate] = useState<ForexCandidateMeta | null>(null);

  // Forex Teknik sekmesi filtreleri
  const [forexCategoryFilter, setForexCategoryFilter] = useState<string>("ALL");
  const [forexSearchQuery, setForexSearchQuery] = useState<string>("");

  // Kripto sekmesi filtreleri
  const [cryptoSearchQuery, setCryptoSearchQuery] = useState<string>("");

  // Hızlı işlem durumu
  const [isOrdering, setIsOrdering] = useState(false);

  const flashNotice = (text: string, isError = false) => {
    setMt5Message(text);
    setMt5MessageIsError(isError);
    window.setTimeout(() => setMt5Message(null), isError ? 8000 : 5000);
  };

  const fetchStatus = async () => {
    try {
      const res = await apiFetch("/api/forex/auto-paper/status");
      if (res) {
        setAutoStatus(res.status || "Hazır");
        setAutoEnabled(Boolean(res.enabled));
        if (typeof res.balance === "number") setBalance(res.balance);
        if (typeof res.equity === "number") setEquity(res.equity);
        else if (typeof res.balance === "number") setEquity(res.balance);
        setOpenPnlUsd(res.open_pnl_usd ?? 0.0);
        setOpenPnlPips(res.open_pnl_pips ?? 0.0);
        setRealizedPnlUsd(res.realized_pnl_usd ?? 0.0);
        setRealizedPnlPips(res.realized_pnl_pips ?? 0.0);
        setTotalTrades(res.total_trades ?? 0);
        setWins(res.wins ?? 0);
        setLosses(res.losses ?? 0);
        setWinRate(res.win_rate ?? 0.0);
        setDailyWinRate(res.daily_win_rate ?? 0.0);
        setDailyTrades(res.daily_trades ?? 0);
        setDailyWins(res.daily_wins ?? 0);
        setDailyLosses(res.daily_losses ?? 0);
        setDailyPnlUsd(res.daily_pnl ?? 0.0);
        setDailyPnlPips(res.daily_pips ?? 0.0);
        setOpenPositions((res.open_positions || []).filter(
          (p: AutoPosition) => !symFilter || symFilter.has(String(p.symbol).toUpperCase())
        ));
        setClosedTrades((res.closed_trades || []).filter(
          (t: ClosedTrade) => !symFilter || symFilter.has(String(t.symbol).toUpperCase())
        ));
        setPerSymbolToday((res.per_symbol_today || []).filter(
          (k: SymbolDailyKpi) => !symFilter || symFilter.has(String(k.symbol).toUpperCase())
        ));
        setPerSymbolAllTime((res.per_symbol_all_time || []).filter(
          (k: SymbolDailyKpi) => !symFilter || symFilter.has(String(k.symbol).toUpperCase())
        ));
        setDecisionLogs((res.decision_logs || []).filter(
          (l: DecisionLog) => !symFilter || !l.symbol || symFilter.has(String(l.symbol).toUpperCase())
        ));
        setSessions(res.sessions || []);
      }
    } catch (err) {
      const detail = err instanceof Error ? err.message : "Durum alınamadı";
      setAutoStatus(`bağlantı yok: ${detail}`);
    }

    try {
      const mt5Res = await apiFetch("/api/forex/mt5/status");
      if (mt5Res) {
        setMt5({
          ...mt5Res,
          account: mt5Res.account ?? null,
          open_positions: mt5Res.open_positions || [],
          closed_deals: mt5Res.closed_deals || [],
        });
        setMt5Error("");
      }
    } catch (err) {
      const detail = err instanceof Error ? err.message : "MT5 durumu alınamadı";
      setMt5Error(`MT5 bağlantı hatası: ${detail}`);
      setMt5((prev) => ({ ...prev, connected: false }));
    }

    // Teknik ve Radar Verileri
    try {
      const [rRes, tRes] = await Promise.all([
        apiFetch("/api/forex/radar"),
        apiFetch("/api/forex/tickers"),
      ]);
      if (rRes && rRes.candidates) setRadarCandidates(rRes.candidates);
      if (tRes && tRes.tickers) {
        const map: Record<string, any> = {};
        for (const t of tRes.tickers) map[t.symbol] = t;
        setTickers(map);
      }
    } catch (err) {
      // sessizce geç
    }

    // XAUUSD Gate Snapshot (özellikle XAUUSD sekmesi için)
    if (activeTab === "xauusd") {
      try {
        const snap = await apiFetch("/api/forex/auto-paper/gate-snapshot/XAUUSD");
        if (snap && snap.symbol) setGateSnapshotXAU(snap);
      } catch (err) {
        // sessizce geç
      }
    }
  };

  usePolling(fetchStatus, 3000);

  // MT5 Otomatik Emir İletimini Aç / Kapat
  const toggleMt5Auto = async () => {
    setIsTogglingMt5(true);
    try {
      const nextState = !mt5.auto_trade;
      const res = await apiFetch("/api/forex/mt5/toggle-auto", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ auto_trade: nextState }),
      });
      if (res) {
        setMt5((prev) => ({ ...prev, auto_trade: res.auto_trade }));
        flashNotice(
          res.auto_trade
            ? "IC Markets MT5 otomatik emir iletimi açıldı."
            : "IC Markets MT5 otomatik emir iletimi durduruldu."
        );
      }
    } catch (err) {
      const detail = err instanceof Error ? err.message : "Değiştirilemedi";
      flashNotice(`MT5 otomatik işlem değiştirilemedi: ${detail}`, true);
    } finally {
      setIsTogglingMt5(false);
    }
  };

  // Pozisyon Kapatma
  const closeMt5Position = async (ticket: number) => {
    if (!confirm(`Bilet #${ticket} nolu MT5 pozisyonunu kapatmak istiyor musunuz?`)) return;
    try {
      await apiFetch("/api/forex/mt5/close", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ticket }),
      });
      flashNotice(`Bilet #${ticket} kapatma emri MT5 köprüsüne iletildi.`);
      fetchStatus();
    } catch (err) {
      const detail = err instanceof Error ? err.message : "Kapatılamadı";
      flashNotice(`Pozisyon kapatılamadı: ${detail}`, true);
    }
  };

  const closeAllMt5Positions = async () => {
    const count = mt5.open_positions?.length || 0;
    if (count === 0) return;
    if (!confirm(`Açık olan TÜM (${count}) IC Markets MT5 pozisyonunu kapatmak istiyor musunuz?`)) return;
    try {
      await apiFetch("/api/forex/mt5/close-all", { method: "POST" });
      flashNotice(`Tüm (${count}) MT5 pozisyonunu kapatma emri iletildi.`);
      fetchStatus();
    } catch (err) {
      const detail = err instanceof Error ? err.message : "Kapatılamadı";
      flashNotice(`Pozisyonlar kapatılamadı: ${detail}`, true);
    }
  };

  // Hızlı Emir Gönderme (Örn: XAUUSD için)
  const sendQuickOrder = async (symbol: string, direction: "BUY" | "SELL", lots: number) => {
    if (!confirm(`${symbol} için ${lots} lot ${direction} emri göndermek istiyor musunuz?`)) return;
    setIsOrdering(true);
    try {
      const res = await apiFetch("/api/forex/mt5/order", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ symbol, direction, lots, comment: "MANUAL_QUICK" }),
      });
      if (res && res.status === "ok") {
        flashNotice(`✓ ${symbol} ${direction} ${lots} lot emri MT5 köprüsüne iletildi.`);
        fetchStatus();
      } else {
        flashNotice(`Emir iletilemedi: ${res?.message || "Bilinmeyen hata"}`, true);
      }
    } catch (err) {
      const detail = err instanceof Error ? err.message : "Hata";
      flashNotice(`Emir gönderilemedi: ${detail}`, true);
    } finally {
      setIsOrdering(false);
    }
  };

  // CSV İndirme
  const downloadCsv = () => {
    if (closedTrades.length === 0) return;
    const header = "İşlem ID;Sembol;Yön;Lot;Giriş;Çıkış;Kapanış Zamanı;Çıkış Nedeni;Net Kâr ($);Pip\n";
    const rows = closedTrades
      .map(
        (t) =>
          `"${t.id}";"${t.symbol}";"${t.direction}";${t.lots};${t.entry_price};${t.exit_price};"${formatUtc3(
            t.exit_time
          )}";"${t.exit_reason || ""}";${t.pnl_usd.toFixed(2)};${t.pnl_pips.toFixed(1)}`
      )
      .join("\n");
    const blob = new Blob(["\uFEFF" + header + rows], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `Forex_Kapali_Islemler_${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  // XAUUSD adayı ve ticker verisi
  const xauCandidate = useMemo(() => {
    return radarCandidates.find((c) => c.symbol === "XAUUSD") || null;
  }, [radarCandidates]);

  const xauTicker = useMemo(() => {
    return tickers["XAUUSD"] || null;
  }, [tickers]);

  // Forex Pariteleri (Kripto ve Altın hariç veya dahil filtrelenmiş)
  const filteredForexCandidates = useMemo(() => {
    return radarCandidates.filter((c) => {
      // Kripto olmayanlar
      const isCrypto = c.category === "crypto" || CRYPTO_SYMBOLS.some((cs) => cs.sym === c.symbol);
      if (isCrypto) return false;

      // Kategori filtresi
      if (forexCategoryFilter !== "ALL") {
        if (forexCategoryFilter === "major" && c.category !== "major") return false;
        if (forexCategoryFilter === "cross" && c.category !== "cross") return false;
        if (forexCategoryFilter === "commodity" && c.category !== "commodity") return false;
        if (forexCategoryFilter === "index" && c.category !== "index") return false;
        if (forexCategoryFilter === "jpy" && !c.symbol.includes("JPY")) return false;
        if (forexCategoryFilter === "eur" && !c.symbol.includes("EUR")) return false;
        if (forexCategoryFilter === "gbp" && !c.symbol.includes("GBP")) return false;
      }

      // Arama filtresi
      if (forexSearchQuery.trim()) {
        const q = forexSearchQuery.trim().toLowerCase();
        return `${c.symbol} ${c.display} ${c.name}`.toLowerCase().includes(q);
      }
      return true;
    });
  }, [radarCandidates, forexCategoryFilter, forexSearchQuery]);

  // Kripto Pariteleri (10'lu hafta sonu portföyü)
  const cryptoCandidatesList = useMemo(() => {
    return CRYPTO_SYMBOLS.map((def) => {
      const cand = radarCandidates.find((c) => c.symbol === def.sym) || null;
      const tick = tickers[def.sym] || null;
      return {
        ...def,
        candidate: cand,
        ticker: tick,
      };
    }).filter((c) => {
      if (cryptoSearchQuery.trim()) {
        const q = cryptoSearchQuery.trim().toLowerCase();
        return `${c.sym} ${c.name}`.toLowerCase().includes(q);
      }
      return true;
    });
  }, [radarCandidates, tickers, cryptoSearchQuery]);

  const activeSessions = sessions.filter((s) => s.active);

  return (
    <div className="space-y-5 pb-16 font-sans">
      {/* ÜST BAŞLIK VE KONTROL PANELİ */}
      <div className="p-4 rounded-2xl bg-gradient-to-r from-blue-950/40 via-slate-900/60 to-indigo-950/40 border border-blue-500/20 backdrop-blur-md shadow-lg flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="w-12 h-12 rounded-xl bg-blue-500/20 border border-blue-400/40 flex items-center justify-center text-2xl shadow-[0_0_16px_rgba(59,130,246,0.3)]">
            💼
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-xl font-bold font-mono text-white tracking-tight">
                {title || "FOREX PORTFÖY & ALGORİTMA KOMUTA"}
              </h1>
              <span
                className={`px-2 py-0.5 rounded text-[10px] font-mono font-bold border ${
                  mt5.connected
                    ? "bg-emerald-500/20 text-emerald-300 border-emerald-400/40"
                    : "bg-rose-500/20 text-rose-300 border-rose-400/40"
                }`}
              >
                {mt5.connected ? "MT5 CANLI BAĞLI" : "MT5 KÖPRÜSÜ BEKLENİYOR"}
              </span>
            </div>
            <p className="text-xs text-bunker-muted font-mono mt-0.5">
              IC Markets MT5 canlı veri hattı, çoklu strateji motorları ve 7/24 piyasa takibi
            </p>
          </div>
        </div>

        {/* Hızlı İşlem & Ayar Düğmeleri */}
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={toggleMt5Auto}
            disabled={isTogglingMt5 || !mt5.connected}
            className={`px-3.5 py-2 rounded-xl font-mono text-xs font-bold transition-all shadow-md flex items-center gap-2 ${
              mt5.auto_trade
                ? "bg-emerald-600 hover:bg-emerald-500 text-white shadow-emerald-600/30"
                : "bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700"
            }`}
          >
            <span>{mt5.auto_trade ? "🟢 Otonom Scalper Aktif" : "⏸️ Otonom Scalper Durduruldu"}</span>
          </button>

          <Link
            href="/settings"
            className="px-3 py-2 rounded-xl bg-bunker-800 hover:bg-bunker-700 text-slate-200 border border-bunker-700 text-xs font-bold transition-all flex items-center gap-1.5"
            title="Forex & Algoritma Ayarlarını Aç"
          >
            <span>⚙️</span>
            <span>Ayarlar</span>
          </Link>

          <button
            type="button"
            onClick={() => setShowMt5Guide((p) => !p)}
            className="px-2.5 py-2 rounded-xl bg-bunker-800 hover:bg-bunker-700 text-bunker-muted hover:text-white border border-bunker-700 text-xs font-bold"
            title="Yardım & Rehber"
          >
            ❓
          </button>
        </div>
      </div>

      {/* BİLDİRİM / HATA ÇUBUĞU */}
      {(mt5Error || mt5Message) && (
        <div
          role="alert"
          className={`px-4 py-2 rounded-xl border font-mono text-xs ${
            mt5Error || mt5MessageIsError
              ? "bg-rose-500/10 border-rose-500/40 text-rose-300"
              : "bg-emerald-500/10 border-emerald-500/40 text-emerald-300"
          }`}
        >
          {mt5Error && <p>{mt5Error}</p>}
          {mt5Message && <p>{mt5Message}</p>}
        </div>
      )}

      {/* REHBER PANELİ */}
      {showMt5Guide && (
        <div className="p-4 rounded-xl bg-bunker-950 border border-blue-500/30 text-xs text-bunker-muted space-y-2">
          <div className="font-bold text-white flex items-center gap-1.5">
            <span>🚀 IC Markets MT5 ve 4 Sekmeli Komuta Merkezi Nasıl Çalışır?</span>
          </div>
          <ol className="list-decimal list-inside space-y-1.5 text-[11px] leading-relaxed">
            <li><strong>Portföy &amp; İşlemler:</strong> Hesap bakiyesi, kâr/zarar, sembol başarı kartları ve anlık açık pozisyonları izleyip yönetebilirsiniz.</li>
            <li><strong>XAUUSD Komuta Merkezi:</strong> Altın paritesi için 18-kapılı filtre durumunu, teknik göstergeleri ve sistemin tüm karar loglarını saniye saniye denetler.</li>
            <li><strong>Forex Çiftleri:</strong> Tüm majör ve çapraz paritelerin anlık trendini, skorunu ve RSI seviyelerini tek ızgarada sunar.</li>
            <li><strong>Kripto Çiftleri (7/24):</strong> Hafta sonları Forex kapalıyken devrede olan 10 IC Markets kripto varlığında FVG ve S3 durumunu gösterir.</li>
          </ol>
        </div>
      )}

      {/* 4 ANA SEKME BAŞLIKLARI */}
      <div className="flex flex-wrap gap-2 border-b border-bunker-800 pb-2">
        {[
          { id: "portfolio", label: "💼 Portföy & İşlemler", badge: `${mt5.open_positions?.length || 0} Açık` },
          { id: "xauusd", label: "🥇 XAUUSD Komuta & Loglar", badge: xauCandidate ? `Skor ${xauCandidate.score}` : "Canlı" },
          { id: "forex_tech", label: "💱 Forex Çiftleri Teknik Analiz", badge: `${filteredForexCandidates.length} Parite` },
          { id: "crypto_tech", label: "⚡ Kripto Çiftleri (7/24)", badge: "10 Varlık" },
        ].map((tab) => (
          <button
            key={tab.id}
            type="button"
            onClick={() => setActiveTab(tab.id as TabKey)}
            className={`px-4 py-2.5 rounded-xl font-bold text-xs transition-all border flex items-center gap-2 ${
              activeTab === tab.id
                ? "bg-blue-600/25 text-blue-300 border-blue-500/60 shadow-lg shadow-blue-500/10"
                : "bg-bunker-900/60 text-bunker-muted border-bunker-800 hover:text-white hover:bg-bunker-800"
            }`}
          >
            <span>{tab.label}</span>
            <span
              className={`text-[10px] px-2 py-0.5 rounded-full font-mono font-bold ${
                activeTab === tab.id
                  ? "bg-blue-500/30 text-blue-200"
                  : "bg-bunker-800 text-bunker-muted"
              }`}
            >
              {tab.badge}
            </span>
          </button>
        ))}
      </div>

      {/* ========================================================================= */}
      {/* SEKME 1: GENEL PORTFÖY, AÇIK İŞLEMLER VE SEMBOL BAŞARI KARTLARI */}
      {/* ========================================================================= */}
      {activeTab === "portfolio" && (
        <div className="space-y-5 animate-in fade-in duration-150">
          {/* IC Markets MT5 Canlı Metrikleri */}
          {(() => {
            const liveBal = mt5.account ? Number(mt5.account.balance) : balance;
            const liveEq = mt5.account ? Number(mt5.account.equity) : equity;
            const liveMargin = mt5.account ? Number(mt5.account.free_margin) : null;
            const livePnl = (mt5.open_positions || []).reduce(
              (acc, p) => acc + Number(p.pnl_usd ?? (p as any).profit ?? 0),
              0
            );
            return (
              <div className="grid grid-cols-2 md:grid-cols-6 gap-3">
                <div className="p-3.5 rounded-xl bg-bunker-900/80 border border-bunker-800 shadow-sm">
                  <span className="text-[11px] font-bold text-bunker-muted uppercase block">IC Markets Bakiye</span>
                  <span className="text-lg font-black text-emerald-400 font-mono">
                    {liveBal == null ? "—" : `$${liveBal.toFixed(2)}`} <span className="text-xs font-normal text-bunker-muted">{mt5.account?.currency || "USD"}</span>
                  </span>
                  <span className="text-[10px] font-semibold text-bunker-muted block mt-0.5">Kapanan net bakiye</span>
                </div>

                <div className="p-3.5 rounded-xl bg-bunker-900/80 border border-bunker-800 shadow-sm">
                  <span className="text-[11px] font-bold text-bunker-muted uppercase block">Özsermaye (Equity)</span>
                  <span className={`text-lg font-black font-mono ${liveEq != null && liveBal != null && liveEq >= liveBal ? "text-cyan-300" : "text-rose-400"}`}>
                    {liveEq == null ? "—" : `$${liveEq.toFixed(2)}`}
                  </span>
                  <span className="text-[10px] font-semibold text-bunker-muted block mt-0.5">Serbest: {liveMargin == null ? "—" : `$${liveMargin.toFixed(2)}`}</span>
                </div>

                <div className="p-3.5 rounded-xl bg-bunker-900/80 border border-bunker-800 shadow-sm">
                  <span className="text-[11px] font-bold text-bunker-muted uppercase block">Açık PnL (Anlık)</span>
                  <span className={`text-lg font-black font-mono ${livePnl >= 0 ? "text-emerald-400" : "text-rose-400"}`}>
                    {livePnl >= 0 ? "+" : ""}${livePnl.toFixed(2)}
                  </span>
                  <span className="text-[10px] font-semibold text-bunker-muted block mt-0.5">{mt5.open_positions?.length || 0} açık işlem</span>
                </div>

                <div className="p-3.5 rounded-xl bg-bunker-900/80 border border-bunker-800 shadow-sm">
                  <span className="text-[11px] font-bold text-bunker-muted uppercase block">Hesap / Sunucu</span>
                  <span className="text-base font-black text-white tracking-wide">
                    {mt5.account?.login ?? "—"}
                  </span>
                  <span className="text-[10px] font-bold text-emerald-400 block mt-0.5 truncate">{mt5.account?.server ?? "—"}</span>
                </div>

                <div className="p-3.5 rounded-xl bg-bunker-900/80 border border-bunker-800 shadow-sm">
                  <span className="text-[11px] font-bold text-bunker-muted uppercase block">Kaldıraç &amp; Sahip</span>
                  <span className="text-base font-black text-yellow-300">
                    {mt5.account?.leverage != null ? `1:${mt5.account.leverage}` : "—"}
                  </span>
                  <span className="text-[10px] font-bold text-bunker-muted block mt-0.5 truncate">{mt5.account?.name ?? "—"}</span>
                </div>

                <div className="p-3.5 rounded-xl bg-bunker-900/80 border border-bunker-800 shadow-sm">
                  <span className="text-[11px] font-bold text-bunker-muted uppercase block">Aktif Seanslar</span>
                  <div className="flex items-center gap-1 mt-1 overflow-x-auto">
                    {activeSessions.length > 0 ? (
                      activeSessions.map((s) => (
                        <span
                          key={s.name}
                          className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-emerald-500/15 text-emerald-400 border border-emerald-500/30 whitespace-nowrap"
                        >
                          {s.flag} {s.name}
                        </span>
                      ))
                    ) : (
                      <span className="text-[11px] font-semibold text-bunker-muted">7/24 Açık</span>
                    )}
                  </div>
                </div>
              </div>
            );
          })()}

          {/* Günlük ve Tüm Zamanlar Başarı Kartları */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {[
              {
                title: "GÜNLÜK SİSTEM BAŞARISI",
                badge: "Bugün (UTC)",
                badgeCls: "bg-blue-500/15 text-blue-300 border-blue-400/30",
                rate: dailyWinRate,
                w: dailyWins,
                l: dailyLosses,
                n: dailyTrades,
                pnlUsd: dailyPnlUsd,
                pnlPips: dailyPnlPips,
              },
              {
                title: "TÜM ZAMANLAR BAŞARI ORANI",
                badge: "Kayıtlı Defter",
                badgeCls: "bg-bunker-800 text-bunker-muted border-bunker-700",
                rate: winRate,
                w: wins,
                l: losses,
                n: totalTrades,
                pnlUsd: realizedPnlUsd,
                pnlPips: realizedPnlPips,
              },
            ].map((b) => {
              const hasTrades = b.n > 0;
              const rateTone = !hasTrades
                ? "text-bunker-muted"
                : b.rate >= 50
                ? "text-emerald-400"
                : "text-rose-400";
              return (
                <div key={b.title} className="p-3.5 rounded-xl bg-bunker-900/80 border border-bunker-800 shadow-sm">
                  <div className="flex items-center justify-between gap-2 flex-wrap">
                    <span className="text-[11px] font-bold text-bunker-muted uppercase">{b.title}</span>
                    <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full border ${b.badgeCls}`}>
                      {b.badge}
                    </span>
                  </div>
                  <div className="flex items-baseline gap-3 mt-1">
                    <span className={`text-2xl font-black font-mono ${rateTone}`}>
                      {hasTrades ? `%${b.rate.toFixed(1)}` : "—"}
                    </span>
                    <span className="text-[11px] font-semibold text-bunker-muted font-mono">
                      {hasTrades ? `${b.w}K / ${b.l}Z (${b.n} İşlem)` : "Kapanan işlem yok"}
                    </span>
                  </div>
                  <div className="mt-1.5 pt-1.5 border-t border-bunker-800 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px]">
                    <span className="font-bold text-bunker-muted">NET KÂRLILIK</span>
                    <span className={`font-mono font-black ${b.pnlUsd >= 0 ? "text-emerald-400" : "text-rose-400"}`}>
                      {b.pnlUsd >= 0 ? "+" : ""}${b.pnlUsd.toFixed(2)}
                    </span>
                    <span className={`font-mono font-bold ${b.pnlPips >= 0 ? "text-emerald-400/80" : "text-rose-400/80"}`}>
                      {b.pnlPips >= 0 ? "+" : ""}{b.pnlPips.toFixed(1)} pip
                    </span>
                  </div>
                </div>
              );
            })}
          </div>

          {/* Sembol Bazlı Performans Kartları */}
          <div className="space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-2 px-1">
              <div className="flex items-center gap-2">
                <span className="text-base">📊</span>
                <h2 className="text-sm font-black text-white uppercase tracking-wider">
                  Sembol Bazlı Başarı Kartları
                </h2>
                <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-blue-500/15 text-blue-300 border border-blue-400/30">
                  Bugün &amp; Tüm Zamanlar
                </span>
              </div>
            </div>

            {perSymbolToday.length === 0 ? (
              <div className="p-6 rounded-2xl border border-bunker-800 bg-bunker-900/70 text-center text-xs text-bunker-muted">
                <p className="text-sm font-bold text-white">Bugün henüz sonuçlanan işlem bulunmuyor.</p>
                <p className="mt-1">Piyasa kapalı olabilir ya da motor yeni sinyal bekliyor.</p>
              </div>
            ) : (
              <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-3">
                {perSymbolToday.map((k) => {
                  const hasTrades = k.trades > 0;
                  const hasOpen = k.open_count > 0;
                  const wrTone = !hasTrades ? "text-bunker-muted" : k.win_rate >= 50 ? "text-emerald-400" : "text-rose-400";
                  const mainUsd = hasTrades ? k.pnl_usd : k.open_pnl_usd;
                  const mainTone = !hasTrades && !hasOpen ? "text-bunker-muted" : mainUsd >= 0 ? "text-emerald-400" : "text-rose-400";
                  const all = perSymbolAllTime.find((a) => a.symbol === k.symbol) || null;

                  return (
                    <div key={k.symbol} className="p-3.5 rounded-xl bg-bunker-900/80 border border-bunker-800 shadow-sm">
                      <div className="flex items-start justify-between gap-1.5">
                        <span className="text-[11px] font-bold text-white uppercase block truncate">{k.symbol}</span>
                        {hasOpen ? (
                          <span className="px-1.5 py-0.5 rounded text-[9px] font-black bg-amber-500/20 text-amber-300 border border-amber-400/40">
                            ⚡ {k.open_count} AÇIK
                          </span>
                        ) : hasTrades ? (
                          <span className="px-1.5 py-0.5 rounded text-[9px] font-black bg-bunker-800 text-bunker-muted border border-bunker-700">
                            {k.trades} İŞLEM
                          </span>
                        ) : null}
                      </div>

                      <span className={`text-lg font-black font-mono block mt-1 ${mainTone}`}>
                        {hasTrades ? `${k.pnl_usd >= 0 ? "+" : ""}$${k.pnl_usd.toFixed(2)}` : hasOpen ? `${k.open_pnl_usd >= 0 ? "+" : ""}$${k.open_pnl_usd.toFixed(2)}` : "—"}
                      </span>

                      <span className="text-[10px] font-semibold text-bunker-muted block mt-0.5">
                        {hasTrades ? `${k.pnl_pips >= 0 ? "+" : ""}${k.pnl_pips} pip · ${k.wins}K/${k.losses}Z` : "İşlem yok"}
                      </span>

                      {all && (
                        <div className="mt-1.5 pt-1.5 border-t border-bunker-800/70 text-[9px]">
                          <div className="flex justify-between items-center text-bunker-muted">
                            <span>Tüm Zamanlar</span>
                            <span className={all.win_rate >= 50 ? "text-emerald-400 font-bold" : "text-rose-400 font-bold"}>
                              %{all.win_rate.toFixed(0)} ({all.trades})
                            </span>
                          </div>
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          {/* Canlı Açık MT5 Pozisyonları */}
          <div className="rounded-2xl border border-bunker-800 bg-bunker-900/70 overflow-hidden shadow-xl">
            <div className="p-4 border-b border-bunker-800 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
              <div className="flex items-center gap-2">
                <span className="text-lg">⚡</span>
                <h2 className="text-sm font-black text-white uppercase tracking-wider">
                  Canlı IC Markets MT5 Açık Pozisyonları ({mt5.open_positions?.length || 0})
                </h2>
              </div>

              {mt5.open_positions && mt5.open_positions.length > 0 && (
                <button
                  type="button"
                  onClick={closeAllMt5Positions}
                  className="px-3 py-1 rounded-lg bg-rose-600/25 border border-rose-500/50 text-rose-300 hover:bg-rose-600/40 text-xs font-bold transition-all flex items-center gap-1.5 shadow-sm"
                >
                  <span>🛑 Tüm Pozisyonları Kapat ({mt5.open_positions.length})</span>
                </button>
              )}
            </div>

            {(!mt5.open_positions || mt5.open_positions.length === 0) ? (
              <div className="p-10 text-center text-bunker-muted text-xs space-y-1">
                <p className="text-sm font-bold text-white">Şu an açık bir MT5 pozisyonu bulunmuyor.</p>
                <p>Otonom motor canlı sinyalleri izliyor. Teyitli sinyal geldiğinde işlem anında açılır.</p>
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs font-mono">
                  <thead className="bg-bunker-950/80 text-bunker-muted uppercase border-b border-bunker-800 text-[11px] font-black">
                    <tr>
                      <th className="py-3 px-4">Bilet</th>
                      <th className="py-3 px-3">Parite</th>
                      <th className="py-3 px-3">Yön</th>
                      <th className="py-3 px-3">Rozet / Koruma</th>
                      <th className="py-3 px-3">Lot</th>
                      <th className="py-3 px-3">Giriş</th>
                      <th className="py-3 px-3">Güncel</th>
                      <th className="py-3 px-3">SL / TP</th>
                      <th className="py-3 px-3">Kâr ($ / Pip)</th>
                      <th className="py-3 px-4 text-right">Aksiyon</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-bunker-800/60">
                    {mt5.open_positions.map((p) => {
                      const pnlVal = Number(p.pnl_usd ?? (p as any).profit ?? 0);
                      const isProfit = pnlVal >= 0;
                      const isTrailing = p.protection === "TRAILING" || !!p.trailing_activated;
                      const isBE = (p.protection === "BREAKEVEN" || !!p.breakeven_activated) && !isTrailing;

                      return (
                        <tr key={p.ticket} className="hover:bg-bunker-800/40 transition-colors">
                          <td className="py-3 px-4 text-cyan-300 font-black">#{p.ticket}</td>
                          <td className="py-3 px-3">
                            <span className="font-black text-white text-sm">{p.symbol}</span>
                            {(p.strategy_label || p.strategy) && (
                              <span className="ml-1.5 px-1.5 py-0.5 rounded text-[9px] font-bold bg-purple-900/40 text-purple-300 border border-purple-600/50">
                                {p.strategy_label || p.strategy}
                              </span>
                            )}
                          </td>
                          <td className="py-3 px-3">
                            <span
                              className={`px-2 py-0.5 rounded text-[10px] font-black ${
                                p.direction === "BUY"
                                  ? "bg-emerald-500/15 text-emerald-400 border border-emerald-500/30"
                                  : "bg-rose-500/15 text-rose-400 border border-rose-500/30"
                              }`}
                            >
                              {p.direction}
                            </span>
                          </td>
                          <td className="py-3 px-3">
                            {isTrailing ? (
                              <span className="px-2 py-0.5 rounded text-[10px] font-black bg-amber-500/20 text-amber-300 border border-amber-400/40">
                                🏃 TRAILING STOP
                              </span>
                            ) : isBE ? (
                              <span className="px-2 py-0.5 rounded text-[10px] font-black bg-cyan-500/20 text-cyan-300 border border-cyan-400/40">
                                🛡️ BAŞABAŞ (BE)
                              </span>
                            ) : (
                              <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-bunker-800 text-bunker-muted">
                                🛑 Sabit SL
                              </span>
                            )}
                          </td>
                          <td className="py-3 px-3 text-white font-bold">{p.lots} Lot</td>
                          <td className="py-3 px-3 text-bunker-muted">{p.entry_price}</td>
                          <td className="py-3 px-3 text-white font-bold">{p.current_price}</td>
                          <td className="py-3 px-3 text-xs">
                            <div className="text-rose-400">SL: {p.sl_price || "—"}</div>
                            <div className="text-emerald-400">TP: {p.tp_price || "—"}</div>
                          </td>
                          <td className={`py-3 px-3 ${isProfit ? "text-emerald-400" : "text-rose-400"} font-black`}>
                            <div>{isProfit ? "+" : ""}${pnlVal.toFixed(2)}</div>
                            {p.pnl_pips != null && (
                              <div className="text-[10px] font-normal">{Number(p.pnl_pips) >= 0 ? "+" : ""}{p.pnl_pips} p</div>
                            )}
                          </td>
                          <td className="py-3 px-4 text-right">
                            <button
                              type="button"
                              onClick={() => closeMt5Position(p.ticket)}
                              className="px-2.5 py-1 rounded bg-rose-500/20 hover:bg-rose-500/40 text-rose-300 border border-rose-500/40 text-xs font-bold transition-all"
                            >
                              Kapat
                            </button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* Kapanan İşlemler Tablosu */}
          <div className="rounded-2xl border border-bunker-800 bg-bunker-900/70 p-4 shadow-xl">
            <div className="flex items-center justify-between border-b border-bunker-800 pb-3 mb-3">
              <div className="flex items-center gap-2">
                <span className="text-base">🏁</span>
                <h3 className="text-xs font-black text-white uppercase tracking-wider">
                  Kapanan Scalp İşlemleri ({closedTrades.length})
                </h3>
              </div>
              <button
                type="button"
                onClick={downloadCsv}
                disabled={closedTrades.length === 0}
                className="px-3 py-1 rounded-lg text-xs font-bold bg-blue-600/30 text-blue-300 border border-blue-400/40 hover:bg-blue-600/50 transition-all disabled:opacity-40 flex items-center gap-1.5"
              >
                <span>📥</span>
                <span>CSV İndir</span>
              </button>
            </div>

            <div className="max-h-72 overflow-y-auto space-y-2 pr-1 text-xs">
              {closedTrades.length === 0 ? (
                <div className="text-center py-8 text-bunker-muted">Henüz kapanmış bir işlem bulunmuyor.</div>
              ) : (
                closedTrades.slice(0, 30).map((tr: any, idx: number) => {
                  const pnlVal = Number(tr.pnl_usd ?? tr.profit ?? 0);
                  const isWin = pnlVal >= 0;
                  return (
                    <div
                      key={tr.id ?? tr.ticket ?? idx}
                      className="p-2.5 rounded-lg border border-bunker-800 bg-bunker-950/60 flex items-center justify-between"
                    >
                      <div>
                        <div className="flex items-center gap-2">
                          <span className="font-black text-white">{tr.symbol}</span>
                          <span className={`px-1.5 py-0.2 rounded text-[9px] font-black ${tr.direction === "BUY" ? "text-emerald-400" : "text-rose-400"}`}>
                            {tr.direction}
                          </span>
                          <span className="text-bunker-muted text-[10px]">{tr.lots} Lot</span>
                          <span className="text-bunker-muted text-[10px]">({tr.exit_reason || "MT5 Kapanış"})</span>
                        </div>
                        <div className="text-[10px] text-bunker-muted mt-0.5">
                          {tr.entry_price} → {tr.exit_price} ({formatUtc3(tr.exit_time)})
                        </div>
                      </div>
                      <div className={`font-black text-xs font-mono text-right ${isWin ? "text-emerald-400" : "text-rose-400"}`}>
                        {isWin ? "+" : ""}${pnlVal.toFixed(2)}
                      </div>
                    </div>
                  );
                })
              )}
            </div>
          </div>
        </div>
      )}

      {/* ========================================================================= */}
      {/* SEKME 2: XAUUSD TEKNİK VERİLERİ VE SİSTEM ALGORİTMALARININ TARAMA LOGLARI */}
      {/* ========================================================================= */}
      {activeTab === "xauusd" && (
        <div className="space-y-5 animate-in fade-in duration-150">
          {/* XAUUSD Canlı Fiyat & Gösterge Başlığı */}
          <div className="p-4 rounded-2xl bg-gradient-to-r from-amber-950/40 via-yellow-950/20 to-slate-900 border border-amber-500/30 shadow-xl flex flex-wrap items-center justify-between gap-4">
            <div className="flex items-center gap-3">
              <div className="w-12 h-12 rounded-xl bg-amber-500/20 border border-amber-400/50 flex items-center justify-center text-2xl shadow-[0_0_16px_rgba(245,158,11,0.3)]">
                🥇
              </div>
              <div>
                <div className="flex items-center gap-2">
                  <h2 className="text-lg font-black text-white">XAUUSD — ONS ALTIN KOMUTA MERKEZİ</h2>
                  <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-amber-500/20 text-amber-300 border border-amber-400/40">
                    SPOT / MT5
                  </span>
                </div>
                <div className="flex items-center gap-3 text-xs text-bunker-muted font-mono mt-0.5">
                  <span>Fiyat: <strong className="text-white text-sm">${xauCandidate?.price?.toFixed(2) || xauTicker?.bid?.toFixed(2) || "—"}</strong></span>
                  <span>Spread: <strong className="text-amber-300">{xauCandidate?.spread_pips ?? xauTicker?.spread_pips ?? "—"} pip</strong></span>
                  <span>Trend: <strong className={xauCandidate?.trend === "BULL" ? "text-emerald-400" : "text-rose-400"}>{xauCandidate?.trend || "Nötr"}</strong></span>
                </div>
              </div>
            </div>

            {/* Hızlı İşlem Düğmeleri */}
            <div className="flex items-center gap-2">
              <button
                type="button"
                disabled={isOrdering || !mt5.connected}
                onClick={() => sendQuickOrder("XAUUSD", "BUY", 0.01)}
                className="px-3 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white font-bold text-xs shadow-md transition-all flex items-center gap-1 disabled:opacity-40"
              >
                ▲ Hızlı BUY 0.01
              </button>
              <button
                type="button"
                disabled={isOrdering || !mt5.connected}
                onClick={() => sendQuickOrder("XAUUSD", "SELL", 0.01)}
                className="px-3 py-1.5 rounded-lg bg-rose-600 hover:bg-rose-500 text-white font-bold text-xs shadow-md transition-all flex items-center gap-1 disabled:opacity-40"
              >
                ▼ Hızlı SELL 0.01
              </button>
              {xauCandidate && (
                <button
                  type="button"
                  onClick={() => setChartModalCandidate(xauCandidate)}
                  className="px-3 py-1.5 rounded-lg bg-blue-600/30 border border-blue-400/40 text-blue-300 hover:bg-blue-600/50 text-xs font-bold transition-all"
                >
                  📈 Grafik
                </button>
              )}
            </div>
          </div>

          {/* XAUUSD 6'lı Teknik İndikatör Kartları */}
          <div className="grid grid-cols-2 md:grid-cols-6 gap-3 font-mono">
            <div className="p-3.5 rounded-xl bg-bunker-900/80 border border-bunker-800">
              <span className="text-[10px] text-bunker-muted uppercase block">RSI (5M / 15M)</span>
              <span className="text-lg font-black text-cyan-300 block mt-1">
                {xauCandidate?.rsi_5m ? xauCandidate.rsi_5m.toFixed(1) : "—"}
              </span>
              <span className="text-[10px] text-bunker-muted">15M: {xauCandidate?.rsi_15m ? xauCandidate.rsi_15m.toFixed(1) : "—"}</span>
            </div>

            <div className="p-3.5 rounded-xl bg-bunker-900/80 border border-bunker-800">
              <span className="text-[10px] text-bunker-muted uppercase block">SuperTrend Yönü</span>
              <span className={`text-lg font-black block mt-1 ${xauCandidate?.supertrend_dir && xauCandidate.supertrend_dir > 0 ? "text-emerald-400" : "text-rose-400"}`}>
                {xauCandidate?.supertrend_dir && xauCandidate.supertrend_dir > 0 ? "▲ BOĞA" : "▼ AYI"}
              </span>
              <span className="text-[10px] text-bunker-muted">M5 Teyitli</span>
            </div>

            <div className="p-3.5 rounded-xl bg-bunker-900/80 border border-bunker-800">
              <span className="text-[10px] text-bunker-muted uppercase block">ADX Trend Gücü</span>
              <span className={`text-lg font-black block mt-1 ${xauCandidate?.adx && xauCandidate.adx >= 25 ? "text-emerald-400" : "text-yellow-400"}`}>
                {xauCandidate?.adx ? xauCandidate.adx.toFixed(1) : "—"}
              </span>
              <span className="text-[10px] text-bunker-muted">{xauCandidate?.adx && xauCandidate.adx >= 25 ? "Güçlü Trend" : "Yatay / Chop"}</span>
            </div>

            <div className="p-3.5 rounded-xl bg-bunker-900/80 border border-bunker-800">
              <span className="text-[10px] text-bunker-muted uppercase block">ATR Volatilite</span>
              <span className="text-lg font-black text-amber-300 block mt-1">
                {xauCandidate?.atr_pips ? `${xauCandidate.atr_pips} p` : "—"}
              </span>
              <span className="text-[10px] text-bunker-muted">Dinamik Stop Çarpanı</span>
            </div>

            <div className="p-3.5 rounded-xl bg-bunker-900/80 border border-bunker-800">
              <span className="text-[10px] text-bunker-muted uppercase block">Radar Skoru</span>
              <span className="text-lg font-black text-purple-300 block mt-1">
                {xauCandidate?.score ? `${xauCandidate.score}/100` : "—"}
              </span>
              <span className="text-[10px] text-bunker-muted">Eşik: 75.0</span>
            </div>

            <div className="p-3.5 rounded-xl bg-bunker-900/80 border border-bunker-800">
              <span className="text-[10px] text-bunker-muted uppercase block">CSM Dolar Farkı</span>
              <span className={`text-lg font-black block mt-1 ${xauCandidate?.csm_diff && xauCandidate.csm_diff > 0 ? "text-emerald-400" : "text-rose-400"}`}>
                {xauCandidate?.csm_diff ? `${xauCandidate.csm_diff > 0 ? "+" : ""}${xauCandidate.csm_diff.toFixed(1)}` : "—"}
              </span>
              <span className="text-[10px] text-bunker-muted">Altın vs USD Akışı</span>
            </div>
          </div>

          {/* XAUUSD 18-Kapı Zincir Durumu (GateSnapshotCard) */}
          {gateSnapshotXAU && (
            <div className="space-y-2">
              <h3 className="text-xs font-black text-white uppercase tracking-wider flex items-center gap-2">
                <span>🛡️</span>
                <span>XAUUSD Otonom Karar Kapıları Zinciri</span>
              </h3>
              <GateSnapshotCard snapshot={gateSnapshotXAU} />
            </div>
          )}

          {/* Sistem Algoritmaları Tarama & Karar Logları */}
          <div className="rounded-2xl border border-bunker-800 bg-bunker-900/70 p-4 shadow-xl space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-bunker-800 pb-3">
              <div className="flex items-center gap-2">
                <span className="text-base">📜</span>
                <h3 className="text-xs font-black text-white uppercase tracking-wider">
                  Sistem Algoritmaları Karar &amp; Tarama Logları ({decisionLogs.length})
                </h3>
              </div>

              {/* Kategori Filtresi */}
              <div className="flex flex-wrap items-center gap-1.5 text-xs">
                {["ALL", "ENTRY", "EXIT", "PROTECT", "GATE", "SCAN", "SYSTEM"].map((cat) => (
                  <button
                    key={cat}
                    type="button"
                    onClick={() => setLogFilter(cat)}
                    className={`px-2 py-1 rounded text-[10px] font-bold transition-all border ${
                      logFilter === cat
                        ? "bg-blue-600 text-white border-blue-400"
                        : "bg-bunker-950 text-bunker-muted border-bunker-800 hover:text-white"
                    }`}
                  >
                    {cat}
                  </button>
                ))}
              </div>
            </div>

            {/* Strateji Filtresi */}
            <div className="flex flex-wrap items-center gap-1.5 text-xs pb-1">
              {[
                { id: "ALL", label: "Tüm Stratejiler" },
                { id: "RADAR", label: "Klasik Radar" },
                { id: "S3", label: "S3 SuperTrend" },
                { id: "LONDON", label: "London Box" },
                { id: "EMA_ADX", label: "EMA+ADX" },
                { id: "DONCHIAN", label: "Donchian" },
              ].map((st) => (
                <button
                  key={st.id}
                  type="button"
                  onClick={() => setStrategyFilter(st.id)}
                  className={`px-2 py-0.5 rounded text-[10px] font-mono font-bold transition-all border ${
                    strategyFilter === st.id
                      ? "bg-purple-600/30 text-purple-300 border-purple-400"
                      : "bg-bunker-950/60 text-bunker-muted border-bunker-800 hover:text-white"
                  }`}
                >
                  {st.label}
                </button>
              ))}
            </div>

            {/* Log Listesi */}
            <div className="max-h-96 overflow-y-auto space-y-2 pr-1 text-xs">
              {(() => {
                const filtered = decisionLogs.filter((l) => {
                  if (logFilter !== "ALL" && l.category !== logFilter) return false;
                  if (strategyFilter !== "ALL") {
                    const txt = `${l.strategy || ""} ${l.strategy_label || ""} ${l.message || ""}`.toUpperCase();
                    if (!txt.includes(strategyFilter)) return false;
                  }
                  return true;
                });

                if (filtered.length === 0) {
                  return (
                    <div className="text-center py-10 text-bunker-muted text-xs">
                      Seçili filtrelere uygun karar logu bulunmuyor.
                    </div>
                  );
                }

                return filtered.map((log) => {
                  const catColors: Record<string, string> = {
                    SCAN: "border-sky-500/30 bg-sky-500/10 text-sky-200",
                    ENTRY: "border-emerald-500/30 bg-emerald-500/10 text-emerald-300",
                    EXIT: "border-blue-500/30 bg-blue-500/10 text-blue-300",
                    PROTECT: "border-cyan-500/30 bg-cyan-500/10 text-cyan-300",
                    GATE: "border-amber-500/30 bg-amber-500/10 text-amber-300",
                    SYSTEM: "border-bunker-700 bg-bunker-800/40 text-bunker-muted",
                  };

                  return (
                    <div
                      key={log.id}
                      className={`p-2.5 rounded-lg border text-[11px] leading-relaxed flex items-start justify-between gap-2 transition-all ${
                        catColors[log.category] || "border-bunker-800 bg-bunker-900"
                      }`}
                    >
                      <div className="flex-1">
                        <div className="flex items-center gap-1.5 flex-wrap mb-1">
                          <span className="font-bold uppercase tracking-wider text-[10px]">
                            [{log.category}]
                          </span>
                          {log.symbol && (
                            <span className="px-1.5 py-0.2 rounded text-[9px] font-mono font-bold bg-bunker-800 text-slate-200 border border-bunker-700">
                              {log.symbol}
                            </span>
                          )}
                          {log.strategy_label && (
                            <span className="px-1.5 py-0.2 rounded text-[9px] font-bold bg-purple-900/40 text-purple-300 border border-purple-600/50">
                              {log.strategy_label}
                            </span>
                          )}
                        </div>
                        <div className="text-slate-200 font-medium">{log.message}</div>
                      </div>
                      <span className="text-[10px] opacity-70 whitespace-nowrap font-mono">{formatUtc3(log.time)}</span>
                    </div>
                  );
                });
              })()}
            </div>
          </div>
        </div>
      )}

      {/* ========================================================================= */}
      {/* SEKME 3: FOREX ÇİFTLERİ TEKNİK ANALİZ KARTLARI */}
      {/* ========================================================================= */}
      {activeTab === "forex_tech" && (
        <div className="space-y-4 animate-in fade-in duration-150">
          {/* Arama & Kategori Filtre Çubuğu */}
          <div className="p-3.5 rounded-xl bg-bunker-900/80 border border-bunker-800 flex flex-wrap items-center justify-between gap-3">
            <div className="flex flex-wrap items-center gap-1.5 text-xs">
              {[
                { id: "ALL", label: "Tümü" },
                { id: "major", label: "Majörler" },
                { id: "jpy", label: "JPY Krosları" },
                { id: "eur", label: "EUR Krosları" },
                { id: "gbp", label: "GBP Krosları" },
                { id: "commodity", label: "Emtia" },
                { id: "index", label: "Endeksler" },
              ].map((c) => (
                <button
                  key={c.id}
                  type="button"
                  onClick={() => setForexCategoryFilter(c.id)}
                  className={`px-3 py-1.5 rounded-lg text-xs font-bold transition-all border ${
                    forexCategoryFilter === c.id
                      ? "bg-blue-600/30 text-blue-300 border-blue-400"
                      : "bg-bunker-950 text-bunker-muted border-bunker-800 hover:text-white"
                  }`}
                >
                  {c.label}
                </button>
              ))}
            </div>

            <input
              type="text"
              placeholder="🔍 Parite ara (EUR, GBP, JPY...)"
              value={forexSearchQuery}
              onChange={(e) => setForexSearchQuery(e.target.value)}
              className="bg-bunker-950 border border-bunker-700 rounded-lg px-3 py-1.5 text-xs font-mono text-white placeholder-bunker-600 outline-none focus:border-blue-400 w-52"
            />
          </div>

          {/* Forex Pariteleri Izgarası */}
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
            {filteredForexCandidates.map((c) => {
              const isBuy = c.action === "BUY";
              const isSell = c.action === "SELL";
              const rsi = c.rsi_5m ?? c.rsi_15m;
              const tick = tickers[c.symbol];

              return (
                <div
                  key={c.symbol}
                  className="p-4 rounded-xl bg-bunker-900/80 border border-bunker-800 hover:border-bunker-700 transition-all shadow-sm space-y-3"
                >
                  {/* Başlık Satırı */}
                  <div className="flex items-start justify-between gap-2">
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="text-base font-black text-white">{c.display || c.symbol}</span>
                        <span className="text-[10px] px-1.5 py-0.5 rounded bg-bunker-800 text-bunker-muted uppercase">
                          {c.category}
                        </span>
                      </div>
                      <span className="text-[11px] text-bunker-muted block">{c.name}</span>
                    </div>

                    <div className="text-right">
                      <span className="text-sm font-black text-white font-mono block">
                        {c.price || tick?.bid || "—"}
                      </span>
                      <span className="text-[10px] text-cyan-400 font-mono font-bold block">
                        {c.spread_pips ?? tick?.spread_pips ?? "—"}p spread
                      </span>
                    </div>
                  </div>

                  {/* Sinyal ve Skor Çubuğu */}
                  <div className="p-2 rounded-lg bg-bunker-950/70 border border-bunker-800 flex items-center justify-between text-xs">
                    <div className="flex items-center gap-2">
                      <span
                        className={`px-2 py-0.5 rounded text-[10px] font-black ${
                          isBuy
                            ? "bg-emerald-500/20 text-emerald-300 border border-emerald-400/40"
                            : isSell
                            ? "bg-rose-500/20 text-rose-300 border border-rose-400/40"
                            : "bg-bunker-800 text-bunker-muted"
                        }`}
                      >
                        {isBuy ? "▲ AL SİNYALİ" : isSell ? "▼ SAT SİNYALİ" : "BEKLE"}
                      </span>
                      <span className="text-bunker-muted font-mono text-[11px] font-bold">
                        Skor: {c.score}/100
                      </span>
                    </div>

                    <button
                      type="button"
                      onClick={() => setChartModalCandidate(c)}
                      className="px-2.5 py-1 rounded bg-blue-600/30 text-blue-300 border border-blue-400/40 text-[11px] font-bold hover:bg-blue-600/50 transition-all flex items-center gap-1"
                    >
                      <span>📈</span>
                      <span>Grafik</span>
                    </button>
                  </div>

                  {/* İndikatör Grid */}
                  <div className="grid grid-cols-4 gap-1.5 text-center text-[10px] font-mono">
                    <div className="p-1.5 rounded bg-bunker-950 border border-bunker-800/80">
                      <span className="text-bunker-muted block">RSI 5M</span>
                      <span className={`font-bold ${rsi && (rsi >= 70 || rsi <= 30) ? "text-amber-300" : "text-white"}`}>
                        {rsi ? rsi.toFixed(0) : "—"}
                      </span>
                    </div>
                    <div className="p-1.5 rounded bg-bunker-950 border border-bunker-800/80">
                      <span className="text-bunker-muted block">S.Trend</span>
                      <span className={`font-bold ${c.supertrend_dir > 0 ? "text-emerald-400" : "text-rose-400"}`}>
                        {c.supertrend_dir > 0 ? "Boğa" : "Ayı"}
                      </span>
                    </div>
                    <div className="p-1.5 rounded bg-bunker-950 border border-bunker-800/80">
                      <span className="text-bunker-muted block">ADX</span>
                      <span className={`font-bold ${c.adx >= 25 ? "text-emerald-400" : "text-bunker-muted"}`}>
                        {c.adx ? c.adx.toFixed(0) : "—"}
                      </span>
                    </div>
                    <div className="p-1.5 rounded bg-bunker-950 border border-bunker-800/80">
                      <span className="text-bunker-muted block">ATR</span>
                      <span className="text-white font-bold">{c.atr_pips ? `${c.atr_pips}p` : "—"}</span>
                    </div>
                  </div>

                  {/* Hedef ve Stop Seviyeleri */}
                  <div className="flex items-center justify-between text-[11px] font-mono pt-1 border-t border-bunker-800/60">
                    <span className="text-emerald-400 font-bold">Hedef TP: {c.pip_target ? `+${c.pip_target}p` : "—"}</span>
                    <span className="text-rose-400 font-bold">Stop: {c.stop_loss_pips ? `-${c.stop_loss_pips}p` : "—"}</span>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* ========================================================================= */}
      {/* SEKME 4: 7/24 HAFTA SONU KRİPTO ÇİFTLERİ TEKNİK ANALİZİ */}
      {/* ========================================================================= */}
      {activeTab === "crypto_tech" && (
        <div className="space-y-4 animate-in fade-in duration-150">
          {/* Kripto Portföy Bannerı */}
          <div className="p-4 rounded-2xl bg-gradient-to-r from-purple-950/40 via-indigo-950/30 to-slate-900 border border-purple-500/30 shadow-xl flex flex-wrap items-center justify-between gap-4">
            <div className="flex items-center gap-3">
              <div className="w-12 h-12 rounded-xl bg-purple-500/20 border border-purple-400/50 flex items-center justify-center text-2xl shadow-[0_0_16px_rgba(168,85,247,0.3)]">
                ⚡
              </div>
              <div>
                <div className="flex items-center gap-2">
                  <h2 className="text-lg font-black text-white">IC MARKETS 7/24 KRİPTO PORTFÖYÜ</h2>
                  <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-purple-500/20 text-purple-300 border border-purple-400/40">
                    HAFTA SONU KESİNTİSİZ
                  </span>
                </div>
                <p className="text-xs text-bunker-muted font-mono mt-0.5">
                  Fırsat kaçırmayan FVG Pullback ve S3 SuperTrend motorları — Güvenli %2 risk bütçesi ile 7/24 canlı işlem
                </p>
              </div>
            </div>

            <input
              type="text"
              placeholder="🔍 Kripto ara (SOL, ETH, BTC...)"
              value={cryptoSearchQuery}
              onChange={(e) => setCryptoSearchQuery(e.target.value)}
              className="bg-bunker-950 border border-bunker-700 rounded-lg px-3 py-1.5 text-xs font-mono text-white placeholder-bunker-600 outline-none focus:border-purple-400 w-52"
            />
          </div>

          {/* Kripto Pariteleri Kart Izgarası */}
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
            {cryptoCandidatesList.map((item) => {
              const c = item.candidate;
              const tick = item.ticker;
              const priceVal = c?.price ?? tick?.bid ?? 0.0;
              const spreadVal = c?.spread_pips ?? tick?.spread_pips ?? 0.0;
              const isBuy = c?.action === "BUY";
              const isSell = c?.action === "SELL";

              return (
                <div
                  key={item.sym}
                  className="p-4 rounded-xl bg-bunker-900/80 border border-bunker-800 hover:border-purple-500/40 transition-all shadow-sm space-y-3"
                >
                  {/* Başlık ve Fiyat */}
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex items-center gap-2.5">
                      <span className="text-2xl">{item.icon}</span>
                      <div>
                        <div className="flex items-center gap-1.5">
                          <span className="font-black text-white text-base">{item.sym}</span>
                          <span className="text-[10px] px-1.5 py-0.5 rounded bg-purple-900/30 text-purple-300 font-bold border border-purple-600/40">
                            7/24
                          </span>
                        </div>
                        <span className="text-[11px] text-bunker-muted">{item.name}</span>
                      </div>
                    </div>

                    <div className="text-right font-mono">
                      <span className="text-base font-black text-white block">
                        ${priceVal > 0 ? priceVal.toFixed(item.digits) : "—"}
                      </span>
                      <span className="text-[10px] text-purple-300 font-bold block">
                        {spreadVal}p spread
                      </span>
                    </div>
                  </div>

                  {/* Strateji Durumları: FVG & S3 */}
                  <div className="p-2.5 rounded-lg bg-bunker-950/70 border border-bunker-800 space-y-1.5 text-xs font-mono">
                    <div className="flex items-center justify-between">
                      <span className="text-bunker-muted flex items-center gap-1">
                        <span>⚡</span>
                        <span>FVG Pullback:</span>
                      </span>
                      <span className="text-emerald-400 font-bold">1.8R TP Takipte</span>
                    </div>
                    <div className="flex items-center justify-between">
                      <span className="text-bunker-muted flex items-center gap-1">
                        <span>🚀</span>
                        <span>S3 SuperTrend:</span>
                      </span>
                      <span className={`font-bold ${c?.supertrend_dir && c.supertrend_dir > 0 ? "text-emerald-400" : "text-rose-400"}`}>
                        {c?.supertrend_dir && c.supertrend_dir > 0 ? "▲ Boğa Yönü" : "▼ Ayı Yönü"}
                      </span>
                    </div>
                    <div className="flex items-center justify-between pt-1 border-t border-bunker-800/60">
                      <span className="text-bunker-muted">Akıllı Kalite Kalkanı:</span>
                      <span className="text-cyan-300 font-bold">Aktif (%0.30 EMA)</span>
                    </div>
                  </div>

                  {/* Sinyal & Skor & Grafik Butonu */}
                  <div className="flex items-center justify-between text-xs pt-1">
                    <div className="flex items-center gap-2">
                      <span
                        className={`px-2 py-0.5 rounded text-[10px] font-black font-mono ${
                          isBuy
                            ? "bg-emerald-500/20 text-emerald-300 border border-emerald-400/40"
                            : isSell
                            ? "bg-rose-500/20 text-rose-300 border border-rose-400/40"
                            : "bg-bunker-800 text-bunker-muted"
                        }`}
                      >
                        {isBuy ? "▲ AL SİNYALİ" : isSell ? "▼ SAT SİNYALİ" : "BEKLE"}
                      </span>
                      <span className="text-bunker-muted font-mono text-[11px] font-bold">
                        Skor: {c?.score || 75}/100
                      </span>
                    </div>

                    {c && (
                      <button
                        type="button"
                        onClick={() => setChartModalCandidate(c)}
                        className="px-2.5 py-1 rounded bg-purple-600/30 text-purple-300 border border-purple-400/40 text-[11px] font-bold hover:bg-purple-600/50 transition-all flex items-center gap-1"
                      >
                        <span>📈</span>
                        <span>Grafik</span>
                      </button>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* ALT BAĞLANTILAR */}
      <div className="flex flex-wrap items-center justify-between gap-3 text-xs text-bunker-muted pt-4 border-t border-bunker-800">
        <div className="flex items-center gap-4">
          <Link href="/forex" className="hover:text-blue-400 transition-colors">
            ← Forex Radar &amp; Canlı Piyasa
          </Link>
          <span className="text-bunker-700">|</span>
          <Link href="/forex/reports" className="hover:text-blue-300 font-bold text-blue-400 transition-colors flex items-center gap-1">
            📊 Tüm İşlem Raporları &amp; Analitik →
          </Link>
        </div>
        <Link href="/forex/charts" className="hover:text-blue-400 transition-colors">
          Grafik Ekranı (1 / 2 / 4) →
        </Link>
      </div>

      {/* GRAFİK MODALI */}
      {chartModalCandidate && (
        <ForexChartModal
          candidate={chartModalCandidate}
          onClose={() => setChartModalCandidate(null)}
        />
      )}
    </div>
  );
}
