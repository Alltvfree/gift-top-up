import type { Config } from "tailwindcss";

/**
 * Tilly Trading operator-console design system.
 * Terminal amber on deep ink — all colors are tokens, never hardcode in components.
 */
const config: Config = {
  darkMode: ["class"],
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#070b11",
        surface: "#0e1420",
        panel: "#121a28",
        panel2: "#16202f",
        line: "#26344a",
        amber: "#ffb020",
        amber2: "#ffd06b",
        up: "#34d399",
        down: "#fb5d5d",
        muted: "#6f8098",
        fg: "#e2e8f0",
      },
      fontFamily: {
        display: ["var(--font-display)", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["var(--font-mono)", "ui-monospace", "monospace"],
      },
      keyframes: {
        flick: {
          "0%,100%": { opacity: "1" },
          "50%": { opacity: "0.35" },
        },
        pulsering: {
          "0%,100%": { boxShadow: "0 0 0 0 rgba(255,176,32,0.55)" },
          "70%": { boxShadow: "0 0 0 5px rgba(255,176,32,0)" },
        },
        sweep: {
          "0%": { transform: "translateX(-120%)" },
          "100%": { transform: "translateX(360%)" },
        },
      },
      animation: {
        "tick-live": "flick 1.4s ease-in-out infinite",
        "pulse-dot": "pulsering 1.8s ease-out infinite",
        sweep: "sweep 3.2s linear infinite",
      },
    },
  },
  plugins: [require("tailwindcss-animate")],
};

export default config;
