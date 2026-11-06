import { afterEach, describe, expect, it, vi } from "vitest";

import {
  attributionSince, bundlePath, classify, outcome, prefetchScreen, resetScreenBundles, screenJoin, screenKey, screenRead,
  setScreen, type Read, type Screen,
} from "./screenBundle";

const CHAT: Screen = { kind: "chat", accountId: "A1", fanId: "42", lacks: ["savedReplies"] };
const CK = "chat|A1|42|savedReplies";
const BODY = {
  seed: { messages: [{ id: 9 }] }, fan: { fan_id: 42 }, attribution: { by_msg_id: { 5: { e: 1 }, 9: { e: 2 } } },
  fanHistory: { by_media: {} }, scheduledSends: { list: [] }, savedReplies: { list: [] }, thumbs: [], errors: [],
};

afterEach(() => resetScreenBundles());

describe("chat classify", () => {
  it.each<[string, string, string | null, Partial<Read> | null]>([
    ["seed page", "/admin/messages/A1/42?limit=30", null, { field: "seed", bundle: CK, starter: false }],
    ["an older seed page", "/admin/messages/A1/42?limit=30&before_id=9", null, null],
    ["another limit", "/admin/messages/A1/42?limit=50", null, null],
    ["another fan's seed", "/admin/messages/A1/43?limit=30", null, null],
    ["attribution bare", "/admin/messages/A1/42/attribution", null, { field: "attribution" }],
    ["attribution since", "/admin/messages/A1/42/attribution?since_id=5", null, { field: "attribution", since: 5 }],
    ["attribution bad since", "/admin/messages/A1/42/attribution?since_id=x", null, null],
    ["attribution since past 2^53 (a rounded snowflake)", "/admin/messages/A1/42/attribution?since_id=731234567890123500000", null, null],
    ["fan", "/admin/fans/A1/42", null, { field: "fan" }],
    ["fan-history", "/admin/vault/fan-history?account_id=A1&fan_id=42", null, { field: "fanHistory" }],
    ["scheduled sends, the Creator's", "/api/of/v2/scheduled-sends?fan_id=42", "A1", { field: "scheduledSends", accountId: "A1" }],
    ["scheduled sends, unscoped", "/api/of/v2/scheduled-sends?fan_id=42", null, null],
    ["scheduled sends, another Creator", "/api/of/v2/scheduled-sends?fan_id=42", "B", null],
    ["saved replies lacked", "/admin/saved-replies?account_id=A1", null, { field: "savedReplies" }],
    ["sensitive words not lacked", "/admin/sensitive-words?account_id=A1", null, null],
    ["a Creator-scoped admin read", "/admin/fans/A1/42", "A1", null],
    ["a share token", "/admin/fans/A1/42?t=x", null, null],
  ])("%s", (_n, url, aid, want) => {
    const r = classify(url, aid, CHAT);
    if (want == null) expect(r).toBeNull();
    else expect(r).toMatchObject(want);
  });

  it("key and path", () => {
    expect(screenKey(CHAT)).toBe(CK);
    expect(bundlePath(CK)).toBe("/admin/screens/chat?account=A1&fan=42&lacks=savedReplies");
    expect(bundlePath("chat|A1|42|")).toBe("/admin/screens/chat?account=A1&fan=42");
  });
});

describe("chat outcome", () => {
  const read = (field: Read["field"], extra: Partial<Read> = {}): Read =>
    ({ field, accountId: null, starter: false, bundle: CK, ...extra });
  it("each field is its route's body", () => {
    expect(outcome(BODY, read("seed"))).toEqual({ kind: "body", body: BODY.seed });
    expect(outcome(BODY, read("scheduledSends", { accountId: "A1" }))).toEqual({ kind: "body", body: BODY.scheduledSends });
    expect(outcome(BODY, read("sensitiveWords"))).toEqual({ kind: "miss" });
  });
  it("attribution since: derived from the bare rows", () => {
    expect(outcome(BODY, read("attribution", { since: 6 }))).toEqual({ kind: "body", body: { by_msg_id: { 9: { e: 2 } } } });
  });
  it("an error is the route's; a late read is a miss (no follow-up)", async () => {
    const err = { ...BODY, fan: undefined, errors: [{ accountId: null, read: "fan", status: 404, detail: "nope" }] };
    expect(outcome(err, read("fan"))).toEqual({ kind: "error", status: 404, detail: "nope" });
    setScreen(CHAT);
    const late = { ...BODY, seed: undefined, errors: [{ accountId: null, read: "seed", status: 504, detail: { upstream_status: "bundle_deadline" } }] };
    const get = vi.fn(async () => late);
    prefetchScreen(CHAT, get);
    expect(await screenJoin(screenRead("/admin/messages/A1/42?limit=30", null)!, get)).toEqual({ kind: "miss" });
    expect(get).toHaveBeenCalledTimes(1);
  });
});

describe("attributionSince", () => {
  const rows = (n: number) => ({ by_msg_id: Object.fromEntries(Array.from({ length: n }, (_, i) => [String(i + 1), {}])) });
  it.each<[string, unknown, number, unknown]>([
    ["rows at or past since", { by_msg_id: { 3: 1, 5: 2, 7: 3 } }, 5, { by_msg_id: { 5: 2, 7: 3 } }],
    ["text ids compared as BigInt", { by_msg_id: { "9007199254740993": 1, "9007199254740990": 2 } },
      9007199254740991, { by_msg_id: { "9007199254740993": 1 } }],
    ["at the limit: the route answers", rows(200), 1, null],
    ["under the limit", rows(199), 199, { by_msg_id: { 199: {} } }],
    ["no body", null, 1, null],
  ])("%s", (_n, bare, since, want) => {
    expect(attributionSince(bare, since)).toEqual(want);
  });
});
