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
  // 2026-09-27: Gruplamalar kaldırıldı. `ana` düz listedir (Sidebar'da
  // başlık/chevron GÖSTERİLMEZ — kullanıcı isteği: "gruplamayı kaldır").
  // Sıralama kullanıcının önerdiği öncelik sırasıdır.
  {
    id: "ana",
    label: "Ana",
    items: [
      { href: "/monitoring", label: "Radar", icon: "📡", desc: "Otonom izleme ve hız avcısı" },
      { href: "/mtf-scanner", label: "MTF Tarama", icon: "🧠", desc: "MACD & Signal MTF canlı tarayıcı" },
      { href: "/technical-charts", label: "Teknik Grafik", icon: "🖥️", desc: "4'lü çoklu TradingView ekranı" },
      { href: "/charts", label: "Grafik", icon: "📈", desc: "Mum grafikleri" },
      { href: "/binance-tr", label: "Binance", icon: "🏛️", desc: "Kendi hesabında canlı işlem", exchangeLabel: true },
      { href: "/portfolio", label: "Sanal Portföy", icon: "💼", desc: "Canlı sanal portföy ve otonom işlemler" },
      { href: "/chat", label: "Chat", icon: "💬", desc: "Uzman trader LLM asistanı" },
      { href: "/settings", label: "Ayarlar", icon: "⚙️", desc: "Bot konfigürasyonu", adminOnly: true },
      { href: "/reports", label: "Raporlar", icon: "📋", desc: "Sinyal ve işlem raporları" },
    ],
  },
  // `diger`: kullanıcı isteği — sık kullanılanlar dışındakiler tek, varsayılan
  // kapalı bölümde. `/admin` Yönetim Merkezi'ne, `/profile` Ayarlar'a sekme
  // olarak taşındığı için ana listede yerleri yok; routelar CANLI kalır.
  {
    id: "diger",
    label: "Diğer",
    collapseWhenEmpty: true,
    items: [
      { href: "/", label: "Canlı Terminal", icon: "🖥️", desc: "Canlı pano ve son aktivite" },
      { href: "/system-health", label: "Sistem Sağlığı", icon: "🩺", desc: "Detaylı sistem sağlığı" },
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
