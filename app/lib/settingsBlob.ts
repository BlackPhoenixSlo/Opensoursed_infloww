"use client";

/**
 * useSettingsBlob — one Blob tab's Settings blob, read and written whole
 * through `GET/PUT /admin/settings/{tab}` (service/settings_api.py, ADR-0007).
 *
 * `value` is the defaults, then the stored blob, then this session's edits. A
 * save PUTs the WHOLE `value` — the Relay replaces the blob, so keys a Panel
 * does not render survive only because they ride along here.
 *
 * The Load gate: Save stays off, and `save.onSave` sends nothing, until the
 * blob has loaded once. A save over a blob that never loaded would replace the
 * stored settings with the defaults. `loaded` is `!!data` with no `isSuccess`
 * conjunct, so a failed background refetch over a good load keeps Save on
 * (`loadGateNote` in StickySaveBar.tsx words the
 * three states). Panels render `<SaveRow {...blob.save} />`, and a Panel that
 * gates its own controls shows `<RetryLoad q={blob.query} />` beside the note.
 * `commit` sends `value` with a patch laid over it at once, behind the same
 * gate: a modal's Submit, or a Panel whose nested state is merged key by key
 * (Sales passes `onSave={() => blob.commit({ attribution })}` to its SaveRow).
 *
 * The `sales` and `time-tracking` tabs are versioned (service/settings_api.py, roadmap W6 6.4): a save takes
 * effect from `effective.value` (an ISO UTC time; null is now), sent as `?effective_from=`, and the read
 * carries the tab's `history` (SettingsVersions.tsx renders both).
 *
 * A successful save also invalidates the Applied settings read
 * (appliedSettings.ts), so whatever a stored value drives (the top bar's time
 * zone, ...) follows with no reload.
 */

import { useState } from "react";
import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";

import { relay } from "@/lib/relay";
import { loadGateNote, type SaveControl } from "@/components/settings/StickySaveBar";
import { APPLIED_SETTINGS_KEY } from "@/lib/appliedSettings";

/** The Settings tabs whose Panel saves a blob — the Relay's allow-list. */
export const BLOB_TABS = [
  "account", "preferences", "roles", "sales", "time-tracking", "shifts", "messaging", "security",
] as const;
export type BlobTab = (typeof BLOB_TABS)[number];

/** One saved version of a versioned tab, latest effective first; `effective_from` null is "since the start". */
export interface SettingsVersion {
  effective_from: string | null;
  saved_at: string;
  in_effect: boolean;
}

interface BlobResponse {
  tab: string;
  config: Record<string, unknown>;
  history?: SettingsVersion[];
}

export function useSettingsBlob<T extends object>(tab: BlobTab, defaults: T): {
  value: T;
  set: (patch: Partial<T>) => void;
  reset: () => void;
  /** Clears the last save's outcome (its error or "saved"), as a dialog's Cancel does. */
  resetSave: () => void;
  loaded: boolean;
  save: SaveControl;
  commit: (patch: Partial<T>, onSaved?: () => void) => void;
  query: UseQueryResult<BlobResponse>;
  /** A versioned tab's next save takes effect from `value` (ISO UTC), now when null. */
  effective: { value: string | null; set: (at: string | null) => void };
  history: SettingsVersion[];
} {
  const qc = useQueryClient();
  const queryKey = ["settings-blob", tab];
  const q = useQuery<BlobResponse>({
    queryKey,
    queryFn: () => relay.get<BlobResponse>(`/admin/settings/${tab}`),
    staleTime: 60_000,
    refetchOnWindowFocus: false,
  });
  const [edits, setEdits] = useState<Partial<T>>({});
  const [effectiveFrom, setEffectiveFrom] = useState<string | null>(null);

  const loaded = !!q.data;
  const value = { ...defaults, ...(q.data?.config ?? {}), ...edits } as T;

  const saveM = useMutation<BlobResponse, Error, { config: T; at: string | null }>({
    mutationFn: ({ config, at }) => relay.put<BlobResponse>(
      `/admin/settings/${tab}${at ? `?effective_from=${encodeURIComponent(at)}` : ""}`, config),
    onSuccess: (reply) => {
      qc.setQueryData(queryKey, reply);
      void qc.invalidateQueries({ queryKey: APPLIED_SETTINGS_KEY });
      setEdits({});
      setEffectiveFrom(null);
    },
  });

  const set = (patch: Partial<T>) => {
    if (saveM.isSuccess || saveM.isError) saveM.reset();
    setEdits((e) => ({ ...e, ...patch }));
  };

  /** The one Save path, behind the Load gate: `value` with `patch` laid over it. */
  const commit = (patch: Partial<T>, onSaved?: () => void) => {
    if (!loaded) return;
    saveM.mutate({ config: { ...value, ...patch }, at: effectiveFrom }, { onSuccess: onSaved });
  };

  return {
    value,
    set,
    reset: () => {
      setEdits({});
      setEffectiveFrom(null);
    },
    resetSave: () => saveM.reset(),
    loaded,
    save: {
      onSave: () => commit({}),
      saving: saveM.isPending,
      canSave: loaded,
      saved: saveM.isSuccess,
      error: saveM.error?.message ?? null,
      gateNote: loadGateNote(q),
    },
    commit,
    query: q,
    effective: { value: effectiveFrom, set: setEffectiveFrom },
    history: q.data?.history ?? [],
  };
}
