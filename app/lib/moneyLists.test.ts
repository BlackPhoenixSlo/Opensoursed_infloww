import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { relayGet } = vi.hoisted(() => ({ relayGet: vi.fn() }));

vi.mock("@/lib/relay", async (orig) => ({
  ...(await orig<typeof import("@/lib/relay")>()),
  relay: { get: (...args: unknown[]) => relayGet(...args) },
}));

import { RelayError } from "@/lib/relay";
import { isNoRoute, moneyPath, readMoneyList, resetMoneyLists, splitMoneyBody } from "./moneyLists";

const MONEY = "/api/of/v2/users/notifications/money";
const row = (id: number) => ({ id, type: "purchase", text: `r${id}`, createdAt: "2026-11-19T00:00:00Z" });
const tick = () => new Promise((r) => setTimeout(r, 0));

describe("moneyPath", () => {
  it.each([
    [["purchases", "tip"], `${MONEY}?types=purchases%2Ctip&limit=20&offset=0`],
    [["tip", "purchases"], `${MONEY}?types=purchases%2Ctip&limit=20&offset=0`],
    [["tip"], `${MONEY}?types=tip&limit=20&offset=0`],
  ] as const)("%j → %s", (types, want) => {
    expect(moneyPath(types)).toBe(want);
  });
});

describe("splitMoneyBody", () => {
  it.each([
    ["each type's body (array or {list})", { purchases: { list: [row(1)] }, tip: [row(2)] }, { purchases: [1], tip: [2] }],
    ["a type the reply lacks lists nothing (a stub's {list: []})", { list: [] }, { purchases: [], tip: [] }],
    ["not an object", null, { purchases: [], tip: [] }],
    ["a failed type is its error", { purchases: { list: [row(1)] }, errors: { tip: { status: 429, detail: "x" } } },
      { purchases: [1], tip: 429 }],
  ])("%s", (_name, raw, want) => {
    const got = splitMoneyBody(raw, ["purchases", "tip"]);
    const shape = Object.fromEntries(Object.entries(got).map(([t, v]) =>
      [t, v instanceof RelayError ? v.status : v.map((n) => n.id)]));
    expect(shape).toEqual(want);
  });
});

describe("isNoRoute", () => {
  it.each([
    [new RelayError(404, { detail: "Not Found" }), true],
    [new RelayError(404, { detail: "unknown account" }), false],
    [new RelayError(500, { detail: "Not Found" }), false],
    [new Error("x"), false],
  ])("%s → %s", (e, want) => {
    expect(isNoRoute(e)).toBe(want);
  });
});

describe("readMoneyList", () => {
  beforeEach(() => {
    resetMoneyLists();
    relayGet.mockReset();
  });
  afterEach(() => resetMoneyLists());

  const combined = (path: string) => {
    const types = (new URLSearchParams(path.split("?")[1]).get("types") ?? "").split(",");
    return Object.fromEntries(types.map((t) => [t, { list: [row(t === "tip" ? 2 : 1)] }]));
  };

  it("one Creator's types in one tick: one read; another Creator: its own", async () => {
    relayGet.mockImplementation((p: string) => Promise.resolve(combined(p)));
    const got = await Promise.all([readMoneyList("1", "purchases"), readMoneyList("1", "tip"), readMoneyList("2", "tip")]);
    expect(got.map((rows) => rows.map((n) => n.id))).toEqual([[1], [2], [2]]);
    expect(relayGet.mock.calls.map(([p, ctx]) => [p, ctx])).toEqual([
      [moneyPath(["purchases", "tip"]), { accountId: "1", priority: "background" }],
      [moneyPath(["tip"]), { accountId: "2", priority: "background" }],
    ]);
  });

  it("types asked in separate ticks: a read each, only the asked type", async () => {
    relayGet.mockImplementation((p: string) => Promise.resolve(combined(p)));
    await readMoneyList("1", "tip");
    await readMoneyList("1", "purchases");
    expect(relayGet.mock.calls.map(([p]) => p)).toEqual([moneyPath(["tip"]), moneyPath(["purchases"])]);
  });

  it("one type failed: that waiter rejects, the other resolves", async () => {
    relayGet.mockResolvedValue({ purchases: { list: [row(1)] }, errors: { tip: { status: 429, detail: "x" } } });
    const [p, t] = await Promise.allSettled([readMoneyList("1", "purchases"), readMoneyList("1", "tip")]);
    expect(p.status).toBe("fulfilled");
    expect(t.status === "rejected" && (t.reason as RelayError).status).toBe(429);
  });

  it("a relay without the route: per-type reads, now and for the rest of the load", async () => {
    relayGet.mockImplementation((p: string) => p.startsWith(MONEY)
      ? Promise.reject(new RelayError(404, { detail: "Not Found" }))
      : Promise.resolve({ list: [row(p.includes("type=tip") ? 2 : 1)] }));
    const got = await Promise.all([readMoneyList("1", "purchases"), readMoneyList("1", "tip")]);
    expect(got.map((rows) => rows[0].id)).toEqual([1, 2]);
    await readMoneyList("1", "tip");
    expect(relayGet.mock.calls.map(([p]) => p)).toEqual([
      moneyPath(["purchases", "tip"]),
      "/api/of/v2/users/notifications?limit=20&offset=0&type=purchases",
      "/api/of/v2/users/notifications?limit=20&offset=0&type=tip",
      "/api/of/v2/users/notifications?limit=20&offset=0&type=tip",
    ]);
  });

  it("another failure rejects every waiter, no fallback", async () => {
    relayGet.mockRejectedValue(new RelayError(503, { detail: "down" }));
    const r = await Promise.allSettled([readMoneyList("1", "purchases"), readMoneyList("1", "tip")]);
    expect(r.map((x) => x.status)).toEqual(["rejected", "rejected"]);
    expect(relayGet).toHaveBeenCalledTimes(1);
  });

  it("a waiter aborted before the read is left out; one aborted mid-read rejects, the read goes on for the other", async () => {
    let resolve!: (v: unknown) => void;
    relayGet.mockImplementation(() => new Promise((r) => { resolve = r; }));
    const early = new AbortController();
    const mid = new AbortController();
    const a = readMoneyList("1", "purchases", early.signal);
    const aRejected = expect(a).rejects.toBeDefined();
    early.abort();
    const b = readMoneyList("1", "tip", mid.signal);
    const c = readMoneyList("1", "tip");
    await tick();
    expect(relayGet.mock.calls.map(([p]) => p)).toEqual([moneyPath(["tip"])]);
    const readSignal = relayGet.mock.calls[0][2] as AbortSignal;
    mid.abort();
    await expect(b).rejects.toBeDefined();
    expect(readSignal.aborted).toBe(false);
    resolve({ tip: { list: [row(2)] } });
    await aRejected;
    expect((await c).map((n) => n.id)).toEqual([2]);
  });

  it("every waiter aborted mid-read aborts the read", async () => {
    relayGet.mockImplementation(() => new Promise(() => {}));
    const x = new AbortController();
    const y = new AbortController();
    const a = readMoneyList("1", "purchases", x.signal);
    const b = readMoneyList("1", "tip", y.signal);
    await tick();
    const readSignal = relayGet.mock.calls[0][2] as AbortSignal;
    x.abort();
    expect(readSignal.aborted).toBe(false);
    y.abort();
    expect(readSignal.aborted).toBe(true);
    await expect(Promise.allSettled([a, b])).resolves.toHaveLength(2);
  });
});
