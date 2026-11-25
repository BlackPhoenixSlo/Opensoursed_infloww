"use client";

/**
 * useFullAiConfig — Full AI Chat's config requests around the Test chat reducer's config part (`fullAiTestChat.ts`):
 *
 *   GET  /admin/full-ai/config?account_id=   the query on `fullAiConfigKey`: its first answer and Reload → `loaded`;
 *                                            a later answer (Do mode's Apply invalidates the key) → `externalDraft`,
 *                                            which the reducer adopts if newer, or raises Keep mine / Take theirs
 *   PUT  /admin/full-ai/config/draft {account_id, draft, rev}   a control or the JSON editor: `editDraft`, `saveDraft`,
 *                                            then `draftSaved` with the stored draft and rev
 *   POST /admin/full-ai/config/save | rollback {account_id, rev}   `commit`, then `saved` / `rolledBack`
 *   PUT  /admin/full-ai/config/checkpoint {account_id, checkpoint, rev}   the checkpoint JSON: `commit`, then `loaded`
 *                                            with the answer (a draft edit unstored is dropped, as on Reload)
 *   PUT  /admin/full-ai/config/audience {account_id, fans?, top_spend_cents?}   `putAudience` (the Fans dialog, the Top
 *                                            spend box): no rev, every side at once; `audienceSave`, then
 *                                            `audienceSaved` / `audienceSaveFailed` (draft writes wait meanwhile)
 *
 * Every write answers the GET shape. A field error is 422 `{errors: ["<key or page label>: <why>"]}` → `configFailed`; a stale rev is
 * 409 `{detail, rev}` → `stale` (the page asks for a reload instead of overwriting); a 409 without `rev` → `configFailed`
 * with its detail (`writeFailed`). All read through `RelayError.body`. Reload (a fresh
 * GET → `loaded`) is also the way back from a refused edit or a failed read: it drops the unstored edit. Keep mine PUTs
 * the page's draft on the applied rev (`keepMineSave`); Take theirs only dispatches.
 * Called inside `useFullAiTestChat`, which owns the reducer.
 */

import { useQuery } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, type Dispatch } from "react";

import type { ConfigBody, FullAiConfig } from "@/components/automations/fullAiConfig";
import {
  audienceFailed, canEdit, canRollback, canSave, keepMineSave, writeFailed, type AudiencePatch, type AudienceResult,
  type TestChatAction, type TestChatState,
} from "@/components/automations/fullAiTestChat";
import { errText } from "@/lib/errText";
import { relay } from "@/lib/relay";

export const fullAiConfigKey = (accountId: string) => ["full-ai-config", accountId] as const;

