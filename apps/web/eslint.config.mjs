import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  // test/browser holds scripts to paste into a browser console (they declare a function the console calls), not code that is part of the app
  globalIgnores([".next/**", "out/**", "build/**", "next-env.d.ts", "coverage/**", "test/browser/**"]),
]);

export default eslintConfig;
