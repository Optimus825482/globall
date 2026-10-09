"use client";

import React, { useEffect, useMemo, useRef, useState, useCallback } from "react";
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
import dynamic from "next/dynamic";
import { apiFetch } from "../../lib/api";
import { findIndicatorEntry, filterIndicatorInstances } from "../../charts/IndicatorPicker";
import {
  applySeries,
  applyStructure,
  computeHeights,
  desiredChartHeight,
  defaultMetaIndicators,
  structureSignature,
  updateLastPoints,
  type Engine,
} from "./forexIndicatorEngine";
import type { IndicatorInstance, IndicatorStyle, RegistryEntry } from "../../charts/types";
import { uid as newUid } from "../../charts/chartShared";

// Picker/ayar panelleri ağırdır (tüm registry'yi tarar) → yalnız açıldığında in.
const IndicatorPicker = dynamic(() => import("../../charts/IndicatorPicker").then((m) => m.default), { ssr: false });
const IndicatorSettings = dynamic(() => import("../../charts/IndicatorSettings"), { ssr: false });

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
  /**
   * Kompakt mod (MetaMobil): Üst bilgi/aksiyon çubuğunu ve "Ayrı Sayfa" gibi
   * gömülü-görünüm düğmelerini gizler. Periyot + gösterge seçici ve mum tuvali
   * korunur; sayfa kendi başlık/one-click barını zaten çiziyor.
   */
  compact?: boolean;
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
// BB / SMA / EMA / MACD artık `forexIndicatorEngine` üzerinden
// `lightweight-charts-indicators` registry'sinden hesaplanır; burada yalnızca
// header şeridinin kullandığı bağımsız yardımcılar kalır.

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

// ADX-14 (Wilder): TR/+DM/-DM yumuşatması → DI+/DI- → DX → ADX.
// Yalnız son değer döndürülür (başlıktaki canlı sayı için; seri çizilmez).
function calculateADXLatest(candles: CandleBar[], period = 14): number | null {
  if (candles.length < period * 2 + 1) return null;
  const trs: number[] = [];
  const plusDM: number[] = [];
  const minusDM: number[] = [];
  for (let i = 1; i < candles.length; i++) {
    const up = candles[i].high - candles[i - 1].high;
    const down = candles[i - 1].low - candles[i].low;
    plusDM.push(up > down && up > 0 ? up : 0);
    minusDM.push(down > up && down > 0 ? down : 0);
    trs.push(Math.max(
      candles[i].high - candles[i].low,
      Math.abs(candles[i].high - candles[i - 1].close),
      Math.abs(candles[i].low - candles[i - 1].close),
    ));
  }
  const dxOf = (tr: number, pdm: number, mdm: number) => {
    const pdi = tr > 0 ? (100 * pdm) / tr : 0;
    const mdi = tr > 0 ? (100 * mdm) / tr : 0;
    const sum = pdi + mdi;
    return sum > 0 ? (100 * Math.abs(pdi - mdi)) / sum : 0;
  };
  let tr = 0, pdm = 0, mdm = 0;
  for (let i = 0; i < period; i++) { tr += trs[i]; pdm += plusDM[i]; mdm += minusDM[i]; }
  const dxs: number[] = [dxOf(tr, pdm, mdm)];
  for (let i = period; i < trs.length; i++) {
    tr = tr - tr / period + trs[i];
    pdm = pdm - pdm / period + plusDM[i];
    mdm = mdm - mdm / period + minusDM[i];
    dxs.push(dxOf(tr, pdm, mdm));
  }
  if (dxs.length < period) return null;
  let adx = 0;
  for (let i = 0; i < period; i++) adx += dxs[i];
  adx /= period;
  for (let i = period; i < dxs.length; i++) adx = (adx * (period - 1) + dxs[i]) / period;
  return adx;
}

// CCI-14: tipik fiyat (H+L+C)/3 ortalamadan sapması / 0.015 × ortalama sapma.
function calculateCCILatest(candles: CandleBar[], period = 14): number | null {
  if (candles.length < period) return null;
  const win = candles.slice(candles.length - period);
  const tps = win.map((c) => (c.high + c.low + c.close) / 3);
  const sma = tps.reduce((a, b) => a + b, 0) / period;
  const md = tps.reduce((a, b) => a + Math.abs(b - sma), 0) / period;
  if (md === 0) return 0;
  return (tps[tps.length - 1] - sma) / (0.015 * md);
}

