import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/relay", () => ({ relay: { get: vi.fn() } }));

import { fetchOlderSeed, mapRows, mergeSeedIntoMessages } from "@/hooks/useChatMessagesLocal";
import { relay, type OFMessage } from "@/lib/relay";

function msg(over: Partial<OFMessage> & { id: number | string }): OFMessage {
  return {
    text: "",
    fromUser: { id: 0 },
    createdAt: "2026-06-04T12:00:00.000Z",
    media: [],
    ...over,
  } as OFMessage;
}

const ids = (rows: OFMessage[]) => rows.map((m) => String(m.id));

describe("mergeSeedIntoMessages", () => {
  it("empty cache: seed becomes the content (cold-open hydration)", () => {
    const seed = [msg({ id: 1 }), msg({ id: 2 }), msg({ id: 3 })];
    expect(mergeSeedIntoMessages(undefined, seed)).toBe(seed);
    expect(mergeSeedIntoMessages([], seed)).toBe(seed);
  });

  it("OF won the race: a superset cache is returned UNCHANGED (same ref → no notify)", () => {
    const ofRows = [msg({ id: 1, mediaCount: 2 }), msg({ id: 2 }), msg({ id: 3 })];
    const seed = [msg({ id: 1 }), msg({ id: 2 })];
    const merged = mergeSeedIntoMessages(ofRows, seed);
    expect(merged).toBe(ofRows);
  });

  it("patcher-first: a live message in the cache is kept; seed history prepends in order", () => {
    const live = msg({ id: 100, text: "just arrived" });
    const seed = [msg({ id: 1 }), msg({ id: 2 }), msg({ id: 3 })];
    const merged = mergeSeedIntoMessages([live], seed);
    expect(ids(merged)).toEqual(["1", "2", "3", "100"]);
    expect(merged[merged.length - 1]).toBe(live);
  });

  it("dedup: rows already in the cache are not duplicated, and the existing (richer) row wins", () => {
    const existingTwo = msg({ id: 2, mediaCount: 5 });
    const seed = [msg({ id: 1 }), msg({ id: 2, mediaCount: 0 }), msg({ id: 3 })];
    const merged = mergeSeedIntoMessages([existingTwo], seed);
    expect(ids(merged)).toEqual(["1", "2", "3"]);
    expect(merged.find((m) => String(m.id) === "2")).toBe(existingTwo);
  });

  it("dedup normalizes id type: number cache id matches string seed id", () => {
    const existing = msg({ id: 5 });
    const seed = [msg({ id: "5" }), msg({ id: 6 })];
    const merged = mergeSeedIntoMessages([existing], seed);
    expect(ids(merged)).toEqual(["5", "6"]);
  });

  it("a seed tip lands in its created_at slot, not prepended to the top", () => {
    const cache = [
      msg({ id: 10, createdAt: "2026-06-01T00:00:00.000Z" }),
      msg({ id: 30, createdAt: "2026-06-03T00:00:00.000Z" }),
    ];
    const seed = [
      msg({ id: 6_000_000_000_000_007, isTip: true, createdAt: "2026-06-02T00:00:00.000Z" }),
    ];
    expect(ids(mergeSeedIntoMessages(cache, seed)))
      .toEqual(["10", "6000000000000007", "30"]);
  });
});

// 5e15 mass-placeholder ids are a just-sent bridge: a stale one must never seed, as the OF fetch can't retire an id that high.
describe("mapRows — mass placeholder staleness", () => {
  const NOW = Date.parse("2026-07-02T12:00:00.000Z");
  const BAND = 5_000_000_000_000_042;

  function row(over: Record<string, unknown>) {
    return {
      account_id: "acct1",
      fan_id: 42,
      message_id: 1,
      direction: "out" as const,
      sender_name: null,
      body: "hey",
      media_count: 0,
      price_cents: 0,
      is_tip: null,
      is_paid: null,
      is_unsent: null,
      purchased_at: null,
      created_at: "2026-07-02T11:59:00",
      ...over,
    };
  }

  it("drops a placeholder older than the 1h bridge window", () => {
    const rows = mapRows(
      [row({ message_id: BAND, created_at: "2026-06-26T15:15:00" })],
      "acct1", 42, NOW,
    );
    expect(rows).toEqual([]);
  });

  it("keeps a fresh placeholder (the just-sent live bridge)", () => {
    const rows = mapRows(
      [row({ message_id: BAND, created_at: "2026-07-02T11:55:00" })],
      "acct1", 42, NOW,
    );
    expect(rows.map((m) => String(m.id))).toEqual([String(BAND)]);
  });

  it("real rows are untouched by the placeholder cutoff, however old", () => {
    const rows = mapRows(
      [row({ message_id: 1000, created_at: "2025-01-01T00:00:00" })],
      "acct1", 42, NOW,
    );
    expect(rows.map((m) => String(m.id))).toEqual(["1000"]);
  });
});

// 6e15 (transaction_ingest._TIP_MSG_ID_BASE) is ledger-synthesized inline tips, rendered only via this seed: the cutoff must never age them out.
describe("mapRows — ledger-tip band is exempt from the cutoff", () => {
  const NOW = Date.parse("2026-07-02T12:00:00.000Z");

  it("keeps a months-old synthetic tip row", () => {
    const rows = mapRows(
      [{
        account_id: "acct1", fan_id: 42,
        message_id: 6_000_000_000_000_042,
        direction: "in" as const, sender_name: null, body: "tipped you",
        media_count: 0, price_cents: 0, is_tip: true, is_paid: null, is_unsent: null,
        purchased_at: null, created_at: "2026-04-01T09:00:00",
      }],
      "acct1", 42, NOW,
    );
    expect(rows.map((m) => String(m.id))).toEqual(["6000000000000042"]);
    expect(rows[0].isTip).toBe(true);
  });
});

describe("mapRows — is_paid → isPaid unlock signal", () => {
  const NOW = Date.parse("2026-07-02T12:00:00.000Z");

  function ppvRow(over: Record<string, unknown>) {
    return {
      account_id: "acct1", fan_id: 42, message_id: 2000,
      direction: "out" as const, sender_name: null, body: "unlock me",
      media_count: 1, price_cents: 2999, is_tip: null, is_paid: null, is_unsent: null,
      purchased_at: null, created_at: "2026-07-02T11:00:00", ...over,
    };
  }

  it("maps a paid PPV to isPaid=true", () => {
    const rows = mapRows([ppvRow({ is_paid: true })], "acct1", 42, NOW);
    expect(rows[0].isPaid).toBe(true);
    expect(rows[0].price).toBe(29.99);
  });

  it("maps an unpaid / null-paid PPV to isPaid=false", () => {
    expect(mapRows([ppvRow({ is_paid: null })], "acct1", 42, NOW)[0].isPaid).toBe(false);
    expect(mapRows([ppvRow({ is_paid: false })], "acct1", 42, NOW)[0].isPaid).toBe(false);
  });
});
