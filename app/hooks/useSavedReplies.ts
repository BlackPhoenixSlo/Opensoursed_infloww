"use client";


import { type QueryClient, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  relay, RelayError, type FillApplyResult, type FillPlan, type FillUndoEntry, type FillUndoResult, type SavedReply,
  type SavedReplySequenceMeta,
} from "@/lib/relay";

const KEY = "saved-replies";

interface ListResp {
  list: SavedReply[];
}

export function useSavedReplySequences(accountId: string | null) {
  return useQuery<SavedReplySequenceMeta[]>({
    queryKey: [KEY, accountId, "sequences"],
    enabled: !!accountId,
    queryFn: async () =>
      (await relay.get<{ list: SavedReplySequenceMeta[] }>(
        `/admin/saved-replies/sequences?account_id=${encodeURIComponent(accountId!)}`,
      )).list ?? [],
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
  });
}

export function useDeleteSavedReplies(accountId: string | null) {
  const qc = useQueryClient();
  return useMutation<{ deleted: number }, Error, number[]>({
    mutationFn: (ids) =>
      relay.post<{ deleted: number }>(
        `/admin/saved-replies/delete?account_id=${encodeURIComponent(accountId ?? "")}`,
        { ids },
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: [KEY, accountId] }),
  });
}

export function markScriptSent(id: number): Promise<unknown> {
  return relay.post("/admin/saved-replies/sent", { id }).catch(() => undefined);
}

export function savedRepliesQuery(accountId: string | null) {
  return {
    queryKey: [KEY, accountId],
    queryFn: async () => {
      const resp = await relay.get<ListResp>(
        `/admin/saved-replies?account_id=${encodeURIComponent(accountId ?? "")}`,
      );
      return resp.list ?? [];
    },
    staleTime: 5 * 60 * 1000,
  };
}

export function useSavedReplies(accountId: string | null) {
  return useQuery<SavedReply[]>({
    ...savedRepliesQuery(accountId),
    enabled: !!accountId,
    refetchOnWindowFocus: false,
  });
}

export interface SavedReplyDraft {
  title?: string | null;
  text: string;
  price?: number;
  lockedText?: boolean;
  media?: SavedReply["media"];
  taggedUsers?: number[];
  previews?: number[];
  gifId?: string | null;
  gifUrl?: string | null;
  scriptId?: string | null;
  scriptStep?: number | null;
  tags?: string[];
  notes?: string | null;
}

function toWire(d: SavedReplyDraft) {
  return {
    title: d.title ?? null,
    text: d.text,
    price: d.price ?? 0,
    locked_text: d.lockedText ?? false,
    media: d.media ?? [],
    tagged_users: d.taggedUsers ?? [],
    previews: d.previews ?? [],
    gif_id: d.gifId ?? null,
    gif_url: d.gifUrl ?? null,
    script_id: d.scriptId ?? null,
    script_step: d.scriptStep ?? null,
    tags: d.tags ?? [],
    notes: d.notes ?? "",
  };
}

export function useCreateSavedReply(accountId: string | null) {
  const qc = useQueryClient();
  return useMutation<SavedReply, Error, SavedReplyDraft>({
    mutationFn: (draft) =>
      relay.post<SavedReply>(
        `/admin/saved-replies?account_id=${encodeURIComponent(accountId ?? "")}`,
        toWire(draft),
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: [KEY, accountId] }),
  });
}

export function useUpdateSavedReply(accountId: string | null) {
  const qc = useQueryClient();
  return useMutation<SavedReply, Error, { id: number } & SavedReplyDraft>({
    mutationFn: ({ id, ...draft }) =>
      relay.put<SavedReply>(`/admin/saved-replies/${id}`, toWire(draft)),
    onSuccess: () => qc.invalidateQueries({ queryKey: [KEY, accountId] }),
  });
}

