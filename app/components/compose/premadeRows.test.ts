import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import {
  blankRow, buildPayload, initPremade, itemToRow, payloadToRows, premadeReducer, rowToItem, rowsReducer, rowsToItems,
  type Kind, type PostsCycle, type PremadeAction, type PremadeState, type Row, type RowCtx, type RowsAction,
} from "@/components/compose/premadeRows";
import { mergeCaptions, parseCaptions } from "@/lib/parseCaptions";
import type { VaultMedia } from "@/lib/relay";

const run = (s: Row[], ...actions: RowsAction[]) => actions.reduce(rowsReducer, s);
const row = (over: Partial<Row> = {}): Row => ({ ...blankRow(), ...over });
const media = (id: number) => ({ id, type: "photo" }) as VaultMedia;
const POSTS: RowCtx = { kind: "auto_posts" };
const MASS: RowCtx = { kind: "mass_premade" };

describe("rowsReducer", () => {
  const two = () => [row({ texts: ["a"] }), row({ texts: ["b"] })];

  it.each<[string, Row[], RowsAction[], Row[]]>([
    ["patch merges into row i only", two(), [{ type: "patch", i: 1, patch: { price: "5", folderId: "7" } }],
      [row({ texts: ["a"] }), row({ texts: ["b"], price: "5", folderId: "7" })]],
    ["add appends a blank row", two(), [{ type: "add" }], [...two(), blankRow()]],
    ["remove drops row i", two(), [{ type: "remove", i: 0 }], [row({ texts: ["b"] })]],
    ["remove keeps the last row", [row({ texts: ["a"] })], [{ type: "remove", i: 0 }], [row({ texts: ["a"] })]],
    ["reset → one blank row", two(), [{ type: "reset" }], [blankRow()]],
    // System chip: off ↔ include, never exclude (OF drops a built-in name in excludedLists).
    ["system chip off → include", [row({ includes: [], excludes: [] })], [{ type: "toggleListInclude", i: 0, id: "fans" }],
      [row({ includes: ["fans"], excludes: [] })]],
    ["system chip include → off (no exclude state)", [row({ includes: ["fans"] })], [{ type: "toggleListInclude", i: 0, id: "fans" }],
      [row({ includes: [], excludes: [] })]],
    ["toggleListInclude adds + clears its exclude", [row({ includes: [], excludes: ["9"] })],
      [{ type: "toggleListInclude", i: 0, id: "9" }], [row({ includes: ["9"], excludes: [] })]],
    ["toggleListInclude again removes", [row({ includes: ["9"], excludes: [] })],
      [{ type: "toggleListInclude", i: 0, id: "9" }], [row({ includes: [], excludes: [] })]],
    ["toggleListExclude adds + clears its include", [row({ includes: ["9"], excludes: [] })],
      [{ type: "toggleListExclude", i: 0, id: "9" }], [row({ includes: [], excludes: ["9"] })]],
    ["toggleListExclude again removes", [row({ includes: [], excludes: ["9"] })],
      [{ type: "toggleListExclude", i: 0, id: "9" }], [row({ includes: [], excludes: [] })]],
  ])("%s", (_name, start, actions, want) => {
    expect(run(start, ...actions)).toEqual(want);
  });

  it("leaves other rows untouched (same reference)", () => {
    const s = two();
    const next = rowsReducer(s, { type: "patch", i: 1, patch: { texts: ["q"] } });
    expect(next[0]).toBe(s[0]);
    expect(s[1].texts).toEqual(["b"]); // input not mutated
  });
});

