"use client";

import React, { useCallback, useState } from "react";
import { apiFetch } from "../../lib/api";
import { usePolling } from "../../lib/usePolling";

interface CalendarEvent {
  id: string;
  title: string;
  currency: string;
  country: string;
  date_iso: string;
  time_str: string;
  forecast?: string;
  previous?: string;
  actual?: string;
  stars?: number;
  impact?: string;
  affected_symbols?: string[];
  is_within_5m?: boolean;
  bias_direction?: "BUY" | "SELL" | "NEUTRAL";
  bias_confidence?: number;
  bias_explanation?: string;
  /** Backend `evaluate_event_outcome` sonucu (ana sayfa da aynı alanı okur). */
  outcome?: {
    side?: "bullish" | "bearish" | null;
    basis?: "forecast" | "previous" | null;
    comparison_tr?: string | null;
    label_tr?: string | null;
    direction_note_tr?: string | null;
  } | null;
  /** Para birimi yönünün paritelere çevrilmiş hali (backend `pair_impacts`). */
  pair_impacts?: Array<{ symbol: string; direction: number }>;
  /** "Ne olursa ne olur" senaryosu (backend `generate_event_scenario`). */
  scenario?: {
    bullish_trigger?: string;
    bullish_outcome?: string;
    bearish_trigger?: string;
    bearish_outcome?: string;
    scalper_tip?: string;
  } | null;
}

// API `country` alanında ülke değil para birimi kodu (JPY, USD…) geliyor;
// bu yüzden her iki anahtar türü de eşlenir.
const FLAG_MAP: Record<string, string> = {
  US: "🇺🇸", USD: "🇺🇸", EU: "🇪🇺", EUR: "🇪🇺", GB: "🇬🇧", GBP: "🇬🇧",
  JP: "🇯🇵", JPY: "🇯🇵", CA: "🇨🇦", CAD: "🇨🇦", AU: "🇦🇺", AUD: "🇦🇺",
  NZ: "🇳🇿", NZD: "🇳🇿", CH: "🇨🇭", CHF: "🇨🇭", CN: "🇨🇳", CNY: "🇨🇳",
};

function getFlag(ev: CalendarEvent) {
  return FLAG_MAP[ev.currency] || FLAG_MAP[ev.country] || "🌐";
}

/** UTC+3 (TR) gün anahtarı: YYYY-MM-DD. */
function trDayKey(ms: number) {
  return new Date(ms + 3 * 3600 * 1000).toISOString().slice(0, 10);
}

function dayHeading(dayKey: string) {
  const today = trDayKey(Date.now());
  const tomorrow = trDayKey(Date.now() + 24 * 3600 * 1000);
  const long = new Date(dayKey + "T00:00:00").toLocaleDateString("tr-TR", {
    weekday: "long", day: "numeric", month: "long",
  });
  if (dayKey === today) return `BUGÜN · ${long}`;
  if (dayKey === tomorrow) return `YARIN · ${long}`;
  return long;
}

function formatUtc3Time(dateIso: string) {
  try {
    const d = new Date(dateIso);
    const tr = new Date(d.getTime() + 3 * 3600 * 1000);
    return `${String(tr.getUTCHours()).padStart(2, "0")}:${String(tr.getUTCMinutes()).padStart(2, "0")}`;
  } catch {
    return "--:--";
  }
}

function groupByDate(events: CalendarEvent[], newestFirst = false) {
  const map = new Map<string, CalendarEvent[]>();
  for (const ev of events) {
    let key = "Tarihsiz";
    if (ev.date_iso) {
      // UTC+3 gün anahtarı (saat dilimi tutarlılığı)
      try {
        const tr = new Date(new Date(ev.date_iso).getTime() + 3 * 3600 * 1000);
        key = tr.toISOString().slice(0, 10);
      } catch { /* Tarihsiz */ }
    }
    if (!map.has(key)) map.set(key, []);
    map.get(key)!.push(ev);
  }
  // Gün içinde saat sırası (API sırası saat sırasını garanti etmiyor).
  // Açıklananlar sekmesi: en yeni üstte; Bekleyenler: ilk açıklanacak üstte.
  const dir = newestFirst ? -1 : 1;
  for (const list of map.values()) {
    list.sort((a, b) => dir * ((Date.parse(a.date_iso) || 0) - (Date.parse(b.date_iso) || 0)));
  }
  return Array.from(map.entries()).sort(([a], [b]) => dir * a.localeCompare(b));
}

