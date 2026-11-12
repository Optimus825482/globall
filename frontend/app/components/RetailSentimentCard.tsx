"use client";

// ============================================================================
// PERAKENDE KONUMLANMA TABLOSU (2026-11-12)
// Myfxbook topluluk outlook'u: hangi paritede kalabalık hangi tarafta,
// kalabalığın ortalama giriş maliyeti ve fiyata uzaklığı.
//
// KAPI DEĞİL, BAĞLAM: karar üretmez / sıralama değiştirmez.
// Kaynak ücretsiz API (15 dk tur, 100 istek/24s tavanı) → kart 5 dk'da bir okur,
// ağa çıkma işini backend yapar (arka plan rutini).
//
// İŞARET KURALI (Myfxbook ile aynı): KÂR yönü POZİTİF.
//   long kârda  = fiyat, ortalama long girişin ÜSTÜNDE
//   short kârda = fiyat, ortalama short girişin ALTINDA
// ============================================================================

import React, { useCallback, useState } from "react";
import { apiFetch } from "../lib/api";
import { usePolling } from "../lib/usePolling";
import { Card } from "./ui";

interface SentimentItem {
  symbol: string;
  long_pct: number;
  short_pct: number;
  positions: number;
  popularity: number;
  crowded: "LONG" | "SHORT" | null;
  price: number | null;
  price_is_live?: boolean;
  avg_long_price: number | null;
  avg_short_price: number | null;
  dist_long_pips: number | null;
  dist_short_pips: number | null;
}

interface SentimentSummary {
  available: boolean;
  reason?: string;
  age_min?: number | null;
  symbols?: number;
  crowd_pct?: number;
  calls_today?: number;
  daily_cap?: number;
  min_interval_min?: number;
}

function fmtPrice(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "—";
  const abs = Math.abs(v);
  if (abs >= 1000) return v.toFixed(2);
  if (abs >= 10) return v.toFixed(3);
  return v.toFixed(5);
}

function Pips({ value }: { value: number | null }) {
  if (value === null || value === undefined) return <span className="text-bunker-muted">—</span>;
  const tone = value > 0 ? "text-emerald-400" : value < 0 ? "text-rose-400" : "text-bunker-muted";
  return (
    <span className={`tabular-nums ${tone}`}>
      {value > 0 ? "+" : ""}
      {value.toFixed(0)} pip
    </span>
  );
}

