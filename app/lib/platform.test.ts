import { readFileSync, readdirSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

import {
  CAPABILITIES, PLATFORMS, PLATFORM_KEY, PLATFORM_NAME, accountCan, accountPlatform, can, getPlatform, platformRow,
  resetPlatformForTests, type AccountPlatform, type Capability, type Platform,
} from "@/lib/platform";

describe("can", () => {
  const rows: [Platform | null, Capability, boolean][] = [
    ...CAPABILITIES.map((c) => ["onlyfans", c, true] as [Platform, Capability, boolean]),
    ...CAPABILITIES.map((c) => ["fansly", c, c === "mass_history"] as [Platform, Capability, boolean]),
    ...CAPABILITIES.map((c) => [null, c, false] as [null, Capability, boolean]),
  ];
  it.each(rows)("%s can %s → %s", (p, cap, want) => {
    expect(can(p, cap)).toBe(want);
  });

  it("lists 19 Capabilities, OnlyFans lacking none and Fansly all but mass_history", () => {
    expect(CAPABILITIES).toHaveLength(19);
    expect(PLATFORMS.map((p) => [p.key, p.lacks.length])).toEqual([["onlyfans", 0], ["fansly", 18]]);
  });
});

describe("accountCan", () => {
  const accounts = [{ id: "of", platform: "onlyfans" }, { id: "fa", platform: "fansly" }, { id: "legacy" }];
  it.each<[string, string, Capability, boolean]>([
    ["an OnlyFans Creator", "of", "notifications_read", true],
    ["a Fansly Creator", "fa", "notifications_read", false],
    ["a Fansly Creator's fan activity", "fa", "fan_activity", false],
    ["a Fansly Creator's native welcome", "fa", "native_welcome", false],
    ["an OnlyFans Creator's native welcome", "of", "native_welcome", true],
    ["a Creator with no stored platform reads as OnlyFans", "legacy", "fan_activity", true],
    ["a Creator not in the accounts list is allowed", "gone", "fan_activity", true],
  ])("%s", (_n, id, cap, want) => {
    expect(accountCan(accounts, id, cap)).toBe(want);
  });
});

describe("Platform names and keys read from the table", () => {
  it("PLATFORM_NAME is each row's label, and the unregistered key is Unknown platform", () => {
    expect(PLATFORM_NAME).toEqual({ onlyfans: "OnlyFans", fansly: "Fansly", unknown: "Unknown platform" });
  });

  it.each<[string, { platform?: string | null }, AccountPlatform]>([
    ["missing", {}, "onlyfans"],
    ["null", { platform: null }, "onlyfans"],
    ["empty", { platform: "" }, "onlyfans"],
    ["blank", { platform: "  " }, "onlyfans"],
    ["unregistered", { platform: "mym" }, "unknown"],
    ["onlyfans", { platform: "onlyfans" }, "onlyfans"],
    ["fansly", { platform: "fansly" }, "fansly"],
    ["fansly, as the Relay normalises it", { platform: " Fansly " }, "fansly"],
  ])("accountPlatform: %s platform", (_, a, want) => {
    expect(accountPlatform(a)).toBe(want);
  });

  it("an unregistered key is Unknown platform: every Capability false, no row, not a table key", () => {
    const p = accountPlatform({ platform: "mym" });
    expect(PLATFORM_NAME[p]).toBe("Unknown platform");
    expect(CAPABILITIES.filter((c) => can(p, c))).toEqual([]);
    expect(platformRow(p)).toBeUndefined();
    expect(PLATFORMS.map((r) => r.key)).toEqual(["onlyfans", "fansly"]);
  });

  it("an account with an unregistered key is refused every Capability", () => {
    const accounts = [{ id: "x", platform: "mym" }];
    expect(CAPABILITIES.filter((c) => accountCan(accounts, "x", c))).toEqual([]);
  });

  it.each<[string | null, Platform]>([[null, "onlyfans"], ["fansly", "fansly"], ["mym", "onlyfans"], ["onlyfans", "onlyfans"]])(
    "stored switch %s reads %s",
    (raw, want) => {
      if (raw === null) window.localStorage.removeItem(PLATFORM_KEY);
      else window.localStorage.setItem(PLATFORM_KEY, raw);
      resetPlatformForTests();
      expect(getPlatform()).toBe(want);
      window.localStorage.removeItem(PLATFORM_KEY);
      resetPlatformForTests();
    },
  );
});

type BranchAllow = Record<string, { hits: number; reason: string }>;

const PLATFORM_BRANCH_ALLOW: BranchAllow = {
  "fansly-manager/FanslyManagerPage.tsx": { hits: 1, reason: "mirror-owned single-platform gate" },
  "growth/PromotionTab.tsx": { hits: 1, reason: "promo `source` field (made on OnlyFans vs here), not a Creator's Platform" },
};

function platformBranches(source: string, keys: readonly string[]): string[] {
  const k = `["'](?:${keys.join("|")})["']`;
  const branch = new RegExp(`[!=]==?\\s*${k}|${k}\\s*[!=]==?`);
  return source.split("\n").flatMap((line, i) => (branch.test(line) ? [`${i + 1}: ${line.trim()}`] : []));
}

function platformBranchOffenders(
  files: readonly { path: string; source: string }[], keys: readonly string[], allow: BranchAllow,
): string[] {
  return files.flatMap((f) => {
    const hits = platformBranches(f.source, keys);
    const want = allow[f.path]?.hits ?? 0;
    if (hits.length === want) return [];
    const lines = hits.map((l) => `${f.path}:${l}`);
    return want ? [`${f.path}: allowlisted ${want}, found ${hits.length}`, ...lines] : lines;
  });
}

describe("Platform-branch scan: components read the row, never a literal Platform key", () => {
  const KEYS = PLATFORMS.map((p) => p.key);
  const seeded = 'const fansly = account.platform === "fansly";';

  it.each<[string, string, string[]]>([
    ["=== a key", seeded, ['1: const fansly = account.platform === "fansly";']],
    ["== a key", 'if (p == "onlyfans") x();', ['1: if (p == "onlyfans") x();']],
    ["!== a key", "ok = p !== 'fansly';", ["1: ok = p !== 'fansly';"]],
    ["the key first", 'if ("fansly" === p) x();', ['1: if ("fansly" === p) x();']],
    ["a key outside a comparison", 'const at = "fansly";\nsetPlatform("onlyfans");', []],
    ["an unregistered key", 'p === "mym"', []],
  ])("flags %s", (_n, src, want) => {
    expect(platformBranches(src, KEYS)).toEqual(want);
  });

  it("fails on a seeded branch in a scratch component, passes it on the allowlist, and fails a second one there", () => {
    const files = [{ path: "setup/Scratch.tsx", source: `export const x = 1;\n${seeded}` }];
    const allow = { "setup/Scratch.tsx": { hits: 1, reason: "scratch" } };
    expect(platformBranchOffenders(files, KEYS, {})).toEqual(['setup/Scratch.tsx:2: const fansly = account.platform === "fansly";']);
    expect(platformBranchOffenders(files, KEYS, allow)).toEqual([]);
    const grown = [{ path: "setup/Scratch.tsx", source: `${files[0].source}\nif (p === "onlyfans") x();` }];
    expect(platformBranchOffenders(grown, KEYS, allow)).toEqual([
      "setup/Scratch.tsx: allowlisted 1, found 2",
      'setup/Scratch.tsx:2: const fansly = account.platform === "fansly";',
      'setup/Scratch.tsx:3: if (p === "onlyfans") x();',
    ]);
    expect(platformBranchOffenders([{ path: "setup/Scratch.tsx", source: "" }], KEYS, allow))
      .toEqual(["setup/Scratch.tsx: allowlisted 1, found 0"]);
  });

  it("app/components has no literal Platform branch beyond the allowlist's counts, and every allowlisted file exists", () => {
    const dir = resolve(__dirname, "../components");
    const files = readdirSync(dir, { recursive: true, encoding: "utf8" })
      .filter((f) => /\.tsx?$/.test(f) && !/\.test\.tsx?$/.test(f) && !f.split("/").includes("node_modules"))
      .map((f) => ({ path: f, source: readFileSync(resolve(dir, f), "utf8") }));
    expect(platformBranchOffenders(files, KEYS, PLATFORM_BRANCH_ALLOW)).toEqual([]);
    const paths = new Set(files.map((f) => f.path));
    expect(Object.keys(PLATFORM_BRANCH_ALLOW).filter((p) => !paths.has(p))).toEqual([]);
  });
});
