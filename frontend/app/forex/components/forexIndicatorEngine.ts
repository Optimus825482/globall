"use client";

// MetaMobil / ForexNativeChart için MT5 tarzı indikatör motoru.
//
// Amaç: `/charts` sayfasında elle yazılmış (BB, SMA, MACD, SuperTrend ve
// kütüphanedeki 450+ hazır indikatör) render mantığını tek bir paylaşımlı
// yardımcıya taşımak. Böylece MetaMobil grafiği "yalnız 4 sabit gösterge"
// yerine picker'dan seçilen HER indikatörü, kendi paneli ve kendi çizgi
// stiliyle canlı olarak çizebilir.
//
// Tasarım kararları:
// - Çizim tipi TAHMİN EDİLMEZ: her registry kaydı `plotConfig[]` taşır ve her
//   plot kendi `style`'ını ('line' | 'histogram' | 'columns' | 'area' | ...)
//   bildirir. Eskiden "3+ plot → histogram" varsayımı yapılıyordu; bu RSI/CCI
//   gibi osilatörleri sütun grafiğine çeviriyordu. Doğru kaynak plotConfig'tir.
// - `display: "none"` işaretli plotlar (RSI'ın 70/30 bantları gibi) çizilmez;
//   seviye çizgileri `hlineConfig`'ten gelir. İkisi birden çizilirse görüntü
//   kirlenir (TradingView da yalnız hline çizer).
// - Panel kimliği olarak `IndicatorInstance.uid` kullanılır AMA "aynı uid,
//   farklı parametre/stil" durumunda seriler yeniden kurulur: her instance
//   için `signature` saklanır, değişince dispose+rebuild. Bu, kullanıcı bir
//   indikatörün ayarını değiştirdiğinde eski/stale çizgilerin görünmemesini
//   garanti eder.
// - Panel indeksleri uid ile ÖZEL eşlenir (`uid -> paneIndex`); böylece bir
//   panel kaldırıldıktan sonra kalanların indeksleri kaymaz.
// - `applyStructure` eski motoru `previous` ile alıp TÜM serilerini
//   `removeSeries` ile atar. Yalnız `removePane` çağırmak pane 0 üzerindeki
//   overlay serilerini bırakıyor ve gösterge her açılıp kapandığında üst üste
//   çizgi birikiyordu.
// - `applySeries` YALNIZCA veri yazar (`setData`), yapıya dokunmaz; yapı
//   değişince `applyStructure` çağrılır. Canlı tick'te her 2.5 sn tam rebuild
//   yapmamak için bu ayrım kritiktir (jank/tekrar oluşturma maliyeti).

import { HistogramSeries, LineSeries, LineStyle, type IChartApi, type ISeriesApi, type UTCTimestamp } from "lightweight-charts";
import { findIndicatorEntry } from "../../charts/IndicatorPicker";
import { PALETTE, uid as newUid } from "../../charts/chartShared";
import type { IndicatorInstance, IndicatorStyle, RegistryEntry } from "../../charts/types";

/** Normalize edilmiş çizim tipi — plotConfig'in `style` alanından gelir. */
type PlotKind = "line" | "histogram";

type PlotPoint = { time: UTCTimestamp; value: number; color?: string };

/** Bir instance'ın çizdiği tek seri. */
export type PlottedSeries = {
  series: ISeriesApi<"Line"> | ISeriesApi<"Histogram">;
  /** line | histogram — canlı `update()` çağrılarının doğru API'yi seçmesi için. */
  kind: PlotKind;
  /** Bu serinin hangi plot'a (`plots.plotN`) karşılık geldiği. */
  plotKey: string;
  /** Bölünmüş (renk değişimli) serilerde hangi parça; bölünmeyenlerde 0. */
  segment: number;
  /** Bu serinin kapsadığı son veri noktası. */
  lastPoint: PlotPoint | null;
};

