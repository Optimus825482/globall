// Menü tanımı — TEK kaynak. `Sidebar` (masaüstü) ve `BottomNav` (mobil)
// aynı listeyi okur; iki yüzey birbirinden ayrışamaz.
//
// 2026-10-07: SPOT PİYASA MENÜSÜ KALDIRILDI. Bu uygulama artık YALNIZCA
// Forex & Emtia sunar; kripto spot sayfaları (Radar, MTF, Grafik, Binance
// terminali, Sanal Portföy, Raporlar…) silindi. Menüde tek bir piyasa
// vardır, dolayısıyla piyasa-modu anahtarı da (spot/forex) yoktur.
//
// GRUP KURALLARI (niyet kodun kendisinde):
// - `adminOnly`  : yalnız admin (Ayarlar)
//
// Erişim AÇMAK erişim vermek DEĞİLDİR: `RequireAdmin` gibi sayfa-içi
// korumalar ayrıdır ve bu dosya yalnız menüde görünürlüğü yönetir.

export type MenuItem = {
  href: string;
  label: string;
  icon: string;
  desc: string;
  adminOnly?: boolean;
  /** Menüde görünür ama aktif sayfa eşleşmesi bu yol listesine bakar. */
  alsoActive?: string[];
};

export type MenuGroup = {
  id: string;
  label: string;
  items: MenuItem[];
  /** Bu gruptaki tüm öğeler admin ise gruba girilmeden gizlenir. */
  collapseWhenEmpty?: boolean;
};

export const MENU_GROUPS: MenuGroup[] = [
  {
    id: "forex_ana",
    label: "Forex & Emtia",
    items: [
      { href: "/forex/btc-gold", label: "BTC + Altın", icon: "🥇", desc: "Yalnız XAUUSD & BTCUSD otonom scalper konsolu" },
      { href: "/forex", label: "Forex Radar", icon: "📡", desc: "Majör pariteler ve emtia takibi" },
      { href: "/forex/islemler", label: "Canlı İşlemler", icon: "⚡", desc: "Açık ve kapanan Forex pozisyonları, anlık PnL ve başarı oranı" },
      { href: "/forex/technical-charts", label: "Teknik Grafik", icon: "🖥️", desc: "4'lü çoklu Forex ekranı" },
      { href: "/forex/charts", label: "Grafik", icon: "📈", desc: "Tekli detaylı parite grafiği" },
      { href: "/forex/calendar", label: "Ekonomik Takvim", icon: "📅", desc: "Canlı makroekonomik veriler ve haberler" },
      { href: "/forex/portfolio", label: "Forex Portföy", icon: "💼", desc: "Lot ve Pip bazlı demo hesap yönetimi" },
      { href: "/forex/ayarlar", label: "Ayarlar", icon: "⚙️", desc: "Otonom scalping risk, çıkış ve sembol parametreleri" },
      { href: "/chat", label: "Forex Chat", icon: "💬", desc: "Makroekonomi ve FX uzman AI asistanı" },
    ],
  },
  {
    id: "diger",
    label: "Diğer",
    collapseWhenEmpty: true,
    items: [
      { href: "/system-health", label: "Sistem Sağlığı", icon: "🩺", desc: "Detaylı sistem sağlığı" },
      { href: "/settings", label: "Ayarlar", icon: "⚙️", desc: "Sistem konfigürasyonu", adminOnly: true },
    ],
  },
];

/**
 * Mobil alt navigasyon — en sık kullanılan 4 iş + menü düğmesi.
 * Masaüstü menüsünün kısaltması değil, AYRI bir yüzeydir: mobilde 4 öğe
 * sığar, 20 öğe sığmaz.
 */
export const BOTTOM_NAV_ITEMS: MenuItem[] = [
  { href: "/forex/portfolio", label: "Portföy", icon: "💼", desc: "" },
  { href: "/forex", label: "Forex Radar", icon: "📡", desc: "" },
  { href: "/forex/charts", label: "Grafik", icon: "📈", desc: "" },
  { href: "/forex/calendar", label: "Takvim", icon: "📅", desc: "" },
];

export type Visibility = {
  isAdmin: boolean;
};

export function isItemVisible(item: MenuItem, v: Visibility): boolean {
  if (item.adminOnly && !v.isAdmin) return false;
  return true;
}

export function visibleGroups(v: Visibility): MenuGroup[] {
  return MENU_GROUPS
    .map((group) => ({ ...group, items: group.items.filter((item) => isItemVisible(item, v)) }))
    .filter((group) => !group.collapseWhenEmpty || group.items.length > 0);
}
