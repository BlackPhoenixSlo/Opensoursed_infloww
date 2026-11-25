import { NOTIF_TYPES, type NotifSettings, type NotifTypeKey } from "@/lib/notifSettings";
import type { Platform } from "@/lib/platform";

export function pushTypes(s: NotifSettings): NotifTypeKey[] {
  return s.enabled && s.osPing ? NOTIF_TYPES.map((t) => t.key).filter((k) => s.toast[k]) : [];
}

export function pushBody(s: NotifSettings): { types: NotifTypeKey[]; platforms: Record<Platform, boolean> } {
  return { types: pushTypes(s), platforms: { ...s.platforms } };
}

export function pushWanted(s: NotifSettings): boolean {
  return pushTypes(s).length > 0;
}