describe("rowToItem", () => {
  it.each<[string, Partial<Row>, RowCtx, Record<string, unknown>]>([
    ["blank post → {}", { includes: [] }, POSTS, {}],
    ["one variant → text (trimmed)", { texts: ["  hi  ", " "] }, POSTS, { text: "hi" }],
    ["many variants → texts pool", { texts: ["a", "b"] }, POSTS, { texts: ["a", "b"] }],
    ["media + folder + count", { media: [media(1), media(2)], folderId: "5", mediaCount: "2.7" }, POSTS,
      { media_files: [1, 2], media_folder_id: 5, media_count: 2 }],
    ["media_count needs a pool", { mediaCount: "3" }, POSTS, {}],
    ["delay + price + hours_to_live", { delayMinutes: "30", price: "4.5", hoursToLive: "6" }, POSTS,
      { delay_minutes: 30, price: 4.5, hours_to_live: 6 }],
    ["garbage/zero knobs dropped", { delayMinutes: "x", price: "0", hoursToLive: "-1" }, POSTS, {}],
    ["paid post previews", { price: "5", previewMedia: [media(8)], previewFolderId: "3", previewCount: "2" }, POSTS,
      { price: 5, preview_media_files: [8], preview_media_folder_id: 3, preview_media_count: 2 }],
    ["free post drops previews", { previewMedia: [media(8)], previewFolderId: "3" }, POSTS, {}],
    ["mass ignores previews + hours_to_live", { includes: [], onlineOnly: false, price: "5",
      previewMedia: [media(8)], hoursToLive: "6" }, MASS, { price: 5 }],
    ["mass defaults: online + fans/following", {}, MASS,
      { online_only: true, user_lists: ["fans", "following"] }],
    ["mass resend needs count>0 AND hours", { includes: [], onlineOnly: false, resendCount: "2", resendAfterHours: "" },
      MASS, {}],
    ["mass full knobs", {
      includes: ["fans", "42"], excludes: ["43"], onlineOnly: false, unsendAfterHours: "8",
      resendCount: "2.9", resendAfterHours: "24", excludeRepliedHours: "2", excludeInboundHours: "3",
      unreadLimit: "10", recentChatHours: "5", recentChatLimit: "0",
    }, MASS, {
      user_lists: ["fans", "42"], excluded_user_lists: ["43"], unsend_after_hours: 8,
      resend_count: 2, resend_after_hours: 24, exclude_replied_hours: 2, exclude_inbound_hours: 3,
      unread_limit: 10, recent_chat_hours: 5,
    }],
  ])("%s", (_name, over, ctx, want) => {
    expect(rowToItem(row(over), ctx)).toEqual(want);
  });
});

describe("rowsToItems", () => {
  it("drops rows with no text and no media; folder-only counts", () => {
    const rows = [row({ texts: [" "] }), row({ texts: ["hi"] }), row({ folderId: "5" })];
    expect(rowsToItems(rows, POSTS)).toEqual([{ text: "hi" }, { media_folder_id: 5 }]);
  });
});

// Every knob set (incl. ones the mode ignores). Expected JSON is origin/main's
// rowToItem output for this row (pre-refactor, run verbatim) — pins values AND
// key order, i.e. the exact wire bytes.
const FULL = row({
  texts: [" hello ", "", "second"], media: [media(11), media(12)], folderId: "7", mediaCount: "3.9",
  previewMedia: [media(21)], previewFolderId: "8", previewCount: "1.5",
  delayMinutes: "15", hoursToLive: "48", price: "9.99",
  onlineOnly: true, unsendAfterHours: "12", resendAfterHours: "24", resendCount: "2.7",
  includes: ["fans", "555"], excludes: ["following", "666"],
  excludeRepliedHours: "6", excludeInboundHours: "4", unreadLimit: "50.8",
  recentChatHours: "72", recentChatLimit: "20",
});

