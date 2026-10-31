"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import {
  createChart,
  CandlestickSeries,
  LineSeries,
  HistogramSeries,
  ColorType,
  LineStyle,
  UTCTimestamp,
  IChartApi,
  ISeriesApi,
} from "lightweight-charts";
import { API_BASE, apiRequest } from "../lib/api";
import { subscribeLive } from "../lib/liveSocket";
import { formatPrice, pricePrecision } from "../lib/format";

export interface SignalModalData {
  id: number;
  symbol: string;
  timeframe: string;
  strategy: string;
  strategy_label: string;
  entry_price: number;
  current_price: number;
  target_price: number;
  stop_price: number;
  score: number;
  kdj_j: number | null;
  status: "OPEN" | "WIN_TP" | "LOSS_SL" | "EXPIRED" | "MANUAL_CLOSED" | string;
  pnl_pct: number;
  mfe_pct: number;
  net_pnl_try: number;
  detected_at: string;
  exit_time: string | null;
  details?: {
    note?: string;
    tp_pct?: number;
    sl_pct?: number;
  };
}

interface SpotChartModalProps {
  signal: SignalModalData;
  onClose: () => void;
}

type Bar = {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
};

export interface ActiveIndicators {
  // Overlay
  ema50: boolean;
  ema20: boolean;
  ema200: boolean;
  bollinger: boolean;
  supertrend: boolean;
  vwap: boolean;
  // Subpanes
  kdj: boolean;
  rsi: boolean;
  macd: boolean;
}

// ── Matematiksel Gösterge Hesaplayıcıları ─────────────────────────────────────
function calcEMA(bars: Bar[], period: number): { time: UTCTimestamp; value: number }[] {
  if (bars.length < period) return [];
  const k = 2 / (period + 1);
  let ema = bars.slice(0, period).reduce((acc, b) => acc + b.close, 0) / period;
  const result: { time: UTCTimestamp; value: number }[] = [
    { time: bars[period - 1].time as UTCTimestamp, value: ema },
  ];
  for (let i = period; i < bars.length; i++) {
    ema = bars[i].close * k + ema * (1 - k);
    result.push({ time: bars[i].time as UTCTimestamp, value: ema });
  }
  return result;
}

function calcBollinger(bars: Bar[], period = 20, mult = 2) {
  const upper: { time: UTCTimestamp; value: number }[] = [];
  const middle: { time: UTCTimestamp; value: number }[] = [];
  const lower: { time: UTCTimestamp; value: number }[] = [];
  for (let i = period - 1; i < bars.length; i++) {
    let sum = 0;
    for (let j = 0; j < period; j++) sum += bars[i - j].close;
    const sma = sum / period;
    let varSum = 0;
    for (let j = 0; j < period; j++) varSum += Math.pow(bars[i - j].close - sma, 2);
    const std = Math.sqrt(varSum / period);
    const t = bars[i].time as UTCTimestamp;
    middle.push({ time: t, value: sma });
    upper.push({ time: t, value: sma + mult * std });
    lower.push({ time: t, value: sma - mult * std });
  }
  return { upper, middle, lower };
}

function calcATR(bars: Bar[], period = 14): { time: UTCTimestamp; value: number }[] {
  if (bars.length < period + 1) return [];
  const trs: number[] = [bars[0].high - bars[0].low];
  for (let i = 1; i < bars.length; i++) {
    const tr = Math.max(
      bars[i].high - bars[i].low,
      Math.abs(bars[i].high - bars[i - 1].close),
      Math.abs(bars[i].low - bars[i - 1].close)
    );
    trs.push(tr);
  }
  let atr = trs.slice(0, period).reduce((a, b) => a + b, 0) / period;
  const result: { time: UTCTimestamp; value: number }[] = [
    { time: bars[period - 1].time as UTCTimestamp, value: atr },
  ];
  for (let i = period; i < bars.length; i++) {
    atr = (atr * (period - 1) + trs[i]) / period;
    result.push({ time: bars[i].time as UTCTimestamp, value: atr });
  }
  return result;
}

function calcSupertrend(bars: Bar[], period = 10, mult = 3) {
  const atrList = calcATR(bars, period);
  if (!atrList.length) return { trend: [] };
  const startIdx = bars.length - atrList.length;
  const trend: { time: UTCTimestamp; value: number; color: string }[] = [];
  let prevUp = 0;
  let prevDn = 0;
  let direction = 1;

  for (let i = 0; i < atrList.length; i++) {
    const bi = startIdx + i;
    const atr = atrList[i].value;
    const hl2 = (bars[bi].high + bars[bi].low) / 2;
    const basicUp = hl2 - mult * atr;
    const basicDn = hl2 + mult * atr;
    const finalUp = i === 0 ? basicUp : basicUp > prevUp || bars[bi - 1].close < prevUp ? basicUp : prevUp;
    const finalDn = i === 0 ? basicDn : basicDn < prevDn || bars[bi - 1].close > prevDn ? basicDn : prevDn;
    const close = bars[bi].close;

    if (direction === 1 && close < finalUp) direction = -1;
    else if (direction === -1 && close > finalDn) direction = 1;

    trend.push({
      time: bars[bi].time as UTCTimestamp,
      value: direction === 1 ? finalUp : finalDn,
      color: direction === 1 ? "#10b981" : "#ef4444",
    });
    prevUp = finalUp;
    prevDn = finalDn;
  }
  return { trend };
}

function calcVWAP(bars: Bar[]): { time: UTCTimestamp; value: number }[] {
  let cumPV = 0;
  let cumV = 0;
  return bars.map((b) => {
    const tp = (b.high + b.low + b.close) / 3;
    cumPV += tp * b.volume;
    cumV += b.volume;
    return {
      time: b.time as UTCTimestamp,
      value: cumV === 0 ? tp : cumPV / cumV,
    };
  });
}

