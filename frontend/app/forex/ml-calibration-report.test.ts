import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { describe, expect, it } from "vitest";

/**
 * ML KALİBRASYON RAPORU + CSV — regresyon kilidi (2026-11-09).
 *
 * Kullanıcı isteği: "ML olasılık kalibrasyonu bunu da raporlardan görebileyim,
 * CSV çıktı alabileyim." Rapor yalnız `/api/system/health` içinde SAYAÇ olarak
 * görünüyordu; ham veriyi indirmenin yolu yoktu.
 *
 * Kilitlenen davranış:
 *  1. Rapor sayfasında "ML Kalibrasyonu" sekmesi var ve bileşeni yüklüyor.
 *  2. CSV BACKEND'den indirilir (client-side üretim değil) → ekrandaki sayı ile
 *     dosya AYNI modülden gelir, birbirini tutar.
 *  3. Rapor OUT-OF-SAMPLE bloğunu gösterir; in-sample ECE'yi kanıt sanmaz.
 *     OOS skill ≤ 0 ise "filtre olarak kullanılamaz" uyarısı BASILIR.
 */
const HERE = path.dirname(fileURLToPath(import.meta.url));
const FRONTEND = path.resolve(HERE, "..", "..");
const read = (...p: string[]) => readFileSync(path.join(FRONTEND, ...p), "utf8");

const PAGE = read("app", "forex", "reports", "page.tsx");
const REPORT = read("app", "forex", "reports", "MlCalibrationReport.tsx");

describe("Rapor sekmesi", () => {
  it("sekme listesinde ve görünüm tipinde kayıtlı", () => {
    expect(PAGE).toContain('"mlcal", "ML Kalibrasyonu"');
    expect(PAGE).toContain('"trades" | "llm" | "risk" | "mlcal"');
    expect(PAGE).toContain('view === "mlcal" ? <MlCalibrationReport />');
    expect(PAGE).toContain('import MlCalibrationReport from "./MlCalibrationReport"');
  });
});

describe("CSV indirme", () => {
  it("backend ucundan indiriliyor (client-side üretim değil)", () => {
    expect(REPORT).toContain("/api/reports/ml-calibration/csv?days=");
    expect(REPORT).toContain("await res.blob()");
    expect(REPORT).toContain("URL.revokeObjectURL");
  });

  it("indirme hatası sessizce yutulmuyor", () => {
    const i = REPORT.indexOf("const downloadCsv");
    const block = REPORT.slice(i, i + 900);
    expect(block).toContain("catch");
    expect(block).toContain("setError");
  });
});

describe("Kanıt dürüstlüğü", () => {
  it("out-of-sample bloğu gösteriliyor", () => {
    expect(REPORT).toContain("out_of_sample");
    expect(REPORT).toContain("OOS Brier skill");
  });

  it("OOS skill ≤ 0 ise 'filtre olarak kullanılamaz' uyarısı var", () => {
    // Uyarı başlığı büyük harfli yazılır (FİLTRESİ) → kök ifadeyi ara.
    expect(REPORT).toContain("KANIT ZAYIF");
    expect(REPORT).toContain("kullanılamaz");
    expect(REPORT).toContain("verdict");
  });

  it("in-sample yanılsaması metinde açıkça uyarılıyor", () => {
    expect(REPORT).toContain("yanılsama");
  });

  it("eşik eğrisi ve güvenilirlik kovaları render ediliyor", () => {
    expect(REPORT).toContain("threshold_curve");
    expect(REPORT).toContain("bins");
  });
});