describe("rowToItem golden (origin/main)", () => {
  it.each<[string, RowCtx, string]>([
    ["posts", POSTS, '{"texts":["hello","second"],"media_files":[11,12],"media_folder_id":7,"media_count":3,'
      + '"delay_minutes":15,"price":9.99,"preview_media_files":[21],"preview_media_folder_id":8,'
      + '"preview_media_count":1,"hours_to_live":48}'],
    ["messages", MASS, '{"texts":["hello","second"],"media_files":[11,12],"media_folder_id":7,"media_count":3,'
      + '"delay_minutes":15,"price":9.99,"online_only":true,"unsend_after_hours":12,"resend_count":2,'
      + '"resend_after_hours":24,"user_lists":["fans","555"],"excluded_user_lists":["following","666"],'
      + '"exclude_replied_hours":6,"exclude_inbound_hours":4,"unread_limit":50,"recent_chat_hours":72,'
      + '"recent_chat_limit":20}'],
  ])("%s", (_name, ctx, want) => {
    expect(JSON.stringify(rowToItem(FULL, ctx))).toBe(want);
  });
});

describe("itemToRow round-trip", () => {
  // item → row → item keeps every payload field.
  it.each<[string, Partial<Row>, RowCtx]>([
    ["posts full", FULL, POSTS],
    ["mass full (custom excludes only)", { ...FULL, excludes: ["666"] }, MASS],
    ["one text", { texts: ["solo"] }, POSTS],
    ["mass blank (online off, no audience)", { includes: [], onlineOnly: false }, MASS],
    ["mass defaults", {}, MASS],
    ["free post, folder only", { folderId: "3", previewMedia: [media(9)] }, POSTS],
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
        includes: [] }));
  });
});

describe("payloadToRows", () => {
  it.each<[string, Record<string, unknown> | undefined, RowCtx["kind"], Row[]]>([
    ["missing → one blank row", undefined, "auto_posts", [blankRow()]],
    ["empty list → one blank row", { posts: [] }, "auto_posts", [blankRow()]],
    ["reads the kind's key only", { messages: [{ text: "m" }] }, "auto_posts", [blankRow()]],
    ["posts", { posts: [{ text: "a" }, null] }, "auto_posts",
      [row({ texts: ["a"], onlineOnly: false, includes: [] }), row({ onlineOnly: false, includes: [] })]],
    ["messages", { messages: [{ texts: ["a", "b"], online_only: true, user_lists: ["fans"] }] }, "mass_premade",
      [row({ texts: ["a", "b"], includes: ["fans"] })]],
  ])("%s", (_name, payload, kind, want) => {
    expect(payloadToRows(payload, kind)).toEqual(want);
  });
});

describe("buildPayload", () => {
  const NO_CYCLE: PostsCycle = { resendCount: "", resendAfterHours: "" };
  const CYCLE: PostsCycle = { resendCount: "3.5", resendAfterHours: "12" };
  const rows = [row({ texts: ["hi"], includes: [], onlineOnly: false })];
  // Expected key order = origin/main's buildComposePayload literals.
  it.each<[string, Row[], PostsCycle, RowCtx, string | null]>([
    ["no usable row → null", [row({ texts: [" "] })], CYCLE, POSTS, null],
    ["posts rule", rows, CYCLE, POSTS,
      '{"posts":[{"text":"hi"}],"resend_count":3,"resend_after_hours":12}'],
    ["posts cycle unset → dropped", rows, NO_CYCLE, POSTS, '{"posts":[{"text":"hi"}]}'],
    ["posts cycle needs count>0 AND hours", rows, { resendCount: "0", resendAfterHours: "12" }, POSTS,
      '{"posts":[{"text":"hi"}]}'],
    ["mass rule ignores the cycle", rows, CYCLE, MASS, '{"messages":[{"text":"hi"}]}'],
  ])("%s", (_name, rs, cycle, ctx, want) => {
    const p = buildPayload(rs, cycle, ctx);
    expect(p === null ? null : JSON.stringify(p)).toBe(want);
  });
});

