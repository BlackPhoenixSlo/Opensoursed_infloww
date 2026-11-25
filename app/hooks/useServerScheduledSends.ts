"use client";


import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ssePoll } from "@/lib/events";
import { relay, type OFMessage } from "@/lib/relay";
import { type FanId } from "@/lib/fanId";

const KEY = "scheduled-sends";

export interface ServerScheduledSend {
  job_id: number;
  kind?: "scheduled_send";
  fan_id: FanId;
  run_at: string;
  status: string;
  text: string;
  price?: number;
  locked_text?: boolean;
  media_count?: number;
  giphy_id?: string | null;
}

interface ListResp {
  list?: ServerScheduledSend[];
}

export function scheduledSendsKey(accountId: string, fanId: FanId) {
  return [KEY, accountId, fanId] as const;
}

export function useServerScheduledSends(accountId: string | null, fanId: FanId | null) {
  return useQuery<ServerScheduledSend[]>({
    queryKey: scheduledSendsKey(accountId ?? "", fanId ?? 0),
    queryFn: async () => {
      const resp = await relay.get<ListResp>(
        `/api/of/v2/scheduled-sends?fan_id=${fanId}`,
        { accountId },
      );
      return (resp.list ?? []).sort(
        (a, b) => new Date(a.run_at).getTime() - new Date(b.run_at).getTime(),
      );
    },
    enabled: !!accountId && fanId != null,
    staleTime: 8_000,
    refetchInterval: ssePoll(5 * 60_000, 12_000),
    refetchOnWindowFocus: true,
  });
}

export function useCancelServerScheduled() {
  const qc = useQueryClient();
  return useMutation<unknown, Error, { jobId: number; accountId: string; fanId: FanId }>({
    mutationFn: ({ jobId, accountId }) =>
      relay.delete(`/api/of/v2/scheduled-sends/${jobId}`, { accountId }),
    onMutate: ({ jobId, accountId, fanId }) => {
      qc.setQueryData<ServerScheduledSend[]>(
        scheduledSendsKey(accountId, fanId),
        (prev) => (prev ?? []).filter((s) => s.job_id !== jobId),
      );
    },
    onSettled: (_d, _e, { accountId, fanId }) =>
      qc.invalidateQueries({ queryKey: scheduledSendsKey(accountId, fanId) }),
  });
}

export function scheduledToPseudoMessage(
  s: ServerScheduledSend,
  ownerUserId: number | null,
): OFMessage {
  return {
    id: `sched-${s.job_id}`,
    _scheduleJobId: s.job_id,
    _isFutureScheduled: true,
    _fireAt: s.run_at,
    _pending: true,
    text: s.text,
    createdAt: s.run_at,
    fromUser: { id: ownerUserId ?? -1, name: "you" },
    media: [],
    mediaCount: s.media_count ?? 0,
    price: s.price ?? 0,
    lockedText: s.locked_text,
    giphyId: s.giphy_id ?? undefined,
  } as unknown as OFMessage;
}
