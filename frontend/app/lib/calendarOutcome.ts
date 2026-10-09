// Ekonomik takvim: "hangi senaryo gerçekleşti?" kararının GÖRÜNTÜ tarafı.
//
// Yön kararı (bullish/bearish) BACKEND'de verilir (`app/forex_news.py`
// `evaluate_event_outcome`) ve olayın `outcome` alanıyla gelir — burada karar
// YENİDEN TÜRETİLMEZ, yalnız okunur. Sebep: senaryo metinleri ve gerçek `actual`
// değerleri orada; kuralı burada kopyalamak "gösterilen senaryo metni" ile
// "seçilen dal"ın zamanla ayrışmasına yol açardı.
//
// Burada kalan tek mantık ZAMAN penceresidir: açıklanan veri o takvim günü
// boyunca (Türkiye saati, UTC+3) gösterilir, gece yarısı geçince kaybolur.
// Pencere saniyelik paylaşımlı sayaçla (`nowSec`) değerlendirildiği için gün
// dönümünde YENİ FETCH BEKLEMEDEN kaybolur.
//
// Saf `.ts` modülü olması kasıtlıdır: `vitest.config.ts` React için jsdom
// kurmuyor (`environment: "node"`), bu yüzden test edilebilir mantık burada
// toplanır — `page.tsx` içinde bırakılırsa hiçbir test onu koşamaz.

/** Backend'in `outcome.side` değeri. `null` = karar verilemedi (veri yok/eşitlik). */
export type OutcomeSide = "bullish" | "bearish" | null;

/** Backend'in `outcome` sözlüğü (bkz. `forex_news.evaluate_event_outcome`). */
export interface CalendarOutcome {
  side?: OutcomeSide;
  bucket?: string | null;
  basis?: "forecast" | "previous" | null;
  actual_num?: number | null;
  baseline_num?: number | null;
  comparison_tr?: string | null;
  label_tr?: string | null;
  /**
   * Yalnız ters yorumlanan ailelerde (işsizlik/başvuru, petrol stoğu) doludur:
   * orada sayısal ilişki ile piyasa yönü ayrışır ("231K > 220K" ama 🔴) ve
   * rozet tek başına çelişkili okunur.
   */
  direction_note_tr?: string | null;
}

/** Bu modülün ihtiyaç duyduğu olay alanları (page.tsx `EconomicEvent`'in alt kümesi). */
export interface CalendarEventLike {
  forecast?: string;
  previous?: string;
  actual?: string;
  date_iso?: string;
  has_data?: boolean;
  outcome?: CalendarOutcome | null;
  /** Yalnız `selectPriorityAlertEvents` kullanır (uyarı önceliği). */
  stars?: number;
  impact?: string;
}

/** Veri yok anlamına gelen metinler (backend `_MISSING_VALUE_TOKENS` ile aynı sözleşme). */
const MISSING = new Set(["", "—", "-", "–", "n/a", "na", "null", "none", "nan", "--"]);

function isMissing(value?: string | null): boolean {
  return value == null || MISSING.has(String(value).trim().toLowerCase());
}

/**
 * `actual` gerçekten açıklanmış bir değer mi?
 *
 * `"—"`/boş "veri yok" demektir — bunu gerçek bir sonuç sanıp vitrine koymak
 * `null`'u 0'a çevirmekle aynı sınıf hatadır (bkz. `lib/format.ts` sözleşmesi).
 */
export function hasPublishedActual(actual?: string | null): boolean {
  return !isMissing(actual);
}

/**
 * Olayda gösterilecek bir veri (Beklenti veya Önceki) var mı?
 *
 * Backend `has_data` bayrağını gönderir; alan yoksa (eski önbellek) burada
 * aynı kuraldan türetilir — iki taraf ayrı düşmesin.
 */
export function hasCalendarData(ev: CalendarEventLike): boolean {
  if (typeof ev.has_data === "boolean") return ev.has_data;
  return !isMissing(ev.forecast) || !isMissing(ev.previous);
}

/** Backend'in yön kararı; karar verilemediyse `null`. */
export function outcomeSide(ev: CalendarEventLike | null | undefined): OutcomeSide {
  const side = ev?.outcome?.side;
  return side === "bullish" || side === "bearish" ? side : null;
}

/** Vitrin satırı: "3.2% > 3.0% (Beklenti Üzeri)". Backend metni yoksa `null`. */
export function comparisonText(ev: CalendarEventLike): string | null {
  const text = ev.outcome?.comparison_tr;
  return typeof text === "string" && text.trim() ? text : null;
}

