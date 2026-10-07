"use client";

import React, { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { apiFetch } from "../lib/api";
import { formatPrice } from "../lib/format";
import ForexChartModal from "./components/ForexChartModal";

interface SessionInfo {
  name: string;
  flag: string;
  city: string;
  active: boolean;
  hours_utc: string;
}

/** Sinyal kalite kademesi — backend `tier` alanı. */
type Tier = "STRONG" | "ACTIVE" | "WATCH" | "WAIT";

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
  action: "BUY" | "SELL" | "HOLD";
  rsi_15m: number;
  macd_verdict: string;
  cmo: number;
  cci: number;
  adx: number;
  supertrend_dir: number;
  htf_trend: string;
  pip_target: number;
  stop_loss_pips: number;
  risk_reward: string;
  atr_pips: number;
  tv_symbol: string;
  // Kapı değerlendirmesi (otonom motorun gerçek giriş kararı)
  tier: Tier;
  signal_ready: boolean;
  gate_passed: boolean;
  blocked_by: string[];
  primary_blocker: string | null;
  blocker_text: string;
  required_score: number;
}

interface RadarThresholds {
  min_score: number;
  btc_min_score: number;
  commodity_min_score: number;
  max_spread_pips: number;
  adx_filter_enabled: boolean;
  adx_min: number;
  supertrend_filter_enabled: boolean;
  major_session_filter: boolean;
  major_session_utc: string;
  major_min_atr_pips: number;
}

/**
 * Kademe sözlüğü — renk, etiket ve kısa açıklama TEK yerde.
 * `STRONG` motorun şu an gerçekten işlem açacağı aday; diğerleri izleme.
 */
const TIER_META: Record<Tier, { label: string; badge: string; dot: string; hint: string }> = {
  STRONG: {
    label: "⚡ GÜÇLÜ SİNYAL",
    badge: "bg-emerald-500/20 text-emerald-300 border-emerald-400/50",
    dot: "bg-emerald-400",
    hint: "Tüm giriş kapıları açık — otonom motor bu sinyalle işlem açabilir.",
  },
  ACTIVE: {
    label: "💼 POZİSYON AÇIK",
    badge: "bg-blue-500/20 text-blue-300 border-blue-400/50",
    dot: "bg-blue-400",
    hint: "Sinyal onaylı fakat bu sembolde zaten açık pozisyon var.",
  },
  WATCH: {
    label: "👁️ İZLE",
    badge: "bg-amber-500/20 text-amber-300 border-amber-400/50",
    dot: "bg-amber-400",
    hint: "Kalite kapıları temiz; yalnızca zamanlama (seans/volatilite) uygun değil.",
  },
  WAIT: {
    label: "⏸️ BEKLE",
    badge: "bg-bunker-800 text-bunker-muted border-bunker-700",
    dot: "bg-bunker-600",
    hint: "Sinyal giriş kalitesinde değil — engel gerekçesi satırda yazılı.",
  },
};

const TIER_ORDER: Tier[] = ["STRONG", "ACTIVE", "WATCH", "WAIT"];

/** Sembolün SuperTrend yönü (0 = bilinmiyor). */
function supertrendText(dir: number): { text: string; tone: string } {
  if (dir > 0) return { text: "▲ BOĞA", tone: "text-emerald-400" };
  if (dir < 0) return { text: "▼ AYI", tone: "text-rose-400" };
  return { text: "— nötr", tone: "text-bunker-muted" };
}

/** ADX trend gücü: <20 yönsüz, <25 zayıf, >=25 güçlü. */
function adxTone(adx: number): string {
  if (adx >= 25) return "text-emerald-400";
  if (adx >= 20) return "text-yellow-400";
  return "text-bunker-muted";
}

/** Skor rengi: giriş eşiğine göre — eşiği geçen yeşil, yaklaşan sarı. */
function scoreTone(score: number, required: number): string {
  if (score >= required) return "text-emerald-400";
  if (score >= required - 10) return "text-yellow-400";
  return "text-bunker-muted";
}

