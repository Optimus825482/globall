"use client";

import React, { useEffect, useRef, useState, useCallback } from "react";
import {
  createChart,
  CandlestickSeries,
  LineSeries,
  IChartApi,
  ISeriesApi,
  IPriceLine,
  UTCTimestamp,
  LineStyle,
} from "lightweight-charts";
import { apiFetch } from "../../lib/api";
import { SUPERTREND_ENTRY } from "../../charts/IndicatorPicker";

export type Timeframe = "1m" | "5m" | "15m" | "30m" | "1h" | "4h" | "1d";

const TF_SECONDS: Record<Timeframe, number> = {
  "1m": 60,
  "5m": 300,
  "15m": 900,
  "30m": 1800,
  "1h": 3600,
  "4h": 14400,
  "1d": 86400,
};

type CandleBar = {
  time: UTCTimestamp;
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number;
};

export interface ForexNativeChartProps {
  symbol: string;
  displayName?: string;
  category?: string;
  initialTimeframe?: Timeframe;
  pipTarget?: number;
  stopLossPips?: number;
  action?: "BUY" | "SELL" | "HOLD";
  score?: number;
  tier?: string;
  adx?: number;
  atrPips?: number;
  htfTrend?: string;
  macdVerdict?: string;
  riskReward?: string;
  onOpenLotCalculator?: (symbol: string, slPips: number) => void;
  className?: string;
}

function formatPriceBySymbol(v?: number | null, symbol: string = ""): string {
  if (v == null || !Number.isFinite(v) || v <= 0) return "—";
  const s = symbol.toUpperCase();
  if (s.includes("JPY")) return v.toFixed(3);
  if (
    s.includes("XAU") ||
    s.includes("GOLD") ||
    s.includes("NAS") ||
    s.includes("US30") ||
    s.includes("SPX") ||
    s.includes("BTC") ||
    s.includes("ETH") ||
    s.includes("OIL")
  ) {
    return v.toFixed(2);
  }
  return v.toFixed(5);
}

function getSymbolPrecision(symbol: string = ""): number {
  const s = symbol.toUpperCase();
  if (s.includes("JPY")) return 3;
  if (
    s.includes("XAU") ||
    s.includes("GOLD") ||
    s.includes("NAS") ||
    s.includes("US30") ||
    s.includes("SPX") ||
    s.includes("BTC") ||
    s.includes("ETH") ||
    s.includes("OIL")
  ) {
    return 2;
  }
  return 5;
}

function calculateBollingerBands(candles: CandleBar[], period = 20, stdDevMultiplier = 2) {
  const upper: { time: UTCTimestamp; value: number }[] = [];
  const middle: { time: UTCTimestamp; value: number }[] = [];
  const lower: { time: UTCTimestamp; value: number }[] = [];

  if (candles.length < period) return { upper, middle, lower };

  for (let i = period - 1; i < candles.length; i++) {
    const slice = candles.slice(i - period + 1, i + 1);
    const sum = slice.reduce((acc, c) => acc + c.close, 0);
    const mean = sum / period;

    const variance = slice.reduce((acc, c) => acc + Math.pow(c.close - mean, 2), 0) / period;
    const stdDev = Math.sqrt(variance);

    const time = candles[i].time;
    middle.push({ time, value: mean });
    upper.push({ time, value: mean + stdDevMultiplier * stdDev });
    lower.push({ time, value: mean - stdDevMultiplier * stdDev });
  }

  return { upper, middle, lower };
}

function calculateEMA(candles: CandleBar[], period: number) {
  if (candles.length < period) return [];
  const k = 2 / (period + 1);
  const result: { time: UTCTimestamp; value: number }[] = [];

  let sum = 0;
  for (let i = 0; i < period; i++) {
    sum += candles[i].close;
  }
  let prevEma = sum / period;
  result.push({ time: candles[period - 1].time, value: prevEma });

  for (let i = period; i < candles.length; i++) {
    const curEma = (candles[i].close - prevEma) * k + prevEma;
    result.push({ time: candles[i].time, value: curEma });
    prevEma = curEma;
  }
  return result;
}

