// `lib/calendarOutcome.ts` — "hangi senaryo gerçekleşti?" görüntü kararı.
//
// Buradaki asıl değer iki sözleşmedir:
//   1. Yön kararı backend'in `outcome.side` alanından OKUNUR, yeniden türetilmez.
//   2. Pencere UTC+3 takvim günüdür — gün dönümünde kart fetch beklemeden düşer.
// Ayrıca `"—"` "veri yok" demektir; onu gerçek bir sonuç sanıp vitrine koymak
// `lib/format.ts`'in "0 meşru bir değerdir ama veri yok değildir" kuralını ihlal eder.

import { describe, it, expect } from "vitest";
import {
  hasPublishedActual,
  hasCalendarData,
  outcomeSide,
  comparisonText,
  labelText,
  basisText,
  directionNoteText,
  endOfTrDayMs,
  isOutcomeVisibleNow,
  selectScenarioBranches,
  branchFallbackReason,
  selectTodaysPublished,
  selectPriorityAlertEvents,
  type CalendarEventLike,
} from "./calendarOutcome";

describe("hasPublishedActual", () => {
  it("gerçek değerleri açıklanmış sayar", () => {
    expect(hasPublishedActual("0.2%")).toBe(true);
    expect(hasPublishedActual("-1.5M")).toBe(true);
    expect(hasPublishedActual("145K")).toBe(true);
    expect(hasPublishedActual("0")).toBe(true); // 0 meşru bir açıklamadır
  });

  it("veri yok işaretlerini açıklanmış SAYMAZ", () => {
    for (const missing of ["—", "", "  ", "N/A", "n/a", "null", undefined, null]) {
      expect(hasPublishedActual(missing as string), String(missing)).toBe(false);
    }
  });
});

describe("hasCalendarData", () => {
  it("backend has_data bayrağını otorite kabul eder", () => {
    expect(hasCalendarData({ has_data: true, forecast: "—", previous: "—" })).toBe(true);
    expect(hasCalendarData({ has_data: false, forecast: "0.2%", previous: "—" })).toBe(false);
  });

  it("bayrak yoksa (eski önbellek) forecast/previous'dan türetir", () => {
    expect(hasCalendarData({ forecast: "0.2%", previous: "—" })).toBe(true);
    expect(hasCalendarData({ forecast: "—", previous: "148.2" })).toBe(true);
    expect(hasCalendarData({ forecast: "—", previous: "—" })).toBe(false);
    expect(hasCalendarData({})).toBe(false);
  });
});

describe("outcomeSide / metin okuyucular", () => {
  it("backend kararını okur, bilinmeyeni null yapar", () => {
    expect(outcomeSide({ outcome: { side: "bullish" } })).toBe("bullish");
    expect(outcomeSide({ outcome: { side: "bearish" } })).toBe("bearish");
    expect(outcomeSide({ outcome: { side: null } })).toBe(null);
    expect(outcomeSide({ outcome: null })).toBe(null);
    expect(outcomeSide({})).toBe(null);
    expect(outcomeSide(null)).toBe(null);
  });

  it("boş metinleri null döner (boş rozet basılmaz)", () => {
    expect(comparisonText({ outcome: { comparison_tr: "3.2% > 3.0%" } })).toBe("3.2% > 3.0%");
    expect(comparisonText({ outcome: { comparison_tr: "  " } })).toBe(null);
    expect(labelText({ outcome: { label_tr: "Önceki'ye Göre Azalış" } })).toBe("Önceki'ye Göre Azalış");
    expect(labelText({ outcome: { label_tr: "" } })).toBe(null);
  });

  it("kıyas tabanını çözer", () => {
    expect(basisText({ outcome: { basis: "forecast" } })).toBe("Beklenti");
    expect(basisText({ outcome: { basis: "previous" } })).toBe("Önceki");
    expect(basisText({ outcome: { basis: null } })).toBe(null);
  });

  it("ters aile uyarısını okur, yoksa null döner", () => {
    // "231K > 220K" ama dal 🔴 — rozetin yanında açıklama şart.
    expect(
      directionNoteText({ outcome: { direction_note_tr: "Yüksek değer bu olayda ayı yönlüdür" } }),
    ).toBe("Yüksek değer bu olayda ayı yönlüdür");
    // Ters olmayan aile / eşitlik: uyarı basılmaz.
    expect(directionNoteText({ outcome: { direction_note_tr: null } })).toBe(null);
    expect(directionNoteText({ outcome: { direction_note_tr: "  " } })).toBe(null);
    expect(directionNoteText({ outcome: {} })).toBe(null);
    expect(directionNoteText({})).toBe(null);
    expect(directionNoteText(null)).toBe(null);
  });
});

