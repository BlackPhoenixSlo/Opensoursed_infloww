import { describe, expect, it } from "vitest";

import {
  buildBody, canSave, derive, initRuleEditor, ruleEditorReducer as reduce, type RuleEditorAction, type RuleEditorState,
} from "@/components/automations/ruleEditorForm";
import { LIST_KEY, listItems, type Kind, type SendGap } from "@/components/compose/payloadRules";
import { blankRow, buildPayload, type Row } from "@/components/compose/premadeRows";
import type { VaultMedia } from "@/lib/relay";

const KINDS: [Kind, string, string][] = [["auto_posts", "posts", "messages"], ["mass_premade", "messages", "posts"]];

const run = (s: RuleEditorState, ...actions: RuleEditorAction[]) => actions.reduce(reduce, s);
const rule = (payload: Record<string, unknown>, extra: Record<string, unknown> = {}) =>
  ({ name: "Feed", every_seconds: 7200, is_enabled: true, payload, ...extra });
const patch = (p: Partial<Row>): RuleEditorAction => ({ type: "row", a: { type: "patch", patch: p } });
const caption = (text: string): RuleEditorAction => patch({ texts: [text] });
const edit = (text: string): RuleEditorAction => ({ type: "raw", a: { type: "edit", text } });
const media = (id: number) => ({ id, type: "photo" }) as VaultMedia;

describe.each(KINDS)("canSave from Raw JSON (%s)", (kind, own, other) => {
  it("lists into the kind's own key", () => expect(LIST_KEY[kind]).toBe(own));
  // A message also needs an audience (the "Auto Mass audience gate" table): every one-message mass row below has one.
  const aud = kind === "mass_premade" ? `, "user_lists": ["fans"]` : "";

  // An item counts when it would send: a message needs text (the backend skips a text-less mass, `no_text`), a post
  // text or media (`empty_post`). Only the kind's own list counts.
  it.each<[string, string, boolean, boolean]>([
    ["valid", `{ "${own}": [ { "text": "Hello"${aud} } ] }`, true, true],
    ["a texts pool", `{ "${own}": [ { "texts": [" ", "Yo"]${aud} } ] }`, true, true],
    ["other kind's list", `{ "${other}": [ { "text": "x" } ], "${own}": [] }`, false, false],
    ["unparseable", `{ "${own}": [ {` , false, false],
    ["null list", `{ "${own}": null }`, false, false],
    ["{} list", `{ "${own}": {} }`, false, false],
    ["blank buffer", "   ", false, false],
    ["whitespace-only item", `{ "${own}": [ { "text": "   " } ] }`, false, false],
    ["[{}]", `{ "${own}": [ {} ] }`, false, false],
    ["[null]", `{ "${own}": [ null ] }`, false, false],
    ["media only", `{ "${own}": [ { "media_files": [1] } ] }`, true, false],
    ["string media id only", `{ "${own}": [ { "media_files": ["42"] } ] }`, true, false],
    ["folder only", `{ "${own}": [ { "media_folder_id": 3 } ] }`, true, false],
    ["a funnel message (its opener is the text)", `{ "${own}": [ { "funnel_id": 3, "user_lists": ["fans"] } ] }`,
      false, true],
    ["an empty first item, a usable second", `{ "${own}": [ {}, { "text": "B"${aud} } ] }`, true, true],
    ["leading BOM", `﻿{ "${own}": [ { "text": "Hello"${aud} } ] }`, true, true],
  ])("%s", (_name, text, wantPosts, wantMass) => {
    expect(canSave(run(initRuleEditor(kind, null), { type: "toRaw" }, edit(text))))
      .toBe(kind === "auto_posts" ? wantPosts : wantMass);
  });

  it("unparseable after valid keeps the last valid value but is not savable", () => {
    const s = run(initRuleEditor(kind, null), { type: "toRaw" }, edit(`{ "${own}": [ { "text": "Hello"${aud} } ] }`), edit("{"));
    expect(derive(s).payload).toEqual(JSON.parse(`{ "${own}": [ { "text": "Hello"${aud} } ] }`));
    expect(canSave(s)).toBe(false);
  });
});