function calculateRSI(candles: CandleBar[], period = 14) {
  if (candles.length <= period) return [];
  const result: { time: UTCTimestamp; value: number }[] = [];
  let gains = 0;
  let losses = 0;

  for (let i = 1; i <= period; i++) {
    const diff = candles[i].close - candles[i - 1].close;
    if (diff >= 0) gains += diff;
    else losses += Math.abs(diff);
  }

  let avgGain = gains / period;
  let avgLoss = losses / period;

  const firstRs = avgLoss === 0 ? 100 : avgGain / avgLoss;
  const firstRsi = avgLoss === 0 ? 100 : 100 - 100 / (1 + firstRs);
  result.push({ time: candles[period].time, value: firstRsi });

  for (let i = period + 1; i < candles.length; i++) {
    const diff = candles[i].close - candles[i - 1].close;
    const curGain = diff > 0 ? diff : 0;
    const curLoss = diff < 0 ? Math.abs(diff) : 0;

    avgGain = (avgGain * (period - 1) + curGain) / period;
    avgLoss = (avgLoss * (period - 1) + curLoss) / period;

    const rs = avgLoss === 0 ? 100 : avgGain / avgLoss;
    const rsi = avgLoss === 0 ? 100 : 100 - 100 / (1 + rs);
    result.push({ time: candles[i].time, value: rsi });
  }
  return result;
}