export type InstanceSeries = {
  instance: IndicatorInstance;
  /** uid + hesaplanan signature; değişince yapı yeniden kurulur. */
  signature: string;
  /** Alt panel instance'ları için benzersiz anahtar (`inst:<uid>`); overlay için `null`. */
  paneKey: string | null;
  /** Bu instance için çizilen tüm seriler. */
  series: PlottedSeries[];
};

/** Mum serisi: `volume` opsiyonel (bazı sağlayıcılar hacim vermez). */
export type EngineBar = {
  time: UTCTimestamp;
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number;
};

export type Engine = {
  /** uid -> o instance'ın serileri (overlay ve pane aynı haritada). */
  byUid: Map<string, InstanceSeries>;
  /** panel anahtarı -> pane indeksi (volume → "volume"). */
  paneIndexByKey: Map<string, number>;
  /** Pane sırası (yükseklik hesabı için): ["volume", "inst:<uid>", ...] */
  paneKeys: string[];
  /** Yapı imzası: instance uid'leri + volume görünürlüğü. Değişince rebuild. */
  signature: string;
  /** Hacim serisi (varsa) — veri tazelemesinde `setData` için tutulur. */
  volumeSeries: ISeriesApi<"Histogram"> | null;
};

/** Stil/parametre/sembol değişimini tek bir karşılaştırılabilir imzaya indirger. */
export function instanceSignature(inst: IndicatorInstance, symbol: string, timeframe: string): string {
  return JSON.stringify({
    id: inst.registryId,
    p: inst.params,
    o: inst.overlay,
    s: inst.style,
    sym: symbol,
    tf: timeframe,
  });
}

/**
 * Yapı imzası: instance'ların sırası + çizim stili + sembol/periyot + pencere
 * modu. `Engine.signature` ile karşılaştırılarak rebuild/refresh kararı verilir.
 */
export function structureSignature(
  instances: IndicatorInstance[],
  symbol: string,
  timeframe: string,
  volumeVisible: boolean,
): string {
  return JSON.stringify({
    insts: instances.map((i) => instanceSignature(i, symbol, timeframe)),
    volume: volumeVisible,
  });
}

const styleWidth = (style: IndicatorStyle, i: number) =>
  ((style.lineWidths?.[i] ?? style.lineWidth) as 1 | 2 | 3 | 4);

const styleColor = (style: IndicatorStyle, i: number) =>
  style.colors[i] || PALETTE[i % PALETTE.length];

/**
 * `removeSeries` CAĞRISI ŞART: `removePane` yalnız pane'i siler, pane 0
 * üzerindeki overlay serileri grafikte kalır. Ayrıca pane içindeki seriler
 * de tek tek atılır; aksi halde lightweight-charts iç haritası sızar.
 */
export function disposeEngine(chart: IChartApi, engine: Engine): void {
  for (const inst of engine.byUid.values()) {
    for (const ps of inst.series) {
      try { chart.removeSeries(ps.series); } catch { /* zaten gitmiş olabilir */ }
    }
  }
  if (engine.volumeSeries) {
    try { chart.removeSeries(engine.volumeSeries); } catch { /* zaten gitmiş olabilir */ }
  }
}

/** Entry'nin plotConfig'ini `id -> style` haritasına indirger. */
function plotStyleMap(entry: RegistryEntry): Map<string, { kind: PlotKind; hidden: boolean }> {
  const map = new Map<string, { kind: PlotKind; hidden: boolean }>();
  for (const cfg of (entry as any).plotConfig ?? []) {
    if (!cfg?.id) continue;
    // Pine'da tek mumluk işaretler (circles/cross) bir çizgi gibi bağlanmamalı;
    // ama bunları LineSeries ile çizmek en yakın görsel karşılık. Sütun familyası
    // histogram olur.
    const kind: PlotKind = cfg.style === "histogram" || cfg.style === "columns" ? "histogram" : "line";
    const hidden = cfg.display === "none" || cfg.visible === false;
    map.set(cfg.id, { kind, hidden });
  }
  return map;
}

