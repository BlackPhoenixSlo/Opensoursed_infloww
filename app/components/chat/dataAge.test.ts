/**
 * dataAge — P3 seam 1 (docs/spec/watched-creator-refresher/phase-03-data-age-live-connection-mark.md, Testing
 * Decisions): the mark rows (tickets 17, 18), the age rows (ticket 24). Times are epoch ms on the Relay's clock
 * unless named `tab`.
 */
import { describe, expect, it } from "vitest";

import {
  creatorFreshnessReducer, type CreatorFreshnessState, type Freshness, type HeldFreshness,
} from "@/lib/creatorFreshness";
import {
  asOfText, badgeAge, DOWN_GRACE_MS, liveMark, SLACK_MS, type BadgeAge, type LiveMark,
} from "./dataAge";
import { serverOffset } from "@/lib/ageClock";
import { badgeUnread, unreadBadgeSources } from "./unreadBadge";

const T = 1_800_000_000_000; // the Relay's now in every row unless skewed
const S = 1_000;
const MIN = 60 * S;
type Facts = Pick<Freshness, "live" | "live_since">;
const facts = (live: Facts["live"], sinceAgo: number | null): Facts =>
  ({ live, live_since: sinceAgo === null ? null : T - sinceAgo });

const DOWN_3 = "No live connection for 3 min: new messages may arrive late";

describe("liveMark", () => {
  // [row, facts, isDead (the account's session_dead_at), kind or null, title]
  it.each<[string, Facts | null, boolean, LiveMark["kind"] | null, string?]>([
    ["up → none", facts("up", 10 * MIN), false, null],
    ["down 59.9 s → none", facts("down", 59_900), false, null],
    ["down 60 s → down", facts("down", DOWN_GRACE_MS), false, "down", "No live connection for 1 min: new messages may arrive late"],
    ["down 3 min → down, whole minutes", facts("down", 3 * MIN + 59 * S), false, "down", DOWN_3],
    ["down then up → none (clears at once)", facts("up", 1 * S), false, null],
    // Down 5 s, up long enough for the Relay's 5 s tick, down 5 s: `live_since` restarted.
    ["flap the Relay saw → none", facts("down", 5 * S), false, null],
    // The "up" was shorter than one tick: one outage, `live_since` 55 s ago, then 60 s.
    ["flap it missed, 55 s → none", facts("down", 55 * S), false, null],
    ["flap it missed, 60 s → down", facts("down", 60 * S), false, "down"],
    // Fansly / no pump: never "down" on the Relay, never amber here.
    ["live null → none", facts(null, null), false, null],
    ["no snapshot, not dead → none", null, false, null],
    // A restart's reconnect wave: every Creator down since boot.
    ["restart wave, 30 s after boot → none", facts("down", 30 * S), false, null],
    ["restart wave, 59 s after boot → none", facts("down", 59 * S), false, null],
    // ASSUMPTION: the Relay sets `live_since` whenever `live` is not null (service/shared_refresher.py:30); a
    // "down" without one is unknown, not down: no mark.
    ["down, no live_since → none", facts("down", null), false, null],
    // Ticket 18: Dead session.
    ["live dead → dead at once", facts("dead", 0), false, "dead", "Disconnected"],
    ["live dead, account not flagged yet → dead", facts("dead", 1 * S), false, "dead"],
    ["snapshot up + stale session_dead_at → none (re-captured)", facts("up", 3 * S), true, null],
    ["snapshot down past grace + stale session_dead_at → down", facts("down", 3 * MIN), true, "down", DOWN_3],
    ["no snapshot + session_dead_at → dead", null, true, "dead", "Disconnected"],
    ["Fansly (live null) + session_dead_at → dead, never down", facts(null, null), true, "dead", "Disconnected"],
  ])("%s", (_row, f, isDead, kind, title) => {
    const m = liveMark(f, isDead, T, 0);
    expect(m?.kind ?? null).toBe(kind);
    if (title) expect(m?.title).toBe(title);
  });

  it("texts: down reads \"No live connection\"; dead reads the Creators page's word (sessionConnectivity)", () => {
    expect(liveMark(facts("down", 3 * MIN), false, T, 0)).toEqual({
      kind: "down", text: "No live connection", title: DOWN_3, srText: "no live connection",
    });
    expect(liveMark(facts("dead", 0), false, T, 0)).toEqual({
      kind: "dead", text: "Disconnected", title: "Disconnected", srText: "disconnected",
    });
  });

  // Tab clock +5 min (or −5 min) against the Relay: the offset from the seed's `now` gives the same verdicts.
  it.each<[string, Facts | null, boolean, LiveMark["kind"] | null]>([
    ["down 59.9 s", facts("down", 59_900), false, null],
    ["down 60 s", facts("down", 60 * S), false, "down"],
    ["down 3 min", facts("down", 3 * MIN), false, "down"],
    ["up", facts("up", 10 * MIN), false, null],
    ["restart wave 30 s", facts("down", 30 * S), false, null],
  ])("skewed tab clock, %s → same verdict", (_row, f, isDead, kind) => {
    for (const skew of [5 * MIN, -5 * MIN]) {
      const seedReceivedAt = T - 2 * MIN + skew; // the seed answered 2 min ago on the Relay's clock
      const offset = serverOffset(T - 2 * MIN, seedReceivedAt);
      expect(liveMark(f, isDead, T + skew, offset)?.kind ?? null).toBe(kind);
    }
    // Without the offset a +5 min tab clock marks a Creator down 30 s.
    expect(liveMark(facts("down", 30 * S), false, T + 5 * MIN, 0)?.kind).toBe("down");
  });
});

