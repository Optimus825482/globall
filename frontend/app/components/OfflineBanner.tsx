"use client";

import React, { useState, useEffect } from "react";
import { usePwa } from "../lib/pwa";

export default function OfflineBanner() {
  const { isOnline } = usePwa();
  const [showReconnected, setShowReconnected] = useState(false);

  useEffect(() => {
    if (isOnline) {
      // Çevrimiçi duruma dönünce 2.5 saniye boyunca "Yeniden bağlandı" rozeti göster
      setShowReconnected(true);
      const timer = setTimeout(() => setShowReconnected(false), 2500);
      return () => clearTimeout(timer);
    }
  }, [isOnline]);

  if (!isOnline) {
    return (
      <div
        role="alert"
        className="fixed top-0 left-0 right-0 z-50 py-1.5 px-3 bg-rose-950/95 border-b border-rose-500/50 backdrop-blur-md text-center text-xs font-mono font-bold text-rose-200 flex items-center justify-center gap-2 shadow-lg animate-in slide-in-from-top-2"
        style={{ paddingTop: "max(0.35rem, env(safe-area-inset-top, 0px))" }}
      >
        <span className="w-2 h-2 rounded-full bg-rose-500 animate-ping" />
        <span>⚡ ÇEVRİMDIŞI MOD — İnternet bağlantısı kesildi. Yeniden bağlanılıyor...</span>
      </div>
    );
  }

  if (showReconnected) {
    return (
      <div
        role="status"
        className="fixed top-0 left-0 right-0 z-50 py-1 px-3 bg-emerald-950/95 border-b border-emerald-500/50 backdrop-blur-md text-center text-[11px] font-mono font-bold text-emerald-200 flex items-center justify-center gap-2 shadow-lg animate-in fade-in"
        style={{ paddingTop: "max(0.25rem, env(safe-area-inset-top, 0px))" }}
      >
        <span className="w-2 h-2 rounded-full bg-emerald-400" />
        <span>✓ BAĞLANTI KURULDU — Canlı veri akışı devam ediyor.</span>
      </div>
    );
  }

  return null;
}
