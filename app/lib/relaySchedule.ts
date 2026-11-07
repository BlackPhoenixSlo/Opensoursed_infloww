/**
 * relaySchedule — the rules for the browser's background OnlyFans reads (pure; relay.ts runs them).
 *
 * A screen's per-Creator burst (badges, rosters, profiles, chat lists) went out all at once: a big
 * agency put a hundred-plus reads on the phone's one connection beside the user's click, most of them
 * only to wait in the relay, which runs at most 2 background reads per Creator at a time
 * (service/server.py `_ACCOUNT_LANE_BACKGROUND`), and a screen left mid-load could not take back the
 * ones already sent. Now a read tagged `background` (a GET under /api/of/) waits here: at most
 * `perCreator` of one Creator's on the wire (the relay's lane, so nothing is slower: the relay would
 * hold the rest anyway), and at most `SLOW_CAP` in all when the browser says the link is starved
 * (2g/3g or Save-Data). Waiting reads are dropped when their screen goes away. The Creator the user
 * has open never waits (its reads are the user's), and a user read never queues (relay.ts sends it at
 * once, fetch priority high).
 *
 * The open screen's own reads (a read its bundle covers that went out per Creator: lib/screenBundle.ts) start before
 * every other background read. While its bundle fails (`reserve`: a blocked or broken bundle, so each of its reads
 * goes out on its own), the other reads (the money rail's feeds, rosters) take at most `perCreator - 1` of a
 * Creator's slots: the last one is the screen's, so two slow rail feeds never hold its chat list back.
 *
 * Why no tighter cap on a high-latency link: those reads wait on round trips, not bandwidth, so fewer
 * in flight only adds round trips. Measured (slop clicks-first, 250 ms RTT, 13 Creators): 2 in all
 * took the cold Dashboard from 3.9 s to 17.3 s, 24 in all to 4.7 s, and a click went ahead either way.
 */

export type Lane = "user" | "background";

export interface Job {
  id: number;
  /** The Creator the read is for (`X-Account-Id`); null when unscoped (one lane of its own). */
  accountId: string | null;
  /** A read the open screen's bundle covers, gone out on its own (a miss, a failed or late bundle). */
  screen?: boolean;
}

export interface ScheduleState {
  /** Background reads waiting for a slot, in arrival order. */
  queue: readonly Job[];
  /** Background reads on the wire. */
  onWire: readonly Job[];
  /** The most of one Creator's background reads on the wire: the relay's background lane per Creator. */
  perCreator: number;
  /** The Creator the user has open (Messages Pro's chat or scope, or a pressed Fan row): its reads never wait. */
  focus: string | null;
  /** navigator.connection's estimate, when the browser has one (Chromium; Safari has none). */
  net: { effectiveType?: string; saveData?: boolean } | null;
  /** The open screen's last bundle failed: its reads go out per Creator, and each Creator keeps a slot for them. */
  reserve: boolean;
}

export type Action =
  | { type: "enqueue"; job: Job }
  | { type: "start"; ids: readonly number[] }
  /** Finished, or aborted (its screen went away): gone from the queue and the wire. */
  | { type: "done"; id: number }
  | { type: "focus"; accountId: string | null }
  | { type: "net"; effectiveType?: string; saveData?: boolean }
  /** A screen bundle's call failed (on) or answered (off). */
  | { type: "reserve"; on: boolean };

/** service/server.py `_ACCOUNT_LANE_BACKGROUND`'s default. */
export const PER_CREATOR = 2;
export const SLOW_CAP = 4;

export const initialSchedule: ScheduleState = {
  queue: [], onWire: [], perCreator: PER_CREATOR, focus: null, net: null, reserve: false,
};

/** A starved link: the browser says 2g / 3g, or the user asked to save data. */
export function isSlow(s: Pick<ScheduleState, "net">): boolean {
  const n = s.net;
  return !!n && (n.saveData === true || /(^|-)(2g|3g)$/.test(n.effectiveType ?? ""));
}

/** The waiting reads to start now, in start order: every read of the focus Creator, then the screen's reads, then
 *  the rest, each in arrival order while its Creator has fewer than `perCreator` on the wire (and, under `reserve`,
 *  fewer than `perCreator - 1` of the rest, never below 1; on a starved link: while fewer than SLOW_CAP in all). */
export function admissible(s: ScheduleState): number[] {
  if (!s.queue.length) return [];
  const isFocus = (j: Job) => s.focus != null && j.accountId === s.focus;
  const out = s.queue.filter(isFocus).map((j) => j.id);
  const busy = new Map<string | null, number>();
  const rest = new Map<string | null, number>();
  const add = (m: Map<string | null, number>, k: string | null) => m.set(k, (m.get(k) ?? 0) + 1);
  for (const j of s.onWire) {
    add(busy, j.accountId);
    if (!j.screen) add(rest, j.accountId);
  }
  let total = s.onWire.length + out.length;
  const slow = isSlow(s);
  const restCap = s.reserve ? Math.max(1, s.perCreator - 1) : s.perCreator;
  for (const screen of [true, false]) {
    for (const j of s.queue) {
      if (isFocus(j) || !!j.screen !== screen) continue;
      if (slow && total >= SLOW_CAP) break;
      if ((busy.get(j.accountId) ?? 0) >= s.perCreator) continue;
      if (!screen && (rest.get(j.accountId) ?? 0) >= restCap) continue;
      add(busy, j.accountId);
      if (!screen) add(rest, j.accountId);
      total += 1;
      out.push(j.id);
    }
  }
  return out;
}

export function scheduleReducer(s: ScheduleState, a: Action): ScheduleState {
  switch (a.type) {
    case "enqueue":
      return { ...s, queue: [...s.queue, a.job] };
    case "start": {
      const ids = new Set(a.ids);
      return { ...s, queue: s.queue.filter((j) => !ids.has(j.id)), onWire: [...s.onWire, ...s.queue.filter((j) => ids.has(j.id))] };
    }
    case "done":
      return { ...s, queue: s.queue.filter((j) => j.id !== a.id), onWire: s.onWire.filter((j) => j.id !== a.id) };
    case "focus":
      return a.accountId === s.focus ? s : { ...s, focus: a.accountId };
    case "net":
      return { ...s, net: { effectiveType: a.effectiveType, saveData: a.saveData } };
    case "reserve":
      return a.on === s.reserve ? s : { ...s, reserve: a.on };
  }
}
