"use client";

import React, { createContext, useContext, useEffect, useState, useCallback } from "react";

interface PwaContextType {
  isInstalled: boolean;
  isInstallable: boolean;
  isIos: boolean;
  isOnline: boolean;
  promptInstall: () => Promise<boolean>;
  showIosGuide: boolean;
  setShowIosGuide: (show: boolean) => void;
  openInstallDialog: () => void;
}

const PwaContext = createContext<PwaContextType>({
  isInstalled: false,
  isInstallable: false,
  isIos: false,
  isOnline: true,
  promptInstall: async () => false,
  showIosGuide: false,
  setShowIosGuide: () => {},
  openInstallDialog: () => {},
});

export function PwaProvider({ children }: { children: React.ReactNode }) {
  const [deferredPrompt, setDeferredPrompt] = useState<any>(null);
  const [isInstalled, setIsInstalled] = useState(false);
  const [isIos, setIsIos] = useState(false);
  const [isOnline, setIsOnline] = useState(true);
  const [showIosGuide, setShowIosGuide] = useState(false);

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
      // Masaüstü veya diğer tarayıcılar için bilgilendirme
      alert(
        "PWA Kurulumu: Tarayıcınızın adres çubuğundaki 'Yükle' simgesine veya menüdeki 'Ana Ekrana Ekle' seçeneğine dokunarak uygulamayı tam ekran yükleyebilirsiniz."
      );
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
        openInstallDialog,
      }}
    >
      {children}
    </PwaContext.Provider>
  );
}

export function usePwa() {
  return useContext(PwaContext);
}