describe("serverOffset", () => {
  it.each<[string, number, number, number]>([
    ["no skew", T, T, 0],
    ["tab clock 5 min ahead", T, T + 5 * MIN, 5 * MIN],
    ["tab clock 5 min behind", T, T - 5 * MIN, -5 * MIN],
  ])("%s", (_row, serverMs, receivedAt, want) => {
    expect(serverOffset(serverMs, receivedAt)).toBe(want);
  });
});

// ── Age (ticket 24) ──────────────────────────────────────────────────────────────────────────────────────────────

const LEASE = 120;
const TAB = 600;
/** One held Creator: the total confirmed `ago` ms before T, its Cycle, its Live connection. */
const held = (aid: string, ago: number | null, cycle_s: number | null, over: Partial<Freshness> = {}): HeldFreshness => ({
  account_id: aid, boot: 1, seq: 1, now: T, at: ago === null ? null : T - ago, cycle_s, live: "up", live_since: T - 1 * MIN,
  values: { unread_total: ago === null ? null : { n: 3, at: T - ago } }, receivedAt: T, ...over,
});
const stateOf = (...hs: HeldFreshness[]): CreatorFreshnessState => Object.fromEntries(hs.map((h) => [h.account_id, h]));
/** The age as the chip gets it: Phase 2's sources over every held Creator. */
const ageOf = (state: CreatorFreshnessState, dead: string[] = [], tabNow = T, offset = 0): BadgeAge | null =>
  badgeAge(unreadBadgeSources(state, Object.keys(state)), state, new Set(dead), tabNow, offset);

