import { existsSync, readFileSync } from "node:fs";
import { basename, dirname, resolve } from "node:path";
import { describe, expect, it } from "vitest";

// ofMirrorMass and ofMirrorChat read bindChatTags while they load; reached from ofMirrorChatShared's own imports that read dies in a browser ("Cannot access 'bindChatTags' before initialization") but not under vitest, so read the source.
describe("ofMirrorChatShared's imports", () => {
  const source = (file: string) => {
    for (const ext of [".ts", ".tsx", "/index.ts", "/index.tsx"]) if (existsSync(file + ext)) return file + ext;
    return null;
  };
  const inlineTypesOnly = (clause: string) => {
    const names = /^\{([^}]*)\}$/.exec(clause.trim())?.[1].split(",").map((n) => n.trim()).filter(Boolean);
    return !!names?.length && names.every((n) => n.startsWith("type "));
  };
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
    expect(reached).toContain("ofMirrorData.ts");
    expect(reached).not.toContain("ofMirrorChatShared.ts");
  });
});
