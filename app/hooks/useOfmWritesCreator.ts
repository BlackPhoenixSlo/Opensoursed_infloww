"use client";


import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { useUser } from "@/contexts/UserContext";
import { OFM_WRITES_KEY } from "@/lib/ofMirrorNewWrites";
import { relay } from "@/lib/relay";

const KEY = ["ofm-writes-creator"] as const;

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

export function ofmWritesStatus(v: Pick<OfmWritesCreator, "server_on" | "forced_off">): string {
  if (!v.server_on) return "Off for every creator on this server. This switch can only keep it off here.";
  return v.forced_off ? "Off for this creator." : "On for this creator.";
}
