import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        teal: {
          50: "#F0FDFA",
          100: "#CCFBF1",
          200: "#99F6E4",
          300: "#5EEAD4",
          400: "#2DD4BF",
          500: "#14B8A6",
          600: "#0D9488",
          700: "#0F766E",
          800: "#115E59",
          900: "#134E4A",
        },
        primary: {
          DEFAULT: "var(--color-primary)",
          hover: "var(--color-primary-hover)",
          light: "var(--color-primary-light)",
          bg: "var(--color-primary-bg)",
          wash: "var(--color-primary-wash)",
        },
        page: "var(--bg-page)",
        panel: "var(--bg-panel)",
        surface: "var(--bg-surface)",
        elevated: "var(--bg-elevated)",
        "primary-text": "var(--text-primary)",
        secondary: "var(--text-secondary)",
        muted: "var(--text-muted)",
        "status-running": "var(--status-running)",
        "status-warning": "var(--status-warning)",
        "status-error": "var(--status-error)",
        "status-info": "var(--status-info)",
      },
      borderColor: {
        default: "var(--border-default)",
        subtle: "var(--border-subtle)",
      },
      backgroundColor: {
        page: "var(--bg-page)",
        panel: "var(--bg-panel)",
        surface: "var(--bg-surface)",
        elevated: "var(--bg-elevated)",
        default: "var(--border-default)",
      },
      width: {
        sidebar: "13rem",
      },
      margin: {
        sidebar: "13rem",
      },
    },
  },
  plugins: [],
};

export default config;
