import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        surface: {
          DEFAULT: "#13151f",
          raised: "#1c1f2e",
          overlay: "#242840",
        },
        border: {
          DEFAULT: "#2d3148",
          muted: "#1e2235",
        },
        primary: {
          DEFAULT: "#6366f1",
          hover: "#4f52d9",
          muted: "rgba(99,102,241,0.15)",
        },
        tier: {
          hot: "#ef4444",
          warm: "#f97316",
          cool: "#3b82f6",
          cold: "#6b7280",
        },
      },
      fontFamily: {
        sans: ["var(--font-inter)", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "Fira Code", "monospace"],
      },
    },
  },
  plugins: [],
};

export default config;
