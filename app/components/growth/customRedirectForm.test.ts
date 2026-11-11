import { describe, expect, it } from "vitest";

import {
  buildPayload, formError, INITIAL_FORM, redirectFormReducer, type Action, type RedirectForm,
} from "./customRedirectForm";

const run = (actions: Action[], from: RedirectForm = INITIAL_FORM) => actions.reduce(redirectFormReducer, from);
const form = (name: string, target: string, botCheck = false): RedirectForm => ({ ...INITIAL_FORM, name, target, botCheck });

describe("redirectFormReducer", () => {
  it("edit sets the field and clears the error", () => {
    const s = run([{ type: "fail", err: "x" }, { type: "edit", field: "target", value: "ofl.ink/a" }]);
    expect(s).toEqual({ ...INITIAL_FORM, target: "ofl.ink/a" });
  });
  it("setBotCheck toggles; reset clears everything", () => {
    const s = run([{ type: "edit", field: "name", value: "N" }, { type: "setBotCheck", on: true }]);
    expect(s.botCheck).toBe(true);
    expect(redirectFormReducer(s, { type: "reset" })).toBe(INITIAL_FORM);
  });
});

describe("formError / buildPayload", () => {
  it.each<[string, RedirectForm, boolean, string | null, ReturnType<typeof buildPayload>]>([
    ["target sent as typed, trimmed (the relay normalizes it)", form(" Bio ", " ofl.ink/nora "), true, null,
      { name: "Bio", target_url: "ofl.ink/nora", bot_check: false }],
    ["bot check sent when available", form("Bio", "ofl.ink/i", true), true, null,
      { name: "Bio", target_url: "ofl.ink/i", bot_check: true }],
    ["bot check dropped when unavailable", form("Bio", "ofl.ink/i", true), false, null,
      { name: "Bio", target_url: "ofl.ink/i", bot_check: false }],
    ["name required", form("  ", "ofl.ink/i"), true, "Name is required.",
      { name: "", target_url: "ofl.ink/i", bot_check: false }],
    ["target required", form("x", "   "), true, "Target URL is required.",
      { name: "x", target_url: "", bot_check: false }],
    ["a bad target is the relay's to refuse", form("x", "javascript:alert(1)"), true, null,
      { name: "x", target_url: "javascript:alert(1)", bot_check: false }],
  ])("%s", (_n, f, available, err, payload) => {
    expect(formError(f)).toBe(err);
    expect(buildPayload(f, available)).toEqual(payload);
  });
});
