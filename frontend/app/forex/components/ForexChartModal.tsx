"use client";

import React, { useEffect } from "react";
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
  rsi_15m: number;
  macd_verdict: string;
  cmo?: number;
  cci?: number;
  adx: number;
  supertrend_dir: number;
  htf_trend: string;
  pip_target: number;
  stop_loss_pips: number;
  risk_reward: string;
  atr_pips: number;
  tv_symbol?: string;
  tier: "STRONG" | "ACTIVE" | "WATCH" | "WAIT";
  required_score?: number;
}

interface ForexChartModalProps {
  candidate: ForexCandidateMeta;
  onClose: () => void;
  onOpenLotCalculator?: (symbol: string, slPips: number) => void;
}

export default function ForexChartModal({
  candidate,
  onClose,
  onOpenLotCalculator,
}: ForexChartModalProps) {
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-2 sm:p-4 bg-black/80 backdrop-blur-sm animate-in fade-in"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="relative w-full max-w-6xl h-[92vh] bg-bunker-950 rounded-2xl border border-bunker-700 shadow-2xl flex flex-col overflow-hidden">
        <ForexNativeChart
          symbol={candidate.symbol}
          displayName={candidate.display}
          category={candidate.category}
          action={candidate.action}
          score={candidate.score}
          tier={candidate.tier}
          adx={candidate.adx}
          atrPips={candidate.atr_pips}
          htfTrend={candidate.htf_trend}
          macdVerdict={candidate.macd_verdict}
          riskReward={candidate.risk_reward}
          pipTarget={candidate.pip_target}
          stopLossPips={candidate.stop_loss_pips}
          separatePageHref={`/forex/charts?symbol=${candidate.tv_symbol || candidate.symbol}`}
          onOpenLotCalculator={onOpenLotCalculator}
          onClose={onClose}
        />
      </div>
    </div>
  );
}
