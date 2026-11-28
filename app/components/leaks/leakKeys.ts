import type { QueryClient } from "@tanstack/react-query";

const root = ["leak-tracker"] as const;
const setupRoot = [...root, "setup"] as const;
const rosterRoot = [...root, "roster"] as const;
const allRoot = [...root, "all"] as const;
const stripRoot = [...root, "strip"] as const;
const watchRoot = (creatorId: string) => [...root, "watch", creatorId] as const;

export const leakKeys = {
  setupRoot,
  rosterRoot,
  setup: (scope: string | null) => [...setupRoot, scope] as const,
  roster: (scope: string | null) => [...rosterRoot, scope] as const,
  all: (scope: string | null) => [...allRoot, scope] as const,
  strip: (scope: string | null) => [...stripRoot, scope] as const,
  watch: (creatorId: string, scope: string | null) => [...watchRoot(creatorId), scope] as const,
  google: (creatorId: string, scope: string | null) => [...watchRoot(creatorId), scope, "google"] as const,
  offer: (creatorId: string, scope: string | null) => [...root, "offer", creatorId, scope] as const,
};

export function afterWatchWrite(qc: QueryClient, creatorId: string) {
  return Promise.all([setupRoot, rosterRoot, allRoot, stripRoot, watchRoot(creatorId)]
    .map((queryKey) => qc.invalidateQueries({ queryKey })));
}
