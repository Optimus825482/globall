// ============================================================================
// UYGULAMA İÇİ BİLDİRİM AYARLARI (Radar & Sinyal Popupları)
// ============================================================================

export interface InAppNotificationSettings {
  enabled: boolean;
  soundEnabled: boolean;
  autoCloseSec: number; // 0 = kapanmaz (manuel), 10, 20, 30 sn
}

const STORAGE_KEY = "scalper_in_app_notifications_v1";

export const DEFAULT_IN_APP_SETTINGS: InAppNotificationSettings = {
  enabled: true,
  soundEnabled: true,
  autoCloseSec: 20,
};

export function getInAppNotificationSettings(): InAppNotificationSettings {
  if (typeof window === "undefined") return DEFAULT_IN_APP_SETTINGS;
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULT_IN_APP_SETTINGS;
    const parsed = JSON.parse(raw);
    return {
      enabled: typeof parsed.enabled === "boolean" ? parsed.enabled : true,
      soundEnabled: typeof parsed.soundEnabled === "boolean" ? parsed.soundEnabled : true,
      autoCloseSec: typeof parsed.autoCloseSec === "number" ? parsed.autoCloseSec : 20,
    };
  } catch {
    return DEFAULT_IN_APP_SETTINGS;
  }
}

export function saveInAppNotificationSettings(settings: InAppNotificationSettings): void {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
    window.dispatchEvent(new CustomEvent("scalper_in_app_settings_changed", { detail: settings }));
  } catch (err) {
    console.error("Bildirim ayarları kaydedilemedi:", err);
  }
}

export function triggerTestInAppNotification(): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent("scalper_test_radar_modal"));
}
