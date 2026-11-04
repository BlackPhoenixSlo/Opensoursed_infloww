/**
 * pushPrefs — what a Web Push subscription asks the relay for, from the
 * toaster's settings (lib/notifSettings): the types whose toast is on, while
 * the master switch and the OS ping are on, and the per-platform switches.
 * No types = no subscription (lib/webPush unsubscribes).
 */

import { NOTIF_TYPES, type NotifSettings, type NotifTypeKey } from "@/lib/notifSettings";
import type { Platform } from "@/lib/platform";

export function pushTypes(s: NotifSettings): NotifTypeKey[] {
  return s.enabled && s.osPing ? NOTIF_TYPES.map((t) => t.key).filter((k) => s.toast[k]) : [];
}

/** `PUT /push/subscription`'s settings half (the keys are webPush's). */
export function pushBody(s: NotifSettings): { types: NotifTypeKey[]; platforms: Record<Platform, boolean> } {
  return { types: pushTypes(s), platforms: { ...s.platforms } };
}

export function pushWanted(s: NotifSettings): boolean {
  return pushTypes(s).length > 0;
}
