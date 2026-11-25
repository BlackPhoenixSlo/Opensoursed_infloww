"use client";

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";

import { relay } from "@/lib/relay";
import { Skeleton } from "@/components/ui/Skeleton";
import { cn } from "@/lib/utils";


export interface FanList {
  id: number | string;
  name?: string;
  // OF tags lists 'custom' or 'build-in' (sic); spelling varies.
  type?: string;
  usersCount?: number;
}

export type ListsResp = { list?: FanList[]; hasMore?: boolean } | FanList[];

// Include-only: OF silently drops built-in names inside excludedLists.
export const SYSTEM_AUDIENCES: Array<{ id: string; label: string }> = [
  { id: "fans",      label: "All fans"  },
  { id: "following", label: "Following" },
];

export const DEFAULT_BROADCAST_LISTS: string[] = SYSTEM_AUDIENCES.map((a) => a.id);

const TOP_LIST_NAMES: string[] = [
  "fans",
  "following",
];

export function topRank(name: string): number {
  const i = TOP_LIST_NAMES.indexOf(name.toLowerCase());
  return i === -1 ? TOP_LIST_NAMES.length : i;
}

export const FAN_LISTS_PAGE = 50;
export const FAN_LISTS_MAX_PAGES = 40;

// Ids must be OF's /lists ids: local list keys are plain ints too and would silently name another folder.
export async function readAllFanLists(
  get: (path: string) => Promise<ListsResp>,
): Promise<FanList[]> {
  const out: FanList[] = [];
  const seen = new Set<string>();
  for (let page = 0; page < FAN_LISTS_MAX_PAGES; page++) {
    const path = page === 0
      ? `/api/of/v2/lists?limit=${FAN_LISTS_PAGE}`
      : `/api/of/v2/lists?limit=${FAN_LISTS_PAGE}&offset=${out.length}`;
    let r: ListsResp;
    try {
      r = await get(path);
    } catch (e) {
      if (page === 0) throw e;
      break;
    }
    const rows = Array.isArray(r) ? r : (r?.list ?? []);
    let added = 0;
    for (const l of rows) {
      const id = String(l.id);
      if (seen.has(id)) continue;
      seen.add(id);
      out.push(l);
      added++;
    }
    if (Array.isArray(r) || !r?.hasMore || rows.length === 0 || added === 0) break;
  }
  return out;
}

// Every reader of the shared cache key must spread this, or the first screen decides whether it holds every list.
export function fanListsQuery(accountId: string | null | undefined) {
  return {
    queryKey: ["fan-lists", accountId ?? ""],
    staleTime: 5 * 60_000,
    queryFn: () => readAllFanLists((path) => relay.get<ListsResp>(path, { accountId: accountId! })),
  };
}

export function useFanLists(accountId: string | null | undefined) {
  const listsQ = useQuery<FanList[]>({ ...fanListsQuery(accountId), enabled: !!accountId });

  const customLists = useMemo(() => {
    // OF sometimes tags built-in fans/following with a type the type-filter misses.
    const systemIds = new Set(SYSTEM_AUDIENCES.map((a) => a.id));
    const filtered = (listsQ.data ?? []).filter(
      (l) =>
        l.type !== "build-in" &&
        l.type !== "built-in" &&
        !systemIds.has(String(l.id)),
    );
    return filtered.slice().sort((a, b) => {
      const an = (a.name ?? "").toLowerCase();
      const bn = (b.name ?? "").toLowerCase();
      const ra = topRank(an);
      const rb = topRank(bn);
      if (ra !== rb) return ra - rb;
      return an.localeCompare(bn);
    });
  }, [listsQ.data]);

  return {
    customLists,
    isLoading: listsQ.isLoading,
    isFetching: listsQ.isFetching,
    data: listsQ.data,
  };
}

export function SysChip({
  state, onClick, label, disabled = false,
}: {
  state: "off" | "in";
  onClick: () => void;
  label: string;
  disabled?: boolean;
}) {
  const stateStyles = {
    off: "bg-transparent text-fg-dim border-border hover:border-accent hover:text-fg",
    in:  "bg-accent/10 text-accent border-accent/30",
  };
  const hint = state === "off" ? "OF built-in" : "included";
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title="Click to toggle: off → include → off"
      className={
        "h-6 px-2 rounded-full border text-[12px] flex items-center gap-1.5 transition-colors " +
        "disabled:opacity-40 " + stateStyles[state]
      }
    >
      <span>{label}</span>
      <span className="opacity-70">· {hint}</span>
    </button>
  );
}

export function ListColumn({
  lists, loading, selected, onToggle, emptyLabel, disabled = false,
}: {
  lists: FanList[];
  loading: boolean;
  selected: Set<string>;
  onToggle: (id: string) => void;
  emptyLabel: string;
  disabled?: boolean;
}) {
  if (loading) {
    return (
      <div className="space-y-1.5" aria-busy="true">
        {["w-32", "w-24", "w-28"].map((w) => <Skeleton key={w} className={cn("h-4", w)} />)}
      </div>
    );
  }
  if (lists.length === 0) {
    return <div className="text-[12px] text-muted">{emptyLabel}</div>;
  }
  return (
    <div className="flex flex-col gap-1 max-h-none sm:max-h-32 overflow-visible sm:overflow-y-auto pr-1">
      {lists.map((l) => {
        const id = String(l.id);
        const checked = selected.has(id);
        return (
          <label
            key={id}
            className="flex items-center gap-1.5 text-xs cursor-pointer hover:bg-bg-elev-1/40 rounded px-1 min-h-[40px] sm:min-h-auto py-2 sm:py-0.5"
          >
            <input
              type="checkbox"
              checked={checked}
              disabled={disabled}
              onChange={() => onToggle(id)}
            />
            <span className="flex-1 truncate">{l.name || `List #${id}`}</span>
            <span className="text-[12px] text-muted shrink-0">({l.usersCount ?? 0})</span>
          </label>
        );
      })}
    </div>
  );
}
