import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { describe, expect, it } from "vitest";

/**
 * AYARLAR > FOREX ML SEKMESİ — regresyon kilidi (2026-11-09).
 *
 * Kullanıcı: "Ayarlar kısmına Forex ML sekmesi oluştur; bu sekmede eğitim ve
 * testleri yaparak loglayalım ve sayfada raporlayalım". Veri sunucu DB'sinde
 * olduğu için eğitim sunucuda koşar; panel onu tetikler ve raporlar.
 *
 * Kilitlenen davranış:
 *  1. Ayarlar'da "Forex ML" sekmesi var ve bileşeni yüklüyor.
 *  2. Eğitim SUNUCUDA koşuyor (`/api/system/forex-ml/train`), istemcide değil.
 *  3. Koşu geçmişi sayfada loglanıyor (forex_ml_runs tablosu).
 *  4. OOS skill <= 0 ise "karar kapısı OLMAMALI" uyarısı görünüyor.
 */
const HERE = path.dirname(fileURLToPath(import.meta.url));
const FRONTEND = path.resolve(HERE, "..", "..");
const read = (...p: string[]) => readFileSync(path.join(FRONTEND, ...p), "utf8");

const PAGE = read("app", "settings", "page.tsx");
const PANEL = read("app", "settings", "ForexMlPanel.tsx");

describe("Ayarlar sekmesi", () => {
  it("'Forex ML' sekmesi kayıtlı ve render ediliyor", () => {
    expect(PAGE).toContain('["ml", "Forex ML"');
    expect(PAGE).toContain('"profile" | "ml"');
    expect(PAGE).toContain("<ForexMlPanel />");
    expect(PAGE).toContain('import ForexMlPanel from "./ForexMlPanel"');
  });
});

describe("Eğitim akışı", () => {
  it("eğitim SUNUCUDA koşuyor (admin ucu)", () => {
    expect(PANEL).toContain("/api/system/forex-ml/train");
    expect(PANEL).toContain("/api/system/forex-ml");
    // sayfada istemci-taraflı eğitim YOK (sklearn tarayıcıda değil)
    expect(PANEL).not.toContain("LogisticRegression");
  });

  it("koşu geçmişi loglanıyor", () => {
    expect(PANEL).toContain("Eğitim koşusu geçmişi");
    expect(PANEL).toContain("brier_skill_oos");
  });

  it("eğitim hata verirse panelde görünüyor", () => {
    const i = PANEL.indexOf("!report.trained");
    expect(i).toBeGreaterThan(-1);
    expect(PANEL.slice(i - 200, i + 200)).toContain("Eğitim yapılmadı");
  });
});

describe("Dürüstlük", () => {
  it("'karar kapısı değil' uyarısı var", () => {
    expect(PANEL).toContain("karar kapısı DEĞİL");
    expect(PANEL).toContain("replay A/B");
  });

  it("OOS skill işaretine göre renk", () => {
    expect(PANEL).toContain("skillCls");
  });
});
