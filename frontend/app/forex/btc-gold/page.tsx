"use client";

import ForexPortfolioPage from "../portfolio/page";

// 2026-10-06 kullanıcı kararı: yalnızca Ons Altın (XAUUSD) ve BTC (BTCUSD) izlenir
// ve işlem açılır. Bu sayfa ana otonom konsolun birebir aynısıdır; yalnızca
// görünümdü bu iki sembole daraltılmıştır (backend'de allowed_symbols aynı ikisi).
export default function BtcGoldForexPage() {
  return (
    <ForexPortfolioPage
      symbols={["XAUUSD", "BTCUSD"]}
      title="BTC + ALTIN · OTONOM SCALPER KONSOLU"
    />
  );
}
