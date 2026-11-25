import { can, type Capability, type Platform } from "@/lib/platform";

export type ChatListFilter = "unread" | "pinned" | "priority" | "who_tipped" | "unread_tips";

const FILTER_NEEDS: Partial<Record<ChatListFilter, Capability>> = {
  pinned: "pin_message", priority: "filter_priority", who_tipped: "filter_tips", unread_tips: "filter_tips",
};

export function platformHonours(platform: Platform | null, filter: ChatListFilter | null | undefined, listId: string | null | undefined): boolean {
  const need = filter ? FILTER_NEEDS[filter] : undefined;
  return (!need || can(platform, need)) && (!listId || can(platform, "filter_folders"));
}
