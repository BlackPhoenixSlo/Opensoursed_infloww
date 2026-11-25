import fs from "node:fs";
import path from "node:path";

export const APP_ROOT = __dirname;

export function stripComments(src: string): string {
  // Block comments strip only where `/*` opens a line: a global regex is fail-open when `/*` sits in a string or JSX text.
  const keepLines = (m: string) => m.replace(/[^\n]/g, "");
  return src
    .replace(/^[ \t]*\{?\/\*[^*]*\*+(?:[^/*][^*]*\*+)*\/\}?[ \t]*$/gm, keepLines)
    .replace(/(?<![:\w])\/\/.*$/gm, "");
}

function specifiers(src: string): string[] {
  const out: string[] = [];
  for (const re of [/from\s+["']([^"']+)["']/g, /import\(\s*["']([^"']+)["']\s*\)/g,
                    /require\(\s*["']([^"']+)["']\s*\)/g]) {
    for (const m of src.matchAll(re)) out.push(m[1]);
  }
  return out;
}

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

export function importsOf(rel: string): string[] {
  const src = stripComments(fs.readFileSync(path.join(APP_ROOT, rel), "utf8"));
  return specifiers(src).map((s) => resolveSpec(s, rel)).filter((t): t is string => t !== null);
}

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
