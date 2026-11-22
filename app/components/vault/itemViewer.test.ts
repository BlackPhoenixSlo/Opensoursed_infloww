/** The folders editor's viewer + player reducer (`itemViewer.ts`), as a table. */
import { describe, expect, it } from "vitest";

import type { Tile } from "@/components/vault/vaultManageActions";

import { INITIAL_VIEWER, type ViewerAction, type ViewerState, viewerReducer } from "./itemViewer";

const t = (id: number, ai?: Record<string, unknown>) => ({ id, type: "photo", ...(ai ? { _ai: ai } : {}) }) as Tile;
const run = (actions: ViewerAction[], from: ViewerState = INITIAL_VIEWER) => actions.reduce(viewerReducer, from);
const ids = (s: ViewerState) => [s.preview?.id ?? null, s.play?.id ?? null];

describe("viewerReducer", () => {
  it.each<[string, ViewerAction[], (number | null)[]]>([
    ["open", [{ type: "open", media: t(1) }], [1, null]],
    ["step = open another", [{ type: "open", media: t(1) }, { type: "open", media: t(2) }], [2, null]],
    ["expand plays the open item", [{ type: "open", media: t(1) }, { type: "expand" }], [1, 1]],
    ["expand with nothing open is nothing", [{ type: "expand" }], [null, null]],
    ["play from the grid", [{ type: "play", media: t(3) }], [null, 3]],
    ["escape: player first", [{ type: "open", media: t(1) }, { type: "expand" }, { type: "escape" }], [1, null]],
    ["escape twice: viewer next", [{ type: "open", media: t(1) }, { type: "expand" }, { type: "escape" }, { type: "escape" }],
      [null, null]],
    ["close closes both", [{ type: "open", media: t(1) }, { type: "expand" }, { type: "close" }], [null, null]],
    ["the player's own close", [{ type: "open", media: t(1) }, { type: "expand" }, { type: "closePlayer" }], [1, null]],
  ])("%s", (_n, actions, want) => {
    expect(ids(run(actions))).toEqual(want);
  });

  it.each<[string, ViewerAction[], Record<string, unknown> | undefined]>([
    ["saved merges into the open item's _ai",
      [{ type: "open", media: t(1, { a: 1, tags: ["x"] }) }, { type: "saved", mediaId: 1, updated: { tags: ["y"] } }],
      { a: 1, tags: ["y"] }],
    // W30 C7: save on 1, step to 2 before the answer — 2 keeps its own _ai.
    ["a stale item's answer is ignored",
      [{ type: "open", media: t(1, { tags: ["x"] }) }, { type: "open", media: t(2, { tags: ["z"] }) },
        { type: "saved", mediaId: 1, updated: { tags: ["y"] } }],
      { tags: ["z"] }],
    // W30 C7 / M1: only _ai's keys merge, not the response's media_id / id / kind / locked_fields.
    ["extra keys are not merged",
      [{ type: "open", media: t(1, {}) }, { type: "saved", mediaId: 1, updated: {
        media_id: 1, id: 1, kind: "photo", locked_fields: ["tags"], description: "d", fields: { a: 1 },
        jev_picks: {}, jev_ai: null } }],
      { description: "d", fields: { a: 1 }, jev_picks: {}, jev_ai: null }],
  ])("%s", (_n, actions, want) => {
    expect(run(actions).preview?._ai).toEqual(want);
  });

  it("saved with nothing open stays nothing", () => {
    expect(run([{ type: "saved", mediaId: 1, updated: { tags: [] } }])).toEqual(INITIAL_VIEWER);
  });
});
