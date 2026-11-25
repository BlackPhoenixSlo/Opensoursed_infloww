"use client";


import { useQuery, useQueryClient } from "@tanstack/react-query";

import { relay, RelayError } from "@/lib/relay";
import { APPLIED_SETTINGS_KEY } from "@/lib/appliedSettings";

const KEY = ["settings-blob", "account"] as const;
interface BlobResponse { tab: string; config: Record<string, unknown> }

export const GENDERS = ["Female", "Male", "Trans Man", "Trans Woman"] as const;
export type Gender = (typeof GENDERS)[number];

export interface CreatorDetails {
  name: string;
  gender?: Gender | "";
  avatar?: string;
}

export interface CreatorProfile extends Partial<CreatorDetails> {
  tag?: string;
  notes?: string;
}

export interface DraftCreator extends CreatorDetails {
  id: string;
  created_at: string;
}

export interface CreatorsBlob {
  profiles?: Record<string, CreatorProfile>;
  drafts?: DraftCreator[];
}

type AccountBlob = { creators?: CreatorsBlob } & Record<string, unknown>;

export const SETTINGS_NOT_LOADED = "Settings not loaded — try again.";

export function useCreatorProfiles() {
  const qc = useQueryClient();
  const q = useQuery<BlobResponse>({
    queryKey: KEY,
    queryFn: () => relay.get<BlobResponse>("/admin/settings/account"),
    staleTime: 60_000,
    refetchOnWindowFocus: false,
    retry: (n, err) => n < 2 && !(err instanceof RelayError && err.status < 500),
  });
  const creators = ((q.data?.config ?? {}) as AccountBlob).creators ?? {};
  const profiles = creators.profiles ?? {};
  const drafts = creators.drafts ?? [];
  const wired = !!q.data;
  const tagCounts: Record<string, number> = {};
  for (const p of Object.values(profiles)) if (p.tag) tagCounts[p.tag] = (tagCounts[p.tag] ?? 0) + 1;

  const write = async (next: (c: CreatorsBlob) => CreatorsBlob) => {
    const cur = qc.getQueryData<BlobResponse>(KEY);
    // A chatter's 401 on the blob never becomes a 200; refuse instead of replacing a blob that never loaded.
    if (!cur) throw new Error(SETTINGS_NOT_LOADED);
    const config = cur.config as AccountBlob;
    const reply = await relay.put<BlobResponse>("/admin/settings/account", { ...config, creators: next(config.creators ?? {}) });
    qc.setQueryData(KEY, reply);
    void qc.invalidateQueries({ queryKey: APPLIED_SETTINGS_KEY });
  };
  const P = (c: CreatorsBlob) => c.profiles ?? {};
  const D = (c: CreatorsBlob) => c.drafts ?? [];

  return {
    wired,
    profiles,
    drafts,
    tags: Object.keys(tagCounts).sort(),
    tagCounts,
    renameTag: (from: string, to: string) =>
      write((c) => ({
        ...c,
        profiles: Object.fromEntries(Object.entries(P(c)).map(([id, p]) => [id, p.tag === from ? { ...p, tag: to || undefined } : p])),
      })),
    saveProfile: (accountId: string, patch: CreatorProfile) =>
      write((c) => ({ ...c, profiles: { ...P(c), [accountId]: { ...P(c)[accountId], ...patch } } })),
    updateDraft: (id: string, d: CreatorDetails) =>
      write((c) => ({ ...c, drafts: D(c).map((x) => (x.id === id ? { ...x, ...d } : x)) })),
    removeDraft: (id: string) => write((c) => ({ ...c, drafts: D(c).filter((x) => x.id !== id) })),
    linkAccount: (accountId: string, profile: CreatorProfile, draftId?: string) =>
      write((c) => ({
        ...c,
        profiles: { ...P(c), [accountId]: { ...P(c)[accountId], ...profile } },
        drafts: draftId ? D(c).filter((x) => x.id !== draftId) : D(c),
      })),
    removeProfile: (accountId: string) =>
      write((c) => {
        const rest = { ...P(c) };
        delete rest[accountId];
        return { ...c, profiles: rest };
      }),
  };
}

// 64px JPEG data URL: the Relay caps the settings blob at 64 KB.
export function avatarDataUrl(file: File, size = 64): Promise<string> {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => {
      const c = document.createElement("canvas");
      c.width = size; c.height = size;
      const s = Math.min(img.width, img.height);
      c.getContext("2d")?.drawImage(img, (img.width - s) / 2, (img.height - s) / 2, s, s, 0, 0, size, size);
      URL.revokeObjectURL(url);
      resolve(c.toDataURL("image/jpeg", 0.8));
    };
    img.onerror = () => { URL.revokeObjectURL(url); reject(new Error("not an image")); };
    img.src = url;
  });
}
