// Sayfa bazlı kopyalanan biçimlendirme kurallarının TEK kaynağı.
//
// H-04/H-15/H-16: fiyat biçimi 5 ayrı dosyada kopyalanmıştı (`chartShared`,
// `macd-monitor`, `monitoring`, `RadarAlertModal`, `binance-tr`) ve aynı fiyat
// sayfaya göre `1,5` / `1,5000` / `4250000.00` gibi farklı basılıyordu.
// Artık tüm bileşenler bu modülü kullanır; `app/charts/chartShared.ts` yalnızca
// buradan yeniden dışa aktarır (grafik ekseni de aynı `pricePrecision`'ı alır).
//
// TL biçimi tek (H-15): `₺` ÖNEK, her zaman 2 ondalık, tr-TR gruplama.
//
// Veri yoksa her fonksiyon "—" döner (0 DEĞİL). 0 meşru bir değerdir ama
// "veri yok" değildir; null'u 0'a çevirip yeşile boyamak yasaktır (H-02/H-05).

/**
 * Zaman damgasını milisaniyeye normalize eder. Backend karışık birim
 * gönderir (epoch saniye veya ms); eski `ts < 10_000_000_000 ? ts * 1000 : ts`
 * sezgiseli 8 sayfada kopyalanmıştı — artık burada tek yerde (H-24).
 */
export function toMs(ts: number | string | null | undefined): number {
  const value = Number(ts || 0);
  if (!Number.isFinite(value) || value <= 0) return 0;
  return value < 10_000_000_000 ? value * 1000 : value;
}

/**
 * Herhangi bir zaman damgasını veya tarih dizesini UTC+3 (Türkiye Saati) olarak biçimlendirir.
 */
