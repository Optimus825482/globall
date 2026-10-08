"use client";

import dynamic from "next/dynamic";

const TechnicalChartsPage = dynamic(() => import("../../technical-charts/page"), {
  ssr: false,
  loading: () => (
    <div className="h-full min-h-[500px] flex items-center justify-center bg-bunker-950 border border-bunker-800 rounded-xl">
      <div className="flex items-center gap-2 font-mono text-xs text-bunker-muted">
        <span className="w-2 h-2 rounded-full bg-neon-green animate-ping" />
        Teknik Grafik Tuvali Hazırlanıyor...
      </div>
    </div>
  ),
});

export default function ForexTechnicalChartsPage() {
  return <TechnicalChartsPage />;
}
