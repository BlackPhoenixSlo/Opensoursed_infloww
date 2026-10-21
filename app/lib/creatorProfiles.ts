"use client";

/**
 * useCreatorProfiles — what Infloww stores about a Creator that the Relay's account registry does not: the Creator
 * details (Display image, Creator name, Gender; Infloww's `addCreators` / `updateCreators`) and the account's Tag and
 * Internal notes (`updateCreator`'s `group` and `description`), plus the Creators added with Done and not yet linked
 * (Infloww's Creator rows with no account, "Pending connection").
 *
 * Stored under the `creators` key of the agency's `account` Settings blob (GET/PUT /admin/settings/account,
 * service/settings_api.py): the schema keeps keys it does not know (service/settings_schema.py), and the Account
 * Panel saves the whole blob, so the key rides along. No new Relay route. The Relay caps a blob at 64 KB, so a Display
 * image is stored as a 64px JPEG data URL (about 3 KB).
 *
 * A chatter session gets a 401 on the blob: `wired` is false and every save is refused (Not wired).
 */

import { useQuery, useQueryClient } from "@tanstack/react-query";

import { relay, RelayError } from "@/lib/relay";
import { APPLIED_SETTINGS_KEY } from "@/lib/appliedSettings";

/** useSettingsBlob's key for the tab, so the Account Panel and this hook share one cache entry. */
const KEY = ["settings-blob", "account"] as const;
interface BlobResponse { tab: string; config: Record<string, unknown> }

/** Infloww's `genderOptions` (index.9f50f370.js @12407169): Female / Male / Trans Man / Trans Woman. */
export const GENDERS = ["Female", "Male", "Trans Man", "Trans Woman"] as const;
export type Gender = (typeof GENDERS)[number];

/** The Creator details (step 1's form, Edit creator details). */
export interface CreatorDetails {
  name: string;
  gender?: Gender | "";
  /** A data: URL, 64px JPEG. */
  avatar?: string;
}

/** One linked account's stored extras. */
export interface CreatorProfile extends Partial<CreatorDetails> {
  tag?: string;
  notes?: string;
}

/** A Creator saved with Done, no account linked yet. */
export interface DraftCreator extends CreatorDetails {
  id: string;
  created_at: string;
}

export interface CreatorsBlob {
  profiles?: Record<string, CreatorProfile>;
  drafts?: DraftCreator[];
}

type AccountBlob = { creators?: CreatorsBlob } & Record<string, unknown>;

export function useCreatorProfiles() {
  const qc = useQueryClient();
  const q = useQuery<BlobResponse>({
    queryKey: KEY,
    queryFn: () => relay.get<BlobResponse>("/admin/settings/account"),
    staleTime: 60_000,
    refetchOnWindowFocus: false,
    // A chatter's 401 never becomes a 200 by asking again.
    retry: (n, err) => n < 2 && !(err instanceof RelayError && err.status < 500),
  });
  const creators = ((q.data?.config ?? {}) as AccountBlob).creators ?? {};
  const profiles = creators.profiles ?? {};
  const drafts = creators.drafts ?? [];
  const wired = !!q.data;
  // How many accounts hold each Tag (the Tag manager's "used by N"); its keys are every Tag in use.
  const tagCounts: Record<string, number> = {};
  for (const p of Object.values(profiles)) if (p.tag) tagCounts[p.tag] = (tagCounts[p.tag] ?? 0) + 1;

  /** One PUT of the whole blob with the `creators` key rebuilt from the latest cached blob (so two quick writes do
   *  not undo each other); the Relay replaces the blob, so every other key rides along. */
  const write = async (next: (c: CreatorsBlob) => CreatorsBlob) => {
    const cur = qc.getQueryData<BlobResponse>(KEY);
    if (!cur) throw new Error("not wired");
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
    /** Every Tag in use, sorted: the Tag select's and the Tag filter's options. */
    tags: Object.keys(tagCounts).sort(),
    tagCounts,
    /** Renames a Tag on every account that holds it, in one write; "" clears it (the Tag manager's Delete). The Tag
     *  manager refuses a name another Tag already has. */
    renameTag: (from: string, to: string) =>
      write((c) => ({
        ...c,
        profiles: Object.fromEntries(Object.entries(P(c)).map(([id, p]) => [id, p.tag === from ? { ...p, tag: to || undefined } : p])),
      })),
    saveProfile: (accountId: string, patch: CreatorProfile) =>
      write((c) => ({ ...c, profiles: { ...P(c), [accountId]: { ...P(c)[accountId], ...patch } } })),
    addDraft: async (d: CreatorDetails) => {
      const draft: DraftCreator = { ...d, id: `draft-${Date.now().toString(36)}`, created_at: new Date().toISOString() };
      await write((c) => ({ ...c, drafts: [...D(c), draft] }));
      return draft;
    },
    updateDraft: (id: string, d: CreatorDetails) =>
      write((c) => ({ ...c, drafts: D(c).map((x) => (x.id === id ? { ...x, ...d } : x)) })),
    removeDraft: (id: string) => write((c) => ({ ...c, drafts: D(c).filter((x) => x.id !== id) })),
    /** A linked account takes the Creator details and the account details in one write; its draft, if any, goes. */
    linkAccount: (accountId: string, profile: CreatorProfile, draftId?: string) =>
      write((c) => ({
        ...c,
        profiles: { ...P(c), [accountId]: { ...P(c)[accountId], ...profile } },
        drafts: draftId ? D(c).filter((x) => x.id !== draftId) : D(c),
      })),
    /** Drops a deleted account's extras. */
    removeProfile: (accountId: string) =>
      write((c) => {
        const rest = { ...P(c) };
        delete rest[accountId];
        return { ...c, profiles: rest };
      }),
  };
}

/** A picked image file as a 64px square JPEG data URL (center-cropped), small enough for the 64 KB blob. */
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
