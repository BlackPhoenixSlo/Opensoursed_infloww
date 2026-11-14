import { describe, expect, it } from "vitest";

import {
  accessTokensFormReducer, buildPayload, canSubmit, INITIAL_FORM, toTokenDays, type AccessTokensForm, type Action,
} from "./accessTokensForm";

const run = (actions: Action[], from: AccessTokensForm = INITIAL_FORM) => actions.reduce(accessTokensFormReducer, from);
const OPEN: Action = { type: "open" };
const name = (value: string): Action => ({ type: "name", value });
const created: Action = { type: "created", name: "claude", token: "ifw_x" };

describe("accessTokensFormReducer", () => {
  it.each<[string, Action[], Partial<AccessTokensForm>]>([
    ["open starts a blank 90-day form", [name("old"), OPEN], { open: true, name: "", days: 90, created: null }],
    ["typing and picking", [OPEN, name("claude"), { type: "days", value: 365 }], { name: "claude", days: 365 }],
    ["created shows the token", [OPEN, name("claude"), created], { created: { name: "claude", token: "ifw_x" } }],
    ["the shown token cannot be edited away", [OPEN, created, name("x"), { type: "days", value: 30 }],
      { name: "", days: 90, created: { name: "claude", token: "ifw_x" } }],
    ["close forgets the token", [OPEN, created, { type: "close" }], INITIAL_FORM],
    ["a late created after close is dropped", [OPEN, { type: "close" }, created], INITIAL_FORM],
    ["reopen after a token is a fresh form", [OPEN, created, { type: "close" }, OPEN], { open: true, created: null }],
  ])("%s", (_n, actions, want) => {
    expect(run(actions)).toMatchObject(want);
  });
});

describe("canSubmit / buildPayload", () => {
  it.each<[string, Action[], boolean]>([
    ["closed", [name("x")], false],
    ["blank", [OPEN], false],
    ["spaces only", [OPEN, name("   ")], false],
    ["a name", [OPEN, name("claude")], true],
    ["64 chars", [OPEN, name("a".repeat(64))], true],
    ["65 chars", [OPEN, name("a".repeat(65))], false],
    ["token showing", [OPEN, name("claude"), created], false],
  ])("%s → %s", (_n, actions, want) => {
    expect(canSubmit(run(actions))).toBe(want);
  });

  it("trims the name and sends the days", () => {
    expect(buildPayload(run([OPEN, name("  claude desktop "), { type: "days", value: 30 }]))).toEqual({ name: "claude desktop", days: 30 });
    expect(buildPayload(run([OPEN, name("x")]))).toEqual({ name: "x", days: 90 });
  });
});

describe("toTokenDays", () => {
  it.each([["30", 30], ["365", 365], [90, 90], ["7", 90], ["", 90], ["abc", 90]] as const)(
    "%j → %d",
    (v, want) => expect(toTokenDays(v)).toBe(want),
  );
});
