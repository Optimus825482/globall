"use client";

// ============================================================================
// UYGULAMA İÇİ EKONOMİK TAKVİM 5 DAKİKA KALA UYARI MODALI (POPUP)
// Investing.com 2 ve 3 Yıldızlı Olaylar açıklanmadan 5 dakika önce:
// - Sesli ve görsel dikkat çekici uyarı verir
// - Etkilenecek sembolleri (XAUUSD, EURUSD, USDJPY, USOIL...) listeler
// - Beklenti üstü/altı olası yön senaryolarını özetler
// ============================================================================

import React, { useEffect, useState, useRef, useCallback } from "react";
import Link from "next/link";
import { apiFetch } from "../../lib/api";
import {
  getInAppNotificationSettings,
  InAppNotificationSettings,
} from "../../lib/notificationSettings";

export interface CalendarEventAlert {
  id: string;
  title: string;
  original_title?: string;
  country: string;
  currency?: string;
  country_name?: string;
  flag?: string;
  date_str: string;
  date_iso?: string;
  impact: string;
  stars?: number;
  stars_str?: string;
  impact_label?: string;
  forecast?: string;
  previous?: string;
  actual?: string;
  status?: string;
  minutes_until?: number;
  is_within_5m?: boolean;
  affected_symbols: string[];
  scenario?: {
    title?: string;
    bullish_trigger?: string;
    bullish_outcome?: string;
    bearish_trigger?: string;
    bearish_outcome?: string;
    scalper_tip?: string;
    summary_short?: string;
  };
}

/**
// Zarif 3-tonlu makro takvim sesli uyarısı (660Hz -> 880Hz -> 1100Hz)
*/
export function playCalendarAlertSound() {
  try {
    const AudioContextClass = window.AudioContext || (window as any).webkitAudioContext;
    if (!AudioContextClass) return;
    const ctx = new AudioContextClass();
    const now = ctx.currentTime;
    const freqs = [660, 880, 1100];
    freqs.forEach((freq, idx) => {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = "sine";
      const start = now + idx * 0.12;
      osc.frequency.setValueAtTime(freq, start);
      gain.gain.setValueAtTime(0.001, start);
      gain.gain.linearRampToValueAtTime(0.18, start + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.001, start + 0.22);
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.start(start);
      osc.stop(start + 0.23);
    });
  } catch {}
}

