import type { Config } from "tailwindcss";

export default {
  darkMode: "class",
  content: ["./app/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bunker: {
          950: "#070b14",
          900: "#0c1322",
          800: "#142036",
          700: "#1f3050",
          600: "#314a77",
          muted: "#93a7c6"
        },
        neon: {
          green: "#00f0ff",
          greenHover: "#38bdf8",
          red: "#ff3366",
          yellow: "#f0b90b",
          cyan: "#00f0ff",
          blue: "#38bdf8"
        },
        global: {
          cyan: "#00f0ff",
          sky: "#38bdf8",
          gold: "#f0b90b",
          dark: "#070b14"
        },
        surface: {
          primary: "#0c1322",
          secondary: "#142036",
          danger: "#350914",
          success: "#022938"
        }
      },
      fontFamily: {
        sans: ["var(--font-sans)", "ui-sans-serif", "system-ui", "sans-serif"],
        display: ["var(--font-display)", "var(--font-sans)", "sans-serif"],
        mono: ["var(--font-mono)", "ui-monospace", "SFMono-Regular", "Menlo", "monospace"]
      }
    }
  },
  plugins: [],
} satisfies Config;
