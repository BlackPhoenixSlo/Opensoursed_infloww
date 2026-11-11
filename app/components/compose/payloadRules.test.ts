import { describe, expect, it } from "vitest";

import {
  explicitFans, filtersOf, hasContent, intList, MASS_AUDIENCE_KEYS, massReaches, onlineWithoutList, ppvPrice,
  sendAdvice, sendGap, truthy, type Kind, type SendGap,
} from "@/components/compose/payloadRules";

// Each rule here mirrors a service/ read; the tables pin the backend's behaviour, not the form's.
describe("readers", () => {
  it.each<[string, unknown, unknown]>([
    ["intList: int() takes numbers, digit strings, bools", intList([1, 4.5, " 42 ", "x", "4.5", true, null]), [1, 4.5, " 42 ", true]],
    ["intList: not a list", intList("1,2"), []],
    ["truthy: [] {} \"\" 0 null false", [[], {}, "", 0, null, false].map(truthy), [false, false, false, false, false, false]],
    ["truthy: [0] {a} \"0\" 1", [[0], { a: 0 }, "0", 1].map(truthy), [true, true, true, true]],
    ["explicitFans: included_users only (fan_ids is never forwarded)", explicitFans({ included_users: ["5", "x"], fan_ids: [7] }), ["5"]],
    ["explicitFans: fan_ids alone reaches nobody", explicitFans({ fan_ids: [7] }), []],
    ["filtersOf: a dict", filtersOf({ filters: { online: 1 } }), { online: 1 }],
    ["filtersOf: not a dict", filtersOf({ filters: [1] }), {}],
    ["ppvPrice: a numeric string charges", [12, "12", "0", "x", null, -1].map(ppvPrice), [12, 12, 0, 0, 0, 0]],
  ])("%s", (_name, got, want) => {
    expect(got).toEqual(want);
  });
});

describe("hasContent", () => {
  it.each<[string, Kind, Record<string, unknown>, boolean]>([
    ["text", "mass_premade", { messages: [{ text: "a" }] }, true],
    ["blank text", "mass_premade", { messages: [{ text: "  " }] }, false],
    ["media only (backend: no_text)", "mass_premade", { messages: [{ media_files: [1] }] }, false],
    ["a funnel", "mass_premade", { messages: [{ funnel_name: "x" }] }, true],
    ["media only", "auto_posts", { posts: [{ media_files: [1] }] }, true],
    ["a string media id", "auto_posts", { posts: [{ media_files: ["42"] }] }, true],
    ["a garbage media id", "auto_posts", { posts: [{ media_files: ["x"] }] }, false],
    ["folder only", "auto_posts", { posts: [{ media_folder_id: 0 }] }, true],
    ["claims only (backend: empty_post)", "auto_posts", { posts: [{ media_claims: [{}] }] }, false],
    ["[{}]", "auto_posts", { posts: [{}] }, false],
    ["[null]", "auto_posts", { posts: [null] }, false],
  ])("%s (%s) → %s", (_name, kind, payload, want) => {
    expect(hasContent(payload, kind)).toBe(want);
  });
});