export default function ForexNativeChart({
  symbol,
  displayName,
  category,
  initialTimeframe = "5m",
  pipTarget,
  stopLossPips,
  action,
  score,
  tier,
  adx,
  atrPips,
  htfTrend,
  macdVerdict,
  riskReward,
  onOpenLotCalculator,
  className = "",
}: ForexNativeChartProps) {
  const [timeframe, setTimeframe] = useState<Timeframe>(initialTimeframe);
  const [candles, setCandles] = useState<CandleBar[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Gösterge Aç/Kapat Durumları
  const [showBB, setShowBB] = useState(true);
  const [showSupertrend, setShowSupertrend] = useState(true);
  const [showEma, setShowEma] = useState(true);
  const [showTargets, setShowTargets] = useState(true);

  // Canlı Tick ve Geri Sayım
  const [livePrice, setLivePrice] = useState<number | null>(null);
  const [liveBid, setLiveBid] = useState<number | null>(null);
  const [liveAsk, setLiveAsk] = useState<number | null>(null);
  const [liveSpread, setLiveSpread] = useState<number | null>(null);
  const [lastTickDir, setLastTickDir] = useState<"up" | "down" | null>(null);
  const [countdown, setCountdown] = useState<number>(0);
  const [latestRsi, setLatestRsi] = useState<number | null>(null);

  // DOM & Grafik Referansları
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartApiRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);

  const upperBbRef = useRef<ISeriesApi<"Line"> | null>(null);
  const middleBbRef = useRef<ISeriesApi<"Line"> | null>(null);
  const lowerBbRef = useRef<ISeriesApi<"Line"> | null>(null);

  const supertrendSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const ema9SeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const ema21SeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const ema50SeriesRef = useRef<ISeriesApi<"Line"> | null>(null);

  const tpPriceLineRef = useRef<IPriceLine | null>(null);
  const slPriceLineRef = useRef<IPriceLine | null>(null);
  const entryPriceLineRef = useRef<IPriceLine | null>(null);

  const lastCandleRef = useRef<CandleBar | null>(null);
  const timeframeRef = useRef<Timeframe>(timeframe);
  timeframeRef.current = timeframe;

  // Mum Verisi Yükleme
  const loadKlines = useCallback(async (tf: Timeframe, silent = false) => {
    if (!silent) setLoading(true);
    setError(null);
    try {
      const data = await apiFetch(`/api/forex/klines?symbol=${encodeURIComponent(symbol)}&interval=${tf}&limit=250`);
      if (data && Array.isArray(data.candles) && data.candles.length > 0) {
        const parsed: CandleBar[] = data.candles.map((c: any) => ({
          time: Number(c.time) as UTCTimestamp,
          open: Number(c.open),
          high: Number(c.high),
          low: Number(c.low),
          close: Number(c.close),
          volume: Number(c.volume ?? 0),
        }));
        setCandles(parsed);
        lastCandleRef.current = parsed[parsed.length - 1];

        if (data.current_price) {
          setLivePrice(data.current_price);
        }

        const rsiArr = calculateRSI(parsed, 14);
        if (rsiArr.length > 0) {
          setLatestRsi(Math.round(rsiArr[rsiArr.length - 1].value * 10) / 10);
        }
      } else {
        if (!silent) setError("Bu sembol için mum verisi bulunamadı.");
      }
    } catch (err) {
      console.error("Forex kline getirme hatası:", err);
      if (!silent) setError("Veri akışında geçici kesinti oluştu.");
    } finally {
      if (!silent) setLoading(false);
    }
  }, [symbol]);

  useEffect(() => {
    setCandles([]);
    lastCandleRef.current = null;
    loadKlines(timeframe);
  }, [timeframe, loadKlines]);

  // Canlı veri polling (her 4 saniyede bir sessiz tazeleme)
  useEffect(() => {
    const timer = setInterval(() => {
      if (!document.hidden) {
        loadKlines(timeframeRef.current, true);
      }
    }, 4000);
    return () => clearInterval(timer);
  }, [loadKlines]);

  // Mum kapanış sayacı
  useEffect(() => {
    const tfSecs = TF_SECONDS[timeframe] || 300;
    const tick = () => {
      const nowSec = Math.floor(Date.now() / 1000);
      const last = lastCandleRef.current;
      if (last && Number(last.time) > 0) {
        const nextCandleSec = Number(last.time) + tfSecs;
        setCountdown(Math.max(0, nextCandleSec - nowSec));
      } else {
        setCountdown(tfSecs - (nowSec % tfSecs));
      }
    };
    tick();
    const interval = setInterval(tick, 1000);
    return () => clearInterval(interval);
  }, [timeframe, candles]);

  // Canlı Ticker Dinleme
  useEffect(() => {
    const fetchTicker = async () => {
      try {
        const res = await apiFetch(`/api/forex/tickers`);
        if (res && Array.isArray(res.tickers)) {
          const tick = res.tickers.find((t: any) => t.symbol === symbol.toUpperCase());
          if (tick) {
            if (tick.price && Math.abs(tick.price - (livePrice || 0)) > 1e-6) {
              setLastTickDir(livePrice != null && tick.price >= livePrice ? "up" : "down");
              setLivePrice(tick.price);
            }
            if (tick.bid) setLiveBid(tick.bid);
            if (tick.ask) setLiveAsk(tick.ask);
            if (tick.spread_pips != null) setLiveSpread(tick.spread_pips);

            if (candleSeriesRef.current && lastCandleRef.current) {
              const last = lastCandleRef.current;
              const updatedBar: CandleBar = {
                time: last.time,
                open: last.open,
                high: Math.max(last.high, tick.price),
                low: Math.min(last.low, tick.price),
                close: tick.price,
              };
              lastCandleRef.current = updatedBar;
              try {
                candleSeriesRef.current.update(updatedBar as any);
              } catch {}
            }
          }
        }
      } catch {}
    };
    const t = setInterval(fetchTicker, 2500);
    return () => clearInterval(t);
  }, [symbol, livePrice]);

  // Grafik Tuvalini Başlat (lightweight-charts)
  useEffect(() => {
    if (!chartContainerRef.current) return;

    const precision = getSymbolPrecision(symbol);
    const minMove = Math.pow(10, -precision);

    const chart = createChart(chartContainerRef.current, {
      width: chartContainerRef.current.clientWidth,
      height: chartContainerRef.current.clientHeight || 500,
      layout: {
        background: { color: "#080c14" },
        textColor: "#94a3b8",
        fontFamily: "'JetBrains Mono', monospace, ui-monospace, sans-serif",
      },
      grid: {
        vertLines: { color: "rgba(30, 41, 59, 0.45)" },
        horzLines: { color: "rgba(30, 41, 59, 0.45)" },
      },
      crosshair: {
        mode: 0,
        vertLine: { color: "#00f3ff", width: 1, style: LineStyle.Dotted },
        horzLine: { color: "#00f3ff", width: 1, style: LineStyle.Dotted },
      },
      timeScale: {
        timeVisible: true,
        secondsVisible: false,
        borderColor: "#1e293b",
      },
      rightPriceScale: {
        borderColor: "#1e293b",
        scaleMargins: { top: 0.12, bottom: 0.12 },
      },
    });

    chartApiRef.current = chart;

    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: "#10b981",
      downColor: "#f43f5e",
      borderVisible: false,
      wickUpColor: "#10b981",
      wickDownColor: "#f43f5e",
      priceFormat: {
        type: "price",
        precision,
        minMove,
      },
    });
    candleSeriesRef.current = candleSeries;

    const upperBb = chart.addSeries(LineSeries, {
      color: "rgba(56, 189, 248, 0.75)",
      lineWidth: 1,
      title: "BB Üst",
      priceLineVisible: false,
      lastValueVisible: false,
    });
    const middleBb = chart.addSeries(LineSeries, {
      color: "rgba(245, 158, 11, 0.75)",
      lineWidth: 1,
      lineStyle: LineStyle.Dashed,
      title: "BB Orta",
      priceLineVisible: false,
      lastValueVisible: false,
    });
    const lowerBb = chart.addSeries(LineSeries, {
      color: "rgba(56, 189, 248, 0.75)",
      lineWidth: 1,
      title: "BB Alt",
      priceLineVisible: false,
      lastValueVisible: false,
    });
    upperBbRef.current = upperBb;
    middleBbRef.current = middleBb;
    lowerBbRef.current = lowerBb;

    const supertrendSeries = chart.addSeries(LineSeries, {
      lineWidth: 2,
      title: "SuperTrend",
      priceLineVisible: false,
      lastValueVisible: true,
    });
    supertrendSeriesRef.current = supertrendSeries;

    const ema9 = chart.addSeries(LineSeries, {
      color: "#3b82f6",
      lineWidth: 1,
      title: "EMA 9",
      priceLineVisible: false,
      lastValueVisible: false,
    });
    const ema21 = chart.addSeries(LineSeries, {
      color: "#a855f7",
      lineWidth: 1,
      title: "EMA 21",
      priceLineVisible: false,
      lastValueVisible: false,
    });
    const ema50 = chart.addSeries(LineSeries, {
      color: "#f97316",
      lineWidth: 1,
      title: "EMA 50",
      priceLineVisible: false,
      lastValueVisible: false,
    });
    ema9SeriesRef.current = ema9;
    ema21SeriesRef.current = ema21;
    ema50SeriesRef.current = ema50;

    const handleResize = () => {
      if (chartContainerRef.current && chartApiRef.current) {
        const w = chartContainerRef.current.clientWidth;
        const h = chartContainerRef.current.clientHeight;
        if (w > 0 && h > 0) {
          chartApiRef.current.applyOptions({
            width: w,
            height: h,
          });
        }
      }
    };
    window.addEventListener("resize", handleResize);

    let resizeObserver: ResizeObserver | null = null;
    if (typeof ResizeObserver !== "undefined" && chartContainerRef.current) {
      resizeObserver = new ResizeObserver(() => {
        handleResize();
      });
      resizeObserver.observe(chartContainerRef.current);
    }

    return () => {
      window.removeEventListener("resize", handleResize);
      if (resizeObserver) resizeObserver.disconnect();
      chart.remove();
      chartApiRef.current = null;
      candleSeriesRef.current = null;
    };
  }, [symbol]);

  // Mum Verilerini ve Göstergeleri Grafiğe Bas
  useEffect(() => {
    if (!candleSeriesRef.current || candles.length === 0) return;

    try {
      candleSeriesRef.current.setData(candles as any);
      chartApiRef.current?.timeScale().fitContent();
    } catch (e) {
      console.warn("Mum verisi basılırken uyarı:", e);
    }

    if (showBB && upperBbRef.current && middleBbRef.current && lowerBbRef.current) {
      const { upper, middle, lower } = calculateBollingerBands(candles, 20, 2);
      if (upper.length > 0) {
        upperBbRef.current.setData(upper as any);
        middleBbRef.current.setData(middle as any);
        lowerBbRef.current.setData(lower as any);
        upperBbRef.current.applyOptions({ visible: true });
        middleBbRef.current.applyOptions({ visible: true });
        lowerBbRef.current.applyOptions({ visible: true });
      }
    } else if (upperBbRef.current) {
      upperBbRef.current.applyOptions({ visible: false });
      middleBbRef.current?.applyOptions({ visible: false });
      lowerBbRef.current?.applyOptions({ visible: false });
    }

    if (showSupertrend && supertrendSeriesRef.current && candles.length > 10) {
      try {
        const res = SUPERTREND_ENTRY.calculate(candles, { period: 10, multiplier: 3 });
        const plot0 = res?.plots?.plot0 ?? [];
        if (plot0.length > 0) {
          const formatted = plot0.map((pt) => ({
            time: (pt.time > 1e11 ? Math.floor(pt.time / 1000) : Math.floor(pt.time)) as UTCTimestamp,
            value: pt.value,
            color: pt.color,
          }));
          supertrendSeriesRef.current.setData(formatted as any);
          supertrendSeriesRef.current.applyOptions({ visible: true });
        }
      } catch (e) {
        console.warn("Supertrend basılırken hata:", e);
      }
    } else if (supertrendSeriesRef.current) {
      supertrendSeriesRef.current.applyOptions({ visible: false });
    }

    if (showEma && ema9SeriesRef.current && ema21SeriesRef.current && ema50SeriesRef.current) {
      const e9 = calculateEMA(candles, 9);
      const e21 = calculateEMA(candles, 21);
      const e50 = calculateEMA(candles, 50);
      if (e9.length > 0) ema9SeriesRef.current.setData(e9 as any);
      if (e21.length > 0) ema21SeriesRef.current.setData(e21 as any);
      if (e50.length > 0) ema50SeriesRef.current.setData(e50 as any);
      ema9SeriesRef.current.applyOptions({ visible: true });
      ema21SeriesRef.current.applyOptions({ visible: true });
      ema50SeriesRef.current.applyOptions({ visible: true });
    } else if (ema9SeriesRef.current) {
      ema9SeriesRef.current.applyOptions({ visible: false });
      ema21SeriesRef.current?.applyOptions({ visible: false });
      ema50SeriesRef.current?.applyOptions({ visible: false });
    }
  }, [candles, showBB, showSupertrend, showEma]);

  // Hedef ve Stop Çizgileri
  useEffect(() => {
    if (!candleSeriesRef.current) return;
    const series = candleSeriesRef.current;

    if (tpPriceLineRef.current) {
      try { series.removePriceLine(tpPriceLineRef.current); } catch {}
      tpPriceLineRef.current = null;
    }
    if (slPriceLineRef.current) {
      try { series.removePriceLine(slPriceLineRef.current); } catch {}
      slPriceLineRef.current = null;
    }
    if (entryPriceLineRef.current) {
      try { series.removePriceLine(entryPriceLineRef.current); } catch {}
      entryPriceLineRef.current = null;
    }

    if (!showTargets) return;

    const basePrice = livePrice || (candles.length > 0 ? candles[candles.length - 1].close : null);
    if (!basePrice) return;

    const isBuy = action === "BUY";
    const pipMultiplier = symbol.includes("JPY")
      ? 0.01
      : symbol.includes("XAU") || symbol.includes("GOLD")
      ? 0.1
      : 0.0001;

    let calculatedTp = 0;
    let calculatedSl = 0;
    if (pipTarget && pipTarget > 0) {
      calculatedTp = isBuy
        ? basePrice + pipTarget * pipMultiplier
        : basePrice - pipTarget * pipMultiplier;
    }
    if (stopLossPips && stopLossPips > 0) {
      calculatedSl = isBuy
        ? basePrice - stopLossPips * pipMultiplier
        : basePrice + stopLossPips * pipMultiplier;
    }

    entryPriceLineRef.current = series.createPriceLine({
      price: basePrice,
      color: "#38bdf8",
      lineWidth: 1,
      lineStyle: LineStyle.Dashed,
      axisLabelVisible: true,
      title: `GİRİŞ / FİYAT ${formatPriceBySymbol(basePrice, symbol)}`,
    });

    if (calculatedTp > 0) {
      tpPriceLineRef.current = series.createPriceLine({
        price: calculatedTp,
        color: "#10b981",
        lineWidth: 1,
        lineStyle: LineStyle.Dotted,
        axisLabelVisible: true,
        title: `HEDEF TP (+${pipTarget}p)`,
      });
    }

    if (calculatedSl > 0) {
      slPriceLineRef.current = series.createPriceLine({
        price: calculatedSl,
        color: "#f43f5e",
        lineWidth: 1,
        lineStyle: LineStyle.Dotted,
        axisLabelVisible: true,
        title: `STOP SL (-${stopLossPips}p)`,
      });
    }
  }, [showTargets, livePrice, candles, pipTarget, stopLossPips, action, symbol]);

  return (
    <div className={`flex flex-col h-full w-full bg-bunker-950 font-mono select-none ${className}`}>
      {/* ÜST BİLGİ & KONTROL ÇUBUĞU */}
      <div className="p-3 bg-bunker-900/95 border-b border-bunker-800 flex flex-wrap items-center justify-between gap-3 shrink-0">
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2">
            <span className="text-base font-bold text-white tracking-wide">
              {displayName || symbol}
            </span>
            {category && (
              <span className="px-1.5 py-0.5 rounded text-[10px] font-bold uppercase bg-bunker-800 text-bunker-400 border border-bunker-700">
                {category}
              </span>
            )}
            {tier === "STRONG" && (
              <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-emerald-500/20 text-emerald-300 border border-emerald-400/40 animate-pulse">
                ⚡ GÜÇLÜ SİNYAL
              </span>
            )}
            {action === "BUY" && (
              <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-emerald-500/20 text-emerald-400 border border-emerald-500/30">
                ▲ AL
              </span>
            )}
            {action === "SELL" && (
              <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-rose-500/20 text-rose-400 border border-rose-500/30">
                ▼ SAT
              </span>
            )}
          </div>

          {/* Canlı Fiyat Rozeti */}
          <div className="flex items-center gap-2.5 bg-bunker-950 px-3 py-1 rounded-lg border border-bunker-800">
            <span className={`text-base font-black transition-colors ${
              lastTickDir === "up" ? "text-emerald-400" : lastTickDir === "down" ? "text-rose-400" : "text-white"
            }`}>
              {formatPriceBySymbol(livePrice, symbol)}
            </span>
            {liveBid != null && liveAsk != null && (
              <span className="text-[11px] text-bunker-muted hidden md:inline">
                ({formatPriceBySymbol(liveBid, symbol)} / {formatPriceBySymbol(liveAsk, symbol)})
              </span>
            )}
            {liveSpread != null && (
              <span className="text-[11px] text-cyan-400 font-bold border-l border-bunker-800 pl-2">
                {liveSpread}p
              </span>
            )}
          </div>
        </div>

        {/* Aksiyonlar (Lot hesapla vb.) */}
        <div className="flex items-center gap-2">
          {onOpenLotCalculator && (
            <button
              type="button"
              onClick={() => onOpenLotCalculator(symbol, stopLossPips || 20)}
              className="px-2.5 py-1 rounded-lg bg-blue-500/15 border border-blue-400/30 text-blue-300 text-xs font-bold hover:bg-blue-500/25 transition-all"
            >
              🧮 Lot Hesapla
            </button>
          )}
        </div>
      </div>

      {/* PERİYOT & GÖSTERGE SEÇİCİ */}
      <div className="px-3 py-1.5 bg-bunker-950/90 border-b border-bunker-800/80 flex flex-wrap items-center justify-between gap-2 text-xs shrink-0">
        <div className="flex items-center gap-1">
          <span className="text-[10px] text-bunker-muted mr-1">Periyot:</span>
          {(["1m", "5m", "15m", "30m", "1h", "4h", "1d"] as Timeframe[]).map((tf) => (
            <button
              key={tf}
              type="button"
              onClick={() => setTimeframe(tf)}
              className={`px-2 py-0.5 rounded text-xs font-bold transition-all ${
                timeframe === tf
                  ? "bg-blue-600 text-white shadow-[0_0_8px_rgba(37,99,235,0.4)] border border-blue-400"
                  : "bg-bunker-900 text-bunker-muted border border-bunker-800 hover:text-white"
              }`}
            >
              {tf}
            </button>
          ))}
        </div>

        <div className="flex items-center gap-1.5 overflow-x-auto">
          <button
            type="button"
            onClick={() => setShowBB(!showBB)}
            className={`px-2 py-0.5 rounded text-[11px] font-bold border transition-all ${
              showBB
                ? "bg-cyan-500/20 text-cyan-300 border-cyan-400/40"
                : "bg-bunker-900 text-bunker-muted border-bunker-800 opacity-60"
            }`}
          >
            BB
          </button>
          <button
            type="button"
            onClick={() => setShowSupertrend(!showSupertrend)}
            className={`px-2 py-0.5 rounded text-[11px] font-bold border transition-all ${
              showSupertrend
                ? "bg-emerald-500/20 text-emerald-300 border-emerald-400/40"
                : "bg-bunker-900 text-bunker-muted border-bunker-800 opacity-60"
            }`}
          >
            SuperTrend
          </button>
          <button
            type="button"
            onClick={() => setShowEma(!showEma)}
            className={`px-2 py-0.5 rounded text-[11px] font-bold border transition-all ${
              showEma
                ? "bg-purple-500/20 text-purple-300 border-purple-400/40"
                : "bg-bunker-900 text-bunker-muted border-bunker-800 opacity-60"
            }`}
          >
            EMA 9/21/50
          </button>
          <button
            type="button"
            onClick={() => setShowTargets(!showTargets)}
            className={`px-2 py-0.5 rounded text-[11px] font-bold border transition-all ${
              showTargets
                ? "bg-amber-500/20 text-amber-300 border-amber-400/40"
                : "bg-bunker-900 text-bunker-muted border-bunker-800 opacity-60"
            }`}
          >
            TP/SL
          </button>
        </div>

        <div className="flex items-center gap-3 text-xs">
          {latestRsi !== null && (
            <span className="text-bunker-muted">
              RSI: <strong className={latestRsi > 70 ? "text-rose-400" : latestRsi < 30 ? "text-emerald-400" : "text-white"}>{latestRsi}</strong>
            </span>
          )}
          <div className="flex items-center gap-1.5 bg-bunker-900 px-2 py-0.5 rounded border border-bunker-800">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-ping" />
            <span className="text-[10px] text-bunker-muted">Kapanış:</span>
            <span className="font-bold text-white tabular-nums">
              {formatCountdown(countdown)}
            </span>
          </div>
        </div>
      </div>

      {/* GRAFİK TUVALİ */}
      <div className="relative flex-1 w-full bg-[#080c14] overflow-hidden min-h-[420px]">
        {loading && (
          <div className="absolute inset-0 z-10 flex flex-col items-center justify-center bg-black/60 backdrop-blur-sm gap-2">
            <div className="w-8 h-8 border-2 border-blue-400 border-t-transparent rounded-full animate-spin" />
            <p className="text-xs text-blue-300 font-bold">Mum verisi yükleniyor…</p>
          </div>
        )}

        {error && (
          <div className="absolute inset-0 z-10 flex flex-col items-center justify-center bg-black/70 gap-3 p-4 text-center">
            <div className="text-3xl">⚠️</div>
            <p className="text-sm font-bold text-rose-400">{error}</p>
            <button
              type="button"
              onClick={() => loadKlines(timeframe)}
              className="px-3 py-1.5 rounded-lg bg-blue-600 text-white text-xs font-bold hover:bg-blue-500 transition-colors"
            >
              Tekrar Dene
            </button>
          </div>
        )}

        <div ref={chartContainerRef} className="w-full h-full" />
      </div>

      {/* ALT BİLGİ ŞERİDİ */}
      {(pipTarget != null || stopLossPips != null || score != null || adx != null) && (
        <div className="p-2.5 bg-bunker-900/90 border-t border-bunker-800 flex flex-wrap items-center justify-between gap-3 text-xs shrink-0">
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
            {pipTarget != null && (
              <span className="text-bunker-muted">
                Hedef TP: <strong className="text-emerald-400">+{pipTarget}p</strong>
              </span>
            )}
            {stopLossPips != null && (
              <span className="text-bunker-muted">
                Stop SL: <strong className="text-rose-400">-{stopLossPips}p</strong>
              </span>
            )}
            {riskReward && (
              <span className="text-bunker-muted">
                R/R: <strong className="text-white">{riskReward}</strong>
              </span>
            )}
            {atrPips != null && (
              <span className="text-bunker-muted">
                ATR: <strong className="text-cyan-400">{atrPips}p</strong>
              </span>
            )}
            {adx != null && (
              <span className="text-bunker-muted">
                ADX: <strong className={adx >= 25 ? "text-emerald-400" : "text-yellow-400"}>{adx.toFixed(0)}</strong>
              </span>
            )}
            {htfTrend && (
              <span className="text-bunker-muted">
                HTF: <strong className="text-white">{htfTrend}</strong>
              </span>
            )}
          </div>
          {macdVerdict && (
            <div className="text-[11px] text-bunker-muted">
              {macdVerdict}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function formatCountdown(sec: number): string {
  if (sec <= 0) return "00:00";
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}
