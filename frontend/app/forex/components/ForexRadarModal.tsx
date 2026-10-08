"use client";

// ============================================================================
// UYGULAMA İÇİ FOREX RADAR SİNYAL BİLDİRİM MODALI (POPUP)
// 2026-10-07: Push bildirimi yerine, Forex radarına takılan güçlü sinyallerde
// (Skor >= 75, Tier: STRONG) doğrudan uygulama içinde açılan bildirim penceresi.
// ============================================================================

import React, { useEffect, useState, useRef, useCallback } from "react";
import Link from "next/link";
import { apiFetch } from "../../lib/api";
import { usePolling } from "../../lib/usePolling";
import {
  getInAppNotificationSettings,
  InAppNotificationSettings,
} from "../../lib/notificationSettings";

interface RadarCandidate {
  symbol: string;
  display: string;
  name?: string;
  category?: string;
  action: "BUY" | "SELL" | "HOLD";
  score: number;
  tier: string;
  price: number;
  spread_pips: number;
  tp_pips?: number;
  sl_pips?: number;
  rr_ratio?: number;
  adx?: number;
  supertrend_dir?: number;
  rsi?: number;
  has_open_position?: boolean;
}

export function playRadarSound() {
  try {
    const AudioContextClass = window.AudioContext || (window as any).webkitAudioContext;
    if (!AudioContextClass) return;
    const ctx = new AudioContextClass();
    const now = ctx.currentTime;
    // Zarif, yüksek frekanslı 2 tonlu radar uyarısı
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = "sine";
    osc.frequency.setValueAtTime(1200, now);
    osc.frequency.exponentialRampToValueAtTime(1800, now + 0.12);
    gain.gain.setValueAtTime(0.001, now);
    gain.gain.linearRampToValueAtTime(0.18, now + 0.02);
    gain.gain.exponentialRampToValueAtTime(0.001, now + 0.25);
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.start(now);
    osc.stop(now + 0.26);
  } catch {}
}