/**
 * Hesaplanan plot'ları çizilebilir veriye çevirir.
 * `colorIdx`, IndicatorSettings'in "ÇİZGİ n" sıralamasıyla aynı olacak şekilde
 * (veri içeren plotlar sayılarak) atanır; gizli plotlar da sırayı tüketir ki
 * kullanıcının seçtiği renk doğru çizgiye düşsün.
 */
function resolvePlots(
  entry: RegistryEntry,
  bars: EngineBar[],
  params: Record<string, any>,
): { key: string; kind: PlotKind; colorIdx: number; data: PlotPoint[] }[] {
  const result = safeCalculate(entry, bars, params);
  if (!result?.plots) return [];

  const styles = plotStyleMap(entry);
  const out: { key: string; kind: PlotKind; colorIdx: number; data: PlotPoint[] }[] = [];
  let colorIdx = 0;

  for (const [key, raw] of Object.entries(result.plots as Record<string, any[]>)) {
    if (!Array.isArray(raw)) continue;
    const data: PlotPoint[] = [];
    for (const p of raw) {
      if (!p || p.value == null || !Number.isFinite(p.value)) continue;
      const sec = p.time > 1e11 ? Math.floor(p.time / 1000) : Math.floor(Number(p.time));
      data.push({ time: sec as UTCTimestamp, value: Number(p.value), color: p.color });
    }
    if (!data.length) continue;

    const meta = styles.get(key) ?? { kind: "line" as PlotKind, hidden: false };
    const myIdx = colorIdx++;
    // plotConfig'te tanımlı olmayan (özel) kayıtlar gizlenmez; paket kayıtları
    // `display: "none"` ile neyi çizmeyeceğini açıkça söyler.
    if (meta.hidden) continue;
    out.push({ key, kind: meta.kind, colorIdx: myIdx, data });
  }
  return out;
}

/** Renk değişiminde çizgiyi bölerek segment bazlı renk verir (linebr/supertrend). */
function splitByColor(
  data: PlotPoint[],
  fallback: string,
): { color: string; data: { time: UTCTimestamp; value: number }[] }[] {
  const segments: { color: string; data: { time: UTCTimestamp; value: number }[] }[] = [];
  let current: { time: UTCTimestamp; value: number }[] = [];
  let color = data[0]?.color || fallback;
  for (const p of data) {
    const c = p.color || fallback;
    if (c !== color) {
      // Kopukluk noktasını her iki segmente de koy; aksi halde çizgiler
      // arasında boşluk kalır (lightweight-charts noktaları birbirine bağlar).
      if (current.length) {
        segments.push({ color, data: current });
        current = [{ time: p.time, value: p.value }];
      } else {
        current.push({ time: p.time, value: p.value });
      }
      color = c;
    } else {
      current.push({ time: p.time, value: p.value });
    }
  }
  if (current.length) segments.push({ color, data: current });
  return segments;
}

/** Bir plot'un, söz konusu segment için üretilecek seri verisini döndürür. */
function segmentData(plot: { data: PlotPoint[] }, segment: number, fallbackColor: string): PlotPoint[] {
  if (!plot.data.some((d) => d.color)) {
    // Plot kendi rengini vermiyorsa bölünme yok; segment 0 tüm veriyi alır.
    return plot.data.map(({ time, value }) => ({ time, value }));
  }
  return splitByColor(plot.data, fallbackColor)[segment]?.data ?? [];
}

/**
 * Yapıyı uygular: eski serileri temizler, volume + tüm instance'lar için
 * panelleri/serileri yeniden kurar. Veri YAZMAZ — onu `applySeries` yapar.
 * Dönen `Engine` çağıran tarafta panel yüksekliklerini hesaplamak için tutulur.
 */
