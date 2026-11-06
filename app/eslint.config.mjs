import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";
import noFixedPolling from "./eslint-rules/no-fixed-polling.mjs";

export default defineConfig([
  ...nextVitals,
  ...nextTs,
  {
    plugins: { local: { rules: { "no-fixed-polling": noFixedPolling } } },
    rules: {
      "local/no-fixed-polling": "error",
      "@typescript-eslint/no-explicit-any": "off",
      "@typescript-eslint/no-unused-vars": ["warn", { argsIgnorePattern: "^_" }],
      // React Compiler rules that eslint-config-next 16 switched on. The
      // codebase predates them (100+ hits) and does not run the compiler;
      // warn so they stay visible without failing lint.
      "react-hooks/set-state-in-effect": "warn",
      "react-hooks/refs": "warn",
      "react-hooks/static-components": "warn",
      "react-hooks/purity": "warn",
      "react-hooks/use-memo": "warn",
      "react-hooks/immutability": "warn",
    },
  },
  globalIgnores([".next/**", "out/**", "build/**", "next-env.d.ts"]),
]);
