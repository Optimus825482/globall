// Borsaya bağlı varlık kontrolleri — 2026-09-27
//
// Bu test, Global özel terminalinin veri katmanını kilitler. Terminal 2478
// satırlık bir bileşende `h.asset === "TRY"` yazıyordu; Global örneğinde nakit
// varlık USDT olduğu için bu kontrol YANLIŞ sonuç veriyordu: nakit varlık
// işlem varlığı sanılıyor, pozisyon tablosunda satış butonu açılıyor ve PnL
// yanlış hesaplanıyordu. Uygulama çalışıyordu, yanlış şeyi söylüyordu —
// sessiz bozulmanın en pahalı türü.
//
// `isCash` burada yaşar çünkü saf fonksiyondur; `page.tsx` içinde kalsaydı
// test edilemezdi. Sayfa bu modülü içe aktarır.

import { describe, it, expect } from "vitest";
import { isCashAsset, cashSymbolLabel } from "./exchangeAsset";

describe("isCashAsset — nakit varlık tespiti", () => {
  it("TRY modunda TRY naktadır", () => {
    expect(isCashAsset("TRY", "TRY")).toBe(true);
    expect(isCashAsset("USDT", "TRY")).toBe(false);
    expect(isCashAsset("BTC", "TRY")).toBe(false);
  });

  it("Global modunda USDT naktadır, TRY değil", () => {
    // KRİTİK: Global'da TRY bir işlem varlığı değildir. Eski sabit kontrol
    // `h.asset === "TRY"` idi ve Global'da hiçbir zaman doğru dönmüyordu.
    expect(isCashAsset("USDT", "USDT")).toBe(true);
    expect(isCashAsset("TRY", "USDT")).toBe(false);
    expect(isCashAsset("BTC", "USDT")).toBe(false);
  });

  it("küçük harf ve karışık büyük/küçük normalize edilir", () => {
    // API bazen küçük harf döner; `==="TRY"` karşılaştırması kaçırırdı ve
    // nakit varlık işlem varlığı gibi işlenirdi.
    expect(isCashAsset("try", "TRY")).toBe(true);
    expect(isCashAsset("Usdt", "USDT")).toBe(true);
    expect(isCashAsset("uSdT", "USDT")).toBe(true);
  });

  it("boş, null ve tanımsız varlık nakit DEĞİLDİR", () => {
    // Boş string nakit sayılsa, `find` her seferinde ilk boş bakiyeyi seçer
    // ve nakit bakiyesi 0 yerine yanlış bir değere düşerdi.
    expect(isCashAsset("", "TRY")).toBe(false);
    expect(isCashAsset(null, "USDT")).toBe(false);
    expect(isCashAsset(undefined, "USDT")).toBe(false);
  });

  it("daha uzun varlık adı nakit sanılmaz", () => {
    // `TRY` ile birebir karşılaştırma yerine `endsWith` kullanılsaydı
    // "STRY" gibi bir varlık yanlışlıkla nakit olurdu. Kural: TAM EŞİTLİK.
    expect(isCashAsset("STRY", "TRY")).toBe(false);
    expect(isCashAsset("XTRY", "TRY")).toBe(false);
  });
});

describe("cashSymbolLabel — etiket", () => {
  it("sembol etiketi borsanın quote'südür", () => {
    expect(cashSymbolLabel("BTC", "TRY")).toBe("BTCTRY");
    expect(cashSymbolLabel("BTC", "USDT")).toBe("BTCUSDT");
  });

  it("zaten quote ile biten varlıkta çift eklemez", () => {
    expect(cashSymbolLabel("BTCUSDT", "USDT")).toBe("BTCUSDT");
    expect(cashSymbolLabel("BTCTRY", "TRY")).toBe("BTCTRY");
  });

  it("Global'da TRY etiketi üretmez", () => {
    // Eski sabit `{asset}TRY` yazımı Global'da "BTCTRY" üretiyordu — borsada
    // öyle bir sembol yoktur, arama boş döner ve kullanıcı neden bulamadığını
    // anlamaz.
    expect(cashSymbolLabel("BTC", "USDT")).not.toContain("TRY");
  });
});
