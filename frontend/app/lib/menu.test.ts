// Menü görünürlük kuralları — 2026-09-26
//
// Bu kilitler iki sınıf hatayı:
//
// 1. ERİŞİLEMEZLİK. Menü düz bir listeydi ve 25 sayfanın 10'u görünüyordu.
//    Kalan sayfalar çalışıyordu ama link verilmediği için kullanıcı URL'yi
//    bilmeden ulaşamıyordu. Burada "her sayfa ya menüde ya admin altında
//    erişilebilir" kuralı kilitlenir.
//
// 2. YANLIŞ BORSA. `/binance-tr` private API'ye (`api.binance.me`) bağlıdır;
//    Global örneğinde `api.binance.com` gerekir. İki örnek ayrı DB kullandığı
//    için Global'ın menüsünde TR terminali hem yanlış borsada hem de
//    yanlış veritabanında çalışırdı.

import { describe, it, expect } from "vitest";
import { MENU_GROUPS, BOTTOM_NAV_ITEMS, isItemVisible, visibleGroups, type Visibility } from "./menu";

const ADMIN: Visibility = { isAdmin: true, canViewMacd: true, isGlobal: false };
const USER: Visibility = { isAdmin: false, canViewMacd: false, isGlobal: false };
const MACD_VIEWER: Visibility = { isAdmin: false, canViewMacd: true, isGlobal: false };

const allItems = MENU_GROUPS.flatMap((g) => g.items);
const hrefs = allItems.map((i) => i.href);

describe("menu — kapsam", () => {
  it("menüde aynı href iki kez geçmez", () => {
    const dupes = hrefs.filter((h, i) => hrefs.indexOf(h) !== i);
    expect(dupes).toEqual([]);
  });

  it("her grup etiketli ve en az bir öğesi var", () => {
    for (const group of MENU_GROUPS) {
      expect(group.label.length).toBeGreaterThan(0);
      expect(group.id.length).toBeGreaterThan(0);
    }
  });

  it("2026-09-26: menüden linki olmayan sayfa KALMAMIŞ olmalı", () => {
    // Bu liste, menüye eklenmeden önce HİÇBİR navigasyon yüzeyinden
    // erişilemeyen sayfalardı. Yeni bir sayfa eklenirse ya buraya ya da
    // menüye girmek zorunda — sessizce erişilemez kalmak yasak.
    //
    // 2026-09-27: `/history` ve `/reports/forecasts` LİSTEDEN ÇIKARILDI.
    // `db8591d` (Tur A temizlik) bu iki sayfayı SİLDİ; tahmin raporu
    // `reports/page.tsx` içine sekme olarak taşındı. Menüde kalsalar
    // 404'e bağlantı verirdi — uygulama çalışırken yanlış yere götürür,
    // sessiz bozulmanın en ucuz görünen ama en sinir bozan türü.
    //
    // 2026-09-27: `/risk`, `/alerts`, `/memory`, `/trade-repair` de
    // LİSTEDEN ÇIKARILDI — menü yeniden yapılandırması: risk/alarm/
    // hafıza Yönetim Merkezi'ne sekme taşındı (/admin?tab=…), Trade
    // Repair sayfası silindi. Artık bu routeların menü linki OLMAMALI
    // (aşağıdaki "SİLİNMİŞ / TAŞINMIŞ" testinin kapsamında).
    //
    // 2026-09-27: `/symbol-analysis` de LİSTEDEN ÇIKARILDI — kullanıcı
    // isteği: menüden kalktı, Grafik sayfasındaki 🔬 ANALİZ butonunun
    // açtığı modala taşındı (charts/page.tsx iframe).
    const ORPHANS: string[] = [];
    for (const route of ORPHANS) {
      expect(hrefs).toContain(route);
    }
  });

  it("öksüz kopyalar menüye GİRMEZ", () => {
    // `/gainer-radar` yalnız `redirect("/")` yapan ölü bir alias'tır —
    // menüde yeri yoktur, tıklamak boş yere bir yönlendirme yapar.
    expect(hrefs).not.toContain("/gainer-radar");
  });

  it("2026-09-27: SİLİNMİŞ sayfalar menüde KALMAZ (db8591d temizliği)", () => {
    // `db8591d` bu dosyaları sildi. Menüde kalırlarsa bağlantı 404'e gider.
    // Test, menü ile dosya sistemini birbirine bağlayan tek yerde — yeni bir
    // sayfa silinirse ya da menüye eklenirse burada görünür.
    //
    // 2026-09-27 menü yeniden yapılandırması — TAŞINAN / SİLİNEN routelar:
    //   `/risk`, `/alerts`, `/memory` → Yönetim Merkezi sekmeleri
    //   (/admin?tab=risk|alerts|memory). Ana menüde ayrı link istemniyor;
    //   `/trade-repair` → sayfa silindi (İşlem Onarımı);
    //   `/symbol-analysis` → Grafik sayfasındaki 🔬 ANALİZ modalına taşındı
    //   (menü linki yok, modaldan ulaşılır). Menüde kalırlarsa ana
    //   navigasyonda gereksiz/404'lük girdi olur.
    for (const dead of [
      "/history", "/reports/forecasts", "/gainer-radar",
      "/risk", "/alerts", "/memory", "/trade-repair",
      "/symbol-analysis",
    ]) {
      expect(hrefs).not.toContain(dead);
    }
  });
});