export default function RetailSentimentCard() {
  const [items, setItems] = useState<SentimentItem[]>([]);
  const [summary, setSummary] = useState<SentimentSummary | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      const res = await apiFetch("/api/system/retail-sentiment?limit=12");
      setItems(Array.isArray(res?.items) ? res.items : []);
      setSummary(res?.summary ?? null);
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Perakende konumlanma okunamadı");
    }
  }, []);

  usePolling(load, 300000);

  const crowdPct = summary?.crowd_pct ?? 70;
  const crowded = items.filter((i) => i.crowded);

  return (
    <Card className="!p-0 overflow-hidden">
      <div className="flex flex-wrap items-baseline justify-between gap-2 border-b border-bunker-800 px-4 py-3 sm:px-5">
        <div>
          <p className="eyebrow">Market sentiment · perakende konumlanma</p>
          <h2 className="text-sm font-semibold">Kalabalık hangi tarafta?</h2>
        </div>
        <p className="text-2xs text-bunker-muted tabular-nums">
          {summary?.available
            ? `Myfxbook · ${summary.symbols ?? items.length} parite · ${summary.age_min ?? 0} dk önce` +
              (summary.calls_today !== undefined ? ` · kota ${summary.calls_today}/${summary.daily_cap}` : "")
            : "veri yok"}
        </p>
      </div>

      {error && <p className="px-4 py-3 text-xs text-rose-300 sm:px-5">{error}</p>}

      {!error && summary && !summary.available && (
        <p className="px-4 py-4 text-xs text-bunker-muted sm:px-5">
          {summary.reason || "Veri çekilemedi"} — kalabalık yönü okunamadı, tahmin edilmez.
        </p>
      )}

      {items.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[720px] text-xs">
            <thead>
              <tr className="border-b border-bunker-800 text-left text-2xs uppercase tracking-wide text-bunker-muted">
                <th className="px-4 py-2.5 font-medium sm:px-5">Sembol</th>
                <th className="px-3 py-2.5 font-medium">Topluluk trendi (short ↔ long)</th>
                <th className="hidden px-3 py-2.5 font-medium md:table-cell">Popülerlik</th>
                <th className="px-3 py-2.5 font-medium text-right">Ort. short / fiyata uzaklık</th>
                <th className="px-3 py-2.5 font-medium text-right">Ort. long / fiyata uzaklık</th>
                <th className="px-4 py-2.5 font-medium text-right sm:px-5">Fiyat</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-bunker-800">
              {items.map((it) => {
                const shortW = Math.max(0, Math.min(100, it.short_pct));
                const popW = Math.max(2, Math.min(100, it.popularity * 100));
                const hot = it.crowded !== null;
                return (
                  <tr key={it.symbol} className="align-middle">
                    <td className="px-4 py-2.5 font-semibold tabular-nums sm:px-5">
                      {it.symbol}
                      {hot && (
                        <span className="ml-1.5 rounded bg-amber-400/15 px-1 py-0.5 text-2xs font-medium text-amber-300">
                          %{it.crowded === "LONG" ? it.long_pct.toFixed(0) : it.short_pct.toFixed(0)} {it.crowded}
                        </span>
                      )}
                    </td>

                    {/* Topluluk trendi: sol kırmızı = SHORT, sağ yeşil = LONG (Myfxbook ile aynı) */}
                    <td className="px-3 py-2.5">
                      <div className="flex h-2 w-full max-w-[220px] overflow-hidden rounded-sm bg-bunker-800">
                        <div className="h-full bg-rose-500" style={{ width: `${shortW}%` }} />
                        <div className="h-full bg-emerald-500" style={{ width: `${100 - shortW}%` }} />
                      </div>
                      <p className="mt-1 text-2xs text-bunker-muted tabular-nums">
                        %{it.short_pct.toFixed(0)} short · %{it.long_pct.toFixed(0)} long
                      </p>
                    </td>

                    <td className="hidden px-3 py-2.5 md:table-cell">
                      <div className="h-2 w-full max-w-[140px] overflow-hidden rounded-sm bg-bunker-800">
                        <div className="h-full bg-amber-500/80" style={{ width: `${popW}%` }} />
                      </div>
                      <p className="mt-1 text-2xs text-bunker-muted tabular-nums">
                        {it.positions.toLocaleString("tr-TR")} pozisyon
                      </p>
                    </td>

                    <td className="px-3 py-2.5 text-right">
                      <div className="tabular-nums">{fmtPrice(it.avg_short_price)}</div>
                      <Pips value={it.dist_short_pips} />
                    </td>

                    <td className="px-3 py-2.5 text-right">
                      <div className="tabular-nums">{fmtPrice(it.avg_long_price)}</div>
                      <Pips value={it.dist_long_pips} />
                    </td>

                    <td className="px-4 py-2.5 text-right tabular-nums sm:px-5">
                      {fmtPrice(it.price)}
                      <p className="text-2xs text-bunker-muted">
                        {it.price_is_live ? "canlı" : "son kapanış"}
                      </p>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <p className="border-t border-bunker-800 px-4 py-2.5 text-2xs text-bunker-muted sm:px-5">
        Kalabalık eşiği %{crowdPct} (tek taraf). Bu bir <strong>filtre değil</strong>: karar akışını
        değiştirmez, LLM bağlamına ve bu tabloya bilgi olarak girer.
        {" "}Pozitif pip = o taraf kârda. Endeksler Myfxbook kapsamında yok.
        {crowded.length > 0 ? ` Bugün ${crowded.length} paritede kalabalık tek taraflı.` : ""}
      </p>
    </Card>
  );
}
