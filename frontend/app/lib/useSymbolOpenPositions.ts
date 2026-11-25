"use client";

import { useCallback, useEffect, useState } from "react";
import { LineStyle, type IPriceLine, type ISeriesApi } from "lightweight-charts";
import { apiFetch } from "./api";
import { useLiveMessages, type LiveMessage } from "./liveSocket";
import { usePolling } from "./usePolling";

export interface ChartOpenPosition {
  id: string;
  symbol: string;
  direction: "BUY" | "SELL";
  entryPrice: number;
  slPrice: number | null;
  tpPrice: number | null;
  lots: number | null;
  pnlUsd: number | null;
  pnlPips: number | null;
  source: "MT5" | "PAPER";
}

function normSym(raw: unknown): string {
  const s = String(raw || "")
    .toUpperCase()
    .replace(/[^A-Z0-9]/g, "");
  if (s.endsWith("USDT") && s.length > 4) return `${s.slice(0, -4)}USD`;
  return s;
}

function toNum(v: unknown): number | null {
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

function extractPositionsForSymbol(payload: any, targetSym: string): ChartOpenPosition[] {
  if (!payload || !targetSym) return [];
  const target = normSym(targetSym);
  if (!target) return [];

  const out: ChartOpenPosition[] = [];
  const seen = new Set<string>();

  const pushList = (list: any, source: "MT5" | "PAPER") => {
    if (!Array.isArray(list)) return;
    for (const p of list) {
      if (!p || typeof p !== "object") continue;
      if (normSym(p.symbol) !== target) continue;
      const entry = toNum(p.entry_price ?? p.open_price ?? p.price_open);
      if (entry == null || entry <= 0) continue;
      const dirRaw = String(p.direction ?? p.side ?? p.type ?? "BUY").toUpperCase();
      const direction: "BUY" | "SELL" = dirRaw.includes("SELL") || dirRaw === "SHORT" ? "SELL" : "BUY";
      const slRaw = toNum(p.sl_price ?? p.sl ?? p.stop_loss);
      const tpRaw = toNum(p.tp_price ?? p.tp ?? p.take_profit);
      const id = String(p.ticket ?? p.id ?? `${source}-${target}-${entry}`);
      const dedupeKey = `${source}:${id}`;
      if (seen.has(dedupeKey)) continue;
      seen.add(dedupeKey);
      out.push({
        id,
        symbol: target,
        direction,
        entryPrice: entry,
        slPrice: slRaw != null && slRaw > 0 ? slRaw : null,
        tpPrice: tpRaw != null && tpRaw > 0 ? tpRaw : null,
        lots: toNum(p.lots ?? p.volume ?? p.lot),
        pnlUsd: toNum(p.pnl_usd ?? p.profit ?? p.unrealized_pnl_usd),
        pnlPips: toNum(p.pnl_pips),
        source,
      });
    }
  };

  pushList(payload?.mt5?.open_positions, "MT5");
  pushList(payload?.open_positions, payload?.mt5?.connected ? "MT5" : "PAPER");
  return out;
}

/**
 * Verilen sembol için açık MT5 / Paper pozisyonlarını canlı (WS + 10sn yoklama) döndürür.
 * api.ts TTL önbelleği sayesinde çoklu grafik slotları tek HTTP isteğini paylaşır.
 */
export function useSymbolOpenPositions(symbol: string, enabled: boolean = true): ChartOpenPosition[] {
  const [positions, setPositions] = useState<ChartOpenPosition[]>([]);

  const load = useCallback(async () => {
    if (!enabled || !symbol) {
      setPositions([]);
      return;
    }
    try {
      const data = await apiFetch("/api/forex/auto-paper/status");
      setPositions(extractPositionsForSymbol(data, symbol));
    } catch {
      // Sessiz: grafik mum akışını kesme
    }
  }, [symbol, enabled]);

  useEffect(() => {
    void load();
  }, [load]);

  usePolling(load, enabled && symbol ? 10_000 : null);

  useLiveMessages(
    useCallback(
      (msg: LiveMessage) => {
        if (!enabled || !symbol) return;
        if (msg?.type === "fx_state" && msg.data) {
          setPositions(extractPositionsForSymbol(msg.data, symbol));
        }
      },
      [symbol, enabled]
    )
  );

  return positions;
}

/**
 * Candlestick serisi üzerinde açık pozisyonların Giriş, SL ve TP çizgilerini senkronlar.
 */
export function syncPositionPriceLines(
  candleSeries: ISeriesApi<"Candlestick"> | null | undefined,
  linesRef: { current: IPriceLine[] },
  positions: ChartOpenPosition[]
): void {
  if (!candleSeries) return;
  for (const line of linesRef.current) {
    try {
      candleSeries.removePriceLine(line);
    } catch {
      // Seri yeniden kurulmuş olabilir
    }
  }
  linesRef.current = [];

  for (const pos of positions) {
    const isBuy = pos.direction === "BUY";
    const lotTxt = pos.lots != null ? ` ${pos.lots.toFixed(2)}` : "";
    const pnlTxt =
      pos.pnlUsd != null
        ? ` · ${pos.pnlUsd >= 0 ? "+" : "-"}$${Math.abs(pos.pnlUsd).toFixed(2)}`
        : "";
    try {
      const entryLine = candleSeries.createPriceLine({
        price: pos.entryPrice,
        color: isBuy ? "#06b6d4" : "#f97316",
        lineWidth: 2,
        lineStyle: LineStyle.Solid,
        axisLabelVisible: true,
        title: `${pos.direction}${lotTxt}${pnlTxt}`,
      });
      linesRef.current.push(entryLine);
    } catch {
      /* yoksay */
    }

    if (pos.slPrice != null && pos.slPrice > 0) {
      try {
        const slLine = candleSeries.createPriceLine({
          price: pos.slPrice,
          color: "#f43f5e",
          lineWidth: 1,
          lineStyle: LineStyle.Dashed,
          axisLabelVisible: true,
          title: `SL (${pos.direction})`,
        });
        linesRef.current.push(slLine);
      } catch {
        /* yoksay */
      }
    }

    if (pos.tpPrice != null && pos.tpPrice > 0) {
      try {
        const tpLine = candleSeries.createPriceLine({
          price: pos.tpPrice,
          color: "#10b981",
          lineWidth: 1,
          lineStyle: LineStyle.Dashed,
          axisLabelVisible: true,
          title: `TP (${pos.direction})`,
        });
        linesRef.current.push(tpLine);
      } catch {
        /* yoksay */
      }
    }
  }
}
