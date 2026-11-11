import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import type { Kind } from "@/components/compose/payloadRules";
import {
  blankRow, buildPayload, customIncludes, hasMoreAudience, itemToRow, lastChatChips, payloadToRow, priceLabel,
  rowReducer, rowToItem, type Row, type RowAction,
} from "@/components/compose/premadeRows";
import { mergeCaptions, parseCaptions } from "@/lib/parseCaptions";
import type { VaultMedia } from "@/lib/relay";

const run = (s: Row, ...actions: RowAction[]) => actions.reduce(rowReducer, s);
const row = (over: Partial<Row> = {}): Row => ({ ...blankRow(), ...over });
const media = (id: number) => ({ id, type: "photo" }) as VaultMedia;
const POSTS: Kind = "auto_posts";
const MASS: Kind = "mass_premade";

describe("rowReducer", () => {
  it.each<[string, Row, RowAction[], Row]>([
    ["patch merges", row({ texts: ["a"] }), [{ type: "patch", patch: { price: "5", folderId: "7" } }],
      row({ texts: ["a"], price: "5", folderId: "7" })],
    // System chip: off ↔ include, never exclude (OF drops a built-in name in excludedLists).
    ["system chip off → include", row({ includes: [], excludes: [] }), [{ type: "toggleListInclude", id: "fans" }],
      row({ includes: ["fans"], excludes: [] })],
    ["system chip include → off (no exclude state)", row({ includes: ["fans"] }), [{ type: "toggleListInclude", id: "fans" }],
      row({ includes: [], excludes: [] })],
    ["toggleListInclude adds + clears its exclude", row({ includes: [], excludes: ["9"] }),
      [{ type: "toggleListInclude", id: "9" }], row({ includes: ["9"], excludes: [] })],
    ["toggleListInclude again removes", row({ includes: ["9"], excludes: [] }),
      [{ type: "toggleListInclude", id: "9" }], row({ includes: [], excludes: [] })],
    ["toggleListExclude adds + clears its include", row({ includes: ["9"], excludes: [] }),
      [{ type: "toggleListExclude", id: "9" }], row({ includes: [], excludes: ["9"] })],
    ["toggleListExclude again removes", row({ includes: [], excludes: ["9"] }),
      [{ type: "toggleListExclude", id: "9" }], row({ includes: [], excludes: [] })],
  ])("%s", (_name, start, actions, want) => {
    expect(run(start, ...actions)).toEqual(want);
  });

  it("never mutates its input", () => {
    const s = row({ texts: ["b"] });
    rowReducer(s, { type: "patch", patch: { texts: ["q"] } });
    expect(s.texts).toEqual(["b"]);
  });
});