describe("endOfTrDayMs", () => {
  it("UTC+3 gününün bitişini verir", () => {
    // 2026-10-09T12:30:00Z -> TR 15:30, TR günü 2026-10-10T00:00+03:00 = 2026-10-09T21:00Z
    expect(endOfTrDayMs(Date.parse("2026-10-09T12:30:00Z"))).toBe(
      Date.parse("2026-10-09T21:00:00Z"),
    );
  });

  it("TR günü ile UTC günü farklı olduğunda TR'yi esas alır", () => {
    // 2026-10-09T23:00:00Z -> TR 2026-10-10 02:00; TR günü bitişi 2026-10-10T21:00Z
    expect(endOfTrDayMs(Date.parse("2026-10-09T23:00:00Z"))).toBe(
      Date.parse("2026-10-10T21:00:00Z"),
    );
  });
});

describe("isOutcomeVisibleNow", () => {
  const announcedAt = "2026-10-09T12:30:00Z"; // TR 15:30

  it("açıklanmadan önce gizler", () => {
    const before = Date.parse("2026-10-09T12:29:00Z");
    expect(isOutcomeVisibleNow(announcedAt, before, "3.2%")).toBe(false);
  });

  it("açıklandıktan sonra aynı TR gününde gösterir", () => {
    expect(isOutcomeVisibleNow(announcedAt, Date.parse("2026-10-09T20:00:00Z"), "3.2%")).toBe(true);
  });

  it("TR günü bitince gizler (UTC günü henüz kapanmamış olsa bile)", () => {
    // 2026-10-09T21:00:00Z = TR 2026-10-10 00:00 — yeni gün
    expect(isOutcomeVisibleNow(announcedAt, Date.parse("2026-10-09T21:00:00Z"), "3.2%")).toBe(false);
    expect(isOutcomeVisibleNow(announcedAt, Date.parse("2026-10-10T09:00:00Z"), "3.2%")).toBe(false);
  });

  it("sınırlarda doğru davranır", () => {
    expect(isOutcomeVisibleNow(announcedAt, Date.parse("2026-10-09T20:59:59Z"), "3.2%")).toBe(true);
    expect(isOutcomeVisibleNow(announcedAt, Date.parse("2026-10-09T21:00:00Z"), "3.2%")).toBe(false);
  });

  it("veri yoksa hiç göstermez", () => {
    expect(isOutcomeVisibleNow(announcedAt, Date.parse("2026-10-09T20:00:00Z"), "—")).toBe(false);
    expect(isOutcomeVisibleNow(announcedAt, Date.parse("2026-10-09T20:00:00Z"), undefined)).toBe(false);
  });

  it("date_iso yoksa/bozuksa veriyi GİZLEMEZ (gösterir)", () => {
    expect(isOutcomeVisibleNow(undefined, Date.parse("2026-10-09T20:00:00Z"), "3.2%")).toBe(true);
    expect(isOutcomeVisibleNow("not-a-date", Date.parse("2026-10-09T20:00:00Z"), "3.2%")).toBe(true);
  });
});

describe("selectScenarioBranches", () => {
  it("sonuç görünürken yalnız gerçekleşen dalı bırakır", () => {
    expect(selectScenarioBranches("bullish", true)).toEqual({ showBullish: true, showBearish: false });
    expect(selectScenarioBranches("bearish", true)).toEqual({ showBullish: false, showBearish: true });
  });

  it("dal belirsizse (eşitlik/ayrıştırılamadı) iki dalı da gösterir", () => {
    expect(selectScenarioBranches(null, true)).toEqual({ showBullish: true, showBearish: true });
    expect(selectScenarioBranches(undefined, true)).toEqual({ showBullish: true, showBearish: true });
  });

  it("sonuç görünmüyorsa mevcut davranışı korur", () => {
    expect(selectScenarioBranches("bullish", false)).toEqual({ showBullish: true, showBearish: true });
    expect(selectScenarioBranches("bearish", false)).toEqual({ showBullish: true, showBearish: true });
  });
});

