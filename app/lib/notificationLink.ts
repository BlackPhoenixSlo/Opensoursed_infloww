import type { MouseEvent } from "react";

import type { FanTab } from "@/components/chat/useFanTabs";
import { fanIdFromParam, type FanId } from "@/lib/fanId";
import { isPopoutRoute, openPopout, POPOUT_FEATURES, POPOUT_WINDOW } from "@/lib/nav";

export const FAN_TAB_PARAM = "fanTab";

export function notificationHref(
  accountId: string,
  user: { id?: FanId | null; name?: string | null; username?: string | null },
  { refresh = false }: { refresh?: boolean } = {},
): string | null {
  const acc = encodeURIComponent(accountId);
  let path: string;
  if (user.id) path = `/messages-pro/${acc}/${user.id}`;
  else if (user.username) path = `/messages-pro/${acc}/u/${encodeURIComponent(user.username)}`;
  else return null;
  const q = new URLSearchParams(refresh ? { refresh: "media" } : {});
  q.set(FAN_TAB_PARAM, user.name || user.username || `fan ${user.id}`);
  return `${path}?${q}`;
}

export function fanTabOf(href: string): FanTab | null {
  const u = new URL(href, "http://link.invalid");
  const m = /^\/messages-pro\/([^/]+)\/([^/]+)$/.exec(u.pathname);
  const name = u.searchParams.get(FAN_TAB_PARAM);
  const fanId = m ? fanIdFromParam(m[2]) : null;
  if (!m || fanId === null || name === null) return null;
  return { accountId: decodeURIComponent(m[1]), fanId, name };
}

export type FanTabOpener = (tab: FanTab, opts: { refresh: boolean }) => unknown;

export const IN_PLACE_KEY = "__inflowwOpenNotification";
type InPlace = (href: string) => boolean;
type WithInPlace = Window & { [IN_PLACE_KEY]?: InPlace };

export function setFanTabOpener(open: FanTabOpener): () => void {
  const inPlace: InPlace = (href) => {
    const tab = fanTabOf(href);
    if (tab) open(tab, { refresh: new URL(href, "http://link.invalid").searchParams.get("refresh") === "media" });
    return tab !== null;
  };
  const w = window as WithInPlace;
  w[IN_PLACE_KEY] = inPlace;
  return () => {
    if (w[IN_PLACE_KEY] === inPlace) delete w[IN_PLACE_KEY];
  };
}

function takenBy(w: Window | null, href: string): boolean {
  try {
    return (w as WithInPlace | null)?.[IN_PLACE_KEY]?.(href) === true;
  } catch {
    return false;
  }
}

export function openNotification(href: string): void {
  if (takenBy(window, href)) return;
  if (isPopoutRoute(window.location.pathname)) {
    window.location.assign(href);
    return;
  }
  const w = fanTabOf(href) ? window.open("", POPOUT_WINDOW, POPOUT_FEATURES) : null;
  if (w && takenBy(w, href)) w.focus();
  else openPopout(href);
}

export function onNotificationClick(e: MouseEvent, href: string): void {
  if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
  e.preventDefault();
  openNotification(href);
}
