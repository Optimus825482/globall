// Aynı sözleşme, TR (TRY) örneğinde.
//
// Neden ayrı dosya: `NEXT_PUBLIC_QUOTE_ASSET` bir Next.js BUILD-TIME sabitidir.
// Vitest dosya başına kendi modül grafiğini kurduğu için env'i import'tan ÖNCE
// ayarlamak gerekir; bu dosya tam olarak bunu yapar.
//
// 2026-11-10: `format.ts` varsayılanı USDT olduğu için TR örneğini kilitleyen
// ayrı bir dosya şart — aksi hâlde "env verilmezse TRY" varsayımı sessizce
// yanlış olur (5 test kırmızıydı).

import { describe, it, expect, beforeAll, vi } from "vitest";

describe("format — TR (TRY) gösterimi", () => {
  let fmt: typeof import("./format");

  beforeAll(async () => {
    process.env.NEXT_PUBLIC_QUOTE_ASSET = "TRY";
    vi.resetModules();
    fmt = await import("./format");
  });

  it("quote TRY, gösterim birimi '₺'", () => {
    expect(fmt.QUOTE_ASSET).toBe("TRY");
    expect(fmt.QUOTE_SYMBOL).toBe("₺");
  });

  it("formatMoney/formatTL '₺' basar", () => {
    expect(fmt.formatTL(1234.5)).toBe("₺1.234,50");
  });

  it("toSymbol TRY çifti üretir, iki kez eklemez", () => {
    expect(fmt.toSymbol("BTC")).toBe("BTCTRY");
    expect(fmt.toSymbol("btc")).toBe("BTCTRY");
    expect(fmt.toSymbol("BTCTRY")).toBe("BTCTRY");
  });

  it("withQuote/withQuotePrice '₺' öneki basar (maksimum ondalık kovası)", () => {
    expect(fmt.withQuote(1.23456, 2)).toBe("₺1,23");
    expect(fmt.withQuote(1.23456, 6)).toBe("₺1,23456");
    expect(fmt.withQuotePrice(1.5)).toBe(`₺${fmt.formatPrice(1.5)}`);
    expect(fmt.withQuotePrice(4250)).toBe(`₺${fmt.formatPrice(4250)}`);
    expect(fmt.withQuotePrice(null)).toBe("—");
  });

  it("SAYI biçimi birimden bağımsız: tr-TR gruplama ve virgül ondalık", () => {
    expect(fmt.formatTL(1234.5).slice("₺".length))
      .toBe((1234.5).toLocaleString("tr-TR", { minimumFractionDigits: 2, maximumFractionDigits: 2 }));
  });
});
