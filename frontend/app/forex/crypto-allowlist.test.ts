import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { describe, expect, it } from "vitest";

/**
 * KRİPTO ALLOWLIST PARİTESİ — regresyon kilidi (2026-11-09).
 *
 * ÜRÜN KURALI: yalnız **BTC / ETH / XRP**. Backend `config.CRYPTO_ALLOWED_BASES`
 * diğer tüm kripto tabanlarını eler. Frontend'de bu semboller listelerde kaldığı
 * sürece kullanıcı "açtım ama işlem/veri gelmiyor" durumuna düşer — bu SESSİZ bir
 * kusurdur (derleme geçer, kart boş kalır).
 *
 * Bu dosya iki tarafı BİRBİRİNE bağlar: frontend listeleri ile backend
 * allowlist'i aynı kalmazsa test kırılır. Emekliye ayrılan tabanlar
 * (`EMEKLI`) hiçbir frontend dosyasında seçenek olarak geçemez.
 */
const HERE = path.dirname(fileURLToPath(import.meta.url));
const FRONTEND = path.resolve(HERE, "..", "..");
const REPO = path.resolve(FRONTEND, "..");

const APP_BASES = ["BTC", "ETH", "XRP"];
const EMEKLI = ["SOL", "BNB", "LNK", "UNI", "AVX", "ADA", "XTZ", "DATA"];

const read = (...p: string[]) => readFileSync(path.join(FRONTEND, ...p), "utf8");

const PORTFOLIO = read("app", "forex", "portfolio", "page.tsx");
const PANEL = read("app", "forex", "components", "AutoSettingsPanel.tsx");
const FOREX_PAGE = read("app", "forex", "page.tsx");

/** Backend allowlist'i kaynak dosyadan oku (env yoksa varsayılan). */
function backendBases(): string[] {
  const src = readFileSync(path.join(REPO, "backend", "app", "config.py"), "utf8");
  const m = src.match(/CRYPTO_ALLOWED_BASES"\s*,\s*"([^"]+)"/);
  expect(m, "config.py'de CRYPTO_ALLOWED_BASES varsayılanı bulunamadı").toBeTruthy();
  return m![1].split(",").map((s) => s.trim().toUpperCase());
}

describe("backend allowlist = BTC/ETH/XRP", () => {
  it("config.py varsayılanı bu üçü", () => {
    expect(backendBases().sort()).toEqual([...APP_BASES].sort());
  });
});

describe("Forex Portföy sayfası — Kripto Çiftleri sekmesi", () => {
  it("CRYPTO_SYMBOLS yalnız BTC/ETH/XRP", () => {
    const block = PORTFOLIO.slice(
      PORTFOLIO.indexOf("const CRYPTO_SYMBOLS"),
      PORTFOLIO.indexOf("export default function ForexPortfolioPage"),
    );
    const syms = [...block.matchAll(/sym:\s*"([A-Z]+)"/g)].map((m) => m[1]);
    expect(syms).toEqual(["BTCUSD", "ETHUSD", "XRPUSD"]);
  });

  it("emekli tabanlar sayfada hiç geçmiyor", () => {
    for (const base of EMEKLI) {
      // Örn. "SOLUSD" — eski kartlar tamamen kalkmalı
      expect(PORTFOLIO).not.toContain(`${base}USD`);
    }
  });

  it("rozet sayıyı listeden türetiyor (elle yazılmış '10 Varlık' yok)", () => {
    expect(PORTFOLIO).toContain("${CRYPTO_SYMBOLS.length} Varlık");
    expect(PORTFOLIO).not.toMatch(/badge:\s*"\d+ Varlık"/);
  });

  it("yardım metni ve arama ipucu güncel", () => {
    expect(PORTFOLIO).not.toContain("10 IC Markets kripto");
    expect(PORTFOLIO).toContain("BTC/ETH/XRP");
    expect(PORTFOLIO).not.toContain("Kripto ara (SOL");
  });
});

describe("Ayarlar paneli — sembol seçici", () => {
  it("Kripto (7/24) grubu yalnız BTC/ETH/XRP", () => {
    const group = PANEL
      .split('group: "Kripto (7/24)" }')
      .slice(0, -1)
      .map((chunk) => chunk.slice(chunk.lastIndexOf('{ sym: "')));
    const syms = group.map((chunk) => chunk.match(/sym:\s*"([A-Z]+)"/)![1]);
    expect(syms).toEqual(["BTCUSD", "ETHUSD", "XRPUSD"]);
  });

  it("fvg_symbols varsayılanları yalnız izinli üçlü", () => {
    const defaults = [...PANEL.matchAll(/fvg_symbols:[^[]*\[([^\]]*)\]/g)].map((m) =>
      m[1].split(",").map((s) => s.trim().replace(/"/g, "")).filter(Boolean),
    );
    expect(defaults.length).toBeGreaterThanOrEqual(3);
    for (const d of defaults) expect(d).toEqual(["BTCUSD", "ETHUSD", "XRPUSD"]);
  });

  it("emekli tabanlar panelde seçenek olarak kalmadı", () => {
    for (const base of EMEKLI) expect(PANEL).not.toContain(`${base}USD`);
  });
});

describe("Radar sayfası kategori filtresi", () => {
  it("kripto filtresi emekli tabanları saymıyor", () => {
    for (const base of EMEKLI) expect(FOREX_PAGE).not.toContain(`${base}USD`);
  });
});
