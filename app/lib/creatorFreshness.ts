/**
 * The tab's per-Creator `Freshness` store (docs/spec/watched-creator-refresher/phase-01-shared-refresher.md,
 * Contract 1, 5): what the Relay's Shared refresher last confirmed for each Creator, seeded from each network
 * accounts answer (`useAccounts`), moved by each `creator_refreshed` (`useAccountStateEvents`) and confirmed by each
 * stream ping's `fresh` (`confirmed`: Contract 7). A pure reducer
 * (hooks/useCreatorFreshness.ts holds the state in React Query and only dispatches); `of` reads one Creator.
 *
 * Freshness only moves forward. Per Creator a delivery (seed or event) replaces the held snapshot only when its
 * `(boot, seq)` is not lower, compared as a pair: a higher `boot` (a Relay restart) replaces whole. Within a boot
 * `at` and every slot's `at` take the max of held and delivered, so a late seed never rolls `at` back. Each held
 * snapshot keeps `receivedAt` (the tab's clock) beside the Relay's `now` from the same delivery: the skew reference.
 * A ping (`confirmed`) only raises a held Creator's `at` (never a slot's, never `boot` or `seq`), and with it takes
 * the ping's `now` / `receivedAt` pair; a Creator not held, or an `at` not later, is left alone.
 * Eviction (Contract 6): a seed (a network accounts answer) drops every held Creator whose row has no `freshness` or
 * is absent, so a switch-off (Knob off + restart) empties the store and the tab shows today's screen;
 * `identityChanged` clears all.
 * A change-free delivery returns the same state object, so the Knob off (no row carries `freshness`) writes nothing.
 */

/** A slot under `values` that carries its own confirmation time (Phase 2's `unread_total`). */
export interface TimedSlot { at: number; [k: string]: unknown }

export interface FreshnessValues {
  /** Only with `SHARED_REFRESHER_BELL=me`. */
  notif_count?: number;
  /** Phase 2; key present iff `UNREAD_TOTAL` is on; null: none yet. */
  unread_total?: { n: number; at: number } | null;
  [slot: string]: unknown;
}

/** The Relay's snapshot of one Creator (Contract 1): the accounts rows' `freshness`, the `creator_refreshed` body. */
export interface Freshness {
  account_id: string;
  /** Epoch ms the Relay process started. */
  boot: number;
  /** Per Creator per boot, +1 on every publish. */
  seq: number;
  /** Epoch ms, Relay clock at send time. */
  now: number;
  /** Epoch ms, Relay clock: the Last refresh; null: none since boot. */
  at: number | null;
  /** The Creator's Cycle; null: not read. */
  cycle_s: number | null;
  live: "up" | "down" | "dead" | null;
  live_since: number | null;
  values: FreshnessValues;
}

/** A held snapshot: the delivery it came in, with the tab's clock at its arrival. */
export type HeldFreshness = Freshness & { receivedAt: number };

export type CreatorFreshnessState = Readonly<Record<string, HeldFreshness>>;

export const EMPTY_FRESHNESS: CreatorFreshnessState = {};

/** One accounts-answer row as the seed sees it (owner `id`, chatter `account_id` mapped to it). */
export interface SeedRow { id: string; freshness?: Freshness | null }

export type Action =
  | { type: "seeded"; rows: readonly SeedRow[]; receivedAt: number }
  | { type: "refreshed"; body: unknown; receivedAt: number }
  /** A stream ping's `fresh` (`{aid: at}`, epoch ms) and its `ts` as epoch ms (`now`). */
  | { type: "confirmed"; fresh: Readonly<Record<string, number>>; now: number; receivedAt: number }
  /** The signed-in principal changed: nothing held is theirs. */
  | { type: "identityChanged" };

const isNum = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);

/** The event body as a Freshness, or null when it is not one (no id, boot, seq or now; no `values` object). */
function parse(body: unknown): Freshness | null {
  if (!body || typeof body !== "object") return null;
  const b = body as Partial<Freshness>;
  if (typeof b.account_id !== "string" || !isNum(b.boot) || !isNum(b.seq) || !isNum(b.now)) return null;
  if (!b.values || typeof b.values !== "object") return null;
  return b as Freshness;
}

