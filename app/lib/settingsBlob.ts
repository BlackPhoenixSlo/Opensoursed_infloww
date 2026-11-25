"use client";


import { useState } from "react";
import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";

import { relay } from "@/lib/relay";
import { loadGateNote, type SaveControl } from "@/components/settings/StickySaveBar";
import { APPLIED_SETTINGS_KEY } from "@/lib/appliedSettings";

export const BLOB_TABS = [
  "account", "preferences", "roles", "sales", "time-tracking", "shifts", "messaging", "security",
] as const;
export type BlobTab = (typeof BLOB_TABS)[number];

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
  resetSave: () => void;
  loaded: boolean;
  save: SaveControl;
  commit: (patch: Partial<T>, onSaved?: () => void) => void;
  query: UseQueryResult<BlobResponse>;
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

  // Load gate: a save over a blob that never loaded would replace the stored settings with defaults.
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
