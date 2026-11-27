import { describe, expect, it } from "vitest";

import type { AccountMeta } from "@/lib/relay";
import { fanslyPick } from "./fanslyMirrorPick";

const acct = (id: string, live = true): AccountMeta =>
  ({ id, nickname: id, is_active: true, has_session: true, session_dead_at: live ? null : "2026-11-20T00:00:00Z" }) as AccountMeta;

const A = acct("fa");
const B = acct("fb");
const DEAD = acct("fdead", false);

describe("fanslyPick", () => {
  it.each([
    ["a live Fansly creator in the list", [A, B], "fb", { kind: "picked", accountId: "fb" }],
    ["no param", [A, B], null, { kind: "standIn", accountId: "fa" }],
    ["an empty param", [A, B], "", { kind: "standIn", accountId: "fa" }],
    ["an unknown id", [A, B], "nope", { kind: "standIn", accountId: "fa" }],
    ["a dead Fansly pick", [A, DEAD], "fdead", { kind: "standIn", accountId: "fa" }],
    ["a dead first creator", [DEAD, B], null, { kind: "standIn", accountId: "fb" }],
    ["only dead creators", [DEAD], "fdead", { kind: "none" }],
    ["no creators", [], "fa", { kind: "none" }],
    ["accounts not loaded", undefined, "fa", { kind: "loading" }],
  ] as const)("%s", (_, known, param, out) => {
    expect(fanslyPick(known as AccountMeta[] | undefined, param).pick).toEqual(out);
  });

  it("returns the live creators it picked from, dead ones dropped", () => {
    expect(fanslyPick([DEAD, A, B], null).live).toEqual([A, B]);
    expect(fanslyPick(undefined, "fa").live).toEqual([]);
  });
});
