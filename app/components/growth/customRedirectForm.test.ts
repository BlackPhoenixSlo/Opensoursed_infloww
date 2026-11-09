import { describe, expect, it } from "vitest";

import {
  buildPayload, formError, INITIAL_FORM, normalizeTarget, redirectFormReducer, type Action, type RedirectForm,
} from "./customRedirectForm";

const run = (actions: Action[], from: RedirectForm = INITIAL_FORM) => actions.reduce(redirectFormReducer, from);
const form = (name: string, target: string, botCheck = false): RedirectForm => ({ ...INITIAL_FORM, name, target, botCheck });

describe("normalizeTarget", () => {
  // Same table as service/tests/test_tracking_links.py case_target_normalization.
  it.each<[string, string | null]>([
    ["ofl.ink/nora", "https://ofl.ink/nora"],
    ["  ofl.ink/nora  ", "https://ofl.ink/nora"],
    ["www.example.com", "https://www.example.com"],
    ["ofl.ink:8080/x", "https://ofl.ink:8080/x"],
    ["//ofl.ink/x", "https://ofl.ink/x"],
    ["https://ofl.ink/nora", "https://ofl.ink/nora"],
    ["http://example.com/a?b=c", "http://example.com/a?b=c"],
    ["HTTPS://Example.com", "HTTPS://Example.com"],
    ["javascript:alert(1)", null],
    ["JavaScript:alert(1)", null],
    ["javascript://ofl.ink/%0Aalert(1)", null],
    ["data:text/html,<b>x</b>", null],
    ["ftp://ofl.ink/x", null],
    ["mailto:a@b.com", null],
    ["nora", null],
    ["https://localhost/x", null],
    ["", null],
    ["   ", null],
    ["ofl.ink/a b", null],
    ["https://ofl.ink:99999/x", null],
    ["a".repeat(1990) + ".com/xxxxxxxxxx", null],
  ])("%s", (raw, want) => {
    expect(normalizeTarget(raw)).toBe(want);
  });
});

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
    ["scheme-less target normalized", form(" Bio ", "ofl.ink/nora"), true, null,
      { name: "Bio", target_url: "https://ofl.ink/nora", bot_check: false }],
    ["bot check sent when available", form("Bio", "ofl.ink/i", true), true, null,
      { name: "Bio", target_url: "https://ofl.ink/i", bot_check: true }],
    ["bot check dropped when unavailable", form("Bio", "ofl.ink/i", true), false, null,
      { name: "Bio", target_url: "https://ofl.ink/i", bot_check: false }],
    ["name required", form("  ", "ofl.ink/i"), true, "Name is required.", null],
    ["javascript: refused", form("x", "javascript:alert(1)"), true, "Target must be a web address, e.g. ofl.ink/name.", null],
    ["no dotted host refused", form("x", "nora"), true, "Target must be a web address, e.g. ofl.ink/name.", null],
  ])("%s", (_n, f, available, err, payload) => {
    expect(formError(f)).toBe(err);
    expect(buildPayload(f, available)).toEqual(payload);
  });
});