export function formatUtc3(timeInput: number | string | null | undefined): string {
  if (!timeInput) return "—";
  const str = String(timeInput).trim();
  if (!str || str === "-") return "—";

  if (str.includes("UTC+3")) return str;

  // "HH:MM:SS UTC" biçimi
  if (/^\d{2}:\d{2}:\d{2}\s*UTC$/i.test(str)) {
    const parts = str.replace(/\s*UTC/i, "").split(":").map(Number);
    if (parts.length === 3) {
      const h = String((parts[0] + 3) % 24).padStart(2, "0");
      const m = String(parts[1]).padStart(2, "0");
      const s = String(parts[2]).padStart(2, "0");
      return `${h}:${m}:${s} UTC+3`;
    }
  }

  // "YYYY-MM-DD HH:MM:SS UTC" biçimi
  if (str.includes("UTC")) {
    const clean = str.replace(/\s*UTC/i, "").trim();
    if (clean.includes(" ") || clean.includes("-")) {
      const d = new Date(clean.replace(" ", "T") + "Z");
      if (!isNaN(d.getTime())) {
        const d3 = new Date(d.getTime() + 3 * 3600 * 1000);
        const y = d3.getUTCFullYear();
        const m = String(d3.getUTCMonth() + 1).padStart(2, "0");
        const day = String(d3.getUTCDate()).padStart(2, "0");
        const h = String(d3.getUTCHours()).padStart(2, "0");
        const min = String(d3.getUTCMinutes()).padStart(2, "0");
        const s = String(d3.getUTCSeconds()).padStart(2, "0");
        return `${y}-${m}-${day} ${h}:${min}:${s} UTC+3`;
      }
    }
  }

  // Sayısal timestamp (ms veya epoch saniye)
  const n = Number(timeInput);
  if (!isNaN(n) && n > 0) {
    const d = new Date(toMs(n));
    if (!isNaN(d.getTime())) {
      const dateStr = d.toLocaleDateString("tr-TR", { timeZone: "Europe/Istanbul", year: "numeric", month: "2-digit", day: "2-digit" });
      const timeStr = d.toLocaleTimeString("tr-TR", { timeZone: "Europe/Istanbul", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
      return `${dateStr} ${timeStr} UTC+3`;
    }
  }

  return str;
}

/** tr-TR kısa tarih + saat (tarayıcı yerel dilimi). */
export function fmtDateTime(ts: number | string | null | undefined): string {
  const ms = toMs(ts);
  if (!ms) return "—";
  return new Date(ms).toLocaleString("tr-TR", { dateStyle: "short", timeStyle: "short" });
}

/**
 * tr-TR GÜN/SAAT dakika çözünürlüğü: `26/09 14:35`.
 *
 * Neden ayrı bir fonksiyon: raporlar sayfası bu biçimi `toLocaleString("tr-TR",
 * { day, month, hour, minute })` ile kendi içinde yeniden yazıyordu ve
 * `dateStyle:"short"` kullanan `fmtDateTime`'dan FARKLI çıktı veriyordu (sıra
 * ve saat çözünürlüğü farklı). Aynı zaman damgası iki sayfada iki biçimde
 * basılınca hangisinin doğru olduğu belirsizleşiyordu. Artık tek kaynak burada.
 */
export function fmtMinute(ts: number | string | null | undefined): string {
  const ms = toMs(ts);
  if (!ms) return "—";
  return new Date(ms).toLocaleString("tr-TR", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/**
 * Sabit 2 ondalıklı genel sayı (`12.34`). Fiyat olmayan sayılar için
 * (adet, puan, oran tabanı). Eksik/geçersiz → "—" (0 DEĞİL).
 */
export function formatNumber2(value: number | string | null | undefined): string {
  const n = Number(value);
  if (value == null || value === "" || !Number.isFinite(n)) return "—";
  return String(Number(n.toFixed(2)));
}

/**
 * Bölünen (0.1234) girdiden yüzde: `%12.3`.
 *
 * SINIR: backend bazı uçlarda oranı YÜZDE (12.3), bazılarında ondaklık (0.123)
 * döndürür. Bu yardımcı **bölünen** sözleşmesini varsayar; yüzde gelen
 * alanlarda `formatFixed` kullan.
 */
export function formatRatioPct(value: number | string | null | undefined, digits = 1): string {
  const n = Number(value);
  if (value == null || value === "" || !Number.isFinite(n)) return "—";
  return `%${(n * 100).toFixed(digits)}`;
}

/** tr-TR yalnız tarih. */
export function fmtDate(ts: number | string | null | undefined): string {
  const ms = toMs(ts);
  if (!ms) return "—";
  return new Date(ms).toLocaleDateString("tr-TR");
}

/** tr-TR yalnız saat (saniye/ms karışık girdi güvenli). */
export function fmtClockTime(ts: number | string | null | undefined): string {
  const ms = toMs(ts);
  if (!ms) return "—";
  return new Date(ms).toLocaleTimeString("tr-TR");
}

/**
 * Paylaşılan fiyat hassasiyeti: <1 → 6 hane, <100 → 4 hane, <1000 → 3 hane,
 * aksi 2 hane. Grafik ekseni (`chartPriceFormat`) ve tüm fiyat gösterimi bu
 * kuralı kullanır; aynı fiyat farklı sayfalarda farklı yuvarlanmaz.
 *
 * `null`/`undefined` 2 haneye düşer. (Eskiden `Math.abs(Number(null))` = 0
 * olduğu için "veri yok" sessizce EN YÜKSEK kovaya (6 hane) düşüyordu:
 * eksen 0,000000 basıyordu. `formatPrice` zaten "—" döndürüyor, ama grafik
 * ekseni doğrudan bu fonksiyonu çağırıyordu.)
 */
export function pricePrecision(value: number | null | undefined): number {
  if (value == null) return 2;
  const abs = Math.abs(value);
  if (!Number.isFinite(abs)) return 2;
  if (abs < 1) return 6;
  if (abs < 100) return 4;
  if (abs < 1000) return 3;
  return 2;
}

/**
 * Fiyat biçimi (tr-TR, hassasiyet kovası `pricePrecision`).
 * Eksik/geçersiz veya ≤0 fiyat "—" döner: 0 bir fiyat değil, "veri yok"tur.
 */
export function formatPrice(value: number | null | undefined): string {
  const n = Number(value);
  if (value == null || !Number.isFinite(n) || n <= 0) return "—";
  return n.toLocaleString("tr-TR", {
    minimumFractionDigits: 0,
    maximumFractionDigits: pricePrecision(n),
  });
}

/**
 * Gösterim birimi. `NEXT_PUBLIC_QUOTE_ASSET` build-time env'den okunur:
 *   - verilmezse → `TRY` (Binance TR örneği, bugünkü davranış)
 *   - `USDT`    → Global örneği
 *
 * AYNI İMAJ İKİ QUOTE'YU TAŞIYAMAZ: Next.js `NEXT_PUBLIC_*` değerlerini
 * build sırasında sabitler, çalışma anında okumaz. Global örneği için
 * AYRI bir frontend build gerekir (bkz. docker-compose `frontend_global`).
 * Backend ise `/api/market-symbols` yanıtında `quote_asset` döndürür; bu
 * değer ikisinin aynı olduğunu doğrulamak için kullanılabilir.
 */
export const QUOTE_ASSET = (process.env.NEXT_PUBLIC_QUOTE_ASSET || "USDT").toUpperCase();

/** `TRY` → `₺`, `USDT` → `$`, `USD`/`USDC` → `$`. Yalnız GÖSTERİM. */
export const QUOTE_SYMBOL: string = (() => {
  if (QUOTE_ASSET === "TRY") return "₺";
  if (QUOTE_ASSET === "USDT") return "$";
  if (QUOTE_ASSET === "USD" || QUOTE_ASSET === "USDC") return "$";
  return QUOTE_ASSET;
})();

/**
 * GÖSTERİM para birimi adı/simgesi. Kullanıcı kuralı: Global örneğinde
 * kullanıcı isteği gereğince her yerde "$" simgesi gösterilir.
 */
export const QUOTE_ASSET_NAME: string = QUOTE_ASSET === "USDT" ? "$" : QUOTE_ASSET;

/**
 * Taban varlık + bu deployment'ın quote'sü → sembol (`"BTC"` + `USDT` =
 * `"BTCUSDT"`). Sayfaların sembol varsayılanlarını sabit `BTCTRY` yerine
 * buradan türetmeleri gerekir: `BTCUSDT` sabiti Global örneğinde bulunmayan
 * bir semboldür ve sayfa sessizce boş grafikle açılır.
 */
export function toSymbol(base: string): string {
  const value = String(base || "").toUpperCase();
  return value.endsWith(QUOTE_ASSET) ? value : `${value}${QUOTE_ASSET}`;
}

/**
 * Para birimi: önek, TAM 2 ondalık, tr-TR gruplama.
 * Küçük tutarlarda 8 ondalık basmak yok (H-15); sembol her zaman önek.
 *
 * Adı tarihsel olarak `formatTL`; çağıran kod değişmeden Global'da USDT
 * göstermesi için gösterim birimini env'e bağladık. Yeni kod `formatMoney`
 * adını tercih edebilir — `formatTL` geriye dönük uyum için korunuyor.
 */
export function formatMoney(value: number | null | undefined): string {
  const n = Number(value);
  if (value == null || !Number.isFinite(n)) return "—";
  return `${QUOTE_SYMBOL}${n.toLocaleString("tr-TR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

/** @deprecated `formatMoney` kullanın; bu ad tarihsel olarak TRY'ye özgüydü. */
export const formatTL = formatMoney;

/**
 * İşaretli tutar (K/Z): kâr `+…`, zarar `-…`, tam sıfır `0,00`, veri yok "—".
 * Sembol önek, işaret sembolün önünde → `-₺12,00` (H-15 biçim birliği).
 */
export function formatSignedMoney(value: number | null | undefined): string {
  const n = Number(value);
  if (value == null || !Number.isFinite(n)) return "—";
  const magnitude = formatMoney(Math.abs(n));
  if (n < 0) return `-${magnitude}`;
  if (n > 0) return `+${magnitude}`;
  return magnitude;
}

/** @deprecated `formatSignedMoney` kullanın. */
export const formatSignedTL = formatSignedMoney;

/**
 * Ham (biçimsiz) sayının önüne gösterim birimi koyar. `formatMoney`'den farkı
 * ondalık hassasiyetin çağıran tarafından seçilmesidir (miktar/noter alanları
 * 6 hane ister, tutarlar 2).
 *
 * DİKKAT: girdi önceden `toLocaleString("tr-TR", …)` ile biçimlendirilmiş bir
 * STRING ise `Number()` onu `NaN` yapar → "—" döner. Bu yüzden sayıyı ham
 * geçirin; biçimlendirilmiş fiyat metni istiyorsanız `withQuotePrice`.
 */
export function withQuote(value: number | string, digits = 2): string {
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  return `${QUOTE_SYMBOL}${n.toLocaleString("tr-TR", { maximumFractionDigits: digits })}`;
}

/**
 * `₺{formatPrice(x)}` kalıbının karşılığı: gösterim birimi + fiyat hassasiyeti
 * kovası. Bileşenlerdeki elle yazılmış para öneklerinin TEK karşılığı —
 * `formatPrice` ile AYNI ondalık kovasını kullanır (korelasyon bozulmaz).
 */
export function withQuotePrice(value: number | null | undefined): string {
  const formatted = formatPrice(value);
  return formatted === "—" ? formatted : `${QUOTE_SYMBOL}${formatted}`;
}

/**
 * Fiyat olmayan sabit ondalıklı sayılar (miktar/adet/miktar tutarı).
 * Fiyat için `formatPrice` kullanılmalıdır. Eksik/geçersiz → "—".
 */
export function formatFixed(value: number | string | null | undefined, digits = 2): string {
  const n = Number(value);
  if (value == null || value === "" || !Number.isFinite(n)) return "—";
  return n.toLocaleString("tr-TR", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

/** Yerel (UTC değil) YYYY-MM-DD — date input default değeri için. */
export function localDateInput(): string {
  const now = new Date();
  const offsetMs = now.getTimezoneOffset() * 60_000;
  return new Date(now.getTime() - offsetMs).toISOString().slice(0, 10);
}