export default function ForexRadarPage() {
  const [candidates, setCandidates] = useState<ForexCandidate[]>([]);
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [scanNote, setScanNote] = useState<string>("");
  const [thresholds, setThresholds] = useState<RadarThresholds | null>(null);
  const [loading, setLoading] = useState(true);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  // Filtreler
  const [tierFilter, setTierFilter] = useState<"ALL" | Tier>("ALL");
  const [directionFilter, setDirectionFilter] = useState<"ALL" | "BUY" | "SELL">("ALL");
  const [searchQuery, setSearchQuery] = useState<string>("");

  // Quick Lot Calculator state
  const [calcBalance, setCalcBalance] = useState<number>(10000);
  const [calcRiskPct, setCalcRiskPct] = useState<number>(10.0);
  const [calcSlPips, setCalcSlPips] = useState<number>(20);
  const [calcSymbol, setCalcSymbol] = useState<string>("EURUSD");
  const [calcResult, setCalcResult] = useState<any>(null);

  // Profesyonel Grafik Modalı (Spot tarzı Lightweight Charts)
  const [chartModalCandidate, setChartModalCandidate] = useState<ForexCandidate | null>(null);

  const fetchRadar = async () => {
    try {
      const data = await apiFetch("/api/forex/radar");
      if (data && data.candidates) {
        setCandidates(data.candidates);
        setSessions(data.sessions || []);
        setScanNote(data.scan_note || "");
        setThresholds(data.thresholds || null);
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

  // Güçlü sinyaller — filtrelerden bağımsız, radarın özü.
  const strongSignals = useMemo(() => candidates.filter((c) => c.tier === "STRONG"), [candidates]);

  const tierCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const c of candidates) counts[c.tier] = (counts[c.tier] || 0) + 1;
    return counts;
  }, [candidates]);

  // Tablo: kademe + yön + arama filtreleri uygulanır.
  const visible = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();
    return candidates.filter((c) => {
      if (tierFilter !== "ALL" && c.tier !== tierFilter) return false;
      if (directionFilter !== "ALL" && c.action !== directionFilter) return false;
      if (q && !(`${c.display} ${c.symbol} ${c.name}`.toLowerCase().includes(q))) return false;
      return true;
    });
  }, [candidates, tierFilter, directionFilter, searchQuery]);

  const filtersActive = tierFilter !== "ALL" || directionFilter !== "ALL" || searchQuery.trim() !== "";

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
                FOREX RADAR &amp; CANLI PİYASA
              </h1>
              <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-blue-500/20 text-blue-300 border border-blue-400/30">
                24/5 LIVE
              </span>
            </div>
            <p className="text-xs text-bunker-muted font-mono mt-0.5">
              Majör Döviz Çiftleri, Değerli Madenler ve Endeksler — algoritma taraması
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
            BTC + Altın Odak İzleme
          </div>
          <div className="text-[11px] text-bunker-muted font-mono">Yalnız XAUUSD · BTCUSD</div>
        </Link>
        <Link
          href="/forex/portfolio"
          className="p-3.5 rounded-xl bg-bunker-900/80 border border-blue-500/30 hover:border-blue-400 transition-all group"
        >
          <div className="text-xl mb-1 group-hover:scale-110 transition-transform">💼</div>
          <div className="font-mono text-sm font-bold text-white group-hover:text-blue-300">
            Merkezi Otonom İzleme
          </div>
          <div className="text-[11px] text-bunker-muted font-mono">Tüm Semboller · Tek Ayar</div>
        </Link>
        <Link
          href="/forex/reports"
          className="p-3.5 rounded-xl bg-bunker-900/80 border border-indigo-500/30 hover:border-indigo-400 transition-all group"
        >
          <div className="text-xl mb-1 group-hover:scale-110 transition-transform">📊</div>
          <div className="font-mono text-sm font-bold text-white group-hover:text-indigo-300">
            İşlem Raporları
          </div>
          <div className="text-[11px] text-bunker-muted font-mono">Tüm Giriş/Çıkış &amp; CSV</div>
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

      {/* RADAR TARAMA DURUMU */}
      <div
        className={`p-4 rounded-2xl border shadow-lg space-y-3 ${
          strongSignals.length > 0
            ? "bg-emerald-950/20 border-emerald-500/30"
            : "bg-bunker-900/70 border-bunker-800"
        }`}
      >
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            {/* Radar tarama animasyonu */}
            <div className="relative w-9 h-9 flex items-center justify-center shrink-0">
              <span
                className={`absolute inset-0 rounded-full border animate-ping ${
                  strongSignals.length > 0 ? "border-emerald-400/50" : "border-blue-400/30"
                }`}
              />
              <span
                className={`absolute inset-0 rounded-full border ${
                  strongSignals.length > 0 ? "border-emerald-400/40" : "border-blue-400/20"
                }`}
              />
              <span className="text-base relative">📡</span>
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span className="font-mono text-sm font-bold text-white">
                  {strongSignals.length > 0
                    ? `${strongSignals.length} GÜÇLÜ SİNYAL`
                    : "GÜÇLÜ SİNYAL BEKLENİYOR"}
                </span>
                <span className="flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-mono font-bold bg-emerald-500/15 text-emerald-300 border border-emerald-500/30">
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                  TARAMA AKTİF
                </span>
              </div>
              <p className="text-[11px] text-bunker-muted font-mono mt-0.5">{scanNote}</p>
            </div>
          </div>

          <div className="flex items-center gap-2 text-[11px] font-mono">
            {TIER_ORDER.map((t) => (
              <span
                key={t}
                className={`px-2 py-1 rounded-lg border ${TIER_META[t].badge}`}
                title={TIER_META[t].hint}
              >
                {tierCounts[t] || 0} {TIER_META[t].label.replace(/^\S+\s/, "")}
              </span>
            ))}
            {lastUpdated && (
              <span className="text-bunker-muted">
                · {lastUpdated.toLocaleTimeString("tr-TR")}
              </span>
            )}
          </div>
        </div>

        {/* Eşik şeffaflığı: "güçlü" derken hangi ölçüt kullanılıyor? */}
        {thresholds && (
          <div className="flex flex-wrap gap-x-4 gap-y-1 pt-2 border-t border-bunker-800/60 text-[10px] font-mono text-bunker-muted">
            <span>Min Skor: <strong className="text-white">{thresholds.min_score}</strong></span>
            <span>Emtia: <strong className="text-white">{thresholds.commodity_min_score}</strong></span>
            <span>BTC: <strong className="text-white">{thresholds.btc_min_score}</strong></span>
            <span>Max Spread: <strong className="text-white">{thresholds.max_spread_pips}p</strong></span>
            <span>
              ADX Kalkanı:{" "}
              <strong className="text-white">
                {thresholds.adx_filter_enabled ? `≥${thresholds.adx_min}` : "kapalı"}
              </strong>
            </span>
            <span>
              SuperTrend Teyidi:{" "}
              <strong className="text-white">
                {thresholds.supertrend_filter_enabled ? "açık" : "kapalı"}
              </strong>
            </span>
            <span>
              Majör Seans: <strong className="text-white">{thresholds.major_session_utc}</strong>
              {!thresholds.major_session_filter && " (kapalı)"}
            </span>
            <span>Min ATR: <strong className="text-white">{thresholds.major_min_atr_pips}p</strong></span>
          </div>
        )}
      </div>

      {/* GÜÇLÜ SİNYAL KARTLARI — radarın özü, en üstte */}
      {strongSignals.length > 0 && (
        <div className="rounded-2xl border border-emerald-500/30 bg-emerald-950/10 overflow-hidden shadow-xl">
          <div className="p-4 border-b border-emerald-500/20 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="text-lg">⚡</span>
              <h2 className="font-mono text-sm font-bold text-emerald-300 uppercase tracking-wider">
                Algoritmanın Onayladığı Güçlü İşlem Sinyalleri
              </h2>
            </div>
            <span className="font-mono text-[11px] text-bunker-muted">
              Tüm giriş kapıları açık · motor bu sinyalle işlem açabilir
            </span>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3 p-3">
            {strongSignals.map((c) => {
              const isBuy = c.action === "BUY";
              const st = supertrendText(c.supertrend_dir);
              return (
                <div
                  key={c.symbol}
                  className={`p-4 rounded-xl border font-mono space-y-3 ${
                    isBuy
                      ? "bg-emerald-950/25 border-emerald-500/40"
                      : "bg-rose-950/25 border-rose-500/40"
                  }`}
                >
                  <div className="flex items-start justify-between gap-2">
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="font-bold text-white text-base">{c.display}</span>
                        <span className="text-[10px] px-1.5 py-0.5 rounded bg-bunker-800 text-bunker-muted uppercase">
                          {c.category}
                        </span>
                      </div>
                      <div className="text-[11px] text-bunker-muted truncate">{c.name}</div>
                    </div>
                    <span
                      className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-md text-[11px] font-bold whitespace-nowrap ${
                        isBuy
                          ? "bg-emerald-500/20 text-emerald-300 border border-emerald-400/50"
                          : "bg-rose-500/20 text-rose-300 border border-rose-400/50"
                      }`}
                    >
                      {isBuy ? "▲ AL" : "▼ SAT"}
                    </span>
                  </div>

                  {/* Skor + hedef/stop */}
                  <div className="grid grid-cols-3 gap-2 p-2 rounded-lg bg-bunker-950/60 border border-bunker-800/80">
                    <div>
                      <span className="text-[10px] text-bunker-muted block">SKOR</span>
                      <span className="text-lg font-black text-emerald-400">{c.score.toFixed(1)}</span>
                      <span className="text-[10px] text-bunker-muted block">eşik {c.required_score}</span>
                    </div>
                    <div>
                      <span className="text-[10px] text-bunker-muted block">HEDEF (TP)</span>
                      <span className="text-sm font-bold text-emerald-400">+{c.pip_target}p</span>
                      <span className="text-[10px] text-bunker-muted block">R/R {c.risk_reward}</span>
                    </div>
                    <div>
                      <span className="text-[10px] text-bunker-muted block">STOP (SL)</span>
                      <span className="text-sm font-bold text-rose-400">-{c.stop_loss_pips}p</span>
                      <span className="text-[10px] text-bunker-muted block">ATR {c.atr_pips}p</span>
                    </div>
                  </div>

                  {/* Gösterge teyit satırı */}
                  <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px]">
                    <span className={adxTone(c.adx)}>ADX {c.adx.toFixed(0)}</span>
                    <span className={st.tone}>ST {st.text}</span>
                    <span className="text-bunker-muted">RSI {c.rsi_15m.toFixed(0)}</span>
                    <span className="text-bunker-muted">HTF {c.htf_trend}</span>
                  </div>

                  <div className="flex items-center justify-between text-[11px] pt-1 border-t border-bunker-800/60">
                    <span className="text-white font-bold">
                      {c.bid} / {c.ask}
                    </span>
                    <span className="text-cyan-400 font-bold">{c.spread_pips}p spread</span>
                    <button
                      type="button"
                      onClick={() => setChartModalCandidate(c)}
                      className="px-3 py-1.5 rounded-lg bg-blue-600/30 border border-blue-400/40 text-blue-300 font-bold hover:bg-blue-600/50 hover:text-white transition-all shadow-[0_0_10px_rgba(59,130,246,0.25)] flex items-center gap-1"
                      title="Profesyonel Mum Grafiğini Aç"
                    >
                      <span>📈</span>
                      <span>Grafik</span>
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* TÜM TARAMA TABLOSU */}
      <div className="rounded-2xl border border-bunker-800 bg-bunker-900/70 backdrop-blur-md overflow-hidden shadow-xl">
        <div className="p-4 border-b border-bunker-800 flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <span className="text-lg">📡</span>
            <h2 className="font-mono text-sm font-bold text-white uppercase tracking-wider">
              Tüm Tarama — {visible.length}/{candidates.length} Sembol
            </h2>
          </div>

          {/* Filtreler */}
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <input
              type="text"
              placeholder="🔍 Sembol ara…"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="bg-bunker-950 border border-bunker-700 rounded-lg px-2.5 py-1.5 font-mono text-white placeholder-bunker-600 outline-none focus:border-blue-400 w-36"
            />
            <select
              value={tierFilter}
              onChange={(e) => setTierFilter(e.target.value as any)}
              className="bg-bunker-950 border border-bunker-700 rounded-lg px-2.5 py-1.5 font-mono text-white outline-none focus:border-blue-400"
            >
              <option value="ALL">Tüm Kademeler</option>
              {TIER_ORDER.map((t) => (
                <option key={t} value={t}>
                  {TIER_META[t].label} ({tierCounts[t] || 0})
                </option>
              ))}
            </select>
            <select
              value={directionFilter}
              onChange={(e) => setDirectionFilter(e.target.value as any)}
              className="bg-bunker-950 border border-bunker-700 rounded-lg px-2.5 py-1.5 font-mono text-white outline-none focus:border-blue-400"
            >
              <option value="ALL">Tüm Yönler</option>
              <option value="BUY">▲ AL</option>
              <option value="SELL">▼ SAT</option>
            </select>
            {filtersActive && (
              <button
                type="button"
                onClick={() => {
                  setTierFilter("ALL");
                  setDirectionFilter("ALL");
                  setSearchQuery("");
                }}
                className="text-blue-400 hover:underline font-bold px-1"
              >
                ✕ Temizle
              </button>
            )}
          </div>
        </div>

        {loading ? (
          <div className="p-12 text-center font-mono text-sm text-bunker-muted">
            <div className="inline-block w-6 h-6 border-2 border-blue-400 border-t-transparent rounded-full animate-spin mb-2" />
            <p>Forex pariteleri taranıyor…</p>
          </div>
        ) : visible.length === 0 ? (
          <div className="p-12 text-center space-y-2 font-mono">
            <div className="text-3xl">🔍</div>
            <p className="text-sm font-bold text-white">Bu filtreyle eşleşen sembol yok.</p>
            <p className="text-xs text-bunker-muted">
              Filtreleri temizleyip tüm taramayı görebilirsiniz.
            </p>
          </div>
        ) : (
          <>
            {/* Masaüstü Tablo Görünümü */}
            <div className="hidden lg:block overflow-x-auto">
              <table className="w-full text-left font-mono text-xs">
                <thead className="bg-bunker-950/80 text-bunker-muted uppercase border-b border-bunker-800 text-[10px] tracking-wider">
                  <tr>
                    <th className="py-3 px-4">Parite / Varlık</th>
                    <th className="py-3 px-3">Kademe</th>
                    <th className="py-3 px-3">Yön</th>
                    <th className="py-3 px-3">Fiyat (Bid/Ask)</th>
                    <th className="py-3 px-3">Spread</th>
                    <th className="py-3 px-2">ADX</th>
                    <th className="py-3 px-2">S.Trend</th>
                    <th className="py-3 px-2">RSI</th>
                    <th className="py-3 px-3">Hedef / Stop</th>
                    <th className="py-3 px-3">Skor</th>
                    <th className="py-3 px-3">Durum / Engel</th>
                    <th className="py-3 px-4 text-right">Grafik</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-bunker-800/60">
                  {visible.map((c) => {
                    const isBuy = c.action === "BUY";
                    const isSell = c.action === "SELL";
                    const meta = TIER_META[c.tier];
                    const st = supertrendText(c.supertrend_dir);
                    return (
                      <tr
                        key={c.symbol}
                        className={`hover:bg-bunker-800/40 transition-colors group ${
                          c.tier === "STRONG" ? "bg-emerald-950/20" : ""
                        }`}
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
                            className={`inline-flex items-center gap-1.5 px-2 py-1 rounded-md text-[10px] font-bold whitespace-nowrap border ${meta.badge}`}
                            title={meta.hint}
                          >
                            <span className={`w-1.5 h-1.5 rounded-full ${meta.dot}`} />
                            {meta.label.replace(/^\S+\s/, "")}
                          </span>
                        </td>

                        <td className="py-3.5 px-3">
                          {isBuy || isSell ? (
                            <span
                              className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-md text-[11px] font-bold ${
                                isBuy
                                  ? "bg-emerald-500/15 text-emerald-400 border border-emerald-500/30"
                                  : "bg-rose-500/15 text-rose-400 border border-rose-500/30"
                              }`}
                            >
                              {isBuy ? "▲ AL" : "▼ SAT"}
                            </span>
                          ) : (
                            <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md text-[11px] font-bold bg-bunker-800 text-bunker-muted border border-bunker-700">
                              ⏸ BEKLE
                            </span>
                          )}
                        </td>

                        <td className="py-3.5 px-3 font-semibold text-white text-[11px] whitespace-nowrap">
                          {formatPrice(c.bid)} <span className="text-bunker-600">/</span>{" "}
                          {formatPrice(c.ask)}
                        </td>

                        <td className="py-3.5 px-3 text-cyan-400 font-bold">
                          {c.spread_pips}p
                        </td>

                        <td className={`py-3.5 px-2 font-bold ${adxTone(c.adx)}`}>
                          {c.adx.toFixed(0)}
                        </td>

                        <td className={`py-3.5 px-2 font-bold whitespace-nowrap ${st.tone}`}>
                          {st.text}
                        </td>

                        <td className="py-3.5 px-2 text-bunker-muted">
                          {c.rsi_15m.toFixed(0)}
                        </td>

                        <td className="py-3.5 px-3 whitespace-nowrap">
                          <span className="text-emerald-400 font-bold">+{c.pip_target}p</span>
                          <span className="text-bunker-600"> / </span>
                          <span className="text-rose-400 font-bold">-{c.stop_loss_pips}p</span>
                          <div className="text-[10px] text-bunker-muted">R/R {c.risk_reward}</div>
                        </td>

                        <td className="py-3.5 px-3">
                          <div className="flex items-center gap-1.5">
                            <div className="w-12 bg-bunker-800 rounded-full h-1.5 overflow-hidden">
                              <div
                                className={`h-full rounded-full ${
                                  c.score >= c.required_score ? "bg-emerald-400" : "bg-blue-400"
                                }`}
                                style={{ width: `${Math.min(100, c.score)}%` }}
                              />
                            </div>
                            <span className={`font-bold ${scoreTone(c.score, c.required_score)}`}>
                              {c.score.toFixed(1)}
                            </span>
                          </div>
                          <div className="text-[10px] text-bunker-muted">eşik {c.required_score}</div>
                        </td>

                        <td className="py-3.5 px-3">
                          {c.primary_blocker ? (
                            <div
                              className="text-[10px] text-amber-300/90 max-w-[190px] leading-snug"
                              title={(c.blocked_by || []).join(" · ")}
                            >
                              {c.blocker_text}
                            </div>
                          ) : (
                            <span className="text-[10px] text-emerald-400 font-bold">
                              Tüm kapılar açık
                            </span>
                          )}
                        </td>

                        <td className="py-3.5 px-4 text-right">
                          <button
                            type="button"
                            onClick={() => setChartModalCandidate(c)}
                            className="px-2.5 py-1.5 rounded-lg bg-blue-500/10 text-blue-400 border border-blue-400/20 hover:bg-blue-500/25 hover:text-white transition-all font-bold text-[11px] inline-flex items-center gap-1 shadow-sm"
                            title="Profesyonel Mum Grafiğini Aç"
                          >
                            <span>📈</span>
                            <span>Grafik</span>
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            {/* Mobil / Tablet Kart Görünümü */}
            <div className="lg:hidden space-y-3 p-3 font-mono">
              {visible.map((c) => {
                const isBuy = c.action === "BUY";
                const isSell = c.action === "SELL";
                const meta = TIER_META[c.tier];
                const st = supertrendText(c.supertrend_dir);
                return (
                  <div
                    key={c.symbol}
                    className={`p-3.5 rounded-2xl border shadow-md space-y-2.5 ${
                      c.tier === "STRONG"
                        ? "border-emerald-500/40 bg-emerald-950/20"
                        : "border-bunker-800 bg-bunker-900/90"
                    }`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <div className="flex items-center gap-2">
                        <span className="font-bold text-white text-base">{c.display}</span>
                        <span className="text-[10px] px-1.5 py-0.2 rounded bg-bunker-800 text-bunker-muted uppercase">
                          {c.category}
                        </span>
                      </div>
                      <span
                        className={`inline-flex items-center gap-1.5 px-2 py-1 rounded-md text-[10px] font-bold border ${meta.badge}`}
                      >
                        <span className={`w-1.5 h-1.5 rounded-full ${meta.dot}`} />
                        {meta.label.replace(/^\S+\s/, "")}
                      </span>
                    </div>

                    <div className="flex items-center gap-2">
                      {isBuy || isSell ? (
                        <span
                          className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-md text-[11px] font-bold ${
                            isBuy
                              ? "bg-emerald-500/15 text-emerald-400 border border-emerald-500/30"
                              : "bg-rose-500/15 text-rose-400 border border-rose-500/30"
                          }`}
                        >
                          {isBuy ? "▲ AL" : "▼ SAT"}
                        </span>
                      ) : (
                        <span className="px-2.5 py-1 rounded-md text-[11px] font-bold bg-bunker-800 text-bunker-muted border border-bunker-700">
                          ⏸ BEKLE
                        </span>
                      )}
                      <span className="text-white font-bold text-xs">
                        {formatPrice(c.bid)} / {formatPrice(c.ask)}
                      </span>
                      <span className="text-cyan-400 font-bold text-xs">{c.spread_pips}p</span>
                    </div>

                    <div className="grid grid-cols-4 gap-2 text-xs p-2 rounded-xl bg-bunker-950/70 border border-bunker-800/80">
                      <div>
                        <span className="text-[10px] text-bunker-muted block">SKOR</span>
                        <span className={`font-bold ${scoreTone(c.score, c.required_score)}`}>
                          {c.score.toFixed(1)}
                        </span>
                      </div>
                      <div>
                        <span className="text-[10px] text-bunker-muted block">ADX</span>
                        <span className={`font-bold ${adxTone(c.adx)}`}>{c.adx.toFixed(0)}</span>
                      </div>
                      <div>
                        <span className="text-[10px] text-bunker-muted block">S.TREND</span>
                        <span className={`font-bold ${st.tone}`}>
                          {c.supertrend_dir > 0 ? "BOĞA" : c.supertrend_dir < 0 ? "AYI" : "—"}
                        </span>
                      </div>
                      <div>
                        <span className="text-[10px] text-bunker-muted block">RSI</span>
                        <span className="font-bold text-bunker-muted">{c.rsi_15m.toFixed(0)}</span>
                      </div>
                    </div>

                    <div className="grid grid-cols-2 gap-2 text-xs">
                      <div>
                        <span className="text-[10px] text-bunker-muted block">Hedef (TP)</span>
                        <span className="text-emerald-400 font-bold">+{c.pip_target}p</span>
                      </div>
                      <div className="text-right">
                        <span className="text-[10px] text-bunker-muted block">Stop (SL)</span>
                        <span className="text-rose-400 font-bold">-{c.stop_loss_pips}p</span>
                      </div>
                    </div>

                    {c.primary_blocker && (
                      <div className="text-[10px] text-amber-300/90 p-2 rounded-lg bg-amber-950/20 border border-amber-500/20 leading-snug">
                        ⚠️ {c.blocker_text}
                      </div>
                    )}

                    <div className="flex items-center justify-between text-[11px] pt-1 border-t border-bunker-800/60">
                      <span className="text-bunker-muted">R/R {c.risk_reward}</span>
                      <button
                        type="button"
                        onClick={() => setChartModalCandidate(c)}
                        className="px-3 py-1.5 rounded-lg bg-blue-600/30 border border-blue-400/40 text-blue-300 font-bold text-xs hover:bg-blue-600/50 hover:text-white transition-all touch-target inline-flex items-center gap-1 shadow-sm"
                        title="Profesyonel Mum Grafiğini Aç"
                      >
                        <span>📈</span>
                        <span>Grafik</span>
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          </>
        )}
      </div>

      {/* FOREX RİSK & LOT HESAPLAYICI (WIDGET) */}
      <div id="lot-calculator" className="p-5 rounded-2xl border border-bunker-800 bg-gradient-to-br from-bunker-900/90 to-bunker-950/90 shadow-xl space-y-4">
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
              Pozisyon Hacmi Riski (% Bakiye):
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

      {/* PROFESYONEL FOREX GRAFİK MODALI (Spot Tarzı Lightweight Charts) */}
      {chartModalCandidate && (
        <ForexChartModal
          candidate={chartModalCandidate}
          onClose={() => setChartModalCandidate(null)}
          onOpenLotCalculator={(sym, sl) => {
            setCalcSymbol(sym);
            setCalcSlPips(sl);
            // Sayfa altına doğru hesaplayıcıya kaydır
            const calcElem = document.getElementById("lot-calculator");
            if (calcElem) {
              calcElem.scrollIntoView({ behavior: "smooth" });
            }
          }}
        />
      )}
    </div>
  );
}
