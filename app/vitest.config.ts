/**
 * Vitest config for the Next.js app (React 19).
 *
 * Inert until the dev-deps are installed by T-TESTKIT:
 *   pnpm add -D vitest @vitejs/plugin-react jsdom \
 *     @testing-library/react @testing-library/jest-dom @testing-library/user-event
 *
 * Run:  pnpm test        (watch)
 *       pnpm test:run    (one-shot, CI)
 */
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import { resolve } from "node:path";

// CPU-bound jsdom renders: 0.6-2.3 s alone, 5-9.3 s at host load ~90 (measured), past the 5 s default.
// No timer wait to fake, so these files get 15 s (~1.6x the slowest); everything else keeps 5 s.
const SLOW_JSDOM = [
  "components/chat/Composer.fuScript.test.tsx",
  "components/chat/ComposerFocusKeys.test.tsx",
  "components/chat/ComposerRefusedOffers.test.tsx",
  "components/chat/ComposerToolbar.test.tsx",
  "components/chat/ComposerUpload.test.tsx",
  "components/chat/FanList.test.tsx",
  "components/chat/OutboundTranslation.test.tsx",
  "components/chat/PpvRow.test.tsx",
  "components/chat/TimedMessagePopover.test.tsx",
  "components/growth/SmartMessagesPage.test.tsx",
  "components/growth/VaultProPage.test.tsx",
];

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./vitest.setup.ts"],
    // include lives in the projects: extends: true concatenates arrays, so a root include would pull every file
    // into slow-jsdom too.
    exclude: ["node_modules/**", ".next/**"],
    // "0 tests = ok" until the first frontend tests land (T-TESTKIT). Without
    // this, `vitest run` exits 1 on an empty suite and reddens run-tests.sh.
    passWithNoTests: true,
    projects: [
      { extends: true, test: { name: "default", include: ["**/*.test.{ts,tsx}"], exclude: SLOW_JSDOM } },
      { extends: true, test: { name: "slow-jsdom", include: SLOW_JSDOM, testTimeout: 15_000 } },
    ],
  },
  resolve: {
    // Mirror tsconfig paths: "@/*" -> "./*"
    alias: { "@": resolve(__dirname, ".") },
  },
});