describe.each(KINDS)("the one popup (%s)", (kind, own) => {
  // A saved message needs an audience to save (payloadRules `massReaches`).
  const aud = kind === "mass_premade" ? { user_lists: ["fans"] } : {};
  it("new: the form view, Create waits for text", () => {
    const s = initRuleEditor(kind, null);
    expect(derive(s).view).toBe("form");
    expect(canSave(s)).toBe(false);
    expect(derive(s).wait).toBe("content");
    expect(buildBody(s)).toBeNull();
    expect(canSave(run(s, caption("   ")))).toBe(false);
    expect(canSave(run(s, caption("Hi")))).toBe(true);
  });

  it("media alone: a post can go, a message waits for text (the backend skips a text-less mass)", () => {
    const s = run(initRuleEditor(kind, null), patch({ media: [media(5)] }));
    expect(derive(s).wait).toBe(kind === "auto_posts" ? null : "content");
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

  it("a key the form doesn't hold: the legacy view, saved untouched byte for byte", () => {
    const stored = { [own]: [{ text: "hi", unknown_knob: 7, ...aud }], top_level_extra: true, dry_run: true };
    const s = initRuleEditor(kind, rule(stored));
    expect(s).toMatchObject({ name: "Feed", intervalValue: 2, intervalUnit: "hours", enabled: true, dryRun: true });
    expect(derive(s).view).toBe("legacy");
    expect(buildBody(s)!.payload).toBe(stored);
  });

  it("a key the form doesn't hold is never rebuilt from the row (the row can't become the content)", () => {
    const stored = { [own]: [{ text: "hi", unknown_knob: 7, ...aud }] };
    const s = run(initRuleEditor(kind, rule(stored)), caption("new"));
    expect(derive(s).view).toBe("legacy");
    expect(derive(s).payload).toEqual(stored);
    expect(buildBody(s)!.payload).toBe(stored);
  });

  it("Raw JSON shows the form's edits; back to the form re-seeds it from the buffer", () => {
    let s = run(initRuleEditor(kind, null), caption("from form"), { type: "toRaw" });
    expect(derive(s).view).toBe("raw");
    expect(JSON.parse(s.raw.text)[own][0].text).toBe("from form");
    s = run(s, edit(`{ "${own}": [ { "text": "from json" } ] }`), { type: "toForm" });
    expect(derive(s).view).toBe("form");
    expect(s.row.texts).toEqual(["from json"]);
    expect(derive(s).payload).toEqual({ [own]: [{ text: "from json" }] });
  });

  it("Composer while already on the form keeps the row's edits", () => {
    const s = run(initRuleEditor(kind, null), caption("kept"), { type: "toForm" });
    expect(s.row.texts).toEqual(["kept"]);
  });

  it("a key added in Raw JSON sends the rule to the legacy notice on Composer", () => {
    const s = run(initRuleEditor(kind, null), caption("x"), { type: "toRaw" },
      edit(`{ "${own}": [ { "text": "x", "excluded_users": [5] } ] }`), { type: "toForm" });
    expect(derive(s).view).toBe("legacy");
    expect(derive(s).payload).toEqual({ [own]: [{ text: "x", excluded_users: [5] }] });
  });

  it("an empty form opens Raw JSON as its one item (defaults kept, nothing lost on the way back)", () => {
    const over: Partial<Row> = kind === "mass_premade" ? { price: "5", includes: ["42"] } : { price: "5", hoursToLive: "6" };
    const s = run(initRuleEditor(kind, null), patch(over), { type: "toRaw" });
    expect(JSON.parse(s.raw.text)).toEqual(buildPayload({ ...blankRow(), ...over }, kind));
    const back = run(s, { type: "toForm" });
    expect(derive(back).view).toBe("form");
    expect(back.row).toMatchObject(over);
  });

  it("an unparseable buffer stays in Raw JSON on Composer", () => {
    const s = run(initRuleEditor(kind, null), { type: "toRaw" }, edit("{"), { type: "toForm" });
    expect(derive(s).view).toBe("raw");
    expect(s.raw.text).toBe("{");
  });

  it("a failed save shows its error", () => {
    const s = run(initRuleEditor(kind, null), { type: "raw", a: { type: "fail", error: "relay down" } });
    expect(s.raw.error).toBe("relay down");
  });
});

// F1: the form only opens on a payload it can hold losslessly (payloadToRow → buildPayload is the same payload, key
// order aside). Anything else would be rewritten by the first edit — and a dropped audience key sends to other fans.
describe("form view only on a lossless round trip", () => {
  const FULL_MASS: Partial<Row> = {
    texts: ["a", "b"], media: [media(1), media(2)], folderId: "7", mediaCount: "2", price: "9.99", onlineOnly: true,
    unsendAfterHours: "8", includes: ["fans", "42"], excludes: ["43"], excludeLastChatHours: "3",
    excludeRepliedHours: "0", excludeInboundHours: "4", unreadLimit: "10", recentChatHours: "5", recentChatLimit: "20",
  };
  const FULL_POST: Partial<Row> = {
    texts: ["hello"], media: [media(11)], folderId: "7", mediaCount: "3", price: "12",
    previewMedia: [media(21)], previewFolderId: "8", previewCount: "1", hoursToLive: "48",
  };
  const built = (over: Partial<Row>, kind: Kind) => buildPayload({ ...blankRow(), ...over }, kind)!;
  const m = (item: Record<string, unknown>, top: Record<string, unknown> = {}) =>
    ({ messages: [{ text: "hi", user_lists: ["fans"], ...item }], ...top });
  const p = (item: Record<string, unknown>, top: Record<string, unknown> = {}) => ({ posts: [{ text: "hi", ...item }], ...top });

  it.each<[string, Kind, Record<string, unknown>, "form" | "legacy"]>([
    // New / empty rules are the form.
    ["{} (new rule)", "mass_premade", {}, "form"],
    ["an empty messages list", "mass_premade", { messages: [] }, "form"],
    ["an empty posts list", "auto_posts", { posts: [] }, "form"],
    ["no items but another key", "auto_posts", { posts: [], resend_count: 2 }, "legacy"],
    // What the form itself builds is the form.
    ["a form-built full message", "mass_premade", built(FULL_MASS, "mass_premade"), "form"],
    ["a form-built default message", "mass_premade", built({ texts: ["hi"] }, "mass_premade"), "form"],
    ["a form-built full post", "auto_posts", built(FULL_POST, "auto_posts"), "form"],
    ["the same, keys in another order", "mass_premade", { messages: [{ user_lists: ["fans"], text: "hi" }] }, "form"],
    // F2: an explicit 0 on the default-on guards round-trips (guard off).
    ["exclude_replied_hours 0", "mass_premade", m({ exclude_replied_hours: 0 }), "form"],
    ["exclude_inbound_hours 0", "mass_premade", m({ exclude_inbound_hours: 0 }), "form"],
    // mass_premade `_SEND_KEYS` the form doesn't hold → legacy.
    ["previews", "mass_premade", m({ media_files: [1], previews: [1] }), "legacy"],
    ["filters (online)", "mass_premade", m({ filters: { online: 1 } }), "legacy"],
    ["included_users", "mass_premade", m({ included_users: [5] }), "legacy"],
    ["excluded_users", "mass_premade", m({ excluded_users: [5] }), "legacy"],
    ["list_ids", "mass_premade", m({ list_ids: [7] }), "legacy"],
    ["exclude_list_ids", "mass_premade", m({ exclude_list_ids: [7] }), "legacy"],
    ["funnel_id", "mass_premade", m({ funnel_id: 3 }), "legacy"],
    ["funnel_name", "mass_premade", m({ funnel_name: "strokes" }), "legacy"],
    ["funnel", "mass_premade", m({ funnel: "strokes" }), "legacy"],
    // Values the form would rewrite → legacy.
    ["a string media id", "mass_premade", m({ media_files: ["42"] }), "legacy"],
    ["a string media id (post)", "auto_posts", p({ media_files: [1, "42"] }), "legacy"],
    ["text + texts together", "mass_premade", m({ texts: ["a", "b"] }), "legacy"],
    ["a one-entry texts pool", "auto_posts", { posts: [{ texts: ["solo"] }] }, "legacy"],
    ["an untrimmed caption", "auto_posts", { posts: [{ text: " hi " }] }, "legacy"],
    ["a string price", "mass_premade", m({ price: "12" }), "legacy"],
    ["price 0", "auto_posts", p({ price: 0 }), "legacy"],
    ["online_only false", "mass_premade", m({ online_only: false }), "legacy"],
    ["exclude_last_chat_hours 0", "mass_premade", m({ exclude_last_chat_hours: 0 }), "legacy"],
    ["a built-in name in excluded_user_lists", "mass_premade", m({ excluded_user_lists: ["following"] }), "legacy"],
    ["a fractional media_count", "auto_posts", p({ media_files: [1], media_count: 2.5 }), "legacy"],
    ["media_count with no pool", "auto_posts", p({ media_count: 2 }), "legacy"],
    ["a string hours_to_live", "auto_posts", p({ hours_to_live: "6" }), "legacy"],
    ["media_claims (post)", "auto_posts", p({ media_claims: [{ id: 1 }] }), "legacy"],
    ["a free post's preview pool", "auto_posts", p({ preview_media_files: [3] }), "legacy"],
    ["an unknown item key", "mass_premade", m({ future_knob: 1 }), "legacy"],
    ["an unknown top-level key", "mass_premade", m({}, { top: "kept" }), "legacy"],
    ["the other kind's list too", "auto_posts", p({}, { messages: [{ text: "x" }] }), "legacy"],
    ["[null]", "mass_premade", { messages: [null] }, "legacy"],
    // Older multi-item / timed rules stay legacy.
    ["two messages", "mass_premade", { messages: [{ text: "a" }, { text: "b" }] }, "legacy"],
    ["a resend", "mass_premade", m({ resend_count: 1, resend_after_hours: 24 }), "legacy"],
    ["a delay", "auto_posts", p({ delay_minutes: 30 }), "legacy"],
    ["a repost cycle", "auto_posts", p({}, { resend_count: 2, resend_after_hours: 24 }), "legacy"],
    ["resend_count 0", "mass_premade", m({ resend_count: 0 }), "legacy"],
  ])("%s (%s) → %s", (_name, kind, stored, want) => {
    const s = initRuleEditor(kind, rule(stored));
    expect(derive(s).view).toBe(want);
    // Whichever view: Save untouched sends the stored payload object itself.
    if (canSave(s)) expect(buildBody(s)!.payload).toBe(s.stored!.payload);
  });
});

// F3: a mass form that reaches nobody can't be saved (the backend skips every run, `empty_audience`).
describe("Auto Mass audience gate", () => {
  const form = (...actions: RuleEditorAction[]) => run(initRuleEditor("mass_premade", null), caption("hi"), ...actions);
  const none = patch({ includes: [] });
  const off = patch({ onlineOnly: false });
  it.each<[string, RuleEditorAction[], SendGap | null]>([
    ["default: All fans + Following", [], null],
    ["one custom list", [none, { type: "row", a: { type: "toggleListInclude", id: "42" } }], null],
    // D5: the backend would send online_only alone, but OF's `userLists: []` + online shape is unverified.
    ["no list, online only (the default chip)", [none], "online"],
    ["no list, online off", [none, off], "audience"],
    ["no list, only an exclude list", [none, off, { type: "row", a: { type: "toggleListExclude", id: "9" } }], "audience"],
    // D5: the default Online only chip with no list waits, whatever the includes; off, the includes reach.
    ["no list, include chatted-with (online on)", [none, patch({ recentChatHours: "24" })], "online"],
    ["no list, include chatted-with", [none, off, patch({ recentChatHours: "24" })], null],
    ["no list, include unread (online on)", [none, patch({ unreadLimit: "5" })], "online"],
    ["no list, include unread", [none, off, patch({ unreadLimit: "5" })], null],
    ["no list, recent-chat cap alone", [none, off, patch({ recentChatLimit: "5" })], "audience"],
    ["no list and no text: text first", [none, caption("")], "content"],
  ])("%s → %s", (_name, actions, want) => {
    const s = form(...actions);
    expect(derive(s).wait).toBe(want);
    expect(canSave(s)).toBe(want === null);
  });

  // R7 / D5: Raw JSON and the legacy view judge a message by the same per-item rules (payloadRules `sendGap`).
  it.each<[string, string, SendGap | null]>([
    ["no audience", `{ "messages": [ { "text": "hi" } ] }`, "audience"],
    ["an unknown key is no audience", `{ "messages": [ { "text": "x" } ], "note": 1 }`, "audience"],
    ["two messages, neither reaches anyone", `{ "messages": [ { "text": "a" }, { "text": "b" } ] }`, "audience"],
    ["user_lists", `{ "messages": [ { "text": "hi", "user_lists": ["fans"] } ] }`, null],
    ["included_users", `{ "messages": [ { "text": "hi", "included_users": [5] } ] }`, null],
    ["fan_ids (never forwarded)", `{ "messages": [ { "text": "hi", "fan_ids": [5] } ] }`, "audience"],
    ["online_only alone", `{ "messages": [ { "text": "hi", "online_only": true } ] }`, "online"],
    ["filters.online alone", `{ "messages": [ { "text": "hi", "filters": { "online": 1 } } ] }`, "online"],
    ["online + a list", `{ "messages": [ { "text": "hi", "online_only": true, "user_lists": ["fans"] } ] }`, null],
    ["a second message online without a list", `{ "messages": [ { "text": "a", "user_lists": ["fans"] }, `
      + `{ "text": "b", "online_only": true } ] }`, "online"],
    ["paid with no media (D6: a warning only)", `{ "messages": [ { "text": "hi", "price": 5, "user_lists": ["fans"] } ] }`, null],
  ])("Raw JSON: %s → %s", (_name, text, want) => {
    const s = run(form(none, off), { type: "toRaw" }, edit(text));
    expect(derive(s).view).toBe("raw");
    expect(derive(s).wait).toBe(want);
  });

  it("an Auto Post has no audience", () => {
    expect(canSave(run(initRuleEditor("auto_posts", null), caption("hi"), patch({ includes: [] })))).toBe(true);
  });
});

// R8 / D6: a paid post with no media never sends (auto_posts `paid_no_media`): Create waits. A paid message with
// none only warns (OF refusing it is unverified for a mass).
describe.each(KINDS)("PPV with no image (%s)", (kind) => {
  const paid = kind === "auto_posts" ? "ppv" : null;
  it.each<[string, RuleEditorAction[], SendGap | null, "ppv" | null]>([
    ["free, no media", [caption("hi")], null, null],
    ["paid, no media", [caption("hi"), patch({ price: "5" })], paid, kind === "mass_premade" ? "ppv" : null],
    ["paid with an image", [caption("hi"), patch({ price: "5", media: [media(5)] })], null, null],
    ["paid with a folder", [caption("hi"), patch({ price: "5", folderId: "3" })], null, null],
  ])("%s → %s / %s", (_name, actions, wait, advice) => {
    const s = run(initRuleEditor(kind, null), ...actions);
    expect(derive(s)).toMatchObject({ wait, advice });
    expect(canSave(s)).toBe(wait === null);
  });
});

it("T3: a post price as text never saves (auto_posts `price > 0` raises on a string)", () => {
  const s = run(initRuleEditor("auto_posts", null), { type: "toRaw" },
    edit(`{ "posts": [ { "text": "hi", "price": "12", "media_files": [1] } ] }`));
  expect(derive(s).wait).toBe("price");
  expect(buildBody(s)).toBeNull();
});

// U2: a stored payload that would wait (it never sent) still saves untouched — a rename, a new interval or the Dry
// run switch changes nothing it sends. Touch its content and the gate is back.
describe("an untouched stored payload never blocks Save", () => {
  it.each<[string, Kind, Record<string, unknown>, "form" | "legacy", RuleEditorAction, SendGap]>([
    ["a mass that reaches nobody", "mass_premade", { messages: [{ text: "hi" }] }, "form", caption("other"), "audience"],
    ["a legacy mass that reaches nobody", "mass_premade", { messages: [{ text: "x" }], note: 1 }, "legacy",
      edit(`{ "messages": [ { "text": "y" } ], "note": 1 }`), "audience"],
    ["D5: online only, no list", "mass_premade", { messages: [{ text: "hi", online_only: true }] }, "form",
      caption("other"), "online"],
    ["a post price as text", "auto_posts", { posts: [{ text: "hi", price: "12", media_files: [1] }] }, "legacy",
      edit(`{ "posts": [ { "text": "yo", "price": "12", "media_files": [1] } ] }`), "price"],
    ["a paid post with no media", "auto_posts", { posts: [{ text: "hi", price: 12 }] }, "form", caption("other"), "ppv"],
  ])("%s", (_name, kind, stored, view, touch, wait) => {
    const s = initRuleEditor(kind, rule(stored));
    expect(derive(s)).toMatchObject({ view, wait: null });
    // Rename, reschedule, Dry run: the stored payload object goes back (with the switch's dry_run when flipped).
    const renamed = buildBody(run(s, { type: "field", patch: { name: "Renamed", intervalValue: 3 } }))!;
    expect(renamed).toMatchObject({ name: "Renamed", every_seconds: 3 * 3600 });
    expect(renamed.payload).toBe(stored);
    expect(buildBody(run(s, { type: "field", patch: { dryRun: true } }))!.payload).toEqual({ ...stored, dry_run: true });
    // Through Raw JSON untouched: still the stored payload.
    expect(derive(run(s, { type: "toRaw" })).wait).toBeNull();
    // Its content touched: judged like any payload.
    const t = touch.type === "raw" ? run(s, { type: "toRaw" }, touch) : run(s, touch);
    expect(derive(t).wait).toBe(wait);
    expect(buildBody(t)).toBeNull();
  });
});

// V2: a dry-run rule switched live is judged like any payload, even untouched.
describe("Dry run turned off on an untouched stored rule re-applies the gate", () => {
  it.each<[string, Kind, Record<string, unknown>, SendGap]>([
    ["D5 online only, no list", "mass_premade", { messages: [{ text: "hi", online_only: true }], dry_run: true }, "online"],
    ["a mass that reaches nobody", "mass_premade", { messages: [{ text: "hi" }], dry_run: true }, "audience"],
    ["a paid post with no media", "auto_posts", { posts: [{ text: "hi", price: 12 }], dry_run: true }, "ppv"],
    ["a post price as text", "auto_posts", { posts: [{ text: "hi", price: "12", media_files: [1] }], dry_run: true }, "price"],
  ])("%s", (_name, kind, stored, wait) => {
    const s = initRuleEditor(kind, rule(stored));
    expect(derive(s)).toMatchObject({ wait: null, sameAsStored: true });
    expect(buildBody(run(s, { type: "field", patch: { name: "Renamed" } }))!.payload).toBe(stored);
    const live = run(s, { type: "field", patch: { dryRun: false } });
    expect(derive(live).wait).toBe(wait);
    expect(buildBody(live)).toBeNull();
  });

  it.each<[string, Kind, Record<string, unknown>, SendGap]>([
    ["D5 online only, no list", "mass_premade", { messages: [{ text: "hi", online_only: true }] }, "online"],
    ["a paid post with no media", "auto_posts", { posts: [{ text: "hi", price: 12 }] }, "ppv"],
  ])("Enabled turned on, %s: gated too", (_name, kind, stored, wait) => {
    const s = initRuleEditor(kind, rule(stored, { is_enabled: false }));
    expect(derive(s).wait).toBeNull();
    expect(derive(run(s, { type: "field", patch: { name: "Renamed" } })).wait).toBeNull();
    const on = run(s, { type: "field", patch: { enabled: true } });
    expect(derive(on).wait).toBe(wait);
    expect(buildBody(on)).toBeNull();
    // Enabled on but still Dry run: not live, untouched passes.
    const dry = initRuleEditor(kind, rule({ ...stored, dry_run: true }, { is_enabled: false }));
    expect(derive(run(dry, { type: "field", patch: { enabled: true } })).wait).toBeNull();
  });

  it("a sendable dry-run rule switched live sends its payload without dry_run", () => {
    const stored = { messages: [{ text: "hi", user_lists: ["fans"] }], dry_run: true };
    const live = run(initRuleEditor("mass_premade", rule(stored)), { type: "field", patch: { dryRun: false } });
    expect(buildBody(live)!.payload).toEqual({ messages: [{ text: "hi", user_lists: ["fans"] }] });
  });
});

// A stored rule with an empty list opens as the blank row: untouched, rename / disable still save it as stored.
describe("an empty stored payload", () => {
  it.each<[Kind, Record<string, unknown>]>([
    ["mass_premade", { messages: [] }], ["auto_posts", { posts: [] }], ["auto_posts", {}],
  ])("%s %j: untouched rename sends it back; a typed caption is judged", (kind, stored) => {
    const s = initRuleEditor(kind, rule(stored, { is_enabled: false }));
    expect(derive(s)).toMatchObject({ view: "form", wait: null, sameAsStored: true });
    expect(buildBody(run(s, { type: "field", patch: { name: "Renamed" } }))!.payload).toBe(stored);
    expect(derive(run(s, caption("hi"))).sameAsStored).toBe(false);
  });

  it("an untouched non-empty stored form payload is the seeded object itself", () => {
    const s = initRuleEditor("mass_premade", rule({ messages: [{ text: "hi", user_lists: ["fans"] }] }));
    expect(derive(s).view).toBe("form");
    expect(derive(s).payload).toBe(s.raw.value);
  });

  it("a new rule's blank row is still the built payload (judged: no content)", () => {
    const s = initRuleEditor("mass_premade", null);
    expect(derive(s).wait).toBe("content");
  });
});

// F8: what the user didn't touch goes back exactly as stored.
describe("untouched Save keeps the stored rule", () => {
  const msg = { messages: [{ text: "hi", user_lists: ["fans"] }] };

  it.each<[string, number | null]>([["90 s", 90], ["45 s", 45], ["no interval", null], ["2 h", 7200]])(
    "interval %s: not sent until the interval fields change", (_name, every) => {
      const s = initRuleEditor("mass_premade", rule(msg, { every_seconds: every }));
      expect(buildBody(s)!.every_seconds).toBeUndefined();
      const t = run(s, { type: "field", patch: { intervalValue: 3, intervalUnit: "hours" } });
      expect(buildBody(t)!.every_seconds).toBe(10800);
    });

  it.each<[string, Record<string, unknown>]>([
    ["dry_run false", { ...msg, dry_run: false }],
    ["dry_run true first", { dry_run: true, ...msg }],
    ["dry_run as a string", { ...msg, dry_run: "yes" }],
  ])("%s: the stored payload object, byte for byte", (_name, stored) => {
    const body = buildBody(initRuleEditor("mass_premade", rule(stored)))!;
    expect(body.payload).toBe(stored);
    expect(JSON.stringify(body.payload)).toBe(JSON.stringify(stored));
  });

  it("an edit reverted, or a trip through Raw JSON, is no change", () => {
    const stored = { ...msg, dry_run: false };
    const s0 = initRuleEditor("mass_premade", rule(stored));
    expect(buildBody(run(s0, caption("other"), caption("hi")))!.payload).toBe(stored);
    expect(buildBody(run(s0, { type: "toRaw" }))!.payload).toBe(stored);
  });

  it("Dry run flipped, or the message changed: the payload is rebuilt with the switch's dry_run", () => {
    const stored = { ...msg, dry_run: false };
    const s0 = initRuleEditor("mass_premade", rule(stored));
    expect(buildBody(run(s0, { type: "field", patch: { dryRun: true } }))!.payload).toEqual({ ...msg, dry_run: true });
    expect(buildBody(run(s0, caption("new")))!.payload).toEqual({ messages: [{ text: "new", user_lists: ["fans"] }] });
  });

  it("name: untouched → not sent (the stored one stays, whitespace and all); edited → trimmed", () => {
    const s = initRuleEditor("mass_premade", rule(msg, { name: "  Feed  " }));
    expect(buildBody(s)!.name).toBeUndefined();
    expect(buildBody(run(s, { type: "field", patch: { name: "  Evening " } }))!.name).toBe("Evening");
    expect(buildBody(run(s, { type: "field", patch: { name: "  " } }))!.name).toBeUndefined();
  });
});

describe("Auto Mass stored audience round-trip", () => {
  it.each<[string, Record<string, unknown>, "form" | "legacy"]>([
    ["audience and chat knobs", { messages: [{ text: "old", online_only: true, user_lists: ["fans", "following", "42"],
      excluded_user_lists: ["43"], exclude_last_chat_hours: 1, exclude_replied_hours: 2,
      exclude_inbound_hours: 3, recent_chat_hours: 4, recent_chat_limit: 5, unread_limit: 6 }] }, "form"],
    ["unknown legacy keys", { messages: [{ text: "old", user_lists: ["fans"], future_knob: { x: 1 } }], top: "kept" }, "legacy"],
  ])("unedited %s round-trips byte-identically", (_name, stored, view) => {
    const s = initRuleEditor("mass_premade", rule(stored));
    expect(derive(s).view).toBe(view);
    expect(JSON.stringify(buildBody(s)!.payload)).toBe(JSON.stringify(stored));
  });
});

describe.each<[Kind, Record<string, unknown>]>([
  ["auto_posts", { posts: [{ text: "A" }, { text: "B", delay_minutes: 30 }] }],
  ["auto_posts", { posts: [{ text: "A" }], resend_count: 2, resend_after_hours: 24 }],
  ["mass_premade", { messages: [{ text: "A", resend_count: 2, resend_after_hours: 24, user_lists: ["fans"] }] }],
])("legacy %s %j", (kind, stored) => {
  it("is the legacy view, saves as stored, Raw JSON shows it, Composer goes back to the notice", () => {
    const s = initRuleEditor(kind, rule(stored));
    expect(derive(s).view).toBe("legacy");
    expect(buildBody(s)!.payload).toEqual(stored);
    const r = run(s, { type: "toRaw" });
    expect(JSON.parse(r.raw.text)).toEqual(stored);
    expect(derive(run(r, { type: "toForm" })).view).toBe("legacy");
  });

  it("a one-item rewrite in Raw JSON opens the form", () => {
    const own = LIST_KEY[kind];
    const s = run(initRuleEditor(kind, rule(stored)), { type: "toRaw" }, edit(`{ "${own}": [ { "text": "A" } ] }`), { type: "toForm" });
    expect(derive(s).view).toBe("form");
    expect(s.row.texts).toEqual(["A"]);
  });
});
