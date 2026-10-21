/**
 * THE RULE, ENFORCED OVER THE WHOLE AUTOMATIONS RENDER GRAPH.
 *
 * Operator copy names the ROLE, never the creator's gender.
 * In the male lane the creator AND the fan are "he", so a creator pronoun collides
 * with the fan's — "he runs his thread" states the opposite of what it means.
 *
 * THE SCOPE IS COMPUTED, NOT TYPED, AND IT TOOK FOUR GOES TO MEAN IT. v1 listed
 * three filenames and was green while `ReengageBuyersTab` — mounted INSIDE the AI
 * Chatter tab — shipped "It skips anyone she messaged recently". v2 walked the import
 * graph but seeded at the two seller tabs, which is a hand-typed scope one level up:
 * `AutoreplyTab`, a SIBLING tab, carried five gendered strings while this was green,
 * one of them edited by the same commit. v3 seeds at the composition ROOT — the panel
 * that actually mounts the tabs — so every tab is in scope by construction and a new
 * one joins on the day its import line lands. v4 stopped typing anything: the seeds
 * are every `app/**\/page.tsx`, because a route is the one thing no one hand-picks.
 *
 * Each version failed the way the python guard's own docstring predicts ("WHICH
 * functions are laned is DERIVED, not listed"): a scope you type is a scope you
 * forget.
 *
 * BOTH import spellings are followed — `@/components/…` and relative `./Foo` — and
 * anything under components/ that cannot be resolved FAILS the run instead of
 * dropping out of scope. Following only the alias was the same defect one directory
 * over from the python guard's `_voice.HER` matching: a scope computed from a
 * spelling. `@/hooks`, `@/lib` and `@/contexts` are deliberately not followed (they
 * render no prose), which keeps the closure small with no exclusion list. It still
 * reaches `chat/VaultPicker`, which renders inside a seller tab and which no
 * `components/settings/` glob could find.
 *
 * COMMENTS ARE EXCLUDED: the modules explain why the rule exists, and that
 * explanation must quote the banned words to be worth reading.
 *
 * The FAN is not in scope. He is male in both lanes, so "he"/"him"/"his" is correct.
 */
import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

import { APP_ROOT as ROOT, reachable, stripComments } from "@/test-import-graph";

/** THE ROUTES. Not a filename — a glob of every `app/**\/page.tsx`.
 *
 *  Four versions of this guard typed their own scope and all four forgot something:
 *  three filenames missed `ReengageBuyersTab`; the two seller tabs missed the sibling
 *  `AutoreplyTab`; `ReadyMadePanel` missed `BrainPanel` — the panel holding the
 *  Female/Male dropdown itself, sitting ABOVE the tabs on the same page, shipping
 *  "Her facts" over field labels this series had just taught to say "Why he started
 *  OF". Each time the fix was "seed one level up", and one level up was still typed.
 *
 *  Pages are the only things nobody chooses: Next mounts them, the glob finds them,
 *  and a new screen is in scope the day its route exists. */
function routeSeeds(): string[] {
  const out: string[] = [];
  const walk = (dir: string) => {
    for (const e of fs.readdirSync(path.join(ROOT, dir), { withFileTypes: true })) {
      const rel = path.join(dir, e.name);
      if (e.isDirectory()) walk(rel);
      // EVERY .tsx under app/, not `page.tsx`. `page` is one of Next's route-file
      // names, not the route contract: `layout.tsx` composes too, and the ROOT
      // layout mounts TopNav/MoneyRail/NotificationToaster on every screen. Picking
      // one filename out of that set was v5 of the same typed-scope mistake.
      // Over-seeding is free (the walker de-dupes and these files are the app);
      // under-seeding is the failure this guard exists to stop.
      else if (e.name.endsWith(".tsx")) out.push(rel);
    }
  };
  walk("app");
  return out.sort();
}
const SEEDS = routeSeeds();

/** Words that assert the creator is a woman. `girl` included: "Girl style" was a
 *  checkbox label until it was renamed, and it is the same mistake in one word. */
