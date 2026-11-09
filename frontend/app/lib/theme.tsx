"use client";

import React, { createContext, useContext, useEffect, useState, useCallback } from "react";

export type Theme = "dark" | "light";

interface ThemeContextType {
  theme: Theme;
  isLight: boolean;
  isDark: boolean;
  toggleTheme: () => void;
  setTheme: (theme: Theme) => void;
}

const ThemeContext = createContext<ThemeContextType>({
  // Varsayılan AÇIK TEMA (Erkan kararı, 2026-11-09). `layout.tsx`'teki
  // başlangıç sınıfı ve FOUC script'i ile AYNI olmalı.
  theme: "light",
  isLight: true,
  isDark: false,
  toggleTheme: () => {},
  setTheme: () => {},
});

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [theme, setThemeState] = useState<Theme>("light");

  const applyTheme = useCallback((newTheme: Theme) => {
    if (typeof document !== "undefined") {
      const root = document.documentElement;
      // Tarayıcı/OS çubuğu rengini temayla eşle. `viewport.themeColor` tek
      // (açık) değer bildiriyor; kullanıcı Karanlık'a geçtiğinde meta'yı
      // burada güncellemezsek çubuk açık kalır ve sayfayla çelişir.
      const meta = document.querySelector('meta[name="theme-color"]');
      if (meta) meta.setAttribute("content", newTheme === "light" ? "#f8fafc" : "#070b14");
      if (newTheme === "light") {
        root.classList.remove("dark");
        root.classList.add("light");
        root.setAttribute("data-theme", "light");
        root.style.colorScheme = "light";
      } else {
        root.classList.remove("light");
        root.classList.add("dark");
        root.setAttribute("data-theme", "dark");
        root.style.colorScheme = "dark";
      }
    }
  }, []);

  useEffect(() => {
    try {
      const stored = localStorage.getItem("theme") || localStorage.getItem("forex_theme_preference");
      if (stored === "light" || stored === "dark") {
        setThemeState(stored as Theme);
        applyTheme(stored as Theme);
      } else {
        // 2026-11-09: Depolanmış tercih yoksa VARSAYILAN AÇIK TEMA'dır
        // (Erkan kararı). İşletim sistemi tercihi artık belirleyici DEĞİL:
        // önceki turda `prefers-color-scheme` okunuyordu ve OS'u koyu olan
        // kullanıcı uygulamayı koyu açıyordu — istenen davranış bu değil.
        // `layout.tsx` içindeki FOUC önleyici senkron script ile aynı kural.
        setThemeState("light");
        applyTheme("light");
      }
    } catch {
      applyTheme("light");
    }
  }, [applyTheme]);

  const setTheme = useCallback(
    (newTheme: Theme) => {
      setThemeState(newTheme);
      applyTheme(newTheme);
      try {
        localStorage.setItem("theme", newTheme);
        localStorage.setItem("forex_theme_preference", newTheme);
      } catch {}
    },
    [applyTheme]
  );

  const toggleTheme = useCallback(() => {
    setTheme(theme === "dark" ? "light" : "dark");
  }, [theme, setTheme]);

  return (
    <ThemeContext.Provider
      value={{
        theme,
        isLight: theme === "light",
        isDark: theme === "dark",
        toggleTheme,
        setTheme,
      }}
    >
      {children}
    </ThemeContext.Provider>
  );
}

export function useTheme() {
  return useContext(ThemeContext);
}
