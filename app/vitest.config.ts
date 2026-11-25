import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import { resolve } from "node:path";

// eslint-disable-next-line @typescript-eslint/no-require-imports
const { writePluginBarrel } = require("./lib/pluginBarrel.js") as { writePluginBarrel: (appRoot: string) => string[] };
writePluginBarrel(__dirname);

// CPU-bound jsdom renders: 0.6-2.3 s alone, 5-9.3 s at host load ~90 (measured), past the 5 s default.
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
    exclude: ["node_modules/**", ".next/**"],
    passWithNoTests: true,
    // include lives in the projects: extends: true concatenates arrays, so a root include would pull every file into slow-jsdom too.
    projects: [
      { extends: true, test: { name: "default", include: ["**/*.test.{ts,tsx}"], exclude: SLOW_JSDOM } },
      { extends: true, test: { name: "slow-jsdom", include: SLOW_JSDOM, testTimeout: 15_000 } },
    ],
  },
  resolve: {
    alias: { "@": resolve(__dirname, ".") },
  },
});
