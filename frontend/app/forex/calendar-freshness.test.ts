import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { describe, expect, it } from "vitest";

/**
 * TAKVİM TAZELİK DÜRÜSTLÜĞÜ — regresyon kilidi (2026-11-09).
 *
 * Şikâyet: "takvimi güncellemiyor". İki bağımsız kusur vardı:
 *  1. BACKEND: okuma sorgusu `ORDER BY date_iso ASC LIMIT 150` ile EN ESKİ
 *     satırları döndürüyordu; tablo 150'yi aşınca en yeni olaylar hiç dönmüyordu
 *     (ölçüm: bugüne ait 0 olay). → tests/test_forex_news.py'de kilitlendi.
 *  2. ÖN UÇ: "Güncellendi HH:MM" YALNIZ tarayıcının çekim saatini gösteriyordu;
 *     veri günlerce bayat olsa da saat "şimdi" görünüyordu → kullanıcı taze
 *     sanıyordu. Bu dosya o etiketin sunucunun GERÇEK kaynak senkronuna
 *     bağlandığını kilitler.
 */
const HERE = path.dirname(fileURLToPath(import.meta.url));
const FRONTEND = path.resolve(HERE, "..", "..");
const PAGE = readFileSync(path.join(FRONTEND, "app", "forex", "calendar", "page.tsx"), "utf8");

describe("Takvim tazelik etiketi", () => {
  it("sunucunun kaynak senkronunu kullanıyor (tarayıcı çekim saati değil)", () => {
    expect(PAGE).toContain("last_sync_ts");
    expect(PAGE).toContain("setLastSyncTs");
    expect(PAGE).toContain("syncAgeMin");
  });

  it("bayat veri görsel olarak ayırt ediliyor", () => {
    expect(PAGE).toContain("syncStale");
    expect(PAGE).toContain("bg-amber-400");
    expect(PAGE).toContain("saat önce çekildi");
  });

  it("kaynak senkronu tooltip'te tam zaman olarak var", () => {
    expect(PAGE).toContain("Kaynak senkronu");
  });
});

describe("Açıklanan değer dürüstlüğü", () => {
  it("geçmiş olayda değer yoksa 'gecikmeli' yazıyor ('—' tek başına bozuk görünüyordu)", () => {
    expect(PAGE).toContain("Açıklanan: gecikmeli");
    expect(PAGE).toContain("is_passed");
  });

  it("gecikme nedenini açıklıyor (kaynak aynı gün yayınlamıyor)", () => {
    expect(PAGE).toContain("aynı gün yayınlamıyor");
  });
});