function calcKDJ(
  bars: Bar[],
  period: number = 9,
  signal: number = 3
): {
  k: { time: UTCTimestamp; value: number }[];
  d: { time: UTCTimestamp; value: number }[];
  j: { time: UTCTimestamp; value: number }[];
} {
  if (bars.length < period + signal) {
    return { k: [], d: [], j: [] };
  }
  const rsv: { time: UTCTimestamp; value: number }[] = [];
  for (let i = period - 1; i < bars.length; i++) {
    let hi = -Infinity;
    let lo = Infinity;
    for (let p = 0; p < period; p++) {
      const b = bars[i - p];
      if (b.high > hi) hi = b.high;
      if (b.low < lo) lo = b.low;
    }
    const val = hi !== lo ? ((bars[i].close - lo) / (hi - lo)) * 100 : 50;
    rsv.push({ time: bars[i].time as UTCTimestamp, value: val });
  }

  let kVal = 50;
  let dVal = 50;
  const alpha = 1 / signal;
  const kList: { time: UTCTimestamp; value: number }[] = [];
  const dList: { time: UTCTimestamp; value: number }[] = [];
  const jList: { time: UTCTimestamp; value: number }[] = [];

  for (let i = 0; i < rsv.length; i++) {
    const item = rsv[i];
    kVal = (1 - alpha) * kVal + alpha * item.value;
    dVal = (1 - alpha) * dVal + alpha * kVal;
    const jVal = 3 * kVal - 2 * dVal;

    kList.push({ time: item.time, value: kVal });
    dList.push({ time: item.time, value: dVal });
    jList.push({ time: item.time, value: jVal });
  }

  return { k: kList, d: dList, j: jList };
}

function calcRSI(bars: Bar[], period = 14): { time: UTCTimestamp; value: number }[] {
  if (bars.length <= period) return [];
  let gains = 0;
  let losses = 0;
  for (let i = 1; i <= period; i++) {
    const d = bars[i].close - bars[i - 1].close;
    if (d >= 0) gains += d;
    else losses -= d;
  }
  let ag = gains / period;
  let al = losses / period;
  const result: { time: UTCTimestamp; value: number }[] = [
    { time: bars[period].time as UTCTimestamp, value: 100 - 100 / (1 + (al === 0 ? 100 : ag / al)) },
  ];
  for (let i = period + 1; i < bars.length; i++) {
    const d = bars[i].close - bars[i - 1].close;
    ag = (ag * (period - 1) + (d > 0 ? d : 0)) / period;
    al = (al * (period - 1) + (d < 0 ? -d : 0)) / period;
    result.push({
      time: bars[i].time as UTCTimestamp,
      value: 100 - 100 / (1 + (al === 0 ? 100 : ag / al)),
    });
  }
  return result;
}

function calcMACD(bars: Bar[], fast = 12, slow = 26, signal = 9) {
  if (bars.length < slow + signal) return { macd: [], signal: [], histogram: [] };
  const fEma = calcEMA(bars, fast);
  const sEma = calcEMA(bars, slow);
  const fMap = new Map(fEma.map((f) => [f.time, f.value]));

  const macdLine: Bar[] = sEma
    .map((s) => {
      const fv = fMap.get(s.time);
      return {
        time: s.time as any,
        open: 0,
        high: 0,
        low: 0,
        close: fv != null ? fv - s.value : 0,
        volume: 0,
      };
    })
    .filter((b) => fMap.has(b.time as any));

  const sigLine = calcEMA(macdLine, signal);
  const sigMap = new Map(sigLine.map((s) => [s.time, s.value]));

  const macd: { time: UTCTimestamp; value: number }[] = [];
  const sig: { time: UTCTimestamp; value: number }[] = [];
  const hist: { time: UTCTimestamp; value: number; color: string }[] = [];

  for (const m of macdLine) {
    const sv = sigMap.get(m.time as any);
    if (sv != null) {
      const h = m.close - sv;
      const t = m.time as UTCTimestamp;
      macd.push({ time: t, value: m.close });
      sig.push({ time: t, value: sv });
      hist.push({
        time: t,
        value: h,
        color: h >= 0 ? "rgba(16,185,129,0.85)" : "rgba(239,68,68,0.85)",
      });
    }
  }
  return { macd, signal: sig, histogram: hist };
}

const AVAILABLE_TFS = ["1m", "3m", "5m", "15m", "1h", "4h"];

