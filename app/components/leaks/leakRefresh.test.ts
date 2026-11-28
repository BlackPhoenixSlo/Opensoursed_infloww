import { describe, expect, it } from "vitest";

import { RelayError } from "@/lib/relay";

import {
  cooldownUntil, loaded, RECHECK_FOR_MS, RECHECK_MS, recheck, refreshReducer, refreshView, type Action, type RefreshState,
} from "./leakRefresh";

const PAST = "2026-11-27T04:00:00Z";
const LATER = "2026-11-28T04:00:00Z";
const NOW = new Date("2026-11-27T12:00:00Z");

const STATES: Record<string, RefreshState> = {
  ready: loaded(PAST, false),
  pending: loaded(null, true),
  waiting: loaded(LATER, false),
  sending: { phase: "sending", nextRefreshAt: PAST, pending: false, message: null },
  failed: { phase: "failed", nextRefreshAt: PAST, pending: false, message: "Try again shortly" },
};

const ACTIONS: Record<string, Action> = {
  load: { type: "load", nextRefreshAt: LATER, pending: true },
  send: { type: "send" },
  queued: { type: "queued", nextRefreshAt: LATER },
  cooldown: { type: "cooldown", nextRefreshAt: LATER },
  fail: { type: "fail", message: "Tracking is off for this Creator" },
};

const same = "same";
const TABLE: [string, string, RefreshState | typeof same][] = [
  ["ready", "load", loaded(LATER, true)],
  ["ready", "send", { ...STATES.ready, phase: "sending" }],
  ["ready", "queued", same],
  ["ready", "cooldown", same],
  ["ready", "fail", same],
  ["pending", "load", loaded(LATER, true)],
  ["pending", "send", same],
  ["pending", "queued", same],
  ["pending", "cooldown", same],
  ["pending", "fail", same],
  ["waiting", "load", loaded(LATER, true)],
  ["waiting", "send", { ...STATES.waiting, phase: "sending" }],
  ["waiting", "queued", same],
  ["waiting", "cooldown", same],
  ["waiting", "fail", same],
  ["sending", "load", { ...STATES.sending, nextRefreshAt: LATER, pending: true }],
  ["sending", "send", same],
  ["sending", "queued", loaded(LATER, true)],
  ["sending", "cooldown", loaded(LATER, false)],
  ["sending", "fail", { ...STATES.sending, phase: "failed", message: "Tracking is off for this Creator" }],
  ["failed", "load", loaded(LATER, true)],
  ["failed", "send", { ...STATES.failed, phase: "sending", message: null }],
  ["failed", "queued", same],
  ["failed", "cooldown", same],
  ["failed", "fail", same],
];

describe("refreshReducer", () => {
  it("the table covers every action from every state", () => {
    const covered = new Set(TABLE.map(([s, a]) => `${s}/${a}`));
    for (const s of Object.keys(STATES)) for (const a of Object.keys(ACTIONS)) expect(covered).toContain(`${s}/${a}`);
  });

  it.each(TABLE)("%s + %s", (from, action, want) => {
    const got = refreshReducer(STATES[from], ACTIONS[action]);
    if (want === same) expect(got).toBe(STATES[from]);
    else expect(got).toEqual(want);
  });

  it("a load with nothing pending and no next refresh reads ready", () => {
    expect(refreshReducer(STATES.pending, { type: "load", nextRefreshAt: null, pending: false })).toEqual(loaded(null, false));
  });
});

describe("refreshView", () => {
  const ONCE = "One refresh per Creator every 24 hours";
  it.each<[string, RefreshState, ReturnType<typeof refreshView>]>([
    ["never refreshed", loaded(null, false), { label: "Refresh now", disabled: false, note: null, error: false }],
    ["next refresh in the past", STATES.ready, { label: "Refresh now", disabled: false, note: null, error: false }],
    ["next refresh ahead", STATES.waiting, { label: "Next refresh 28 Nov 04:00", disabled: true, note: ONCE, error: false }],
    ["next refresh later today", loaded("2026-11-27T20:30:00Z", false),
      { label: "Next refresh Today 20:30", disabled: true, note: ONCE, error: false }],
    ["unreadable next refresh", loaded("soon", false), { label: "Refresh now", disabled: false, note: null, error: false }],
    ["a scan pending", STATES.pending, { label: "Checking…", disabled: true, note: null, error: false }],
    ["pending wins over a cooldown time", loaded(LATER, true), { label: "Checking…", disabled: true, note: null, error: false }],
    ["sending", STATES.sending, { label: "Refreshing…", disabled: true, note: null, error: false }],
    ["failed shows the detail and stays enabled", STATES.failed,
      { label: "Refresh now", disabled: false, note: "Try again shortly", error: true }],
  ])("%s", (_name, state, want) => {
    expect(refreshView(state, NOW, "UTC")).toEqual(want);
  });
});

describe("cooldownUntil", () => {
  it.each<[string, unknown, string | null]>([
    ["a cooldown 429", new RelayError(429, { detail: "Refreshed recently", next_refresh_at: LATER }), LATER],
    ["a rate-limit 429", new RelayError(429, { detail: "Try again shortly", next_refresh_at: null }), null],
    ["a 429 with no body", new RelayError(429, null), null],
    ["a 429 with a text body", new RelayError(429, "Too Many Requests"), null],
    ["a 429 with a number", new RelayError(429, { next_refresh_at: 5 }), null],
    ["another status", new RelayError(409, { next_refresh_at: LATER }), null],
    ["not a relay error", new Error("boom"), null],
  ])("%s", (_name, e, want) => {
    expect(cooldownUntil(e)).toBe(want);
  });
});

describe("recheck", () => {
  const T = 1_000_000;
  it.each<[string, boolean, number | null, number, ReturnType<typeof recheck>]>([
    ["not pending stops and forgets", false, T, T + 60_000, { every: false, since: null }],
    ["first pending read starts the clock", true, null, T, { every: RECHECK_MS, since: T }],
    ["still pending inside 10 min", true, T, T + RECHECK_FOR_MS - 1, { every: RECHECK_MS, since: T }],
    ["pending for 10 min stops", true, T, T + RECHECK_FOR_MS, { every: false, since: T }],
    ["pending long after keeps stopped", true, T, T + 3 * RECHECK_FOR_MS, { every: false, since: T }],
  ])("%s", (_name, pending, since, now, want) => {
    expect(recheck(pending, since, now)).toEqual(want);
  });

  it("a new pending after a finished scan starts a fresh 10 min", () => {
    const done = recheck(false, 0, RECHECK_FOR_MS * 2);
    expect(recheck(true, done.since, RECHECK_FOR_MS * 3)).toEqual({ every: RECHECK_MS, since: RECHECK_FOR_MS * 3 });
  });
});