describe("badgeAge", () => {
  it("SLACK_MS is 40 s (needs-human: one constant)", () => {
    expect(SLACK_MS).toBe(40_000);
  });

  // [row, state, dead ids, text or null (fresh / no age)]
  it.each<[string, CreatorFreshnessState, string[], string | null]>([
    ["no snapshot at all (Knob off) → none", stateOf(), [], null],
    ["at null (not read since boot) → none", stateOf(held("a", null, LEASE)), [], null],
    ["cycle_s null (not read by design) → none", stateOf(held("a", 10 * MIN, null)), [], null],
    ["lease 120 s, 160 s → fresh", stateOf(held("a", 160 * S, LEASE)), [], null],
    ["lease 120 s, 160.001 s → as of 2 min", stateOf(held("a", 160 * S + 1, LEASE)), [], "as of 2 min"],
    ["tab 600 s, 640 s → fresh", stateOf(held("a", 640 * S, TAB)), [], null],
    ["tab 600 s, 11 min → as of 11 min", stateOf(held("a", 11 * MIN, TAB)), [], "as of 11 min"],
    // The current Cycle, not the one in force at the read.
    ["tier-up 600 → 120 at 8 min → as of 8 min", stateOf(held("a", 8 * MIN, LEASE)), [], "as of 8 min"],
    ["tier-down 120 → 600 at 5 min → fresh (never early)", stateOf(held("a", 5 * MIN, TAB)), [], null],
    ["count 0 and late → shown", stateOf(held("a", 5 * MIN, LEASE, { values: { unread_total: { n: 0, at: T - 5 * MIN } } })),
      [], "as of 5 min"],
    ["Dead session (live dead) excluded", stateOf(held("a", 30 * MIN, LEASE, { live: "dead" })), [], null],
    ["Dead session (Fansly, session_dead_at) excluded", stateOf(held("a", 30 * MIN, LEASE, { live: null })), ["a"], null],
    ["snapshot up beside a stale session_dead_at (re-captured) → counted", stateOf(held("a", 5 * MIN, LEASE)), ["a"],
      "as of 5 min"],
    ["negative age (noise) → 0, fresh", stateOf(held("a", -5 * S, LEASE)), [], null],
    // Independent of the mark: `live` up and `at` late → age.
    ["live up + at late → age", stateOf(held("a", 5 * MIN, LEASE, { live: "up" })), [], "as of 5 min"],
  ])("%s", (_row, state, dead, text) => {
    expect(ageOf(state, dead)?.text ?? null).toBe(text);
  });

  it("live down past grace + at fresh → mark, no age", () => {
    const h = held("a", 30 * S, LEASE, { live: "down", live_since: T - 3 * MIN });
    expect(ageOf(stateOf(h))).toBeNull();
    expect(liveMark(h, false, T, 0)?.kind).toBe("down");
  });

  it("live up + at late → age, no mark", () => {
    const h = held("a", 5 * MIN, LEASE, { live: "up" });
    expect(ageOf(stateOf(h))?.text).toBe("as of 5 min");
    expect(liveMark(h, false, T, 0)).toBeNull();
  });

  it("which at: the source's only; a creator_warmed of now beside a 5 min old source (lease) → as of 5 min", () => {
    const h = held("a", 5 * MIN, LEASE, { values: { unread_total: { n: 2, at: T - 5 * MIN }, creator_warmed: { at: T } } });
    expect(ageOf(stateOf(h))?.text).toBe("as of 5 min");
  });

  it("which at: Last refresh fresh, the total's at old → fresh (max of the two)", () => {
    const h = held("a", 5 * MIN, LEASE, { at: T - 10 * S });
    expect(ageOf(stateOf(h))).toBeNull();
  });

  it("quiet Creator: a ping advances its source at with n unchanged → fresh (story 32)", () => {
    const quiet = stateOf(held("a", 5 * MIN, LEASE));
    expect(ageOf(quiet)?.text).toBe("as of 5 min");
    const pinged = creatorFreshnessReducer(quiet, { type: "confirmed", fresh: { a: T - 10 * S }, now: T, receivedAt: T });
    expect(pinged.a.values.unread_total).toEqual({ n: 3, at: T - 5 * MIN });
    expect(ageOf(pinged)).toBeNull();
  });

  it("fallback Creator (no held total) or search → no age (sources are fromTotal only)", () => {
    const state = stateOf(held("a", 30 * MIN, LEASE, { at: null, values: {} }), held("b", 30 * MIN, LEASE));
    const count = () => 1;
    const shown = ["a", "b"];
    const plain = badgeUnread(state, shown, count, { ready: true, search: false });
    expect(plain.fallback).toEqual(["a"]);
    expect(badgeAge(unreadBadgeSources(state, plain.fromTotal), state, new Set(), T, 0)?.of).toBe(1);
    const search = badgeUnread(state, shown, count, { ready: true, search: true });
    expect(badgeAge(unreadBadgeSources(state, search.fromTotal), state, new Set(), T, 0)).toBeNull();
    const notYet = badgeUnread(state, shown, count, { ready: false, search: false });
    expect(badgeAge(unreadBadgeSources(state, notYet.fromTotal), state, new Set(), T, 0)).toBeNull();
  });

  it("10 Creators with 1 late → late 1, of 10, its age", () => {
    const hs = Array.from({ length: 10 }, (_, i) => held(`c${i}`, i === 3 ? 12 * MIN : 30 * S, LEASE));
    const a = ageOf(stateOf(...hs));
    expect(a).toMatchObject({ ageMs: 12 * MIN, late: 1, of: 10, text: "as of 12 min" });
  });

  it("2 late → the oldest; a Dead or unread Creator is not one of `of`", () => {
    const hs = [
      held("a", 4 * MIN, LEASE), held("b", 9 * MIN, LEASE), held("c", 30 * S, LEASE),
      held("d", 60 * MIN, LEASE, { live: "dead" }), held("e", null, LEASE), held("f", 60 * MIN, null),
    ];
    expect(ageOf(stateOf(...hs))).toMatchObject({ ageMs: 9 * MIN, late: 2, of: 3, text: "as of 9 min" });
  });

  // Tab clock ±5 min against the Relay: the offset (ping or seed `now`) gives the same verdicts; with neither (0) the
  // tab clock is taken as is.
  it.each<[string, number, number, string | null]>([
    ["lease 160 s", 160 * S, LEASE, null],
    ["lease 161 s", 161 * S, LEASE, "as of 2 min"],
    ["tab 11 min", 11 * MIN, TAB, "as of 11 min"],
    ["tab 5 min", 5 * MIN, TAB, null],
  ])("skewed tab clock, %s → same verdict", (_row, ago, cycle, text) => {
    const state = stateOf(held("a", ago, cycle));
    for (const skew of [5 * MIN, -5 * MIN]) {
      const offset = serverOffset(T - 1 * MIN, T - 1 * MIN + skew); // the latest ping or seed, a minute ago
      expect(ageOf(state, [], T + skew, offset)?.text ?? null).toBe(text);
    }
    expect(ageOf(state, [], T, 0)?.text ?? null).toBe(text);
  });
});