export function useFullAiConfig(accountId: string, state: TestChatState, dispatch: Dispatch<TestChatAction>) {
  const ref = useRef(state);
  useEffect(() => { ref.current = state; }, [state]);

  const q = useQuery({
    queryKey: fullAiConfigKey(accountId),
    queryFn: () => relay.get<ConfigBody>(`/admin/full-ai/config?account_id=${encodeURIComponent(accountId)}`, { accountId }),
    staleTime: 0, gcTime: 0, retry: false, refetchOnWindowFocus: false,
  });
  const { data, error, refetch } = q;
  const seen = useRef<ConfigBody | null>(null);
  const reloading = useRef(false);
  useEffect(() => {
    if (!data || data === seen.current) return;
    const first = seen.current === null;
    seen.current = data;
    if (reloading.current) return;
    dispatch(first ? { type: "loaded", body: data } : { type: "externalDraft", body: data });
  }, [data, dispatch]);
  useEffect(() => {
    if (error) dispatch({ type: "configFailed", errors: [`Couldn't read the Full AI config: ${errText(error, "Request failed")}`] });
  }, [error, dispatch]);

  const reload = useCallback(async () => {
    reloading.current = true;
    try {
      const r = await refetch();
      if (r.data && !r.error) {
        seen.current = r.data;
        dispatch({ type: "loaded", body: r.data });
      }
    } finally {
      reloading.current = false;
    }
  }, [refetch, dispatch]);

  const store = useCallback(async (draft: FullAiConfig, rev: number): Promise<boolean> => {
    try {
      const body = await relay.put<ConfigBody>("/admin/full-ai/config/draft", { account_id: accountId, draft, rev }, { accountId });
      dispatch({ type: "draftSaved", rev: body.rev, draft: body.draft });
      return true;
    } catch (e) {
      dispatch(writeFailed(e));
      return false;
    }
  }, [accountId, dispatch]);

  const putDraft = useCallback(async (draft: FullAiConfig, rev?: number): Promise<boolean> => {
    const s = ref.current;
    if (!canEdit(s)) return false;
    dispatch({ type: "editDraft", draft });
    dispatch({ type: "saveDraft" });
    return store(draft, rev ?? s.rev);
  }, [dispatch, store]);

  const keepMine = useCallback(() => {
    const put = keepMineSave(ref.current);
    if (!put) return;
    dispatch({ type: "keepMine" });
    dispatch({ type: "saveDraft" });
    void store(put.draft, put.rev);
  }, [dispatch, store]);
  const takeTheirs = useCallback(() => dispatch({ type: "takeTheirs" }), [dispatch]);

  const edit = useCallback((patch: Partial<FullAiConfig>) => {
    const d = ref.current.draft;
    if (d) void putDraft({ ...d, ...patch });
  }, [putDraft]);

  const commit = useCallback(async (step: "save" | "rollback") => {
    const s = ref.current;
    if (!(step === "save" ? canSave(s) : canRollback(s))) return;
    dispatch({ type: "commit" });
    try {
      const body = await relay.post<ConfigBody>(`/admin/full-ai/config/${step}`, { account_id: accountId, rev: s.rev }, { accountId });
      dispatch({ type: step === "save" ? "saved" : "rolledBack", rev: body.rev });
    } catch (e) {
      dispatch(writeFailed(e));
    }
  }, [accountId, dispatch]);

  const putCheckpoint = useCallback(async (checkpoint: FullAiConfig, rev?: number): Promise<boolean> => {
    const s = ref.current;
    if (!canEdit(s)) return false;
    dispatch({ type: "commit" });
    try {
      const body = await relay.put<ConfigBody>("/admin/full-ai/config/checkpoint",
        { account_id: accountId, checkpoint, rev: rev ?? s.rev }, { accountId });
      dispatch({ type: "loaded", body });
      return true;
    } catch (e) {
      dispatch(writeFailed(e));
      return false;
    }
  }, [accountId, dispatch]);

  /** Who live answers (the Fans dialog, the Top spend box): `PUT config/audience` with only those keys, no rev, applied
   *  at once on every side (never a draft edit; the controls' `off` wait does not apply). The answer moves only those
   *  keys and the rev (`audienceSaved`); a failure is returned for the control to show, never a page error. */
  const putAudience = useCallback(async (patch: AudiencePatch): Promise<AudienceResult> => {
    dispatch({ type: "audienceSave" });
    try {
      const body = await relay.put<ConfigBody>("/admin/full-ai/config/audience", { account_id: accountId, ...patch }, { accountId });
      dispatch({ type: "audienceSaved", body });
      return { kind: "ok" };
    } catch (e) {
      dispatch({ type: "audienceSaveFailed" });
      return audienceFailed(e);
    }
  }, [accountId, dispatch]);

  const save = useCallback(() => void commit("save"), [commit]);
  const rollback = useCallback(() => void commit("rollback"), [commit]);
  const writerModels = data?.writer_models ?? [];
  const writerProviders = data?.writer_providers;
  const providerLabels = data?.provider_labels;
  const ownerKeys = data?.owner_keys;
  const reference = data?.reference ?? [];
  const limits = data?.limits ?? null;
  return { edit, putDraft, putCheckpoint, putAudience, save, rollback, reload, keepMine, takeTheirs, writerModels, writerProviders, providerLabels, ownerKeys, reference, limits };
}

export type FullAiConfigApi = ReturnType<typeof useFullAiConfig>;
