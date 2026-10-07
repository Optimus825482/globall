// Menü görünürlük kuralları — 2026-10-07 (FOREX-ONLY yeniden yapılandırma)
//
// 1. Ana sayfa (`/`) artık Günlük Forex İşlem Performansı konsoludur ve menünün en üstündedir.
// 2. Forex Portföy, BTC + Altın, Forex Radar, Grafik, Teknik Grafik, Forex Chat, Raporlar sıralıdır.
// 3. Ayarlar birleştirilmiş tek sayfadır (`/settings`), Sistem Sağlığı sekme olarak içine alınmıştır.
// 4. Silinen spot sayfaların href'i menüde bulunmaz.

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

  it("2026-10-07: TÜM menü öğeleri geçerli rotalara gider (tek piyasa Forex + Ana Sayfa)", () => {
    const ALLOWED = ["/", "/forex", "/chat", "/settings"];
    for (const href of hrefs) {
      expect(ALLOWED.some((p) => href === p || href.startsWith(p + "/"))).toBe(true);
    }
  });

  it("2026-10-07: SİLİNMİŞ spot sayfalar menüde KALMAZ", () => {
    for (const dead of [
      "/monitoring", "/mtf-scanner", "/binance-tr", "/alerts", "/risk",
      "/macd-monitor", "/symbol-analysis", "/database", "/memory", "/admin",
      "/users", "/profile",
    ]) {
      expect(hrefs).not.toContain(dead);
    }
  });

  it("Ana Sayfa (/) menünün en üstündedir", () => {
    expect(MENU_GROUPS[0].items[0].href).toBe("/");
    expect(MENU_GROUPS[0].items[0].label).toBe("Ana Sayfa");
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

  it("kullanıcı istediği sıralamada Forex sayfalarını listeler", () => {
    const groups = visibleGroups(ADMIN);
    const forex = groups.find((g) => g.id === "forex_ana");
    expect(forex).toBeDefined();
    const items = forex!.items.map((i) => i.href);
    const expectedOrder = [
      "/",
      "/forex/portfolio",
      "/forex/btc-gold",
      "/forex",
      "/forex/charts",
      "/forex/technical-charts",
      "/chat",
      "/forex/reports",
      "/settings",
    ];
    expect(items).toEqual(expectedOrder);
  });
});

describe("menu — mobil alt navigasyon", () => {
  it("4 öğe + menü düğmesi mobilde sığar", () => {
    expect(BOTTOM_NAV_ITEMS.length).toBe(4);
  });

  it("alt navigasyon öğeleri menüde de var", () => {
    for (const item of BOTTOM_NAV_ITEMS) {
      expect(hrefs).toContain(item.href);
    }
  });
});
