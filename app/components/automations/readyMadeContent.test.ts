import { describe, expect, it } from "vitest";

import { isLegacy, summarize } from "@/components/automations/readyMadeContent";
import type { Kind } from "@/components/compose/premadeRows";

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
    ["audience + chat skip", "mass_premade", { messages: [{ text: "caption", price: 12, user_lists: ["fans", "following"],
      online_only: true, exclude_last_chat_hours: 1 }] }, "$12 · caption · Fans + Online · skips chatted 1h"],
    ["Following + included custom lists", "mass_premade", { messages: [{ text: "caption", user_lists: ["following", "42"] }] },
      "Free · caption · Following + Lists"],
    ["[null]", "mass_premade", { messages: [null] }, "Free"],
    ["legacy two messages", "mass_premade", { messages: [{ text: "A", price: 5 }, { text: "B" }] }, "2 messages · A"],
  ])("%s", (_name, kind, payload, want) => {
    expect(summarize(payload, kind)).toBe(want);
  });
});

describe("isLegacy", () => {
  it.each<[string, Kind, Record<string, unknown>, boolean]>([
    ["empty", "mass_premade", {}, false],
    ["one message", "mass_premade", { messages: [{ text: "a", unsend_after_hours: 8, exclude_last_chat_hours: 1 }] }, false],
    ["resend_count 0 / delay 0 are no timer", "mass_premade", { messages: [{ text: "a", resend_count: 0, delay_minutes: 0 }] }, false],
    ["two messages", "mass_premade", { messages: [{ text: "a" }, { text: "b" }] }, true],
    ["resend", "mass_premade", { messages: [{ text: "a", resend_count: 2, resend_after_hours: 24 }] }, true],
    ["resend hours alone (kept, not dropped)", "mass_premade", { messages: [{ text: "a", resend_after_hours: 24 }] }, true],
    ["resend count as a string", "mass_premade", { messages: [{ text: "a", resend_count: "1" }] }, true],
    ["delay", "mass_premade", { messages: [{ text: "a", delay_minutes: 30 }] }, true],
    ["[null]", "mass_premade", { messages: [null] }, false],
    ["posts list ignored on a mass rule", "mass_premade", { posts: [{ text: "a" }, { text: "b" }] }, false],
    ["mass ignores a top-level resend (never read)", "mass_premade", { messages: [{ text: "a" }], resend_count: 2 }, false],
    // Auto Post: one post; an older list, its repost cycle (list-level) or a per-post delay → Raw JSON.
    ["empty post rule", "auto_posts", {}, false],
    ["one post", "auto_posts", { posts: [{ text: "a", price: 12, hours_to_live: 6, preview_media_files: [1] }] }, false],
    ["cycle 0 is no timer", "auto_posts", { posts: [{ text: "a" }], resend_count: 0, resend_after_hours: 0 }, false],
    ["two posts", "auto_posts", { posts: [{ text: "a" }, { text: "b" }] }, true],
    ["repost cycle", "auto_posts", { posts: [{ text: "a" }], resend_count: 2, resend_after_hours: 24 }, true],
    ["repost hours alone", "auto_posts", { posts: [{ text: "a" }], resend_after_hours: 24 }, true],
    ["per-post delay", "auto_posts", { posts: [{ text: "a", delay_minutes: 30 }] }, true],
    ["messages list ignored on a post rule", "auto_posts", { messages: [{ text: "a" }, { text: "b" }] }, false],
  ])("%s %s", (_name, kind, payload, want) => {
    expect(isLegacy(payload, kind)).toBe(want);
  });
});