export function applyStructure(
  chart: IChartApi,
  bars: EngineBar[],
  instances: IndicatorInstance[],
  opts: {
    symbol: string;
    timeframe: string;
    volumeVisible: boolean;
    signature: string;
    previous?: Engine | null;
  },
): Engine {
  // 1) Önceki yapının TÜM serilerini at (overlay'ler dahil), sonra panelleri.
  if (opts.previous) disposeEngine(chart, opts.previous);
  while (chart.panes().length > 1) chart.removePane(1);

  const engine: Engine = {
    byUid: new Map(),
    paneIndexByKey: new Map(),
    paneKeys: [],
    signature: opts.signature,
    volumeSeries: null,
  };

  let paneIdx = 1;

  // 2) Hacim paneli (opsiyonel)
  if (opts.volumeVisible) {
    const series = chart.addSeries(HistogramSeries, {
      priceLineVisible: false,
      lastValueVisible: false,
    }, paneIdx);
    series.setData(volumeData(bars) as any);
    engine.volumeSeries = series;
    engine.paneIndexByKey.set("volume", paneIdx);
    engine.paneKeys.push("volume");
    chart.priceScale("right", paneIdx).applyOptions({ scaleMargins: { top: 0.25, bottom: 0.02 } });
    paneIdx++;
  }

  // 3) Instance'lar
  for (const inst of instances) {
    const entry: RegistryEntry | undefined = findIndicatorEntry(inst.registryId);
    if (!entry) continue;

    const plots = resolvePlots(entry, bars, inst.params);
    if (!plots.length) continue;

    const arr: PlottedSeries[] = [];

    if (inst.overlay) {
      for (const plot of plots) {
        const color = styleColor(inst.style, plot.colorIdx);
        // Kendi rengini veren plotlar (supertrend linebr, RQ kernel) renk
        // değişiminde bölünür; aksi halde tek renk çizilir.
        const hasOwnColors = plot.data.some((d) => d.color);
        const segs = hasOwnColors ? splitByColor(plot.data, color) : [{ color, data: plot.data }];
        segs.forEach((seg, si) => {
          if (!seg.data.length) return;
          const s = chart.addSeries(LineSeries, {
            color: seg.color,
            lineWidth: styleWidth(inst.style, plot.colorIdx),
            priceLineVisible: !!inst.style.showPriceLine,
            lastValueVisible: !!inst.style.showPriceLine,
          }, 0);
          s.setData(seg.data as any);
          arr.push({
            series: s, kind: "line", plotKey: plot.key, segment: si,
            lastPoint: seg.data[seg.data.length - 1] ?? null,
          });
        });
      }
      engine.byUid.set(inst.uid, {
        instance: inst,
        signature: instanceSignature(inst, opts.symbol, opts.timeframe),
        paneKey: null,
        series: arr,
      });
      continue;
    }

    // Alt panel
    const key = `inst:${inst.uid}`;
    engine.paneIndexByKey.set(key, paneIdx);
    engine.paneKeys.push(key);

    for (const plot of plots) {
      const color = styleColor(inst.style, plot.colorIdx);
      if (plot.kind === "histogram") {
        const isMacd = inst.registryId === "macd";
        const data = isMacd
          ? plot.data.map((d, i) => ({ ...d, color: macdColor(d.value, plot.data[i - 1]?.value) }))
          : plot.data;
        const s = chart.addSeries(HistogramSeries, {
          color,
          base: 0,
          priceLineVisible: false,
          lastValueVisible: false,
        }, paneIdx);
        s.setData(data as any);
        arr.push({
          series: s, kind: "histogram", plotKey: plot.key, segment: 0,
          lastPoint: data[data.length - 1] ?? null,
        });
      } else {
        const s = chart.addSeries(LineSeries, {
          color,
          lineWidth: styleWidth(inst.style, plot.colorIdx),
          priceLineVisible: !!inst.style.showPriceLine,
          lastValueVisible: !!inst.style.showPriceLine,
        }, paneIdx);
        s.setData(plot.data as any);
        arr.push({
          series: s, kind: "line", plotKey: plot.key, segment: 0,
          lastPoint: plot.data[plot.data.length - 1] ?? null,
        });
      }
    }

    chart.priceScale("right", paneIdx).applyOptions({ autoScale: true, scaleMargins: { top: 0.12, bottom: 0.12 } });
    addReferenceLines(chart, paneIdx, entry, arr);

    engine.byUid.set(inst.uid, {
      instance: inst,
      signature: instanceSignature(inst, opts.symbol, opts.timeframe),
      paneKey: key,
      series: arr,
    });
    paneIdx++;
  }

  return engine;
}

