import { existsSync, readFileSync } from "node:fs";
import { basename, dirname, resolve } from "node:path";
import { describe, expect, it } from "vitest";

/**
 * ofMirrorMass and ofMirrorChat read ofMirrorChatShared's bindChatTags while they load (their dialog tables), and both import
 * ofMirrorChatShared. Reached from its own imports, that read runs first in a browser and the page dies ("Cannot access
 * 'bindChatTags' before initialization"). Read off the source: under vitest's module runner that read does not throw, so no
 * import here goes red.
 */
describe("ofMirrorChatShared's imports", () => {
  const source = (file: string) => {
    for (const ext of [".ts", ".tsx", "/index.ts", "/index.tsx"]) if (existsSync(file + ext)) return file + ext;
    return null;
  };
  /** `import { type A, type B } from`: erased like `import type`, so no edge. */
  const inlineTypesOnly = (clause: string) => {
    const names = /^\{([^}]*)\}$/.exec(clause.trim())?.[1].split(",").map((n) => n.trim()).filter(Boolean);
    return !!names?.length && names.every((n) => n.startsWith("type "));
  };
  /** Every module `entry`'s value imports reach; `entry` itself only if an import comes back to it. */
  const reachedFrom = (entry: string) => {
    const reached = new Set<string>();
    const walk = (file: string) => {
      for (const [, kind, clause, spec] of readFileSync(file, "utf8").matchAll(/^\s*(?:import|export)\s+(type\s+)?([^;]*?)from\s+"([^"]+)"/gm)) {
        if (kind || inlineTypesOnly(clause)) continue;
        const to = spec.startsWith("@/") ? source(resolve(__dirname, "..", spec.slice(2))) : spec.startsWith(".") ? source(resolve(dirname(file), spec)) : null;
        if (!to || reached.has(to)) continue;
        reached.add(to);
        walk(to);
      }
    };
    walk(entry);
    return [...reached].map((f) => basename(f));
  };

  it("never reach back to it", () => {
    const reached = reachedFrom(resolve(__dirname, "ofMirrorChatShared.ts"));
    expect(reached).toContain("ofMirrorData.ts"); // the walk does follow its imports
    expect(reached).not.toContain("ofMirrorChatShared.ts");
  });
});
