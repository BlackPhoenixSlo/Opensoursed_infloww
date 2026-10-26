/**
 * notificationLink — a notification's "open": its Fan in a Fan tab of Messages
 * Pro (docs/spec/phase-01-window-chrome-tabs.md, story 38: "Only 'Open in new
 * tab' and a notification's 'open' create a Fan tab"). Every notification
 * click comes here: the toast, the top bar bell's row, the /notifications row,
 * the Buys & tips rail and the OS notification (browser and desktop app).
 *
 * - `notificationHref` is the link: the Fan's Deep link, plus `?refresh=media`
 *   for money (the Fan just paid, so a fresh window's persisted caches are
 *   stale by seconds) and `?fanTab=<name>`. A Fan known only by username
 *   links to `/u/<username>`, which resolves the id and keeps the query.
 * - A mounted Messages Pro registers the Notifications panel's opener
 *   (`setFanTabOpener`) as a page global (`IN_PLACE_KEY`): the tab is added
 *   (or reused) and opened in place, with no reload and no new window, for a
 *   click in that window, in another one (through its handle on the Messages
 *   Pro window, focused) and from the desktop app's main process.
 * - With no Messages Pro up to take it, the link opens the Messages Pro
 *   window (`openPopout`), whose page reads `fanTab` on arrival, adds the tab
 *   the same way and drops the param. The desktop app's native notification
 *   and a link it is asked to open as a tab land there too
 *   (desktop/lib/window-open.js).
 * - Modified clicks (cmd/ctrl/shift/alt, non-left buttons) keep the browser's
 *   own link behaviour: a new tab on the same link, which adds the tab there.
 */

import type { MouseEvent } from "react";

import type { FanTab } from "@/components/chat/useFanTabs";
import { fanIdFromParam, type FanId } from "@/lib/fanId";
import { isPopoutRoute, openPopout, POPOUT_FEATURES, POPOUT_WINDOW } from "@/lib/nav";

/** The Deep link's one-shot "open as a Fan tab" param; its value is the tab's name. */
export const FAN_TAB_PARAM = "fanTab";

/** The link for a notification about `user`, a Fan of `accountId`; null with
 *  neither an id nor a username. */
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

/** The Fan tab a notification link names, or null (a username link, or not one). */
export function fanTabOf(href: string): FanTab | null {
  const u = new URL(href, "http://link.invalid");
  const m = /^\/messages-pro\/([^/]+)\/([^/]+)$/.exec(u.pathname);
  const name = u.searchParams.get(FAN_TAB_PARAM);
  const fanId = m ? fanIdFromParam(m[2]) : null;
  if (!m || fanId === null || name === null) return null;
  return { accountId: decodeURIComponent(m[1]), fanId, name };
}

/** Opens a notification's Fan in place; `refresh`: the link's `?refresh=media`. */
export type FanTabOpener = (tab: FanTab, opts: { refresh: boolean }) => unknown;

/** The page global through which a mounted Messages Pro takes a notification's
 *  link in place: `(href) => true` when it did. This window's notifications,
 *  another window's (through its handle on the Messages Pro window) and the
 *  desktop app's main process (desktop/lib/window-open.js) all call it, so
 *  Messages Pro is never reloaded under the Employee, and a second click
 *  while the first loads cannot cancel the first. */
export const IN_PLACE_KEY = "__inflowwOpenNotification";
type InPlace = (href: string) => boolean;
type WithInPlace = Window & { [IN_PLACE_KEY]?: InPlace };

/** Messages Pro's page, while mounted with its Employee resolved:
 *  notifications open their Fan with `open`. Returns the unregister. */
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
    return false; // another origin's window
  }
}

/** Open a notification's link (`notificationHref`): in place inside Messages
 *  Pro; else in the Messages Pro window, in place when its page is up. A link
 *  Messages Pro cannot take in place (a username link: only its resolver
 *  knows the Fan id; or before its Employee resolves) loads that window. */
export function openNotification(href: string): void {
  if (takenBy(window, href)) return;
  if (isPopoutRoute(window.location.pathname)) {
    window.location.assign(href); // this window is Messages Pro: load it here, open no other
    return;
  }
  const w = fanTabOf(href) ? window.open("", POPOUT_WINDOW, POPOUT_FEATURES) : null;
  if (w && takenBy(w, href)) w.focus();
  else openPopout(href);
}

/** A left click on a notification's link: `openNotification` instead of the
 *  browser's navigation. Modified clicks keep the browser's own behaviour. */
export function onNotificationClick(e: MouseEvent, href: string): void {
  if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
  e.preventDefault();
  openNotification(href);
}
