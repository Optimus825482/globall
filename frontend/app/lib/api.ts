// Browser: localhost geliştirmede backend portu, aksi halde same-origin.
// SSR/prerender: boş string (relative URL). Sabit "http://localhost:8004"
// fallback'i sunucu tarafında yanlış hedefe istek atmamak için kaldırıldı.
const browserOrigin = typeof window !== "undefined"
  ? (window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1"
    ? "http://localhost:8004"
    : window.location.origin)
  : "";
export const API_BASE = process.env.NEXT_PUBLIC_API_URL || browserOrigin;
export const WS_BASE = process.env.NEXT_PUBLIC_WS_URL || API_BASE.replace(/^http/, "ws");

export const WS_URL = `${WS_BASE.replace(/\/$/, "")}/ws`;

/**
 * H-12: tüm GET istekleri varsayılan olarak tarayıcı HTTP önbelleğini atlar.
 * Backend `Cache-Control` göndermediği için (yalnız auth ara katmanı var)
 * 51 GET çağrısının çoğu `cache: "no-store"` bayrağını taşımıyordu; bir ayar
 * kaydedildikten sonra sekmeye geri dönüldüğünde eski değer görünebiliyordu.
 * Çağıran kendi `cache` değerini verirse o değer kazanır.
 */
// PERFORMANS (2026-10-30): aynı GET isteği birden fazla bileşenden (ör. radar
// sayfası + global radar modalı, takvim bandı + takvim uyarısı) aynı anda
// atılıyordu. Uçuştaki aynı URL'ye giden GET'ler tek istekte birleşir; yanıt
// her çağırana `clone()` ile verilir. İmzalı/iptal edilebilir (signal) istekler
// ve gövdeli isteklere dokunulmaz.
const inflightGets = new Map<string, Promise<Response>>();
const INFLIGHT_LINGER_MS = 0;

export function apiRequest(input: RequestInfo | URL, init?: RequestInit) {
  const method = String(init?.method || (input instanceof Request ? input.method : "GET")).toUpperCase();
  // Audit: başarısız login POST'u auth-expired yayınlamamalı (login ekranında
  // yanlış "Oturum süresi doldu" flaşı), o yüzden URL de ayrıştırılır.
  const url = input instanceof Request ? input.url : String(input);
  const headers = new Headers(init?.headers);
  if (init?.body && typeof init.body === "string" && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const merged: RequestInit = { credentials: "include", ...init, headers };
  if ((method === "GET" || method === "HEAD") && merged.cache === undefined) {
    merged.cache = "no-store";
  }
  const dedupe = method === "GET" && !(input instanceof Request) && !merged.signal && !merged.body;
  let request: Promise<Response>;
  if (dedupe) {
    const key = url;
    let shared = inflightGets.get(key);
    if (!shared) {
      shared = fetch(input, merged);
      inflightGets.set(key, shared);
      const release = () => setTimeout(() => inflightGets.delete(key), INFLIGHT_LINGER_MS);
      shared.then(release, release);
    }
    request = shared.then((r) => r.clone());
  } else {
    request = fetch(input, merged);
  }
  return request.then((response) => {
    const isLoginPost = method === "POST" && url.includes("/auth/login");
    if (response.status === 401 && typeof window !== "undefined" && !isLoginPost) {
      window.dispatchEvent(new CustomEvent("scalper:auth-expired"));
    }
    return response;
  });
}

// Sık değişmeyen, salt-okunur uçlar için kısa ömürlü bellek önbelleği. Takvim
// ve sağlık verisi birden çok bileşende (bant, uyarı, kenar çubuğu, sayfa)
// ayrı yoklamalarla çekiliyordu. `refresh` parametreli çağrı önbelleği atlar.
const TTL_RULES: Array<[RegExp, number]> = [
  [/^\/api\/forex\/news(\?(?!.*refresh)|$)/, 15_000],
  [/^\/api\/system\/health$/, 8_000],
];
const ttlCache = new Map<string, { at: number; data: unknown }>();

export async function apiFetch(path: string, init?: RequestInit) {
  const method = String(init?.method || "GET").toUpperCase();
  const ttl = method === "GET" && !init?.signal ? TTL_RULES.find(([re]) => re.test(path))?.[1] : undefined;
  if (ttl) {
    const hit = ttlCache.get(path);
    if (hit && Date.now() - hit.at < ttl) return typeof structuredClone === "function" ? structuredClone(hit.data) : hit.data;
  }
  const response = await apiRequest(`${API_BASE}${path}`, { cache: "no-store", ...init });
  if (!response.ok) throw new Error(`API ${response.status}`);
  const data = await response.json();
  if (ttl) ttlCache.set(path, { at: Date.now(), data });
  return data;
}

/**
 * JSON döndüren endpoint'ler için merkezi yardımcı: HTTP hatalarını JSON
 * gövdesi gibi parse etmek yerine Error fırlatır. Sayfalardaki
 * `const res = await apiRequest(...); const data = await res.json()`
 * deseninin (res.ok kontrolü olmadan 4xx/5xx gövdesini veri sanan) yerine
 * kullanılır. Hata mesajında backend detayı varsa taşınır.
 */
export async function getJSON<T = unknown>(path: string, init?: RequestInit): Promise<T> {
  const response = await apiRequest(`${API_BASE}${path}`, { cache: "no-store", ...init });
  if (!response.ok) {
    let detail = "";
    try {
      const body = await response.json();
      detail = typeof body?.detail === "string" ? body.detail : "";
    } catch {
      /* gövde JSON olmayabilir */
    }
    throw new Error(detail || `API ${response.status}`);
  }
  return response.json() as Promise<T>;
}

type PageResponse<T> = Record<string, unknown> & {
  limit?: number;
  offset?: number;
};

export async function fetchAllPages<T>(
  path: string,
  key: string,
  options: { pageSize?: number; maxRows?: number } = {},
): Promise<{ rows: T[]; complete: boolean }> {
  const pageSize = options.pageSize ?? 200;
  const maxRows = options.maxRows ?? 10_000;
  const rows: T[] = [];
  const seenIds = new Set<unknown>();
  let offset = 0;
  while (rows.length < maxRows) {
    const separator = path.includes("?") ? "&" : "?";
    const data = await apiFetch(
      `${path}${separator}limit=${pageSize}&offset=${offset}`,
    ) as PageResponse<T>;
    const page = Array.isArray(data[key]) ? data[key] as T[] : [];
    for (const item of page) {
      const id = typeof item === "object" && item !== null ? (item as Record<string, unknown>).id : undefined;
      if (id !== undefined && seenIds.has(id)) continue;
      if (id !== undefined) seenIds.add(id);
      rows.push(item);
    }
    if (page.length < pageSize) return { rows, complete: true };
    offset += page.length;
  }
  return { rows, complete: false };
}
