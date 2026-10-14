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
    // /metamobil, 2026-10-07 birleşik menüde MetaTrader mobil kopyası olarak
    // eklendi (menu.ts); test bu rotayı tanımıyordu ve zincirleme bayattı.
    const ALLOWED = ["/", "/forex", "/chat", "/settings", "/metamobil"];
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
      "/metamobil",
      "/forex/btc-gold",
      "/forex",
      "/forex/charts",
      "/chat",
      "/forex/islemler",
      "/forex/reports",
      "/settings",
    ];
    expect(items).toEqual(expectedOrder);
  });

  it("2026-10-14: Grafik ve Teknik Grafik TEK menü öğesinde birleşti", () => {
    // Kullanıcı iki ayrı grafik sayfasının tek sayfada birleşmesini istedi;
    // menüde tek "Grafik" girişi kalır, eski rota `alsoActive` ile aynı
    // sayfayı aydınlatır (link kırılmaz, ama ikinci bir satır açılmaz).
    expect(hrefs).toContain("/forex/charts");
    expect(hrefs).not.toContain("/forex/technical-charts");
    const grafik = allItems.find((i) => i.href === "/forex/charts");
    expect(grafik?.alsoActive ?? []).toContain("/forex/technical-charts");
  });

  it("2026-10-13: Forex İşlemler kendi menü öğesidir (Raporlar'a gizlenmez)", () => {
    const islemler = allItems.find((i) => i.href === "/forex/islemler");
    expect(islemler).toBeDefined();
    const reports = allItems.find((i) => i.href === "/forex/reports");
    // Eski hâlde /forex/islemler yalnız `alsoActive` ile Raporlar'a bağlıydı;
    // kullanıcı onu ayrı bir giriş olarak istedi.
    expect(reports?.alsoActive ?? []).not.toContain("/forex/islemler");
  });
});

describe("menu — mobil alt navigasyon", () => {
  it("5 öğe + menü düğmesi mobilde sığar", () => {
    expect(BOTTOM_NAV_ITEMS.length).toBe(5);
  });

  it("alt navigasyon öğeleri menüde de var", () => {
    for (const item of BOTTOM_NAV_ITEMS) {
      expect(hrefs).toContain(item.href);
    }
  });
});