export function useDeleteSavedReply(accountId: string | null) {
  const qc = useQueryClient();
  return useMutation<unknown, Error, number>({
    mutationFn: (id) => relay.delete(`/admin/saved-replies/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: [KEY, accountId] }),
  });
}

export interface SavedReplyRelabel {
  kind: "tag" | "sequence";
  from?: string | null;
  to?: string | null;
  ids?: number[];
}

export function useRelabelSavedReplies(accountId: string | null) {
  const qc = useQueryClient();
  return useMutation<{ updated: number }, Error, SavedReplyRelabel>({
    mutationFn: (body) =>
      relay.post<{ updated: number }>(
        `/admin/saved-replies/relabel?account_id=${encodeURIComponent(accountId ?? "")}`,
        body,
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: [KEY, accountId] }),
  });
}

export interface SavedReplyImportResult {
  total: number;
  success_count: number;
  fail_count: number;
  failed: Array<{ sheet: string; row: number; name: string; reason: string }>;
}

export function useImportSavedReplies(accountId: string | null) {
  const qc = useQueryClient();
  return useMutation<SavedReplyImportResult, Error, File>({
    mutationFn: (file) =>
      relay.uploadFile<SavedReplyImportResult>(
        `/admin/saved-replies/import?account_id=${encodeURIComponent(accountId ?? "")}`,
        file,
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: [KEY, accountId] }),
  });
}

export interface SavedReplyCopy {
  fromAccountIds: string[];
  toAccountIds: string[];
  allCreators: boolean;
  ids?: number[];
}

export interface SavedReplyCopyResult {
  copied: number;
  skipped: number;
  media_dropped: number;
}

export interface ScriptsOverview {
  accounts: Array<{ id: string; nickname?: string | null }>;
  sequences: Array<{ name: string; per_account: Record<string, number> }>;
  tags: Array<{ name: string; per_account: Record<string, number> }>;
}

export function useScriptsOverview() {
  return useQuery<ScriptsOverview>({
    queryKey: [KEY, "overview"],
    queryFn: () => relay.get<ScriptsOverview>("/admin/saved-replies/overview"),
    staleTime: 60 * 1000,
    refetchOnWindowFocus: false,
  });
}

export function useCopySavedReplies() {
  const qc = useQueryClient();
  return useMutation<SavedReplyCopyResult, Error, SavedReplyCopy>({
    mutationFn: ({ fromAccountIds, toAccountIds, allCreators, ids }) =>
      relay.post<SavedReplyCopyResult>("/admin/saved-replies/copy", {
        from_account_ids: fromAccountIds,
        to_account_ids: toAccountIds,
        all_creators: allCreators,
        ids,
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: [KEY] }),
  });
}


const fillUrl = (route: "plan" | "apply" | "undo", accountId: string | null) =>
  `/admin/saved-replies/fill/${route}?account_id=${encodeURIComponent(accountId ?? "")}`;

export function fillPlanKey(accountId: string | null, sequence: string | null) {
  return [KEY, accountId, "fill-plan", sequence] as const;
}

// Never persisted: a reload's restored "Ready to fill" would be a stale verdict.
const FILL_PLAN_META = { persist: false } as const;

function seedFillPlan(qc: QueryClient, account: string, sequence: string, plan: FillPlan) {
  const queryKey = fillPlanKey(account, sequence);
  qc.getQueryCache().build(qc, { queryKey, meta: FILL_PLAN_META });
  qc.setQueryData(queryKey, plan);
}

export function useFillPlan(accountId: string | null, sequence: string | null) {
  return useQuery<FillPlan>({
    queryKey: fillPlanKey(accountId, sequence),
    enabled: !!accountId && !!sequence,
    queryFn: () => relay.post<FillPlan>(fillUrl("plan", accountId), { sequence }),
    staleTime: 0,
    refetchOnWindowFocus: false,
    meta: FILL_PLAN_META,
  });
}

export function stalePlan(err: unknown): FillPlan | null {
  if (!(err instanceof RelayError) || err.status !== 409) return null;
  const detail = (err.body as { detail?: { error?: unknown; plan?: FillPlan } } | null)?.detail;
  return detail?.error === "stale" && detail.plan ? detail.plan : null;
}

export function useFillApply() {
  const qc = useQueryClient();
  return useMutation<FillApplyResult, Error, { account: string; sequence: string }>({
    mutationFn: async ({ account, sequence }) => {
      try {
        const r = await relay.post<FillApplyResult>(fillUrl("apply", account), { sequence });
        if (r.status !== "ok" && r.plan) seedFillPlan(qc, account, sequence, r.plan);
        return r;
      } catch (e) {
        const fresh = stalePlan(e);
        if (fresh) seedFillPlan(qc, account, sequence, fresh);
        throw e;
      } finally {
        await qc.invalidateQueries({ queryKey: [KEY, account] });
      }
    },
  });
}

export function useFillUndo() {
  const qc = useQueryClient();
  return useMutation<FillUndoResult, Error, { account: string; sequence: string; undo: FillUndoEntry[] }>({
    mutationFn: async ({ account, ...body }) => {
      try {
        return await relay.post<FillUndoResult>(fillUrl("undo", account), body);
      } finally {
        await qc.invalidateQueries({ queryKey: [KEY, account] });
      }
    },
  });
}
