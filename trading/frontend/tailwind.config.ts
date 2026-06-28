import type { Config } from "tailwindcss";

export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        border: "hsl(var(--border))",
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        muted: { DEFAULT: "hsl(var(--muted))", foreground: "hsl(var(--muted-foreground))" },
        primary: { DEFAULT: "hsl(var(--primary))", foreground: "hsl(var(--primary-foreground))" },
        destructive: { DEFAULT: "hsl(var(--destructive))", foreground: "hsl(var(--destructive-foreground))" },
        card: { DEFAULT: "hsl(var(--card))", foreground: "hsl(var(--card-foreground))" },
        success: "hsl(var(--success))",
        danger: "hsl(var(--danger))",
        warning: "hsl(var(--warning))",
        info: "hsl(var(--info))",

        /* Trading-specific palette — direct hex so we can match
           Bloomberg/3Commas greens and reds exactly without HSL churn. */
        bull: {
          DEFAULT: "#22c55e",
          dim: "rgba(34, 197, 94, 0.18)",
          text: "#4ade80",
          glow: "rgba(34, 197, 94, 0.35)",
        },
        bear: {
          DEFAULT: "#ef4444",
          dim: "rgba(239, 68, 68, 0.18)",
          text: "#f87171",
          glow: "rgba(239, 68, 68, 0.35)",
        },
        warn: {
          DEFAULT: "#eab308",
          dim: "rgba(234, 179, 8, 0.18)",
          text: "#facc15",
        },
        term: {
          bg: "#0D1117",        /* terminal base */
          surface: "#11161D",   /* surface-1 */
          surface2: "#161C24",  /* surface-2 (cards) */
          border: "#222B36",    /* surface-3 */
          grid: "#1A2230",
          ink: "#E6EDF3",
          muted: "#7D8590",
        },

        /* Trading Command Center palette — exposed as utility classes
           (bg-ttcc-bg, border-ttcc-border, text-ttcc-green, ...). */
        ttcc: {
          bg: "#0D1117",
          surface: "#161B22",
          "surface-2": "#21262D",
          border: "#30363D",
          text: "#E6EDF3",
          "text-secondary": "#8B949E",
          "text-muted": "#484F58",
          green: "#3FB950",
          red: "#F85149",
          yellow: "#D29922",
          blue: "#58A6FF",
          accent: "#7C5CFC",
        },
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "monospace"],
      },
      borderRadius: { lg: "var(--radius)", md: "calc(var(--radius) - 2px)", sm: "calc(var(--radius) - 4px)" },
      fontSize: {
        "2xs": ["10px", { lineHeight: "12px" }],
        "3xs": ["9px", { lineHeight: "11px" }],
      },
      gridTemplateColumns: {
        "tt-pos": "repeat(auto-fill, minmax(260px, 1fr))",
      },
      keyframes: {
        "pnl-up": {
          "0%":   { backgroundColor: "rgba(34, 197, 94, 0.22)" },
          "100%": { backgroundColor: "rgba(34, 197, 94, 0)" },
        },
        "pnl-down": {
          "0%":   { backgroundColor: "rgba(239, 68, 68, 0.22)" },
          "100%": { backgroundColor: "rgba(239, 68, 68, 0)" },
        },
      },
      animation: {
        "pnl-up": "pnl-up 500ms ease-out",
        "pnl-down": "pnl-down 500ms ease-out",
      },
    },
  },
  plugins: [require("@tailwindcss/typography")],
} satisfies Config;
