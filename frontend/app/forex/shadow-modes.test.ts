import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { describe, expect, it } from "vitest";

/**
 * GÖLGE MODLAR SEKMESİ — regresyon kilidi (2026-11-09).
 *
 * Kullanıcı isteği: "kaç tane gölge mod varsa raporlar kısmında raporlama
 * sekmesi olarak oluştur". Bu dosya sekmenin ve dürüstlük kurallarının yerinde
 * kaldığını kilitler:
 *  1. Raporlar sayfasında "Gölge Modlar" sekmesi var ve bileşeni yüklüyor.
 *  2. Bileşen sunucudan geliyor (`/api/reports/shadow-summary`) — sayı uydurmuyor.
 *  3. "Gölge = kararı değiştirmez" uyarısı ekranda.
 *  4. ENFORCE modu ayrı etiketle gösteriliyor (karar değiştiren kapı).
 */
const HERE = path.dirname(fileURLToPath(import.meta.url));
const FRONTEND = path.resolve(HERE, "..", "..");
const read = (...p: string[]) => readFileSync(path.join(FRONTEND, ...p), "utf8");

const PAGE = read("app", "forex", "reports", "page.tsx");
const COMP = read("app", "forex", "reports", "ShadowModesReport.tsx");

describe("Sekme", () => {
  it("raporlar sayfasında kayıtlı", () => {
    expect(PAGE).toContain('["shadow", "Gölge Modlar"]');
    expect(PAGE).toContain('"mlcal" | "shadow"');
    expect(PAGE).toContain('view === "shadow" ? <ShadowModesReport />');
    expect(PAGE).toContain('import ShadowModesReport from "./ShadowModesReport"');
  });
});

describe("Bileşen dürüstlüğü", () => {
  it("veri sunucudan geliyor (uydurma sayı yok)", () => {
    expect(COMP).toContain("/api/reports/shadow-summary");
  });

  it("'gölge kararı değiştirmez' uyarısı var", () => {
    expect(COMP).toContain("kararı DEĞİŞTİRMEZ");
  });

  it("ENFORCE modu karar-değiştiren olarak etiketli", () => {
    expect(COMP).toContain("ENFORCE (karar değişir)");
    expect(COMP).toContain("GÖLGE");
  });

  it("ilerleme çubuğu erişilebilir (role=progressbar)", () => {
    expect(COMP).toContain('role="progressbar"');
    expect(COMP).toContain("aria-valuenow");
  });
});
