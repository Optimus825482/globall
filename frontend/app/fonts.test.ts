import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

/**
 * FONT YAPILANDIRMASI — regresyon kilidi (2026-11-09).
 *
 * Neden bu test var: iki gerçek hata bu dosyada oluştu ve ikisi de SESSİZDİ —
 * ekranda "font yüklenmiyor / bazı harfler bozuk" olarak göründü, derleme
 * başarılıydı.
 *
 * 1) `next/font/local` içindeki `fallback` seçeneğini DERLEME ANINDA statik
 *    olarak okur. Dizi dışında tanımlanmış bir sabiti spread etmek
 *    (`...SYMBOLS`) "Unexpected spread" ile derlemeyi kırar — bu yüzden
 *    adlar dosyada DÜZ yazılıdır.
 * 2) Daha sinsi olanı: next/font bu adları üretilen CSS'e **TIRNAKSIZ** yazar.
 *    Tırnaksız aile adı geçerli CSS tanımlayıcıları dizisi olmalıdır. Bir
 *    turda listeye `Noto Sans Symbols 2` eklendi; son parça rakamla başladığı
 *    için GEÇERSİZ bir tanımlayıcıdır ve tarayıcı `font-family` bildiriminin
 *    TAMAMINI düşürür → metin varsayılana (Times New Roman) kayar. Derleme
 *    yine başarılı olur, hata ancak tarayıcıda ölçümle görünür.
 */

const kaynak = readFileSync(
  fileURLToPath(new URL("./fonts.ts", import.meta.url)),
  "utf8",
);

/** CSS tanımlayıcısı: `-?` + harf/alt çizgi/unicode ile başlar, sonra
 *  harf, rakam, tire, alt çizgi, unicode gelebilir. Başta rakam OLMAZ. */
const GECERLI_TANIMLAYICI = /^-?[A-Za-z_\u00A0-\uFFFF][A-Za-z0-9_\-\u00A0-\uFFFF]*$/;

/** Tırnaksız yazılacak aile adı: boşlukla ayrılmış GEÇERLİ tanımlayıcılar. */
function aileAdiGecerliMi(ad: string): boolean {
  const parcalar = ad.trim().split(/\s+/);
  return parcalar.length > 0 && parcalar.every((p) => GECERLI_TANIMLAYICI.test(p));
}

function fallbackAdlari(): string[] {
  const bloklar = [...kaynak.matchAll(/fallback:\s*\[([\s\S]*?)\]/g)].map((m) => m[1]);
  return bloklar.flatMap((b) => [...b.matchAll(/"([^"]+)"/g)].map((m) => m[1]));
}

describe("fonts.ts — font yapılandırması", () => {
  it("en az iki fallback listesi tanımlar (sans + mono)", () => {
    const adlar = fallbackAdlari();
    expect(adlar.length).toBeGreaterThan(10);
    expect(kaynak).toMatch(/var:?\s*|variable:\s*"--font-sans"/);
    expect(kaynak).toContain('variable: "--font-mono"');
  });

  it("HER fallback adı geçerli bir tırnaksız CSS aile adıdır", () => {
    // Kırılırsa: `font-family` bildiriminin tamamı düşer ve tüm arayüz
    // varsayılan fonta kayar. Yeni ad eklerken tırnak kullan ya da adı düzelt.
    const gecersiz = fallbackAdlari().filter((ad) => !aileAdiGecerliMi(ad));
    expect(gecersiz).toEqual([]);
  });

  it("fallback listelerinde spread kullanılmaz (next/font statik okur)", () => {
    const bloklar = [...kaynak.matchAll(/fallback:\s*\[([\s\S]*?)\]/g)].map((m) => m[1]);
    for (const b of bloklar) {
      expect(b).not.toMatch(/\.\.\./);
    }
  });

  it("Türkçe ve ₺ için sembol/emoji yedeği zincirde vardır", () => {
    // Bu fontların hiçbirinde ok/geometrik şekil/emoji yoktur; tarayıcı
    // bunları sistem sembol fontundan alır — zincirde açıkça yazılı olmalı.
    expect(kaynak).toContain('"Segoe UI Symbol"');
    expect(kaynak).toContain('"Noto Color Emoji"');
  });

  it("font dosyaları repoya gömülüdür (build'de ağ gerekmez)", () => {
    expect(kaynak).toContain("./fonts/Roboto-Variable.woff2");
    expect(kaynak).toContain("./fonts/NotoSansMono-Variable.woff2");
  });
});