// send_mass_decide.plan: `if not recipients and not user_lists and not online_only and not filters: empty_audience`;
// recipients = int_list(included_users) + list_ids members + the recent-chat / unread includes (mass_premade's
// _SEND_KEYS forwards no fan_ids). online_only alone is D5's `online` wait, so it is no audience key here.
describe("massReaches (the backend's empty_audience, statically)", () => {
  it("iterates exactly the audience keys the help line names", () => {
    expect(MASS_AUDIENCE_KEYS).toEqual(["user_lists", "included_users", "list_ids", "filters", "recent_chat_hours", "unread_limit"]);
  });
  it.each<[string, Record<string, unknown>, boolean]>([
    ["nothing", { text: "a" }, false],
    ["user_lists", { user_lists: ["fans"] }, true],
    ["user_lists []", { user_lists: [] }, false],
    ["included_users", { included_users: [5] }, true],
    ["included_users as strings (int_list)", { included_users: ["5"] }, true],
    ["included_users all garbage", { included_users: ["x"] }, false],
    ["fan_ids: never forwarded by mass_premade", { fan_ids: [7] }, false],
    ["fan_ids beside an empty included_users", { included_users: [], fan_ids: [7] }, false],
    ["list_ids", { list_ids: [3] }, true],
    ["exclude-only keys", { excluded_users: [1], exclude_list_ids: [2], excluded_user_lists: ["9"] }, false],
    ["online_only alone (D5's online wait instead)", { online_only: true }, false],
    ["filters", { filters: { min_spent: 5 } }, true],
    ["filters {}", { filters: {} }, false],
    ["filters not a dict", { filters: [1] }, false],
    ["recent_chat_hours", { recent_chat_hours: 24 }, true],
    ["recent_chat_hours 0", { recent_chat_hours: 0 }, false],
    ["recent_chat_hours -1 (future cutoff: nobody)", { recent_chat_hours: -1 }, false],
    ["recent_chat_hours as text", { recent_chat_hours: "24" }, false],
    ["unread_limit -5", { unread_limit: -5 }, false],
    ["unread_limit 10", { unread_limit: 10 }, true],
    ["unread_limit", { unread_limit: 5 }, true],
    ["recent_chat_limit alone", { recent_chat_limit: 5 }, false],
  ])("%s → %s", (_name, item, want) => {
    expect(massReaches(item)).toBe(want);
  });
});

// D5: an online filter with no user_lists sends OF `userLists: []` + online, a shape never verified.
describe("onlineWithoutList (D5)", () => {
  it.each<[string, Record<string, unknown>, boolean]>([
    ["online_only, no list", { online_only: true }, true],
    ["filters.online, no list", { filters: { online: 1 } }, true],
    ["online + recent-chat include, no list", { online_only: true, recent_chat_hours: 24 }, true],
    ["online + explicit fans, no list", { online_only: true, included_users: [5] }, true],
    ["online + empty user_lists", { online_only: true, user_lists: [] }, true],
    ["online + a list", { online_only: true, user_lists: ["fans"] }, false],
    ["no online filter", { recent_chat_hours: 24 }, false],
    ["online_only false", { online_only: false }, false],
    ["filters without online", { filters: { min_spent: 5 } }, false],
  ])("%s → %s", (_name, item, want) => {
    expect(onlineWithoutList(item)).toBe(want);
  });
});

