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

function groupByDate(events: CalendarEvent[]) {
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
  for (const list of map.values()) {
    list.sort((a, b) => (Date.parse(a.date_iso) || 0) - (Date.parse(b.date_iso) || 0));
  }
  return Array.from(map.entries()).sort(([a], [b]) => a.localeCompare(b));
}

export default function ForexCalendarPage() {
  const [events, setEvents] = useState<CalendarEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [filterStars, setFilterStars] = useState<number | null>(null);
  const [showPast, setShowPast] = useState(false);

  const fetchNews = useCallback(async () => {
    try {
      const data = await apiFetch("/api/forex/news?refresh=1");
      setEvents(Array.isArray(data?.news) ? data.news : []);
      setError("");
    } catch (e) {
      const detail = e instanceof Error ? e.message : "";
      setError(detail ? `Takvim verisi alınamadı: ${detail}` : "Takvim verisi alınamadı");
    } finally {
      setLoading(false);
    }
  }, []);

  usePolling(fetchNews, 60_000);

  // Varsayılan: bugünden itibaren. Geçmiş günler "Geçmişi göster" ile açılır.
  const todayKey = trDayKey(Date.now());
  const visible = showPast
    ? events
    : events.filter((e) => !e.date_iso || trDayKey(Date.parse(e.date_iso) || 0) >= todayKey);
  const filtered = filterStars
    ? visible.filter((e) => (e.stars || (e.impact === "High" ? 3 : 2)) === filterStars)
    : visible;

  const grouped = groupByDate(filtered);

  const biasBadge = (dir?: string, conf?: number) => {
    if (dir === "BUY")
      return (
        <span className="px-1.5 py-0.5 rounded bg-emerald-500/20 border border-emerald-400/40 text-emerald-300 font-mono text-[10px] font-bold">
          AL {conf ? `· %${Math.round(conf * 100)}` : ""}
        </span>
      );
    if (dir === "SELL")
      return (
        <span className="px-1.5 py-0.5 rounded bg-rose-500/20 border border-rose-400/40 text-rose-300 font-mono text-[10px] font-bold">
          SAT {conf ? `· %${Math.round(conf * 100)}` : ""}
        </span>
      );
    return (
      <span className="px-1.5 py-0.5 rounded bg-bunker-800 border border-bunker-700 text-bunker-muted font-mono text-[10px]">
        NÖTR
      </span>
    );
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

  return (
    <div className="space-y-6 pb-12">
      {/* ÜST BAŞLIK — ana sayfa ile aynı gradyan kart */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 p-4 rounded-2xl bg-gradient-to-r from-blue-950/40 via-slate-900/60 to-indigo-950/40 border border-blue-500/20 backdrop-blur-md shadow-lg">
        <div className="flex items-center gap-3">
          <div className="w-12 h-12 rounded-xl bg-blue-500/20 border border-blue-400/40 flex items-center justify-center text-2xl shadow-[0_0_16px_rgba(59,130,246,0.3)]">
            📅
          </div>
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

        <div className="flex items-center gap-2 font-mono text-xs text-bunker-muted">
          <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
          <span>Canlı Makro Veri Akışı</span>
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
        <button
          type="button"
          onClick={() => setShowPast((v) => !v)}
          aria-pressed={showPast}
          className={`px-3 py-1.5 min-h-11 sm:min-h-0 rounded-lg border font-mono text-xs font-bold transition-all ${
            showPast
              ? "bg-blue-500/20 border-blue-400/60 text-blue-200"
              : "bg-bunker-800/80 border-bunker-700 text-bunker-muted hover:text-white"
          }`}
        >
          Geçmişi göster
        </button>
        <span className="ml-auto text-[11px] text-bunker-muted font-mono">
          {filtered.length} olay
        </span>
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
            onClick={() => { setLoading(true); void fetchNews(); }}
            className="px-4 py-1.5 rounded-lg bg-rose-500/20 border border-rose-400/40 font-bold text-xs"
          >
            Tekrar Dene
          </button>
        </div>
      )}

      {!loading && !error && filtered.length === 0 && (
        <div className="text-bunker-muted font-mono text-sm text-center py-12">
          Seçilen filtreye uygun olay bulunamadı.
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
                {dayEvents.map((ev) => (
                  <div
                    key={ev.id}
                    className={`flex flex-col sm:flex-row sm:items-center justify-between gap-2 p-3 rounded-xl border transition-all ${
                      ev.is_within_5m
                        ? "bg-amber-950/20 border-amber-500/40"
                        : ev.actual && ev.actual !== "—"
                        ? "bg-bunker-950/40 border-bunker-700"
                        : "bg-bunker-950/20 border-bunker-800 hover:border-bunker-700"
                    }`}
                  >
                    <div className="flex items-center gap-3 min-w-0">
                      <div className="shrink-0 w-9 h-9 rounded-lg bg-bunker-800 border border-bunker-700 flex items-center justify-center text-lg">
                        {getFlag(ev)}
                      </div>
                      <div className="min-w-0">
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className="font-mono text-sm font-bold text-white truncate">
                            {ev.title}
                          </span>
                          {starsBadge(ev.stars, ev.impact)}
                          {ev.is_within_5m && (
                            <span className="px-1.5 py-0.5 rounded bg-amber-500/20 border border-amber-400/40 text-amber-300 font-mono text-[10px] font-bold animate-pulse">
                              ⏳ 5 DK
                            </span>
                          )}
                          {ev.actual && ev.actual !== "—" && (
                            <span className="px-1.5 py-0.5 rounded bg-emerald-500/20 border border-emerald-400/40 text-emerald-300 font-mono text-[10px] font-bold">
                              ✓ AÇIKLANDI
                            </span>
                          )}
                        </div>
                        <div className="flex items-center gap-x-3 gap-y-1 text-[11px] text-bunker-muted font-mono mt-1 flex-wrap">
                          <span className="text-white/70 font-bold">{formatUtc3Time(ev.date_iso)}</span>
                          <span>Önceki: {ev.previous || "—"}</span>
                          <span>Beklenti: {ev.forecast || "—"}</span>
                          {ev.actual && ev.actual !== "—" && (
                            <>
                                  <span className="text-white font-bold">Açıklanan: {ev.actual}</span>
                            </>
                          )}
                        </div>
                      </div>
                    </div>

                    <div className="flex items-center gap-2 flex-wrap sm:justify-end">
                      {biasBadge(ev.bias_direction, ev.bias_confidence)}
                      {ev.affected_symbols && ev.affected_symbols.length > 0 && (
                        <span title={ev.affected_symbols.join(", ")} className="px-1.5 py-0.5 rounded bg-bunker-800 border border-bunker-700 text-bunker-muted font-mono text-[10px]">
                          {ev.affected_symbols.slice(0, 4).join(", ")}
                          {ev.affected_symbols.length > 4 ? ` +${ev.affected_symbols.length - 4}` : ""}
                        </span>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
