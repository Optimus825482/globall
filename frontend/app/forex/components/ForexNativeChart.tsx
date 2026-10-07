"use client";

import React, { useEffect, useRef, useState, useCallback } from "react";
import Link from "next/link";
import {
  createChart,
  CandlestickSeries,
  LineSeries,
  HistogramSeries,
  IChartApi,
  ISeriesApi,
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
  separatePageHref?: string;
  onOpenLotCalculator?: (symbol: string, slPips: number) => void;
  onClose?: () => void;
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

// -------------------------------------------------------------
// İNDİKATÖR MATEMATİĞİ
// -------------------------------------------------------------

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

function calculateSMA(candles: CandleBar[], period: number) {
  if (candles.length < period) return [];
  const result: { time: UTCTimestamp; value: number }[] = [];
  let sum = 0;
  for (let i = 0; i < period; i++) {
    sum += candles[i].close;
  }
  result.push({ time: candles[period - 1].time, value: sum / period });

  for (let i = period; i < candles.length; i++) {
    sum += candles[i].close - candles[i - period].close;
    result.push({ time: candles[i].time, value: sum / period });
  }
  return result;
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

interface MacdBar {
  time: UTCTimestamp;
  macd: number;
  signal: number;
  hist: number;
  color: string;
}

function calculateMACD(candles: CandleBar[], fast = 12, slow = 26, signal = 9): MacdBar[] {
  if (candles.length < slow + signal) return [];

  const emaFast = calculateEMA(candles, fast);
  const emaSlow = calculateEMA(candles, slow);

  const fastMap = new Map<number, number>();
  for (const p of emaFast) fastMap.set(p.time, p.value);

  const macdPoints: { time: UTCTimestamp; value: number }[] = [];
  for (const p of emaSlow) {
    const fVal = fastMap.get(p.time);
    if (fVal !== undefined) {
      macdPoints.push({ time: p.time, value: fVal - p.value });
    }
  }

  if (macdPoints.length < signal) return [];

  const kSig = 2 / (signal + 1);
  let sumSig = 0;
  for (let i = 0; i < signal; i++) {
    sumSig += macdPoints[i].value;
  }
  let prevSig = sumSig / signal;

  const result: MacdBar[] = [];
  const firstMacd = macdPoints[signal - 1].value;
  const firstHist = firstMacd - prevSig;
  result.push({
    time: macdPoints[signal - 1].time,
    macd: firstMacd,
    signal: prevSig,
    hist: firstHist,
    color: firstHist >= 0 ? "#10b981" : "#f43f5e",
  });

  for (let i = signal; i < macdPoints.length; i++) {
    const curVal = macdPoints[i].value;
    const curSig = (curVal - prevSig) * kSig + prevSig;
    prevSig = curSig;
    const curHist = curVal - curSig;
    const prevHist = result[result.length - 1].hist;

    let color = "#10b981";
    if (curHist >= 0) {
      color = curHist >= prevHist ? "#10b981" : "rgba(16, 185, 129, 0.55)";
    } else {
      color = curHist <= prevHist ? "#f43f5e" : "rgba(244, 63, 94, 0.55)";
    }

    result.push({
      time: macdPoints[i].time,
      macd: curVal,
      signal: curSig,
      hist: curHist,
      color,
    });
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

// -------------------------------------------------------------
// BİLEŞEN
// -------------------------------------------------------------

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
  separatePageHref,
  onOpenLotCalculator,
  onClose,
  className = "",
}: ForexNativeChartProps) {
  const [timeframe, setTimeframe] = useState<Timeframe>(initialTimeframe);
  const [candles, setCandles] = useState<CandleBar[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Göstergeler (Kullanıcı talebi: varsayılan yalnız Bollinger Bands + alt pane MACD açık)
  const [showBB, setShowBB] = useState(true);
  const [showSma, setShowSma] = useState(false);
  const [showMacd, setShowMacd] = useState(true);
  const [showSupertrend, setShowSupertrend] = useState(false);

  // Canlı Veriler & İndikatör Okumaları
  const [livePrice, setLivePrice] = useState<number | null>(null);
  const [liveBid, setLiveBid] = useState<number | null>(null);
  const [liveAsk, setLiveAsk] = useState<number | null>(null);
  const [liveSpread, setLiveSpread] = useState<number | null>(null);
  const [lastTickDir, setLastTickDir] = useState<"up" | "down" | null>(null);
  const [countdown, setCountdown] = useState<number>(0);
  const [latestRsi, setLatestRsi] = useState<number | null>(null);

  // Canlı İndikatör Değerleri (Header için)
  const [liveSma7, setLiveSma7] = useState<number | null>(null);
  const [liveSma30, setLiveSma30] = useState<number | null>(null);
  const [liveSma99, setLiveSma99] = useState<number | null>(null);
  const [liveMacdHist, setLiveMacdHist] = useState<number | null>(null);

  // Geçmişe kaydırma durumu (Kullanıcı sola çektiğinde beliren Canlı Fiyata Dön düğmesi)
  const [isScrolledBack, setIsScrolledBack] = useState(false);

  // DOM & Grafik Referansları
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartApiRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);

  // BB Serileri (Pane 0)
  const upperBbRef = useRef<ISeriesApi<"Line"> | null>(null);
  const middleBbRef = useRef<ISeriesApi<"Line"> | null>(null);
  const lowerBbRef = useRef<ISeriesApi<"Line"> | null>(null);

  // SMA Serileri (Pane 0: 7, 30, 99)
  const sma7SeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const sma30SeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const sma99SeriesRef = useRef<ISeriesApi<"Line"> | null>(null);

  // SuperTrend Serisi (Pane 0)
  const supertrendSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);

  // MACD Serileri (Pane 1)
  const macdHistRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const macdLineRef = useRef<ISeriesApi<"Line"> | null>(null);
  const macdSignalRef = useRef<ISeriesApi<"Line"> | null>(null);

  const lastCandleRef = useRef<CandleBar | null>(null);
  const timeframeRef = useRef<Timeframe>(timeframe);
  timeframeRef.current = timeframe;

  // GÖRÜNÜM KİLİDİ: fitContent() YALNIZCA sembol veya periyot değiştiğinde 1 kez çağrılır!
  // Periyodik sessiz pollinglerde fitContent() ÇAĞRILMAZ, böylece kullanıcının sola çektiği mumlar sağa yapışmaz!
  const fittedForRef = useRef<string>("");

  // Pane Yüksekliklerini Güncelle
  const updatePaneLayout = useCallback(() => {
    if (!chartApiRef.current || !chartContainerRef.current) return;
    const chart = chartApiRef.current;
    const w = chartContainerRef.current.clientWidth;
    const h = chartContainerRef.current.clientHeight || 520;
    if (w <= 0 || h <= 0) return;

    chart.applyOptions({ width: w, height: h });

    const panes = chart.panes();
    if (panes.length >= 2) {
      if (showMacd) {
        const macdH = Math.max(80, Math.min(135, Math.round(h * 0.26)));
        const mainH = Math.max(160, h - macdH);
        panes[0]?.setHeight(mainH);
        panes[1]?.setHeight(macdH);
      } else {
        panes[0]?.setHeight(h);
        panes[1]?.setHeight(0);
      }
    } else if (panes.length === 1) {
      panes[0]?.setHeight(h);
    }
  }, [showMacd]);

  // Mum Verisi Yükleme
  const loadKlines = useCallback(async (tf: Timeframe, silent = false) => {
    if (!silent) setLoading(true);
    setError(null);
    try {
      const data = await apiFetch(`/api/forex/klines?symbol=${encodeURIComponent(symbol)}&interval=${tf}&limit=250`);
      if (data && Array.isArray(data.candles) && data.candles.length > 0) {
        // SONLULUK KAPISI: backend eksik/`None` alan döndürürse `Number(undefined)`
        // = NaN olur; NaN'lı bir mum seriye girerse lightweight-charts onu boyarken
        // "Value is undefined" istisnası fırlatır (grafik her karede patlar).
        // Bozuk mumlar seriye HİÇ girmesin.
        const parsed: CandleBar[] = data.candles
          .map((c: any) => ({
            time: Number(c.time) as UTCTimestamp,
            open: Number(c.open),
            high: Number(c.high),
            low: Number(c.low),
            close: Number(c.close),
            volume: Number(c.volume ?? 0),
          }))
          .filter((b: CandleBar) =>
            Number.isFinite(b.time) && b.time > 0 &&
            Number.isFinite(b.open) && Number.isFinite(b.high) &&
            Number.isFinite(b.low) && Number.isFinite(b.close));
        if (parsed.length > 0) {
          setCandles(parsed);
          lastCandleRef.current = parsed[parsed.length - 1];

          if (data.current_price) {
            setLivePrice(data.current_price);
          }

          const rsiArr = calculateRSI(parsed, 14);
          if (rsiArr.length > 0) {
            setLatestRsi(Math.round(rsiArr[rsiArr.length - 1].value * 10) / 10);
          }
        } else if (!silent) {
          setError("Bu sembol için mum verisi bulunamadı.");
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

  // Canlı veri polling (her 4 saniyede bir sessiz tazeleme — görünümü sıfırlamaz!)
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
            // FİYAT KAPISI: tick nesnesi `price` taşımazsa (yalnız bid/ask yayınlanır)
            // eskiden `tick.price` = `undefined` doğrudan mumun `close` alanına yazılıyor,
            // `series.update()` ile seriye giriyor ve lightweight-charts mumu boyarken
            // `ensure(close)` ile "Value is undefined" fırlatıp grafiği her karede
            // patlatıyordu. Fiyatı bid/ask ortasından türet; sonlu değilse muma dokunma.
            const bid = Number(tick.bid);
            const ask = Number(tick.ask);
            const mid = Number.isFinite(bid) && Number.isFinite(ask) && bid > 0 && ask > 0
              ? (bid + ask) / 2
              : NaN;
            const rawPrice = Number(tick.price);
            const px = Number.isFinite(rawPrice) && rawPrice > 0
              ? rawPrice
              : (Number.isFinite(mid) ? mid : NaN);

            if (Number.isFinite(px) && Math.abs(px - (livePrice || 0)) > 1e-6) {
              setLastTickDir(livePrice != null && px >= livePrice ? "up" : "down");
              setLivePrice(px);
            }
            if (Number.isFinite(bid) && bid > 0) setLiveBid(bid);
            if (Number.isFinite(ask) && ask > 0) setLiveAsk(ask);
            if (tick.spread_pips != null) setLiveSpread(tick.spread_pips);

            if (candleSeriesRef.current && lastCandleRef.current && Number.isFinite(px)) {
              const last = lastCandleRef.current;
              if (Number.isFinite(last.open) && Number.isFinite(last.high) && Number.isFinite(last.low)) {
                const updatedBar: CandleBar = {
                  time: last.time,
                  open: last.open,
                  high: Math.max(last.high, px),
                  low: Math.min(last.low, px),
                  close: px,
                };
                lastCandleRef.current = updatedBar;
                try {
                  candleSeriesRef.current.update(updatedBar as any);
                } catch {}
              }
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
        // shiftVisibleRangeOnNewBar: false -> Kullanıcı mumları sola çekip incelerken yeni tick geldiğinde sağa sıçramayı engeller!
        shiftVisibleRangeOnNewBar: false,
        rightOffset: 6,
        barSpacing: 9,
        minBarSpacing: 1.5,
      },
      rightPriceScale: {
        borderColor: "#1e293b",
        scaleMargins: { top: 0.10, bottom: 0.10 },
      },
    });

    chartApiRef.current = chart;

    // --- PANE 0: MUM GRAFİĞİ ---
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
    }, 0);
    candleSeriesRef.current = candleSeries;

    // --- PANE 0: BOLLINGER BANDS (20, 2) ---
    const upperBb = chart.addSeries(LineSeries, {
      color: "rgba(56, 189, 248, 0.85)",
      lineWidth: 1,
      title: "BB Üst",
      priceLineVisible: false,
      lastValueVisible: false,
    }, 0);
    const middleBb = chart.addSeries(LineSeries, {
      color: "rgba(245, 158, 11, 0.85)",
      lineWidth: 1,
      lineStyle: LineStyle.Dashed,
      title: "BB Orta",
      priceLineVisible: false,
      lastValueVisible: false,
    }, 0);
    const lowerBb = chart.addSeries(LineSeries, {
      color: "rgba(56, 189, 248, 0.85)",
      lineWidth: 1,
      title: "BB Alt",
      priceLineVisible: false,
      lastValueVisible: false,
    }, 0);
    upperBbRef.current = upperBb;
    middleBbRef.current = middleBb;
    lowerBbRef.current = lowerBb;

    // --- PANE 0: 3'LÜ SIMPLE MOVING AVERAGES (SMA 7, 30, 99) ---
    const sma7 = chart.addSeries(LineSeries, {
      color: "#38bdf8", // Sky Blue
      lineWidth: 2,
      title: "SMA 7",
      priceLineVisible: false,
      lastValueVisible: false,
    }, 0);
    const sma30 = chart.addSeries(LineSeries, {
      color: "#a855f7", // Mor
      lineWidth: 2,
      title: "SMA 30",
      priceLineVisible: false,
      lastValueVisible: false,
    }, 0);
    const sma99 = chart.addSeries(LineSeries, {
      color: "#f97316", // Turuncu
      lineWidth: 2,
      title: "SMA 99",
      priceLineVisible: false,
      lastValueVisible: false,
    }, 0);
    sma7SeriesRef.current = sma7;
    sma30SeriesRef.current = sma30;
    sma99SeriesRef.current = sma99;

    // --- PANE 0: SUPERTREND ---
    const supertrendSeries = chart.addSeries(LineSeries, {
      lineWidth: 2,
      title: "SuperTrend",
      priceLineVisible: false,
      lastValueVisible: true,
    }, 0);
    supertrendSeriesRef.current = supertrendSeries;

    // --- PANE 1: MACD ALT PANE (12, 26, 9) ---
    const macdHist = chart.addSeries(HistogramSeries, {
      color: "#10b981",
      base: 0,
      title: "Histogram",
      priceLineVisible: false,
      lastValueVisible: false,
    }, 1);
    const macdLine = chart.addSeries(LineSeries, {
      color: "#38bdf8",
      lineWidth: 2,
      title: "MACD (12,26)",
      priceLineVisible: false,
      lastValueVisible: false,
    }, 1);
    const macdSignal = chart.addSeries(LineSeries, {
      color: "#f59e0b",
      lineWidth: 2,
      title: "Sinyal (9)",
      priceLineVisible: false,
      lastValueVisible: false,
    }, 1);

    macdHistRef.current = macdHist;
    macdLineRef.current = macdLine;
    macdSignalRef.current = macdSignal;

    // MACD Pane 1 Fiyat Ekseni ve Sıfır Çizgisi
    chart.priceScale("right", 1).applyOptions({
      autoScale: true,
      scaleMargins: { top: 0.15, bottom: 0.15 },
    });

    macdHist.createPriceLine({
      price: 0,
      color: "rgba(148, 163, 184, 0.45)",
      lineWidth: 1,
      lineStyle: LineStyle.Dotted,
      axisLabelVisible: false,
      title: "0",
    });

    // Kullanıcı sola kaydırdığında "Canlı Fiyat" düğmesini göster
    chart.timeScale().subscribeVisibleLogicalRangeChange((range) => {
      if (!range) return;
      const count = lastCandleRef.current ? 100 : 0;
      if (range.to != null && count > 0) {
        setIsScrolledBack(range.to < count - 3);
      }
    });

    // Yeniden Boyutlandırma
    const handleResize = () => {
      updatePaneLayout();
    };
    window.addEventListener("resize", handleResize);

    let resizeObserver: ResizeObserver | null = null;
    if (typeof ResizeObserver !== "undefined" && chartContainerRef.current) {
      resizeObserver = new ResizeObserver(() => {
        handleResize();
      });
      resizeObserver.observe(chartContainerRef.current);
    }

    // İlk pane yüksekliklerini uygula
    setTimeout(updatePaneLayout, 50);

    return () => {
      window.removeEventListener("resize", handleResize);
      if (resizeObserver) resizeObserver.disconnect();
      chart.remove();
      chartApiRef.current = null;
      candleSeriesRef.current = null;
    };
  }, [symbol, updatePaneLayout]);

  // Pane boyutlarını `showMacd` değişiminde senkronize et
  useEffect(() => {
    updatePaneLayout();
    if (macdHistRef.current) macdHistRef.current.applyOptions({ visible: showMacd });
    if (macdLineRef.current) macdLineRef.current.applyOptions({ visible: showMacd });
    if (macdSignalRef.current) macdSignalRef.current.applyOptions({ visible: showMacd });
  }, [showMacd, updatePaneLayout]);

  // Mum Verilerini ve Göstergeleri Grafiğe Bas
  useEffect(() => {
    if (!candleSeriesRef.current || candles.length === 0) return;

    try {
      candleSeriesRef.current.setData(candles as any);

      // GÖRÜNÜM KİLİDİ: Yalnızca sembol veya periyot değişince sığdır!
      // Sessiz arka plan güncellemelerinde fitContent() çalışmaz, böylece sola çekilen görünüm korunur.
      const viewKey = `${symbol}|${timeframe}`;
      if (fittedForRef.current !== viewKey) {
        fittedForRef.current = viewKey;
        chartApiRef.current?.timeScale().fitContent();
        setIsScrolledBack(false);
      }
    } catch (e) {
      console.warn("Mum verisi basılırken uyarı:", e);
    }

    // --- 1. BOLLINGER BANDS (20, 2) ---
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

    // --- 2. 3'LÜ SIMPLE MOVING AVERAGES (7, 30, 99) ---
    if (showSma && sma7SeriesRef.current && sma30SeriesRef.current && sma99SeriesRef.current) {
      const s7 = calculateSMA(candles, 7);
      const s30 = calculateSMA(candles, 30);
      const s99 = calculateSMA(candles, 99);

      if (s7.length > 0) {
        sma7SeriesRef.current.setData(s7 as any);
        setLiveSma7(s7[s7.length - 1].value);
      }
      if (s30.length > 0) {
        sma30SeriesRef.current.setData(s30 as any);
        setLiveSma30(s30[s30.length - 1].value);
      }
      if (s99.length > 0) {
        sma99SeriesRef.current.setData(s99 as any);
        setLiveSma99(s99[s99.length - 1].value);
      }

      sma7SeriesRef.current.applyOptions({ visible: true });
      sma30SeriesRef.current.applyOptions({ visible: true });
      sma99SeriesRef.current.applyOptions({ visible: true });
    } else if (sma7SeriesRef.current) {
      sma7SeriesRef.current.applyOptions({ visible: false });
      sma30SeriesRef.current?.applyOptions({ visible: false });
      sma99SeriesRef.current?.applyOptions({ visible: false });
    }

    // --- 3. MACD ALT PANE (12, 26, 9) ---
    if (showMacd && macdHistRef.current && macdLineRef.current && macdSignalRef.current) {
      const macdBars = calculateMACD(candles, 12, 26, 9);
      if (macdBars.length > 0) {
        macdHistRef.current.setData(macdBars.map((m) => ({ time: m.time, value: m.hist, color: m.color })) as any);
        macdLineRef.current.setData(macdBars.map((m) => ({ time: m.time, value: m.macd })) as any);
        macdSignalRef.current.setData(macdBars.map((m) => ({ time: m.time, value: m.signal })) as any);
        setLiveMacdHist(macdBars[macdBars.length - 1].hist);
      }
      macdHistRef.current.applyOptions({ visible: true });
      macdLineRef.current.applyOptions({ visible: true });
      macdSignalRef.current.applyOptions({ visible: true });
    } else if (macdHistRef.current) {
      macdHistRef.current.applyOptions({ visible: false });
      macdLineRef.current?.applyOptions({ visible: false });
      macdSignalRef.current?.applyOptions({ visible: false });
    }

    // --- 4. SUPERTREND ---
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
  }, [candles, showBB, showSma, showMacd, showSupertrend, symbol, timeframe]);

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

        {/* Aksiyonlar (Lot hesapla, Ayrı Sayfa, Kapat) */}
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
          {separatePageHref && (
            <Link
              href={separatePageHref}
              target="_blank"
              className="px-2.5 py-1 rounded-lg bg-bunker-800 border border-bunker-700 text-bunker-300 text-xs font-bold hover:text-white hover:border-bunker-600 transition-all hidden sm:inline-flex items-center gap-1"
              title="Ayrı Sayfada Aç"
            >
              <span>Ayrı Sayfa</span>
              <span>↗</span>
            </Link>
          )}
          {onClose && (
            <button
              type="button"
              onClick={onClose}
              className="w-8 h-8 rounded-lg bg-bunker-800 text-bunker-300 hover:text-white hover:bg-rose-900/60 transition-colors flex items-center justify-center font-bold text-base"
              title="Kapat"
            >
              ✕
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

        {/* İndikatör Butonları */}
        <div className="flex items-center gap-1.5 overflow-x-auto">
          {/* Bollinger Bands (Default Açık) */}
          <button
            type="button"
            onClick={() => setShowBB(!showBB)}
            className={`px-2 py-0.5 rounded text-[11px] font-bold border transition-all ${
              showBB
                ? "bg-cyan-500/20 text-cyan-300 border-cyan-400/50 shadow-[0_0_6px_rgba(6,182,212,0.3)]"
                : "bg-bunker-900 text-bunker-muted border-bunker-800 opacity-60"
            }`}
            title="Bollinger Bands (20, 2)"
          >
            BB (20,2)
          </button>

          {/* 3'lü Simple Moving Averages (Default Açık) */}
          <button
            type="button"
            onClick={() => setShowSma(!showSma)}
            className={`px-2 py-0.5 rounded text-[11px] font-bold border transition-all ${
              showSma
                ? "bg-purple-500/20 text-purple-300 border-purple-400/50 shadow-[0_0_6px_rgba(168,85,247,0.3)]"
                : "bg-bunker-900 text-bunker-muted border-bunker-800 opacity-60"
            }`}
            title="3'lü Basit Hareketli Ortalamalar (SMA 7, 30, 99)"
          >
            SMA 7/30/99
          </button>

          {/* MACD Alt Pane (Default Açık) */}
          <button
            type="button"
            onClick={() => setShowMacd(!showMacd)}
            className={`px-2 py-0.5 rounded text-[11px] font-bold border transition-all ${
              showMacd
                ? "bg-emerald-500/20 text-emerald-300 border-emerald-400/50 shadow-[0_0_6px_rgba(16,185,129,0.3)]"
                : "bg-bunker-900 text-bunker-muted border-bunker-800 opacity-60"
            }`}
            title="MACD Alt Gösterge Penceresi (12, 26, 9)"
          >
            MACD (12,26,9)
          </button>

          {/* SuperTrend */}
          <button
            type="button"
            onClick={() => setShowSupertrend(!showSupertrend)}
            className={`px-2 py-0.5 rounded text-[11px] font-bold border transition-all ${
              showSupertrend
                ? "bg-amber-500/20 text-amber-300 border-amber-400/50"
                : "bg-bunker-900 text-bunker-muted border-bunker-800 opacity-60"
            }`}
            title="SuperTrend (10, 3)"
          >
            SuperTrend
          </button>
        </div>

        <div className="flex items-center gap-3 text-xs">
          {latestRsi !== null && (
            <span className="text-bunker-muted hidden md:inline">
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

      {/* İNDİKATÖR CANLI LEJANTI */}
      <div className="px-3 py-1 bg-bunker-950/95 border-b border-bunker-900 text-[11px] flex flex-wrap items-center gap-x-4 gap-y-0.5 text-bunker-muted shrink-0">
        {showSma && (
          <div className="flex items-center gap-3">
            <span className="flex items-center gap-1">
              <span className="w-2.5 h-0.5 bg-[#38bdf8] rounded" />
              <span className="text-[#38bdf8]">SMA 7:</span>
              <strong className="text-white font-bold">{formatPriceBySymbol(liveSma7, symbol)}</strong>
            </span>
            <span className="flex items-center gap-1">
              <span className="w-2.5 h-0.5 bg-[#a855f7] rounded" />
              <span className="text-[#a855f7]">SMA 30:</span>
              <strong className="text-white font-bold">{formatPriceBySymbol(liveSma30, symbol)}</strong>
            </span>
            <span className="flex items-center gap-1">
              <span className="w-2.5 h-0.5 bg-[#f97316] rounded" />
              <span className="text-[#f97316]">SMA 99:</span>
              <strong className="text-white font-bold">{formatPriceBySymbol(liveSma99, symbol)}</strong>
            </span>
          </div>
        )}

        {showMacd && (
          <div className="flex items-center gap-2 border-l border-bunker-800 pl-3">
            <span className="text-cyan-400 font-bold">MACD (12,26,9):</span>
            <span className={`font-bold tabular-nums ${liveMacdHist != null && liveMacdHist >= 0 ? "text-emerald-400" : "text-rose-400"}`}>
              {liveMacdHist != null ? (liveMacdHist >= 0 ? `+${liveMacdHist.toFixed(5)}` : liveMacdHist.toFixed(5)) : "—"}
            </span>
          </div>
        )}
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

        {/* Kullanıcı mumları sola çekip incelediğinde sağa dönmesi için hızlı buton */}
        {isScrolledBack && (
          <button
            type="button"
            onClick={() => {
              chartApiRef.current?.timeScale().scrollToRealTime();
              setIsScrolledBack(false);
            }}
            className="absolute bottom-4 right-16 z-20 flex items-center gap-1.5 px-3 py-1 rounded-full bg-blue-600/90 hover:bg-blue-500 text-white text-xs font-bold shadow-lg border border-blue-400 backdrop-blur transition-all animate-in fade-in"
            title="Canlı fiyata dön"
          >
            <span>⏭ Canlı Fiyat</span>
          </button>
        )}

        <div ref={chartContainerRef} className="w-full h-full" />
      </div>

      {/* ALT BİLGİ ŞERİDİ */}
      {(score != null || adx != null || atrPips != null || htfTrend) && (
        <div className="p-2.5 bg-bunker-900/90 border-t border-bunker-800 flex flex-wrap items-center justify-between gap-3 text-xs shrink-0">
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
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
