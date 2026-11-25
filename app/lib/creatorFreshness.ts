export interface TimedSlot { at: number; [k: string]: unknown }

export interface FreshnessValues {
  notif_count?: number;
  unread_total?: {
    n: number | null; at: number | null; v?: number; grey?: string | null; amber?: number | null; amber_at?: number | null;
  } | null;
  [slot: string]: unknown;
}

export interface Freshness {
  account_id: string;
  boot: number;
  seq: number;
  now: number;
  at: number | null;
  cycle_s: number | null;
  live: "up" | "down" | "dead" | null;
  live_since: number | null;
  values: FreshnessValues;
}

export type HeldFreshness = Freshness & { receivedAt: number };

export type CreatorFreshnessState = Readonly<Record<string, HeldFreshness>>;

export const EMPTY_FRESHNESS: CreatorFreshnessState = {};

export interface SeedRow { id: string; freshness?: Freshness | null }

export type Action =
  | { type: "seeded"; rows: readonly SeedRow[]; receivedAt: number }
  | { type: "refreshed"; body: unknown; receivedAt: number }
  | { type: "confirmed"; fresh: Readonly<Record<string, number>>; now: number; receivedAt: number }
  | { type: "identityChanged" };

const isNum = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);

function parse(body: unknown): Freshness | null {
  if (!body || typeof body !== "object") return null;
  const b = body as Partial<Freshness>;
  if (typeof b.account_id !== "string" || !isNum(b.boot) || !isNum(b.seq) || !isNum(b.now)) return null;
  if (!b.values || typeof b.values !== "object") return null;
  return b as Freshness;
}

const maxAt = (a: number | null, b: number | null): number | null => (a === null ? b : b === null ? a : Math.max(a, b));

const timed = (v: unknown): v is TimedSlot => !!v && typeof v === "object" && isNum((v as TimedSlot).at);

function withMaxAts(base: HeldFreshness, other: Freshness): HeldFreshness {
  const values: FreshnessValues = { ...base.values };
  for (const [k, v] of Object.entries(base.values)) {
    const o = other.values[k];
    if (timed(v) && timed(o) && o.at > v.at) values[k] = { ...v, at: o.at };
  }
  return { ...base, at: maxAt(base.at, other.at), values };
}

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

export function badgeBehind(state: CreatorFreshnessState | undefined, badge: unknown): string[] {
  if (!badge || typeof badge !== "object" || Array.isArray(badge)) return [];
  return Object.entries(badge).filter(([aid, v]) => {
    const held = state?.[aid]?.values.unread_total?.v;
    return isNum(held) && isNum(v) && v !== held;
  }).map(([aid]) => aid);
}

export function of(state: CreatorFreshnessState | undefined, accountId: string): HeldFreshness | null {
  return state?.[accountId] ?? null;
}
