"use client";

import React, { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { apiFetch } from "../lib/api";
import { usePolling } from "../lib/usePolling";
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
  /** Ticker kotasyonu yoksa backend "MT5 tik yok" yazabilir. */
  error?: string | null;
  score: number;
  trend: string;
  action: "BUY" | "SELL" | "HOLD";
  /** 5 dk RSI. Eski yanıtta yalnız `rsi_15m` olabilir. */
  rsi_5m?: number | null;
  rsi_15m?: number | null;
  macd_verdict: string;
  cmo: number;
  cci: number;
  adx: number;
  supertrend_dir: number;
  htf_trend: string;
  pip_target?: number | null;
  stop_loss_pips?: number | null;
  risk_reward?: string | number | null;
  atr_pips: number;
  tv_symbol: string;
  // Kapı değerlendirmesi (otonom motorun gerçek giriş kararı)
  tier: Tier;
  /** Motor bu adayla emir açacak mı. Alan yoksa `tier === "STRONG"` esas alınır. */
  motor_acar?: boolean;
  /** Skor eşiği geçti mi. Alan yoksa skor ile `required_score` karşılaştırılır. */
  skor_gecti?: boolean;
  signal_ready: boolean;
  gate_passed: boolean;
  blocked_by: string[];
  primary_blocker: string | null;
  blocker_text: string;
  required_score?: number | null;
  csm_diff?: number;
  csm_bias?: string;
  fvg_type?: string;
  fvg_gap?: number;
  dss_score?: number;
  dss_tier?: string;
  news_info?: {
    has_active_news?: boolean;
    alignment?: "SUPPORTIVE" | "OPPOSING" | "NEUTRAL" | string;
    badge?: string;
    remaining_min?: number;
    event_title?: string;
    events_count?: number;
  };
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

function optNum(v: unknown): number | null {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

/** Gösterim: `rsi_5m` varsa o, yoksa `rsi_15m`. İkisi de yoksa tire. */
function fmtRsi(c: { rsi_5m?: number | null; rsi_15m?: number | null }): string {
  const n = optNum(c.rsi_5m) ?? optNum(c.rsi_15m);
  return n == null ? "—" : n.toFixed(0);
}

function fmtTp(v: unknown): string {
  const n = optNum(v);
  return n == null ? "—" : `+${n}p`;
}

function fmtSl(v: unknown): string {
  const n = optNum(v);
  return n == null ? "—" : `-${n}p`;
}

function fmtRr(v: unknown): string {
  if (typeof v === "number" && Number.isFinite(v)) return String(v);
  if (typeof v === "string" && v.trim()) return v.trim();
  return "—";
}

function radarQuote(c: { bid?: number | null; ask?: number | null; error?: string | null }): { text: string; failed: boolean } {
  const err = typeof c.error === "string" ? c.error.trim() : "";
  const bid = formatPrice(c.bid);
  const ask = formatPrice(c.ask);
  if (err && bid === "—" && ask === "—") return { text: err, failed: true };
  return { text: `${bid} / ${ask}`, failed: false };
}

/** Bildirim ve güçlü sinyal: alan varsa yalnız `motor_acar === true`. */
function motorOpens(c: { motor_acar?: boolean; tier?: string }): boolean {
  if (typeof c.motor_acar === "boolean") return c.motor_acar;
  return c.tier === "STRONG";
}

function scorePassed(c: ForexCandidate): boolean {
  if (typeof c.skor_gecti === "boolean") return c.skor_gecti;
  const req = optNum(c.required_score);
  return req != null && c.score >= req;
}

/** Skor rengi: giriş eşiğine göre — eşiği geçen yeşil, yaklaşan sarı. */
function scoreTone(score: number, required: number | null, passed: boolean): string {
  if (passed) return "text-emerald-400";
  if (required != null && score >= required - 10) return "text-yellow-400";
  return "text-bunker-muted";
}

/** Strateji taraması satırı (backend /auto-paper/strategy-scan ve /scan-now). */
interface ScanNowRow {
  strategy: string;
  strategy_label: string;
  symbol: string;
  display: string;
  status: string;
  action: string | null;
  panel_kapsaminda: boolean;
}

interface ScanNowResponse {
  status: string;
  scanned_at: string;
  total_rows: number;
  candidates_count: number;
  sessions_active: string[];
  entry_hour_blocked: boolean;
  motor_enabled: boolean;
  rows: ScanNowRow[];
}

/**
 * Satırın hangi strateji kolundan geldiği — rozet rengi/etiketi TEK yerden.
 *
 * Kapsam (2026-10-13): motordaki TÜM giriş kolları listelenir; yeni bir kol
 * eklenirse (bkz. backend `_forex_auto_paper_loop` aday üretimi) buraya da
 * eklenmeli. Motorda üretilip burada tanımsız kalan kol ham koduyla görünür
 * (bilinçli: panelde sessizce kaybolmaz).
 */
const ARM_META: Record<string, { icon: string; label: string; medal: string }> = {
  RADAR: {
    icon: "📡",
    label: "Klasik Radar",
    medal: "bg-blue-500/15 text-blue-300 border-blue-500/40",
  },
  DONCHIAN_ADX: {
    icon: "🎯",
    label: "Donchian ADX",
    medal: "bg-purple-500/15 text-purple-300 border-purple-500/40",
  },
  EMA_ADX_PULLBACK_M5: {
    icon: "📐",
    label: "EMA+ADX",
    medal: "bg-cyan-500/15 text-cyan-300 border-cyan-500/40",
  },
  S3_5M: {
    icon: "🧭",
    label: "S3 · 5m",
    medal: "bg-amber-500/15 text-amber-300 border-amber-500/40",
  },
  S3_15M: {
    icon: "🧭",
    label: "S3 · 15m",
    medal: "bg-amber-500/15 text-amber-300 border-amber-500/40",
  },
  LONDON_BREAKOUT: {
    icon: "🌅",
    label: "London Breakout",
    medal: "bg-orange-500/15 text-orange-300 border-orange-500/40",
  },
  LONDON_SIGN: {
    icon: "🌆",
    label: "London Sign",
    medal: "bg-fuchsia-500/15 text-fuchsia-300 border-fuchsia-500/40",
  },
  SQUEEZE_KC_M15: {
    icon: "🌀",
    label: "Keltner Squeeze · 15m",
    medal: "bg-teal-500/15 text-teal-300 border-teal-500/40",
  },
  COMBO3_M5: {
    icon: "🧩",
    label: "Combo3 UTBot+Vortex · 5m",
    medal: "bg-rose-500/15 text-rose-300 border-rose-500/40",
  },
  KOMBO_M5: {
    icon: "🧪",
    label: "Kombo XAU · 5m (KMB1/4/9)",
    medal: "bg-fuchsia-500/15 text-fuchsia-300 border-fuchsia-500/40",
  },
};

function armMeta(strategy: string) {
  return (
    ARM_META[strategy] || {
      icon: "🧩",
      label: strategy || "Bilinmeyen kol",
      medal: "bg-bunker-800 text-bunker-muted border-bunker-700",
    }
  );
}

/** Kolların panelde gösterim sırası (motor karar akışına yakın sıra). */
const ARM_ORDER: string[] = [
  "RADAR",
  "LONDON_SIGN",
  "DONCHIAN_ADX",
  "EMA_ADX_PULLBACK_M5",
  "S3_5M",
  "S3_15M",
  "LONDON_BREAKOUT",
  "SQUEEZE_KC_M15",
  "COMBO3_M5",
  "KOMBO_M5",
];

export default function ForexRadarPage() {
  const [candidates, setCandidates] = useState<ForexCandidate[]>([]);
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [scanNote, setScanNote] = useState<string>("");
  const [thresholds, setThresholds] = useState<RadarThresholds | null>(null);
  const [csm, setCsm] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [radarError, setRadarError] = useState("");
  const [strategyScanError, setStrategyScanError] = useState("");
  const [scanNowNotice, setScanNowNotice] = useState<{ ok: boolean; text: string } | null>(null);
  const [calcError, setCalcError] = useState("");
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  // Filtreler
  const [tierFilter, setTierFilter] = useState<"ALL" | Tier>("ALL");
  const [directionFilter, setDirectionFilter] = useState<"ALL" | "BUY" | "SELL">("ALL");
  const [categoryFilter, setCategoryFilter] = useState<string>("ALL");
  const [searchQuery, setSearchQuery] = useState<string>("");

  // Quick Lot Calculator state
  const [calcBalance, setCalcBalance] = useState<number>(10000);
  const [calcRiskPct, setCalcRiskPct] = useState<number>(10.0);
  const [calcSlPips, setCalcSlPips] = useState<number>(20);
  const [calcSymbol, setCalcSymbol] = useState<string>("EURUSD");
  const [calcResult, setCalcResult] = useState<any>(null);

  // Profesyonel Grafik Modalı (Lightweight Charts)
  const [chartModalCandidate, setChartModalCandidate] = useState<ForexCandidate | null>(null);

  // Strateji taraması — TÜM giriş kolları (Radar/S3/LB/LS/Donchian/EAP).
  // Sayfa açıkken periyodik yoklanır; "Şimdi Tara" aynı ucu POST ile zorlar.
  const [scanning, setScanning] = useState(false);
  const [scanNowResult, setScanNowResult] = useState<ScanNowResponse | null>(null);
  const [armFilter, setArmFilter] = useState<string>("ALL");
  const runScanNow = async () => {
    setScanning(true);
    try {
      const res = await apiFetch("/api/forex/auto-paper/scan-now", { method: "POST" });
      // Buton listeyi sıfırlar ki manuel turun sonucu doğrudan görünsün
      // (kullanıcı bir kola süzülmüşse ve o kol bu turda aday üretmediyse
      // "hiçbir şey olmadı" izlenimi doğmasın).
      setArmFilter("ALL");
      setScanNowResult(res);
      const rows = Number(res?.total_rows ?? res?.rows?.length ?? 0);
      setScanNowNotice({
        ok: true,
        text: `Tarama tamamlandı. ${rows} satır döndü.`,
      });
    } catch (err) {
      const detail = err instanceof Error ? err.message : "Tarama başarısız";
      setScanNowNotice({ ok: false, text: `Tarama başarısız: ${detail}` });
    } finally {
      setScanning(false);
    }
  };

  const fetchStrategyScan = async () => {
    try {
      const res = await apiFetch("/api/forex/auto-paper/strategy-scan");
      if (res && res.rows) setScanNowResult(res);
      setStrategyScanError("");
    } catch (err) {
      const detail = err instanceof Error ? err.message : "Strateji taraması alınamadı";
      setStrategyScanError(`Strateji taraması alınamadı: ${detail}`);
    }
  };

  const fetchRadar = async () => {
    try {
      const data = await apiFetch("/api/forex/radar");
      if (data && data.candidates) {
        setCandidates(data.candidates);
        setSessions(data.sessions || []);
        setScanNote(data.scan_note || "");
        setThresholds(data.thresholds || null);
        setCsm(data.csm || null);
        setLastUpdated(new Date());
        setRadarError("");
      }
    } catch (err) {
      const detail = err instanceof Error ? err.message : "Radar verisi alınamadı";
      setRadarError(`Radar verisi alınamadı: ${detail}`);
    } finally {
      setLoading(false);
    }
  };

  // PERFORMANS (2026-10-08): 3 sn'lik çıplak interval yerine usePolling —
  // arka planda durur, üst üste binen istekleri engeller.
  usePolling(fetchRadar, 3000);

  // Strateji taraması 5 sn'de bir (backend'de aynı TTL önbelleği var): radar
  // tablosu klasik skoru, bu bölüm ise DİĞER tüm giriş kollarını gösterir.
  // Sekme arka plandayken usePolling durur — motor döngüsü zaten kendi turunda
  // aynı kararları verir, panelin yoklaması yalnız görünürlük içindir.
  usePolling(fetchStrategyScan, 5000);

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
      setCalcError("");
    } catch (err) {
      setCalcResult(null);
      const detail = err instanceof Error ? err.message : "Lot hesaplanamadı";
      setCalcError(`Lot hesaplanamadı: ${detail}`);
    }
  };

  useEffect(() => {
    calculateLot();
  }, [calcBalance, calcRiskPct, calcSlPips, calcSymbol]);

  // Güçlü sinyaller — filtrelerden bağımsız, radarın özü.
  const strongSignals = useMemo(
    () => candidates.filter((c) => motorOpens(c)),
    [candidates],
  );

  // Kol özeti: her giriş kolu kaç sembol taradı / kaç canlı aday üretti.
  // Sıralama ARM_ORDER (motor akışı), tanımsız kollar sona alfabetik eklenir —
  // backend yeni bir kol eklerse panelde kaybolmaz, "🧩" rozetiyle görünür.
  const armStats = useMemo(() => {
    const rows = scanNowResult?.rows || [];
    const byArm = new Map<string, { strategy: string; total: number; candidates: number }>();
    for (const r of rows) {
      const key = r.strategy || "—";
      const cur = byArm.get(key) || { strategy: key, total: 0, candidates: 0 };
      cur.total += 1;
      if (r.action) cur.candidates += 1;
      byArm.set(key, cur);
    }
    const known = ARM_ORDER.filter((a) => byArm.has(a)).map((a) => byArm.get(a)!);
    const unknown = [...byArm.values()]
      .filter((a) => !ARM_ORDER.includes(a.strategy))
      .sort((x, y) => x.strategy.localeCompare(y.strategy));
    return [...known, ...unknown];
  }, [scanNowResult]);

  const visibleScanRows = useMemo(() => {
    const rows = scanNowResult?.rows || [];
    return armFilter === "ALL" ? rows : rows.filter((r) => r.strategy === armFilter);
  }, [scanNowResult, armFilter]);

  const tierCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const c of candidates) counts[c.tier] = (counts[c.tier] || 0) + 1;
    return counts;
  }, [candidates]);

  // Tablo: kademe + yön + kategori + arama filtreleri uygulanır.
  const visible = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();
    return candidates.filter((c) => {
      if (tierFilter !== "ALL" && c.tier !== tierFilter) return false;
      if (directionFilter !== "ALL" && c.action !== directionFilter) return false;
      if (categoryFilter !== "ALL") {
        if (categoryFilter === "crypto") {
          const isCrypto = c.category === "crypto" || ["BTCUSD", "ETHUSD", "SOLUSD", "BNBUSD", "XRPUSD", "LNKUSD", "UNIUSD", "AVXUSD", "ADAUSD", "XTZUSD", "DATAUSD"].includes(c.symbol);
          if (!isCrypto) return false;
        } else if (categoryFilter === "commodity") {
          if (c.category !== "commodity" && !c.symbol.includes("XAU")) return false;
        } else if (categoryFilter === "index") {
          if (c.category !== "index" && !c.symbol.includes("US30") && !c.symbol.includes("NAS100")) return false;
        } else if (categoryFilter === "major") {
          if (c.category !== "major") return false;
        } else if (categoryFilter === "cross") {
          if (c.category !== "cross") return false;
        }
      }
      if (q && !(`${c.display} ${c.symbol} ${c.name}`.toLowerCase().includes(q))) return false;
      return true;
    });
  }, [candidates, tierFilter, directionFilter, categoryFilter, searchQuery]);

  const filtersActive = tierFilter !== "ALL" || directionFilter !== "ALL" || categoryFilter !== "ALL" || searchQuery.trim() !== "";

  return (
    <div className="space-y-6 pb-12">
      {/* ÜST BAŞLIK & SEANS BİLGİSİ */}
      <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4">
        <div className="flex flex-col sm:flex-row sm:items-center gap-3 min-w-0">
          <div className="min-w-0">
            <h1 className="text-xl font-bold font-mono text-white tracking-tight">Forex Radar</h1>
            <p className="text-xs text-bunker-muted font-mono mt-0.5">
              Majör pariteler, değerli madenler ve endeksler — algoritma taraması (24/5)
            </p>
          </div>
          <button
            onClick={runScanNow}
            disabled={scanning}
            className="shrink-0 min-h-11 sm:min-h-10 px-4 rounded-lg font-mono text-sm font-bold bg-cyan-400 text-bunker-950 hover:bg-sky-400 disabled:bg-bunker-700 disabled:text-bunker-muted disabled:cursor-not-allowed transition-colors flex items-center justify-center gap-2"
            title="Tüm stratejileri (Radar, S3, LB, Donchian, EAP) sırayla tek turda tetikler — salt-okunur rapor, işlem açmaz"
          >
            {scanning ? (
              <>
                <span className="inline-block w-3 h-3 border-2 border-bunker-950/40 border-t-bunker-950 rounded-full animate-spin" />
                Taranıyor…
              </>
            ) : (
              "Şimdi tara"
            )}
          </button>
        </div>

        {/* Piyasa seansları */}
        <div className="flex items-center gap-2 overflow-x-auto pb-1 lg:pb-0" aria-label="Piyasa seansları">
          {sessions.map((s) => (
            <div
              key={s.name}
              className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border font-mono text-xs whitespace-nowrap ${
                s.active
                  ? "bg-emerald-500/15 border-emerald-500/40 text-emerald-300"
                  : "bg-bunker-900/80 border-bunker-800 text-bunker-muted"
              }`}
            >
              <span aria-hidden>{s.flag}</span>
              <span className="font-bold">{s.name}</span>
              <span className="text-[10px]">{s.active ? "açık" : "kapalı"}</span>
            </div>
          ))}
        </div>
      </div>

      {scanNowNotice && (
        <p
          role="status"
          className={`px-4 py-2 rounded-xl border font-mono text-xs ${
            scanNowNotice.ok
              ? "bg-emerald-500/10 border-emerald-500/40 text-emerald-300"
              : "bg-rose-500/10 border-rose-500/40 text-rose-300"
          }`}
        >
          {scanNowNotice.text}
        </p>
      )}

      {strategyScanError && (
        <div role="alert" className="px-4 py-3 rounded-xl border border-rose-500/40 bg-rose-500/10 text-rose-300 font-mono text-xs flex flex-wrap items-center justify-between gap-2">
          <span>{strategyScanError}</span>
          <button
            type="button"
            onClick={() => { void fetchStrategyScan(); }}
            className="px-3 py-1 rounded-lg bg-rose-500/20 border border-rose-400/40 font-bold"
          >
            Tekrar Dene
          </button>
        </div>
      )}

      {/* TÜM TARAMA SİSTEMLERİ — giriş kollarının canlı durumu.
          Eskiden yalnız "Şimdi Tara" sonrası görünürdü; artık sayfa açıkken
          5 sn'de bir kendiliğinden taranır (backend GET /auto-paper/strategy-scan). */}
      {scanNowResult && (
        <div className="p-4 rounded-2xl bg-bunker-900/80 border border-emerald-500/30 backdrop-blur-md shadow-lg">
          <div className="flex items-center justify-between gap-3 mb-3 flex-wrap">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-lg">🔬</span>
              <span className="font-mono text-sm font-bold text-emerald-300">
                Tüm Tarama Sistemleri — {scanNowResult.candidates_count}/{scanNowResult.total_rows} kol canlı aday üretti
              </span>
              <span className="flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-mono font-bold bg-emerald-500/15 text-emerald-300 border border-emerald-500/30">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                KENDİLİĞİNDEN TARANIYOR
              </span>
            </div>
            <div className="flex items-center gap-2 flex-wrap font-mono text-[11px]">
              <span className="text-bunker-muted">{scanNowResult.scanned_at}</span>
              {scanNowResult.motor_enabled ? (
                <span className="px-2 py-0.5 rounded bg-emerald-500/15 border border-emerald-500/40 text-emerald-300 font-bold">MOTOR AÇIK</span>
              ) : (
                <span className="px-2 py-0.5 rounded bg-yellow-500/15 border border-yellow-500/40 text-yellow-300 font-bold">MOTOR KAPALI — adaylar işleme çevrilmez</span>
              )}
              {scanNowResult.entry_hour_blocked && (
                <span className="px-2 py-0.5 rounded bg-rose-500/15 border border-rose-500/40 text-rose-300 font-bold">ZAYIF SAAT KALKANI</span>
              )}
              <Link
                href="/forex/ayarlar"
                className="px-2 py-0.5 rounded bg-bunker-800 border border-bunker-700 text-bunker-muted hover:text-white transition-colors"
                title="Kolların sembol listelerini ve eşiklerini ayarlar sayfasından yönet"
              >
                ⚙️ ayarlar
              </Link>
            </div>
          </div>

          {/* Kol rozetleri — hangi kol kaç sembol tarıyor, kaçı aday üretti.
              Tıklayınca liste o kola süzülür (aynı kola ikinci tık filtreyi kaldırır). */}
          <div className="flex flex-wrap gap-2 mb-3">
            <button
              type="button"
              onClick={() => setArmFilter("ALL")}
              className={`px-2 py-1 rounded-lg border font-mono text-[10px] font-bold transition-all ${
                armFilter === "ALL"
                  ? "bg-emerald-500/20 border-emerald-400/60 text-emerald-200"
                  : "bg-bunker-800/80 border-bunker-700 text-bunker-muted hover:text-white"
              }`}
            >
              TÜMÜ · {scanNowResult.total_rows} satır
            </button>
            {armStats.map((a) => {
              const meta = armMeta(a.strategy);
              const on = armFilter === a.strategy;
              return (
                <button
                  key={a.strategy}
                  type="button"
                  onClick={() => setArmFilter(on ? "ALL" : a.strategy)}
                  className={`px-2 py-1 rounded-lg border font-mono text-[10px] font-bold transition-all ${
                    on
                      ? "bg-emerald-500/20 border-emerald-400/60 text-emerald-200"
                      : a.candidates > 0
                        ? `${meta.medal} hover:brightness-125`
                        : "bg-bunker-800/80 border-bunker-700 text-bunker-muted hover:text-white"
                  }`}
                  title={`${meta.label} — ${a.total} sembol tarandı, ${a.candidates} canlı aday`}
                >
                  {meta.icon} {meta.label} · {a.total}
                  {a.candidates > 0 && (
                    <span className="ml-1 text-emerald-300">★{a.candidates}</span>
                  )}
                </button>
              );
            })}
          </div>

          <div className="space-y-1 max-h-96 overflow-y-auto">
            {visibleScanRows.map((r, i) => {
              const meta = armMeta(r.strategy);
              return (
                <div
                  key={`${r.strategy}-${r.symbol}-${i}`}
                  className={`flex items-center gap-2 px-2.5 py-1.5 rounded-lg font-mono text-xs border ${
                    r.action
                      ? "bg-emerald-500/10 border-emerald-500/30"
                      : "bg-bunker-900/60 border-bunker-800"
                  }`}
                >
                  <span className={`px-1.5 py-0.5 rounded text-[10px] font-bold shrink-0 border ${meta.medal}`}>
                    {meta.icon} {meta.label}
                  </span>
                  <span className="font-bold text-white shrink-0">{r.display}</span>
                  {r.action && (
                    <span className={`font-bold shrink-0 ${r.action === "BUY" ? "text-emerald-400" : "text-rose-400"}`}>
                      {r.action === "BUY" ? "▲ AL" : "▼ SAT"}
                    </span>
                  )}
                  <span className={r.action ? "text-emerald-200/90" : "text-bunker-muted"}>{r.status}</span>
                  {!r.panel_kapsaminda && r.symbol !== "—" && (
                    <span
                      className="ml-auto shrink-0 px-1.5 py-0.5 rounded text-[10px] bg-yellow-500/10 border border-yellow-500/30 text-yellow-300"
                      title="Bu sembol allowed_symbols dışında — sinyal olsa bile motor işlem açamaz"
                    >
                      panel kapsamı dışı
                    </span>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Menüde olmayan iki derin bağlantı (rapor/grafik/takvim zaten menüde) */}
      <div className="flex flex-wrap items-center gap-x-5 gap-y-1 font-mono text-xs">
        <Link href="/forex/portfolio?tab=xauusd" className="inline-flex items-center min-h-11 sm:min-h-0 font-bold text-cyan-300 hover:text-cyan-200 hover:underline">
          XAUUSD komuta ve karar logları →
        </Link>
        <Link href="/forex/portfolio" className="inline-flex items-center min-h-11 sm:min-h-0 font-bold text-cyan-300 hover:text-cyan-200 hover:underline">
          Merkezi otonom izleme →
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

      {/* 8x8 PARA BİRİMİ GÜÇ MATRİSİ (CSM - CURRENCY STRENGTH METER) */}
      {csm && csm.ranking && csm.ranking.length > 0 && (
        <div className="p-4 rounded-2xl bg-bunker-900/90 border border-blue-500/30 shadow-xl font-mono">
          <div className="flex flex-wrap items-center justify-between gap-2 mb-3 pb-2.5 border-b border-bunker-800">
            <div className="flex items-center gap-2">
              <span className="text-base">🌐</span>
              <span className="text-xs font-bold text-white uppercase tracking-wider">
                Para Birimi Güç Matrisi (CSM - Currency Strength Meter)
              </span>
              <span className="text-[10px] px-2 py-0.5 rounded bg-blue-500/20 text-blue-300 font-bold border border-blue-500/30">
                8 Para Birimi · Kurumsal Akış Sıralaması
              </span>
            </div>
            <div className="text-[11px] text-bunker-muted flex items-center gap-3">
              <span>Lider: <strong className="text-emerald-400">#{csm.ranks?.[csm.strongest] ?? 1} {csm.strongest}</strong></span>
              <span>En Zayıf: <strong className="text-rose-400">#{csm.ranks?.[csm.weakest] ?? 8} {csm.weakest}</strong></span>
            </div>
          </div>
          <div className="grid grid-cols-4 sm:grid-cols-8 gap-2">
            {csm.ranking.map(([curr, score]: [string, number], idx: number) => {
              const isPositive = score > 0;
              const isTop = idx === 0;
              const isBottom = idx === csm.ranking.length - 1;
              return (
                <div
                  key={curr}
                  className={`p-2.5 rounded-xl border text-center transition-all ${
                    isTop
                      ? "bg-emerald-950/40 border-emerald-500/50 shadow-[0_0_12px_rgba(16,185,129,0.2)]"
                      : isBottom
                      ? "bg-rose-950/40 border-rose-500/50 shadow-[0_0_12px_rgba(244,63,94,0.2)]"
                      : "bg-bunker-950/50 border-bunker-800"
                  }`}
                >
                  <div className="flex items-center justify-between text-[10px] text-bunker-muted mb-0.5">
                    <span>#{idx + 1}</span>
                    {isTop ? <span className="text-emerald-400 font-bold">LİDER</span> : isBottom ? <span className="text-rose-400 font-bold">DİP</span> : null}
                  </div>
                  <div className="text-sm font-black text-white">{curr}</div>
                  <div className={`text-xs font-bold ${isPositive ? "text-emerald-400" : "text-rose-400"}`}>
                    {score > 0 ? `+${score.toFixed(1)}` : score.toFixed(1)}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

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
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="font-bold text-white text-base">{c.display}</span>
                        <span className="text-[10px] px-1.5 py-0.5 rounded bg-bunker-800 text-bunker-muted uppercase">
                          {c.category}
                        </span>
                        {c.dss_tier === "A+" && (
                          <span className="text-[10px] px-2 py-0.5 rounded-full font-black bg-gradient-to-r from-amber-500/30 to-yellow-500/30 border border-amber-400 text-amber-200 animate-pulse shadow-[0_0_10px_rgba(245,158,11,0.3)]">
                            👑 A+ KURUMSAL
                          </span>
                        )}
                        {c.dss_tier === "B" && (
                          <span className="text-[10px] px-1.5 py-0.5 rounded font-bold bg-blue-500/20 border border-blue-400/40 text-blue-300">
                            ✨ B KURULUM
                          </span>
                        )}
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

                  {/* Ekonomik Takvim Haber Yönü Rozeti */}
                  {c.news_info?.has_active_news && (
                    <div
                      className={`px-2.5 py-1.5 rounded-lg border flex items-center justify-between text-xs font-bold ${
                        c.news_info.alignment === "SUPPORTIVE"
                          ? "bg-amber-500/15 border-amber-500/40 text-amber-300 shadow-[0_0_12px_rgba(245,158,11,0.2)]"
                          : "bg-rose-500/15 border-rose-500/40 text-rose-300 shadow-[0_0_12px_rgba(244,63,94,0.2)]"
                      }`}
                    >
                      <div className="flex items-center gap-1.5 truncate">
                        <span>{c.news_info.alignment === "SUPPORTIVE" ? "🔥" : "⚠️"}</span>
                        <span className="truncate">{c.news_info.badge || c.news_info.event_title}</span>
                      </div>
                      {c.news_info.remaining_min != null && (
                        <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-black/40 text-white/90 shrink-0">
                          {c.news_info.remaining_min.toFixed(0)} dk
                        </span>
                      )}
                    </div>
                  )}

                  {/* Skor + hedef/stop */}
                  <div className="grid grid-cols-3 gap-2 p-2 rounded-lg bg-bunker-950/60 border border-bunker-800/80">
                    <div>
                      <span className="text-[10px] text-bunker-muted block">SKOR</span>
                      <span className="text-lg font-black text-emerald-400">{c.score.toFixed(1)}</span>
                      <span className="text-[10px] text-bunker-muted block">eşik {optNum(c.required_score) ?? "—"}</span>
                    </div>
                    <div>
                      <span className="text-[10px] text-bunker-muted block">HEDEF (TP)</span>
                      <span className="text-sm font-bold text-emerald-400">{fmtTp(c.pip_target)}</span>
                      <span className="text-[10px] text-bunker-muted block">R/R {fmtRr(c.risk_reward)}</span>
                    </div>
                    <div>
                      <span className="text-[10px] text-bunker-muted block">STOP (SL)</span>
                      <span className="text-sm font-bold text-rose-400">{fmtSl(c.stop_loss_pips)}</span>
                      <span className="text-[10px] text-bunker-muted block">ATR {c.atr_pips}p</span>
                    </div>
                  </div>

                  {/* Gösterge teyit satırı */}
                  <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px]">
                    <span className={adxTone(c.adx)}>ADX {c.adx.toFixed(0)}</span>
                    <span className={st.tone}>ST {st.text}</span>
                    <span className="text-bunker-muted">RSI (5 dk) {fmtRsi(c)}</span>
                    <span className="text-bunker-muted">HTF {c.htf_trend}</span>
                    {c.csm_diff != null && c.csm_diff !== 0 && (
                      <span className={`font-bold ${c.csm_diff > 0 ? "text-emerald-400" : "text-rose-400"}`}>
                        CSM {c.csm_diff > 0 ? `+${c.csm_diff.toFixed(1)}` : c.csm_diff.toFixed(1)}
                      </span>
                    )}
                    {c.fvg_type && c.fvg_type !== "NONE" && (
                      <span className="text-purple-300 font-bold">⚡ FVG {c.fvg_type === "BULLISH_FVG" ? "Boğa" : "Ayı"}</span>
                    )}
                  </div>

                  <div className="flex items-center justify-between text-[11px] pt-1 border-t border-bunker-800/60">
                    <span className={`font-bold ${radarQuote(c).failed ? "text-rose-300" : "text-white"}`}>
                      {radarQuote(c).text}
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
              value={categoryFilter}
              onChange={(e) => setCategoryFilter(e.target.value)}
              className="bg-bunker-950 border border-bunker-700 rounded-lg px-2.5 py-1.5 font-mono text-white outline-none focus:border-blue-400"
            >
              <option value="ALL">Tüm Kategoriler</option>
              <option value="crypto">⚡ Kripto (7/24)</option>
              <option value="major">Majör Pariteler</option>
              <option value="cross">Kros Pariteler</option>
              <option value="commodity">Emtia (Altın)</option>
              <option value="index">Endeksler (US30 / NAS)</option>
            </select>
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
                  setCategoryFilter("ALL");
                  setSearchQuery("");
                }}
                className="text-blue-400 hover:underline font-bold px-1"
              >
                ✕ Temizle
              </button>
            )}
          </div>
        </div>

        {radarError && candidates.length > 0 && (
          <p role="alert" className="px-4 py-2 font-mono text-xs text-rose-300 border-b border-rose-500/30 bg-rose-500/10">
            {radarError} Son başarılı tarama ekranda duruyor.
          </p>
        )}

        {loading && candidates.length === 0 ? (
          <div className="p-12 text-center font-mono text-sm text-bunker-muted">
            <div className="inline-block w-6 h-6 border-2 border-blue-400 border-t-transparent rounded-full animate-spin mb-2" />
            <p>Forex pariteleri taranıyor…</p>
          </div>
        ) : radarError && candidates.length === 0 ? (
          <div role="alert" className="p-12 text-center space-y-3 font-mono">
            <div className="text-3xl">⚠️</div>
            <p className="text-sm font-bold text-rose-300">{radarError}</p>
            <p className="text-xs text-bunker-muted">
              Bu bir filtre sonucu değil. Radar isteği başarısız oldu.
            </p>
            <button
              type="button"
              onClick={() => { setLoading(true); void fetchRadar(); }}
              className="px-4 py-2 rounded-lg bg-rose-500/20 border border-rose-400/40 text-rose-200 font-bold text-xs"
            >
              Tekrar Dene
            </button>
          </div>
        ) : visible.length === 0 ? (
          <div className="p-12 text-center space-y-2 font-mono">
            <div className="text-3xl">🔍</div>
            <p className="text-sm font-bold text-white">
              {filtersActive ? "Bu filtreyle eşleşen sembol yok." : "Radar şu an sembol döndürmedi."}
            </p>
            <p className="text-xs text-bunker-muted">
              {filtersActive
                ? "Filtreleri temizleyip tüm taramayı görebilirsiniz."
                : "Bağlantı var; tarama listesi boş."}
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
                    <th className="py-3 px-2">RSI (5 dk)</th>
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
                          {c.news_info?.has_active_news && (
                            <span
                              className={`inline-flex items-center gap-1 mt-1 px-1.5 py-0.5 rounded text-[9px] font-bold border ${
                                c.news_info.alignment === "SUPPORTIVE"
                                  ? "bg-amber-500/15 text-amber-300 border-amber-500/30"
                                  : "bg-rose-500/15 text-rose-300 border-rose-500/30"
                              }`}
                              title={c.news_info.badge}
                            >
                              {c.news_info.alignment === "SUPPORTIVE" ? "🔥" : "⚠️"} {c.news_info.alignment === "SUPPORTIVE" ? "Haber Desteği" : "Zıt Yön Uyarısı"} ({c.news_info.remaining_min?.toFixed(0)}dk)
                            </span>
                          )}
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

                        <td className={`py-3.5 px-3 font-semibold text-[11px] whitespace-nowrap ${radarQuote(c).failed ? "text-rose-300" : "text-white"}`}>
                          {radarQuote(c).text}
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
                          {fmtRsi(c)}
                        </td>

                        <td className="py-3.5 px-3 whitespace-nowrap">
                          <span className="text-emerald-400 font-bold">{fmtTp(c.pip_target)}</span>
                          <span className="text-bunker-600"> / </span>
                          <span className="text-rose-400 font-bold">{fmtSl(c.stop_loss_pips)}</span>
                          <div className="text-[10px] text-bunker-muted">R/R {fmtRr(c.risk_reward)}</div>
                        </td>

                        <td className="py-3.5 px-3">
                          <div className="flex items-center gap-1.5">
                            <div className="w-12 bg-bunker-800 rounded-full h-1.5 overflow-hidden">
                              <div
                                className={`h-full rounded-full ${
                                  scorePassed(c) ? "bg-emerald-400" : "bg-blue-400"
                                }`}
                                style={{ width: `${Math.min(100, c.score)}%` }}
                              />
                            </div>
                            <span className={`font-bold ${scoreTone(c.score, optNum(c.required_score), scorePassed(c))}`}>
                              {c.score.toFixed(1)}
                            </span>
                          </div>
                          <div className="text-[10px] text-bunker-muted">eşik {optNum(c.required_score) ?? "—"}</div>
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
                      <span className={`font-bold text-xs ${radarQuote(c).failed ? "text-rose-300" : "text-white"}`}>
                        {radarQuote(c).text}
                      </span>
                      <span className="text-cyan-400 font-bold text-xs">{c.spread_pips}p</span>
                    </div>

                    <div className="grid grid-cols-4 gap-2 text-xs p-2 rounded-xl bg-bunker-950/70 border border-bunker-800/80">
                      <div>
                        <span className="text-[10px] text-bunker-muted block">SKOR</span>
                        <span className={`font-bold ${scoreTone(c.score, optNum(c.required_score), scorePassed(c))}`}>
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
                        <span className="text-[10px] text-bunker-muted block">RSI (5 dk)</span>
                        <span className="font-bold text-bunker-muted">{fmtRsi(c)}</span>
                      </div>
                    </div>

                    <div className="grid grid-cols-2 gap-2 text-xs">
                      <div>
                        <span className="text-[10px] text-bunker-muted block">Hedef (TP)</span>
                        <span className="text-emerald-400 font-bold">{fmtTp(c.pip_target)}</span>
                      </div>
                      <div className="text-right">
                        <span className="text-[10px] text-bunker-muted block">Stop (SL)</span>
                        <span className="text-rose-400 font-bold">{fmtSl(c.stop_loss_pips)}</span>
                      </div>
                    </div>

                    {c.primary_blocker && (
                      <div className="text-[10px] text-amber-300/90 p-2 rounded-lg bg-amber-950/20 border border-amber-500/20 leading-snug">
                        ⚠️ {c.blocker_text}
                      </div>
                    )}

                    <div className="flex items-center justify-between text-[11px] pt-1 border-t border-bunker-800/60">
                      <span className="text-bunker-muted">R/R {fmtRr(c.risk_reward)}</span>
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
            {calcRiskPct >= 10 && (
              <p className="mt-1 text-[10px] font-mono text-amber-300">
                Varsayılan risk %10. Tek işlemde bakiyenin büyük kısmı riske girer.
              </p>
            )}
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
              <option value="USDCHF">USD/CHF</option>
              <option value="AUDUSD">AUD/USD</option>
              <option value="USDCAD">USD/CAD</option>
              <option value="NZDUSD">NZD/USD</option>
              <option value="AUDCAD">AUD/CAD</option>
              <option value="GBPJPY">GBP/JPY</option>
              <option value="EURJPY">EUR/JPY</option>
              <option value="XAUUSD">XAU/USD (Altın)</option>
              <option value="BTCUSD">BTC/USD</option>
              <option value="NAS100">NAS100</option>
              <option value="US30">US30</option>
            </select>
          </div>
        </div>

        {calcError && (
          <p role="alert" className="font-mono text-xs text-rose-300">{calcError}</p>
        )}

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

      {/* PROFESYONEL FOREX GRAFİK MODALI (Lightweight Charts) */}
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
