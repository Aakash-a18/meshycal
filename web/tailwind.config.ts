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
        ink: "#0e1116",
        cream: "#faf7f2",
        receipt: "#f5efe6",
      },
    },
  },
  plugins: [],
};

export default config;
