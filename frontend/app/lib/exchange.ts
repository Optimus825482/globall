// Borsa kimliği — TEK kaynak, backend'den.
//
// Neden env değil: `NEXT_PUBLIC_QUOTE_ASSET` bir BUILD sabitidir. Frontend
// build'i ile backend'in konuştuğu borsa arasında uyuşmazlık olursa uygulama
// sağlıklı görünür ama yanlış borsanın sembollerini arar (sessiz bozulma).
// `/api/market-symbols` yanıtı `quote_asset` + `exchange` + `exchange_label`
// yayınlar; burada o değerler dinlenir ve yanlış eşleşme KULLANICIYA GÖRÜNÜR
// hâle getirilir (boş grafik değil, açık uyarı).
//
// `format.ts`'in aksine bu değerler CALISMA ANINDA gelir; sayfa yeniden
// yüklenmeden de güncellenir.

"use client";

import { createContext, useContext } from "react";
import { useEffect, useState } from "react";
import { API_BASE } from "./api";

export type ExchangeInfo = {
  /** TR→"TRY", Global→"USDT" */
  quoteAsset: string;
  /** "binance_tr" | "binance_global" | "?" (henüz bilinmiyor) */
  exchange: string;
  /** "Binance TR" | "Binance Global" */
  label: string;
  /** Backend'den henüz yanıt gelmedi (ilk yükleme) */
  loading: boolean;
  /** Backend'e ulaşılamadı — menü borsa adı gösteremiyor */
  error: boolean;
};

const UNKNOWN: ExchangeInfo = {
  quoteAsset: (process.env.NEXT_PUBLIC_QUOTE_ASSET || "TRY").toUpperCase(),
  exchange: process.env.NEXT_PUBLIC_QUOTE_ASSET === "USDT" ? "binance_global" : "binance_tr",
  label: process.env.NEXT_PUBLIC_QUOTE_ASSET === "USDT" ? "Binance Global" : "Binance TR",
  loading: false,
  error: true,
};

const ExchangeContext = createContext<ExchangeInfo>(UNKNOWN);

/** Borsa bilgisini bir kez çeker ve tüm ağaca dağıtır. */
export function useExchangeProvider() {
  const [info, setInfo] = useState<ExchangeInfo>({ ...UNKNOWN, loading: true });

  useEffect(() => {
    let alive = true;
    fetch(`${API_BASE}/api/market-symbols`, { credentials: "include" })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((d) => {
        if (!alive) return;
        setInfo({
          quoteAsset: String(d?.quote_asset || "TRY").toUpperCase(),
          exchange: String(d?.exchange || "?"),
          label: String(d?.exchange_label || "Borsa"),
          loading: false,
          error: false,
        });
      })
      .catch(() => {
        if (!alive) return;
        // Backend düşükse menü boş kalmasın: build-time tahmini gösterilir
        // ama `error` işareti menüde uyarı üretir.
        setInfo((prev) => ({ ...prev, loading: false, error: true }));
      });
    return () => { alive = false; };
  }, []);

  return { info, ExchangeContext };
}

export const useExchange = () => useContext(ExchangeContext);
