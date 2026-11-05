import { describe, expect, it } from "vitest";

import { canSave, summarize } from "@/components/automations/readyMadeContent";
import { LIST_KEY, listItems, type Kind } from "@/components/compose/premadeRows";
import { initialRawJson, rawJsonReducer } from "@/lib/rawJsonReducer";
import { PAYLOAD_RAW } from "@/lib/rulePayload";

const reduce = rawJsonReducer(PAYLOAD_RAW);
/** The editor's raw state after Raw JSON is opened on an empty payload and `text` is typed. */
const typed = (text: string) => reduce(reduce(initialRawJson({}), { type: "open" }), { type: "edit", text });

const KINDS: [Kind, string, string][] = [["auto_posts", "posts", "messages"], ["mass_premade", "messages", "posts"]];

describe.each(KINDS)("canSave(%s)", (kind, own, other) => {
  it("lists into the kind's own key", () => expect(LIST_KEY[kind]).toBe(own));

  // Pins current behaviour: any array entry counts as content; only the kind's own list counts.
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
    expect(canSave(typed(text), kind)).toBe(want);
  });

  it("unparseable after valid keeps the last valid value but is not savable", () => {
    const s = reduce(typed(`{ "${own}": [ { "text": "Hello" } ] }`), { type: "edit", text: "{" });
    expect(listItems(s.value, kind)).toHaveLength(1);
    expect(canSave(s, kind)).toBe(false);
  });

  it("composer view (raw off) saves the kind's list", () => {
    expect(canSave(initialRawJson({ [own]: [{ text: "a" }] }), kind)).toBe(true);
    expect(canSave(initialRawJson({ [other]: [{ text: "a" }] }), kind)).toBe(false);
  });
});

describe("summarize", () => {
  it.each<[string, Kind, Record<string, unknown>, string | null]>([
    ["empty", "auto_posts", {}, null],
    ["other kind's list", "auto_posts", { messages: [{ text: "x" }] }, null],
    ["one post", "auto_posts", { posts: [{ text: " Hello " }] }, "1 post · Hello"],
    ["reposts and a texts pool", "auto_posts", { posts: [{ texts: ["A", "B"] }, {}], resend_count: 2 }, "2 posts · reposts ×2 · A"],
    ["one message", "mass_premade", { messages: [{ text: "Hi" }] }, "1 message · Hi"],
    ["[null]", "mass_premade", { messages: [null] }, "1 message"],
  ])("%s", (_name, kind, payload, want) => {
    expect(summarize(payload, kind)).toBe(want);
  });
});
