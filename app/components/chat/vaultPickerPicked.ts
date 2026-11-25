import { type VaultMedia } from "@/lib/relay";

export interface Picked {
  ids: Set<number>;
  meta: Map<number, VaultMedia>;
}

export type PickedAction =
  | { type: "reset"; ids: number[] }
  | { type: "toggle"; media: VaultMedia }
  /** Shift/box select: add every one (never removes). */
  | { type: "addMany"; media: VaultMedia[] };

export const pickedInit = (ids: number[]): Picked => ({ ids: new Set(ids), meta: new Map() });

export function pickedReducer(s: Picked, a: PickedAction): Picked {
  switch (a.type) {
    case "reset":
      return pickedInit(a.ids);
    case "toggle": {
      const ids = new Set(s.ids);
      if (ids.has(a.media.id)) ids.delete(a.media.id);
      else ids.add(a.media.id);
      return { ids, meta: new Map(s.meta).set(a.media.id, a.media) };
    }
    case "addMany":
      if (a.media.length === 0) return s;
      return {
        ids: new Set([...s.ids, ...a.media.map((m) => m.id)]),
        meta: new Map([...s.meta, ...a.media.map((m) => [m.id, m] as const)]),
      };
  }
}

// `extra` (the double-clicked tile) is always in: a dblclick's two clicks toggle it twice, so picked-ness depends on parity.
export function buildPicked(s: Picked, items: VaultMedia[], extra?: VaultMedia): VaultMedia[] {
  const inList = new Map(items.map((m) => [m.id, m]));
  const ids = new Set(s.ids);
  if (extra) ids.add(extra.id);
  return [...ids].map((id) =>
    (extra?.id === id ? extra : undefined) ?? inList.get(id) ?? s.meta.get(id) ?? ({ id, type: "photo" } as VaultMedia));
}