describe("rowToItem", () => {
  it.each<[string, Partial<Row>, Kind, Record<string, unknown>]>([
    ["blank post → {}", { includes: [] }, POSTS, {}],
    ["one variant → text (trimmed)", { texts: ["  hi  ", " "] }, POSTS, { text: "hi" }],
    ["many variants → texts pool", { texts: ["a", "b"] }, POSTS, { texts: ["a", "b"] }],
    ["media + folder + count", { media: [media(1), media(2)], folderId: "5", mediaCount: "2.7" }, POSTS,
      { media_files: [1, 2], media_folder_id: 5, media_count: 2 }],
    ["media_count needs a pool", { mediaCount: "3" }, POSTS, {}],
    ["price + hours_to_live", { price: "4.5", hoursToLive: "6" }, POSTS, { price: 4.5, hours_to_live: 6 }],
    ["garbage/zero knobs dropped", { price: "0", hoursToLive: "-1" }, POSTS, {}],
    ["paid post previews", { price: "5", previewMedia: [media(8)], previewFolderId: "3", previewCount: "2" }, POSTS,
      { price: 5, preview_media_files: [8], preview_media_folder_id: 3, preview_media_count: 2 }],
    ["free post drops previews", { previewMedia: [media(8)], previewFolderId: "3" }, POSTS, {}],
    ["mass ignores previews + hours_to_live", { includes: [], onlineOnly: false, excludeLastChatHours: "", price: "5",
      previewMedia: [media(8)], hoursToLive: "6" }, MASS, { price: 5 }],
    ["mass defaults: online + fans/following + skip chatted-with 1h", {}, MASS,
      { online_only: true, user_lists: ["fans", "following"], exclude_last_chat_hours: 1 }],
    ["All fans + Online now + 3h chip mapping", { includes: ["fans"], onlineOnly: true, excludeLastChatHours: "3" }, MASS,
      { online_only: true, user_lists: ["fans"], exclude_last_chat_hours: 3 }],
    ["Following without Online now", { includes: ["following"], onlineOnly: false, excludeLastChatHours: "1" }, MASS,
      { user_lists: ["following"], exclude_last_chat_hours: 1 }],
    ["mass skip chatted-with Off/0 → dropped", { includes: [], onlineOnly: false, excludeLastChatHours: "0" }, MASS, {}],
    ["mass full knobs", {
      includes: ["fans", "42"], excludes: ["43"], onlineOnly: false, unsendAfterHours: "8",
      excludeLastChatHours: "3", excludeRepliedHours: "2", excludeInboundHours: "3",
      unreadLimit: "10", recentChatHours: "5", recentChatLimit: "0",
    }, MASS, {
      user_lists: ["fans", "42"], excluded_user_lists: ["43"], unsend_after_hours: 8,
      exclude_last_chat_hours: 3, exclude_replied_hours: 2, exclude_inbound_hours: 3,
      unread_limit: 10, recent_chat_hours: 5,
    }],
    // Default-on guards (absent = 6h / 2h server-side): blank is the default, an explicit 0 turns them off.
    ["mass replied / inbound blank → absent (backend default)", { includes: [], onlineOnly: false, excludeLastChatHours: "" },
      MASS, {}],
    ["mass replied / inbound 0 → sent as 0 (guard off)", { includes: [], onlineOnly: false, excludeLastChatHours: "",
      excludeRepliedHours: "0", excludeInboundHours: "0" }, MASS, { exclude_replied_hours: 0, exclude_inbound_hours: 0 }],
    ["mass replied / inbound fractional hours kept", { includes: [], onlineOnly: false, excludeLastChatHours: "",
      excludeRepliedHours: "1.5", excludeInboundHours: "-1" }, MASS, { exclude_replied_hours: 1.5 }],
  ])("%s", (_name, over, ctx, want) => {
    expect(rowToItem(row(over), ctx)).toEqual(want);
  });
});

// Every knob set (incl. ones the mode ignores). Expected JSON pins values AND
// key order, i.e. the exact wire bytes (one clock: no delay / resend on either kind).
const FULL = row({
  texts: [" hello ", "", "second"], media: [media(11), media(12)], folderId: "7", mediaCount: "3.9",
  previewMedia: [media(21)], previewFolderId: "8", previewCount: "1.5",
  hoursToLive: "48", price: "9.99",
  onlineOnly: true, unsendAfterHours: "12",
  includes: ["fans", "555"], excludes: ["following", "666"], excludeLastChatHours: "8",
  excludeRepliedHours: "6", excludeInboundHours: "4", unreadLimit: "50.8",
  recentChatHours: "72", recentChatLimit: "20",
});

describe("rowToItem golden", () => {
  it.each<[string, Kind, string]>([
    ["posts", POSTS, '{"texts":["hello","second"],"media_files":[11,12],"media_folder_id":7,"media_count":3,'
      + '"price":9.99,"preview_media_files":[21],"preview_media_folder_id":8,'
      + '"preview_media_count":1,"hours_to_live":48}'],
    ["messages", MASS, '{"texts":["hello","second"],"media_files":[11,12],"media_folder_id":7,"media_count":3,'
      + '"price":9.99,"online_only":true,"unsend_after_hours":12,'
      + '"user_lists":["fans","555"],"excluded_user_lists":["following","666"],"exclude_last_chat_hours":8,'
      + '"exclude_replied_hours":6,"exclude_inbound_hours":4,"unread_limit":50,"recent_chat_hours":72,'
      + '"recent_chat_limit":20}'],
  ])("%s", (_name, ctx, want) => {
    expect(JSON.stringify(rowToItem(FULL, ctx))).toBe(want);
  });
});

