import { describe, expect, it } from "vitest";

import {
  formHoldNotice, formHoldReason, MASS_PPV_ADVICE, samePayload, summarize, waitHelp, type FormHoldReason,
} from "@/components/automations/readyMadeContent";
import type { Kind, SendGap } from "@/components/compose/payloadRules";
describe("summarize", () => {
  it.each<[string, Kind, Record<string, unknown>, string | null]>([
    ["empty", "auto_posts", {}, null],
    ["other kind's list", "auto_posts", { messages: [{ text: "x" }] }, null],
    // One Auto Post reads its price, then "deletes after Nh" when set; a legacy list keeps its count.
    ["one free post", "auto_posts", { posts: [{ text: " Hello " }] }, "Free · Hello"],
    ["one paid post", "auto_posts", { posts: [{ texts: ["Hey", "Yo"], price: 12 }] }, "$12 · Hey"],
    ["auto-delete", "auto_posts", { posts: [{ text: "Hi", hours_to_live: 6 }] }, "Free · Hi · deletes after 6h"],
    ["paid, auto-delete, no text", "auto_posts", { posts: [{ price: 9.99, hours_to_live: 1.5 }] }, "$9.99 · deletes after 1.5h"],
    ["hours_to_live 0 is keep", "auto_posts", { posts: [{ text: "Hi", hours_to_live: 0 }] }, "Free · Hi"],
    ["reposts and a texts pool", "auto_posts", { posts: [{ texts: ["A", "B"], hours_to_live: 6 }, {}], resend_count: 2 },
      "2 posts · reposts ×2 · A"],
    ["a messages list on a post rule is no hours read", "mass_premade", { messages: [{ text: "Hi", hours_to_live: 6 }] }, "Free · Hi"],
    // One Auto Mass message reads its price: "Free · …" / "$12 · …"; a legacy list keeps its count.
    ["one free message", "mass_premade", { messages: [{ text: "Hi" }] }, "Free · Hi"],
    ["one paid message", "mass_premade", { messages: [{ texts: ["Hey", "Yo"], price: 12 }] }, "$12 · Hey"],
    ["cents price", "mass_premade", { messages: [{ text: "Hi", price: 9.99 }] }, "$9.99 · Hi"],
    ["price 0 is free", "mass_premade", { messages: [{ price: 0 }] }, "Free"],
    // The backend charges a numeric string (`price or 0` → OF): never "Free".
    ["a string price charges", "mass_premade", { messages: [{ text: "Hi", price: "12" }] }, "$12 · Hi"],
    // The audience as the chips name it; online only is a filter, not an audience.
    ["audience + chat skip", "mass_premade", { messages: [{ text: "caption", price: 12, user_lists: ["fans", "following"],
      online_only: true, exclude_last_chat_hours: 1 }] }, "$12 · caption · All fans + Following · online only · skips chatted 1h"],
    ["Following + an included custom list", "mass_premade", { messages: [{ text: "caption", user_lists: ["following", "42"] }] },
      "Free · caption · Following + 1 list"],
    ["excluded lists and auto-unsend", "mass_premade", { messages: [{ text: "Hi", user_lists: ["fans", "1", "2"],
      excluded_user_lists: ["3"], unsend_after_hours: 8 }] }, "Free · Hi · All fans + 2 lists · excl. 1 list · unsends after 8h"],
    // Auto Mass reads resend_count per message (mass_premade.py), Auto Post per list (auto_posts.py).
    ["mass resends per message", "mass_premade", { messages: [{ text: "A", resend_count: 2, resend_after_hours: 24 }] },
      "Free · resends ×2 · A"],
    ["mass ignores a top-level resend_count", "mass_premade", { messages: [{ text: "A" }], resend_count: 2 }, "Free · A"],
    // R6: the audience keys only Raw JSON sets are read too, never dropped from the line.
    ["Raw JSON audience keys", "mass_premade", { messages: [{ text: "Hi", included_users: [1, 2], list_ids: [7],
      filters: { online: 1, min_spent: 5 }, excluded_users: [3], exclude_list_ids: [8, 9] }] },
      "Free · Hi · 2 fans + 1 DB list · online only · filters · excl. 2 DB lists + 1 fan"],
    // fan_ids is never forwarded (mass_premade `_SEND_KEYS`): not read as fans.
    ["fan_ids and the chatted-with / unread includes", "mass_premade", { messages: [{ text: "Hi", fan_ids: [1],
      recent_chat_hours: 24, unread_limit: 5 }] }, "Free · Hi · chatted 24h + 5 unread"],
    ["[null]", "mass_premade", { messages: [null] }, "Free"],
    ["legacy two messages", "mass_premade", { messages: [{ text: "A", price: 5 }, { text: "B" }] }, "2 messages · A"],
  ])("%s", (_name, kind, payload, want) => {
    expect(summarize(payload, kind)).toBe(want);
  });
});

describe("samePayload", () => {
  it.each<[string, unknown, unknown, boolean]>([
    ["key order aside", { a: 1, b: { c: [1, 2], d: 2 } }, { b: { d: 2, c: [1, 2] }, a: 1 }, true],
    ["array order counts", { a: [1, 2] }, { a: [2, 1] }, false],
    ["a string is not a number", { a: 12 }, { a: "12" }, false],
    ["an extra key", { a: 1 }, { a: 1, b: undefined }, true],
    ["null vs a payload", null, {}, false],
  ])("%s", (_name, a, b, want) => {
    expect(samePayload(a as Record<string, unknown>, b as Record<string, unknown>)).toBe(want);
  });
});

