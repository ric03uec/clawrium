import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        primary: {
          DEFAULT: "var(--primary)",
          foreground: "var(--primary-text-color)",
          hover: "var(--blue-600)",
          light: "var(--blue-cyan)",
          bg: "var(--accent)",
          wash: "var(--accent)",
        },
        accent: {
          DEFAULT: "var(--primary)",
          foreground: "var(--primary-foreground)",
          soft: "var(--accent)",
        },
        page: "var(--background)",
        panel: "var(--surface-raised)",
        surface: "var(--accent)",
        elevated: "var(--surface-card)",
        "primary-text": "var(--foreground)",
        secondary: "var(--muted-foreground)",
        muted: "var(--muted-foreground)",
        "status-running": {
          DEFAULT: "var(--success)",
          text: "var(--success-text)",
        },
        "status-warning": {
          DEFAULT: "var(--status-warning)",
          text: "var(--warning-text)",
        },
        "status-error": "var(--destructive)",
        "status-info": "var(--blue-500)",
      },
      borderColor: {
        default: "var(--border)",
        subtle: "var(--border)",
      },
      fontFamily: {
        sans: ["var(--font-sans)"],
        serif: ["var(--font-serif)"],
        mono: ["var(--font-mono)"],
      },
      borderRadius: {
        sm: "calc(var(--radius) - 6px)",
        DEFAULT: "calc(var(--radius) - 4px)",
        md: "calc(var(--radius) - 4px)",
        lg: "calc(var(--radius) - 2px)",
        xl: "var(--radius)",
        "2xl": "calc(var(--radius) + 4px)",
      },
      boxShadow: {
        sm: "var(--shadow-card)",
        lg: "var(--shadow-soft)",
        xl: "var(--shadow-soft)",
        card: "var(--shadow-card)",
        soft: "var(--shadow-soft)",
        glow: "var(--shadow-glow)",
      },
      width: {
        sidebar: "248px",
      },
      margin: {
        sidebar: "248px",
      },
    },
  },
  plugins: [],
};

export default config;
