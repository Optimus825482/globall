"use client";

import React, { useEffect, useState, useMemo, useCallback } from "react";
import Link from "next/link";
import { apiFetch } from "../lib/api";

export interface TickerCalendarEvent {
  id: string;
  title: string;
  original_title?: string;
  country: string;
  currency?: string;
  country_name?: string;
  flag?: string;
  date_str: string;
  date_iso?: string;
  impact?: string;
  stars?: number;
  forecast?: string;
  previous?: string;
  actual?: string;
  status?: string;
  affected_symbols: string[];
}

export default function ForexEventTickerBanner() {
  const [events, setEvents] = useState<TickerCalendarEvent[]>([]);
  const [nowMs, setNowMs] = useState<number>(() => Date.now());

  // 1 saniyede bir saati güncelle (geri sayım akıcı olsun)
  useEffect(() => {
    const timer = setInterval(() => {
      setNowMs(Date.now());
    }, 1000);
    return () => clearInterval(timer);
  }, []);

  // 20 saniyede bir takvim verisini sessizce çek
  const fetchCalendar = useCallback(async () => {
    try {
      const res = await apiFetch("/api/forex/news").catch(() => null);
      if (res?.news && Array.isArray(res.news)) {
        setEvents(res.news);
      }
    } catch {
      // Sessiz hata yönetimi
    }
  }, []);

  useEffect(() => {
    fetchCalendar();
    const interval = setInterval(fetchCalendar, 20000);
    return () => clearInterval(interval);
  }, [fetchCalendar]);

  // Aktif penceredeki olayları filtrele:
  // Kural: Açıklanmadan 5 dk önce başlar (-5m), açıklandıktan sonra 10 dk daha devam eder (+10m)
  const activeEvents = useMemo(() => {
    if (!events.length) return [];

    return events.filter((ev) => {
      // Yalnız 2 ve 3 yıldızlı kritik olaylar
      const stars = ev.stars || (ev.impact === "High" ? 3 : 2);
      if (stars < 2) return false;

      if (!ev.date_iso) return false;

      try {
        const evTime = new Date(ev.date_iso).getTime();
        const diffMinutes = (evTime - nowMs) / 60000;

        // diffMinutes > 0: Gelecekte (açıklanmaya kalan dk)
        // diffMinutes < 0: Geçmişte (açıklanalı geçen dk)
        // Pencere: 5 dk kala başlar (diffMinutes <= 5.0) ve açıklandıktan sonra 10 dk sürer (diffMinutes >= -10.0)
        return diffMinutes <= 5.0 && diffMinutes >= -10.0;
      } catch {
        return false;
      }
    });
  }, [events, nowMs]);

  // Eğer bu zaman aralığında aktif bir olay yoksa bant hiç render edilmez (0 yer kaplar)
  if (activeEvents.length === 0) {
    return null;
  }

  // Marquee içinde gösterilecek öğeler
  const tickerItems = activeEvents.map((ev) => {
    const evTime = ev.date_iso ? new Date(ev.date_iso).getTime() : nowMs;
    const diffMinutes = (evTime - nowMs) / 60000;
    const isUpcoming = diffMinutes > 0;
    const symbols = ev.affected_symbols && ev.affected_symbols.length > 0
      ? ev.affected_symbols.join(", ")
      : "XAUUSD, EURUSD, BTCUSD";

    let timeText = "";
    if (isUpcoming) {
      const mins = Math.max(1, Math.ceil(diffMinutes));
      timeText = `${mins} dk içinde açıklanacak`;
    } else {
      const minsAgo = Math.max(0, Math.floor(Math.abs(diffMinutes)));
      timeText = minsAgo === 0 ? "Az önce açıklandı" : `${minsAgo} dk önce açıklandı`;
      if (ev.actual && ev.actual !== "—") {
        timeText += ` (Sonuç: ${ev.actual})`;
      }
    }

    return {
      id: ev.id,
      flag: ev.flag || "🌐",
      title: ev.title,
      isUpcoming,
      timeText,
      symbols,
    };
  });

  return (
    <div
      className="w-full bg-gradient-to-r from-red-600 via-rose-600 to-red-700 text-white border-b border-red-800 shadow-md overflow-hidden select-none z-30"
      style={{ minHeight: "34px" }}
    >
      <Link
        href="/forex/calendar"
        className="flex items-center h-8 sm:h-9 text-xs sm:text-[13px] font-mono font-bold tracking-tight text-white hover:text-amber-200 transition-colors cursor-pointer group"
        title="Detaylı takvimi ve senaryoları görmek için tıklayın"
      >
        {/* Sabit Sol Etiket (Sabit İkaz Rozeti) */}
        <div className="shrink-0 flex items-center gap-1.5 px-3 py-1 bg-red-900/90 border-r border-red-500/50 text-[11px] font-black uppercase tracking-wider z-10 shadow-md">
          <span className="animate-pulse">🚨</span>
          <span className="hidden xs:inline">KRİTİK VERİ ALARMI</span>
          <span className="xs:hidden">ALARM</span>
        </div>

        {/* Sağdan Sola Kayan Bant (Marquee Track) */}
        <div className="overflow-hidden whitespace-nowrap flex-1 flex items-center relative">
          <div className="animate-ticker flex items-center">
            {/* 1. Kopya */}
            <div className="flex items-center shrink-0 pr-10">
              {tickerItems.map((item, idx) => (
                <span key={`t1-${item.id}-${idx}`} className="inline-flex items-center gap-2 mr-8">
                  <span>{item.flag}</span>
                  <span className="underline decoration-red-300 font-extrabold">{item.title}</span>
                  <span className="px-1.5 py-0.2 rounded bg-black/30 text-amber-200 font-black text-[10px] sm:text-xs border border-amber-300/30">
                    {item.isUpcoming ? "⏳ " : "⚡ "}
                    {item.timeText}
                  </span>
                  <span className="text-white/95 font-medium">
                    · <strong className="text-yellow-200 font-black">ETKİLENECEK:</strong> [{item.symbols}]
                  </span>
                  <span className="text-amber-200/90 text-[11px] hidden sm:inline">
                    · (Yüksek volatilite ve spread riskine dikkat!)
                  </span>
                  <span className="text-red-300/80 mx-2">✦</span>
                </span>
              ))}
            </div>

            {/* 2. Kopya (Kesintisiz döngü için) */}
            <div className="flex items-center shrink-0 pr-10" aria-hidden="true">
              {tickerItems.map((item, idx) => (
                <span key={`t2-${item.id}-${idx}`} className="inline-flex items-center gap-2 mr-8">
                  <span>{item.flag}</span>
                  <span className="underline decoration-red-300 font-extrabold">{item.title}</span>
                  <span className="px-1.5 py-0.2 rounded bg-black/30 text-amber-200 font-black text-[10px] sm:text-xs border border-amber-300/30">
                    {item.isUpcoming ? "⏳ " : "⚡ "}
                    {item.timeText}
                  </span>
                  <span className="text-white/95 font-medium">
                    · <strong className="text-yellow-200 font-black">ETKİLENECEK:</strong> [{item.symbols}]
                  </span>
                  <span className="text-amber-200/90 text-[11px] hidden sm:inline">
                    · (Yüksek volatilite ve spread riskine dikkat!)
                  </span>
                  <span className="text-red-300/80 mx-2">✦</span>
                </span>
              ))}
            </div>
          </div>
        </div>
      </Link>
    </div>
  );
}
