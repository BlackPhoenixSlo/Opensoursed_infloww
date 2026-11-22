"use client";

/**
 * useOfmWritesCreator — one Creator's OF Manager new writes (OFM_NEW_WRITES_ENABLED per Creator,
 * `GET`/`PUT /admin/ofm-writes/{id}`, service/server.py). The server's env turns them on; this only forces them off
 * for one Creator, or clears that. A change re-asks every Mirror probe (`ofm-writes`, ofMirrorNewWrites).
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { useUser } from "@/contexts/UserContext";
import { OFM_WRITES_KEY } from "@/lib/ofMirrorNewWrites";
import { relay } from "@/lib/relay";

const KEY = ["ofm-writes-creator"] as const;

/** `server_on`: env on and not forced off box-wide; `forced_off`: this Creator's force-off (`changed_*`: who, when);
 *  `on`: both, what the Mirror's probe answers for it. */
export interface OfmWritesCreator {
  account_id: string;
  server_on: boolean;
  forced_off: boolean;
  on: boolean;
  changed_by: string | null;
  changed_at: string | null;
}

const path = (accountId: string) => `/admin/ofm-writes/${encodeURIComponent(accountId)}`;

export function useOfmWritesCreator(accountId: string) {
  const { user } = useUser();
  return useQuery<OfmWritesCreator>({
    queryKey: [...KEY, user?.user_id ?? "anon", accountId],
    queryFn: () => relay.get<OfmWritesCreator>(path(accountId)),
    staleTime: 0,
  });
}

/** `PUT /admin/ofm-writes/{id}` (the Creator's owner only): force off, or clear the force-off. */
export function useSetOfmWritesCreator() {
  const qc = useQueryClient();
  return useMutation<OfmWritesCreator, Error, { accountId: string; forcedOff: boolean }>({
    mutationFn: ({ accountId, forcedOff }) => relay.put<OfmWritesCreator>(path(accountId), { forced_off: forcedOff }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: KEY });
      void qc.invalidateQueries({ queryKey: [OFM_WRITES_KEY] });
    },
  });
}

/** The card's status line. */
export function ofmWritesStatus(v: Pick<OfmWritesCreator, "server_on" | "forced_off">): string {
  if (!v.server_on) return "Off for every creator on this server. This switch can only keep it off here.";
  return v.forced_off ? "Off for this creator." : "On for this creator.";
}
