"use client";

import React, { createContext, useContext, useEffect, useState, useCallback, useRef } from "react";

interface PwaContextType {
  isInstalled: boolean;
  isInstallable: boolean;
  isIos: boolean;
  isOnline: boolean;
  promptInstall: () => Promise<boolean>;
  showIosGuide: boolean;
  setShowIosGuide: (show: boolean) => void;
  showInstallGuide: boolean;
  setShowInstallGuide: (show: boolean) => void;
  openInstallDialog: () => void;
  updateAvailable: boolean;
  applyUpdate: () => void;
}

const PwaContext = createContext<PwaContextType>({
  isInstalled: false,
  isInstallable: false,
  isIos: false,
  isOnline: true,
  promptInstall: async () => false,
  showIosGuide: false,
  setShowIosGuide: () => {},
  showInstallGuide: false,
  setShowInstallGuide: () => {},
  openInstallDialog: () => {},
  updateAvailable: false,
  applyUpdate: () => {},
});

export function PwaProvider({ children }: { children: React.ReactNode }) {
  const [deferredPrompt, setDeferredPrompt] = useState<any>(null);
  const [isInstalled, setIsInstalled] = useState(false);
  const [isIos, setIsIos] = useState(false);
  const [isOnline, setIsOnline] = useState(true);
  const [showIosGuide, setShowIosGuide] = useState(false);
  const [showInstallGuide, setShowInstallGuide] = useState(false);
  const [updateAvailable, setUpdateAvailable] = useState(false);
  const waitingWorkerRef = useRef<ServiceWorker | null>(null);
  const reloadingRef = useRef(false);

  useEffect(() => {
    if (typeof window === "undefined") return;

    // 1. Çevrimiçi/Çevrimdışı tespiti
    setIsOnline(navigator.onLine);
    const handleOnline = () => setIsOnline(true);
    const handleOffline = () => setIsOnline(false);
    window.addEventListener("online", handleOnline);
    window.addEventListener("offline", handleOffline);

    // 2. Standalone (Yüklü PWA) tespiti
    const checkStandalone = () => {
      const isStandaloneMode =
        window.matchMedia?.("(display-mode: standalone)").matches ||
        (window.navigator as any)?.standalone === true ||
        document.referrer.includes("android-app://");
      setIsInstalled(Boolean(isStandaloneMode));
      if (isStandaloneMode) {
        navigator.storage?.persist?.().catch(() => undefined);
      }
    };
    checkStandalone();

    // 3. iOS tespiti (Safari PWA'da beforeinstallprompt desteklemez)
    const userAgent = window.navigator.userAgent.toLowerCase();
    const isIosDevice =
      /iphone|ipad|ipod/.test(userAgent) ||
      (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
    setIsIos(isIosDevice);

    // 4. beforeinstallprompt (Android / Chrome / Edge)
    const handleBeforeInstallPrompt = (e: Event) => {
      e.preventDefault();
      setDeferredPrompt(e);
    };

    const handleAppInstalled = () => {
      setIsInstalled(true);
      setDeferredPrompt(null);
    };

    window.addEventListener("beforeinstallprompt", handleBeforeInstallPrompt);
    window.addEventListener("appinstalled", handleAppInstalled);

    // 5. Service Worker Kaydı (Hem prod hem PWA desteği için)
    if ("serviceWorker" in navigator) {
      const buildId = process.env.NEXT_PUBLIC_BUILD_ID || "dev";
      const vapid = process.env.NEXT_PUBLIC_VAPID_PUBLIC_KEY || "";
      const swUrl = `/sw.js?v=${buildId}${vapid ? `&vapid=${encodeURIComponent(vapid)}` : ""}`;

      navigator.serviceWorker
        .register(swUrl)
        .then((reg) => {
          if (reg.waiting && navigator.serviceWorker.controller) {
            waitingWorkerRef.current = reg.waiting;
            setUpdateAvailable(true);
          }

          reg.addEventListener("updatefound", () => {
            const newWorker = reg.installing;
            if (!newWorker) return;
            newWorker.addEventListener("statechange", () => {
              if (newWorker.state === "installed" && navigator.serviceWorker.controller) {
                waitingWorkerRef.current = newWorker;
                setUpdateAvailable(true);
              }
            });
          });

          // Güncelleme kontrolü
          reg.update().catch(() => undefined);
        })
        .catch(() => undefined);
    }

    return () => {
      window.removeEventListener("online", handleOnline);
      window.removeEventListener("offline", handleOffline);
      window.removeEventListener("beforeinstallprompt", handleBeforeInstallPrompt);
      window.removeEventListener("appinstalled", handleAppInstalled);
    };
  }, []);

  const applyUpdate = useCallback(() => {
    if (typeof window === "undefined") return;
    const waiting = waitingWorkerRef.current;
    if (!waiting) {
      window.location.reload();
      return;
    }

    const handleControllerChange = () => {
      if (reloadingRef.current) return;
      reloadingRef.current = true;
      window.location.reload();
    };

    navigator.serviceWorker?.addEventListener("controllerchange", handleControllerChange, { once: true });
    try {
      waiting.postMessage({ type: "SKIP_WAITING" });
    } catch {
      window.location.reload();
    }
  }, []);

  const promptInstall = useCallback(async (): Promise<boolean> => {
    if (!deferredPrompt) {
      if (isIos && !isInstalled) {
        setShowIosGuide(true);
      }
      return false;
    }
    try {
      await deferredPrompt.prompt();
      const choiceResult = await deferredPrompt.userChoice;
      if (choiceResult.outcome === "accepted") {
        setDeferredPrompt(null);
        setIsInstalled(true);
        return true;
      }
    } catch {
      // Hata durumunda yutulur
    }
    return false;
  }, [deferredPrompt, isIos, isInstalled]);

  const openInstallDialog = useCallback(() => {
    if (deferredPrompt) {
      void promptInstall();
    } else if (isIos) {
      setShowIosGuide(true);
    } else {
      setShowInstallGuide(true);
    }
  }, [deferredPrompt, isIos, promptInstall]);

  const isInstallable = Boolean(deferredPrompt) || (isIos && !isInstalled);

  return (
    <PwaContext.Provider
      value={{
        isInstalled,
        isInstallable,
        isIos,
        isOnline,
        promptInstall,
        showIosGuide,
        setShowIosGuide,
        showInstallGuide,
        setShowInstallGuide,
        openInstallDialog,
        updateAvailable,
        applyUpdate,
      }}
    >
      {children}
    </PwaContext.Provider>
  );
}

export function usePwa() {
  return useContext(PwaContext);
}