describe("branchFallbackReason", () => {
  const now = Date.parse("2026-10-09T20:00:00Z");

  it("dal belirliyse null döner (açıklama basılmaz)", () => {
    expect(
      branchFallbackReason(
        { date_iso: "2026-10-09T12:30:00Z", actual: "3.2%", outcome: { side: "bullish" } },
        now,
      ),
    ).toBe(null);
  });

  it("açıklanmadıysa 'pending'", () => {
    expect(
      branchFallbackReason(
        { date_iso: "2026-10-09T22:00:00Z", actual: "—", outcome: null },
        now,
      ),
    ).toBe("pending");
  });

  it("eşitlikte 'tie' — 'ayrıştırılamadı' ile KARIŞTIRILMAZ", () => {
    // Operatör için kritik ayrım: veri geldi ve yönsüz (tie), veri gelmedi (pending),
    // yoksa ayrıştırılamadı (unparsed). Yanlış mesaj veriyi hiç gelmemiş sanmaya yol açar.
    expect(
      branchFallbackReason(
        {
          date_iso: "2026-10-09T12:30:00Z",
          actual: "2.1%",
          outcome: { side: null, comparison_tr: "2.1% = 2.1% (Beklentiye Uygun)", label_tr: "Beklentiye Uygun" },
        },
        now,
      ),
    ).toBe("tie");
  });

  it("açıklandı ama eşitlik metni de yoksa 'unparsed'", () => {
    expect(
      branchFallbackReason(
        { date_iso: "2026-10-09T12:30:00Z", actual: "3.2%", outcome: { side: null } },
        now,
      ),
    ).toBe("unparsed");
  });

  it("olay yoksa null", () => {
    expect(branchFallbackReason(null, now)).toBe(null);
    expect(branchFallbackReason(undefined, now)).toBe(null);
  });
});

describe("selectTodaysPublished", () => {
  const now = Date.parse("2026-10-09T20:00:00Z"); // TR 23:00, gün kapanmadan
  const base: CalendarEventLike = {
    date_iso: "2026-10-09T12:30:00Z",
    actual: "3.2%",
    forecast: "3.0%",
    has_data: true,
    outcome: { side: "bullish", label_tr: "Beklenti Üzeri" },
  };

  it("verisi olan, sonucu belirlenmiş ve penceresi açık olayları döner", () => {
    expect(selectTodaysPublished([base], now)).toHaveLength(1);
  });

  it("verisi olmayan olayı almaz", () => {
    const noData = { ...base, has_data: false, forecast: "—", previous: "—" };
    expect(selectTodaysPublished([noData], now)).toHaveLength(0);
  });

  it("sonucu belirlenmemiş (side=null) olayı almaz", () => {
    const undecided = { ...base, outcome: { side: null, label_tr: "Beklentiye Uygun" } };
    expect(selectTodaysPublished([undecided], now)).toHaveLength(0);
  });

  it("henüz açıklanmamış olayı almaz", () => {
    const future = { ...base, date_iso: "2026-10-09T22:00:00Z", actual: "—" };
    expect(selectTodaysPublished([future], now)).toHaveLength(0);
  });

  it("dün açıklanmış olayı almaz", () => {
    const yesterday = { ...base, date_iso: "2026-10-08T12:30:00Z" };
    expect(selectTodaysPublished([yesterday], now)).toHaveLength(0);
  });

  it("en son açıklananı en üste koyar", () => {
    const early = { ...base, date_iso: "2026-10-09T08:00:00Z" };
    const late = { ...base, date_iso: "2026-10-09T18:00:00Z" };
    const ordered = selectTodaysPublished([early, late], now);
    expect(ordered[0].date_iso).toBe("2026-10-09T18:00:00Z");
  });
});

