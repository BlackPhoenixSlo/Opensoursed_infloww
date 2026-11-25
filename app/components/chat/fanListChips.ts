import { platformHonours, type ChatListFilter } from "@/lib/chatFilters";
import type { Platform } from "@/lib/platform";

import type { ActiveChip } from "./FanListFilters";

export type FanListChipSet = {
  pinned: boolean;
  who_tipped: boolean;
  unread_tips: boolean;
  priority: boolean;
};

const ALL: ActiveChip = { kind: "builtin", key: "all" };

export function fanListChips({ platforms, tipsEnabled, pinnedFolderIds, active }: {
  platforms: readonly Platform[];
  tipsEnabled: boolean;
  pinnedFolderIds: readonly string[];
  active: ActiveChip;
}): { chips: FanListChipSet; active: ActiveChip } {
  const any = (filter: ChatListFilter) => platforms.some((p) => platformHonours(p, filter, null));
  const chips: FanListChipSet = {
    pinned: any("pinned"),
    who_tipped: any("who_tipped"),
    unread_tips: any("unread_tips") && tipsEnabled,
    priority: any("priority"),
  };
  let shown: boolean;
  if (active.kind === "folder") shown = pinnedFolderIds.includes(active.listId);
  else {
    const k = active.key;
    shown = k === "pinned" || k === "who_tipped" || k === "unread_tips" || k === "priority" ? chips[k] : true;
  }
  return { chips, active: shown ? active : ALL };
}
