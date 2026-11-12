"use client";

// ============================================================================
// BİLEŞİK SENTIMENT GÖSTERGESİ (2026-11-12)
// Merkez 0: sol = SHORT, sağ = LONG. Çubuk merkezden skora doğru dolar.
//
// Skor dört kanaldan: açıklanmış ekonomik veri (24s, yaş ağırlıklı), CFTC
// pozisyonlanması, küresel nabız (DXY/10Y/VIX/S&P), perakende kalabalığı (ters).
// AĞIRLIKLAR YARGIDIR — kanıt değil. Bu bir KAPI DEĞİL: karar akışını değiştirmez.
// ============================================================================

import React, { useCallback, useState } from "react";
import { apiFetch } from "../lib/api";
import { usePolling } from "../lib/usePolling";
import { Card } from "./ui";

interface Component {
  score: number | null;
  detail?: string | null;
  available: boolean;
  events?: number;
  long_pct?: number;
}

interface IndexItem {
  symbol: string;
  score: number;
  label: string;
  coverage: number;
  missing: string[];
  components: Record<string, Component>;
  error?: string;
}

const COMP_LABEL: Record<string, string> = {
  takvim: "Veri",
  cot: "COT",
  kuresel: "Küresel",
  perakende: "Kalabalık",
};

/** Merkez 0 gauge: negatifte sola kırmızı, pozitifte sağa yeşil dolar.
 *  Skor + etiket **çubuğun ortasında** okunur (2026-11-12: sağ üstteki küçük
 *  yazı yerine çubuğun içine, belirgin biçimde). Metin, dolgu renginden bağımsız
 *  okunabilsin diye yarı saydam koyu bir kapsül üstünde durur.
 */
function Gauge({ score, label }: { score: number; label: string }) {
  const pct = Math.max(0, Math.min(100, Math.abs(score)));
  const positive = score >= 0;
  // AÇIK temada da okunur: metin koyu, kapsül beyazımsı (doygun dolgu üstünde).
  const tone =
    score >= 45 ? "text-emerald-700" : score <= -45 ? "text-rose-700" : "text-bunker-800";
  return (
    <div className="relative h-8 w-full overflow-hidden rounded-sm border border-bunker-700/40 bg-bunker-800/40">
      {/* dolgu: merkezden skora doğru */}
      <div
        className={`absolute inset-y-0 ${positive ? "left-1/2 bg-emerald-500" : "right-1/2 bg-rose-500"}`}
        style={{ width: `${pct / 2}%` }}
      />
      {/* merkez işareti (0) */}
      <div className="absolute inset-y-0 left-1/2 w-px -translate-x-1/2 bg-bunker-100/40" />
      {/* skor + etiket — çubuğun ORTASINDA, belirgin */}
      <div className="absolute inset-0 flex items-center justify-center">
        <span
          className={`max-w-[92%] truncate whitespace-nowrap rounded border border-bunker-700/30
                      bg-white/92 px-2.5 py-[3px] text-[11px] font-bold tabular-nums tracking-wide
                      shadow-sm sm:text-xs dark:bg-bunker-900/85 dark:text-white ${tone}`}
          title={`${score > 0 ? "+" : ""}${score.toFixed(0)} · ${label}`}
        >
          {score > 0 ? "+" : ""}
          {score.toFixed(0)}
          <span className="ml-1.5 font-semibold">{label}</span>
        </span>
      </div>
    </div>
  );
}

export default function SentimentGaugeCard() {
  const [items, setItems] = useState<IndexItem[]>([]);
  const [error, setError] = useState("");
  const [weights, setWeights] = useState<Record<string, number>>({});

  const load = useCallback(async () => {
    try {
      const res = await apiFetch("/api/system/sentiment-index?limit=20");
      setItems(Array.isArray(res?.items) ? res.items : []);
      setWeights(res?.weights ?? {});
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sentiment endeksi okunamadı");
    }
  }, []);

  usePolling(load, 120000);

  return (
    <Card className="!p-0 overflow-hidden">
      <div className="flex flex-wrap items-baseline justify-between gap-2 border-b border-bunker-800 px-4 py-3 sm:px-5">
        <div>
          <p className="eyebrow">Market sentiment · bileşik endeks</p>
          <h2 className="text-sm font-semibold">Sol SHORT · merkez 0 · sağ LONG</h2>
        </div>
        <p className="text-2xs text-bunker-muted">
          Haber/veri + COT + küresel nabız + kalabalık
        </p>
      </div>

      {error && <p className="px-4 py-3 text-xs text-rose-300 sm:px-5">{error}</p>}

      {items.length === 0 && !error && (
        <p className="px-4 py-4 text-xs text-bunker-muted sm:px-5">Veri yükleniyor…</p>
      )}

      {items.length > 0 && (
        <ul className="divide-y divide-bunker-800">
          {items.map((it) => (
            <li key={it.symbol} className="px-4 py-3 sm:px-5">
              <div className="flex items-center justify-between gap-3">
                <span className="text-xs font-semibold tabular-nums">{it.symbol}</span>
                <span className="flex items-center gap-2 text-2xs text-bunker-muted">
                  <span
                    className={`rounded px-1 py-0.5 tabular-nums ${
                      it.coverage >= 0.75
                        ? "bg-emerald-500/10 text-emerald-300"
                        : it.coverage >= 0.5
                          ? "bg-amber-400/10 text-amber-300"
                          : "bg-rose-500/10 text-rose-300"
                    }`}
                    title={`Kapsam: hangi bileşenlerin verisi var (${it.missing.join(", ") || "tam"})`}
                  >
                    %{Math.round(it.coverage * 100)}
                  </span>
                </span>
              </div>

              <div className="mt-2">
                <Gauge score={it.score} label={it.label} />
                <div className="mt-1 flex justify-between text-[10px] text-bunker-muted sm:text-2xs">
                  <span>−100 SHORT</span>
                  <span>0</span>
                  <span>LONG +100</span>
                </div>
              </div>

              <div className="mt-2 flex flex-wrap gap-1.5">
                {Object.entries(it.components).map(([key, c]) => (
                  <span
                    key={key}
                    title={c.available ? (c.detail || "") : `veri yok · ${it.missing.includes(key) ? "kapsam dışı" : ""}`}
                    className={`rounded px-1.5 py-0.5 text-2xs tabular-nums ${
                      c.available
                        ? (c.score ?? 0) >= 0
                          ? "bg-emerald-500/10 text-emerald-300"
                          : "bg-rose-500/10 text-rose-300"
                        : "bg-bunker-800 text-bunker-muted"
                    }`}
                  >
                    {COMP_LABEL[key] || key}{" "}
                    {c.available && c.score !== null ? `${c.score > 0 ? "+" : ""}${c.score.toFixed(0)}` : "—"}
                  </span>
                ))}
              </div>
            </li>
          ))}
        </ul>
      )}

      <p className="border-t border-bunker-800 px-4 py-2.5 text-2xs text-bunker-muted sm:px-5">
        Ağırlıklar:{" "}
        {Object.entries(weights)
          .map(([k, v]) => `${COMP_LABEL[k] || k} ${Math.round(v * 100)}%`)
          .join(" · ")}
        . Kapsam %100&apos;ün altındaysa eksik bileşen skora katılmaz — nötr sayılmaz.
        Bu bir <strong>filtre değil</strong>; ağırlıklar yargıdır, ölçülmüş kenar değildir.
      </p>
    </Card>
  );
}