// ============================================================================
// UYARI ÖNCELİĞİ — aynı dakikada açıklanan kümeden tek popup
// ============================================================================

describe("selectPriorityAlertEvents", () => {
  const ISO = "2026-10-16T12:30:00.000Z";

  it("aynı dakikada açıklanan kümeden yalnız en önemlisini bırakır", () => {
    const out = selectPriorityAlertEvents([
      { id: "a", date_iso: ISO, stars: 2, impact: "Medium" },
      { id: "b", date_iso: ISO, stars: 3, impact: "High" },
      { id: "c", date_iso: ISO, stars: 2, impact: "Medium" },
    ]);
    expect(out.map((e) => e.id)).toEqual(["b"]);
  });

  it("hiçbir olayı GİZLEMEZ — farklı dakikalar hepsi kalır", () => {
    const out = selectPriorityAlertEvents([
      { id: "a", date_iso: "2026-10-16T12:30:00.000Z", stars: 3 },
      { id: "b", date_iso: "2026-10-16T14:00:00.000Z", stars: 2 },
      { id: "c", date_iso: "2026-10-16T15:30:00.000Z", stars: 3 },
    ]);
    expect(out.map((e) => e.id)).toEqual(["a", "b", "c"]);
  });

  it("eşit yıldızda impact ile karar verir", () => {
    const out = selectPriorityAlertEvents([
      { id: "a", date_iso: ISO, stars: 2, impact: "Medium" },
      { id: "b", date_iso: ISO, stars: 2, impact: "High" },
    ]);
    expect(out.map((e) => e.id)).toEqual(["b"]);
  });

  it("yıldız yoksa impact'ten türetir (3 yıldız varsayılanı)", () => {
    const out = selectPriorityAlertEvents([
      { id: "a", date_iso: ISO, impact: "Medium" },
      { id: "b", date_iso: ISO, impact: "High" },
    ]);
    expect(out.map((e) => e.id)).toEqual(["b"]);
  });

  it("tam eşitlikte GİRDİ SIRASINI korur (kararlı)", () => {
    const out = selectPriorityAlertEvents([
      { id: "ilk", date_iso: ISO, stars: 3, impact: "High" },
      { id: "ikinci", date_iso: ISO, stars: 3, impact: "High" },
    ]);
    expect(out.map((e) => e.id)).toEqual(["ilk"]);
    expect(out).toHaveLength(1);
  });

  it("date_iso yoksa olay düşürülmez, kendi başına değerlendirilir", () => {
    const out = selectPriorityAlertEvents([
      { id: "tarihsiz-1", stars: 2 },
      { id: "tarihsiz-2", stars: 3 },
    ]);
    expect(out.map((e) => e.id)).toEqual(["tarihsiz-1", "tarihsiz-2"]);
  });

  it("girdi mutasyona uğratılmaz", () => {
    const input = [
      { id: "a", date_iso: ISO, stars: 2 },
      { id: "b", date_iso: ISO, stars: 3 },
    ];
    const snapshot = JSON.stringify(input);
    selectPriorityAlertEvents(input);
    expect(JSON.stringify(input)).toBe(snapshot);
  });

  it("gerçek vaka: Retail Sales manşet + Ex Autos tek popup'a iner", () => {
    const out = selectPriorityAlertEvents([
      { id: "tv-retail", date_iso: ISO, stars: 3, impact: "High" },
      { id: "tv-retail-ex", date_iso: ISO, stars: 2, impact: "Medium" },
    ]);
    expect(out).toHaveLength(1);
    expect(out[0].id).toBe("tv-retail");
  });

  it("gerçek vaka: EIA Crude + Gasoline (ikisi de 2 yıldız) tek popup'a iner", () => {
    const out = selectPriorityAlertEvents([
      { id: "tv-eia-crude", date_iso: ISO, stars: 2, impact: "Medium" },
      { id: "tv-eia-gasoline", date_iso: ISO, stars: 2, impact: "Medium" },
    ]);
    expect(out).toHaveLength(1);
    // İkisi de aynı önemde: girdi sırası korunur, ama POPUP TEKTİR.
    expect(out[0].id).toBe("tv-eia-crude");
  });
});
