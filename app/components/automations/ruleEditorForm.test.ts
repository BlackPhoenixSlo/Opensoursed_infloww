import { describe, expect, it } from "vitest";

import {
  buildBody, canSave, currentPayload, editorView, initRuleEditor, ruleEditorReducer as reduce,
  type RuleEditorAction, type RuleEditorState,
} from "@/components/automations/ruleEditorForm";
import { LIST_KEY, listItems, type Kind } from "@/components/compose/premadeRows";

const KINDS: [Kind, string, string][] = [["auto_posts", "posts", "messages"], ["mass_premade", "messages", "posts"]];

const run = (s: RuleEditorState, ...actions: RuleEditorAction[]) => actions.reduce(reduce, s);
const rule = (payload: Record<string, unknown>, extra: Record<string, unknown> = {}) =>
  ({ name: "Feed", every_seconds: 7200, is_enabled: true, payload, ...extra });
const caption = (text: string): RuleEditorAction => ({ type: "rows", a: { type: "patch", i: 0, patch: { texts: [text] } } });
const edit = (text: string): RuleEditorAction => ({ type: "raw", a: { type: "edit", text } });

describe.each(KINDS)("canSave from Raw JSON (%s)", (kind, own, other) => {
  it("lists into the kind's own key", () => expect(LIST_KEY[kind]).toBe(own));

  // Any array entry counts as content; only the kind's own list counts.
  it.each<[string, string, boolean]>([
    ["valid", `{ "${own}": [ { "text": "Hello" } ] }`, true],
    ["other kind's list", `{ "${other}": [ { "text": "x" } ], "${own}": [] }`, false],
    ["unparseable", `{ "${own}": [ {`, false],
    ["null list", `{ "${own}": null }`, false],
    ["{} list", `{ "${own}": {} }`, false],
    ["blank buffer", "   ", false],
    ["whitespace-only item", `{ "${own}": [ { "text": "   " } ] }`, true],
    ["[{}]", `{ "${own}": [ {} ] }`, true],
    ["[null]", `{ "${own}": [ null ] }`, true],
    ["leading BOM", `﻿{ "${own}": [ { "text": "Hello" } ] }`, true],
  ])("%s", (_name, text, want) => {
    expect(canSave(run(initRuleEditor(kind, null), { type: "toRaw" }, edit(text)))).toBe(want);
  });

  it("unparseable after valid keeps the last valid value but is not savable", () => {
    const s = run(initRuleEditor(kind, null), { type: "toRaw" }, edit(`{ "${own}": [ { "text": "Hello" } ] }`), edit("{"));
    expect(currentPayload(s)).toEqual({ [own]: [{ text: "Hello" }] });
    expect(canSave(s)).toBe(false);
  });
});