describe("itemToRow round-trip", () => {
  // item → row → item keeps every payload field.
  it.each<[string, Partial<Row>, Kind]>([
    ["posts full", FULL, POSTS],
    ["mass full (custom excludes only)", { ...FULL, excludes: ["666"] }, MASS],
    ["one text", { texts: ["solo"] }, POSTS],
    ["mass blank (online off, no audience)", { includes: [], onlineOnly: false }, MASS],
    ["mass defaults", {}, MASS],
    ["free post, folder only", { folderId: "3", previewMedia: [media(9)] }, POSTS],
    ["mass replied / inbound 0 (guard off)", { excludeRepliedHours: "0", excludeInboundHours: "0" }, MASS],
  ])("%s", (_name, over, ctx) => {
    const item = rowToItem(row(over), ctx);
    expect(rowToItem(itemToRow(item), ctx)).toEqual(item);
  });
  it("a built-in name saved in excluded_user_lists (it excluded nobody) is not carried; list ids are", () => {
    const item = rowToItem(FULL, MASS);
    expect(item.excluded_user_lists).toEqual(["following", "666"]);
    expect(itemToRow(item).excludes).toEqual(["666"]);
    expect(rowToItem(itemToRow(item), MASS)).toEqual({ ...item, excluded_user_lists: ["666"] });
  });
  it("re-seeds media as id-only stubs and fills the row", () => {
    expect(itemToRow({ text: "t", media_files: [1, "x"], media_folder_id: 4, price: 5, online_only: true }))
      .toEqual(row({ texts: ["t"], media: [media(1)], folderId: "4", price: "5", onlineOnly: true,
        includes: [], excludeLastChatHours: "" }));
  });
});

describe("payloadToRow", () => {
  it.each<[string, Record<string, unknown> | undefined, Kind, Row]>([
    ["missing → blank row", undefined, "auto_posts", blankRow()],
    ["empty list → blank row", { posts: [] }, "auto_posts", blankRow()],
    ["reads the kind's key only", { messages: [{ text: "m" }] }, "auto_posts", blankRow()],
    ["posts: the first item", { posts: [{ text: "a" }, { text: "b" }] }, "auto_posts",
      row({ texts: ["a"], onlineOnly: false, includes: [], excludeLastChatHours: "" })],
    ["[null] → an empty saved item", { posts: [null] }, "auto_posts",
      row({ onlineOnly: false, includes: [], excludeLastChatHours: "" })],
    // A saved message without the key is Off (the 1h default is for new rules only).
    ["messages", { messages: [{ texts: ["a", "b"], online_only: true, user_lists: ["fans"] }] }, "mass_premade",
      row({ texts: ["a", "b"], includes: ["fans"], excludeLastChatHours: "" })],
    ["messages, skip chatted-with 3h", { messages: [{ text: "a", exclude_last_chat_hours: 3 }] }, "mass_premade",
      row({ texts: ["a"], onlineOnly: false, includes: [], excludeLastChatHours: "3" })],
    ["messages, replied / inbound 0 seed back as 0", { messages: [{ text: "a", exclude_replied_hours: 0,
      exclude_inbound_hours: 0 }] }, "mass_premade",
    row({ texts: ["a"], onlineOnly: false, includes: [], excludeLastChatHours: "", excludeRepliedHours: "0",
      excludeInboundHours: "0" })],
  ])("%s", (_name, payload, kind, want) => {
    expect(payloadToRow(payload, kind)).toEqual(want);
  });
});

