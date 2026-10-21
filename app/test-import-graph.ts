/**
 * Test-only (beside `test-utils.tsx`; it reads files with `node:fs`, so no app
 * module may import it). Helpers for source-reading guards: comment blanking, import
 * specifier parsing and the reachability walk over the app's import graph.
 * Shared by `components/settings/sellerCopyLane.test.tsx` (the seller copy lane)
 * and `lib/messagesPro.test.ts` (the Messages Pro magic-number guard), so the two
 * guards compute their scopes the same way.
 *
 * A scope you type is a scope you forget; a scope computed from one import
 * spelling is the same defect one level down. So every spelling is parsed
 * (`from`, `import(…)`, `require(…)`, `@/…` and relative), and anything the
 * walk cannot resolve is reported rather than dropped.
 */
import fs from "node:fs";
import path from "node:path";

/** The app package root: every path below is relative to it. */
export const APP_ROOT = __dirname;

/** Source minus comments, BLANKED line for line so `file:line` stays the file's own.
 *
 *  Block comments are stripped only where `/*` OPENS A LINE. A global `/\*[\s\S]*?\*\/`
 *  is fail-open: one `/*` inside a string or JSX text swallows everything up to the
 *  next JSDoc terminator. `[^*]*\*+([^/*][^*]*\*+)*` is the non-backtracking
 *  block-comment body: it cannot run past the FIRST `*\/`. Trailing `//` goes too;
 *  `(?<![:\w])` keeps `https://` intact. */
export function stripComments(src: string): string {
  const keepLines = (m: string) => m.replace(/[^\n]/g, "");
  return src
    .replace(/^[ \t]*\{?\/\*[^*]*\*+(?:[^/*][^*]*\*+)*\/\}?[ \t]*$/gm, keepLines)
    .replace(/(?<![:\w])\/\/.*$/gm, "");
}

/** Every import specifier in `src`: static, re-exported, dynamic or required. */
function specifiers(src: string): string[] {
  const out: string[] = [];
  for (const re of [/from\s+["']([^"']+)["']/g, /import\(\s*["']([^"']+)["']\s*\)/g,
                    /require\(\s*["']([^"']+)["']\s*\)/g]) {
    for (const m of src.matchAll(re)) out.push(m[1]);
  }
  return out;
}

/** A specifier → a path relative to the app root, or null for a package. An
 *  alias or relative path that names no file comes back as its bare base, so the
 *  caller can report it: ours by shape but unresolvable, never skipped. */
export function resolveSpec(spec: string, fromRel: string): string | null {
  let base: string | null = null;
  if (spec.startsWith("@/")) base = spec.slice(2);
  else if (spec.startsWith("./") || spec.startsWith("../")) {
    base = path.normalize(path.join(path.dirname(fromRel), spec));
  }
  if (base === null) return null;
  for (const cand of [base + ".tsx", base + ".ts", base + ".jsx", base + ".js",
                      path.join(base, "index.tsx"), path.join(base, "index.ts")]) {
    if (fs.existsSync(path.join(APP_ROOT, cand))) return cand;
  }
  return base;
}

/** The files `rel` imports, by every spelling (comments ignored), resolved
 *  relative to the app root; one that names no file comes back as its bare base. */
export function importsOf(rel: string): string[] {
  const src = stripComments(fs.readFileSync(path.join(APP_ROOT, rel), "utf8"));
  return specifiers(src).map((s) => resolveSpec(s, rel)).filter((t): t is string => t !== null);
}

/** The modules reachable from `seeds`, following each resolved import that
 *  `follow` accepts. FAIL CLOSED: a missing seed, and any import under
 *  `components/` that names no file, comes back in `unresolved`. */
export function reachable(seeds: string[], follow: (target: string) => boolean):
    { modules: string[]; unresolved: string[] } {
  const seen = new Set<string>();
  const unresolved = new Set<string>();
  const queue = [...seeds];
  while (queue.length) {
    const rel = queue.shift()!;
    if (seen.has(rel)) continue;
    if (!fs.existsSync(path.join(APP_ROOT, rel))) { unresolved.add(rel); continue; }
    seen.add(rel);
    for (const target of importsOf(rel)) {
      if (!fs.existsSync(path.join(APP_ROOT, target))) {
        if (target.startsWith("components/")) unresolved.add(`${rel} -> ${target}`);
        continue;
      }
      if (follow(target)) queue.push(target);
    }
  }
  return { modules: [...seen].sort(), unresolved: [...unresolved].sort() };
}
