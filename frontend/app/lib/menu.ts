// Menü tanımı — TEK kaynak. `Sidebar` (masaüstü) ve `BottomNav` (mobil)
// aynı listeyi okur; iki yüzey birbirinden ayrışamaz.
//
// 2026-10-07: FOREX-ONLY BİRLEŞİK MENÜ
// Kullanıcı istekleri doğrultusunda sıralama:
// 1. Ana Sayfa (Uygulama girişi: Günlük Forex işlemleri başarısı & kârlılığı)
// 2. Forex Portföy
// 3. BTC + Altın
// 4. Forex Radar
// 5. Grafik
// 6. Teknik Grafik
// 7. Forex Chat
// 8. Raporlar
// 9. Ayarlar (Forex Scalper ayarları, Sistem Sağlığı, Uygulama vb. tek yerde birleştirildi)

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
      { href: "/", label: "Ana Sayfa", icon: "🏠", desc: "Günün Forex işlem karnesi, başarı oranı ve kârlılık özeti" },
      { href: "/forex/portfolio", label: "Forex Portföy", icon: "💼", desc: "Lot ve Pip bazlı hesap yönetimi" },
      { href: "/metamobil", label: "MetaMobil", icon: "📱", desc: "MetaTrader 5 mobil arayüz kopyası (Kotasyonlar, Grafik, Ticaret & Geçmiş)", alsoActive: ["/forex/metamobil"] },
      { href: "/forex/btc-gold", label: "BTC + Altın", icon: "🥇", desc: "Yalnız XAUUSD & BTCUSD otonom scalper konsolu" },
      { href: "/forex", label: "Forex Radar", icon: "📡", desc: "Majör pariteler ve emtia takibi" },
      { href: "/forex/charts", label: "Grafik", icon: "📈", desc: "Tekli detaylı parite grafiği", alsoActive: ["/charts"] },
      { href: "/forex/technical-charts", label: "Teknik Grafik", icon: "🖥️", desc: "4'lü çoklu Forex ekranı", alsoActive: ["/technical-charts"] },
      { href: "/chat", label: "Forex Chat", icon: "💬", desc: "Makroekonomi ve FX uzman AI asistanı" },
      { href: "/forex/reports", label: "Raporlar", icon: "📋", desc: "Detaylı işlem geçmişi ve analiz raporları", alsoActive: ["/forex/islemler"] },
      { href: "/settings", label: "Ayarlar", icon: "⚙️", desc: "Forex motor parametreleri, sistem sağlığı ve konfigürasyon", adminOnly: true, alsoActive: ["/forex/ayarlar", "/system-health"] },
    ],
  },
];

/**
 * Mobil alt navigasyon — en sık kullanılan 4 iş.
 */
export const BOTTOM_NAV_ITEMS: MenuItem[] = [
  { href: "/", label: "Ana Sayfa", icon: "🏠", desc: "" },
  { href: "/metamobil", label: "MetaMobil", icon: "📱", desc: "" },
  { href: "/forex/portfolio", label: "Portföy", icon: "💼", desc: "" },
  { href: "/forex", label: "Radar", icon: "📡", desc: "" },
  { href: "/forex/charts", label: "Grafik", icon: "📈", desc: "" },
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