const BANNED = /\b(she|her|hers|herself|girl|girls|woman|women)\b/i;

/** Source minus comments, so the rule's own rationale can quote what it forbids.
 *
 *  Block comments are stripped only where `/*` OPENS A LINE. A global `/\*[\s\S]*?\*\/`
 *  is fail-open here: one `/*` inside a string or JSX text swallows everything up to
 *  the next JSDoc terminator, deleting real copy from the scan. Every block comment in
 *  these files starts its own line, so the narrow rule loses nothing.
 *
 *  Trailing `//` counts too — a guard that fires on a comment is one people switch
 *  off. `(?<![:\w])` keeps `https://` intact. */
export function codeOnly(src: string): string {
  // Comments are BLANKED, not deleted — a multi-line block replaced by "" collapses
  // every line after it, so the reported file:line pointed at the wrong place (the
  // guard's first real catch cited :651 for a string on :674). The blanking and its
  // non-backtracking block-comment body live in `test-import-graph.ts`, shared
  // with the Messages Pro magic-number guard.
  return stripComments(src)
    // A string literal whose ENTIRE content is a lane id is wire DATA, never copy
    // (`form?.voice ?? "her"`). Whole-literal only — never a substring, never JSX
    // text — so no judgement call and no exclusion list.
    .replace(/"(her|him)"/g, '"·"');
}

/** Modules reachable from the seeds (`test-import-graph.ts`'s `reachable`).
 *
 *  BOTH SPELLINGS are followed — `@/components/…` and relative `./Foo`. The first
 *  version followed only the alias, so a sibling imported `./Foo` silently
 *  dropped out of scope: "computed from the import
 *  graph" was computed from a spelling. Only components/ is followed (hooks, lib and
 *  contexts render no prose), and anything under components/ the walk cannot resolve
 *  comes back as UNRESOLVED — FAIL CLOSED: a resolver that silently drops what it
 *  cannot follow is how the typed list failed, one level down. */
const { modules: MODULES, unresolved: UNRESOLVED } = reachable(SEEDS, (t) => t.startsWith("components/"));


describe("seller-tab operator copy names the role, not the gender", () => {
  it("finds the whole render graph, and follows everything it should", () => {
    // FAIL CLOSED. A walker that silently drops what it cannot follow collapses to
    // the two seeds and passes forever — the same fail-open as the typed list, one
    // level down. Anything under components/ it could not resolve is reported here
    // rather than quietly leaving the scope.
    expect(UNRESOLVED).toEqual([]);
    expect(SEEDS.length).toBeGreaterThanOrEqual(20);   // the app/ tree still resolves
    expect(MODULES.length).toBeGreaterThanOrEqual(35);
    for (const must of ["components/growth/AutoReplyPage.tsx",          // a page's own panel
                        "components/automations/GetToKnowFansPage.tsx", // a SIBLING page
                        "components/settings/NudgeOnlineTab.tsx",       // mounted inside another tab
                        "components/automations/FunnelEditor.tsx",
                        "components/chat/VaultPicker.tsx"]) {           // cross-directory
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
    // The fan's pronouns are correct in both lanes and must NOT trip it.
    expect(BANNED.test('  "after he buys, the ask goes up"')).toBe(false);
    // Nor a substring inside an ordinary word.
    expect(BANNED.test("  where the other thread gathers")).toBe(false);
    // A trailing comment is a comment; a URL is not.
    expect(codeOnly("const a = 1; // she used to do this").trim()).toBe("const a = 1;");
    // Blanking, not deleting: a 3-line comment must still occupy 3 lines, or every
    // offender it reports afterwards carries the wrong coordinates.
    expect(codeOnly("/* a\n b\n */\nreal").split("\n")).toHaveLength(4);
    expect(codeOnly('const u = "https://x/y"; // note')).toContain("https://x/y");
    // …and an inline `/*` in a STRING must not eat the copy after it.
    const tricky = 'const s = "50% /* off";\n  <span>she is here</span>\n';
    expect(codeOnly(tricky)).toContain("she is here");
  });
});
