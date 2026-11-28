import { describe, expect, it } from "vitest";

import { RelayError } from "@/lib/relay";

import { cooldown, refreshCheck, refreshView, unchanged } from "./leakRefresh";

const NOW = new Date("2026-11-27T12:00:00Z");
const LATER = "2026-11-28T04:00:00Z";
const QUEUED = new Date(100).toISOString();
const READY = { sending: false, localNextRefreshAt: null, error: null };

describe("refreshView", () => {
  it.each([
    ["sending", { ...READY, sending: true }, { nextRefreshAt: null, pending: true, expired: false }, "Refreshing…", true],
    ["expired pending", READY, { nextRefreshAt: LATER, pending: true, expired: true }, "Check refresh status", false],
    ["pending", READY, { nextRefreshAt: LATER, pending: true, expired: false }, "Checking…", true],
    ["server cooldown", READY, { nextRefreshAt: LATER, pending: false, expired: false }, "Next refresh 28 Nov 04:00", true],
    ["local cooldown", { ...READY, localNextRefreshAt: LATER },
      { nextRefreshAt: "2026-11-27T04:00:00Z", pending: false, expired: false }, "Next refresh 28 Nov 04:00", true],
    ["expired", { ...READY, localNextRefreshAt: NOW.toISOString() },
      { nextRefreshAt: null, pending: false, expired: false }, "Refresh now", false],
  ] as const)("%s", (_name, local, server, label, disabled) => {
    expect(refreshView(local, server, NOW, "UTC")).toMatchObject({ label, disabled });
  });
});

describe("refreshCheck", () => {
  const idle = { phase: "idle" } as const;
  const acked = refreshCheck(idle, { type: "acked", at: 100, next: LATER, queuedAt: QUEUED });
  const pending = { type: "read", at: 200, pending: true, fresh: true, next: null, checkedAt: null } as const;
  const seen = refreshCheck(acked, pending);
  const complete = { ...pending, pending: false };
  const expired = refreshCheck(acked, { type: "expired" });

  it.each([
    ["starts on acknowledgement", idle, { type: "acked", at: 100, next: LATER, queuedAt: QUEUED },
      { phase: "checking", started: 100, next: LATER, seenPending: false, queuedAt: QUEUED }],
    ["starts on a pending read", idle, pending, { phase: "checking", started: 200, next: null, seenPending: true, queuedAt: null }],
    ["ignores an older cached read", acked, { ...complete, at: 99, next: LATER }, acked],
    ["ignores an unrelated completed scan", acked, complete, acked],
    ["accepts completion matching the acknowledgement", acked, { ...complete, next: LATER }, { phase: "done" }],
    ["keeps the original deadline on a pending read", acked, pending,
      { phase: "checking", started: 100, next: LATER, seenPending: true, queuedAt: QUEUED }],
    ["ignores stale completion", seen, { ...complete, fresh: false }, seen],
    ["first good read completed after queue despite a different cooldown", acked,
      { ...complete, checkedAt: new Date(150).toISOString() }, { phase: "done" }],
    ["ignores a scan older than queue", acked,
      { ...complete, checkedAt: new Date(50).toISOString() }, acked],
    ["completes on a read retry after expiry", expired, complete, { phase: "done" }],
    ["completes after observing pending", seen, complete, { phase: "done" }],
    ["expires", acked, { type: "expired" }, { phase: "expired" }],
    ["stays expired across pending reads", expired, pending, expired],
  ] as const)("%s", (_name, state, action, expected) => {
    expect(refreshCheck(state, action)).toEqual(expected);
  });
});

it.each([[429, true], [503, true], [409, false], [502, false]] as const)("status %i leaves queries unchanged: %s",
  (status, expected) => expect(unchanged(new RelayError(status, null))).toBe(expected));

describe("cooldown", () => {
  it.each<[string, unknown, string | null]>([
    ["a cooldown 429", new RelayError(429, { detail: "Refreshed recently", next_refresh_at: LATER }), LATER],
    ["a rate-limit 429 with a relay deadline", new RelayError(429, { detail: "Try again shortly", next_refresh_at: LATER }), LATER],
    ["a rate-limit 429", new RelayError(429, { detail: "Try again shortly", next_refresh_at: null }), null],
    ["a 429 with no body", new RelayError(429, null), null],
    ["a 429 with a text body", new RelayError(429, "Too Many Requests"), null],
    ["a 429 with a number", new RelayError(429, { next_refresh_at: 5 }), null],
    ["another status", new RelayError(409, { next_refresh_at: LATER }), null],
    ["not a relay error", new Error("boom"), null],
  ])("%s", (_name, e, want) => {
    expect(cooldown(e)?.until ?? null).toBe(want);
  });
});
