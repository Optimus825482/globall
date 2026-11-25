"use client";

import { useCallback, useEffect, useState } from "react";

export type ToastTone = "info" | "success" | "error" | "warning";

interface ToastItem {
  id: number;
  message: string;
  tone: ToastTone;
}

const TOAST_EVENT = "scalper:toast";
const AUTO_DISMISS_MS = 4200;

let nextToastId = 1;

export function showToast(message: string, tone: ToastTone = "info") {
  if (typeof window === "undefined") return;
  window.dispatchEvent(
    new CustomEvent<{ message: string; tone: ToastTone }>(TOAST_EVENT, {
      detail: { message, tone },
    })
  );
}

const TONE_STYLES: Record<
  ToastTone,
  { border: string; accent: string; icon: string }
> = {
  info: {
    border: "border-cyan-400/50",
    accent: "text-cyan-300",
    icon: "ℹ",
  },
  success: {
    border: "border-emerald-400/50",
    accent: "text-emerald-300",
    icon: "✓",
  },
  warning: {
    border: "border-amber-400/50",
    accent: "text-amber-300",
    icon: "⚠",
  },
  error: {
    border: "border-rose-400/50",
    accent: "text-rose-300",
    icon: "✕",
  },
};

export default function AppToast() {
  const [toasts, setToasts] = useState<ToastItem[]>([]);

  const dismiss = useCallback((id: number) => {
    setToasts((prev) => prev.filter((item) => item.id !== id));
  }, []);

  useEffect(() => {
    const timers = new Map<number, number>();

    const handleToast = (event: Event) => {
      const custom = event as CustomEvent<{ message?: string; tone?: ToastTone }>;
      const message = String(custom.detail?.message || "").trim();
      if (!message) return;
      const tone: ToastTone = custom.detail?.tone || "info";
      const id = nextToastId++;

      setToasts((prev) => [...prev.slice(-4), { id, message, tone }]);

      const timer = window.setTimeout(() => {
        timers.delete(id);
        dismiss(id);
      }, AUTO_DISMISS_MS);
      timers.set(id, timer);
    };

    window.addEventListener(TOAST_EVENT, handleToast);
    return () => {
      window.removeEventListener(TOAST_EVENT, handleToast);
      timers.forEach((timer) => window.clearTimeout(timer));
      timers.clear();
    };
  }, [dismiss]);

  if (toasts.length === 0) return null;

  return (
    <div
      className="fixed bottom-[calc(4.75rem+env(safe-area-inset-bottom,0px))] md:bottom-6 right-3 left-3 md:left-auto md:max-w-md z-[130] pointer-events-none flex flex-col gap-2"
      aria-live="polite"
    >
      {toasts.map((toast) => {
        const style = TONE_STYLES[toast.tone] || TONE_STYLES.info;
        const isAlert = toast.tone === "error" || toast.tone === "warning";

        return (
          <div
            key={toast.id}
            role={isAlert ? "alert" : "status"}
            className={`pointer-events-auto flex items-start justify-between gap-3 rounded-xl border ${style.border} bg-bunker-950/95 px-3.5 py-2.5 shadow-2xl backdrop-blur-md font-mono text-xs text-white`}
          >
            <div className="flex items-start gap-2 min-w-0">
              <span
                aria-hidden="true"
                className={`shrink-0 font-bold leading-5 ${style.accent}`}
              >
                {style.icon}
              </span>
              <p className="leading-5 break-words text-white">{toast.message}</p>
            </div>
            <button
              type="button"
              onClick={() => dismiss(toast.id)}
              aria-label="Bildirimi kapat"
              className="pointer-events-auto shrink-0 rounded-md px-1.5 py-0.5 text-bunker-muted hover:text-white hover:bg-bunker-800/80 transition-colors leading-none"
            >
              ✕
            </button>
          </div>
        );
      })}
    </div>
  );
}
