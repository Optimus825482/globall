"use client";

// 2026-10-07: Ayarlar sayfası birleştirildi. Forex ayarları artık
// doğrudan /settings (tab=forex) altında yer alır.
import { useEffect } from "react";
import { useRouter } from "next/navigation";

export default function ForexAyarlarRedirect() {
  const router = useRouter();

  useEffect(() => {
    router.replace("/settings?tab=forex");
  }, [router]);

  return (
    <div className="flex items-center justify-center min-h-[40vh] font-mono text-sm text-cyan-400">
      <div className="flex items-center gap-2">
        <span className="w-2 h-2 rounded-full bg-cyan-400 animate-ping" />
        Ayarlar konsoluna yönlendiriliyor…
      </div>
    </div>
  );
}
