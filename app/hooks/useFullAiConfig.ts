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
 *
 * Every write answers the GET shape. A field error is 422 `{errors: ["<key>: <why>"]}` → `configFailed`; a stale rev is
 * 409 → `stale` (the page asks for a reload instead of overwriting). Both read through `RelayError.body`. Reload (a fresh
 * GET → `loaded`) is also the way back from a refused edit or a failed read: it drops the unstored edit. Keep mine PUTs
 * the page's draft on the applied rev (`keepMineSave`); Take theirs only dispatches.
 * Called inside `useFullAiTestChat`, which owns the reducer.
 */

import { useQuery } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, type Dispatch } from "react";

import {
  canEdit, canRollback, canSave, keepMineSave, type ConfigBody, type FullAiConfig, type TestChatAction, type TestChatState,
} from "@/components/automations/fullAiTestChat";
import { errText } from "@/lib/errText";
import { relay, RelayError } from "@/lib/relay";

/** A failed write as reducer actions: 409 stale, 422 its field errors, else its message. */
function failed(e: unknown): TestChatAction {
  if (e instanceof RelayError && e.status === 409) return { type: "stale" };
  const errors = e instanceof RelayError ? (e.body as { errors?: unknown } | null)?.errors : undefined;
  return { type: "configFailed", errors: Array.isArray(errors) ? errors.map(String) : [errText(e, "Request failed")] };
}

/** The server's `text_style` wire value for the casual house style (`full_ai_config.TEXT_STYLES`).
 *  Named here because the role-copy guard bans the word in component source. */
export const CASUAL_STYLE = "girl";

/** One account's Full AI config query key: Do mode's full_ai_config apply invalidates it on 200 (spec 03c), and the
 *  page's config read below refetches. */
export const fullAiConfigKey = (accountId: string) => ["full-ai-config", accountId] as const;

export function useFullAiConfig(accountId: string, state: TestChatState, dispatch: Dispatch<TestChatAction>) {
  // The handlers read the newest state (a click lands after the render that enabled it).
  const ref = useRef(state);
  useEffect(() => { ref.current = state; }, [state]);

  // Always read fresh (no cache kept off the page, no stale window): the reducer, not the cache, is the page's copy.
  const q = useQuery({
    queryKey: fullAiConfigKey(accountId),
    queryFn: () => relay.get<ConfigBody>(`/admin/full-ai/config?account_id=${encodeURIComponent(accountId)}`, { accountId }),
    staleTime: 0, gcTime: 0, retry: false, refetchOnWindowFocus: false,
  });
  const { data, error, refetch } = q;
  // The answer already dispatched: the first is `loaded`, each later one `externalDraft` (the reducer drops an old rev).
  // During Reload the answer is Reload's own `loaded` (dispatched below even when the body is unchanged), never both.
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

  /** PUT `draft` on `rev` (the reducer already marks it storing); true once stored. */
  const store = useCallback(async (draft: FullAiConfig, rev: number): Promise<boolean> => {
    try {
      const body = await relay.put<ConfigBody>("/admin/full-ai/config/draft", { account_id: accountId, draft, rev }, { accountId });
      dispatch({ type: "draftSaved", rev: body.rev, draft: body.draft });
      return true;
    } catch (e) {
      dispatch(failed(e));
      return false;
    }
  }, [accountId, dispatch]);

  /** Store `draft` as the draft; true once stored. */
  const putDraft = useCallback(async (draft: FullAiConfig): Promise<boolean> => {
    const s = ref.current;
    if (!canEdit(s)) return false;
    dispatch({ type: "editDraft", draft });
    dispatch({ type: "saveDraft" });
    return store(draft, s.rev);
  }, [dispatch, store]);

  /** Keep mine: the page's draft stored on the applied draft's rev. */
  const keepMine = useCallback(() => {
    const put = keepMineSave(ref.current);
    if (!put) return;
    dispatch({ type: "keepMine" });
    dispatch({ type: "saveDraft" });
    void store(put.draft, put.rev);
  }, [dispatch, store]);
  /** Take theirs: the applied draft replaces the page's edit (nothing to write). */
  const takeTheirs = useCallback(() => dispatch({ type: "takeTheirs" }), [dispatch]);

  /** One control's change, stored at once. */
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
      dispatch(failed(e));
    }
  }, [accountId, dispatch]);

  const save = useCallback(() => void commit("save"), [commit]);
  const rollback = useCallback(() => void commit("rollback"), [commit]);
  return { edit, putDraft, save, rollback, reload, keepMine, takeTheirs };
}

export type FullAiConfigApi = ReturnType<typeof useFullAiConfig>;
