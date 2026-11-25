"use client";

import React, { useEffect, useRef } from "react";
import ForexNativeChart from "./ForexNativeChart";

export interface ForexCandidateMeta {
  symbol: string;
  display: string;
  name: string;
  category: string;
  price: number;
  bid: number;
  ask: number;
  spread_pips: number;
  score: number;
  trend: string;
  action: "BUY" | "SELL" | "HOLD";
  /** 5 dk RSI. Eski yanıtta yalnız `rsi_15m` olabilir; tik yoksa gelmez. */
  rsi_15m?: number | null;
  macd_verdict: string;
  cmo?: number;
  cci?: number;
  adx: number;
  supertrend_dir: number;
  htf_trend: string;
  /** Tik yoksa backend bu alanları göndermeyebilir. */
  pip_target?: number | null;
  stop_loss_pips?: number | null;
  risk_reward?: string | number | null;
  atr_pips: number;
  tv_symbol?: string;
  tier: "STRONG" | "ACTIVE" | "WATCH" | "WAIT";
  required_score?: number | null;
}

export interface ForexChartModalProps {
  candidate?: ForexCandidateMeta | null;
  symbol?: string | null;
  display?: string;
  action?: "BUY" | "SELL" | "HOLD";
  onClose: () => void;
  onOpenLotCalculator?: (symbol: string, slPips: number) => void;
}

function inferCategory(sym: string): string {
  const s = sym.toUpperCase();
  if (/BTC|ETH|XRP|SOL|BNB|LTC|DOGE/.test(s)) return "crypto";
  if (/XAU|XAG|GOLD|SILVER|OIL|WTI|BRENT|NGAS/.test(s)) return "commodity";
  if (/US30|NAS100|USTEC|SPX|US500|DAX|DE40|GER40|UK100|JP225/.test(s)) return "index";
  return "forex";
}

export default function ForexChartModal({
  candidate,
  symbol,
  display,
  action,
  onClose,
  onOpenLotCalculator,
}: ForexChartModalProps) {
  const dialogRef = useRef<HTMLDialogElement>(null);

  const resolvedSymbol = (candidate?.symbol || symbol || "").trim().toUpperCase();
  const resolvedDisplay = candidate?.display || display || resolvedSymbol;
  const resolvedCategory = candidate?.category || inferCategory(resolvedSymbol);
  const resolvedAction: "BUY" | "SELL" | "HOLD" = candidate?.action || action || "HOLD";
  const resolvedScore = candidate?.score ?? 0;
  const resolvedTier = candidate?.tier ?? "ACTIVE";
  const resolvedAdx = candidate?.adx ?? 0;
  const resolvedAtrPips = candidate?.atr_pips ?? 0;
  const resolvedHtfTrend = candidate?.htf_trend ?? "NEUTRAL";
  const resolvedMacdVerdict = candidate?.macd_verdict ?? "—";
  const resolvedRiskReward =
    candidate?.risk_reward == null ? undefined : String(candidate.risk_reward);
  const resolvedPipTarget = candidate?.pip_target ?? undefined;
  const resolvedStopLossPips = candidate?.stop_loss_pips ?? undefined;

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog || !resolvedSymbol) return;
    if (!dialog.open) {
      dialog.showModal();
    }
    return () => {
      if (dialog.open) {
        dialog.close();
      }
    };
  }, [resolvedSymbol]);

  if (!resolvedSymbol) return null;

  return (
    <dialog
      ref={dialogRef}
      aria-label={`${resolvedDisplay} Canlı Grafik`}
      onClose={onClose}
      onClick={(e) => {
        if (e.target === dialogRef.current) onClose();
      }}
      className="m-auto w-[calc(100vw-1rem)] sm:w-[calc(100vw-2rem)] max-w-6xl h-[92vh] max-h-[92vh] p-0 bg-transparent border-0 overflow-visible overscroll-contain backdrop:bg-black/80 backdrop:backdrop-blur-sm backdrop:overflow-hidden animate-in fade-in"
    >
      <div className="relative w-full h-full bg-bunker-950 rounded-2xl border border-bunker-700 shadow-2xl flex flex-col overflow-hidden">
        <ForexNativeChart
          symbol={resolvedSymbol}
          displayName={resolvedDisplay}
          category={resolvedCategory}
          action={resolvedAction}
          score={resolvedScore}
          tier={resolvedTier}
          adx={resolvedAdx}
          atrPips={resolvedAtrPips}
          htfTrend={resolvedHtfTrend}
          macdVerdict={resolvedMacdVerdict}
          riskReward={resolvedRiskReward}
          pipTarget={resolvedPipTarget}
          stopLossPips={resolvedStopLossPips}
          separatePageHref={`/forex/charts?symbol=${encodeURIComponent(resolvedSymbol)}`}
          onOpenLotCalculator={onOpenLotCalculator}
          onClose={onClose}
        />
      </div>
    </dialog>
  );
}