export default function ForexCalendarPage() {
  const [events, setEvents] = useState<CalendarEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [filterStars, setFilterStars] = useState<number | null>(null);
  // Varsayılan sekme: açıklananlar (en yeni üstte).
  const [tab, setTab] = useState<"released" | "pending">("released");
  // "" = bugünden itibaren · "ALL" = tüm günler · "YYYY-MM-DD" = tek gün
  const [dayFilter, setDayFilter] = useState<string>("");
  const [openIds, setOpenIds] = useState<Set<string>>(new Set());
  const toggleOpen = (id: string) =>
    setOpenIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  // Sayfa açılışı ve 60 sn'lik yoklama veritabanı/bellek önbelleğinden okur
  // (anında). Sağlayıcılardan (TradingView/Investing) çekim yalnız "Kaynağı
  // yenile" ile tetiklenir — eskiden `?refresh=1` her açılışta ve dakikada bir
  // dış siteleri bekletiyordu.
  const fetchNews = useCallback(async (forceRefresh = false) => {
    try {
      const data = await apiFetch(forceRefresh ? "/api/forex/news?refresh=1" : "/api/forex/news");
      setEvents(Array.isArray(data?.news) ? data.news : []);
      setLastUpdated(new Date());
      setError("");
    } catch (e) {
      const detail = e instanceof Error ? e.message : "";
      setError(detail ? `Takvim verisi alınamadı: ${detail}` : "Takvim verisi alınamadı");
    } finally {
      setLoading(false);
    }
  }, []);

  const [refreshing, setRefreshing] = useState(false);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const refreshSource = async () => {
    setRefreshing(true);
    try {
      await fetchNews(true);
    } finally {
      setRefreshing(false);
    }
  };

  usePolling(() => fetchNews(false), 60_000);

  const todayKey = trDayKey(Date.now());
  const evDay = (e: CalendarEvent) => (e.date_iso ? trDayKey(Date.parse(e.date_iso) || 0) : "");
  const dayKeys = events.map(evDay).filter(Boolean).sort();
  const minDay = dayKeys[0] || todayKey;
  const maxDay = dayKeys[dayKeys.length - 1] || todayKey;
  const visible =
    dayFilter === "ALL"
      ? events
      : dayFilter
      ? events.filter((e) => evDay(e) === dayFilter)
      : events.filter((e) => !e.date_iso || evDay(e) >= todayKey);
  // Oklar olaylı bir sonraki/önceki güne atlar (hafta sonu gibi boş günlerde
  // takılmaz); o yönde olaylı gün yoksa tek gün kayar.
  const uniqueDays = Array.from(new Set(dayKeys));
  const shiftDay = (delta: number) =>
    setDayFilter((cur) => {
      const base = cur && cur !== "ALL" ? cur : todayKey;
      const next =
        delta > 0
          ? uniqueDays.find((d) => d > base)
          : [...uniqueDays].reverse().find((d) => d < base);
      if (next) return next;
      const d = new Date(base + "T00:00:00Z");
      d.setUTCDate(d.getUTCDate() + delta);
      return d.toISOString().slice(0, 10);
    });
  const filtered = filterStars
    ? visible.filter((e) => (e.stars || (e.impact === "High" ? 3 : 2)) === filterStars)
    : visible;

  const isReleased = (e: CalendarEvent) => !!e.actual && e.actual !== "—";
  const releasedCount = filtered.filter(isReleased).length;
  const pendingCount = filtered.length - releasedCount;
  const tabbed = filtered.filter((e) => (tab === "released") === isReleased(e));
  const grouped = groupByDate(tabbed, tab === "released");

  const biasBadge = (dir?: string, conf?: number) => {
    if (dir === "BUY")
      return (
        <span className="px-1.5 py-0.5 rounded bg-emerald-500/20 border border-emerald-400/40 text-emerald-300 font-mono text-[10px] font-bold">
          BUY {conf ? `· %${Math.round(conf * 100)}` : ""}
        </span>
      );
    if (dir === "SELL")
      return (
        <span className="px-1.5 py-0.5 rounded bg-rose-500/20 border border-rose-400/40 text-rose-300 font-mono text-[10px] font-bold">
          SELL {conf ? `· %${Math.round(conf * 100)}` : ""}
        </span>
      );
    return null;
  };

  const starsBadge = (stars?: number, impact?: string) => {
    const s = stars || (impact === "High" ? 3 : 2);
    if (s >= 3)
      return (
        <span className="px-1 py-0.5 rounded bg-red-500/20 border border-red-400/40 text-red-300 font-mono text-[10px] font-bold">
          ⭐⭐⭐
        </span>
      );
    if (s === 2)
      return (
        <span className="px-1 py-0.5 rounded bg-amber-500/20 border border-amber-400/40 text-amber-300 font-mono text-[10px] font-bold">
          ⭐⭐
        </span>
      );
    return (
      <span className="px-1 py-0.5 rounded bg-bunker-800 border border-bunker-700 text-bunker-muted font-mono text-[10px]">
        ⭐
      </span>
    );
  };

  const resultBadge = (
    released: boolean,
    o: CalendarEvent["outcome"],
    cur: string
  ) => {
    const base = "px-2 py-0.5 rounded border font-mono text-[10px] font-bold whitespace-nowrap";
    if (!released)
      return <span className={`${base} bg-bunker-800 border-bunker-700 text-bunker-muted`}>BEKLENİYOR</span>;
    if (!o)
      return (
        <span title="Değer beklenti/önceki ile kıyaslanamadı" className={`${base} bg-bunker-800 border-bunker-700 text-bunker-muted`}>
          YORUMSUZ
        </span>
      );
    if (o.side === "bullish")
      return <span className={`${base} bg-emerald-500/20 border-emerald-400/40 text-emerald-300`}>{cur} GÜÇLÜ ▲</span>;
    if (o.side === "bearish")
      return <span className={`${base} bg-rose-500/20 border-rose-400/40 text-rose-300`}>{cur} ZAYIF ▼</span>;
    return <span className={`${base} bg-bunker-800 border-bunker-700 text-bunker-muted`}>BEKLENTİYE UYGUN</span>;
  };

  return (
    <div className="space-y-6 pb-12">
      {/* ÜST BAŞLIK — ana sayfa ile aynı gradyan kart */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 ">
        <div className="flex items-center gap-3">
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-xl font-bold font-mono text-white tracking-tight">
                KÜRESEL EKONOMİK TAKVİM
              </h1>
              <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-blue-500/20 text-blue-300 border border-blue-400/30">
                BIAS AKTİF
              </span>
            </div>
            <p className="text-xs text-bunker-muted font-mono mt-0.5">
              Faiz Kararları, Enflasyon (TÜFE/CPI), İstihdam (NFP) ve Merkez Bankası Duyuruları — Otonom işlemlere yön katkısı
            </p>
          </div>
        </div>

        <div className="flex items-center gap-3 font-mono text-xs text-bunker-muted">
          <span className="flex items-center gap-1.5" aria-live="polite">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" aria-hidden />
            {lastUpdated ? `Güncellendi ${lastUpdated.toLocaleTimeString("tr-TR", { hour: "2-digit", minute: "2-digit" })}` : "Yükleniyor…"}
          </span>
          <button
            type="button"
            onClick={() => void refreshSource()}
            disabled={refreshing}
            title="TradingView ve Investing.com'dan taze veri çeker (birkaç saniye sürebilir)"
            className="px-3 py-1.5 min-h-11 sm:min-h-0 rounded-lg border border-bunker-700 bg-bunker-800/80 text-white font-bold hover:border-blue-400/60 disabled:opacity-50 transition-colors"
          >
            {refreshing ? "Çekiliyor…" : "Kaynağı yenile"}
          </button>
        </div>
      </div>

      {/* FİLTRELER */}
      <div className="flex items-center gap-2 flex-wrap">
        <button
          onClick={() => setFilterStars(null)}
          className={`px-3 py-1.5 min-h-11 sm:min-h-0 rounded-lg border font-mono text-xs font-bold transition-all ${
            filterStars === null
              ? "bg-blue-500/20 border-blue-400/60 text-blue-200"
              : "bg-bunker-800/80 border-bunker-700 text-bunker-muted hover:text-white"
          }`}
        >
          TÜMÜ
        </button>
        <button
          onClick={() => setFilterStars(3)}
          className={`px-3 py-1.5 min-h-11 sm:min-h-0 rounded-lg border font-mono text-xs font-bold transition-all ${
            filterStars === 3
              ? "bg-red-500/20 border-red-400/60 text-red-200"
              : "bg-bunker-800/80 border-bunker-700 text-bunker-muted hover:text-white"
          }`}
        >
          ⭐⭐⭐ Yüksek
        </button>
        <button
          onClick={() => setFilterStars(2)}
          className={`px-3 py-1.5 min-h-11 sm:min-h-0 rounded-lg border font-mono text-xs font-bold transition-all ${
            filterStars === 2
              ? "bg-amber-500/20 border-amber-400/60 text-amber-200"
              : "bg-bunker-800/80 border-bunker-700 text-bunker-muted hover:text-white"
          }`}
        >
          ⭐⭐ Orta
        </button>
        <div className="flex items-center gap-1.5" role="group" aria-label="Gün seçici">
          <button
            type="button"
            onClick={() => shiftDay(-1)}
            aria-label="Önceki gün"
            className="px-3 py-1.5 min-h-11 sm:min-h-0 rounded-lg border font-mono text-xs font-bold bg-bunker-800/80 border-bunker-700 text-bunker-muted hover:text-white"
          >
            ◀
          </button>
          <input
            type="date"
            value={dayFilter && dayFilter !== "ALL" ? dayFilter : todayKey}
            min={minDay}
            max={maxDay}
            onChange={(e) => setDayFilter(e.target.value || "")}
            aria-label="Gün seç"
            className="px-2 py-1.5 min-h-11 sm:min-h-0 rounded-lg border bg-bunker-950 border-bunker-700 text-white font-mono text-xs font-bold"
          />
          <button
            type="button"
            onClick={() => shiftDay(1)}
            aria-label="Sonraki gün"
            className="px-3 py-1.5 min-h-11 sm:min-h-0 rounded-lg border font-mono text-xs font-bold bg-bunker-800/80 border-bunker-700 text-bunker-muted hover:text-white"
          >
            ▶
          </button>
        </div>
        <button
          type="button"
          onClick={() => setDayFilter("")}
          aria-pressed={dayFilter === ""}
          className={`px-3 py-1.5 min-h-11 sm:min-h-0 rounded-lg border font-mono text-xs font-bold transition-all ${dayFilter === "" ? "bg-blue-500/20 border-blue-400/60 text-blue-200" : "bg-bunker-800/80 border-bunker-700 text-bunker-muted hover:text-white"}`}
        >
          Bugünden itibaren
        </button>
        <button
          type="button"
          onClick={() => setDayFilter("ALL")}
          aria-pressed={dayFilter === "ALL"}
          className={`px-3 py-1.5 min-h-11 sm:min-h-0 rounded-lg border font-mono text-xs font-bold transition-all ${dayFilter === "ALL" ? "bg-blue-500/20 border-blue-400/60 text-blue-200" : "bg-bunker-800/80 border-bunker-700 text-bunker-muted hover:text-white"}`}
        >
          Tüm günler
        </button>
        <span className="ml-auto text-[11px] text-bunker-muted font-mono">
          {tabbed.length} olay
        </span>
      </div>

      {/* SEKMELER: Açıklananlar (varsayılan) / Bekleyenler */}
      <div role="tablist" aria-label="Takvim görünümü" className="flex gap-2">
        {([
          ["released", "Açıklananlar", releasedCount],
          ["pending", "Bekleyenler", pendingCount],
        ] as const).map(([key, label, count]) => (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={tab === key}
            onClick={() => setTab(key)}
            className={`px-4 py-2 min-h-11 sm:min-h-0 rounded-lg border font-mono text-xs font-bold transition-all ${
              tab === key
                ? "bg-blue-500/20 border-blue-400/60 text-blue-200"
                : "bg-bunker-800/80 border-bunker-700 text-bunker-muted hover:text-white"
            }`}
          >
            {label} <span className="opacity-70">({count})</span>
          </button>
        ))}
      </div>

      {/* YÜKLENİYOR / HATA */}
      {loading && (
        <div className="flex items-center gap-2 text-bunker-muted font-mono text-xs py-8 justify-center">
          <span className="inline-block w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin" />
          Takvim verileri yükleniyor…
        </div>
      )}

      {error && (
        <div role="alert" className="p-4 rounded-xl bg-rose-500/10 border border-rose-500/30 text-rose-300 font-mono text-sm text-center space-y-3">
          <p>{error}</p>
          <button
            type="button"
            onClick={() => { setLoading(true); void fetchNews(false); }}
            className="px-4 py-1.5 rounded-lg bg-rose-500/20 border border-rose-400/40 font-bold text-xs"
          >
            Tekrar Dene
          </button>
        </div>
      )}

      {!loading && !error && tabbed.length === 0 && (
        <div className="text-bunker-muted font-mono text-sm text-center py-12">
          {dayFilter && dayFilter !== "ALL"
            ? `${dayHeading(dayFilter)} için bu sekmede olay yok.`
            : tab === "released"
            ? "Seçilen aralıkta açıklanmış veri yok."
            : "Seçilen aralıkta bekleyen veri yok."}
        </div>
      )}

      {/* TAKVİM LİSTESİ — günlük gruplar */}
      <div className="space-y-6">
        {grouped.map(([dateStr, dayEvents]) => {
          const dateLabel = dayHeading(dateStr);
          return (
            <div key={dateStr} className="space-y-2">
              <div className="flex items-center gap-3">
                <div className="h-px flex-1 bg-bunker-800" />
                <span className="font-mono text-xs font-bold text-bunker-muted uppercase tracking-wider">
                  {dateLabel}
                </span>
                <div className="h-px flex-1 bg-bunker-800" />
              </div>

              <div className="space-y-2">
                {dayEvents.map((ev) => {
                  const released = !!ev.actual && ev.actual !== "—";
                  const isOpen = openIds.has(ev.id);
                  const o = ev.outcome;
                  const cur = (ev.currency || "").toUpperCase();
                  const pairs = ev.pair_impacts || [];
                  return (
                    <div
                      key={ev.id}
                      className={`rounded-xl border transition-all ${
                        ev.is_within_5m
                          ? "bg-amber-950/20 border-amber-500/40"
                          : released
                          ? "bg-bunker-950/40 border-bunker-700"
                          : "bg-bunker-950/20 border-bunker-800 hover:border-bunker-700"
                      }`}
                    >
                      <div
                        role="button"
                        tabIndex={0}
                        aria-expanded={isOpen}
                        onClick={() => toggleOpen(ev.id)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter" || e.key === " ") {
                            e.preventDefault();
                            toggleOpen(ev.id);
                          }
                        }}
                        className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 p-3 min-h-11 cursor-pointer rounded-xl focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-400"
                      >
                        <div className="flex items-center gap-3 min-w-0">
                          <div className="shrink-0 w-9 h-9 rounded-lg bg-bunker-800 border border-bunker-700 flex items-center justify-center text-lg">
                            {getFlag(ev)}
                          </div>
                          <div className="min-w-0">
                            <div className="flex items-center gap-2 flex-wrap">
                              <span className="font-mono text-sm font-bold text-white">{ev.title}</span>
                              {starsBadge(ev.stars, ev.impact)}
                              {ev.is_within_5m && (
                                <span className="px-1.5 py-0.5 rounded bg-amber-500/20 border border-amber-400/40 text-amber-300 font-mono text-[10px] font-bold animate-pulse">
                                  ⏳ 5 DK
                                </span>
                              )}
                              {released && (
                                <span className="px-1.5 py-0.5 rounded bg-emerald-500/20 border border-emerald-400/40 text-emerald-300 font-mono text-[10px] font-bold">
                                  ✓ AÇIKLANDI
                                </span>
                              )}
                            </div>
                            <div className="flex items-center gap-x-3 gap-y-1 text-[11px] text-bunker-muted font-mono mt-1 flex-wrap">
                              <span className="text-white/70 font-bold">{formatUtc3Time(ev.date_iso)}</span>
                              <span>Önceki: {ev.previous || "—"}</span>
                              <span>Beklenti: {ev.forecast || "—"}</span>
                              {released && <span className="text-white font-bold">Açıklanan: {ev.actual}</span>}
                            </div>
                          </div>
                        </div>

                        <div className="flex items-center gap-2 flex-wrap sm:justify-end">
                          {resultBadge(released, o, cur)}
                          {biasBadge(ev.bias_direction, ev.bias_confidence)}
                          <span aria-hidden className={`text-bunker-muted text-xs transition-transform ${isOpen ? "rotate-90" : ""}`}>▶</span>
                        </div>
                      </div>

                      {isOpen && (
                        <div className="border-t border-bunker-800 px-3 py-3 space-y-3 font-mono text-xs">
                          {released && o ? (
                            <>
                              <div className="flex items-center gap-2 flex-wrap">
                                <span className="text-bunker-muted">Sonuç:</span>
                                <span className="text-white font-bold">{o.comparison_tr || o.label_tr}</span>
                              </div>
                              <p className="text-white/90">
                                {o.side === "bullish"
                                  ? `${cur} için olumlu: veri para birimini güçlendirir.`
                                  : o.side === "bearish"
                                  ? `${cur} için olumsuz: veri para birimini zayıflatır.`
                                  : "Veri beklentiyle aynı: belirgin bir yön yok."}
                              </p>
                              {o.direction_note_tr && <p className="text-amber-300">{o.direction_note_tr}</p>}
                              {pairs.length > 0 && (
                                <div className="space-y-1.5">
                                  <span className="text-bunker-muted">Parite etkisi:</span>
                                  <div className="flex flex-wrap gap-1.5">
                                    {pairs.map((pr) => (
                                      <span
                                        key={pr.symbol}
                                        className={`px-2 py-1 rounded border text-[11px] font-bold ${
                                          pr.direction > 0
                                            ? "bg-emerald-500/15 border-emerald-400/40 text-emerald-300"
                                            : pr.direction < 0
                                            ? "bg-rose-500/15 border-rose-400/40 text-rose-300"
                                            : "bg-bunker-800 border-bunker-700 text-bunker-muted"
                                        }`}
                                      >
                                        {pr.symbol} {pr.direction > 0 ? "▲ BUY" : pr.direction < 0 ? "▼ SELL" : "— belirsiz"}
                                      </span>
                                    ))}
                                  </div>
                                </div>
                              )}
                              <p className="text-[10px] text-bunker-muted">
                                Kıyas tabanı: {o.basis === "forecast" ? "beklenti" : "önceki değer"}. Bilgi amaçlıdır, işlem emri değildir.
                              </p>
                            </>
                          ) : released ? (
                            <p className="text-bunker-muted">
                              Açıklanan değer ({ev.actual}) beklenti veya önceki değerle karşılaştırılamadı (birim farkı ya da değer yok), bu yüzden yön verilmiyor.
                            </p>
                          ) : (
                            <div className="space-y-2.5">
                              <p className="text-bunker-muted">
                                Henüz açıklanmadı. Açıklanınca sonuç ve parite yönleri burada görünür.
                              </p>
                              {ev.scenario && (ev.scenario.bullish_outcome || ev.scenario.bearish_outcome) && (
                                <div className="grid gap-2 sm:grid-cols-2">
                                  {ev.scenario.bullish_outcome && (
                                    <div className="rounded-lg border border-emerald-400/30 bg-emerald-500/10 p-2.5">
                                      <p className="font-bold text-emerald-300">{ev.scenario.bullish_trigger || "Beklenti üzeri gelirse"}</p>
                                      <p className="mt-1 text-white/90">{ev.scenario.bullish_outcome}</p>
                                    </div>
                                  )}
                                  {ev.scenario.bearish_outcome && (
                                    <div className="rounded-lg border border-rose-400/30 bg-rose-500/10 p-2.5">
                                      <p className="font-bold text-rose-300">{ev.scenario.bearish_trigger || "Beklenti altı kalırsa"}</p>
                                      <p className="mt-1 text-white/90">{ev.scenario.bearish_outcome}</p>
                                    </div>
                                  )}
                                </div>
                              )}
                              {ev.scenario?.scalper_tip && (
                                <p className="text-amber-300">{ev.scenario.scalper_tip}</p>
                              )}
                            </div>
                          )}
                          {ev.bias_direction && ev.bias_direction !== "NEUTRAL" && ev.bias_explanation && (
                            <p className="text-blue-300">İşlem motoru: {ev.bias_explanation}</p>
                          )}
                          {ev.affected_symbols && ev.affected_symbols.length > 0 && (
                            <div className="text-[11px] text-bunker-muted">
                              Etkilenen semboller: {ev.affected_symbols.join(", ")}
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
