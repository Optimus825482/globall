"use client";

import { useEffect, useRef } from "react";

export interface UsePollingOptions {
  /** Doğru ise sekme tekrar öne geldiğinde hemen bir tur çalıştırır (varsayılan: true). */
  runOnVisible?: boolean;
  /** Yanlış ise hook hiçbir zaman otomatik tur çalıştırmaz (yalnızca test/özel durumlar). */
  enabled?: boolean;
}

/**
 * Görünürlük-farkında, çakışma korumalı periyodik veri çekme hook'u.
 *
 * PERFORMANS (2026-10-08): Uygulama uzun süre açık kalınca donuyordu; kök
 * nedenler:
 *   1. Bazı sayfalar (btc-gold 1.5 sn, portfolio 1.5 sn, metamobil 2 sn)
 *      arka planda da dönmeye devam eden interval'lerle hem istemciyi hem
 *      backend'i sürekli meşgul ediyordu. Diğer sayfalar `document.hidden`
 *      kontrolü yapıyordu ama kontrol edilen interval yine de tik atıyordu.
 *   2. Önceki turlar tamamlanmadan yeni tur başlatılıyordu; yavaş yanıtlar
 *      üst üste binip istek kuyruğunu şişiriyordu.
 *
 * Bu hook ikisini de kökten çözer: sekme arka plana geçince interval tamamen
 * DURUR (sadece tick atlanmaz) ve bir tur çalışırken yeni tur başlamaz.
 * Sekme öne geldiğinde isteğe bağlı olarak hemen tazeler.
 *
 * Tüm canlı veri sayfaları bu tek hook'u kullanır; `document.hidden` kontrollü
 * çıplak `setInterval` yerine bu tercih edilmelidir.
 */
export function usePolling(
  callback: () => void | Promise<unknown>,
  ms: number | null,
  options?: UsePollingOptions
) {
  const runOnVisible = options?.runOnVisible ?? true;
  const enabled = options?.enabled ?? true;

  const cbRef = useRef(callback);
  useEffect(() => {
    cbRef.current = callback;
  });

  const inFlightRef = useRef(false);

  useEffect(() => {
    if (ms === null || ms <= 0 || !enabled) return;

    let timer: ReturnType<typeof setInterval> | null = null;

    const run = async () => {
      if (inFlightRef.current) return;
      if (typeof document !== "undefined" && document.hidden) return;
      inFlightRef.current = true;
      try {
        await cbRef.current();
      } finally {
        inFlightRef.current = false;
      }
    };

    const start = () => {
      if (!timer) timer = setInterval(run, ms);
    };
    const stop = () => {
      if (timer) {
        clearInterval(timer);
        timer = null;
      }
    };

    const onVisibility = () => {
      if (typeof document === "undefined") return;
      if (document.visibilityState === "visible") {
        if (runOnVisible) void run();
        start();
      } else {
        stop();
      }
    };

    if (typeof document === "undefined" || document.visibilityState === "visible") {
      void run();
      start();
    }

    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      document.removeEventListener("visibilitychange", onVisibility);
      stop();
    };
  }, [ms, enabled, runOnVisible]);
}