const maxAt = (a: number | null, b: number | null): number | null => (a === null ? b : b === null ? a : Math.max(a, b));

const timed = (v: unknown): v is TimedSlot => !!v && typeof v === "object" && isNum((v as TimedSlot).at);

/** `base` with `at` and each slot's `at` raised to `other`'s where higher (same boot). */
function withMaxAts(base: HeldFreshness, other: Freshness): HeldFreshness {
  const values: FreshnessValues = { ...base.values };
  for (const [k, v] of Object.entries(base.values)) {
    const o = other.values[k];
    if (timed(v) && timed(o) && o.at > v.at) values[k] = { ...v, at: o.at };
  }
  return { ...base, at: maxAt(base.at, other.at), values };
}

/** The held snapshot after one delivery (Contract 5). */
function merge(held: HeldFreshness | undefined, d: Freshness, receivedAt: number): HeldFreshness {
  const delivered: HeldFreshness = { ...d, receivedAt };
  if (!held || d.boot > held.boot) return delivered;
  if (d.boot < held.boot) return held;
  return d.seq >= held.seq ? withMaxAts(delivered, held) : withMaxAts(held, d);
}

const same = (a: HeldFreshness | undefined, b: HeldFreshness) => !!a && JSON.stringify(a) === JSON.stringify(b);

function apply(state: CreatorFreshnessState, deliveries: readonly Freshness[], receivedAt: number): CreatorFreshnessState {
  let next: Record<string, HeldFreshness> | null = null;
  for (const d of deliveries) {
    const held = (next ?? state)[d.account_id];
    const merged = merge(held, d, receivedAt);
    if (merged === held || same(held, merged)) continue;
    next ??= { ...state };
    next[d.account_id] = merged;
  }
  return next ?? state;
}

/** Each held Creator's `at` raised to the ping's where later (Contract 7). */
function confirm(state: CreatorFreshnessState, fresh: unknown, now: number, receivedAt: number): CreatorFreshnessState {
  if (!fresh || typeof fresh !== "object" || Array.isArray(fresh)) return state;
  let next: Record<string, HeldFreshness> | null = null;
  for (const [aid, at] of Object.entries(fresh)) {
    const held = (next ?? state)[aid];
    if (!held || !isNum(at) || (held.at !== null && at <= held.at)) continue;
    next ??= { ...state };
    next[aid] = isNum(now) ? { ...held, at, now, receivedAt } : { ...held, at };
  }
  return next ?? state;
}

/** `state` without the Creators an accounts answer no longer carries `freshness` for (Contract 6). */
function evict(state: CreatorFreshnessState, carried: ReadonlySet<string>): CreatorFreshnessState {
  const gone = Object.keys(state).filter((aid) => !carried.has(aid));
  if (gone.length === 0) return state;
  const next: Record<string, HeldFreshness> = { ...state };
  for (const aid of gone) delete next[aid];
  return next;
}

export function creatorFreshnessReducer(state: CreatorFreshnessState, action: Action): CreatorFreshnessState {
  switch (action.type) {
    case "seeded": {
      const ds: Freshness[] = [];
      for (const r of action.rows) {
        const f = parse(r.freshness);
        if (f) ds.push({ ...f, account_id: r.id });
      }
      return apply(evict(state, new Set(ds.map((d) => d.account_id))), ds, action.receivedAt);
    }
    case "identityChanged":
      return Object.keys(state).length === 0 ? state : EMPTY_FRESHNESS;
    case "refreshed": {
      const f = parse(action.body);
      return f ? apply(state, [f], action.receivedAt) : state;
    }
    case "confirmed":
      return confirm(state, action.fresh, action.now, action.receivedAt);
  }
}

/** The Creator's held snapshot, or null (none held: the Knob is off, or nothing came yet). */
export function of(state: CreatorFreshnessState | undefined, accountId: string): HeldFreshness | null {
  return state?.[accountId] ?? null;
}
