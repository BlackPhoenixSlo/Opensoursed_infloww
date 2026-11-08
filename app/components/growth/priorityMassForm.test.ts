import { describe, expect, it } from "vitest";

import type { VaultMedia } from "@/lib/relay";
import { SENSITIVE_BLOCK_MESSAGE } from "@/lib/sensitiveWords";
import {
  buildPayload, initPriorityMass, launchError, priorityMassReducer,
  type PriorityMassAction, type PriorityMassState,
} from "./priorityMassForm";

const m = (id: number) => ({ id }) as VaultMedia;
const run = (actions: PriorityMassAction[], s = initPriorityMass("a")): PriorityMassState =>
  actions.reduce(priorityMassReducer, s);

describe("priorityMassReducer", () => {
  it("a real account switch resets the audience only; the message stays", () => {
    const s = run([
      { type: "setText", text: "hi" }, { type: "setAttached", attached: [m(1)] }, { type: "setPrice", price: "5" },
      { type: "toggleExclude", id: "9" }, { type: "setAccount", id: "b" },
    ]);
    expect(s).toMatchObject({ accountId: "b", text: "hi", attached: [m(1)], price: "5", seededFor: null });
    expect([...s.includes]).toEqual(["fans", "following"]);
    expect([...s.excludes]).toEqual([]);
  });
});

// The body the old inline mutationFn built (dd6c17d0e / HEAD PriorityMass.tsx), per input.
describe("buildPayload pins the old inline body", () => {
  it.each<[string, PriorityMassAction[], unknown]>([
    ["free text, default audience", [{ type: "setText", text: "  Hey {name}  " }], {
      account_id: "a", text: "Hey {name}", media_files: [], previews: [], price: 0, locked_text: false,
      user_lists: ["fans", "following"], excluded_user_lists: [],
    }],
    ["free with media: previews and lock ignored", [
      { type: "setAttached", attached: [m(1), m(2)] }, { type: "setPreviewCount", n: 1 }, { type: "setLockedText", on: true },
    ], {
      account_id: "a", text: "", media_files: [1, 2], previews: [], price: 0, locked_text: false,
      user_lists: ["fans", "following"], excluded_user_lists: [],
    }],
    ["priced: previews sliced, lock kept, audience in click order", [
      { type: "setAttached", attached: [m(1), m(2), m(3)] }, { type: "setPreviewCount", n: 2 },
      { type: "setPrice", price: "9.5" }, { type: "setLockedText", on: true },
      { type: "toggleInclude", id: "fans" }, { type: "toggleInclude", id: "42" },
      { type: "seedExclude", accountId: "a", listId: "7" }, { type: "toggleExclude", id: "8" },
    ], {
      account_id: "a", text: "", media_files: [1, 2, 3], previews: [1, 2], price: 9.5, locked_text: true,
      user_lists: ["following", "42"], excluded_user_lists: ["7", "8"],
    }],
    ["a price that isn't a number is free", [{ type: "setPrice", price: "." }, { type: "setLockedText", on: true }], {
      account_id: "a", text: "", media_files: [], previews: [], price: 0, locked_text: false,
      user_lists: ["fans", "following"], excluded_user_lists: [],
    }],
  ])("%s", (_, actions, body) => {
    expect(buildPayload(run(actions))).toEqual(body);
  });
});

describe("launchError: the old launch() checks, in order", () => {
  it.each<[string, PriorityMassState, boolean, string | null]>([
    ["sensitive words first", run([], initPriorityMass(null)), true, SENSITIVE_BLOCK_MESSAGE],
    ["no Creator", run([{ type: "setText", text: "x" }], initPriorityMass(null)), false, "Pick a Creator."],
    ["blank text, no media", run([{ type: "setText", text: "  " }]), false, "Add a text or media."],
    ["nothing included", run([{ type: "setText", text: "x" }, { type: "toggleInclude", id: "fans" },
      { type: "toggleInclude", id: "following" }]), false, "Pick at least one audience to include."],
    ["priced text without media", run([{ type: "setText", text: "x" }, { type: "setPrice", price: "3" }]), false,
      "A priced message needs media."],
    ["media only: ok", run([{ type: "setAttached", attached: [m(1)] }, { type: "setPrice", price: "3" }]), false, null],
    ["text only: ok", run([{ type: "setText", text: "x" }]), false, null],
  ])("%s", (_, s, sensitive, want) => {
    expect(launchError(s, sensitive)).toBe(want);
  });
});
