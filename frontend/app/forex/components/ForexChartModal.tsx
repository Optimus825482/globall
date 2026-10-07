"use client";

import React, { useEffect, useRef, useState, useCallback, useMemo } from "react";
import Link from "next/link";
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

type Timeframe = "1m" | "5m" | "15m" | "30m" | "1h" | "4h" | "1d";

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

function formatForexPrice(v?: number | null, symbol: string = ""): string {
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

function getPrecision(symbol: string = ""): number {
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

// Basit Bollinger Bantları Hesabı (Periyot: 20, StdDev: 2)
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

// EMA Hesaplayıcı
function calculateEMA(candles: CandleBar[], period: number) {
  if (candles.length < period) return [];
  const k = 2 / (period + 1);
  const result: { time: UTCTimestamp; value: number }[] = [];
  
  // İlk EMA SMA olarak başlar
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

// RSI Hesaplayıcı
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

export default function ForexChartModal({
  candidate,
  onClose,
  onOpenLotCalculator,
}: ForexChartModalProps) {
  const [timeframe, setTimeframe] = useState<Timeframe>("5m");
  const [candles, setCandles] = useState<CandleBar[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Gösterge Aç/Kapat Durumları
  const [showBB, setShowBB] = useState(true);
  const [showSupertrend, setShowSupertrend] = useState(true);
  const [showEma, setShowEma] = useState(true);
  const [showTargets, setShowTargets] = useState(true);

  // Canlı Tick ve Geri Sayım
  const [livePrice, setLivePrice] = useState<number>(candidate.price);
  const [liveBid, setLiveBid] = useState<number>(candidate.bid);
  const [liveAsk, setLiveAsk] = useState<number>(candidate.ask);
  const [lastTickDir, setLastTickDir] = useState<"up" | "down" | null>(null);
  const [countdown, setCountdown] = useState<number>(0);
  const [latestRsi, setLatestRsi] = useState<number | null>(candidate.rsi_15m);

  // Referanslar
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
  const timeframeRef = useRef<Timeframe>("5m");
  timeframeRef.current = timeframe;

  // ESC tuşu ile kapatma
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  // Mum Verisi Yükleme
  const loadKlines = useCallback(async (tf: Timeframe, silent = false) => {
    if (!silent) setLoading(true);
    setError(null);
    try {
      const data = await apiFetch(`/api/forex/klines?symbol=${encodeURIComponent(candidate.symbol)}&interval=${tf}&limit=250`);
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

        // RSI Hesapla
        const rsiArr = calculateRSI(parsed, 14);
        if (rsiArr.length > 0) {
          setLatestRsi(roundNumber(rsiArr[rsiArr.length - 1].value, 1));
        }
      } else {
        if (!silent) setError("Bu parite için mum verisi alınamadı.");
      }
    } catch (err: any) {
      console.error("Forex kline getirme hatası:", err);
      if (!silent) setError("Veri akışında geçici kesinti oluştu.");
    } finally {
      if (!silent) setLoading(false);
    }
  }, [candidate.symbol]);

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
        const rem = Math.max(0, nextCandleSec - nowSec);
        setCountdown(rem);
      } else {
        // Fallback: periyot modülosu
        const rem = tfSecs - (nowSec % tfSecs);
        setCountdown(rem);
      }
    };
    tick();
    const interval = setInterval(tick, 1000);
    return () => clearInterval(interval);
  }, [timeframe, candles]);

  // Canlı Ticker Dinleme (güncel bid/ask)
  useEffect(() => {
    const fetchTicker = async () => {
      try {
        const res = await apiFetch(`/api/forex/tickers`);
        if (res && Array.isArray(res.tickers)) {
          const tick = res.tickers.find((t: any) => t.symbol === candidate.symbol);
          if (tick) {
            if (tick.price && Math.abs(tick.price - livePrice) > 1e-6) {
              setLastTickDir(tick.price >= livePrice ? "up" : "down");
              setLivePrice(tick.price);
            }
            if (tick.bid) setLiveBid(tick.bid);
            if (tick.ask) setLiveAsk(tick.ask);

            // Anlık muma fiyatı yansıt
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
  }, [candidate.symbol, livePrice]);

  // Grafik Tuvalini Başlat (lightweight-charts)
  useEffect(() => {
    if (!chartContainerRef.current) return;

    const precision = getPrecision(candidate.symbol);
    const minMove = Math.pow(10, -precision);

    const chart = createChart(chartContainerRef.current, {
      width: chartContainerRef.current.clientWidth,
      height: chartContainerRef.current.clientHeight || 520,
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

    // Mum Serisi
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

    // Bollinger Bantları
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

    // Supertrend Serisi
    const supertrendSeries = chart.addSeries(LineSeries, {
      lineWidth: 2,
      title: "SuperTrend",
      priceLineVisible: false,
      lastValueVisible: true,
    });
    supertrendSeriesRef.current = supertrendSeries;

    // EMA Serileri (9, 21, 50)
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

    // Boyut Değişimi Dinleyicisi
    const handleResize = () => {
      if (chartContainerRef.current && chartApiRef.current) {
        chartApiRef.current.applyOptions({
          width: chartContainerRef.current.clientWidth,
          height: chartContainerRef.current.clientHeight,
        });
      }
    };
    window.addEventListener("resize", handleResize);

    return () => {
      window.removeEventListener("resize", handleResize);
      chart.remove();
      chartApiRef.current = null;
      candleSeriesRef.current = null;
    };
  }, [candidate.symbol]);

  // Mum Verilerini ve Göstergeleri Grafiğe Bas
  useEffect(() => {
    if (!candleSeriesRef.current || candles.length === 0) return;

    try {
      candleSeriesRef.current.setData(candles as any);
      chartApiRef.current?.timeScale().fitContent();
    } catch (e) {
      console.warn("Mum verisi basılırken uyarı:", e);
    }

    // Bollinger Bantları
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

    // Supertrend
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

    // EMA (9, 21, 50)
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

  // Hedef ve Stop Çizgilerini Yönet (TP / SL / Giriş Fiyatı)
  useEffect(() => {
    if (!candleSeriesRef.current) return;
    const series = candleSeriesRef.current;

    // Temizle
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

    if (!showTargets || !candidate) return;

    const basePrice = livePrice || candidate.price;
    const isBuy = candidate.action === "BUY";
    const pipMultiplier = candidate.symbol.includes("JPY")
      ? 0.01
      : candidate.symbol.includes("XAU") || candidate.symbol.includes("GOLD")
      ? 0.1
      : 0.0001;

    // TP Fiyatı
    let calculatedTp = 0;
    let calculatedSl = 0;
    if (candidate.pip_target > 0) {
      calculatedTp = isBuy
        ? basePrice + candidate.pip_target * pipMultiplier
        : basePrice - candidate.pip_target * pipMultiplier;
    }
    if (candidate.stop_loss_pips > 0) {
      calculatedSl = isBuy
        ? basePrice - candidate.stop_loss_pips * pipMultiplier
        : basePrice + candidate.stop_loss_pips * pipMultiplier;
    }

    // Giriş çizgisi (mavi kesikli)
    entryPriceLineRef.current = series.createPriceLine({
      price: basePrice,
      color: "#38bdf8",
      lineWidth: 1,
      lineStyle: LineStyle.Dashed,
      axisLabelVisible: true,
      title: `GİRİŞ / TİK ${formatForexPrice(basePrice, candidate.symbol)}`,
    });

    // TP çizgisi (yeşil noktalı)
    if (calculatedTp > 0) {
      tpPriceLineRef.current = series.createPriceLine({
        price: calculatedTp,
        color: "#10b981",
        lineWidth: 1,
        lineStyle: LineStyle.Dotted,
        axisLabelVisible: true,
        title: `HEDEF TP (+${candidate.pip_target}p)`,
      });
    }

    // SL çizgisi (kırmızı noktalı)
    if (calculatedSl > 0) {
      slPriceLineRef.current = series.createPriceLine({
        price: calculatedSl,
        color: "#f43f5e",
        lineWidth: 1,
        lineStyle: LineStyle.Dotted,
        axisLabelVisible: true,
        title: `STOP SL (-${candidate.stop_loss_pips}p)`,
      });
    }
  }, [showTargets, candidate, livePrice]);

  const isBuy = candidate.action === "BUY";
  const isSell = candidate.action === "SELL";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-2 sm:p-4 bg-black/85 backdrop-blur-md animate-in fade-in duration-200">
      <div className="relative w-full max-w-6xl h-[92vh] flex flex-col bg-bunker-950 border border-blue-500/30 rounded-2xl shadow-[0_0_50px_rgba(30,58,138,0.3)] overflow-hidden font-mono">
        
        {/* ÜST BAŞLIK & PARİTE DETAYLARI */}
        <div className="p-3.5 sm:p-4 bg-bunker-900/90 border-b border-bunker-800 flex flex-wrap items-center justify-between gap-3 shrink-0">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-blue-500/20 border border-blue-400/40 flex items-center justify-center text-xl shadow-[0_0_12px_rgba(59,130,246,0.3)] shrink-0">
              {candidate.category === "commodity" ? "🥇" : candidate.category === "crypto" ? "⚡" : "💱"}
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span className="text-lg font-bold text-white tracking-wide">
                  {candidate.display}
                </span>
                <span className="px-2 py-0.5 rounded text-[10px] font-bold uppercase bg-bunker-800 text-bunker-300 border border-bunker-700">
                  {candidate.category}
                </span>
                {candidate.tier === "STRONG" && (
                  <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-emerald-500/20 text-emerald-300 border border-emerald-400/40 animate-pulse">
                    ⚡ GÜÇLÜ SİNYAL
                  </span>
                )}
                {isBuy && (
                  <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-emerald-500/20 text-emerald-400 border border-emerald-500/30">
                    ▲ AL
                  </span>
                )}
                {isSell && (
                  <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-rose-500/20 text-rose-400 border border-rose-500/30">
                    ▼ SAT
                  </span>
                )}
              </div>
              <div className="text-xs text-bunker-muted truncate">
                {candidate.name} · Skor: <strong className="text-emerald-400">{candidate.score.toFixed(1)}</strong>
                {candidate.required_score ? ` (eşik ${candidate.required_score})` : ""}
              </div>
            </div>
          </div>

          {/* Canlı Fiyat & Spread Göstergesi */}
          <div className="flex items-center gap-3 sm:gap-6 bg-bunker-950/80 px-3.5 py-1.5 rounded-xl border border-bunker-800">
            <div>
              <div className="text-[10px] text-bunker-muted">CANLI FİYAT</div>
              <div className={`text-base sm:text-lg font-black transition-colors ${
                lastTickDir === "up" ? "text-emerald-400" : lastTickDir === "down" ? "text-rose-400" : "text-white"
              }`}>
                {formatForexPrice(livePrice, candidate.symbol)}
              </div>
            </div>
            <div className="hidden sm:block border-l border-bunker-800 pl-3">
              <div className="text-[10px] text-bunker-muted">BİD / ASK</div>
              <div className="text-xs font-bold text-white">
                {formatForexPrice(liveBid, candidate.symbol)} / {formatForexPrice(liveAsk, candidate.symbol)}
              </div>
            </div>
            <div className="border-l border-bunker-800 pl-3">
              <div className="text-[10px] text-bunker-muted">SPREAD</div>
              <div className="text-xs font-bold text-cyan-400">
                {candidate.spread_pips}p
              </div>
            </div>
          </div>

          {/* Kapat ve Dışa Aktarma Butonları */}
          <div className="flex items-center gap-2">
            {onOpenLotCalculator && (
              <button
                type="button"
                onClick={() => onOpenLotCalculator(candidate.symbol, candidate.stop_loss_pips)}
                className="px-2.5 py-1.5 rounded-lg bg-blue-500/15 border border-blue-400/30 text-blue-300 text-xs font-bold hover:bg-blue-500/25 transition-all"
                title="Hızlı Lot Hesaplayıcı"
              >
                🧮 Lot Hesapla
              </button>
            )}
            <Link
              href={`/forex/charts?symbol=${candidate.tv_symbol || candidate.symbol}`}
              target="_blank"
              className="px-2.5 py-1.5 rounded-lg bg-bunker-800 border border-bunker-700 text-bunker-300 text-xs font-bold hover:text-white hover:border-bunker-600 transition-all hidden md:inline-flex items-center gap-1"
              title="Ayrı Sayfada Aç"
            >
              <span>Ayrı Sayfa</span>
              <span>↗</span>
            </Link>
            <button
              type="button"
              onClick={onClose}
              className="w-8 h-8 rounded-lg bg-bunker-800 text-bunker-300 hover:text-white hover:bg-rose-900/60 transition-colors flex items-center justify-center font-bold text-lg"
              title="Kapat (ESC)"
            >
              ✕
            </button>
          </div>
        </div>

        {/* KONTROL ÇUBUĞU (Zaman Dilimleri, İndikatörler, Sayaç) */}
        <div className="px-3.5 py-2 bg-bunker-950 border-b border-bunker-800/80 flex flex-wrap items-center justify-between gap-2 text-xs shrink-0">
          
          {/* Periyot Seçici */}
          <div className="flex items-center gap-1">
            <span className="text-[11px] text-bunker-muted mr-1">Periyot:</span>
            {(["1m", "5m", "15m", "30m", "1h", "4h", "1d"] as Timeframe[]).map((tf) => (
              <button
                key={tf}
                type="button"
                onClick={() => setTimeframe(tf)}
                className={`px-2.5 py-1 rounded-md text-xs font-bold transition-all ${
                  timeframe === tf
                    ? "bg-blue-600 text-white shadow-[0_0_10px_rgba(37,99,235,0.4)] border border-blue-400"
                    : "bg-bunker-900 text-bunker-muted border border-bunker-800 hover:text-white hover:bg-bunker-850"
                }`}
              >
                {tf}
              </button>
            ))}
          </div>

          {/* Gösterge Toggle Butonları */}
          <div className="flex items-center gap-1.5 overflow-x-auto pb-0.5 sm:pb-0">
            <button
              type="button"
              onClick={() => setShowBB(!showBB)}
              className={`px-2 py-0.5 rounded text-[11px] font-bold border transition-all ${
                showBB
                  ? "bg-cyan-500/20 text-cyan-300 border-cyan-400/40"
                  : "bg-bunker-900 text-bunker-muted border-bunker-800 opacity-60"
              }`}
            >
              BB (20,2)
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
              TP / SL Çizgileri
            </button>
          </div>

          {/* Mum Kapanış Sayacı & Canlı Durum */}
          <div className="flex items-center gap-3 text-xs">
            {latestRsi !== null && (
              <span className="text-bunker-muted">
                RSI: <strong className={latestRsi > 70 ? "text-rose-400" : latestRsi < 30 ? "text-emerald-400" : "text-white"}>{latestRsi}</strong>
              </span>
            )}
            <div className="flex items-center gap-1.5 bg-bunker-900 px-2 py-0.5 rounded border border-bunker-800">
              <span className="w-2 h-2 rounded-full bg-emerald-400 animate-ping" />
              <span className="text-[11px] text-bunker-muted">Kapanış:</span>
              <span className="font-bold text-white tabular-nums">
                {formatCountdown(countdown)}
              </span>
            </div>
          </div>
        </div>

        {/* GRAFİK TUVALİ (NATIVE LIGHTWEIGHT CHARTS) */}
        <div className="relative flex-1 w-full bg-[#080c14] overflow-hidden">
          {loading && (
            <div className="absolute inset-0 z-10 flex flex-col items-center justify-center bg-black/60 backdrop-blur-sm gap-2">
              <div className="w-8 h-8 border-2 border-blue-400 border-t-transparent rounded-full animate-spin" />
              <p className="text-xs text-blue-300 font-bold">Forex mumları yükleniyor ({candidate.display})…</p>
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

        {/* ALT DURUM & HEDEF / STOP DETAY ÇUBUĞU */}
        <div className="p-3 bg-bunker-900/90 border-t border-bunker-800 flex flex-wrap items-center justify-between gap-3 text-xs shrink-0">
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
            <span className="text-bunker-muted">
              Hedef TP: <strong className="text-emerald-400">+{candidate.pip_target}p</strong>
            </span>
            <span className="text-bunker-muted">
              Stop SL: <strong className="text-rose-400">-{candidate.stop_loss_pips}p</strong>
            </span>
            <span className="text-bunker-muted">
              R/R Oranı: <strong className="text-white">{candidate.risk_reward}</strong>
            </span>
            <span className="text-bunker-muted">
              ATR (14): <strong className="text-cyan-400">{candidate.atr_pips}p</strong>
            </span>
            <span className="text-bunker-muted">
              ADX: <strong className={candidate.adx >= 25 ? "text-emerald-400" : "text-yellow-400"}>{candidate.adx.toFixed(0)}</strong>
            </span>
            <span className="text-bunker-muted">
              HTF Trend: <strong className="text-white">{candidate.htf_trend}</strong>
            </span>
          </div>

          <div className="flex items-center gap-2">
            <span className="text-[11px] text-bunker-muted">
              {candidate.macd_verdict}
            </span>
          </div>
        </div>

      </div>
    </div>
  );
}

function formatCountdown(sec: number): string {
  if (sec <= 0) return "00:00";
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

function roundNumber(num: number, dec = 2): number {
  const f = Math.pow(10, dec);
  return Math.round(num * f) / f;
}