describe("imported captions → payload", () => {
  it("all 251 fixture captions ride in one post's texts pool", () => {
    const raw = readFileSync(join(__dirname, "../../lib/__fixtures__/captions-general.csv"), "utf8");
    const { items } = parseCaptions(raw, { filename: "captions-general.csv" });
    const rows = run([blankRow()], { type: "patch", i: 0, patch: { texts: mergeCaptions([""], items).pool } });
    const p = buildPayload(rows, { resendCount: "", resendAfterHours: "" }, POSTS);
    expect(p?.posts).toHaveLength(1);
    expect(p?.posts?.[0].texts).toEqual(items);
    expect((p?.posts?.[0].texts as string[]).length).toBe(251);
  });
});

// The form state that replaced PremadeForm's rows reducer + two cycle useStates + the opened snapshot.
describe("premadeReducer", () => {
  const S = (over: Partial<PremadeState> = {}): PremadeState =>
    ({ rows: [blankRow()], cycle: { resendCount: "", resendAfterHours: "" }, ...over });
  it.each<[string, PremadeState, PremadeAction[], PremadeState]>([
    ["setCycle patches one knob", S(), [{ type: "setCycle", patch: { resendAfterHours: "24" } }],
      S({ cycle: { resendCount: "", resendAfterHours: "24" } })],
    ["a row action reaches the rows only", S({ cycle: { resendCount: "2", resendAfterHours: "6" } }),
      [{ type: "patch", i: 0, patch: { texts: ["hi"] } }],
      S({ rows: [row({ texts: ["hi"] })], cycle: { resendCount: "2", resendAfterHours: "6" } })],
    ["reset clears the rows and the cycle", S({ rows: [row({ texts: ["a"] }), row()], cycle: { resendCount: "2", resendAfterHours: "6" } }),
      [{ type: "reset" }], S()],
  ])("%s", (_name, start, actions, want) => {
    expect(actions.reduce(premadeReducer, start)).toEqual(want);
  });

  it.each<[string, Record<string, unknown> | undefined, Kind, PostsCycle]>([
    ["auto_posts seeds the cycle from the payload", { posts: [{ text: "a" }], resend_count: 3, resend_after_hours: 12 },
      "auto_posts", { resendCount: "3", resendAfterHours: "12" }],
    ["mass_premade never seeds a cycle", { messages: [{ text: "a" }], resend_count: 3, resend_after_hours: 12 },
      "mass_premade", { resendCount: "", resendAfterHours: "" }],
    ["no payload: blank", undefined, "auto_posts", { resendCount: "", resendAfterHours: "" }],
  ])("initPremade: %s", (_name, payload, kind, cycle) => {
    expect(initPremade(payload, kind)).toEqual({ rows: payloadToRows(payload, kind), cycle });
  });

  // Same input → the body the old inline code built: buildPayload(rows, {resendCount, resendAfterHours}, {kind}).
  it.each<[string, Kind, PremadeAction[], string | null]>([
    ["posts + cycle", "auto_posts", [{ type: "patch", i: 0, patch: { texts: ["hi"] } },
      { type: "setCycle", patch: { resendCount: "2" } }, { type: "setCycle", patch: { resendAfterHours: "24" } }],
      '{"posts":[{"text":"hi"}],"resend_count":2,"resend_after_hours":24}'],
    ["posts, cycle reset away", "auto_posts", [{ type: "setCycle", patch: { resendCount: "2", resendAfterHours: "24" } },
      { type: "reset" }, { type: "patch", i: 0, patch: { texts: ["hi"] } }], '{"posts":[{"text":"hi"}]}'],
    ["mass, default audience", "mass_premade", [{ type: "patch", i: 0, patch: { texts: ["hi"] } }],
      '{"messages":[{"text":"hi","online_only":true,"user_lists":["fans","following"]}]}'],
    ["nothing usable", "auto_posts", [{ type: "setCycle", patch: { resendCount: "2" } }], null],
  ])("payload: %s", (_name, kind, actions, want) => {
    const s = actions.reduce(premadeReducer, initPremade(undefined, kind));
    const p = buildPayload(s.rows, s.cycle, { kind });
    expect(p === null ? null : JSON.stringify(p)).toBe(want);
  });
});