/**
 * Seviye çizgileri: plotConfig'te `display: "none"` ile gizlenen plotların
 * (RSI 70/30 gibi) yerine `hlineConfig` çizilir. Plotlar gizli olduğu için
 * çift çizim olmaz — MT5/TradingView görünümü budur.
 */
function addReferenceLines(chart: IChartApi, paneIdx: number, entry: RegistryEntry, plotted: PlottedSeries[]) {
  const hlines = (entry as any).hlineConfig as any[] | undefined;
  if (!hlines?.length || !plotted.length) return;
  const anchor = plotted[0].series;
  for (const hl of hlines) {
    if (typeof hl?.price !== "number" || !Number.isFinite(hl.price)) continue;
    try {
      anchor.createPriceLine({
        price: hl.price,
        color: hl.color || "rgba(148,163,184,0.55)",
        lineWidth: 1,
        lineStyle: hl.linestyle === "dashed" ? LineStyle.Dashed
          : hl.linestyle === "dotted" ? LineStyle.Dotted
            : LineStyle.Solid,
        axisLabelVisible: true,
        title: hl.title ?? "",
      });
    } catch { /* bazı seriler price line desteklemez */ }
  }
}

/**
 * Veri tazeleme (yapı DEĞİŞMEZ): mevcut serilere `setData` uygular. Canlı
 * tick'te yalnız son nokta `update()` edilir — bu fonksiyon periyodik sessiz
 * yenilemede kullanılır.
 */
export function applySeries(
  engine: Engine,
  bars: EngineBar[],
  opts: { volumeVisible: boolean },
): void {
  if (engine.volumeSeries && opts.volumeVisible) {
    try { engine.volumeSeries.setData(volumeData(bars) as any); } catch { /* sonraki tur düzeltir */ }
  }
  for (const inst of engine.byUid.values()) {
    const entry = findIndicatorEntry(inst.instance.registryId);
    if (!entry) continue;
    const plots = resolvePlots(entry, bars, inst.instance.params);
    const byKey = new Map(plots.map((p) => [p.key, p]));

    for (const ps of inst.series) {
      const plot = byKey.get(ps.plotKey);
      const isMacd = inst.instance.registryId === "macd" && ps.kind === "histogram";
      let data: PlotPoint[];
      if (isMacd && plot) {
        data = plot.data.map((d, i) => ({ ...d, color: macdColor(d.value, plot.data[i - 1]?.value) }));
      } else {
        const color = styleColor(inst.instance.style, plot?.colorIdx ?? 0);
        data = plot ? segmentData(plot, ps.segment, color) : [];
      }
      if (!data.length) continue;
      try { ps.series.setData(data as any); } catch { /* bozuk veri sonraki turda düzelir */ }
      ps.lastPoint = data[data.length - 1] ?? null;
    }
  }
}

/** Canlı tick: yalnız son noktayı `update()` eder (görünüm sıçramaz). */
export function updateLastPoints(engine: Engine, bars: EngineBar[]): void {
  for (const inst of engine.byUid.values()) {
    const entry = findIndicatorEntry(inst.instance.registryId);
    if (!entry) continue;
    const plots = resolvePlots(entry, bars, inst.instance.params);
    const byKey = new Map(plots.map((p) => [p.key, p]));

    for (const ps of inst.series) {
      const plot = byKey.get(ps.plotKey);
      if (!plot || !plot.data.length) continue;
      const isMacd = inst.instance.registryId === "macd" && ps.kind === "histogram";
      const last = plot.data[plot.data.length - 1];
      const point = isMacd
        ? { ...last, color: macdColor(last.value, plot.data[plot.data.length - 2]?.value) }
        : { time: last.time, value: last.value };
      try {
        ps.series.update(point as any);
        ps.lastPoint = point;
      } catch { /* sonraki HTTP turu düzeltir */ }
    }
  }
}

