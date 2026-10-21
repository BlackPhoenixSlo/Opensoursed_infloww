"use client";

/**
 * useSavedReplies — CRUD for local-DB saved replies.
 *
 * OF's /messages/templates rejects creates for everything except the
 * welcome slot, so saved replies live in our SQLite (via relay's
 * /admin/saved-replies/* routes). The welcome message stays on OF —
 * see useTemplates for that path.
 *
 * Per-account list. UI merges these with the OF welcome at render time.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { relay, type SavedReply } from "@/lib/relay";

const KEY = "saved-replies";

interface ListResp {
  list: SavedReply[];
}

export function useSavedReplies(accountId: string | null) {
  return useQuery<SavedReply[]>({
    queryKey: [KEY, accountId],
    enabled: !!accountId,
    queryFn: async () => {
      const resp = await relay.get<ListResp>(
        `/admin/saved-replies?account_id=${encodeURIComponent(accountId!)}`,
      );
      return resp.list ?? [];
    },
    staleTime: 5 * 60 * 1000,
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
  /** Optional Giphy id stored on the template; null clears it. */
  gifId?: string | null;
  /** Cached animated preview URL so the picker chip can render without
   *  re-querying Giphy on every list refresh. */
  gifUrl?: string | null;
  /** Optional script grouping. Templates that share a `scriptId` form a
   *  sequence ordered by `scriptStep`; sending one advances a per-chat
   *  cursor so the composer can suggest the next step. */
  scriptId?: string | null;
  scriptStep?: number | null;
  /** Growth > Scripts' tags and internal notes. */
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

/** One tag or sequence edit across a Creator's scripts (`POST /admin/saved-replies/relabel`):
 *  tag from X to Y renames (to null deletes); tag to Y with `ids` adds it to those scripts; sequence from X to Y
 *  renames (409 on a clash), to null ungroups. `ids` limits any edit to those scripts. */
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

/** The Excel import's answer (`POST /admin/saved-replies/import`): each failed row with its sheet, row and reason. */
export interface SavedReplyImportResult {
  total: number;
  success_count: number;
  fail_count: number;
  failed: Array<{ sheet: string; row: number; name: string; reason: string }>;
}

/** Growth > Scripts' Import from Excel: every sheet is a tag; row 1 names the name, text and note columns. */
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

/** Share and Import from other creators (`POST /admin/saved-replies/copy`): copies scripts without their media,
 *  skipping a name the target already has. `ids` omitted copies every script of the sources. */
export interface SavedReplyCopy {
  fromAccountIds: string[];
  toAccountIds: string[];
  ids?: number[];
}

export interface SavedReplyCopyResult {
  copied: number;
  skipped: number;
  media_dropped: number;
  /** Scripts whose sequence step the target already held: copied outside any sequence. */
  sequence_dropped: number;
}

export function useCopySavedReplies() {
  const qc = useQueryClient();
  return useMutation<SavedReplyCopyResult, Error, SavedReplyCopy>({
    mutationFn: ({ fromAccountIds, toAccountIds, ids }) =>
      relay.post<SavedReplyCopyResult>("/admin/saved-replies/copy", {
        from_account_ids: fromAccountIds,
        to_account_ids: toAccountIds,
        ids,
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: [KEY] }),
  });
}