describe("buildPayload", () => {
  const plain = row({ texts: ["hi"], includes: [], onlineOnly: false });
  // One rule = one item: no resend_* / delay_minutes key on either kind.
  it.each<[string, Row, Kind, string]>([
    // Always the one item, even one that wouldn't send yet (readyMadeContent `sendGap` is the gate).
    ["no text, no media: still the one item", row({ texts: [" "] }), POSTS, '{"posts":[{}]}'],
    ["mass, audience but no text: the audience is kept", row({ texts: [""], includes: ["42"], onlineOnly: false }), MASS,
      '{"messages":[{"user_lists":["42"],"exclude_last_chat_hours":1}]}'],
    ["folder only counts", row({ texts: [""], folderId: "5" }), POSTS, '{"posts":[{"media_folder_id":5}]}'],
    ["posts rule: one post", plain, POSTS, '{"posts":[{"text":"hi"}]}'],
    ["paid post, auto-delete", row({ texts: ["hi"], price: "12", hoursToLive: "6", previewFolderId: "3" }), POSTS,
      '{"posts":[{"text":"hi","price":12,"preview_media_folder_id":3,"hours_to_live":6}]}'],
    ["mass rule: one message", plain, MASS, '{"messages":[{"text":"hi","exclude_last_chat_hours":1}]}'],
    ["mass, default audience", row({ texts: ["hi"] }), MASS,
      '{"messages":[{"text":"hi","online_only":true,"user_lists":["fans","following"],"exclude_last_chat_hours":1}]}'],
  ])("%s", (_name, r, kind, want) => {
    expect(JSON.stringify(buildPayload(r, kind))).toBe(want);
  });
});

describe("imported captions → payload", () => {
  it("all 251 fixture captions ride in one post's texts pool", () => {
    const raw = readFileSync(join(__dirname, "../../lib/__fixtures__/captions-general.csv"), "utf8");
    const { items } = parseCaptions(raw, { filename: "captions-general.csv" });
    const r = run(blankRow(), { type: "patch", patch: { texts: mergeCaptions([""], items).pool } });
    const p = buildPayload(r, POSTS);
    expect(p.posts).toHaveLength(1);
    expect(p.posts?.[0].texts).toEqual(items);
    expect((p.posts?.[0].texts as string[]).length).toBe(251);
  });
});

describe("lastChatChips", () => {
  const P = ["Off", "1h", "3h", "8h", "24h"];
  it.each<[string, string, string, string[]]>([
    ["blank → Off", "", "", P],
    ["0 → Off", "0", "", P],
    ["garbage → Off", "x", "", P],
    ["preset", "8", "8", P],
    ["preset spelled 1.0", "1.0", "1", P],
    ["off-preset value gets its own chip, in order", "2", "2", ["Off", "1h", "2h", "3h", "8h", "24h"]],
    ["above the presets", "48", "48", [...P, "48h"]],
  ])("%s", (_name, hours, value, labels) => {
    const got = lastChatChips(hours);
    expect(got.value).toBe(value);
    expect(got.options.map((o) => o.label)).toEqual(labels);
    expect(got.options.some((o) => o.value === value)).toBe(true);
  });
});

describe("hasMoreAudience", () => {
  it.each<[string, Partial<Row>, boolean]>([
    ["skip chatted-with is up front, not More", { excludeLastChatHours: "3" }, false],
    ["exclude list lives in visible Include / Exclude tabs", { excludes: ["42"] }, false],
    ["exclude replied", { excludeRepliedHours: "2" }, true],
    ["exclude inbound", { excludeInboundHours: "2" }, true],
    ["include chatted-with", { recentChatHours: "5" }, true],
    ["cap recent-chat", { recentChatLimit: "10" }, true],
    ["unread", { unreadLimit: "4" }, true],
  ])("%s", (_name, over, want) => {
    expect(hasMoreAudience(row(over))).toBe(want);
  });
});

describe("customIncludes", () => {
  it("drops the system chips, keeps custom list ids in order", () => {
    expect(customIncludes(row({ includes: ["fans", "42", "following", "7"] }))).toEqual(["42", "7"]);
  });
});

describe("priceLabel (the backend's `price or 0`, a numeric string charges too)", () => {
  it.each<[unknown, string]>([
    [undefined, "Free"], [0, "Free"], ["", "Free"], ["0", "Free"], [-3, "Free"], ["abc", "Free"], [null, "Free"],
    [12, "$12"], ["12", "$12"], [9.99, "$9.99"], ["9.99", "$9.99"],
  ])("%j → %s", (v, want) => {
    expect(priceLabel(v)).toBe(want);
  });
});
