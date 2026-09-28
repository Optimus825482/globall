"use client";

import React, { useEffect, useRef } from "react";

interface TradingViewWidgetProps {
  symbol?: string;
  interval?: string;
  theme?: "dark" | "light";
  height?: string | number;
  hideSideToolbar?: boolean;
}

export default function TradingViewWidget({
  symbol = "FX:EURUSD",
  interval = "15",
  theme = "dark",
  height = "100%",
  hideSideToolbar = true,
}: TradingViewWidgetProps) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!containerRef.current) return;
    containerRef.current.innerHTML = "";

    const script = document.createElement("script");
    script.src = "https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js";
    script.type = "text/javascript";
    script.async = true;
    script.innerHTML = JSON.stringify({
      autosize: true,
      symbol: symbol,
      interval: interval,
      timezone: "Europe/Istanbul",
      theme: theme,
      style: "1",
      locale: "tr",
      enable_publishing: false,
      allow_symbol_change: true,
      calendar: false,
      support_host: "https://www.tradingview.com",
      hide_top_toolbar: false,
      hide_side_toolbar: hideSideToolbar,
      save_image: false,
      backgroundColor: "rgba(7, 11, 20, 1)",
      gridColor: "rgba(30, 41, 59, 0.4)",
    });

    containerRef.current.appendChild(script);
  }, [symbol, interval, theme, hideSideToolbar]);

  return (
    <div className="tradingview-widget-container w-full h-full min-h-[300px]" style={{ height }}>
      <div ref={containerRef} className="tradingview-widget-container__widget w-full h-full" />
    </div>
  );
}