/**
 * Rozet metni. Backend tabana göre üretir ("Beklenti Üzeri" / "Önceki'ye Göre Artış")
 * — canlı akışta olayların ÇOĞUNDA `forecast` boş olduğu için bu ayrım şarttır;
 * boş bir Beklenti alanına atıfla yanlış bilgi verilmesini engeller.
 */
export function labelText(ev: CalendarEventLike): string | null {
  const text = ev.outcome?.label_tr;
  return typeof text === "string" && text.trim() ? text : null;
}

/** Kıyasın hangi değere göre yapıldığı (rozet altı açıklama için). */
export function basisText(ev: CalendarEventLike): "Beklenti" | "Önceki" | null {
  if (ev.outcome?.basis === "forecast") return "Beklenti";
  if (ev.outcome?.basis === "previous") return "Önceki";
  return null;
}

/**
 * Ters yorum uyarısı — yalnız ters ailelerde doludur.
 *
 * İşsizlik/başvuru ve petrol stoğu olaylarında yüksek değer ayı yönlüdür, yani
 * "Beklenti Üzeri" rozeti ile 🔴 işareti YAN YANA doğrudur ama çelişkili görünür.
 * Bu metin o çelişkiyi açıklar; boşsa rozet basılmaz.
 */
export function directionNoteText(ev: CalendarEventLike | null | undefined): string | null {
  const text = ev?.outcome?.direction_note_tr;
  return typeof text === "string" && text.trim() ? text : null;
}

const MS_PER_DAY = 86_400_000;
/** Türkiye saati sabit dilim: UTC+3 (2016'dan beri DST yok). */
const TR_OFFSET_MS = 3 * 3_600_000;

/**
 * Açıklanma anını içeren TAKVİM GÜNÜNÜN (UTC+3) bitişini UTC ms olarak döner.
 *
 * Gün sınırı kullanıcının gördüğü saatle aynı olmalı: arayüz olay saatlerini
 * zaten "Bugün 21:00" gibi Türkiye saatiyle gösteriyor (`format_event_date`).
 * UTC tabanlı bir sınır koysaydık 23:00 TR'de açıklanan bir veri ekranda
 * gece yarısından 3 saat önce kaybolurdu.
 */
export function endOfTrDayMs(announcedAtMs: number): number {
  const shifted = announcedAtMs + TR_OFFSET_MS;
  const trDayStart = Math.floor(shifted / MS_PER_DAY) * MS_PER_DAY;
  return trDayStart + MS_PER_DAY - TR_OFFSET_MS;
}

/**
 * Bu olayın sonucu ŞU AN gösterilmeli mi?
 *
 * İki koşul: (1) açıklanma anı geçmiş olmalı, (2) içinde bulunulan an ile
 * açıklanma AYNI UTC+3 takvim gününde olmalı. Böylece kart o gün boyunca kalır,
 * ertesi gün kendiliğinden düşer.
 *
 * `date_iso` yok/ayrıştırılamıyorsa karar verilemez: veriyi GİZLEMEK yerine
 * sonucu göstermeye devam ederiz (kullanıcı gerçek bir açıklamayı kaçırmasın).
 */
export function isOutcomeVisibleNow(
  dateIso: string | undefined,
  nowMs: number,
  actual?: string | null,
): boolean {
  if (!hasPublishedActual(actual)) return false;
  if (!dateIso) return true;

  const announcedAtMs = Date.parse(dateIso);
  if (!Number.isFinite(announcedAtMs)) return true;

  return nowMs >= announcedAtMs && nowMs < endOfTrDayMs(announcedAtMs);
}

/**
 * Modalda hangi senaryo dalları gösterilsin?
 * - Sonuç görünür VE dal belirliyse: yalnız gerçekleşen dal (diğeri tamamen gizlenir).
 * - Aksi halde (henüz açıklanmadı / eşitlik / ayrıştırılamadı): iki dal da gösterilir.
 *   Karar verilemeyen durumda bilgi gizlenmez — eski davranış korunur.
 */
export function selectScenarioBranches(
  side: OutcomeSide | undefined,
  outcomeVisible: boolean,
): { showBullish: boolean; showBearish: boolean } {
  if (!outcomeVisible) return { showBullish: true, showBearish: true };
  if (side === "bullish") return { showBullish: true, showBearish: false };
  if (side === "bearish") return { showBullish: false, showBearish: true };
  return { showBullish: true, showBearish: true };
}

