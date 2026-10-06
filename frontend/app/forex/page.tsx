"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { apiFetch } from "../lib/api";

interface SessionInfo {
  name: string;
  flag: string;
  city: string;
  active: boolean;
  hours_utc: string;
}

interface ForexCandidate {
  symbol: string;
  display: string;
  name: string;
  category: string;
  price: number;
  bid: number;
  ask: number;
  spread_pips: number;
  score: number;
  trend: string;
  action: "BUY" | "SELL";
  rsi_15m: number;
  macd_verdict: string;
  pip_target: number;
  stop_loss_pips: number;
  risk_reward: string;
  tv_symbol: string;
}

export default function ForexRadarPage() {
  const [candidates, setCandidates] = useState<ForexCandidate[]>([]);
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  // Quick Lot Calculator state
  const [calcBalance, setCalcBalance] = useState<number>(10000);
  const [calcRiskPct, setCalcRiskPct] = useState<number>(1.0);
  const [calcSlPips, setCalcSlPips] = useState<number>(20);
  const [calcSymbol, setCalcSymbol] = useState<string>("EURUSD");
  const [calcResult, setCalcResult] = useState<any>(null);

  const fetchRadar = async () => {
    try {
      const data = await apiFetch("/api/forex/radar");
      if (data && data.candidates) {
        setCandidates(data.candidates);
        setSessions(data.sessions || []);
        setLastUpdated(new Date());
      }
    } catch (err) {
      console.error("Forex radar yükleme hatası:", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchRadar();
    const timer = setInterval(fetchRadar, 3000);
    return () => clearInterval(timer);
  }, []);

  const calculateLot = async () => {
    try {
      const res = await apiFetch("/api/forex/calculate-lot", {
        method: "POST",
        body: JSON.stringify({
          account_balance: calcBalance,
          risk_percentage: calcRiskPct,
          stop_loss_pips: calcSlPips,
          symbol: calcSymbol,
        }),
      });
      setCalcResult(res);
    } catch (err) {
      console.error("Lot hesaplama hatası:", err);
    }
  };

  useEffect(() => {
    calculateLot();
  }, [calcBalance, calcRiskPct, calcSlPips, calcSymbol]);

  return (
    <div className="space-y-6 pb-12">
      {/* ÜST BAŞLIK & SEANS BİLGİSİ */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 p-4 rounded-2xl bg-gradient-to-r from-blue-950/40 via-slate-900/60 to-indigo-950/40 border border-blue-500/20 backdrop-blur-md shadow-lg">
        <div className="flex items-center gap-3">
          <div className="w-12 h-12 rounded-xl bg-blue-500/20 border border-blue-400/40 flex items-center justify-center text-2xl shadow-[0_0_16px_rgba(59,130,246,0.3)]">
            💱
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-xl font-bold font-mono text-white tracking-tight">
                FOREX RADAR & CANLI PİYASA
              </h1>
              <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-blue-500/20 text-blue-300 border border-blue-400/30">
                24/5 LIVE
              </span>
            </div>
            <p className="text-xs text-bunker-muted font-mono mt-0.5">
              Majör Döviz Çiftleri, Değerli Madenler (XAU/USD) ve Küresel Seanslar
            </p>
          </div>
        </div>

        {/* Canlı Piyasa Seansları */}
        <div className="flex items-center gap-2 overflow-x-auto pb-1 md:pb-0">
          {sessions.map((s) => (
            <div
              key={s.name}
              className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border font-mono text-xs transition-all ${
                s.active
                  ? "bg-emerald-500/15 border-emerald-500/40 text-emerald-300 shadow-[0_0_10px_rgba(16,185,129,0.2)]"
                  : "bg-bunker-900/80 border-bunker-800 text-bunker-muted opacity-60"
              }`}
            >
              <span>{s.flag}</span>
              <span className="font-bold">{s.name}</span>
              <span
                className={`w-1.5 h-1.5 rounded-full ${
                  s.active ? "bg-emerald-400 animate-pulse" : "bg-bunker-600"
                }`}
              />
            </div>
          ))}
        </div>
      </div>

      {/* HIZLI ERİŞİM KARTLARI */}
      <div className="grid grid-cols-2 sm:grid-cols-6 gap-3">
        <Link
          href="/forex/btc-gold"
          className="p-3.5 rounded-xl bg-bunker-900/80 border border-amber-500/40 hover:border-amber-400 transition-all group"
        >
          <div className="text-xl mb-1 group-hover:scale-110 transition-transform">🥇</div>
          <div className="font-mono text-sm font-bold text-white group-hover:text-amber-300">
            BTC + Altın
          </div>
          <div className="text-[11px] text-bunker-muted font-mono">XAUUSD · BTCUSD Konsolu</div>
        </Link>
        <Link
          href="/forex/portfolio"
          className="p-3.5 rounded-xl bg-bunker-900/80 border border-blue-500/30 hover:border-blue-400 transition-all group"
        >
          <div className="text-xl mb-1 group-hover:scale-110 transition-transform">💼</div>
          <div className="font-mono text-sm font-bold text-white group-hover:text-blue-300">
            Otonom Portföy
          </div>
          <div className="text-[11px] text-bunker-muted font-mono">Canlı Scalper Takip</div>
        </Link>
        <Link
          href="/forex/reports"
          className="p-3.5 rounded-xl bg-bunker-900/80 border border-indigo-500/30 hover:border-indigo-400 transition-all group"
        >
          <div className="text-xl mb-1 group-hover:scale-110 transition-transform">📊</div>
          <div className="font-mono text-sm font-bold text-white group-hover:text-indigo-300">
            İşlem Raporları
          </div>
          <div className="text-[11px] text-bunker-muted font-mono">Tüm Giriş/Çıkış & CSV</div>
        </Link>
        <Link
          href="/forex/technical-charts"
          className="p-3.5 rounded-xl bg-bunker-900/80 border border-bunker-800 hover:border-blue-500/40 transition-all group"
        >
          <div className="text-xl mb-1 group-hover:scale-110 transition-transform">🖥️</div>
          <div className="font-mono text-sm font-bold text-white group-hover:text-blue-300">
            4'lü Grafik
          </div>
          <div className="text-[11px] text-bunker-muted font-mono">Çoklu TradingView</div>
        </Link>
        <Link
          href="/forex/charts"
          className="p-3.5 rounded-xl bg-bunker-900/80 border border-bunker-800 hover:border-blue-500/40 transition-all group"
        >
          <div className="text-xl mb-1 group-hover:scale-110 transition-transform">📈</div>
          <div className="font-mono text-sm font-bold text-white group-hover:text-blue-300">
            Tekli Grafik
          </div>
          <div className="text-[11px] text-bunker-muted font-mono">Detaylı İnceleme</div>
        </Link>
        <Link
          href="/forex/calendar"
          className="p-3.5 rounded-xl bg-bunker-900/80 border border-bunker-800 hover:border-blue-500/40 transition-all group"
        >
          <div className="text-xl mb-1 group-hover:scale-110 transition-transform">📅</div>
          <div className="font-mono text-sm font-bold text-white group-hover:text-blue-300">
            Takvim
          </div>
          <div className="text-[11px] text-bunker-muted font-mono">Ekonomik Veriler</div>
        </Link>
      </div>

      {/* RADAR FIRSATLARI TABLOSU */}
      <div className="rounded-2xl border border-bunker-800 bg-bunker-900/70 backdrop-blur-md overflow-hidden shadow-xl">
        <div className="p-4 border-b border-bunker-800 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="text-lg">📡</span>
            <h2 className="font-mono text-sm font-bold text-white uppercase tracking-wider">
              En Yüksek Potansiyelli Forex & Emtia Sinyalleri
            </h2>
          </div>
          {lastUpdated && (
            <span className="font-mono text-[11px] text-bunker-muted">
              Son Güncelleme: {lastUpdated.toLocaleTimeString("tr-TR")}
            </span>
          )}
        </div>

        {loading ? (
          <div className="p-12 text-center font-mono text-sm text-bunker-muted">
            <div className="inline-block w-6 h-6 border-2 border-blue-400 border-t-transparent rounded-full animate-spin mb-2" />
            <p>Forex pariteleri taranıyor…</p>
          </div>
        ) : (
          <>
            {/* Masaüstü Tablo Görünümü */}
            <div className="hidden md:block overflow-x-auto">
              <table className="w-full text-left font-mono text-xs">
                <thead className="bg-bunker-950/80 text-bunker-muted uppercase border-b border-bunker-800 text-[10px] tracking-wider">
                  <tr>
                    <th className="py-3 px-4">Parite / Varlık</th>
                    <th className="py-3 px-3">Yön</th>
                    <th className="py-3 px-3">Alış (Bid)</th>
                    <th className="py-3 px-3">Satış (Ask)</th>
                    <th className="py-3 px-3">Spread</th>
                    <th className="py-3 px-3">Hedef (TP)</th>
                    <th className="py-3 px-3">Zarar Durdur (SL)</th>
                    <th className="py-3 px-3">R/R</th>
                    <th className="py-3 px-3">Skor</th>
                    <th className="py-3 px-4 text-right">Grafik</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-bunker-800/60">
                  {candidates.map((c) => {
                    const isBuy = c.action === "BUY";
                    return (
                      <tr
                        key={c.symbol}
                        className="hover:bg-bunker-800/40 transition-colors group"
                      >
                        <td className="py-3.5 px-4">
                          <div className="flex items-center gap-2">
                            <span className="font-bold text-white text-sm group-hover:text-blue-400 transition-colors">
                              {c.display}
                            </span>
                            <span className="text-[10px] px-1.5 py-0.2 rounded bg-bunker-800 text-bunker-muted uppercase">
                              {c.category}
                            </span>
                          </div>
                          <div className="text-[10px] text-bunker-muted truncate max-w-[140px]">
                            {c.name}
                          </div>
                        </td>

                        <td className="py-3.5 px-3">
                          <span
                            className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-md text-[11px] font-bold ${
                              isBuy
                                ? "bg-emerald-500/15 text-emerald-400 border border-emerald-500/30"
                                : "bg-rose-500/15 text-rose-400 border border-rose-500/30"
                            }`}
                          >
                            {isBuy ? "▲ AL (BUY)" : "▼ SAT (SELL)"}
                          </span>
                        </td>

                        <td className="py-3.5 px-3 font-semibold text-white">
                          {c.bid}
                        </td>

                        <td className="py-3.5 px-3 font-semibold text-white">
                          {c.ask}
                        </td>

                        <td className="py-3.5 px-3 text-cyan-400 font-bold">
                          {c.spread_pips} pips
                        </td>

                        <td className="py-3.5 px-3 text-emerald-400 font-bold">
                          +{c.pip_target} p
                        </td>

                        <td className="py-3.5 px-3 text-rose-400 font-bold">
                          -{c.stop_loss_pips} p
                        </td>

                        <td className="py-3.5 px-3 text-bunker-muted font-bold">
                          {c.risk_reward}
                        </td>

                        <td className="py-3.5 px-3">
                          <div className="flex items-center gap-1.5">
                            <div className="w-12 bg-bunker-800 rounded-full h-1.5 overflow-hidden">
                              <div
                                className="bg-blue-400 h-full rounded-full"
                                style={{ width: `${Math.min(100, c.score)}%` }}
                              />
                            </div>
                            <span className="font-bold text-blue-300">
                              {c.score.toFixed(1)}p
                            </span>
                          </div>
                        </td>

                        <td className="py-3.5 px-4 text-right">
                          <Link
                            href={`/forex/charts?symbol=${c.symbol}`}
                            className="px-2.5 py-1.5 rounded-lg bg-blue-500/10 text-blue-400 border border-blue-400/20 hover:bg-blue-500/20 transition-all font-bold text-[11px]"
                          >
                            Grafik ↗
                          </Link>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            {/* Mobil Kart Görünümü */}
            <div className="md:hidden space-y-3 p-3 font-mono">
              {candidates.map((c) => {
                const isBuy = c.action === "BUY";
                return (
                  <div
                    key={c.symbol}
                    className="p-3.5 rounded-2xl border border-bunker-800 bg-bunker-900/90 shadow-md space-y-2.5"
                  >
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <span className="font-bold text-white text-base">{c.display}</span>
                        <span className="text-[10px] px-1.5 py-0.2 rounded bg-bunker-800 text-bunker-muted uppercase">
                          {c.category}
                        </span>
                      </div>
                      <span
                        className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-md text-[11px] font-bold ${
                          isBuy
                            ? "bg-emerald-500/15 text-emerald-400 border border-emerald-500/30"
                            : "bg-rose-500/15 text-rose-400 border border-rose-500/30"
                        }`}
                      >
                        {isBuy ? "▲ AL (BUY)" : "▼ SAT (SELL)"}
                      </span>
                    </div>

                    <div className="grid grid-cols-2 gap-2 text-xs p-2 rounded-xl bg-bunker-950/70 border border-bunker-800/80">
                      <div>
                        <span className="text-[10px] text-bunker-muted block">Alış (Bid)</span>
                        <span className="text-white font-bold">{c.bid}</span>
                      </div>
                      <div className="text-right">
                        <span className="text-[10px] text-bunker-muted block">Satış (Ask)</span>
                        <span className="text-white font-bold">{c.ask}</span>
                      </div>
                      <div>
                        <span className="text-[10px] text-bunker-muted block">Hedef (TP)</span>
                        <span className="text-emerald-400 font-bold">+{c.pip_target} p</span>
                      </div>
                      <div className="text-right">
                        <span className="text-[10px] text-bunker-muted block">Stop (SL)</span>
                        <span className="text-rose-400 font-bold">-{c.stop_loss_pips} p</span>
                      </div>
                    </div>

                    <div className="flex items-center justify-between text-[11px] pt-1 border-t border-bunker-800/60">
                      <div className="flex items-center gap-2">
                        <span className="text-cyan-400 font-bold">{c.spread_pips} pips</span>
                        <span className="text-bunker-700">|</span>
                        <span className="text-yellow-400 font-bold">Skor {c.score.toFixed(0)}</span>
                      </div>
                      <Link
                        href={`/forex/charts?symbol=${c.tv_symbol || c.symbol}`}
                        className="px-3 py-1.5 rounded-lg bg-blue-600/30 border border-blue-400/40 text-blue-300 font-bold text-xs hover:bg-blue-600/40 transition-colors touch-target"
                      >
                        Grafik ↗
                      </Link>
                    </div>
                  </div>
                );
              })}
            </div>
          </>
        )}
      </div>

      {/* FOREX RİSK & LOT HESAPLAYICI (WIDGET) */}
      <div className="p-5 rounded-2xl border border-bunker-800 bg-gradient-to-br from-bunker-900/90 to-bunker-950/90 shadow-xl space-y-4">
        <div className="flex items-center justify-between border-b border-bunker-800 pb-3">
          <div className="flex items-center gap-2">
            <span className="text-lg">🧮</span>
            <h3 className="font-mono text-sm font-bold text-white uppercase tracking-wider">
              Forex Lot ve Risk Boyutlandırma Hesaplayıcısı
            </h3>
          </div>
          <span className="text-xs font-mono text-cyan-400">Otomatik Sermaye Koruma</span>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          <div>
            <label className="block text-[11px] font-mono text-bunker-muted mb-1">
              Hesap Bakiyesi ($ USD):
            </label>
            <input
              type="number"
              value={calcBalance}
              onChange={(e) => setCalcBalance(Number(e.target.value) || 0)}
              className="w-full bg-bunker-950 border border-bunker-700 rounded-lg px-3 py-2 text-sm font-mono text-white focus:border-blue-400 outline-none"
            />
          </div>

          <div>
            <label className="block text-[11px] font-mono text-bunker-muted mb-1">
              İşlem Başına Risk (%):
            </label>
            <input
              type="number"
              step="0.1"
              value={calcRiskPct}
              onChange={(e) => setCalcRiskPct(Number(e.target.value) || 0)}
              className="w-full bg-bunker-950 border border-bunker-700 rounded-lg px-3 py-2 text-sm font-mono text-white focus:border-blue-400 outline-none"
            />
          </div>

          <div>
            <label className="block text-[11px] font-mono text-bunker-muted mb-1">
              Stop Loss Mesafesi (Pips):
            </label>
            <input
              type="number"
              value={calcSlPips}
              onChange={(e) => setCalcSlPips(Number(e.target.value) || 0)}
              className="w-full bg-bunker-950 border border-bunker-700 rounded-lg px-3 py-2 text-sm font-mono text-white focus:border-blue-400 outline-none"
            />
          </div>

          <div>
            <label className="block text-[11px] font-mono text-bunker-muted mb-1">
              Parite:
            </label>
            <select
              value={calcSymbol}
              onChange={(e) => setCalcSymbol(e.target.value)}
              className="w-full bg-bunker-950 border border-bunker-700 rounded-lg px-3 py-2 text-sm font-mono text-white focus:border-blue-400 outline-none"
            >
              <option value="EURUSD">EUR/USD</option>
              <option value="GBPUSD">GBP/USD</option>
              <option value="USDJPY">USD/JPY</option>
              <option value="XAUUSD">XAU/USD (Altın)</option>
              <option value="USDCAD">USD/CAD</option>
              <option value="AUDUSD">AUD/USD</option>
            </select>
          </div>
        </div>

        {calcResult && (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 p-3 rounded-xl bg-bunker-950/70 border border-bunker-800/80 font-mono text-xs">
            <div>
              <span className="text-bunker-muted text-[10px] block">RİSKE EDİLEN TUTAR:</span>
              <span className="text-base font-bold text-rose-400">
                ${calcResult.risk_amount_usd?.toFixed(2)}
              </span>
            </div>
            <div>
              <span className="text-bunker-muted text-[10px] block">STANDART LOT (100k):</span>
              <span className="text-base font-bold text-cyan-300">
                {calcResult.standard_lots} Lot
              </span>
            </div>
            <div>
              <span className="text-bunker-muted text-[10px] block">MİNİ LOT (10k):</span>
              <span className="text-base font-bold text-white">
                {calcResult.mini_lots} Mini
              </span>
            </div>
            <div>
              <span className="text-bunker-muted text-[10px] block">MİKRO LOT (1k):</span>
              <span className="text-base font-bold text-white">
                {calcResult.micro_lots} Mikro
              </span>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