describe("badgeAge title (whole minutes)", () => {
  it.each<[string, CreatorFreshnessState, string]>([
    ["1 of 10", stateOf(...Array.from({ length: 10 }, (_, i) => held(`c${i}`, i ? 30 * S : 12 * MIN, LEASE))),
      "As of 12 min ago: 1 of 10 Creators not refreshed within its Cycle"],
    ["2 of 10", stateOf(...Array.from({ length: 10 }, (_, i) => held(`c${i}`, i < 2 ? (4 + i) * MIN : 30 * S, LEASE))),
      "As of 5 min ago: 2 of 10 Creators not refreshed within its Cycle"],
    ["one Creator, lease", stateOf(held("a", 4 * MIN, LEASE)), "As of 4 min ago: not refreshed within its 2 min Cycle"],
    ["one Creator, 119 min", stateOf(held("a", 119 * MIN + 59 * S, TAB)),
      "As of 119 min ago: not refreshed within its 10 min Cycle"],
    ["25 h: minutes, not days", stateOf(held("a", 25 * 60 * MIN, TAB)),
      "As of 1500 min ago: not refreshed within its 10 min Cycle"],
  ])("%s", (_row, state, title) => {
    expect(ageOf(state)?.title).toBe(title);
  });
});

describe("asOfText", () => {
  it.each<[string, number, string]>([
    ["150 s", 150 * S, "as of 2 min"],
    ["59 min 59 s", 59 * MIN + 59 * S, "as of 59 min"],
    ["60 min", 60 * MIN, "as of 1 h"],
    ["23 h 59 min", 24 * 60 * MIN - 1 * MIN, "as of 23 h"],
    ["25 h", 25 * 60 * MIN, "as of 1 d"],
    ["3 d", 3 * 24 * 60 * MIN, "as of 3 d"],
  ])("%s", (_row, ms, want) => {
    expect(asOfText(ms)).toBe(want);
  });
});
