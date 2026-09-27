"use client";

import RiskPanel from "./RiskPanel";

// (2026-09-27) Risk işlevi `RiskPanel`'e taşındı — hem `/risk` sayfası
// (kendi page-shell + page-heading'iyle) hem de Yönetim Merkezi sekmesi
// (`/admin?tab=risk`, heading'siz) bu tek gövdeyi kullanır.
export default function RiskPage() {
  return (
    <main className="page-shell space-y-6">
      <div className="page-heading flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="eyebrow text-neon-green">RİSK & SERMAYE KORUMA</p>
          <h1 className="font-mono text-2xl font-bold text-white">Risk ve Pozisyon Özeti</h1>
          <p className="mt-1 text-sm text-bunker-muted">Paper-trading kayıtlarından hesaplanan görünürlük ve güvenlik paneli.</p>
        </div>
      </div>
      <RiskPanel />
    </main>
  );
}