// Chandelier Exit (9, 3×ATR): ATR tabanlı iz süren stop seviyesi.
// `dir` +1 ise stop altta (uzun destek), -1 ise üstte (kısa direnç).
function calculateChandelierLatest(
  candles: CandleBar[],
  period = 9,
  mult = 3,
): { stop: number; dir: 1 | -1 } | null {
  if (candles.length < period + 2) return null;
  const trs: number[] = [candles[0].high - candles[0].low];
  for (let i = 1; i < candles.length; i++) {
    trs.push(Math.max(
      candles[i].high - candles[i].low,
      Math.abs(candles[i].high - candles[i - 1].close),
      Math.abs(candles[i].low - candles[i - 1].close),
    ));
  }
  let atr = trs.slice(1, period + 1).reduce((a, b) => a + b, 0) / period;
  const start = period + 1;
  let longStop = 0;
  let shortStop = 0;
  let dir: 1 | -1 = 1;
  let seeded = false;
  for (let i = start; i < candles.length; i++) {
    if (i > start) atr = (atr * (period - 1) + trs[i]) / period;
    const win = candles.slice(i - period + 1, i + 1);
    const highest = Math.max(...win.map((c) => c.high));
    const lowest = Math.min(...win.map((c) => c.low));
    const rawLong = highest - mult * atr;
    const rawShort = lowest + mult * atr;
    const prevClose = candles[i - 1].close;
    if (!seeded) {
      longStop = rawLong;
      shortStop = rawShort;
      dir = candles[i].close >= prevClose ? 1 : -1;
      seeded = true;
      continue;
    }
    longStop = prevClose > longStop ? Math.max(rawLong, longStop) : rawLong;
    shortStop = prevClose < shortStop ? Math.min(rawShort, shortStop) : rawShort;
    dir = candles[i].close > shortStop ? 1 : candles[i].close < longStop ? -1 : dir;
  }
  return { stop: dir === 1 ? longStop : shortStop, dir };
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
  compact = false,
}: ForexNativeChartProps) {
  const [timeframe, setTimeframe] = useState<Timeframe>(initialTimeframe);
  const [candles, setCandles] = useState<CandleBar[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Göstergeler: MT5 mobil akışı — `IndicatorPicker` ile eklenen HER indikatör
  // (kütüphanedeki 450+ dahil) kendi paneli/çizgisiyle çizilir. Varsayılan:
  // BB (overlay) + MACD (alt pane), kullanıcı isteği.
  const [indicators, setIndicators] = useState<IndicatorInstance[]>(() => {
    try {
      const raw = localStorage.getItem("scalper_metamobil_indicators");
      if (raw) {
        const parsed = filterIndicatorInstances(JSON.parse(raw) as IndicatorInstance[]);
        if (parsed.length) return parsed;
      }
    } catch { /* bozuk kayıt → varsayılana düş */ }
    return defaultMetaIndicators();
  });
  const [volumeVisible, setVolumeVisible] = useState(false);
  const [picking, setPicking] = useState(false);
  const [editTarget, setEditTarget] = useState<{ entry: RegistryEntry; editUid?: string } | null>(null);

  // Canlı Veriler & İndikatör Okumaları
  const [livePrice, setLivePrice] = useState<number | null>(null);
  const [liveBid, setLiveBid] = useState<number | null>(null);
  const [liveAsk, setLiveAsk] = useState<number | null>(null);
  const [liveSpread, setLiveSpread] = useState<number | null>(null);
  const [lastTickDir, setLastTickDir] = useState<"up" | "down" | null>(null);
  const [countdown, setCountdown] = useState<number>(0);
  const [latestRsi, setLatestRsi] = useState<number | null>(null);
  // Başlıktaki sayısal gösterge şeridi: ADX-14, CCI-14 ve Chandelier Exit (9, 3×ATR).
  const [latestAdx, setLatestAdx] = useState<number | null>(null);
  const [latestCci, setLatestCci] = useState<number | null>(null);
  const [latestChandelier, setLatestChandelier] = useState<{ stop: number; dir: 1 | -1 } | null>(null);

  // Geçmişe kaydırma durumu (Kullanıcı sola çektiğinde beliren Canlı Fiyata Dön düğmesi)
  const [isScrolledBack, setIsScrolledBack] = useState(false);

  // DOM & Grafik Referansları
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartApiRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);

  // MT5 tarzı gösterge motoru: panel/seri yerleşimi burada tutulur. Yapı
  // (hangi indikatör, hangi panel) değişince yeniden kurulur; veri tazeleme
  // yalnız `setData`/`update` ile yapılır (jank yok).
  const engineRef = useRef<Engine | null>(null);

  const lastCandleRef = useRef<CandleBar | null>(null);
  // Canlı güncellemede göstergeleri yeniden hesaplamak için mum dizisinin aynası.
  // `candles` state'ini tick başına değiştirmeyiz (ağır setData/jank olur); yalnız
  // son mum burada güncellenir, göstergelerin son noktası `series.update()` edilir.
  const candlesRef = useRef<CandleBar[]>([]);
  const timeframeRef = useRef<Timeframe>(timeframe);
  timeframeRef.current = timeframe;

  // GÖRÜNÜM KİLİDİ: fitContent() YALNIZCA sembol veya periyot değiştiğinde 1 kez çağrılır!
  // Periyodik sessiz pollinglerde fitContent() ÇAĞRILMAZ, böylece kullanıcının sola çektiği mumlar sağa yapışmaz!
  const fittedForRef = useRef<string>("");

  // Sığdırma bekleniyor mu? `fitContent()` ve panel yerleşiminin görünür aralık
  // geri yüklemesi İKİSİ DE zaman ekseni invalidation'ı kuyruklar ve aynı karede
  // işlenir. Geri yükleme sonra geldiğinde `fitContent()`in sonucunu iptal edip
  // görünümü eski (bayat) aralığa kilitliyordu — mumlar tuvalin yalnız sağ
  // kenarında tek mum olarak görünüyordu. Bu bayrak açıkken yerleşim aralığı geri
  // yüklemez, bunun yerine tekrar sığdırır. Kullanıcı grafiğe dokunduğunda
  // (tekerlek/pointer) temizlenir; böylece kullanıcının kaydırdığı görünüm
  // sonraki yerleşimlerde korunur.
  const pendingFitRef = useRef(false);

  // Motorun kurduğu panel anahtarları (pane[1..n] sırası). Grafik kutusunun
  // yüksekliği buna göre türetilir; `engineRef` bir ref olduğu için imzayı
  // state üzerinden izleriz.
  const paneKeys = useMemo(
    () => [
      ...(volumeVisible ? ["volume"] : []),
      ...indicators.filter((i) => !i.overlay).map((i) => `inst:${i.uid}`),
    ],
    [indicators, volumeVisible],
  );
  const chartBoxHeight = useMemo(
    () => desiredChartHeight(paneKeys, compact, compact ? 300 : 420),
    [paneKeys, compact],
  );

  // Pane Yüksekliklerini Güncelle
  //
  // `preserveRange: false` — çağıran taraf birazdan `fitContent()` uygulayacaksa
  // görünür aralığı geri YÜKLEME. Relayout bir sonraki animasyon karesinde
  // uygulanıyor; sekme arka plandayken/yük altındayken bu kare `fitContent()`ten
  // SONRA geliyor ve bayat aralığı geri yazıp görünümü serinin başına (bar 0)
  // kilitliyordu — mumlar tuvalin yalnız sağ kenarında görünüyordu.
  const updatePaneLayout = useCallback((preserveRange: boolean = true) => {
    if (!chartApiRef.current || !chartContainerRef.current) return;
    const chart = chartApiRef.current;
    const w = chartContainerRef.current.clientWidth;
    // Ölçülen yükseklik yerine panel sayısından TÜRETİLEN yükseklik kullanılır:
    // panel eklendikçe tuval büyür (kutunun `minHeight`'ı da aynı değer),
    // böylece paneller birbirini ezmez ve okunabilirlik korunur.
    const h = chartBoxHeight;
    if (w <= 0 || h <= 0) return;

    const panes = chart.panes();
    const engine = engineRef.current;
    if (panes.length <= 1 || !engine) {
      chart.applyOptions({ width: w, height: h });
      panes[0]?.setHeight(h - 28);
      return;
    }
    // Panel payları ORAN olarak verilir (bkz. computeHeights) ve yeni payların
    // geçerli olması için önce tuval yeniden boyutlandırılır: lightweight-charts
    // faktörleri saklar ama yükseklikleri ancak bir relayout'ta yeniden
    // hesaplar. Sıra önemli — faktör set edilmeden önce boyut değişirse
    // eski oranlara göre yerleşir.
    const shares = computeHeights(engine, compact);
    // Yükseklik değişimi lightweight-charts'ta zaman eksenini sıfırlar
    // (görünür aralık "en son N mum"a döner). Panel payları değişirken
    // kullanıcının kaydırdığı görünümü korumak için aralığı saklayıp
    // relayout sonrası geri yüklüyoruz. Bekleyen bir sığdırma varsa geri
    // yükleme onu iptal edeceği için aralık saklanmaz (aşağıda tekrar sığdırılır).
    const range = preserveRange && !pendingFitRef.current ? chart.timeScale().getVisibleLogicalRange() : null;
    chart.applyOptions({ width: w, height: h });
    panes.forEach((p, i) => p.setStretchFactor((shares[i] ?? shares[shares.length - 1]) / 100));
    // Relayout tetikle: aksi halde yeni faktörler bir sonraki resize'a kadar
    // uygulanmaz ve paneller eski (ezilmiş) yüksekliklerinde kalır.
    chart.applyOptions({ height: h - 1 });
    chart.applyOptions({ height: h });
    if (range) chart.timeScale().setVisibleLogicalRange(range);
    // Sığdırma bekliyorsa relayout'tan sonra TEKRAR sığdır: yukarıdaki boyut
    // değişiklikleri zaman eksenini sıfırlamış olabilir.
    if (pendingFitRef.current) chart.timeScale().fitContent();
  }, [compact, chartBoxHeight]);

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
          candlesRef.current = parsed;
          lastCandleRef.current = parsed[parsed.length - 1];

          if (data.current_price) {
            setLivePrice(data.current_price);
          }

          const rsiArr = calculateRSI(parsed, 14);
          if (rsiArr.length > 0) {
            setLatestRsi(Math.round(rsiArr[rsiArr.length - 1].value * 10) / 10);
          }

          // Başlık göstergeleri: aynı mum penceresinden ADX-14 / CCI-14 / Chandelier(9).
          const adxVal = calculateADXLatest(parsed, 14);
          setLatestAdx(adxVal == null ? null : Math.round(adxVal * 10) / 10);
          const cciVal = calculateCCILatest(parsed, 14);
          setLatestCci(cciVal == null ? null : Math.round(cciVal * 10) / 10);
          setLatestChandelier(calculateChandelierLatest(parsed, 9, 3));
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
    candlesRef.current = [];
    lastCandleRef.current = null;
    loadKlines(timeframe);
  }, [timeframe, loadKlines]);

  // 4'lü ekrandaki slot periyot butonları `initialTimeframe` prop'unu günceller;
  // bileşen bunu yalnız useState başlangıcında okuyordu → dıştaki butonlar grafiği
  // değiştirmiyordu ("çift periyot kontrolü tutarsız" hissi). Prop değişince senkronla.
  useEffect(() => {
    setTimeframe(initialTimeframe);
  }, [initialTimeframe]);

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
        const remain = nextCandleSec - nowSec;
        // Son mum BAYAT ise (Yahoo gecikmesi/piyasa arası) kalan süre negatife
        // düşüp sayaç 00:00'da kilitleniyordu. Böyle durumda duvar saatine göre
        // bir sonraki mum sınırına geri say (asılı kalmasın).
        setCountdown(remain > 0 ? remain : tfSecs - (nowSec % tfSecs));
      } else {
        setCountdown(tfSecs - (nowSec % tfSecs));
      }
    };
    tick();
    const interval = setInterval(tick, 1000);
    return () => clearInterval(interval);
  }, [timeframe, candles]);

  // CANLI GÖSTERGE SENKRONU (2026-10-07, kullanıcı isteği): canlı tick geldiğinde
  // yalnız mum güncellenirse BB/MACD/SMA son noktaları eski fiyatta kalıp "havada"
  // asılı kalıyor (bantlar mumu içine almıyordu). Bu fonksiyon canlı mumu aynaya
  // (`candlesRef`) yazıldıktan sonra göstergelerin YALNIZ son noktasını
  // `series.update()` ile tazeler — tam `setData` yapmaz, görünüm sıçramaz/jank olmaz.
  // İndikatör listesini kalıcılaştır (MetaMobil'e özel anahtar; /charts'ın
  // masaüstü listesini bozmaz). Güncelleme FONKSİYONEL yapılır: aynı tikte
  // birden çok ekle/sil çağrılırsa (örn. hızlı ardışık dokunuşlar) hepsi doğru
  // listeyi görür — düz `indicators` ile eski closure'lar güncellemeyi ezerdi.
  const persistIndicators = useCallback((updater: (prev: IndicatorInstance[]) => IndicatorInstance[]) => {
    setIndicators((prev) => {
      const next = updater(prev);
      try { localStorage.setItem("scalper_metamobil_indicators", JSON.stringify(next)); } catch { /* özel mod */ }
      return next;
    });
  }, []);

  const addIndicator = useCallback((entry: RegistryEntry, params: Record<string, any>, style: IndicatorStyle) => {
    const inst: IndicatorInstance = {
      uid: newUid(),
      registryId: entry.id,
      name: entry.shortName,
      overlay: entry.overlay,
      params,
      style,
    };
    persistIndicators((prev) => [...prev, inst]);
    setEditTarget(null);
  }, [persistIndicators]);

  const updateIndicator = useCallback((uid: string, params: Record<string, any>, style: IndicatorStyle) => {
    persistIndicators((prev) => prev.map((i) => (i.uid === uid ? { ...i, params, style } : i)));
    setEditTarget(null);
  }, [persistIndicators]);

  const removeIndicator = useCallback((uid: string) => {
    persistIndicators((prev) => prev.filter((i) => i.uid !== uid));
  }, [persistIndicators]);

  // Lejant: her ekli indikatörün son değeri. SAYAÇ SANİYEDE BİR render
  // tetiklediği için bu değerler her render'da DEĞİL, yalnız veri/gösterge
  // değişince `state`'e yazılır (aksi halde 450 indikatörlük registry her
  // saniye yeniden hesaplanırdı).
  const [liveValues, setLiveValues] = useState<{ uid: string; value: number; color?: string }[]>([]);

  const recomputeLiveValues = useCallback((bars: CandleBar[]) => {
    if (!bars.length) { setLiveValues([]); return; }
    const out: { uid: string; value: number; color?: string }[] = [];
    for (const inst of indicators) {
      const entry = findIndicatorEntry(inst.registryId);
      if (!entry) continue;
      try {
        const res = entry.calculate(bars, inst.params);
        const first = Object.values(res?.plots ?? {})[0] as any[] | undefined;
        if (!Array.isArray(first)) continue;
        for (let i = first.length - 1; i >= 0; i--) {
          const v = first[i]?.value;
          if (typeof v === "number" && Number.isFinite(v)) {
            out.push({ uid: inst.uid, value: v, color: first[i]?.color });
            break;
          }
        }
      } catch { /* bu indikatörü atla */ }
    }
    setLiveValues(out);
  }, [indicators]);

  // CANLI GÖSTERGE SENKRONU (2026-10-07, kullanıcı isteği): canlı tick geldiğinde
  // yalnız mum güncellenirse BB/MACD/SMA son noktaları eski fiyatta kalıp "havada"
  // asılı kalıyor (bantlar mumu içine almıyordu). Bu fonksiyon canlı mumu aynaya
  // (`candlesRef`) yazıldıktan sonra göstergelerin YALNIZ son noktasını
  // `series.update()` ile tazeler — tam `setData` yapmaz, görünüm sıçramaz/jank olmaz.
  const syncLiveIndicators = useCallback(() => {
    const engine = engineRef.current;
    if (!engine || !candlesRef.current.length) return;
    updateLastPoints(engine, candlesRef.current);
    // Lejant sayıları: motorla aynı mum aynasından, yalnız ekli indikatörler için.
    recomputeLiveValues(candlesRef.current);
  }, [recomputeLiveValues]);

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
                // BAZ FARKI KAPISI (2026-10-07): canlı fiyat (MT5 spot) ile mum
                // serisi (Yahoo vadeli GC=F) arasında baz farkı varsa, canlı fiyatı
                // son mumun close'una yazmak tek barda ~26$'lik SAHTE çöküş çubuğu
                // üretiyordu. Uçuk farkta mumu güncelleme; backend bir sonraki kline
                // turunda tüm seriyi spota kaydırarak hizalar (bkz. _fetch_forex_klines).
                const ref = Number(last.close);
                const rel = ref > 0 ? Math.abs(px - ref) / ref : 0;
                if (rel <= 0.0015) {
                  const updatedBar: CandleBar = {
                    time: last.time,
                    open: last.open,
                    high: Math.max(last.high, px),
                    low: Math.min(last.low, px),
                    close: px,
                  };
                  lastCandleRef.current = updatedBar;
                  // Aynadaki son mumu da güncelle → göstergeler bu mumla senkron hesaplanır.
                  const arr = candlesRef.current;
                  if (arr.length > 0 && arr[arr.length - 1].time === updatedBar.time) {
                    arr[arr.length - 1] = updatedBar;
                  }
                  try {
                    candleSeriesRef.current.update(updatedBar as any);
                    syncLiveIndicators();
                  } catch {}
                }
              }
            }
          }
        }
      } catch {}
    };
    const t = setInterval(fetchTicker, 2500);
    return () => clearInterval(t);
  }, [symbol, livePrice, syncLiveIndicators]);

  // Grafik Tuvalini Başlat (lightweight-charts)
  useEffect(() => {
    if (!chartContainerRef.current) return;

    const precision = getSymbolPrecision(symbol);
    const minMove = Math.pow(10, -precision);

    const chart = createChart(chartContainerRef.current, {
      width: chartContainerRef.current.clientWidth,
      height: chartContainerRef.current.clientHeight || chartBoxHeight,
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
        // Marjlar geniş: sert hareket/volatilite sıçramasında mumlar üst/alt
        // kenara yapışıp "kesilmiş" görünmesin (2026-10-07).
        scaleMargins: { top: 0.15, bottom: 0.15 },
      },
    });

    chartApiRef.current = chart;
    (window as any).__fxc = chart;

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

    // NOT: BB / SMA / MACD / SuperTrend ve kullanıcının eklediği TÜM indikatörler
    // artık `applyStructure` (forexIndicatorEngine) tarafından kurulur. Burada
    // yalnızca mum serisi sabittir; paneller dinamiktir.

    // Kullanıcı sola kaydırdığında "Canlı Fiyat" düğmesini göster
    //
    // NOT: burada `pendingFitRef` TEMİZLENMEZ. `fitContent()` de bu aboneliği
    // tetiklediği için temizlemek, sığdırmanın kendi ürettiği olayla bayrağı
    // düşürüp bir sonraki yerleşimin bayat aralığı geri yüklemesine yol açıyordu.
    // Kullanıcı niyeti yalnız gerçek girdi olaylarından (tekerlek/pointer) okunur.
    chart.timeScale().subscribeVisibleLogicalRangeChange((range) => {
      if (!range) return;
      const count = lastCandleRef.current ? 100 : 0;
      if (range.to != null && count > 0) {
        setIsScrolledBack(range.to < count - 3);
      }
    });

    // Kullanıcı grafiğe dokunduğunda (tekerlek/sürükleme) bekleyen sığdırmayı
    // düşür; yalnız programatik yerleşim sığdırmayı sürdürsün.
    const dropPendingFit = () => { pendingFitRef.current = false; };
    const container = chartContainerRef.current;
    container.addEventListener("wheel", dropPendingFit, { passive: true });
    container.addEventListener("pointerdown", dropPendingFit);

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
      container.removeEventListener("wheel", dropPendingFit);
      container.removeEventListener("pointerdown", dropPendingFit);
      chart.remove();
      chartApiRef.current = null;
      candleSeriesRef.current = null;
      // Grafik yok edildi: motor serileri artık geçersiz → sıfırla ki bir
      // sonraki veri turu yapıyı yeniden kursun.
      engineRef.current = null;
    };
  }, [symbol, updatePaneLayout]);

  // Pane yükseklikleri YALNIZCA panel yapısı değişince dağıtılır. Bunu veri
  // güncellemesine (2.5 sn'lik canlı tur) de bağlamak, her turda `setHeight`
  // çağırıp lightweight-charts'ın pane'leri yeniden normalize etmesine yol
  // açıyordu — MACD paneli okunamayacak kadar eziliyordu.
  useEffect(() => {
    updatePaneLayout();
  }, [indicators, volumeVisible, updatePaneLayout]);

  // Mum Verilerini ve Göstergeleri Grafiğe Bas
  useEffect(() => {
    if (!candleSeriesRef.current || candles.length === 0) return;

    try {
      candleSeriesRef.current.setData(candles as any);
    } catch (e) {
      console.warn("Mum verisi basılırken uyarı:", e);
    }

    // --- GÖSTERGE MOTORU ---
    // Yapı imzası: hangi indikatörler + sembol + periyot + pencere modu. Yalnız
    // imza değişince panelleri/serileri yeniden kurarız; aksi halde mevcut
    // serilere `setData` uygularız (periyodik tazelemede jank olmaz).
    const chart = chartApiRef.current;
    if (!chart) return;
    const engine = engineRef.current;
    const signature = structureSignature(indicators, symbol, timeframe, volumeVisible);
    const structureChanged = !engine || engine.signature !== signature;

    // GÖRÜNÜM KİLİDİ: sembol/periyot değişince VEYA panel yapısı değişince
    // (indikatör ekle/sil) sığdır — panel eklemek x-aralığını kaydırıp mumları
    // sağa kaçırabiliyor. Sessiz arka plan güncellemelerinde çalışmaz, böylece
    // kullanıcının sola çektiği görünüm korunur.
    const viewKey = `${symbol}|${timeframe}`;
    const willFit = fittedForRef.current !== viewKey || structureChanged;

    if (structureChanged) {
      engineRef.current = applyStructure(chart, candles, indicators, {
        symbol,
        timeframe,
        volumeVisible,
        signature,
        // Önceki motorun serileri içeride tek tek `removeSeries` ile atılır;
        // yalnız `removePane` çağırmak pane 0'daki overlay çizgilerini bırakır.
        previous: engine,
      });
    } else {
      applySeries(engine, candles, { volumeVisible });
    }

    // Sığdırılacaksa panel yerleşimi görünür aralığı GERİ YÜKLEMEZ: ikisi de
    // aynı animasyon karesinde işlenir ve bayat aralığın geri yazılması
    // `fitContent()`in sonucunu ezip görünümü serinin başına kilitlerdi.
    if (willFit) pendingFitRef.current = true;
    updatePaneLayout(!willFit);

    if (willFit) {
      fittedForRef.current = viewKey;
      chart.timeScale().fitContent();
      setIsScrolledBack(false);
    }

    // Header lejant sayıları (yalnız gösterge ekliyse)
    recomputeLiveValues(candles);
  }, [candles, indicators, volumeVisible, symbol, timeframe, updatePaneLayout, recomputeLiveValues]);

  return (
    // `min-h-full` (h-full DEĞİL): kök, kaydırılabilir üst öğenin içinde
    // panel sayısına göre büyüyebilmeli. `h-full` içeriği üst öğenin yüksekliğine
    // kilitler ve büyüyen grafik altındaki panelleri tekrar kırpardı.
    <div className={`flex flex-col min-h-full w-full bg-bunker-950 font-mono select-none ${className}`}>
      {/* ÜST BİLGİ & KONTROL ÇUBUĞU (kompakt modda gizli: sayfa kendi başlığını çizer) */}
      {!compact && (
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
      )}

      {/* PERİYOT & GÖSTERGE SEÇİCİ */}
      <div className="px-3 py-1.5 bg-bunker-950/90 border-b border-bunker-800/80 flex flex-wrap items-center justify-between gap-2 text-xs shrink-0">
        <div className="flex items-center gap-1">
          {/* Kompakt modda periyot seçici gizli: MetaMobil araç çubuğunda zaten var. */}
          {!compact && <span className="text-[10px] text-bunker-muted mr-1">Periyot:</span>}
          {!compact && (["1m", "5m", "15m", "30m", "1h", "4h", "1d"] as Timeframe[]).map((tf) => (
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

        {/* MT5 mobil tarzı gösterge çubuğu: ekli indikatörler çip, ＋ ile ekle */}
        <div className="flex items-center gap-1.5 overflow-x-auto flex-1 min-w-0">
          {indicators.map((inst) => (
            <button
              key={inst.uid}
              type="button"
              onClick={() => {
                const entry = findIndicatorEntry(inst.registryId);
                if (entry) setEditTarget({ entry, editUid: inst.uid });
              }}
              className={`group shrink-0 px-2 py-0.5 rounded text-[11px] font-bold border transition-all whitespace-nowrap ${
                inst.overlay
                  ? "bg-cyan-500/15 text-cyan-300 border-cyan-400/40"
                  : "bg-emerald-500/15 text-emerald-300 border-emerald-400/40"
              }`}
              title={`${inst.name} — ayarlar için dokun`}
            >
              {inst.name}
              <span
                role="button"
                aria-label={`${inst.name} göstergesini kaldır`}
                tabIndex={-1}
                onClick={(e) => { e.stopPropagation(); removeIndicator(inst.uid); }}
                className="ml-1.5 text-bunker-muted hover:text-rose-400 cursor-pointer"
              >
                ✕
              </span>
            </button>
          ))}
          <button
            type="button"
            onClick={() => setPicking(true)}
            className="shrink-0 px-2.5 py-0.5 rounded text-[11px] font-bold border border-emerald-400/50 bg-emerald-500/15 text-emerald-300 hover:bg-emerald-500/25 transition-all whitespace-nowrap"
            title="MT5 tarzı indikatör ekle (arama + kategori + ayarlar)"
          >
            ＋ İndikatör
          </button>
          <button
            type="button"
            onClick={() => setVolumeVisible((v) => !v)}
            className={`shrink-0 px-2 py-0.5 rounded text-[11px] font-bold border transition-all whitespace-nowrap ${
              volumeVisible
                ? "bg-amber-500/20 text-amber-300 border-amber-400/50"
                : "bg-bunker-900 text-bunker-muted border-bunker-800 opacity-60"
            }`}
            title="Hacim paneli"
          >
            Hacim
          </button>
        </div>

        <div className="flex items-center gap-3 text-xs flex-wrap">
          {/* Sayısal gösterge şeridi: aynı mum penceresinden hesaplanan son değerler */}
          <div className="flex items-center gap-2.5 tabular-nums flex-wrap">
            {latestRsi !== null && (
              <span className="text-bunker-muted" title="RSI (14)">
                RSI: <strong className={latestRsi > 70 ? "text-rose-400" : latestRsi < 30 ? "text-emerald-400" : "text-white"}>{latestRsi}</strong>
              </span>
            )}
            {latestAdx !== null && (
              <span
                className="text-bunker-muted"
                title="ADX (14) — trend gücü (≥25 güçlü trend)"
              >
                ADX(14):{" "}
                <strong className={latestAdx >= 25 ? "text-emerald-400" : latestAdx >= 20 ? "text-yellow-400" : "text-bunker-muted"}>
                  {latestAdx}
                </strong>
              </span>
            )}
            {latestChandelier !== null && (
              <span
                className="text-bunker-muted"
                title="Chandelier Exit (9, 3×ATR) — ATR tabanlı iz süren stop seviyesi"
              >
                Chand(9):{" "}
                <strong className={latestChandelier.dir === 1 ? "text-emerald-400" : "text-rose-400"}>
                  {formatPriceBySymbol(latestChandelier.stop, symbol)}{" "}
                  <span className="text-[10px]">{latestChandelier.dir === 1 ? "▲" : "▼"}</span>
                </strong>
              </span>
            )}
            {latestCci !== null && (
              <span
                className="text-bunker-muted"
                title="CCI (14) — ±100 dışı aşırı bölge"
              >
                CCI(14):{" "}
                <strong className={latestCci > 100 ? "text-rose-400" : latestCci < -100 ? "text-emerald-400" : "text-white"}>
                  {latestCci}
                </strong>
              </span>
            )}
          </div>
          <div className="flex items-center gap-1.5 bg-bunker-900 px-2 py-0.5 rounded border border-bunker-800">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-ping" />
            <span className="text-[10px] text-bunker-muted">Kapanış:</span>
            <span className="font-bold text-white tabular-nums">
              {formatCountdown(countdown)}
            </span>
          </div>
        </div>
      </div>

      {/* İNDİKATÖR CANLI LEJANTI — ekli indikatörlerin son değerleri */}
      <div className="px-3 py-1 bg-bunker-950/95 border-b border-bunker-900 text-[11px] flex flex-wrap items-center gap-x-4 gap-y-0.5 text-bunker-muted shrink-0">
        {indicators.map((inst) => {
          const live = liveValues.find((v) => v.uid === inst.uid);
          if (!live) return null;
          const isPane = !inst.overlay;
          const color = live.color || inst.style.colors[0];
          return (
            <span key={inst.uid} className="flex items-center gap-1.5">
              <span className="w-2.5 h-0.5 rounded" style={{ backgroundColor: color }} />
              <span style={{ color }}>{inst.name}:</span>
              <strong className="text-white font-bold tabular-nums">
                {isPane && inst.registryId === "macd"
                  ? (live.value >= 0 ? `+${live.value.toFixed(5)}` : live.value.toFixed(5))
                  : live.value.toFixed(4)}
              </strong>
            </span>
          );
        })}
        {indicators.length === 0 && (
          <span className="text-bunker-muted italic">＋ İndikatör ile gösterge ekleyin</span>
        )}
      </div>

      {/* GRAFİK TUVALİ — yükseklik açık panel sayısına göre büyür (aşağıdaki
          `chartBoxHeight`); sabit bir kutuya sıkıştırıldığında paneller
          okunamayacak kadar eziliyordu. Büyüyen tuval kaydırılabilir bir
          üst öğe içinde durur. */}
      <div
        className="relative flex-1 w-full bg-bunker-950 overflow-hidden"
        style={{ minHeight: chartBoxHeight }}
      >
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

      {/* MT5 TARZI İNDİKATÖR AKIŞI: picker → ayarlar → ekle/güncelle */}
      {picking && (
        <IndicatorPicker
          onSelect={(entry) => { setPicking(false); setEditTarget({ entry }); }}
          onClose={() => setPicking(false)}
        />
      )}
      {editTarget && (
        <IndicatorSettings
          entry={editTarget.entry}
          initialParams={editTarget.editUid ? indicators.find((i) => i.uid === editTarget.editUid)?.params : undefined}
          initialStyle={editTarget.editUid ? indicators.find((i) => i.uid === editTarget.editUid)?.style : undefined}
          editing={!!editTarget.editUid}
          onAdd={(params, style) =>
            editTarget.editUid
              ? updateIndicator(editTarget.editUid, params, style)
              : addIndicator(editTarget.entry, params, style)
          }
          onClose={() => setEditTarget(null)}
        />
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
