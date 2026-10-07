// Menü görünürlük kuralları — 2026-10-07 (FOREX-ONLY yeniden yapılandırma)
//
// Uygulama artık YALNIZCA Forex & Emtia sunar; kripto spot menüsü, piyasa-modu
// anahtarı ve borsa-bazlı görünürlük (`trOnly`/`globalOnly`/`isGlobal`) kaldırıldı.
// Bu kilit üç sınıf hatayı önler:
//
// 1. ERİŞİLEMEZLİK. Her Forex sayfasının bir menü linki olmalı.
// 2. ÖLÜ LİNK. Silinen spot sayfaların href'i menüde KALMAMALI (404'e giderdi).
// 3. YANLIŞ YÜZEY. Mobil alt navigasyon yalnızca var olan Forex rotalarına gider.

import { describe, it, expect } from "vitest";
import { MENU_GROUPS, BOTTOM_NAV_ITEMS, isItemVisible, visibleGroups, type Visibility } from "./menu";

const ADMIN: Visibility = { isAdmin: true };
const USER: Visibility = { isAdmin: false };

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

  it("2026-10-07: TÜM menü öğeleri Forex rotalarına gider (tek piyasa)", () => {
    // Uygulama forex-only olduğu için menüdeki her href `/forex`, `/chat`,
    // `/settings` ya da `/system-health` olmalı. Bir spot rotası sızarsa
    // (ör. /monitoring) kullanıcı 404'e gider — bu test onu yakalar.
    const ALLOWED = ["/forex", "/chat", "/settings", "/system-health"];
    for (const href of hrefs) {
      expect(ALLOWED.some((p) => href === p || href.startsWith(p + "/"))).toBe(true);
    }
  });

  it("2026-10-07: SİLİNMİŞ spot sayfalar menüde KALMAZ", () => {
    // Spot UI + sayfa dosyaları kaldırıldı; menüde kalsalardı bağlantı 404'e
    // giderdi — sessiz bozulmanın en sinir bozucu türü.
    for (const dead of [
      "/", "/monitoring", "/mtf-scanner", "/technical-charts", "/charts",
      "/binance-tr", "/portfolio", "/reports", "/alerts", "/risk",
      "/macd-monitor", "/symbol-analysis", "/database", "/memory", "/admin",
      "/users", "/profile",
    ]) {
      expect(hrefs).not.toContain(dead);
    }
  });
});

describe("menu — rol görünürlüğü", () => {
  it("adminOnly öğeler yalnız admin'e görünür", () => {
    for (const item of allItems.filter((i) => i.adminOnly)) {
      expect(isItemVisible(item, ADMIN)).toBe(true);
      expect(isItemVisible(item, USER)).toBe(false);
    }
  });

  it("normal kullanıcı menüyü boş görmez", () => {
    const groups = visibleGroups(USER);
    expect(groups.length).toBeGreaterThan(0);
    expect(groups.flatMap((g) => g.items).length).toBeGreaterThan(3);
  });

  it("normal kullanıcıda 'diger' grubu Sistem Sağlığı ile kalır", () => {
    const groups = visibleGroups(USER);
    const diger = groups.find((g) => g.id === "diger");
    expect(diger).toBeDefined();
    expect(diger!.items.map((i) => i.href)).toContain("/system-health");
    // Ayarlar adminOnly → normal kullanıcıya görünmez.
    expect(diger!.items.map((i) => i.href)).not.toContain("/settings");
  });

  it("Forex & Emtia grubu tüm forex sayfalarını listeler", () => {
    const groups = visibleGroups(ADMIN);
    const forex = groups.find((g) => g.id === "forex_ana");
    expect(forex).toBeDefined();
    const items = forex!.items.map((i) => i.href);
    for (const href of ["/forex", "/forex/btc-gold", "/forex/islemler", "/forex/charts", "/forex/calendar", "/forex/portfolio", "/forex/ayarlar"]) {
      expect(items).toContain(href);
    }
  });
});

describe("menu — mobil alt navigasyon", () => {
  it("4 öğe + menü düğmesi mobilde sığar", () => {
    expect(BOTTOM_NAV_ITEMS.length).toBe(4);
  });

  it("alt navigasyon yalnız Forex rotalarına gider", () => {
    for (const item of BOTTOM_NAV_ITEMS) {
      expect(item.href.startsWith("/forex")).toBe(true);
    }
  });

  it("alt navigasyon öğeleri menüde de var", () => {
    for (const item of BOTTOM_NAV_ITEMS) {
      expect(hrefs).toContain(item.href);
    }
  });
});
