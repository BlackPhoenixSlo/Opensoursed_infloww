export interface Job {
  id: number;
  accountId: string | null;
  screen: boolean;
}

export interface ScheduleState {
  queue: readonly Job[];
  onWire: readonly Job[];
  perCreator: number;
  focus: string | null;
  net: { effectiveType?: string; saveData?: boolean } | null;
  reserve: boolean;
}

export type Action =
  | { type: "enqueue"; job: Job }
  | { type: "start"; ids: readonly number[] }
  | { type: "done"; id: number }
  | { type: "focus"; accountId: string | null }
  | { type: "net"; effectiveType?: string; saveData?: boolean }
  | { type: "reserve"; on: boolean };

// Mirrors the relay's _ACCOUNT_LANE_BACKGROUND default.
export const PER_CREATOR = 2;
// Measured at 250 ms RTT: a cap of 2 took the cold Dashboard 3.9 s to 17.3 s; reads wait on round trips, not bandwidth.
export const SLOW_CAP = 4;

export const initialSchedule: ScheduleState = {
  queue: [], onWire: [], perCreator: PER_CREATOR, focus: null, net: null, reserve: false,
};

export function isSlow(s: Pick<ScheduleState, "net">): boolean {
  const n = s.net;
  return !!n && (n.saveData === true || /(^|-)(2g|3g)$/.test(n.effectiveType ?? ""));
}

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
