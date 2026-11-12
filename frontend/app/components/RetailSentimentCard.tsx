"use client";

// ============================================================================
// PERAKENDE KONUMLANMA KARTI (2026-11-12)
// Myfxbook topluluk outlook'u: hangi paritede kalabalık hangi tarafta.
// KAPI DEĞİL, BAĞLAM: karar üretmez; "herkes aynı tarafta" bilgisini sayıyla verir.
// Kaynak ücretsiz API (30 dk tur, 100 istek/24s) → bu kart 5 dk'da bir okur,
// ağa çıkma işini backend yapar.
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
  crowded: "LONG" | "SHORT" | null;
}

interface SentimentSummary {
  available: boolean;
  reason?: string;
  symbol?: string | null;
  note?: string;
  age_min?: number | null;
  symbols?: number;
  crowd_pct?: number;
  calls_today?: number;
  daily_cap?: number;
}

export default function RetailSentimentCard() {
  const [items, setItems] = useState<SentimentItem[]>([]);
  const [summary, setSummary] = useState<SentimentSummary | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      const res = await apiFetch("/api/system/retail-sentiment?limit=10");
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
          <p className="eyebrow">Perakende konumlanma</p>
          <h2 className="text-sm font-semibold">Kalabalık hangi tarafta?</h2>
        </div>
        <p className="text-2xs text-bunker-muted tabular-nums">
          {summary?.available
            ? `Myfxbook · ${summary.symbols ?? items.length} parite · ${summary.age_min ?? 0} dk önce`
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
        <ul className="divide-y divide-bunker-800">
          {items.map((it) => {
            const longW = Math.max(0, Math.min(100, it.long_pct));
            const hot = it.crowded !== null;
            return (
              <li key={it.symbol} className="px-4 py-2.5 sm:px-5">
                <div className="flex items-center justify-between gap-3 text-xs">
                  <span className="font-semibold tabular-nums">{it.symbol}</span>
                  <span className={`tabular-nums ${hot ? "font-semibold text-amber-300" : "text-bunker-muted"}`}>
                    %{it.long_pct.toFixed(0)} long · %{it.short_pct.toFixed(0)} short
                    {hot ? ` · KALABALIK ${it.crowded}` : ""}
                  </span>
                </div>
                {/* Uzun/kısa oranı tek çubukta: sol yeşil long, sağ kırmızı short */}
                <div className="mt-1.5 flex h-1.5 w-full overflow-hidden rounded-full bg-emerald-500/70">
                  <div className="h-full bg-emerald-500" style={{ width: `${longW}%` }} />
                  <div className="h-full bg-rose-500/80" style={{ width: `${100 - longW}%` }} />
                </div>
                <p className="mt-1 text-2xs text-bunker-muted tabular-nums">
                  {it.positions.toLocaleString("tr-TR")} açık pozisyon
                </p>
              </li>
            );
          })}
        </ul>
      )}

      <p className="border-t border-bunker-800 px-4 py-2.5 text-2xs text-bunker-muted sm:px-5">
        Kalabalık eşiği %{crowdPct} (tek taraf). Bu bir <strong>filtre değil</strong>: karar akışını
        değiştirmez, LLM bağlamına ve bu karta bilgi olarak girer.
        {summary?.available && crowded.length > 0
          ? ` Bugün ${crowded.length} paritede kalabalık tek taraflı.`
          : ""}
      </p>
    </Card>
  );
}
