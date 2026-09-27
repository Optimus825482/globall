// Menü tanımı — TEK kaynak. `Sidebar` (masaüstü) ve `BottomNav` (mobil)
// aynı listeyi okur; iki yüzey birbirinden ayrışamaz.
//
// 2026-09-26: Menü düz bir liste idi ve 25 sayfanın YALNIZCA 10'u
// görünüyordu. Kalan 14 sayfa (işlem geçmişi, alarmlar, risk, sembol
// analizi, tahmin raporu, LLM hafızası…) çalışıyordu ama HİÇBİR
// navigasyon yüzeyinden linki yoktu — kullanıcı URL'yi bilmeden
// ulaşamıyordu. Gruplama hem erişimi açar hem de 14 öğelik düz listeyi
// okunur kılar.
//
// GRUP KURALLARI (niyet kodun kendisinde):
// - `adminOnly`  : yalnız admin (Ayarlar, Yönetim)
// - `requiresStaff`: admin VEYA MACD izleme yetkisi olan kullanıcı
// - `trOnly`     : yalnız Binance TR örneğinde görünür (private API)
// - `globalOnly` : yalnız Binance Global örneğinde görünür (private API)
//
// Erişim AÇMAK erişim vermek DEĞİLDİR: `RequireAdmin` gibi sayfa-içi
// korumalar ayrıdır ve bu dosya yalnız menüde görünürlüğü yönetir.

export type MenuItem = {
  href: string;
  label: string;
  icon: string;
  desc: string;
  adminOnly?: boolean;
  requiresStaff?: boolean;
  /** Yalnız Binance TR örneğinde görünür (private API `api.binance.me`). */
  trOnly?: boolean;
  /** Yalnız Binance Global örneğinde görünür (private API `api.binance.com`). */
  globalOnly?: boolean;
  /**
   * Etiketi çalışan borsanın adıyla göster: TR örneğinde "Binance TR",
   * Global örneğinde "Binance Global". Sabit metin kalmış olsaydı Global
   * kullanıcısı kendi sayfasında "Binance TR" görürdü.
   */
  exchangeLabel?: boolean;
  /** Menüde görünür ama aktif sayfa eşleşmesi bu yol listesine bakar. */
  alsoActive?: string[];
};

export type MenuGroup = {
  id: string;
  label: string;
  items: MenuItem[];
  /** Bu gruptaki tüm öğeler admin/staff ise gruba girilmeden gizlenir. */
  collapseWhenEmpty?: boolean;
};

export const MENU_GROUPS: MenuGroup[] = [
  {
    id: "pano",
    label: "Pano",
    items: [
      { href: "/", label: "Canlı Terminal", icon: "🖥️", desc: "Canlı pano ve son aktivite" },
      { href: "/portfolio", label: "Sanal Portföy", icon: "💼", desc: "Canlı sanal portföy ve otonom işlemler" },
      { href: "/monitoring", label: "Radar", icon: "📡", desc: "Otonom izleme ve hız avcısı" },
    ],
  },
  {
    id: "analiz",
    label: "Analiz",
    items: [
      { href: "/charts", label: "Grafik", icon: "📈", desc: "Mum grafikleri" },
      { href: "/technical-charts", label: "Teknik Grafik", icon: "🖥️", desc: "4'lü çoklu TradingView ekranı", adminOnly: true },
      { href: "/chat", label: "Chat", icon: "💬", desc: "Uzman trader LLM asistanı" },
    ],
  },
  {
    id: "islem",
    label: "İşlem",
    items: [
      { href: "/binance-tr", label: "Binance", icon: "🏛️", desc: "Kendi hesabında canlı işlem", exchangeLabel: true },
      { href: "/reports", label: "Raporlar", icon: "📋", desc: "Sinyal ve işlem raporları" },
      { href: "/settings", label: "Ayarlar", icon: "⚙️", desc: "Bot konfigürasyonu", adminOnly: true },
      { href: "/profile", label: "Profil", icon: "👤", desc: "Hesap ve şifre" },
    ],
  },
  {
    id: "yonetim",
    label: "Yönetim",
    collapseWhenEmpty: true,
    items: [
      { href: "/admin", label: "Yönetim Merkezi", icon: "🛠️", desc: "Veritabanı, kayıtlar, MACD monitör", requiresStaff: true,
        alsoActive: ["/database", "/audit-logs", "/macd-monitor", "/users"] },
    ],
  },
];

/**
 * Mobil alt navigasyon — en sık kullanılan 4 iş + menü düğmesi.
 * Masaüstü menüsünün kısaltması değil, AYRI bir yüzeydir: mobilde 4 öğe
 * sığar, 20 öğe sığmaz.
 */
export const BOTTOM_NAV_ITEMS: MenuItem[] = [
  { href: "/portfolio", label: "Portföy", icon: "💼", desc: "" },
  { href: "/monitoring", label: "Radar", icon: "📡", desc: "" },
  { href: "/charts", label: "Grafik", icon: "📈", desc: "" },
  { href: "/reports", label: "Raporlar", icon: "📋", desc: "" },
];

export type Visibility = {
  isAdmin: boolean;
  canViewMacd: boolean;
  isGlobal: boolean;
};

export function isItemVisible(item: MenuItem, v: Visibility): boolean {
  if (item.adminOnly && !v.isAdmin) return false;
  if (item.requiresStaff && !(v.isAdmin || v.canViewMacd)) return false;
  if (item.trOnly && v.isGlobal) return false;
  if (item.globalOnly && !v.isGlobal) return false;
  return true;
}

export function visibleGroups(v: Visibility): MenuGroup[] {
  return MENU_GROUPS
    .map((group) => ({ ...group, items: group.items.filter((item) => isItemVisible(item, v)) }))
    .filter((group) => !group.collapseWhenEmpty || group.items.length > 0);
}
