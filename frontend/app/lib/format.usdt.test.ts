// Aynı sözleşme, Global (USDT) örneğinde.
//
// Neden ayrı dosya: `NEXT_PUBLIC_QUOTE_ASSET` bir Next.js BUILD-TIME
// sabitidir. Vitest tek bir modül grafiğini paylaştığı için `format.ts`'yi
// içe aktarmadan önce `process.env`'i değiştirmek gerekir; bu dosya tam olarak
// bunu, modül grafiğini bu dosyaya özgü kılarak yapar.
//
// Bu ayrı dosyanın varlığı bir tesadüf değil: AYNI İMAJ iki quote'yu
// taşıyamaz. Global örneğinin kendi frontend build'i (docker-compose:
// `frontend_global`) gerekir.

import { describe, it, expect, beforeAll, vi } from "vitest";

describe("format — Global (USDT) gösterimi", () => {
  let fmt: typeof import("./format");

  beforeAll(async () => {
    process.env.NEXT_PUBLIC_QUOTE_ASSET = "USDT";
    // Bu dosya kendi modül grafini kurduğu için cache'i atmamız yeterli;
    // `format.ts` ilk kez burada, env tanımlıyken değerlendirilecek.
    vi.resetModules();
    fmt = await import("./format");
  });

  it("quote USDT, gösterim birimi '$' (₺ DEĞİL)", () => {
    expect(fmt.QUOTE_ASSET).toBe("USDT");
    expect(fmt.QUOTE_SYMBOL).toBe("$");
    expect(fmt.QUOTE_ASSET_NAME).toBe("USDT");
  });

  it("formatMoney/formatTL '$' basar — eski ad da aynı işi görür", () => {
    expect(fmt.formatMoney(1234.5)).toBe("$1.234,50");
    expect(fmt.formatTL(1234.5)).toBe("$1.234,50");
    expect(fmt.formatSignedMoney(-5)).toBe("-$5,00");
  });

  it("toSymbol TRY çifti üretmez", () => {
    // `BTCTRY` Global'da YOKTUR; bu sessizce boş grafik demektir.
    expect(fmt.toSymbol("BTC")).toBe("BTCUSDT");
    expect(fmt.toSymbol("BTCUSDT")).toBe("BTCUSDT");
  });

  it("withQuote/withQuotePrice önek olarak '$' basar", () => {
    // `withQuote` yalnız MAKSİMUM ondalık kovası uygular (trailing zero yok):
    // "1.234,5" — `formatMoney`'nin aksine. Çağıranın alanı belirler.
    expect(fmt.withQuote(1234.5, 2)).toBe("$1.234,5");
    expect(fmt.withQuote(1.23456789, 6)).toBe("$1,234568");
    expect(fmt.withQuote(1200, 0)).toBe("$1.200");
    expect(fmt.withQuotePrice(1.5)).toBe(`$${fmt.formatPrice(1.5)}`);
    expect(fmt.withQuotePrice(null)).toBe("—");
  });

  it("SAYI biçimi değişmedi: tr-TR gruplama ve virgül ondalık", () => {
    // Gösterim birimi değişti; sayının nasıl basıldığı DEĞİŞMEDİ. "1.234,50"
    // yalnız tr-TR'de çıkar (en-US'ta "1,234.50" olurdu).
    expect(fmt.formatMoney(1234.5)).toBe("$1.234,50");
    expect(fmt.formatMoney(1234.5).slice("$".length))
      .toBe((1234.5).toLocaleString("tr-TR", { minimumFractionDigits: 2, maximumFractionDigits: 2 }));
  });
});