describe.each(KINDS)("the one popup (%s)", (kind, own) => {
  it("new: the form view, Create waits for text or media", () => {
    const s = initRuleEditor(kind, null);
    expect(editorView(s)).toBe("form");
    expect(canSave(s)).toBe(false);
    expect(buildBody(s)).toBeNull();
    expect(canSave(run(s, caption("   ")))).toBe(false);
    expect(canSave(run(s, caption("Hi")))).toBe(true);
  });

  it("a caption saves the one-item payload with the trigger fields", () => {
    const s = run(initRuleEditor(kind, null), caption("Hi"),
      { type: "field", patch: { name: "  Morning  ", intervalValue: 30, intervalUnit: "minutes", enabled: false } });
    const body = buildBody(s)!;
    expect(body).toMatchObject({ name: "Morning", every_seconds: 1800, is_enabled: false });
    expect(listItems(body.payload, kind)).toHaveLength(1);
    expect((body.payload[own] as { text: string }[])[0].text).toBe("Hi");
    expect(body.payload.dry_run).toBeUndefined();
  });

  it("Dry run rides on the payload; a blank name is left to the server / stored one", () => {
    const body = buildBody(run(initRuleEditor(kind, null), caption("Hi"), { type: "field", patch: { dryRun: true } }))!;
    expect(body.payload.dry_run).toBe(true);
    expect(body.name).toBeUndefined();
  });

  it("editing: seeds the fields; saving untouched keeps the stored payload byte for byte", () => {
    const stored = { [own]: [{ text: "hi", unknown_knob: 7 }], top_level_extra: true, dry_run: true };
    const s = initRuleEditor(kind, rule(stored));
    expect(s).toMatchObject({ name: "Feed", intervalValue: 2, intervalUnit: "hours", enabled: true, dryRun: true });
    expect(s.rows[0].texts).toEqual(["hi"]);
    expect(buildBody(s)!.payload).toEqual(stored);
  });

  it("editing a field of the post rebuilds the payload from the form", () => {
    const s = run(initRuleEditor(kind, rule({ [own]: [{ text: "hi", unknown_knob: 7 }] })), caption("new"));
    expect((currentPayload(s)![own] as Record<string, unknown>[])[0]).toEqual(expect.objectContaining({ text: "new" }));
    expect((currentPayload(s)![own] as Record<string, unknown>[])[0].unknown_knob).toBeUndefined();
  });

  it("Raw JSON shows the form's edits; back to the form re-seeds it from the buffer", () => {
    let s = run(initRuleEditor(kind, null), caption("from form"), { type: "toRaw" });
    expect(editorView(s)).toBe("raw");
    expect(JSON.parse(s.raw.text)[own][0].text).toBe("from form");
    s = run(s, edit(`{ "${own}": [ { "text": "from json" } ] }`), { type: "toForm" });
    expect(editorView(s)).toBe("form");
    expect(s.rows[0].texts).toEqual(["from json"]);
    expect(currentPayload(s)).toEqual({ [own]: [{ text: "from json" }] });
  });

  it("an empty form opens Raw JSON as {}", () => {
    expect(JSON.parse(run(initRuleEditor(kind, null), { type: "toRaw" }).raw.text)).toEqual({});
  });

  it("an unparseable buffer stays in Raw JSON on Composer", () => {
    const s = run(initRuleEditor(kind, null), { type: "toRaw" }, edit("{"), { type: "toForm" });
    expect(editorView(s)).toBe("raw");
    expect(s.raw.text).toBe("{");
  });

  it("a failed save shows its error", () => {
    const s = run(initRuleEditor(kind, null), { type: "raw", a: { type: "fail", error: "relay down" } });
    expect(s.raw.error).toBe("relay down");
  });
});

describe("Auto Mass stored audience round-trip", () => {
  it.each([
    ["audience and chat knobs", { messages: [{ text: "old", online_only: true, user_lists: ["fans", "following", "42"],
      excluded_user_lists: ["43"], exclude_last_chat_hours: 1, exclude_replied_hours: 2,
      exclude_inbound_hours: 3, recent_chat_hours: 4, recent_chat_limit: 5, unread_limit: 6 }] }],
    ["unknown legacy keys", { messages: [{ text: "old", user_lists: ["fans"], future_knob: { x: 1 } }], top: "kept" }],
  ])("unedited %s round-trips byte-identically", (_name, stored) => {
    const s = initRuleEditor("mass_premade", rule(stored));
    expect(JSON.stringify(buildBody(s)!.payload)).toBe(JSON.stringify(stored));
  });
});

describe.each<[Kind, Record<string, unknown>]>([
  ["auto_posts", { posts: [{ text: "A" }, { text: "B", delay_minutes: 30 }] }],
  ["auto_posts", { posts: [{ text: "A" }], resend_count: 2, resend_after_hours: 24 }],
  ["mass_premade", { messages: [{ text: "A", resend_count: 2, resend_after_hours: 24 }] }],
])("legacy %s %j", (kind, stored) => {
  it("is the legacy view, saves as stored, Raw JSON shows it, Composer goes back to the notice", () => {
    const s = initRuleEditor(kind, rule(stored));
    expect(editorView(s)).toBe("legacy");
    expect(buildBody(s)!.payload).toEqual(stored);
    const r = run(s, { type: "toRaw" });
    expect(JSON.parse(r.raw.text)).toEqual(stored);
    expect(editorView(run(r, { type: "toForm" }))).toBe("legacy");
  });

  it("a one-item rewrite in Raw JSON opens the form", () => {
    const own = LIST_KEY[kind];
    const s = run(initRuleEditor(kind, rule(stored)), { type: "toRaw" }, edit(`{ "${own}": [ { "text": "A" } ] }`), { type: "toForm" });
    expect(editorView(s)).toBe("form");
    expect(s.rows[0].texts).toEqual(["A"]);
  });
});
