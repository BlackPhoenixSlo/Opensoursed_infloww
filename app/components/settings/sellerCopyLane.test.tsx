import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

import { APP_ROOT as ROOT, reachable, stripComments } from "@/test-import-graph";

function routeSeeds(): string[] {
  const out: string[] = [];
  const walk = (dir: string) => {
    for (const e of fs.readdirSync(path.join(ROOT, dir), { withFileTypes: true })) {
      const rel = path.join(dir, e.name);
      if (e.isDirectory()) walk(rel);
      else if (e.name.endsWith(".tsx")) out.push(rel);
    }
  };
  walk("app");
  return out.sort();
}
const SEEDS = routeSeeds();

const BANNED = /\b(she|her|hers|herself|girl|girls|woman|women)\b/i;

export function codeOnly(src: string): string {
  return stripComments(src)
    .replace(/"(her|him)"/g, '"·"');
}

const { modules: MODULES, unresolved: UNRESOLVED } = reachable(SEEDS, (t) => t.startsWith("components/"));


describe("seller-tab operator copy names the role, not the gender", () => {
  it("finds the whole render graph, and follows everything it should", () => {
    expect(UNRESOLVED).toEqual([]);
    expect(SEEDS.length).toBeGreaterThanOrEqual(20);
    expect(MODULES.length).toBeGreaterThanOrEqual(35);
    for (const must of ["components/growth/AutoReplyPage.tsx",
                        "components/automations/GetToKnowFansPage.tsx",
                        "components/settings/NudgeOnlineTab.tsx",
                        "components/automations/FunnelEditor.tsx",
                        "components/chat/VaultPicker.tsx"]) {
      expect(MODULES, `${must} is mounted under Automations`).toContain(must);
    }
  });

  for (const rel of MODULES) {
    it(rel, () => {
      const src = fs.readFileSync(path.join(ROOT, rel), "utf8");
      const offenders = codeOnly(src)
        .split("\n")
        .map((line, i) => ({ line, n: i + 1 }))
        .filter(({ line }) => BANNED.test(line))
        .map((o) => `${rel}:${o.n} ${o.line.trim()}`);
      expect(offenders).toEqual([]);
    });
  }

  it("the matcher and the stripper still do their jobs", () => {
    expect(BANNED.test("  <span>Never contradict herself</span>")).toBe(true);
    expect(BANNED.test('  question_hook: "she opens a scene"')).toBe(true);
    expect(BANNED.test('  "after he buys, the ask goes up"')).toBe(false);
    expect(BANNED.test("  where the other thread gathers")).toBe(false);
    expect(codeOnly("const a = 1; // she used to do this").trim()).toBe("const a = 1;");
    expect(codeOnly("/* a\n b\n */\nreal").split("\n")).toHaveLength(4);
    expect(codeOnly('const u = "https://x/y"; // note')).toContain("https://x/y");
    const tricky = 'const s = "50% /* off";\n  <span>she is here</span>\n';
    expect(codeOnly(tricky)).toContain("she is here");
  });
});
