import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { describe, expect, it } from "vitest";

/**
 * COT PANEL DÜĞMESİ — regresyon kilidi (2026-11-09).
 *
 * Şikâyet: sohbette "COT pozisyonlanma ... verisi bu snapshot'ta yok" çıkıyordu.
 * Sebep: LLM bağlamı COT artefaktını OKUYOR ama üretici YALNIZ elle çalıştırılan
 * bir betikti → üretimde artefakt hiç üretilmedi. Kullanıcının kuralı: bakım/
 * ölçüm işleri TERMİNALDE değil PANELDE düğmeyle çalışsın.
 */
const HERE = path.dirname(fileURLToPath(import.meta.url));
const FRONTEND = path.resolve(HERE, "..", "..");
const PANEL = readFileSync(path.join(FRONTEND, "app", "forex", "components", "AutoSettingsPanel.tsx"), "utf8");

describe("COT panel düğmesi", () => {
  it("durumu sunucudan okuyor", () => {
    expect(PANEL).toContain('apiFetch("/api/system/cot")');
    expect(PANEL).toContain("loadCot");
    expect(PANEL).toContain("cotState");
  });

  it("indirme düğmesi uç noktayı POST ediyor", () => {
    expect(PANEL).toContain('apiFetch("/api/system/cot-refresh", { method: "POST" })');
    expect(PANEL).toContain("COT verisini indir");
  });

  it("artefakt yokken dürüst mesaj veriyor (uydurma yok)", () => {
    expect(PANEL).toContain('LLM\'e "COT verisi yok" olarak gider');
  });

  it("bayat artefaktı görsel olarak işaretliyor", () => {
    expect(PANEL).toContain("cotState.stale");
    expect(PANEL).toContain("BAYAT");
  });

  it("kalabalık/ayrışma uyarıları gösteriliyor", () => {
    expect(PANEL).toContain("kalabalık");
    expect(PANEL).toContain("ayrışma");
  });
});
