import { describe, expect, it } from "vitest";

import { popoutReady } from "@/components/of-manager/popoutReady";

describe("popoutReady", () => {
  it.each<[string, Parameters<typeof popoutReady>, boolean]>([
    ["no ?account=: nothing to wait for", [null, [], false], true],
    ["a known id: at once, read or not", ["2", ["1", "2"], false], true],
    ["a known watcher id: at once", ["9", ["9"], false], true],
    ["an unknown id waits for a read", ["9", ["1"], false], false],
    ["an unknown id after a successful read: applied", ["9", ["1"], true], true],
  ])("%s", (_, args, want) => expect(popoutReady(...args)).toBe(want));
});
