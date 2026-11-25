"use client";

import React, { useState, useEffect, useRef, useCallback } from "react";
import { usePwa } from "../lib/pwa";

export default function PwaInstallBanner() {
  const {
    isInstallable,
    isInstalled,
    isIos,
    promptInstall,
    showIosGuide,
    setShowIosGuide,
    showInstallGuide,
    setShowInstallGuide,
    updateAvailable,
    applyUpdate,
  } = usePwa();
  const [dismissed, setDismissed] = useState(true);
  const [updateDismissed, setUpdateDismissed] = useState(false);

  const isGuideOpen = showIosGuide || showInstallGuide;
  const dialogRef = useRef<HTMLDialogElement>(null);
  const pointerDownOutsideRef = useRef(false);

  const closeGuide = useCallback(() => {
    setShowIosGuide(false);
    setShowInstallGuide(false);
  }, [setShowIosGuide, setShowInstallGuide]);

  useEffect(() => {
    // Kurulmuşsa veya daha önce kapatılmışsa gösterme
    if (typeof window === "undefined") return;
    if (isInstalled) return;

    const isDismissed = localStorage.getItem("scalper_pwa_banner_dismissed");
    if (!isDismissed) {
      // Sayfa yüklendikten 3 saniye sonra yumuşakça göster
      const timer = setTimeout(() => setDismissed(false), 3000);
      return () => clearTimeout(timer);
    }
  }, [isInstalled]);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (isGuideOpen) {
      if (!dialog.open) {
        dialog.showModal();
      }
    } else if (dialog.open) {
      dialog.close();
    }
  }, [isGuideOpen]);

  const handleDismiss = () => {
    setDismissed(true);
    try {
      localStorage.setItem("scalper_pwa_banner_dismissed", "true");
    } catch {
      // localStorage kapalıysa yok say
    }
  };

  const handleInstallClick = async () => {
    if (isIos) {
      setShowIosGuide(true);
      setDismissed(true);
    } else {
      const ok = await promptInstall();
      if (ok) setDismissed(true);
    }
  };

  const isOutsideDialog = (e: React.PointerEvent<HTMLDialogElement>) => {
    const dialog = dialogRef.current;
    if (!dialog) return false;
    const rect = dialog.getBoundingClientRect();
    return (
      e.clientX < rect.left ||
      e.clientX > rect.right ||
      e.clientY < rect.top ||
      e.clientY > rect.bottom
    );
  };

  const showUpdateBanner = updateAvailable && !updateDismissed;
  const showInstallBanner = !dismissed && !isInstalled && isInstallable && !showUpdateBanner;

  return (
    <>
      {/* 0. YENİ SÜRÜM GÜNCELLEME BANNERI */}
      {showUpdateBanner && (
        <aside
          role="status"
          aria-label="Uygulama Güncelleme Bildirimi"
          className="fixed bottom-[calc(4.5rem+env(safe-area-inset-bottom,0px))] md:bottom-6 left-3 right-3 md:left-auto md:right-6 md:max-w-md z-50 p-3 rounded-2xl bg-bunker-950/95 border border-emerald-400/50 shadow-[0_10px_35px_rgba(0,0,0,0.8),0_0_20px_rgba(16,185,129,0.2)] backdrop-blur-xl animate-in fade-in slide-in-from-bottom-5 duration-300"
        >
          <div className="flex items-center gap-3">
            <div className="flex-shrink-0 w-9 h-9 rounded-xl bg-emerald-500/20 border border-emerald-400/40 flex items-center justify-center text-base">
              ✨
            </div>
            <div className="flex-1 min-w-0">
              <p className="font-mono text-xs font-bold text-white leading-tight">
                Yeni sürüm hazır
              </p>
              <p className="font-mono text-2xs text-slate-300 leading-tight mt-0.5">
                En güncel özellikler ve düzeltmeler için yenileyin.
              </p>
            </div>
            <div className="flex items-center gap-1.5 flex-shrink-0">
              <button
                type="button"
                onClick={applyUpdate}
                className="py-1.5 px-3 rounded-lg bg-emerald-500 hover:bg-emerald-400 text-bunker-950 font-mono text-xs font-black tracking-wide transition-colors touch-target"
              >
                Güncelle
              </button>
              <button
                type="button"
                onClick={() => setUpdateDismissed(true)}
                className="p-1.5 text-bunker-muted hover:text-white text-xs transition-colors"
                aria-label="Güncelleme bildirimini kapat"
              >
                ✕
              </button>
            </div>
          </div>
        </aside>
      )}

      {/* 1. AKILLI PWA YÜKLEME BANNERI (Mobil Alt Bildirim) */}
      {showInstallBanner && (
        <aside
          role="region"
          aria-label="Uygulamayı Yükle Bildirimi"
          className="fixed bottom-[calc(4.5rem+env(safe-area-inset-bottom,0px))] md:bottom-6 left-3 right-3 md:left-auto md:right-6 md:max-w-md z-50 p-3.5 rounded-2xl bg-bunker-950/95 border border-cyan-400/50 shadow-[0_10px_35px_rgba(0,0,0,0.8),0_0_20px_rgba(0,240,255,0.2)] backdrop-blur-xl animate-in fade-in slide-in-from-bottom-5 duration-300"
        >
          <div className="flex items-start gap-3">
            <div className="relative flex-shrink-0 w-11 h-11 rounded-xl bg-gradient-to-br from-cyan-500/20 to-blue-600/30 border border-cyan-400/40 flex items-center justify-center text-xl shadow-[0_0_12px_rgba(0,240,255,0.3)]">
              <span>🌐</span>
              <span className="absolute -top-1 -right-1 w-2.5 h-2.5 rounded-full bg-cyan-400 animate-ping" />
            </div>

            <div className="flex-1 min-w-0">
              <div className="flex items-center justify-between gap-1">
                <h4 className="font-mono text-xs font-bold text-white tracking-wide flex items-center gap-1.5">
                  SCALPER GLOBAL <span className="text-2xs px-1.5 py-0.2 rounded bg-cyan-400/20 text-cyan-300 border border-cyan-400/30">PWA</span>
                </h4>
                <button
                  type="button"
                  onClick={handleDismiss}
                  className="p-1 text-bunker-muted hover:text-white text-xs transition-colors"
                  aria-label="Kapat"
                >
                  ✕
                </button>
              </div>
              <p className="mt-0.5 text-2xs text-slate-300 font-mono leading-tight">
                Tarayıcı çubukları olmadan, tam ekran ve yüksek hızda yerel mobil deneyimi yaşayın.
              </p>

              <div className="mt-2.5 flex items-center gap-2">
                <button
                  type="button"
                  onClick={handleInstallClick}
                  className="flex-1 py-1.5 px-3 rounded-lg bg-gradient-to-r from-cyan-500 to-blue-600 hover:from-cyan-400 hover:to-blue-500 text-bunker-950 font-mono text-xs font-black tracking-wide shadow-[0_0_12px_rgba(0,240,255,0.4)] transition-all touch-target flex items-center justify-center gap-1.5"
                >
                  <span>📲</span>
                  <span>{isIos ? "NASIL YÜKLENİR?" : "UYGULAMAYI YÜKLE"}</span>
                </button>
                <button
                  type="button"
                  onClick={handleDismiss}
                  className="py-1.5 px-2.5 rounded-lg border border-bunker-800 bg-bunker-900/80 text-bunker-muted hover:text-white font-mono text-2xs transition-colors"
                >
                  Daha Sonra
                </button>
              </div>
            </div>
          </div>
        </aside>
      )}

      {/* 2. YEREL <dialog> KURULUM REHBERİ MODALI (iOS & Masaüstü/Android) */}
      <dialog
        ref={dialogRef}
        aria-labelledby="pwa-guide-title"
        {...({ closedby: "any" } as any)}
        onClose={closeGuide}
        onPointerDown={(e) => {
          pointerDownOutsideRef.current = e.target === dialogRef.current && isOutsideDialog(e);
        }}
        onPointerUp={(e) => {
          if (pointerDownOutsideRef.current && e.target === dialogRef.current && isOutsideDialog(e)) {
            closeGuide();
          }
          pointerDownOutsideRef.current = false;
        }}
        className="m-auto w-[calc(100%-2rem)] max-w-sm rounded-2xl border border-cyan-400/50 bg-bunker-950 p-0 text-white shadow-2xl backdrop:bg-black/80 backdrop:backdrop-blur-sm open:animate-in open:fade-in open:duration-200"
      >
        <div className="p-5 space-y-4">
          <div className="flex items-center justify-between border-b border-bunker-800 pb-3">
            <div className="flex items-center gap-2">
              <span className="text-xl" aria-hidden="true">{isIos ? "🍏" : "📲"}</span>
              <h3 id="pwa-guide-title" className="font-mono text-sm font-bold text-white">
                {isIos ? "iPhone / iPad Kurulum Rehberi" : "Uygulama Kurulum Rehberi"}
              </h3>
            </div>
            <button
              type="button"
              onClick={closeGuide}
              aria-label="Rehberi kapat"
              className="p-1 text-bunker-muted hover:text-white text-sm transition-colors"
            >
              ✕
            </button>
          </div>

          {isIos ? (
            <div className="space-y-3 font-mono text-xs text-slate-300">
              <p className="text-2xs text-cyan-300">
                Scalper Global terminalini App Store uygulaması gibi tam ekran kullanmak için 2 basit adım:
              </p>

              <div className="flex items-start gap-2.5 p-2.5 rounded-xl bg-bunker-900/80 border border-bunker-800">
                <span className="flex-shrink-0 w-6 h-6 rounded-full bg-cyan-500/20 border border-cyan-400/40 text-cyan-300 font-bold flex items-center justify-center text-xs">
                  1
                </span>
                <div>
                  <p className="font-bold text-white">Paylaş Butonuna Dokunun</p>
                  <p className="text-2xs text-bunker-muted mt-0.5">
                    Safari ekranının altındaki veya üstündeki <span className="text-cyan-400 font-bold">Paylaş (Share ⎋ / [↑])</span> ikonuna basın.
                  </p>
                </div>
              </div>

              <div className="flex items-start gap-2.5 p-2.5 rounded-xl bg-bunker-900/80 border border-bunker-800">
                <span className="flex-shrink-0 w-6 h-6 rounded-full bg-cyan-500/20 border border-cyan-400/40 text-cyan-300 font-bold flex items-center justify-center text-xs">
                  2
                </span>
                <div>
                  <p className="font-bold text-white">&quot;Ana Ekrana Ekle&quot; Seçeneğini Seçin</p>
                  <p className="text-2xs text-bunker-muted mt-0.5">
                    Açılan menüyü aşağı kaydırıp <span className="text-emerald-400 font-bold">&quot;Ana Ekrana Ekle (Add to Home Screen ⊞)&quot;</span> butonuna dokunun ve &quot;Ekle&quot;ye basın.
                  </p>
                </div>
              </div>

              <div className="p-2.5 rounded-xl bg-cyan-950/40 border border-cyan-500/30 text-2xs text-cyan-300">
                ✓ Artık terminal ana ekranınızda özel simgesiyle hazır! Bildirimler ve gerçek zamanlı WebSocket akışı kusursuz çalışır.
              </div>
            </div>
          ) : (
            <div className="space-y-3 font-mono text-xs text-slate-300">
              <p className="text-2xs text-cyan-300">
                Scalper Global terminalini masaüstü veya Android cihazınıza tam ekran uygulama olarak kurmak için:
              </p>

              <div className="flex items-start gap-2.5 p-2.5 rounded-xl bg-bunker-900/80 border border-bunker-800">
                <span className="flex-shrink-0 w-6 h-6 rounded-full bg-cyan-500/20 border border-cyan-400/40 text-cyan-300 font-bold flex items-center justify-center text-xs">
                  1
                </span>
                <div>
                  <p className="font-bold text-white">Adres Çubuğu veya Tarayıcı Menüsü</p>
                  <p className="text-2xs text-bunker-muted mt-0.5">
                    Adres çubuğundaki <span className="text-cyan-400 font-bold">Yükle</span> simgesine veya tarayıcı menüsünden <span className="text-emerald-400 font-bold">&quot;Ana Ekrana Ekle / Uygulamayı Yükle&quot;</span> seçeneğine dokunun.
                  </p>
                </div>
              </div>

              <div className="flex items-start gap-2.5 p-2.5 rounded-xl bg-bunker-900/80 border border-bunker-800">
                <span className="flex-shrink-0 w-6 h-6 rounded-full bg-cyan-500/20 border border-cyan-400/40 text-cyan-300 font-bold flex items-center justify-center text-xs">
                  2
                </span>
                <div>
                  <p className="font-bold text-white">Kurulumu Onaylayın</p>
                  <p className="text-2xs text-bunker-muted mt-0.5">
                    Açılan pencerede <span className="text-emerald-400 font-bold">&quot;Yükle&quot;</span> butonuna basarak kurulumu tamamlayın.
                  </p>
                </div>
              </div>

              <div className="p-2.5 rounded-xl bg-cyan-950/40 border border-cyan-500/30 text-2xs text-cyan-300">
                ✓ Terminal bağımsız pencere olarak açılır; bildirimler ve canlı veri akışı kesintisiz çalışır.
              </div>
            </div>
          )}

          <button
            type="button"
            onClick={closeGuide}
            className="w-full py-2.5 rounded-xl bg-cyan-500 hover:bg-cyan-400 text-bunker-950 font-mono font-bold text-xs transition-colors"
          >
            Anladım, Kapat
          </button>
        </div>
      </dialog>
    </>
  );
}