// The full table (every key the form doesn't hold) is ruleEditorForm.test.ts "form view only on a lossless round trip".
describe("formHoldReason", () => {
  it.each<[string, Kind, Record<string, unknown>, FormHoldReason | null]>([
    ["empty", "mass_premade", {}, null],
    ["one message the form holds", "mass_premade", { messages: [{ text: "a", unsend_after_hours: 8, exclude_last_chat_hours: 1 }] }, null],
    ["resend_count 0 / delay 0: timer keys the form doesn't hold", "mass_premade",
      { messages: [{ text: "a", resend_count: 0, delay_minutes: 0 }] }, "timed"],
    ["two messages", "mass_premade", { messages: [{ text: "a" }, { text: "b" }] }, "multi"],
    ["two messages with resends: the list says why", "mass_premade",
      { messages: [{ text: "a", resend_count: 2 }, { text: "b" }] }, "multi"],
    ["resend", "mass_premade", { messages: [{ text: "a", resend_count: 2, resend_after_hours: 24 }] }, "timed"],
    ["resend count as a string", "mass_premade", { messages: [{ text: "a", resend_count: "1" }] }, "timed"],
    ["delay", "mass_premade", { messages: [{ text: "a", delay_minutes: 30 }] }, "timed"],
    ["excluded_users", "mass_premade", { messages: [{ text: "a", excluded_users: [1] }] }, "settings"],
    ["filters", "mass_premade", { messages: [{ text: "a", user_lists: ["fans"], filters: { online: 1 } }] }, "settings"],
    ["[null]", "mass_premade", { messages: [null] }, "settings"],
    ["only the other kind's list", "mass_premade", { posts: [{ text: "a" }, { text: "b" }] }, "settings"],
    // Auto Mass reads resends per message: a top-level one is a key the form doesn't hold, not a timer.
    ["a top-level resend_count on a mass", "mass_premade", { messages: [{ text: "a" }], resend_count: 2 }, "settings"],
    // Auto Post: one post; an older list, its repost cycle (list-level) or a per-post delay → Raw JSON.
    ["empty post rule", "auto_posts", {}, null],
    ["one post", "auto_posts", { posts: [{ text: "a", price: 12, hours_to_live: 6, preview_media_files: [1] }] }, null],
    ["two posts", "auto_posts", { posts: [{ text: "a" }, { text: "b" }] }, "multi"],
    ["repost cycle", "auto_posts", { posts: [{ text: "a" }], resend_count: 2, resend_after_hours: 24 }, "timed"],
    ["per-post delay", "auto_posts", { posts: [{ text: "a", delay_minutes: 30 }] }, "timed"],
    ["a per-post resend_count (Auto Post reads the list's)", "auto_posts", { posts: [{ text: "a", resend_count: 2 }] }, "settings"],
    ["media_claims", "auto_posts", { posts: [{ text: "a", media_claims: [{ id: 1 }] }] }, "settings"],
  ])("%s %s", (_name, kind, payload, want) => {
    expect(formHoldReason(payload, kind)).toBe(want);
  });
});

describe("formHoldNotice", () => {
  it.each<[FormHoldReason, Kind, string]>([
    ["multi", "mass_premade", "Older multi-message rule — edit in Raw JSON."],
    ["multi", "auto_posts", "Older multi-post rule — edit in Raw JSON."],
    ["timed", "mass_premade", "Older rule with a resend or delay timer — edit in Raw JSON."],
    ["timed", "auto_posts", "Older rule with a repost or delay timer — edit in Raw JSON."],
    ["settings", "mass_premade", "Uses settings the Composer can't edit — edit in Raw JSON."],
  ])("%s %s", (reason, kind, want) => {
    expect(formHoldNotice(reason, kind)).toBe(want);
  });
});

describe("waitHelp", () => {
  it.each<[SendGap | null, "form" | "raw" | "legacy", Kind, string, string | null]>([
    [null, "form", "mass_premade", "Create", null],
    ["content", "form", "auto_posts", "Create", "Add text or media to enable Create."],
    ["content", "raw", "mass_premade", "Save changes", "Add at least one message with text to enable Save changes."],
    ["audience", "form", "mass_premade", "Create",
      "Pick who gets it (All fans, Following, a list, or chatted-with / unread in More settings) to enable Create."],
    ["audience", "legacy", "mass_premade", "Save changes", "Give the message an audience (user_lists, included_users, "
      + "list_ids, filters, recent_chat_hours, unread_limit) to enable Save changes."],
    ["online", "form", "mass_premade", "Create", "Online only filters an audience: pick All fans, Following or a list to enable Create."],
    ["online", "raw", "mass_premade", "Create",
      "An online filter (online_only, filters.online) needs a list in user_lists to enable Create."],
    ["price", "raw", "auto_posts", "Create", "The post's price must be a number, not text in quotes, to enable Create."],
    ["ppv", "form", "auto_posts", "Create", "A paid post needs an image: add one or a vault folder, or make it free, to enable Create."],
  ])("%s %s %s", (wait, view, kind, label, want) => {
    expect(waitHelp(wait, view, kind, label)).toBe(want);
  });

  it("the mass PPV advice names the fix", () => expect(MASS_PPV_ADVICE).toMatch(/add one/));
});