describe("menu — rol görünürlüğü", () => {
  const find = (href: string) => allItems.find((i) => i.href === href)!;

  it("adminOnly öğeler yalnız admin'e görünür", () => {
    for (const item of allItems.filter((i) => i.adminOnly)) {
      expect(isItemVisible(item, ADMIN)).toBe(true);
      expect(isItemVisible(item, USER)).toBe(false);
    }
  });

  it("requiresStaff: admin VEYA MACD yetkilisi", () => {
    const admin = find("/admin");
    expect(isItemVisible(admin, ADMIN)).toBe(true);
    expect(isItemVisible(admin, MACD_VIEWER)).toBe(true);
    expect(isItemVisible(admin, USER)).toBe(false);
  });

  it("normal kullanıcı menüyü boş görmez", () => {
    const groups = visibleGroups(USER);
    expect(groups.length).toBeGreaterThan(0);
    expect(groups.flatMap((g) => g.items).length).toBeGreaterThan(5);
  });

  it("normal kullanıcıda Yönetim grubu tamamen gizlenir", () => {
    // collapseWhenEmpty: grup dolu değilse hiç başlık bile basılmaz.
    const groups = visibleGroups(USER);
    expect(groups.find((g) => g.id === "yonetim")).toBeUndefined();
    expect(groups.find((g) => g.id === "yonetim")?.items.length ?? 0).toBe(0);
  });
});

describe("menu — borsa görünürlüğü", () => {
  const globalVis: Visibility = { ...ADMIN, isGlobal: true };

  it("özel terminal İKİ borsada da görünür", () => {
    // 2026-09-27: `/binance-tr` Global'da da açılır — Global için ayrı bir
    // özel terminal eklendi. Önceden `trOnly: true` idi ve Global
    // kullanıcısının menüde hiçbir özel terminali yoktu.
    const item = allItems.find((i) => i.href === "/binance-tr")!;
    expect(item.trOnly).toBeUndefined();
    expect(isItemVisible(item, globalVis)).toBe(true);
    expect(isItemVisible(item, ADMIN)).toBe(true);
  });

  it("terminal etiketi çalışan borsanın adını taşır (sabit metin yok)", () => {
    // Sabit "Binance TR" yazısı Global kullanıcısına yanlış borsayı gösterirdi.
    const item = allItems.find((i) => i.href === "/binance-tr")!;
    expect(item.exchangeLabel).toBe(true);
  });

  it("TR örneğinde Global'a özel hiçbir öğe görünmez", () => {
    const flat = visibleGroups(ADMIN).flatMap((g) => g.items);
    expect(flat.filter((i) => i.globalOnly)).toEqual([]);
  });
});

describe("menu — mobil alt navigasyon", () => {
  it("4 öğe + menü düğmesi mobilde sığar", () => {
    expect(BOTTOM_NAV_ITEMS.length).toBe(4);
  });

  it("alt navigasyon private API'ye bağlı sayfaya gitmez", () => {
    // 2026-09-26: alt navigasyon mobilde 4. öğe olarak `/binance-tr`
    // gösteriyordu. 2026-09-27'de terminal iki borsada da çalışır hâle
    // geldiği için bu kural HER iki borsada da geçerli: alt navigasyon
    // private yüzeye bağlı sayfaya gitmez, oraya menüden gidilir.
    const flat = BOTTOM_NAV_ITEMS.map((i) => i.href);
    expect(flat).not.toContain("/binance-tr");
    for (const item of BOTTOM_NAV_ITEMS) {
      expect(item.trOnly).toBeUndefined();
      expect(item.globalOnly).toBeUndefined();
    }
  });

  it("alt navigasyon öğeleri menüde de var", () => {
    for (const item of BOTTOM_NAV_ITEMS) {
      expect(hrefs).toContain(item.href);
    }
  });
});
