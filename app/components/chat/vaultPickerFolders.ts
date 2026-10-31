/**
 * VaultPicker's folder menu, pure: the folder dropdown's items and the folder
 * a restricted chatter is forced onto. No React — slop loads it in node.
 */

import type { ChatterFolderGrant } from "@/hooks/useVaultMedia";
import type { FanId } from "@/lib/fanId";
import type { VaultList } from "@/lib/relay";

export type FolderSelectItem = { id: FanId; name: string; label: string };

// Infloww-style per-kind counts: "🖼 3 · 🎬 17". GIFs fold into the
// image bucket, audio gets its own segment; zero segments are hidden.
function countsOf(l?: VaultList): string {
  const parts: string[] = [];
  const photos = (l?.photosCount ?? 0) + (l?.gifsCount ?? 0);
  const videos = l?.videosCount ?? 0;
  const audios = l?.audiosCount ?? 0;
  if (photos) parts.push(`🖼 ${photos}`);
  if (videos) parts.push(`🎬 ${videos}`);
  if (audios) parts.push(`🎵 ${audios}`);
  return parts.join(" · ");
}

/** Folder dropdown source. Owners (and unrestricted chatters): OF's full
 *  folder list. Restricted chatters: the AUTHORITATIVE allowlist (DA-3),
 *  enriched with item counts from `lists` where present so the option still
 *  reads "Name (N)". Names come from the access endpoint, NOT vault/lists,
 *  so a folder past the paginated lists page still appears. */
export function folderSelectItems(
  restricted: boolean,
  allowed: ChatterFolderGrant[],
  lists: VaultList[],
): FolderSelectItem[] {
  if (restricted) {
    const byId = new Map(lists.map((l) => [l.id, l] as const));
    return allowed.map((f) => {
      const name = f.folder_name || byId.get(f.folder_id)?.name || `Folder ${f.folder_id}`;
      const counts = countsOf(byId.get(f.folder_id));
      return { id: f.folder_id, name, label: counts ? `${name} — ${counts}` : name };
    });
  }
  return lists.map((l) => {
    const counts = countsOf(l);
    return { id: l.id, name: l.name, label: counts ? `${l.name} — ${counts}` : l.name };
  });
}

/** Chatter Access (folders): a restricted chatter has NO "All folders" view
 *  (the backend soft-denies list_id=None to an empty payload). The first
 *  allowed folder that OF still reports as having media (`lists` is
 *  backend-filtered to the allowed set), which transparently falls through
 *  past a folder that was deleted/emptied on OF (per DA-3). */
export function firstUsableFolderId(allowed: ChatterFolderGrant[], lists: VaultList[]): FanId | null {
  if (allowed.length === 0) return null;
  const liveIds = new Set(lists.map((l) => l.id));
  const live = allowed.find((f) => liveIds.has(f.folder_id));
  // Fall back to the first allowed folder even if lists haven't loaded
  // yet (or report none with media) so we never default to the denied
  // "All" view; an empty grid is a better floor than a soft-denied one.
  return (live ?? allowed[0]).folder_id;
}

export type FolderChip = { id: FanId; name: string; source: "mru" | "global" | "default" };

/** Folder quick-chips: three-tier fallback so the row is always useful.
 *    1. Per-fan MRU (last 3 folders the chatter used on this fan).
 *       Marked with a ★ — "you used this for this fan recently".
 *    2. Account-wide most-used folders (sum across all fans). Marked
 *       with a • — "you use this folder a lot in general".
 *    3. First few vault folders OF returned, as last-ditch defaults.
 *   Capped at `cap` total. Same id never appears twice. */
export function folderChips(
  allFolders: VaultList[],
  folderMru: FanId[],
  accountCounts: Record<string, number>,
  cap: number,
): FolderChip[] {
  if (allFolders.length === 0) return [];
  const byId = new Map(allFolders.map((l) => [l.id, l]));
  const out: FolderChip[] = [];
  const seen = new Set<FanId>();
  const push = (id: FanId, source: FolderChip["source"]) => {
    if (out.length >= cap || seen.has(id)) return;
    const l = byId.get(id);
    if (!l) return; // folder deleted upstream — skip
    seen.add(id);
    out.push({ id: l.id, name: l.name, source });
  };
  // (1) Per-fan MRU.
  for (const id of folderMru) push(id, "mru");
  // (2) Account-wide most-used. Sort folderIds by count DESC.
  if (out.length < cap) {
    const ranked = Object.entries(accountCounts)
      // Keep the id a STRING: these keys are folder ids, and Number() on a
      // Fansly snowflake (>2^53) lands on a different folder.
      .map(([id, count]) => ({ id: id as FanId, count: Number(count) || 0 }))
      .filter((e) => e.id !== "" && e.count > 0)
      .sort((a, b) => b.count - a.count);
    for (const e of ranked) push(e.id, "global");
  }
  // (3) First-three default fallback when neither MRU nor counts cover it.
  if (out.length < cap) {
    for (const l of allFolders) push(l.id, "default");
  }
  return out;
}
