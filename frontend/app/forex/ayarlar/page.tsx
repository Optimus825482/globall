"use client";

// ============================================================================
// FOREX AYARLARI — Otonom scalper'ın TEK parametre ekranı.
// 2026-10-07: AutoSettingsPanel /forex/btc-gold ve /forex/portfolio izleme
// sayfalarından sökülüp buraya taşındı; izleme sayfaları yalnızca izler,
// parametreler yalnız buradan yönetilir. Backend'e dokunulmaz: aynı
// /api/forex/auto-paper/settings ve /auto-paper/reset-symbol-guards uçları
// kullanılır.
// ============================================================================

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { apiFetch } from "../../lib/api";
import AutoSettingsPanel, { type AutoSettings } from "../components/AutoSettingsPanel";

// Panel bu sayfada inline gösterilir (modal değil): show sabit true,
// onClose bilinçli no-op — "✕ Kapat"/"Vazgeç" formu kapatmaz, sayfa açık kalır.
const noopClose = () => {};

interface CleanSlateResult {
  archived_count: number;
  reset_at: string;
  kept_paper_count?: number;
  note: string;
}

export default function ForexAyarlarPage() {
  // appliedSettings kaynağı: /forex/btc-gold ile aynı desen —
  // GET /api/forex/auto-paper/status → res.settings.
  // Panel yalnız gerçek backend ayarları geldiğinde render edilir; böylece
  // form, sayfa varsayılanlarıyla (stale) başlayıp üzerine kaydetmez.
  const [appliedSettings, setAppliedSettings] = useState<AutoSettings | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  // Temiz sayfa (reset-symbol-guards) durumu
  const [isResetting, setIsResetting] = useState(false);
  const [resetResult, setResetResult] = useState<CleanSlateResult | null>(null);
  const [resetError, setResetError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const fetchSettings = async () => {
      try {
        const res = await apiFetch("/api/forex/auto-paper/status");
        if (!cancelled && res?.settings) {
          setAppliedSettings(res.settings);
        }
      } catch (err) {
        if (!cancelled) {
          console.error("Forex ayarları yüklenemedi:", err);
          setLoadError("Motor ayarları yüklenemedi — backend bağlantısını kontrol edin.");
        }
      }
    };
    fetchSettings();
    return () => {
      cancelled = true;
    };
  }, []);

  const handleCleanSlate = async () => {
    if (
      !confirm(
        "🧹 Temiz Sayfa: kesim öncesindeki TÜM kapalı işlemler arşive alınacak; EV kalkanı ve seri-SL sayaçları sıfırlanacak, rapor/KPI/CSV sıfırdan sayacak. Bakiyeye dokunulmaz. Devam edilsin mi?"
      )
    )
      return;
    setIsResetting(true);
    setResetError(null);
    setResetResult(null);
    try {
      const res = await apiFetch("/api/forex/auto-paper/reset-symbol-guards", { method: "POST" });
      setResetResult({
        archived_count: Number(res?.archived_count ?? 0),
        reset_at: String(res?.reset_at ?? "-"),
        kept_paper_count: res?.kept_paper_count != null ? Number(res.kept_paper_count) : undefined,
        note: String(res?.note ?? ""),
      });
    } catch (err) {
      console.error("Temiz sayfa hatası:", err);
      setResetError(err instanceof Error ? err.message : "Temiz sayfa işlemi başarısız oldu.");
    } finally {
      setIsResetting(false);
    }
  };

  return (
    <div className="space-y-6 pb-16 font-mono">
      {/* BAŞLIK */}
      <div className="p-5 rounded-2xl bg-gradient-to-r from-blue-950/40 via-bunker-900/90 to-cyan-950/30 border border-blue-500/40 backdrop-blur-md shadow-2xl flex items-center gap-3.5">
        <div className="w-13 h-13 rounded-2xl bg-blue-500/20 border border-blue-400/40 flex items-center justify-center text-3xl shadow-[0_0_20px_rgba(59,130,246,0.35)]">
          ⚙️
        </div>
        <div>
          <h1 className="text-xl font-black text-white tracking-tight">Forex Ayarları</h1>
          <p className="text-xs text-bunker-muted mt-1">
            Otonom scalping risk, çıkış ve sembol parametreleri — değişiklikler anında motora uygulanır
          </p>
        </div>
      </div>

      {/* PARAMETRE PANELİ (izleme sayfalarından buraya taşındı) */}
      {loadError && (
        <div className="p-3 rounded-xl bg-rose-500/20 border border-rose-500/40 text-rose-300 text-xs font-bold">
          {loadError}
        </div>
      )}
      {!appliedSettings && !loadError && (
        <div className="p-8 text-center text-bunker-muted text-xs animate-pulse rounded-2xl bg-bunker-900/70 border border-bunker-800">
          Motor ayarları yükleniyor…
        </div>
      )}
      {appliedSettings && (
        <AutoSettingsPanel
          show={true}
          onClose={noopClose}
          appliedSettings={appliedSettings}
          onSaved={setAppliedSettings}
          accent="blue"
        />
      )}

      {/* TEMİZ SAYFA (reset-symbol-guards) */}
      <div className="p-5 rounded-2xl bg-bunker-900/80 border border-bunker-800 shadow-xl space-y-3">
        <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-4">
          <div>
            <div className="flex items-center gap-2">
              <span className="text-base">🧹</span>
              <h2 className="text-sm font-bold text-white uppercase tracking-wider">
                Temiz Sayfa (Sembol Kalkanlarını Sıfırla)
              </h2>
            </div>
            <p className="text-[11px] text-bunker-muted mt-1.5 leading-relaxed">
              Kesim öncesindeki tüm kapalı işlemler arşive alınır; EV kalkanı ve seri-SL sayaçları sıfırlanır,
              rapor/KPI/CSV sıfırdan saymaya başlar. Bakiyeye dokunulmaz.
            </p>
          </div>
          <button
            type="button"
            onClick={handleCleanSlate}
            disabled={isResetting}
            className="shrink-0 px-4 py-2 rounded-xl bg-bunker-950 border border-bunker-700 text-white hover:border-amber-400 transition-all text-xs font-bold flex items-center gap-1.5 disabled:opacity-50"
          >
            <span>{isResetting ? "⏳ Temizleniyor…" : "🧹 Temiz Sayfa"}</span>
          </button>
        </div>

        {resetResult && (
          <div className="p-3 rounded-xl bg-emerald-500/15 border border-emerald-500/40 text-emerald-300 text-xs space-y-1">
            <div className="font-bold">✓ Temiz sayfa tamamlandı — {resetResult.reset_at}</div>
            <div>
              Arşive alınan işlem: <span className="font-bold">{resetResult.archived_count}</span>
              {resetResult.kept_paper_count != null && (
                <>
                  {" · "}Raporda kalan: <span className="font-bold">{resetResult.kept_paper_count}</span>
                </>
              )}
            </div>
            {resetResult.note && (
              <div className="text-[11px] text-bunker-300 leading-relaxed">{resetResult.note}</div>
            )}
          </div>
        )}

        {resetError && (
          <div className="p-3 rounded-xl bg-rose-500/20 border border-rose-500/40 text-rose-300 text-xs font-bold">
            {resetError}
          </div>
        )}
      </div>

      {/* ALT GEZİNTİ BAĞLANTILARI */}
      <div className="flex flex-wrap items-center gap-4 text-xs text-bunker-muted pt-2 border-t border-bunker-800">
        <Link href="/forex/btc-gold" className="hover:text-amber-400 transition-colors">
          ← BTC + Altın Kokpiti
        </Link>
        <span className="text-bunker-700">|</span>
        <Link href="/forex/portfolio" className="hover:text-blue-400 transition-colors">
          Forex Portföy Konsolu
        </Link>
      </div>
    </div>
  );
}
