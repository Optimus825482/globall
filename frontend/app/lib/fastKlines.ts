/**
 * fastKlines.ts
 *
 * Binance TR ve Binance Global web/mobil uygulamalarındaki ultra hızlı
 * grafik yükleme mimarisini (Edge CDN + Direct CORS fetch) scalperagent paneline
 * kazandıran yüksek performanslı kline veri istemcisi.
 *
 * 1. Doğrudan Binance Edge CDN (/api/v3/uiKlines):
 *    - TRY çiftleri: https://api.binance.me (Binance TR CDN) -> Yedek: https://api.binance.com
 *    - USDT çiftleri: https://api.binance.com (Binance Global CDN) -> Yedek: https://api.binance.me
 *    - Açık CORS desteği (*) sayesinde istekler sunucu/Python kuyruğuna takılmadan
 *      kullanıcının tarayıcısından doğrudan ~100-250ms içinde yüklenir.
 *
 * 2. In-Memory Mikro Önbellek & Request Coalescing (Tekilleştirme):
 *    - Aynı anda giden (örn. 4'lü MTF ekrandaki) veya hızlı sekme değişimlerindeki
 *      istekler tek Promise altında birleşir.
 *
 * 3. Hızlı Zaman Aşımı & Otomatik Backend Fallback:
 *    - Doğrudan CDN 2.8 saniye içinde yanıt vermezse veya tarayıcı eklentisi (adblock vb.)
 *      engellerse otomatik olarak backend `/api/market-klines` uç noktasına düşer.
 *
 * 4. Canlı WS Tick Bildirimi:
 *    - Grafik anında çizilirken arka planda asenkron olarak backend'e hafif bir ping
 *      atılarak `ws_live_candles` canlı mum akışı (`note_viewed`) tetiklenir.
 */

import { API_BASE, apiRequest } from "./api";

export interface FastKlineBar {
  time: number; // UTC seconds
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

const _klineMemoryCache = new Map<string, { expires: number; data: FastKlineBar[] }>();
const _klineInflight = new Map<string, Promise<FastKlineBar[]>>();
const CACHE_TTL_MS = 5000; // 5 saniye mikro RAM önbellek

function parseCandles(raw: any[]): FastKlineBar[] {
  if (!Array.isArray(raw)) return [];
  const bars: FastKlineBar[] = [];
  for (let i = 0; i < raw.length; i++) {
    const c = raw[i];
    if (!c || c.length < 5) continue;
    bars.push({
      time: Math.floor(Number(c[0]) / 1000),
      open: Number(c[1]),
      high: Number(c[2]),
      low: Number(c[3]),
      close: Number(c[4]),
      volume: Number(c[5] ?? 0),
    });
  }
  return bars;
}

/**
 * Belirtilen sembol ve periyot için mumları doğrudan Binance CDN veya backend üzerinden
 * en yüksek hızda getirir.
 */
export async function fastFetchKlines(
  symbol: string,
  interval: string = "5m",
  limit: number = 200
): Promise<FastKlineBar[]> {
  if (!symbol) return [];
  const clean = symbol.replace("_", "").toUpperCase();
  const cacheKey = `${clean}:${interval}:${limit}`;
  const now = Date.now();

  // 1. In-memory mikro önbellek kontrolü
  const cached = _klineMemoryCache.get(cacheKey);
  if (cached && now < cached.expires && cached.data.length > 0) {
    return cached.data;
  }

  // 2. In-flight tekilleştirme (aynı anda giden mükerrer istekleri birleştir)
  const inflight = _klineInflight.get(cacheKey);
  if (inflight) {
    return inflight;
  }

  const promise = (async () => {
    try {
      const isTry = clean.endsWith("TRY");
      const cdnHosts = isTry
        ? ["https://api.binance.me", "https://api.binance.com"]
        : ["https://api.binance.com", "https://api.binance.me"];

      let candles: FastKlineBar[] | null = null;

      // 3. Doğrudan Binance Edge CDN (TR uygulamasıyla aynı hız)
      for (const host of cdnHosts) {
        try {
          const controller = new AbortController();
          const timeoutId = setTimeout(() => controller.abort(), 2600);
          const url = `${host}/api/v3/uiKlines?symbol=${clean}&interval=${interval}&limit=${limit}`;
          const res = await fetch(url, {
            signal: controller.signal,
            headers: { Accept: "application/json" },
          });
          clearTimeout(timeoutId);
          if (res.ok) {
            const raw = await res.json();
            if (Array.isArray(raw) && raw.length > 0) {
              candles = parseCandles(raw);
              break;
            }
          }
        } catch {
          // CDN denemesi başarısız olursa sonraki CDN'e veya backend fallback'e geç
        }
      }

      // 4. Arka plan canlı WS tetiklemesi (non-blocking)
      if (candles && candles.length > 0) {
        // Backend'deki ws_live_candles note_viewed abonesini tazelemek için hafif arka plan isteği
        apiRequest(`${API_BASE}/api/market-klines/${clean}?interval=${interval}&limit=20`).catch(() => {});
      } else {
        // 5. Fallback: Yerel backend üzerinden güvenli çekim
        const res = await apiRequest(`${API_BASE}/api/market-klines/${clean}?interval=${interval}&limit=${limit}`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const payload = await res.json();
        const raw = payload.candles || [];
        candles = parseCandles(raw);
      }

      if (candles && candles.length > 0) {
        _klineMemoryCache.set(cacheKey, { expires: Date.now() + CACHE_TTL_MS, data: candles });
      }
      return candles || [];
    } finally {
      _klineInflight.delete(cacheKey);
    }
  })();

  _klineInflight.set(cacheKey, promise);
  return promise;
}

/**
 * Kullanıcı sembol seçer seçmez veya sayfayı açar açmaz
 * arka planda 4'lü ekranın tüm TF'lerini önden indirmeye başlar.
 */
export function prefetchKlines(
  symbol: string,
  intervals: string[] = ["1m", "3m", "5m", "15m"],
  limit: number = 200
): void {
  if (!symbol) return;
  const clean = symbol.replace("_", "").toUpperCase();
  for (const tf of intervals) {
    void fastFetchKlines(clean, tf, limit);
  }
}
