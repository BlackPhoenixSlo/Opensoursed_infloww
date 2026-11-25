"use client";


import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import { relay, type RelayContext } from "@/lib/relay";

const KEY = "funnels";
const BG_CTX: RelayContext = { priority: "background" };


export interface StepNext {
  bought?: number;
  ignored?: number;
  keyword?: Record<string, number>;
  default?: number;
}

export interface ReplyStep {
  step: number;
  type?: undefined;
  check_intervals_min?: number[];
  messages?: string[];
  prompt?: string;
  generate?: boolean;
  next?: StepNext;
}

// Media is per-account (vault ids differ per model, see useFunnelMedia); media_files/previews only read legacy funnels.
export interface PpvStep {
  step: number;
  type: "paid_ppv";
  price?: number;
  media_files?: Array<number | string>;
  previews?: Array<number | string>;
  messages?: string[];
  prompt?: string;
  generate?: boolean;
  locked_text?: boolean;
  check_intervals_min?: number[];
  next?: StepNext;
}

export type FunnelStep = ReplyStep | PpvStep;

export interface FunnelSummary {
  id: number;
  name: string;
  description: string | null;
  opening_message: string;
  step_count: number;
  stats?: FunnelStats;
}

export interface FunnelStats {
  last_started_at: string | null;
  active_fans: number;
  listening: boolean;
}

export interface FunnelFull extends FunnelSummary {
  steps: FunnelStep[];
  vault_folder: string | null;
  media_indices: unknown;
  opening_vault_folder: string | null;
  opening_media_indices: unknown;
}


export interface FunnelCreate {
  name: string;
  opening_message: string;
  description?: string | null;
  steps?: FunnelStep[];
}

export interface FunnelUpdate {
  name?: string;
  opening_message?: string;
  description?: string | null;
  steps?: FunnelStep[];
}


export function useFunnels(accountId?: string | null) {
  return useQuery<FunnelSummary[]>({
    queryKey: [KEY, "list", accountId ?? null],
    queryFn: async () => {
      const q = accountId ? `?account_id=${encodeURIComponent(accountId)}` : "";
      const r = await relay.get<{ funnels: FunnelSummary[] }>(`/admin/funnels${q}`, BG_CTX);
      return r.funnels ?? [];
    },
    staleTime: 60_000,
    refetchOnWindowFocus: true,
    placeholderData: keepPreviousData,
  });
}

export function useFunnel(id: number | null) {
  return useQuery<FunnelFull>({
    queryKey: [KEY, id],
    enabled: id != null,
    queryFn: () => relay.get<FunnelFull>(`/admin/funnels/${id}`, BG_CTX),
    staleTime: 60_000,
    refetchOnWindowFocus: false,
  });
}


export function useCreateFunnel() {
  const qc = useQueryClient();
  return useMutation<FunnelFull, Error, FunnelCreate>({
    mutationFn: (body) => relay.post<FunnelFull>("/admin/funnels", body),
    onSuccess: () => qc.invalidateQueries({ queryKey: [KEY] }),
  });
}

export function useUpdateFunnel() {
  const qc = useQueryClient();
  return useMutation<FunnelFull, Error, { id: number } & FunnelUpdate>({
    mutationFn: ({ id, ...patch }) => relay.put<FunnelFull>(`/admin/funnels/${id}`, patch),
    onSuccess: (_d, { id }) => {
      qc.invalidateQueries({ queryKey: [KEY] });
      qc.invalidateQueries({ queryKey: [KEY, id] });
    },
  });
}

export function useDeleteFunnel() {
  const qc = useQueryClient();
  return useMutation<unknown, Error, number>({
    mutationFn: (id) => relay.delete(`/admin/funnels/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: [KEY] }),
  });
}


const MEDIA_KEY = "funnel-media";

export interface FunnelStepMedia {
  media_files: number[];
  previews: number[];
}

export interface FunnelAccountMedia {
  funnel_id: number;
  account_id: string;
  opening_media_ids: number[];
  steps_media: Record<string, FunnelStepMedia>;
}

export interface FunnelMediaSave {
  opening_media_ids?: number[];
  steps_media?: Record<string, FunnelStepMedia>;
}

export function useFunnelMedia(funnelId: number | null, accountId: string | null) {
  return useQuery<FunnelAccountMedia>({
    queryKey: [MEDIA_KEY, funnelId, accountId],
    enabled: funnelId != null && !!accountId,
    queryFn: () =>
      relay.get<FunnelAccountMedia>(
        `/admin/funnels/${funnelId}/media/${accountId}`,
        BG_CTX,
      ),
    staleTime: 30_000,
    refetchOnWindowFocus: false,
  });
}

export function useSaveFunnelMedia() {
  const qc = useQueryClient();
  return useMutation<
    FunnelAccountMedia,
    Error,
    { funnelId: number; accountId: string } & FunnelMediaSave
  >({
    mutationFn: ({ funnelId, accountId, ...body }) =>
      relay.put<FunnelAccountMedia>(
        `/admin/funnels/${funnelId}/media/${accountId}`,
        body,
      ),
    onSuccess: (_d, { funnelId, accountId }) =>
      qc.invalidateQueries({ queryKey: [MEDIA_KEY, funnelId, accountId] }),
  });
}