export default function ForexRadarModal() {
  const [activeSignal, setActiveSignal] = useState<RadarCandidate | null>(null);
  const [notifSettings, setNotifSettings] = useState<InAppNotificationSettings>(() =>
    getInAppNotificationSettings()
  );
  const seenSignalsRef = useRef<Map<string, number>>(new Map());

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
      // Örnek test sinyali aç
      const sampleSignal: RadarCandidate = {
        symbol: "XAUUSD",
        display: "XAU/USD",
        name: "Ons Altın (XAU)",
        action: "BUY",
        score: 88.5,
        tier: "STRONG",
        price: 2685.40,
        spread_pips: 0.2,
        tp_pips: 25.0,
        sl_pips: 8.0,
        rr_ratio: 3.12,
        adx: 38.4,
        rsi: 54.2,
      };
      setActiveSignal(sampleSignal);
      const current = getInAppNotificationSettings();
      if (current.soundEnabled) {
        playRadarSound();
      }
    };

    window.addEventListener("scalper_in_app_settings_changed", handleSettingsChanged);
    window.addEventListener("scalper_test_radar_modal", handleTestModal);
    return () => {
      window.removeEventListener("scalper_in_app_settings_changed", handleSettingsChanged);
      window.removeEventListener("scalper_test_radar_modal", handleTestModal);
    };
  }, []);

  const checkRadarSignals = useCallback(async () => {
    // Uygulama içi bildirimler ayardan kapalıysa popup gösterme
    const current = getInAppNotificationSettings();
    if (!current.enabled) return;

    try {
      const res = await apiFetch("/api/forex/radar");
      if (!res?.candidates || !Array.isArray(res.candidates)) return;

      const activeSymbolsSet = new Set<string>(
        (res.active_symbols || []).map((s: string) => String(s).toUpperCase())
      );

      const now = Date.now();
      // Yalnızca güçlü (STRONG veya skor >= 75) BUY/SELL sinyallerini filtrele.
      // KRİTİK KURAL (2026-10-07): İşlem açılmış olan sembol için (has_open_position,
      // active_symbols içinde olan veya tier === 'ACTIVE') YENİDEN RADAR BİLDİRİMİ GÖNDERİLMEZ!
      const strongOnes: RadarCandidate[] = res.candidates.filter(
        (c: RadarCandidate) => {
          const symU = String(c.symbol || "").toUpperCase();
          const hasOpenPos = Boolean(c.has_open_position) || activeSymbolsSet.has(symU) || c.tier === "ACTIVE";
          if (hasOpenPos) {
            return false; // İşlem açılmış sembolü doğrudan ele
          }
          return (
            (c.tier === "STRONG" || c.score >= 75.0) &&
            (c.action === "BUY" || c.action === "SELL")
          );
        }
      );

      for (const cand of strongOnes) {
        const key = `${cand.symbol}_${cand.action}`;
        const lastSeen = seenSignalsRef.current.get(key) || 0;

        // Aynı sinyal için 120 saniyede bir en fazla 1 kez bildirim göster (spam koruması)
        if (now - lastSeen > 120_000) {
          seenSignalsRef.current.set(key, now);
          // PERFORMANS: Harita sınırsız büyümesin (uzun süre açık uygulamada
          // bellek şişmesi); 500 kaydı aşınca en eski yarısı düşürülür.
          if (seenSignalsRef.current.size > 500) {
            const excess = seenSignalsRef.current.size - 250;
            let dropped = 0;
            for (const k of seenSignalsRef.current.keys()) {
              if (dropped++ >= excess) break;
              seenSignalsRef.current.delete(k);
            }
          }
          setActiveSignal(cand);
          if (current.soundEnabled) {
            playRadarSound();
          }
          break; // Tek seferde bir bildirim göster
        }
      }
    } catch {}
  }, []);

  // Açık olan bildirimdeki sembole işlem açıldıysa bildirimi kendiliğinden hemen kapat
  // PERFORMANS (2026-10-08): /auto-paper/status ağırlıklı bir uçtur; modal açıkken
  // 2 sn'de bir dövmek yerine 5 sn yeterli. usePolling: arka planda durur.
  const pollActiveStatus = useCallback(async () => {
    if (!activeSignal) return;
    try {
      const statusRes = await apiFetch("/api/forex/auto-paper/status");
      if (statusRes?.open_positions && Array.isArray(statusRes.open_positions)) {
        const isNowOpen = statusRes.open_positions.some(
          (p: any) => String(p.symbol || "").toUpperCase() === activeSignal.symbol.toUpperCase()
        );
        if (isNowOpen) {
          setActiveSignal(null);
        }
      }
    } catch {}
  }, [activeSignal]);
  usePolling(pollActiveStatus, activeSignal ? 5000 : null);

  // Otomatik kapanma sayacı (autoCloseSec)
  useEffect(() => {
    if (!activeSignal || notifSettings.autoCloseSec <= 0) return;
    const timer = setTimeout(() => {
      setActiveSignal(null);
    }, notifSettings.autoCloseSec * 1000);
    return () => clearTimeout(timer);
  }, [activeSignal, notifSettings.autoCloseSec]);

  // 4 saniyede bir radarı tara (yalnızca bildirimler açıkken ve modal kapalıyken).
  // PERFORMANS: ms=null iken hook hiç interval kurmaz; arka planda da durur.
  usePolling(
    checkRadarSignals,
    notifSettings.enabled && !activeSignal ? 4000 : null
  );

  if (!activeSignal) return null;

  const isBuy = activeSignal.action === "BUY";

  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center p-4 bg-black/75 backdrop-blur-sm animate-in fade-in duration-200 font-mono"
      role="dialog"
      aria-modal="true"
    >
      <div
        className={`w-full max-w-lg rounded-2xl border p-6 shadow-2xl space-y-4 animate-in zoom-in-95 duration-150 ${
          isBuy
            ? "border-emerald-500/50 bg-gradient-to-b from-emerald-950/90 via-bunker-950 to-bunker-950 shadow-[0_0_30px_rgba(16,185,129,0.25)]"
            : "border-rose-500/50 bg-gradient-to-b from-rose-950/90 via-bunker-950 to-bunker-950 shadow-[0_0_30px_rgba(244,63,94,0.25)]"
        }`}
      >
        {/* Başlık ve Kapat */}
        <div className="flex items-start justify-between gap-3 border-b border-bunker-800 pb-3">
          <div className="flex items-center gap-2.5">
            <div
              className={`w-10 h-10 rounded-xl flex items-center justify-center text-xl font-black ${
                isBuy
                  ? "bg-emerald-500/20 text-emerald-300 border border-emerald-500/40"
                  : "bg-rose-500/20 text-rose-300 border border-rose-500/40"
              }`}
            >
              ⚡
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span className="text-[10px] font-black uppercase tracking-wider text-cyan-300">
                  UYGULAMA İÇİ RADAR SİNYALİ
                </span>
                <span className="w-2 h-2 rounded-full bg-cyan-400 animate-ping" />
              </div>
              <h2 className="text-base font-black text-white tracking-tight mt-0.5">
                ALGORİTMANIN ONAYLADIĞI GÜÇLÜ İŞLEM SİNYALİ
              </h2>
            </div>
          </div>

          <button
            type="button"
            onClick={() => setActiveSignal(null)}
            className="w-8 h-8 rounded-xl bg-bunker-900 border border-bunker-700 hover:border-white text-bunker-muted hover:text-white flex items-center justify-center text-xs font-bold transition-all"
            aria-label="Kapat"
          >
            ✕
          </button>
        </div>

        {/* Sembol ve Yön Göstergesi */}
        <div className="flex items-center justify-between p-3.5 rounded-xl bg-bunker-900/80 border border-bunker-800">
          <div>
            <div className="flex items-center gap-2">
              <span className="text-lg font-black text-white">
                {activeSignal.display || activeSignal.symbol}
              </span>
              {activeSignal.category && (
                <span className="px-1.5 py-0.5 rounded text-[9px] font-bold bg-bunker-800 text-bunker-300 uppercase">
                  {activeSignal.category}
                </span>
              )}
            </div>
            {activeSignal.name && (
              <span className="text-[11px] text-bunker-muted block mt-0.5">
                {activeSignal.name}
              </span>
            )}
          </div>

          <div className="text-right">
            <span
              className={`inline-flex items-center gap-1 px-3 py-1.5 rounded-xl text-xs font-black uppercase tracking-wider ${
                isBuy
                  ? "bg-emerald-500/25 text-emerald-300 border border-emerald-500/50 shadow-[0_0_12px_rgba(16,185,129,0.3)]"
                  : "bg-rose-500/25 text-rose-300 border border-rose-500/50 shadow-[0_0_12px_rgba(244,63,94,0.3)]"
              }`}
            >
              {isBuy ? "▲ AL (LONG)" : "▼ SAT (SHORT)"}
            </span>
          </div>
        </div>

        {/* Metrikler (Skor, TP, SL, R/R) */}
        <div className="grid grid-cols-3 gap-2.5 text-center">
          <div className="p-2.5 rounded-xl bg-bunker-900/60 border border-bunker-800">
            <span className="text-[10px] text-bunker-muted uppercase block font-bold">Skor</span>
            <span className="text-lg font-black text-cyan-300">{activeSignal.score.toFixed(1)}</span>
            <span className="text-[9px] text-bunker-muted block">eşik 75</span>
          </div>

          <div className="p-2.5 rounded-xl bg-emerald-500/10 border border-emerald-500/30">
            <span className="text-[10px] text-emerald-400 uppercase block font-bold">Hedef (TP)</span>
            <span className="text-lg font-black text-emerald-300">
              +{activeSignal.tp_pips || 20}p
            </span>
            <span className="text-[9px] text-emerald-400/80 block">
              R/R 1:{activeSignal.rr_ratio || 2.5}
            </span>
          </div>

          <div className="p-2.5 rounded-xl bg-rose-500/10 border border-rose-500/30">
            <span className="text-[10px] text-rose-400 uppercase block font-bold">Stop (SL)</span>
            <span className="text-lg font-black text-rose-300">
              -{activeSignal.sl_pips || 8}p
            </span>
            <span className="text-[9px] text-rose-400/80 block">Korumalı</span>
          </div>
        </div>

        {/* Teknik İndikatörler */}
        <div className="flex items-center justify-between text-[11px] text-bunker-300 px-1 py-1 border-t border-bunker-800/60">
          <span>
            ADX: <strong className="text-white">{activeSignal.adx?.toFixed(0) || "36"}</strong>
          </span>
          <span>
            ST:{" "}
            <strong className={isBuy ? "text-emerald-400" : "text-rose-400"}>
              {isBuy ? "BOĞA" : "AYI"}
            </strong>
          </span>
          <span>
            RSI: <strong className="text-white">{activeSignal.rsi?.toFixed(0) || "42"}</strong>
          </span>
          <span>
            Spread: <strong className="text-white">{activeSignal.spread_pips?.toFixed(1) || "0.1"}p</strong>
          </span>
        </div>

        {/* Aksiyon Butonları */}
        <div className="pt-2 border-t border-bunker-800 flex items-center justify-between gap-3">
          <Link
            href={`/forex/charts?symbol=${activeSignal.symbol}`}
            onClick={() => setActiveSignal(null)}
            className="flex-1 py-2 rounded-xl bg-cyan-950/60 border border-cyan-500/40 hover:border-cyan-400 text-cyan-300 text-xs font-bold text-center transition-all"
          >
            📈 Grafiği İncele
          </Link>

          <Link
            href="/forex/islemler"
            onClick={() => setActiveSignal(null)}
            className="flex-1 py-2 rounded-xl bg-emerald-950/60 border border-emerald-500/40 hover:border-emerald-400 text-emerald-300 text-xs font-bold text-center transition-all"
          >
            ⚡ Canlı İşlemler
          </Link>

          <button
            type="button"
            onClick={() => setActiveSignal(null)}
            className="px-4 py-2 rounded-xl bg-bunker-900 border border-bunker-700 hover:border-white text-white text-xs font-bold transition-all"
          >
            Kapat
          </button>
        </div>

        {/* Ayarlar linki & otomatik kapanma bilgisi */}
        <div className="flex items-center justify-between text-[10px] text-bunker-400 pt-1">
          <span>
            {notifSettings.autoCloseSec > 0
              ? `⏱️ ${notifSettings.autoCloseSec} sn sonra otomatik kapanır`
              : "📌 Manuel kapatana kadar açık kalır"}
          </span>
          <Link
            href="/settings?tab=app"
            onClick={() => setActiveSignal(null)}
            className="text-bunker-muted hover:text-cyan-300 underline flex items-center gap-1 transition-colors"
          >
            ⚙️ Bildirimleri Yönet / Kapat
          </Link>
        </div>
      </div>
    </div>
  );
}
