import type { ChatterFolderGrant } from "@/hooks/useVaultMedia";
import type { FanId } from "@/lib/fanId";
import type { VaultList } from "@/lib/relay";

export type FolderSelectItem = { id: FanId; name: string; label: string };

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

// Restricted: the access endpoint's allowlist is authoritative; names come from it, not the paginated vault lists.
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

// A restricted chatter has no "All folders" view: the backend soft-denies list_id=None to an empty payload.
export function firstUsableFolderId(allowed: ChatterFolderGrant[], lists: VaultList[]): FanId | null {
  if (allowed.length === 0) return null;
  const liveIds = new Set(lists.map((l) => l.id));
  const live = allowed.find((f) => liveIds.has(f.folder_id));
  return (live ?? allowed[0]).folder_id;
}

export type FolderChip = { id: FanId; name: string; source: "mru" | "global" | "default" };

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
    if (!l) return;
    seen.add(id);
    out.push({ id: l.id, name: l.name, source });
  };
  for (const id of folderMru) push(id, "mru");
  if (out.length < cap) {
    const ranked = Object.entries(accountCounts)
      // Keep the id a string: Number() on a Fansly snowflake (>2^53) lands on a different folder.
      .map(([id, count]) => ({ id: id as FanId, count: Number(count) || 0 }))
      .filter((e) => e.id !== "" && e.count > 0)
      .sort((a, b) => b.count - a.count);
    for (const e of ranked) push(e.id, "global");
  }
  if (out.length < cap) {
    for (const l of allFolders) push(l.id, "default");
  }
  return out;
}