export default function ForexCalendarAlertModal() {
  const [activeAlert, setActiveAlert] = useState<CalendarEventAlert | null>(null);
  const [notifSettings, setNotifSettings] = useState<InAppNotificationSettings>(() =>
    getInAppNotificationSettings()
  );
  const notifiedIdsRef = useRef<Set<string>>(new Set());

  // Ayar değişikliklerini ve test tetikleyicisini dinle
  useEffect(() => {
    const handleSettingsChanged = (e: any) => {
      if (e?.detail) {
        setNotifSettings(e.detail);
      } else {
        setNotifSettings(getInAppNotificationSettings());
      }
    };

    const handleTestModal = () => {
      // Örnek 5 dakika test uyarısı
      const sampleEvent: CalendarEventAlert = {
        id: "test-us-cpi-5m",
        title: "ABD TÜFE Enflasyon Verisi (CPI)",
        original_title: "US CPI m/m & y/y",
        country: "USD",
        currency: "USD",
        country_name: "ABD",
        flag: "🇺🇸",
        date_str: "5 Dakika İçinde (15:30)",
        date_iso: new Date(Date.now() + 5 * 60 * 1000).toISOString(),
        impact: "High",
        stars: 3,
        stars_str: "⭐⭐⭐",
        impact_label: "⭐⭐⭐ YÜKSEK (3 Yıldız)",
        forecast: "0.2%",
        previous: "0.3%",
        minutes_until: 5.0,
        is_within_5m: true,
        affected_symbols: ["XAUUSD", "EURUSD", "BTCUSD", "USDJPY", "GBPUSD"],
        scenario: {
          title: "ABD Enflasyon Senaryosu",
          bullish_trigger: "TÜFE Beklentiden Yüksek Gelirse (> 0.2%)",
          bullish_outcome: "Dolar (DXY) sert yükselir. Altın (XAUUSD), EURUSD ve BTCUSD düşüşe geçer.",
          bearish_trigger: "TÜFE Beklentiden Düşük Gelirse (< 0.2%)",
          bearish_outcome: "Dolar değer kaybeder. Altın (XAUUSD) ve EURUSD yukarı fırlar, Kripto prim yapar.",
          scalper_tip: "Açıklanma anında yüksek spread ve fitil oluşur. İlk 30 saniye yönün oturmasını bekleyin.",
          summary_short: "Sıcak Enflasyon: Dolar↑ / Altın↓ | Soğuk Enflasyon: Altın↑ / Dolar↓",
        },
      };

      setActiveAlert(sampleEvent);
      const current = getInAppNotificationSettings();
      if (current.soundEnabled) {
        playCalendarAlertSound();
      }
    };

    window.addEventListener("scalper_in_app_settings_changed", handleSettingsChanged);
    window.addEventListener("scalper_test_calendar_modal", handleTestModal);

    return () => {
      window.removeEventListener("scalper_in_app_settings_changed", handleSettingsChanged);
      window.removeEventListener("scalper_test_calendar_modal", handleTestModal);
    };
  }, []);

  // 15 saniyede bir yaklaşan 5 dakika olaylarını kontrol et
  const checkApproachingEvents = useCallback(async () => {
    if (!notifSettings.enabled) return;

    try {
      const res = await apiFetch("/api/forex/news").catch(() => null);
      if (!res?.news || !Array.isArray(res.news)) return;

      const nowMs = Date.now();

      for (const item of res.news) {
        const stars = item.stars || (item.impact === "High" ? 3 : 2);
        // Yalnızca 2 ve 3 Yıldızlı Olaylar
        if (stars < 2) continue;

        let isWithin5m = Boolean(item.is_within_5m);

        if (!isWithin5m && item.date_iso) {
          try {
            const evTime = new Date(item.date_iso).getTime();
            const diffMinutes = (evTime - nowMs) / 60000;
            if (diffMinutes > 0 && diffMinutes <= 5.5) {
              isWithin5m = true;
            }
          } catch {}
        }

        if (isWithin5m && !notifiedIdsRef.current.has(item.id)) {
          notifiedIdsRef.current.add(item.id);
          setActiveAlert(item);

          if (notifSettings.soundEnabled) {
            playCalendarAlertSound();
          }

          // Tarayıcı web bildirimi
          if (
            typeof window !== "undefined" &&
            "Notification" in window &&
            Notification.permission === "granted"
          ) {
            try {
              new Notification(`⏰ 5 Dk Kaldı: ${item.title}`, {
                body: `Etkilenecek Pariteler: ${item.affected_symbols.join(", ")}\nBeklenti: ${item.forecast || "—"}`,
                icon: "/icon.svg",
              });
            } catch {}
          }

          break; // Aynı anda 1 bildirim göster
        }
      }
    } catch {}
  }, [notifSettings]);

  useEffect(() => {
    checkApproachingEvents();
    const interval = setInterval(() => {
      if (!document.hidden) {
        checkApproachingEvents();
      }
    }, 15000);
    return () => clearInterval(interval);
  }, [checkApproachingEvents]);

  // Manuel veya otomatik kapatma
  const handleClose = useCallback(() => {
    setActiveAlert(null);
  }, []);

  // Otomatik kapanma zamanlayıcısı
  useEffect(() => {
    if (!activeAlert || notifSettings.autoCloseSec <= 0) return;
    const timer = setTimeout(() => {
      setActiveAlert(null);
    }, notifSettings.autoCloseSec * 1000);
    return () => clearTimeout(timer);
  }, [activeAlert, notifSettings.autoCloseSec]);

  if (!activeAlert) return null;

  const is3Stars = (activeAlert.stars || (activeAlert.impact === "High" ? 3 : 2)) === 3;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-3 sm:p-4 bg-black/80 backdrop-blur-md animate-in fade-in duration-200"
      onClick={handleClose}
      role="dialog"
      aria-modal="true"
    >
      <div
        className={`w-full max-w-xl rounded-2xl border bg-bunker-950 p-5 sm:p-6 shadow-[0_0_50px_rgba(0,0,0,0.8)] space-y-4.5 animate-in zoom-in-95 duration-200 ${
          is3Stars
            ? "border-rose-500/60 shadow-[0_0_35px_rgba(244,63,94,0.3)] ring-2 ring-rose-500/30"
            : "border-amber-500/60 shadow-[0_0_35px_rgba(245,158,11,0.3)] ring-2 ring-amber-500/30"
        }`}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Üst Acil Durum Başlığı */}
        <div className="flex items-start justify-between gap-3 border-b border-bunker-800 pb-3.5">
          <div className="space-y-1">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="w-2.5 h-2.5 rounded-full bg-rose-500 animate-ping" />
              <span className="px-2 py-0.5 rounded text-[10px] font-black tracking-wider uppercase bg-rose-500/20 text-rose-300 border border-rose-500/40">
                ⏰ 5 DAKİKA KALDI
              </span>
              <span
                className={`px-2 py-0.5 rounded text-[10px] font-black uppercase ${
                  is3Stars
                    ? "bg-rose-500/20 text-rose-300 border border-rose-500/40"
                    : "bg-amber-500/20 text-amber-300 border border-amber-500/40"
                }`}
              >
                {is3Stars ? "⭐⭐⭐ 3 YILDIZ (KRİTİK)" : "⭐⭐ 2 YILDIZ (ORTA)"}
              </span>
            </div>

            <h2 className="text-base sm:text-lg font-black text-white mt-1 leading-snug">
              {activeAlert.flag ? `${activeAlert.flag} ` : ""}
              {activeAlert.title}
            </h2>

            {activeAlert.original_title && activeAlert.original_title !== activeAlert.title && (
              <p className="text-[11px] text-bunker-muted">
                Orijinal: {activeAlert.original_title} ({activeAlert.country_name || activeAlert.country})
              </p>
            )}
          </div>

          <button
            type="button"
            onClick={handleClose}
            className="w-8 h-8 rounded-xl bg-bunker-900 border border-bunker-700 hover:border-white text-bunker-muted hover:text-white flex items-center justify-center text-sm font-bold transition-all shrink-0"
            title="Kapat"
          >
            ✕
          </button>
        </div>

        {/* 🎯 ETKİLENECEK PARİTELER (ÇOK BELİRGİN KUTU) */}
        <div className="p-3.5 rounded-xl bg-gradient-to-r from-blue-950/40 via-cyan-950/30 to-bunker-900/60 border border-cyan-500/40 space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-[11px] uppercase font-black text-cyan-300 flex items-center gap-1.5 tracking-wider">
              <span>🎯</span> ETKİLENECEK PARİTELER ({activeAlert.affected_symbols.length})
            </span>
            <span className="text-[10px] text-bunker-muted font-bold">
              Yüksek Spread &amp; Oynaklık Uyarısı
            </span>
          </div>

          <div className="flex flex-wrap gap-2 pt-0.5">
            {activeAlert.affected_symbols.map((sym) => (
              <span
                key={sym}
                className="px-2.5 py-1 rounded-lg text-xs font-black bg-cyan-500/20 text-cyan-200 border border-cyan-400/50 shadow-sm flex items-center gap-1"
              >
                <span>⚡</span>
                <span>{sym}</span>
              </span>
            ))}
          </div>
        </div>

        {/* Rakamlar & Beklenti */}
        <div className="grid grid-cols-2 gap-2 p-2.5 rounded-xl bg-bunker-900/70 border border-bunker-800 text-xs">
          <div>
            <span className="text-[10px] text-bunker-muted block font-bold">Piyasa Beklentisi:</span>
            <strong className="text-cyan-300 text-sm font-black">{activeAlert.forecast || "—"}</strong>
          </div>
          <div>
            <span className="text-[10px] text-bunker-muted block font-bold">Önceki Veri:</span>
            <strong className="text-slate-300 text-sm font-black">{activeAlert.previous || "—"}</strong>
          </div>
        </div>

        {/* ⚡ HANGİ DURUMDA NASIL ETKİLENİR? (ÖZET SENARYO) */}
        <div className="space-y-2 text-xs">
          <span className="text-[11px] font-black uppercase tracking-wider text-amber-300 flex items-center gap-1">
            <span>⚡</span> Hangi Durumda Nasıl Etkilenir?
          </span>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            {/* Beklenti Üzeri */}
            <div className="p-3 rounded-xl bg-emerald-500/10 border border-emerald-500/30 space-y-1">
              <div className="font-bold text-emerald-400 text-[10px] flex items-center gap-1">
                <span>🟢</span>
                <span>{activeAlert.scenario?.bullish_trigger || "Beklenti Üzeri Gelirse:"}</span>
              </div>
              <p className="text-[11px] text-emerald-200/90 leading-relaxed">
                {activeAlert.scenario?.bullish_outcome}
              </p>
            </div>

            {/* Beklenti Altı */}
            <div className="p-3 rounded-xl bg-rose-500/10 border border-rose-500/30 space-y-1">
              <div className="font-bold text-rose-400 text-[10px] flex items-center gap-1">
                <span>🔴</span>
                <span>{activeAlert.scenario?.bearish_trigger || "Beklenti Altı Kalırsa:"}</span>
              </div>
              <p className="text-[11px] text-rose-200/90 leading-relaxed">
                {activeAlert.scenario?.bearish_outcome}
              </p>
            </div>
          </div>
        </div>

        {/* Scalper Güvenlik Uyarısı */}
        <div className="p-2.5 rounded-xl bg-amber-500/10 border border-amber-500/30 text-[11px] text-amber-200/90 flex items-start gap-2">
          <span className="text-base leading-none">⚠️</span>
          <p className="leading-snug">
            <strong>Scalper Uyarısı:</strong> Veri açıklanma dakikasında (±3 dk) broker spreadleri genişleyebilir ve sahte kırılımlar (fitiller) oluşabilir. Açık pozisyonlarınızın SL seviyelerini kontrol edin.
          </p>
        </div>

        {/* Aksiyon Butonları */}
        <div className="pt-2 border-t border-bunker-800 flex items-center justify-between gap-2 flex-wrap">
          <a
            href="https://www.investing.com/economic-calendar"
            target="_blank"
            rel="noopener noreferrer"
            className="px-3 py-1.5 rounded-xl text-xs font-bold text-amber-300 bg-amber-500/10 border border-amber-500/30 hover:bg-amber-500/20 transition-all flex items-center gap-1"
          >
            <span>🌐</span> Investing.com Takvimi ↗
          </a>

          <div className="flex items-center gap-2">
            <Link
              href="/"
              onClick={handleClose}
              className="px-3.5 py-1.5 rounded-xl text-xs font-bold bg-cyan-500/20 text-cyan-300 border border-cyan-500/40 hover:bg-cyan-500/30 transition-all"
            >
              Senaryoyu İncele →
            </Link>

            <button
              type="button"
              onClick={handleClose}
              className="px-4 py-1.5 rounded-xl bg-bunker-900 border border-bunker-700 hover:border-white text-white text-xs font-bold transition-all"
            >
              Anladım / Kapat
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