export default function SpotChartModal({ signal, onClose }: SpotChartModalProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const activeSeriesMapRef = useRef<Map<string, ISeriesApi<any>>>(new Map());

  const [interval, setIntervalTf] = useState<string>(signal.timeframe || "5m");
  const [loading, setLoading] = useState(true);
  const [wsActive, setWsActive] = useState(false);
  const [livePrice, setLivePrice] = useState<number>(signal.current_price);
  const [priceChangePct, setPriceChangePct] = useState<number>(signal.pnl_pct);
  const [showIndicatorsMenu, setShowIndicatorsMenu] = useState(false);

  // Gösterge Seçimleri
  const [indicators, setIndicators] = useState<ActiveIndicators>({
    ema50: true,
    ema20: false,
    ema200: false,
    bollinger: false,
    supertrend: false,
    vwap: false,
    kdj: true,
    rsi: false,
    macd: false,
  });

  // Canlı HUD Değerleri
  const [hudValues, setHudValues] = useState<{
    kdj?: { k: number; d: number; j: number };
    rsi?: number;
    macd?: { macd: number; signal: number; hist: number };
  }>({});

  const barsRef = useRef<Bar[]>([]);
  const wsTimerRef = useRef<NodeJS.Timeout | null>(null);

  // Esc tuşu ile kapatma
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  // Chart Container Başlatma
  useEffect(() => {
    if (!containerRef.current) return;

    if (chartRef.current) {
      chartRef.current.remove();
      chartRef.current = null;
    }

    const chart = createChart(containerRef.current, {
      width: containerRef.current.clientWidth,
      height: containerRef.current.clientHeight || 540,
      layout: {
        background: { type: ColorType.Solid, color: "#06090e" },
        textColor: "#94a3b8",
        fontFamily: "JetBrains Mono, monospace",
        fontSize: 11,
      },
      grid: {
        vertLines: { color: "rgba(30, 41, 59, 0.45)" },
        horzLines: { color: "rgba(30, 41, 59, 0.45)" },
      },
      crosshair: {
        mode: 0,
        vertLine: { color: "#38bdf8", width: 1, style: LineStyle.Dashed },
        horzLine: { color: "#38bdf8", width: 1, style: LineStyle.Dashed },
      },
      timeScale: {
        timeVisible: true,
        secondsVisible: false,
        borderColor: "#1e293b",
      },
      rightPriceScale: {
        borderColor: "#1e293b",
        scaleMargins: { top: 0.1, bottom: 0.12 },
      },
    });

    chartRef.current = chart;

    // Ana Mum Serisi (Pane 0)
    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: "#10b981",
      downColor: "#f43f5e",
      borderVisible: false,
      wickUpColor: "#10b981",
      wickDownColor: "#f43f5e",
    });
    candleSeriesRef.current = candleSeries;

    // Hedef TP, SL ve Giriş çizgileri (Pane 0)
    if (signal.target_price > 0) {
      candleSeries.createPriceLine({
        price: signal.target_price,
        color: "#10b981",
        lineWidth: 1,
        lineStyle: LineStyle.Dashed,
        axisLabelVisible: true,
        title: `TP: ₺${formatPrice(signal.target_price)}`,
      });
    }
    if (signal.stop_price > 0) {
      candleSeries.createPriceLine({
        price: signal.stop_price,
        color: "#f43f5e",
        lineWidth: 1,
        lineStyle: LineStyle.Dashed,
        axisLabelVisible: true,
        title: `SL: ₺${formatPrice(signal.stop_price)}`,
      });
    }
    if (signal.entry_price > 0) {
      candleSeries.createPriceLine({
        price: signal.entry_price,
        color: "#94a3b8",
        lineWidth: 1,
        lineStyle: LineStyle.Dotted,
        axisLabelVisible: true,
        title: `Giriş: ₺${formatPrice(signal.entry_price)}`,
      });
    }

    const ro = new ResizeObserver(() => {
      if (!chartRef.current || !containerRef.current) return;
      chartRef.current.applyOptions({
        width: containerRef.current.clientWidth,
        height: containerRef.current.clientHeight,
      });
    });
    ro.observe(containerRef.current);

    return () => {
      ro.disconnect();
      chart.remove();
      chartRef.current = null;
      candleSeriesRef.current = null;
      activeSeriesMapRef.current.clear();
    };
  }, [signal.entry_price, signal.target_price, signal.stop_price]);

  // Göstergeleri dinamik olarak inşa et ve verileri bas
  const rebuildAndApplyIndicators = useCallback(
    (bars: Bar[]) => {
      const chart = chartRef.current;
      if (!chart || !bars.length) return;

      // Önceki indikatör serilerini temizle
      activeSeriesMapRef.current.forEach((s) => {
        try {
          chart.removeSeries(s);
        } catch {}
      });
      activeSeriesMapRef.current.clear();

      const newHud: typeof hudValues = {};

      // ── 1. GRAFİK ÜSTÜ (OVERLAY - PANE 0) ───────────────────────────────────

      // EMA 50
      if (indicators.ema50) {
        const d = calcEMA(bars, 50);
        if (d.length) {
          const s = chart.addSeries(LineSeries, {
            color: "#00d2ff",
            lineWidth: 2,
            title: "EMA 50",
            priceLineVisible: false,
          });
          s.setData(d);
          activeSeriesMapRef.current.set("ema50", s);
        }
      }

      // EMA 20
      if (indicators.ema20) {
        const d = calcEMA(bars, 20);
        if (d.length) {
          const s = chart.addSeries(LineSeries, {
            color: "#f59e0b",
            lineWidth: 1,
            title: "EMA 20",
            priceLineVisible: false,
          });
          s.setData(d);
          activeSeriesMapRef.current.set("ema20", s);
        }
      }

      // EMA 200
      if (indicators.ema200) {
        const d = calcEMA(bars, 200);
        if (d.length) {
          const s = chart.addSeries(LineSeries, {
            color: "#a855f7",
            lineWidth: 2,
            title: "EMA 200",
            priceLineVisible: false,
          });
          s.setData(d);
          activeSeriesMapRef.current.set("ema200", s);
        }
      }

      // Bollinger Bantları (20, 2)
      if (indicators.bollinger) {
        const bb = calcBollinger(bars);
        if (bb.middle.length) {
          const mid = chart.addSeries(LineSeries, {
            color: "rgba(129, 140, 248, 0.6)",
            lineWidth: 1,
            lineStyle: LineStyle.Dotted,
            title: "BB Mid",
            priceLineVisible: false,
          });
          const up = chart.addSeries(LineSeries, {
            color: "rgba(129, 140, 248, 0.9)",
            lineWidth: 1,
            title: "BB Up",
            priceLineVisible: false,
          });
          const low = chart.addSeries(LineSeries, {
            color: "rgba(129, 140, 248, 0.9)",
            lineWidth: 1,
            title: "BB Low",
            priceLineVisible: false,
          });
          mid.setData(bb.middle);
          up.setData(bb.upper);
          low.setData(bb.lower);
          activeSeriesMapRef.current.set("bb_mid", mid);
          activeSeriesMapRef.current.set("bb_up", up);
          activeSeriesMapRef.current.set("bb_low", low);
        }
      }

      // SuperTrend (10, 3)
      if (indicators.supertrend) {
        const st = calcSupertrend(bars);
        if (st.trend.length) {
          const s = chart.addSeries(LineSeries, {
            color: "#10b981",
            lineWidth: 2,
            title: "SuperTrend",
            priceLineVisible: false,
          });
          s.setData(st.trend);
          activeSeriesMapRef.current.set("supertrend", s);
        }
      }

      // VWAP
      if (indicators.vwap) {
        const v = calcVWAP(bars);
        if (v.length) {
          const s = chart.addSeries(LineSeries, {
            color: "#eab308",
            lineWidth: 2,
            lineStyle: LineStyle.Dashed,
            title: "VWAP",
            priceLineVisible: false,
          });
          s.setData(v);
          activeSeriesMapRef.current.set("vwap", s);
        }
      }

      // ── 2. ALT PANELLER (SUB-PANES) ─────────────────────────────────────────
      let subpane = 1;

      // KDJ (9, 3, 3)
      if (indicators.kdj) {
        const kdj = calcKDJ(bars, 9, 3);
        if (kdj.k.length) {
          const kS = chart.addSeries(
            LineSeries,
            {
              color: "#f59e0b",
              lineWidth: 1,
              title: "K",
              priceScaleId: "kdj_scale",
              priceLineVisible: false,
            },
            subpane
          );
          const dS = chart.addSeries(
            LineSeries,
            {
              color: "#3b82f6",
              lineWidth: 1,
              title: "D",
              priceScaleId: "kdj_scale",
              priceLineVisible: false,
            },
            subpane
          );
          const jS = chart.addSeries(
            LineSeries,
            {
              color: "#c084fc",
              lineWidth: 2,
              title: "J",
              priceScaleId: "kdj_scale",
              priceLineVisible: false,
            },
            subpane
          );

          kS.setData(kdj.k);
          dS.setData(kdj.d);
          jS.setData(kdj.j);

          kS.createPriceLine({
            price: 80,
            color: "rgba(244, 63, 94, 0.45)",
            lineWidth: 1,
            lineStyle: LineStyle.Dotted,
            axisLabelVisible: true,
            title: "80",
          });
          kS.createPriceLine({
            price: 20,
            color: "rgba(16, 185, 129, 0.45)",
            lineWidth: 1,
            lineStyle: LineStyle.Dotted,
            axisLabelVisible: true,
            title: "20",
          });

          chart.priceScale("kdj_scale", subpane).applyOptions({
            scaleMargins: { top: 0.1, bottom: 0.1 },
          });

          activeSeriesMapRef.current.set("kdj_k", kS);
          activeSeriesMapRef.current.set("kdj_d", dS);
          activeSeriesMapRef.current.set("kdj_j", jS);

          newHud.kdj = {
            k: kdj.k[kdj.k.length - 1].value,
            d: kdj.d[kdj.d.length - 1].value,
            j: kdj.j[kdj.j.length - 1].value,
          };
          subpane++;
        }
      }

      // RSI (14)
      if (indicators.rsi) {
        const rsiData = calcRSI(bars, 14);
        if (rsiData.length) {
          const rsiS = chart.addSeries(
            LineSeries,
            {
              color: "#06b6d4",
              lineWidth: 1,
              title: "RSI 14",
              priceScaleId: "rsi_scale",
              priceLineVisible: false,
            },
            subpane
          );
          rsiS.setData(rsiData);

          rsiS.createPriceLine({
            price: 70,
            color: "rgba(244, 63, 94, 0.5)",
            lineWidth: 1,
            lineStyle: LineStyle.Dashed,
            axisLabelVisible: true,
            title: "70",
          });
          rsiS.createPriceLine({
            price: 30,
            color: "rgba(16, 185, 129, 0.5)",
            lineWidth: 1,
            lineStyle: LineStyle.Dashed,
            axisLabelVisible: true,
            title: "30",
          });

          chart.priceScale("rsi_scale", subpane).applyOptions({
            scaleMargins: { top: 0.1, bottom: 0.1 },
          });

          activeSeriesMapRef.current.set("rsi", rsiS);
          newHud.rsi = rsiData[rsiData.length - 1].value;
          subpane++;
        }
      }

      // MACD (12, 26, 9)
      if (indicators.macd) {
        const { macd, signal: sig, histogram } = calcMACD(bars);
        if (macd.length) {
          const hist = chart.addSeries(
            HistogramSeries,
            { title: "MACD Hist", priceScaleId: "macd_scale" },
            subpane
          );
          hist.setData(histogram);

          const line = chart.addSeries(
            LineSeries,
            {
              color: "#3b82f6",
              lineWidth: 1,
              title: "MACD",
              priceScaleId: "macd_scale",
              priceLineVisible: false,
            },
            subpane
          );
          line.setData(macd);

          const sigS = chart.addSeries(
            LineSeries,
            {
              color: "#f59e0b",
              lineWidth: 1,
              title: "Signal",
              priceScaleId: "macd_scale",
              priceLineVisible: false,
            },
            subpane
          );
          sigS.setData(sig);

          chart.priceScale("macd_scale", subpane).applyOptions({
            scaleMargins: { top: 0.15, bottom: 0.15 },
          });

          activeSeriesMapRef.current.set("macd_hist", hist);
          activeSeriesMapRef.current.set("macd_line", line);
          activeSeriesMapRef.current.set("macd_sig", sigS);

          newHud.macd = {
            macd: macd[macd.length - 1].value,
            signal: sig[sig.length - 1].value,
            hist: histogram[histogram.length - 1].value,
          };
          subpane++;
        }
      }

      setHudValues(newHud);
    },
    [indicators]
  );

  // Mumları ve göstergeleri uygula
  const applyBars = useCallback(
    (bars: Bar[]) => {
      barsRef.current = bars;
      if (!bars.length || !candleSeriesRef.current) return;

      // Mum verisi
      candleSeriesRef.current.setData(
        bars.map((b) => ({
          time: b.time as UTCTimestamp,
          open: b.open,
          high: b.high,
          low: b.low,
          close: b.close,
        }))
      );

      // Son mum ve fiyat hassasiyeti
      const lastBar = bars[bars.length - 1];
      if (lastBar) {
        setLivePrice(lastBar.close);
        const prec = pricePrecision(lastBar.close);
        candleSeriesRef.current.applyOptions({
          priceFormat: {
            type: "price",
            precision: prec,
            minMove: 1 / Math.pow(10, prec),
          },
        });

        if (signal.entry_price > 0) {
          const change = ((lastBar.close - signal.entry_price) / signal.entry_price) * 100;
          setPriceChangePct(change);
        }
      }

      rebuildAndApplyIndicators(bars);
    },
    [signal.entry_price, rebuildAndApplyIndicators]
  );

  // HTTP API ile Klines çekme
  const fetchKlines = useCallback(async () => {
    try {
      const cleanSym = signal.symbol.replace(/[\/_]/g, "").toUpperCase();
      const res = await apiRequest(
        `${API_BASE}/api/market-klines/${cleanSym}?interval=${interval}&limit=250`
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const payload = await res.json();
      const rawCandles = payload.candles || [];
      if (!rawCandles.length) return;

      const bars: Bar[] = rawCandles.map((k: number[]) => ({
        time: Math.floor(k[0] / 1000),
        open: Number(k[1]),
        high: Number(k[2]),
        low: Number(k[3]),
        close: Number(k[4]),
        volume: Number(k[5]),
      }));

      applyBars(bars);
      setLoading(false);
    } catch (err) {
      console.error("SpotChartModal mum verisi hatası:", err);
      setLoading(false);
    }
  }, [signal.symbol, interval, applyBars]);

  // Periyodik fetch
  useEffect(() => {
    setLoading(true);
    fetchKlines();
    const intervalTimer = setInterval(fetchKlines, 5000);
    return () => clearInterval(intervalTimer);
  }, [fetchKlines]);

  // WebSocket Canlı Akış Dinleyicisi
  useEffect(() => {
    const cleanSym = signal.symbol.replace(/[\/_]/g, "").toUpperCase();

    const unsubscribe = subscribeLive((msg) => {
      if (msg.type === "kline" && msg.data) {
        const d = msg.data as {
          symbol?: string;
          timeframe?: string;
          time?: number;
          open?: number;
          high?: number;
          low?: number;
          close?: number;
          volume?: number;
        };

        const msgSym = (d.symbol || "").toUpperCase();
        if (msgSym === cleanSym && d.timeframe === interval && d.time && d.close != null) {
          setWsActive(true);
          setLivePrice(d.close);

          if (wsTimerRef.current) clearTimeout(wsTimerRef.current);
          wsTimerRef.current = setTimeout(() => setWsActive(false), 8000);

          const currentBars = [...barsRef.current];
          if (!currentBars.length) return;

          const lastBar = currentBars[currentBars.length - 1];
          const newBarTime = Math.floor(d.time > 10000000000 ? d.time / 1000 : d.time);

          if (lastBar.time === newBarTime) {
            lastBar.close = d.close;
            if (d.high != null && d.high > lastBar.high) lastBar.high = d.high;
            if (d.low != null && d.low < lastBar.low) lastBar.low = d.low;
            if (d.volume != null) lastBar.volume = d.volume;
          } else if (newBarTime > lastBar.time) {
            currentBars.push({
              time: newBarTime,
              open: d.open ?? d.close,
              high: d.high ?? d.close,
              low: d.low ?? d.close,
              close: d.close,
              volume: d.volume ?? 0,
            });
            if (currentBars.length > 300) currentBars.shift();
          }

          applyBars(currentBars);
        }
      }
    });

    return () => {
      unsubscribe();
      if (wsTimerRef.current) clearTimeout(wsTimerRef.current);
    };
  }, [signal.symbol, interval, applyBars]);

  // Gösterge Aç/Kapa Değişimi
  const toggleIndicator = (key: keyof ActiveIndicators) => {
    setIndicators((prev) => {
      const next = { ...prev, [key]: !prev[key] };
      return next;
    });
  };

  const activeCount = Object.values(indicators).filter(Boolean).length;
  const pnlColor = priceChangePct >= 0 ? "text-emerald-400" : "text-rose-400";

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-2 sm:p-4 bg-black/85 backdrop-blur-sm animate-in fade-in"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="relative w-full max-w-6xl h-[94vh] bg-bunker-950 rounded-2xl border border-bunker-700 shadow-2xl flex flex-col overflow-hidden">
        {/* 1. ÜST BAŞLIK BARI */}
        <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-3 bg-bunker-900 border-b border-bunker-800">
          <div className="flex items-center gap-3">
            <div className="flex items-baseline gap-2">
              <span className="text-xl font-bold font-mono text-white tracking-wide">
                {signal.symbol}
              </span>
              <span className="text-xs font-semibold px-2 py-0.5 rounded bg-cyan-950 text-cyan-300 border border-cyan-800/60 font-mono">
                {signal.strategy_label}
              </span>
            </div>

            {/* Timeframe Seçicileri */}
            <div className="flex items-center bg-bunker-950 rounded-lg p-0.5 border border-bunker-800">
              {AVAILABLE_TFS.map((tf) => (
                <button
                  key={tf}
                  type="button"
                  onClick={() => setIntervalTf(tf)}
                  className={`px-2.5 py-1 text-xs font-mono font-medium rounded-md transition-all ${
                    interval === tf
                      ? "bg-cyan-500 text-bunker-950 font-bold shadow-sm"
                      : "text-bunker-muted hover:text-white"
                  }`}
                >
                  {tf}
                </button>
              ))}
            </div>
          </div>

          {/* SAĞ KISIM: GÖSTERGELER & FİYAT & WS & KAPAT */}
          <div className="flex items-center gap-3 font-mono">
            {/* Hızlı Gösterge Butonları */}
            <div className="hidden lg:flex items-center gap-1 bg-bunker-950 p-1 rounded-lg border border-bunker-800 text-[11px]">
              <button
                type="button"
                onClick={() => toggleIndicator("ema50")}
                className={`px-2 py-0.5 rounded transition-colors ${
                  indicators.ema50
                    ? "bg-[#00d2ff]/20 text-[#00d2ff] font-bold border border-[#00d2ff]/40"
                    : "text-bunker-muted hover:text-white"
                }`}
              >
                EMA50
              </button>
              <button
                type="button"
                onClick={() => toggleIndicator("ema20")}
                className={`px-2 py-0.5 rounded transition-colors ${
                  indicators.ema20
                    ? "bg-[#f59e0b]/20 text-[#f59e0b] font-bold border border-[#f59e0b]/40"
                    : "text-bunker-muted hover:text-white"
                }`}
              >
                EMA20
              </button>
              <button
                type="button"
                onClick={() => toggleIndicator("bollinger")}
                className={`px-2 py-0.5 rounded transition-colors ${
                  indicators.bollinger
                    ? "bg-[#818cf8]/20 text-[#818cf8] font-bold border border-[#818cf8]/40"
                    : "text-bunker-muted hover:text-white"
                }`}
              >
                Bollinger
              </button>
              <button
                type="button"
                onClick={() => toggleIndicator("supertrend")}
                className={`px-2 py-0.5 rounded transition-colors ${
                  indicators.supertrend
                    ? "bg-[#10b981]/20 text-[#10b981] font-bold border border-[#10b981]/40"
                    : "text-bunker-muted hover:text-white"
                }`}
              >
                SuperTrend
              </button>
              <button
                type="button"
                onClick={() => toggleIndicator("kdj")}
                className={`px-2 py-0.5 rounded transition-colors ${
                  indicators.kdj
                    ? "bg-[#c084fc]/20 text-[#c084fc] font-bold border border-[#c084fc]/40"
                    : "text-bunker-muted hover:text-white"
                }`}
              >
                KDJ
              </button>
              <button
                type="button"
                onClick={() => toggleIndicator("rsi")}
                className={`px-2 py-0.5 rounded transition-colors ${
                  indicators.rsi
                    ? "bg-[#06b6d4]/20 text-[#06b6d4] font-bold border border-[#06b6d4]/40"
                    : "text-bunker-muted hover:text-white"
                }`}
              >
                RSI
              </button>
              <button
                type="button"
                onClick={() => toggleIndicator("macd")}
                className={`px-2 py-0.5 rounded transition-colors ${
                  indicators.macd
                    ? "bg-[#3b82f6]/20 text-[#3b82f6] font-bold border border-[#3b82f6]/40"
                    : "text-bunker-muted hover:text-white"
                }`}
              >
                MACD
              </button>
            </div>

            {/* Tüm Göstergeler Açılır Menü Butonu */}
            <div className="relative">
              <button
                type="button"
                onClick={() => setShowIndicatorsMenu(!showIndicatorsMenu)}
                className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-bunker-800 hover:bg-bunker-750 text-slate-200 text-xs font-semibold border border-bunker-700 transition-colors"
              >
                <span>📐 Göstergeler ({activeCount})</span>
                <span className="text-[10px]">▼</span>
              </button>

              {/* Açılır Panel */}
              {showIndicatorsMenu && (
                <div
                  className="absolute right-0 top-full mt-2 w-72 bg-bunker-900 border border-bunker-700 rounded-xl shadow-2xl p-3 z-50 animate-in fade-in slide-in-from-top-2"
                  onClick={(e) => e.stopPropagation()}
                >
                  <div className="flex items-center justify-between pb-2 border-b border-bunker-800">
                    <span className="text-xs font-bold text-white uppercase">Gösterge Seçimi</span>
                    <button
                      type="button"
                      onClick={() => setShowIndicatorsMenu(false)}
                      className="text-bunker-muted hover:text-white text-xs"
                    >
                      ✕
                    </button>
                  </div>

                  <div className="mt-2.5 space-y-3 text-xs">
                    {/* Grafik Üstü */}
                    <div>
                      <p className="text-[10px] uppercase font-bold text-cyan-400 mb-1">
                        Grafik Üzeri (Overlay)
                      </p>
                      <div className="space-y-1.5">
                        <label className="flex items-center justify-between cursor-pointer hover:bg-bunker-800/60 p-1.5 rounded">
                          <span className="flex items-center gap-2">
                            <span className="w-2.5 h-0.5 bg-[#00d2ff]" /> EMA 50 (Destek/Direnç)
                          </span>
                          <input
                            type="checkbox"
                            checked={indicators.ema50}
                            onChange={() => toggleIndicator("ema50")}
                            className="rounded bg-bunker-950 border-bunker-700 text-cyan-500 focus:ring-0"
                          />
                        </label>

                        <label className="flex items-center justify-between cursor-pointer hover:bg-bunker-800/60 p-1.5 rounded">
                          <span className="flex items-center gap-2">
                            <span className="w-2.5 h-0.5 bg-[#f59e0b]" /> EMA 20 (Hızlı Trend)
                          </span>
                          <input
                            type="checkbox"
                            checked={indicators.ema20}
                            onChange={() => toggleIndicator("ema20")}
                            className="rounded bg-bunker-950 border-bunker-700 text-cyan-500 focus:ring-0"
                          />
                        </label>

                        <label className="flex items-center justify-between cursor-pointer hover:bg-bunker-800/60 p-1.5 rounded">
                          <span className="flex items-center gap-2">
                            <span className="w-2.5 h-0.5 bg-[#a855f7]" /> EMA 200 (Ana Trend)
                          </span>
                          <input
                            type="checkbox"
                            checked={indicators.ema200}
                            onChange={() => toggleIndicator("ema200")}
                            className="rounded bg-bunker-950 border-bunker-700 text-cyan-500 focus:ring-0"
                          />
                        </label>

                        <label className="flex items-center justify-between cursor-pointer hover:bg-bunker-800/60 p-1.5 rounded">
                          <span className="flex items-center gap-2">
                            <span className="w-2.5 h-0.5 bg-[#818cf8]" /> Bollinger Bantları (20,2)
                          </span>
                          <input
                            type="checkbox"
                            checked={indicators.bollinger}
                            onChange={() => toggleIndicator("bollinger")}
                            className="rounded bg-bunker-950 border-bunker-700 text-cyan-500 focus:ring-0"
                          />
                        </label>

                        <label className="flex items-center justify-between cursor-pointer hover:bg-bunker-800/60 p-1.5 rounded">
                          <span className="flex items-center gap-2">
                            <span className="w-2.5 h-0.5 bg-[#10b981]" /> SuperTrend (10, 3)
                          </span>
                          <input
                            type="checkbox"
                            checked={indicators.supertrend}
                            onChange={() => toggleIndicator("supertrend")}
                            className="rounded bg-bunker-950 border-bunker-700 text-cyan-500 focus:ring-0"
                          />
                        </label>

                        <label className="flex items-center justify-between cursor-pointer hover:bg-bunker-800/60 p-1.5 rounded">
                          <span className="flex items-center gap-2">
                            <span className="w-2.5 h-0.5 bg-[#eab308]" /> VWAP (Hacim Ağırlıklı)
                          </span>
                          <input
                            type="checkbox"
                            checked={indicators.vwap}
                            onChange={() => toggleIndicator("vwap")}
                            className="rounded bg-bunker-950 border-bunker-700 text-cyan-500 focus:ring-0"
                          />
                        </label>
                      </div>
                    </div>

                    {/* Alt Paneller */}
                    <div className="pt-2 border-t border-bunker-800">
                      <p className="text-[10px] uppercase font-bold text-amber-400 mb-1">
                        Alt Paneller (Osilatörler)
                      </p>
                      <div className="space-y-1.5">
                        <label className="flex items-center justify-between cursor-pointer hover:bg-bunker-800/60 p-1.5 rounded">
                          <span className="flex items-center gap-2">
                            <span className="w-2.5 h-0.5 bg-[#c084fc]" /> KDJ (9, 3, 3 - Dip Avcısı)
                          </span>
                          <input
                            type="checkbox"
                            checked={indicators.kdj}
                            onChange={() => toggleIndicator("kdj")}
                            className="rounded bg-bunker-950 border-bunker-700 text-cyan-500 focus:ring-0"
                          />
                        </label>

                        <label className="flex items-center justify-between cursor-pointer hover:bg-bunker-800/60 p-1.5 rounded">
                          <span className="flex items-center gap-2">
                            <span className="w-2.5 h-0.5 bg-[#06b6d4]" /> RSI (14 - Güç Endeksi)
                          </span>
                          <input
                            type="checkbox"
                            checked={indicators.rsi}
                            onChange={() => toggleIndicator("rsi")}
                            className="rounded bg-bunker-950 border-bunker-700 text-cyan-500 focus:ring-0"
                          />
                        </label>

                        <label className="flex items-center justify-between cursor-pointer hover:bg-bunker-800/60 p-1.5 rounded">
                          <span className="flex items-center gap-2">
                            <span className="w-2.5 h-0.5 bg-[#3b82f6]" /> MACD (12, 26, 9)
                          </span>
                          <input
                            type="checkbox"
                            checked={indicators.macd}
                            onChange={() => toggleIndicator("macd")}
                            className="rounded bg-bunker-950 border-bunker-700 text-cyan-500 focus:ring-0"
                          />
                        </label>
                      </div>
                    </div>
                  </div>
                </div>
              )}
            </div>

            {/* Canlı Fiyat */}
            <div className="flex items-baseline gap-2">
              <span className="text-lg font-bold text-white">
                ₺
                {livePrice > 10
                  ? livePrice.toLocaleString("tr-TR", { minimumFractionDigits: 2 })
                  : livePrice}
              </span>
              <span className={`text-xs font-semibold ${pnlColor}`}>
                {priceChangePct >= 0 ? "+" : ""}
                {priceChangePct.toFixed(2)}%
              </span>
            </div>

            {/* WS Durum Rozeti */}
            <div
              className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-semibold border ${
                wsActive
                  ? "bg-emerald-950/80 text-emerald-400 border-emerald-700/60"
                  : "bg-bunker-800/80 text-slate-400 border-bunker-750"
              }`}
            >
              <span
                className={`w-2 h-2 rounded-full ${
                  wsActive ? "bg-emerald-400 animate-pulse" : "bg-slate-500"
                }`}
              />
              <span>{wsActive ? "WS CANLI" : "SENKRONİZE"}</span>
            </div>

            {/* Kapat Butonu */}
            <button
              type="button"
              onClick={onClose}
              className="p-1.5 text-bunker-muted hover:text-white hover:bg-bunker-800 rounded-lg transition-colors"
              title="Kapat (Esc)"
            >
              <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
        </div>

        {/* 2. BİLGİ & CANLI GÖSTERGE DEĞERLERİ HUD */}
        <div className="flex flex-wrap items-center justify-between gap-4 px-4 py-2 bg-bunker-900/60 border-b border-bunker-800 text-xs font-mono">
          <div className="flex items-center gap-4 text-bunker-muted">
            <span>
              Giriş: <strong className="text-slate-200">₺{formatPrice(signal.entry_price)}</strong>
            </span>
            <span>
              TP: <strong className="text-emerald-400">₺{formatPrice(signal.target_price)}</strong>
            </span>
            <span>
              SL: <strong className="text-rose-400">₺{formatPrice(signal.stop_price)}</strong>
            </span>
            <span>
              Net Kâr (300₺): <strong className={pnlColor}>₺{signal.net_pnl_try?.toFixed(2) || "0.00"}</strong>
            </span>
          </div>

          {/* Dinamik Canlı Değerler */}
          <div className="flex items-center gap-4">
            {indicators.kdj && hudValues.kdj && (
              <div className="flex items-center gap-2">
                <span className="text-amber-400 font-bold">K: {hudValues.kdj.k.toFixed(1)}</span>
                <span className="text-blue-400 font-bold">D: {hudValues.kdj.d.toFixed(1)}</span>
                <span className="text-purple-400 font-bold">J: {hudValues.kdj.j.toFixed(1)}</span>
              </div>
            )}
            {indicators.rsi && hudValues.rsi != null && (
              <div className="flex items-center gap-1.5">
                <span className="text-cyan-400 font-bold">RSI(14): {hudValues.rsi.toFixed(1)}</span>
              </div>
            )}
            {indicators.macd && hudValues.macd && (
              <div className="flex items-center gap-2 text-[11px]">
                <span className="text-blue-400">MACD: {hudValues.macd.macd.toFixed(2)}</span>
                <span className="text-amber-400">Sig: {hudValues.macd.signal.toFixed(2)}</span>
                <span className={hudValues.macd.hist >= 0 ? "text-emerald-400" : "text-rose-400"}>
                  H: {hudValues.macd.hist.toFixed(2)}
                </span>
              </div>
            )}
          </div>
        </div>

        {/* 3. GRAFİK ALANI */}
        <div className="relative flex-1 w-full h-full bg-[#06090e]">
          {loading && (
            <div className="absolute inset-0 z-10 flex items-center justify-center bg-bunker-950/70 backdrop-blur-xs">
              <div className="flex items-center gap-2 text-cyan-400 font-mono text-sm">
                <span className="w-4 h-4 border-2 border-cyan-400 border-t-transparent rounded-full animate-spin" />
                <span>Binance TR verileri ve göstergeler yükleniyor...</span>
              </div>
            </div>
          )}
          <div ref={containerRef} className="w-full h-full" />
        </div>

        {/* 4. ALT LEJANT & BİLGİ BARI */}
        <div className="flex items-center justify-between px-4 py-2 bg-bunker-950 border-t border-bunker-800 text-[11px] font-mono text-bunker-muted">
          <div className="flex flex-wrap items-center gap-3">
            <span className="text-slate-400 font-semibold">Aktif Göstergeler:</span>
            {indicators.ema50 && (
              <span className="flex items-center gap-1 text-[#00d2ff]">
                <span className="w-2.5 h-0.5 bg-[#00d2ff]" /> EMA 50
              </span>
            )}
            {indicators.ema20 && (
              <span className="flex items-center gap-1 text-[#f59e0b]">
                <span className="w-2.5 h-0.5 bg-[#f59e0b]" /> EMA 20
              </span>
            )}
            {indicators.ema200 && (
              <span className="flex items-center gap-1 text-[#a855f7]">
                <span className="w-2.5 h-0.5 bg-[#a855f7]" /> EMA 200
              </span>
            )}
            {indicators.bollinger && (
              <span className="flex items-center gap-1 text-[#818cf8]">
                <span className="w-2.5 h-0.5 bg-[#818cf8]" /> Bollinger (20,2)
              </span>
            )}
            {indicators.supertrend && (
              <span className="flex items-center gap-1 text-[#10b981]">
                <span className="w-2.5 h-0.5 bg-[#10b981]" /> SuperTrend
              </span>
            )}
            {indicators.vwap && (
              <span className="flex items-center gap-1 text-[#eab308]">
                <span className="w-2.5 h-0.5 bg-[#eab308]" /> VWAP
              </span>
            )}
            {indicators.kdj && (
              <span className="flex items-center gap-1 text-[#c084fc]">
                <span className="w-2.5 h-0.5 bg-[#c084fc]" /> KDJ(9,3)
              </span>
            )}
            {indicators.rsi && (
              <span className="flex items-center gap-1 text-[#06b6d4]">
                <span className="w-2.5 h-0.5 bg-[#06b6d4]" /> RSI(14)
              </span>
            )}
            {indicators.macd && (
              <span className="flex items-center gap-1 text-[#3b82f6]">
                <span className="w-2.5 h-0.5 bg-[#3b82f6]" /> MACD
              </span>
            )}
          </div>
          <div className="hidden sm:block">Kapatmak için Esc tuşuna basabilirsiniz</div>
        </div>
      </div>
    </div>
  );
}
