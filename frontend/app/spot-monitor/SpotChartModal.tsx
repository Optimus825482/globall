"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import {
  createChart,
  CandlestickSeries,
  LineSeries,
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
  status: "OPEN" | "WIN_TP" | "LOSS_SL" | "EXPIRED";
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

// ── Matematiksel Gösterge Hesaplayıcıları ─────────────────────────────────────
function calcEMA(bars: Bar[], period: number = 50): { time: UTCTimestamp; value: number }[] {
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
  const alpha = 1 / signal; // 1/3 standard
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

const AVAILABLE_TFS = ["1m", "3m", "5m", "15m", "1h", "4h"];

export default function SpotChartModal({ signal, onClose }: SpotChartModalProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const emaSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const kSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const dSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const jSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);

  const [interval, setIntervalTf] = useState<string>(signal.timeframe || "5m");
  const [loading, setLoading] = useState(true);
  const [wsActive, setWsActive] = useState(false);
  const [livePrice, setLivePrice] = useState<number>(signal.current_price);
  const [liveKdj, setLiveKdj] = useState<{ k: number; d: number; j: number } | null>(null);
  const [priceChangePct, setPriceChangePct] = useState<number>(signal.pnl_pct);

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

  // Chart initialization
  useEffect(() => {
    if (!containerRef.current) return;

    // Önceki grafiği temizle
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

    // ── Pane 0: Candlesticks ──
    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: "#10b981",
      downColor: "#f43f5e",
      borderVisible: false,
      wickUpColor: "#10b981",
      wickDownColor: "#f43f5e",
    });
    candleSeriesRef.current = candleSeries;

    // ── Pane 0: EMA 50 (Mavi/Camgöbeği) ──
    const emaSeries = chart.addSeries(LineSeries, {
      color: "#00d2ff",
      lineWidth: 2,
      title: "EMA 50",
      priceLineVisible: false,
    });
    emaSeriesRef.current = emaSeries;

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

    // ── Pane 1: KDJ Indicator Pane (Sub-pane) ──
    const kSeries = chart.addSeries(
      LineSeries,
      {
        color: "#f59e0b", // Amber %K
        lineWidth: 1,
        title: "K",
        priceScaleId: "kdj_scale",
        priceLineVisible: false,
      },
      1
    );
    kSeriesRef.current = kSeries;

    const dSeries = chart.addSeries(
      LineSeries,
      {
        color: "#3b82f6", // Mavi %D
        lineWidth: 1,
        title: "D",
        priceScaleId: "kdj_scale",
        priceLineVisible: false,
      },
      1
    );
    dSeriesRef.current = dSeries;

    const jSeries = chart.addSeries(
      LineSeries,
      {
        color: "#c084fc", // Mor %J
        lineWidth: 2,
        title: "J",
        priceScaleId: "kdj_scale",
        priceLineVisible: false,
      },
      1
    );
    jSeriesRef.current = jSeries;

    // KDJ Aşırı Alım (80) & Aşırı Satım (20) Seviyeleri
    kSeries.createPriceLine({
      price: 80,
      color: "rgba(244, 63, 94, 0.45)",
      lineWidth: 1,
      lineStyle: LineStyle.Dotted,
      axisLabelVisible: true,
      title: "80 (Aşırı Alım)",
    });
    kSeries.createPriceLine({
      price: 20,
      color: "rgba(16, 185, 129, 0.45)",
      lineWidth: 1,
      lineStyle: LineStyle.Dotted,
      axisLabelVisible: true,
      title: "20 (Dip / Aşırı Satım)",
    });

    chart.priceScale("kdj_scale", 1).applyOptions({
      scaleMargins: { top: 0.1, bottom: 0.1 },
    });

    // Resize gözlemcisi
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
      emaSeriesRef.current = null;
      kSeriesRef.current = null;
      dSeriesRef.current = null;
      jSeriesRef.current = null;
    };
  }, [signal.entry_price, signal.target_price, signal.stop_price]);

  // Mumları ve göstergeleri güncelle
  const applyBars = useCallback((bars: Bar[]) => {
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

    // EMA 50
    if (emaSeriesRef.current) {
      const emaData = calcEMA(bars, 50);
      emaSeriesRef.current.setData(emaData);
    }

    // KDJ (9, 3)
    if (kSeriesRef.current && dSeriesRef.current && jSeriesRef.current) {
      const kdj = calcKDJ(bars, 9, 3);
      kSeriesRef.current.setData(kdj.k);
      dSeriesRef.current.setData(kdj.d);
      jSeriesRef.current.setData(kdj.j);

      if (kdj.k.length > 0) {
        setLiveKdj({
          k: kdj.k[kdj.k.length - 1].value,
          d: kdj.d[kdj.d.length - 1].value,
          j: kdj.j[kdj.j.length - 1].value,
        });
      }
    }
  }, [signal.entry_price]);

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

  // Periyodik fetch (note_viewed canlılığını ve arka plan senkronizasyonunu sağlar)
  useEffect(() => {
    setLoading(true);
    fetchKlines();
    const intervalTimer = setInterval(fetchKlines, 5000);
    return () => clearInterval(intervalTimer);
  }, [fetchKlines]);

  // WebSocket Canlı Akış Dinleyicisi
  useEffect(() => {
    const cleanSym = signal.symbol.replace(/[\/_]/g, "").toUpperCase();

    // 1. Backend LiveSocket aboneliği (ws_live_candles)
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

          // WS nabız süresi
          if (wsTimerRef.current) clearTimeout(wsTimerRef.current);
          wsTimerRef.current = setTimeout(() => setWsActive(false), 8000);

          const currentBars = [...barsRef.current];
          if (!currentBars.length) return;

          const lastBar = currentBars[currentBars.length - 1];
          const newBarTime = Math.floor(d.time > 10000000000 ? d.time / 1000 : d.time);

          if (lastBar.time === newBarTime) {
            // Oluşan mumu güncelle
            lastBar.close = d.close;
            if (d.high != null && d.high > lastBar.high) lastBar.high = d.high;
            if (d.low != null && d.low < lastBar.low) lastBar.low = d.low;
            if (d.volume != null) lastBar.volume = d.volume;
          } else if (newBarTime > lastBar.time) {
            // Yeni mum açıldı
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

  const pnlColor = priceChangePct >= 0 ? "text-emerald-400" : "text-rose-400";

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-2 sm:p-4 bg-black/85 backdrop-blur-sm animate-in fade-in"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="relative w-full max-w-6xl h-[94vh] bg-bunker-950 rounded-2xl border border-bunker-700 shadow-2xl flex flex-col overflow-hidden">
        {/* ÜST BAŞLIK BARI */}
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

          {/* FİYAT & KÂR/ZARAR & WS ROZETİ */}
          <div className="flex items-center gap-4 font-mono">
            <div className="flex items-baseline gap-2">
              <span className="text-lg font-bold text-white">
                ₺{livePrice > 10 ? livePrice.toLocaleString("tr-TR", { minimumFractionDigits: 2 }) : livePrice}
              </span>
              <span className={`text-xs font-semibold ${pnlColor}`}>
                {priceChangePct >= 0 ? "+" : ""}{priceChangePct.toFixed(2)}%
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

            {/* Kapat Düğmesi */}
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

        {/* BİLGİ & SEVİYE ŞERİDİ */}
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

          {/* KDJ Canlı Değerleri */}
          {liveKdj && (
            <div className="flex items-center gap-3">
              <span className="text-amber-400 font-bold">K: {liveKdj.k.toFixed(1)}</span>
              <span className="text-blue-400 font-bold">D: {liveKdj.d.toFixed(1)}</span>
              <span className="text-purple-400 font-bold">J: {liveKdj.j.toFixed(1)}</span>
              <span className="text-[10px] text-bunker-muted">
                {liveKdj.j <= 20 ? "(Dip / Aşırı Satım)" : liveKdj.j >= 80 ? "(Aşırı Alım)" : "(Nötr)"}
              </span>
            </div>
          )}
        </div>

        {/* GRAFİK ALANI */}
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

        {/* ALT AÇIKLAMA BARI */}
        <div className="flex items-center justify-between px-4 py-2 bg-bunker-950 border-t border-bunker-800 text-[11px] font-mono text-bunker-muted">
          <div className="flex items-center gap-4">
            <span className="flex items-center gap-1.5">
              <span className="w-2.5 h-0.5 bg-[#00d2ff]" /> EMA 50 (Trend & Destek)
            </span>
            <span className="flex items-center gap-1.5">
              <span className="w-2.5 h-0.5 bg-[#f59e0b]" /> %K (Hızlı)
            </span>
            <span className="flex items-center gap-1.5">
              <span className="w-2.5 h-0.5 bg-[#3b82f6]" /> %D (Sinyal)
            </span>
            <span className="flex items-center gap-1.5">
              <span className="w-2.5 h-0.5 bg-[#c084fc]" /> %J (Momentum Dip Çizgisi)
            </span>
          </div>
          <div>Kapatmak için Esc tuşuna veya dışarıya tıklayabilirsiniz</div>
        </div>
      </div>
    </div>
  );
}