function volumeData(bars: EngineBar[]) {
  return bars.map((b) => ({
    time: b.time,
    value: b.volume ?? 0,
    color: b.close >= b.open ? "rgba(16,185,129,0.45)" : "rgba(239,68,68,0.45)",
  }));
}

function safeCalculate(entry: RegistryEntry, bars: any[], params: any) {
  try {
    return entry.calculate(bars, params);
  } catch {
    // Eksik/uyumsuz parametre tek indikatörün tüm grafiği bozmasını engeller.
    return null;
  }
}

function macdColor(value: number, previous?: number): string {
  const rising = previous == null || value >= previous;
  if (value >= 0) return rising ? "rgba(52, 211, 153, 0.94)" : "rgba(5, 150, 105, 0.84)";
  return rising ? "rgba(248, 113, 113, 0.84)" : "rgba(239, 68, 68, 0.94)";
}

/** Varsayılan MetaMobil göstergeleri: BB (overlay) + MACD (pane). */
export function defaultMetaIndicators(): IndicatorInstance[] {
  return [
    {
      uid: newUid(),
      registryId: "bb",
      name: "BB",
      overlay: true,
      params: { length: 20, maType: "SMA", src: "close", mult: 2, offset: 0 },
      style: { colors: ["#38bdf8", "#f59e0b", "#38bdf8"], lineWidth: 1, showPriceLine: false, showBounds: true },
    },
    {
      uid: newUid(),
      registryId: "macd",
      name: "MACD",
      overlay: false,
      params: { fastLength: 12, slowLength: 26, signalLength: 9, src: "close" },
      style: { colors: ["#10b981", "#38bdf8", "#f59e0b"], lineWidth: 2, showPriceLine: false, showBounds: true },
    },
  ];
}

/**
 * Açık panellere göre grafiğin İHTİYAÇ duyduğu toplam yükseklik.
 *
 * Sabit bir pencereye sıkıştırmak yerine tuval büyür ve sekme kaydırılır;
 * `/charts` sayfası da böyle yapıyor. Aksi halde 386px'lik bir alana 3 panel
 * sığdırılmaya çalışılıyor ve her panel okunamayacak kadar eziliyordu.
 */
export function desiredChartHeight(paneKeys: string[], compact: boolean, minHeight: number): number {
  const axis = 28;
  const mainWant = compact ? 240 : 320;
  const paneWant = (k: string) => (k === "volume" ? (compact ? 72 : 96) : (compact ? 130 : 160));
  const panes = paneKeys.reduce((a, k) => a + paneWant(k), 0);
  return Math.max(minHeight, mainWant + panes + axis);
}

/**
 * Panellerin İSTENEN paylarını döndürür: `[ana, ...pane]`, piksel değil ORAN.
 *
 * Neden oran: lightweight-charts `setHeight` çağrılarını ardışık pane'ler
 * arasında yeniden normalize ediyor (280/110/110 istenip 377/26/95
 * uygulanıyordu — MACD paneli okunamaz hale geliyordu), `setStretchFactor`
 * ise oranı olduğu gibi koruyor. Grafik tuvali `desiredChartHeight` ile bu
 * payların toplamına (+ zaman ekseni) büyütüldüğü için oranlar birebir
 * piksele denk gelir ve hiçbir panel ezilmez.
 */
export function computeHeights(engine: Engine, compact: boolean): number[] {
  const keys = engine.paneKeys;
  const main = compact ? 240 : 320;
  if (!keys.length) return [main];
  const pane = (k: string) => (k === "volume" ? (compact ? 72 : 96) : (compact ? 130 : 160));
  return [main, ...keys.map(pane)];
}