/**
 * Dal neden seçilemedi? Modalda hangi açıklamanın basılacağını belirler.
 *
 * İki durum AYRI mesaj gerektirir: "henüz açıklanmadı" ile "açıklandı ama eşit"
 * operatör için çok farklı şeylerdir — ikincisinde veri gelmiş ve piyasa yönsüz
 * kalmıştır. Yanlış mesaj, operatörün veriyi hiç gelmemiş sanmasına yol açar.
 *
 * `"tie"` tespiti `comparison_tr` içindeki `=` işaretinden yapılır: backend
 * eşitlikte operatörü `=` yapar (`evaluate_event_outcome`).
 */
export type BranchFallbackReason = "pending" | "tie" | "unparsed" | null;

export function branchFallbackReason(
  ev: CalendarEventLike | null | undefined,
  nowMs: number,
): BranchFallbackReason {
  if (!ev || outcomeSide(ev) !== null) return null;
  if (!isOutcomeVisibleNow(ev.date_iso, nowMs, ev.actual)) return "pending";
  // `outcome` nesnesi VAR ama `side` yok: eşitlik ya da taban yok.
  const cmp = comparisonText(ev);
  if (cmp && cmp.includes("=")) return "tie";
  return "unparsed";
}

/**
 * Vitrinde gösterilecek "bugün açıklanan veriler": veri içeren, sonucu BELİRLENMİŞ
 * ve penceresi açık olan olaylar — en son açıklanan en üstte.
 */
export function selectTodaysPublished<T extends CalendarEventLike>(
  events: readonly T[],
  nowMs: number,
): T[] {
  return events
    .filter(
      (ev) =>
        hasCalendarData(ev) &&
        outcomeSide(ev) !== null &&
        isOutcomeVisibleNow(ev.date_iso, nowMs, ev.actual),
    )
    .sort((a, b) => {
      const ta = a.date_iso ? Date.parse(a.date_iso) : 0;
      const tb = b.date_iso ? Date.parse(b.date_iso) : 0;
      return (Number.isFinite(tb) ? tb : 0) - (Number.isFinite(ta) ? ta : 0);
    });
}

/**
 * Uyarı popup'ı için "aynı dakikada açıklanan olaylardan en önemlisi"ni seçer.
 *
 * Sorun: bir olay kümesi (ör. ABD perakende satışları: manşet + "Ex Autos")
 * AYNI dakikada açıklanır. Uyarı döngüsü `item.id` ile tekilleştirme yaptığı için
 * kümedeki her olay AYRI bir popup üretir — ses üst üste çalar, modal yer
 * değiştirir. Bu davranış TradingView tek başınayken de vardı, ancak Investing
 * katmanı küme sayısını artırdı.
 *
 * ÖNEMLİ: `(para birimi, dakika)` ile naif bir tekilleştirme YANLIŞ olurdu —
 * EIA Crude vs Gasoline, Retail Sales manşet vs Ex Autos gibi GERÇEKTEN FARKLI
 * olayları da bastırırdı. Bu fonksiyon hiçbir olayı GİZLEMEZ; yalnızca hangi
 * olayın popup'ı hak ettiğine karar verir. Tablo ve vitrin etkilenmez.
 *
 * Küme anahtarı `date_iso`'nun tam zaman damgasıdır (para birimi + an). Sıralama
 * `stars` (yüksek önce), eşitlikte `impact` ("High" önce), sonra girdi sırası —
 * yani kararlıdır ve girdi mutasyona uğratılmaz.
 */
export function selectPriorityAlertEvents<T extends CalendarEventLike>(events: readonly T[]): T[] {
  const best = new Map<string, T>();
  const order: string[] = [];

  for (const ev of events) {
    if (!ev.date_iso) {
      // Küme anahtarı yoksa olay kendi başına değerlendirilir; asla düşürülmez.
      const key = `\u0000${order.length}`;
      order.push(key);
      best.set(key, ev);
      continue;
    }
    const key = String(ev.date_iso);
    const current = best.get(key);
    if (current === undefined) {
      best.set(key, ev);
      order.push(key);
      continue;
    }
    const evStars = starsOf(ev);
    const curStars = starsOf(current);
    if (evStars > curStars || (evStars === curStars && impactRank(ev) < impactRank(current))) {
      best.set(key, ev);
    }
  }

  return order.map((k) => best.get(k)).filter((ev): ev is T => ev !== undefined);
}

function impactRank(ev: CalendarEventLike): number {
  if (ev.impact === "High") return 0;
  if (ev.impact === "Medium") return 1;
  return 2;
}

function starsOf(ev: CalendarEventLike): number {
  if (typeof ev.stars === "number") return ev.stars;
  return impactRank(ev) === 0 ? 3 : 2;
}