describe("sendGap", () => {
  const fans = { user_lists: ["fans"] };
  it.each<[string, Kind, Record<string, unknown>, SendGap | null]>([
    ["empty", "mass_premade", {}, "content"],
    ["a message with an audience", "mass_premade", { messages: [{ text: "a", ...fans }] }, null],
    ["a message with no audience", "mass_premade", { messages: [{ text: "a" }] }, "audience"],
    ["an unknown key does not make an audience", "mass_premade", { messages: [{ text: "a" }], note: 1 }, "audience"],
    ["fan_ids reach nobody", "mass_premade", { messages: [{ text: "a", fan_ids: [7] }] }, "audience"],
    ["no text", "mass_premade", { messages: [{ ...fans }] }, "content"],
    ["one of two sends (a skipped item drains to the next)", "mass_premade",
      { messages: [{ text: "a" }, { text: "b", ...fans }] }, null],
    ["the item closest to sending says why", "mass_premade", { messages: [{}, { text: "b" }] }, "audience"],
    // D5, per item and whichever item: any online-without-list message blocks.
    ["online only, no list", "mass_premade", { messages: [{ text: "a", online_only: true }] }, "online"],
    ["online + chatted-with, no list", "mass_premade", { messages: [{ text: "a", online_only: true, recent_chat_hours: 24 }] }, "online"],
    ["filters.online, no list", "mass_premade", { messages: [{ text: "a", filters: { online: 1 } }] }, "online"],
    ["one safe message does not clear an online-only one", "mass_premade",
      { messages: [{ text: "a", ...fans }, { text: "b", online_only: true }] }, "online"],
    ["online with no text never sends: not blocking", "mass_premade", { messages: [{ online_only: true }, { text: "b", ...fans }] }, null],
    ["online + a list", "mass_premade", { messages: [{ text: "a", online_only: true, ...fans }] }, null],
    // D6: a paid message with no media is a warning (sendAdvice), not a wait.
    ["paid message, no media", "mass_premade", { messages: [{ text: "a", price: 5, ...fans }] }, null],
    ["post: media only", "auto_posts", { posts: [{ media_files: [1] }] }, null],
    ["post: nothing", "auto_posts", { posts: [{}] }, "content"],
    ["paid post, no media", "auto_posts", { posts: [{ text: "a", price: 5 }] }, "ppv"],
    ["paid post with a folder", "auto_posts", { posts: [{ text: "a", price: 5, media_folder_id: 3 }] }, null],
    ["paid post with only free previews (joined to the media)", "auto_posts",
      { posts: [{ text: "a", price: 5, preview_media_files: [4] }] }, null],
    ["paid post with media_claims", "auto_posts", { posts: [{ text: "a", price: 5, media_claims: [{ id: 1 }] }] }, null],
    ["paid post, media_claims not a list (backend ignores it)", "auto_posts",
      { posts: [{ text: "a", price: 5, media_claims: { id: 1 } }] }, "ppv"],
    ["free post, no media", "auto_posts", { posts: [{ text: "a", price: 0 }] }, null],
    // auto_posts compares `price > 0`: a string price raises TypeError every run, whichever post has it.
    ["post price as a string", "auto_posts", { posts: [{ text: "a", price: "12", media_files: [1] }] }, "price"],
    ["post price \"0\"", "auto_posts", { posts: [{ text: "a", price: "0" }] }, "price"],
    ["post price \"\" is free (`price or 0`)", "auto_posts", { posts: [{ text: "a", price: "" }] }, null],
    ["one bad price blocks the list", "auto_posts", { posts: [{ text: "a" }, { text: "b", price: "5" }] }, "price"],
    ["a string price on a mass is fine (float() reads it)", "mass_premade",
      { messages: [{ text: "a", price: "12", media_files: [1], ...fans }] }, null],
  ])("%s (%s) → %s", (_name, kind, payload, want) => {
    expect(sendGap(payload, kind)).toBe(want);
  });
});

describe("sendAdvice (D6: a warning, Save stays on)", () => {
  const fans = { user_lists: ["fans"] };
  it.each<[string, Kind, Record<string, unknown>, "ppv" | null]>([
    ["paid message, no media", "mass_premade", { messages: [{ text: "a", price: 5, ...fans }] }, "ppv"],
    ["paid message, string price", "mass_premade", { messages: [{ text: "a", price: "5", ...fans }] }, "ppv"],
    ["paid message with media", "mass_premade", { messages: [{ text: "a", price: 5, media_files: [1], ...fans }] }, null],
    ["paid message with a folder", "mass_premade", { messages: [{ text: "a", price: 5, media_folder_id: 2, ...fans }] }, null],
    ["paid funnel message (opener media)", "mass_premade", { messages: [{ funnel_id: 2, price: 5, ...fans }] }, null],
    ["free message", "mass_premade", { messages: [{ text: "a", ...fans }] }, null],
    ["paid message with no text never sends", "mass_premade", { messages: [{ price: 5, ...fans }] }, null],
    ["posts: a hard wait instead (sendGap ppv)", "auto_posts", { posts: [{ text: "a", price: 5 }] }, null],
  ])("%s → %s", (_name, kind, payload, want) => {
    expect(sendAdvice(payload, kind)).toBe(want);
  });
});
