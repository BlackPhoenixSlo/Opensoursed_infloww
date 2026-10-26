"use client";

/**
 * osNotify — one OS-level notification, wherever the app runs.
 *
 * Inside the desktop app the preload exposes `window.fasttShell.notify`
 * (desktop/preload.js), which shows a native notification from the main
 * process; no web `Notification` permission is involved there (it never
 * reached "granted" in packaged builds). In a browser it falls back to the web
 * `Notification`, only when the user has already allowed it; it never asks.
 *
 * `id` dedupes: the desktop shell shows one notification per id even when
 * several windows (popouts) fire it, and the web path uses it as the `tag`.
 * `href` is a same-origin path (a notification's link, lib/notificationLink);
 * a click opens it: the desktop app's main process does, and in a browser the
 * click focuses this window and calls `openNotification`.
 * `window.fasttShell` is typed in hooks/useInDesktopApp.ts.
 */

import { openNotification } from "@/lib/notificationLink";

export interface OsNotifyPayload {
  id: string;
  title: string;
  body: string;
  href?: string | null;
}

/** True when the desktop app shows notifications natively. */
export function hasShellNotify(): boolean {
  return typeof window !== "undefined" && typeof window.fasttShell?.notify === "function";
}

/** Show it. Resolves whether a notification was handed to the OS. */
export async function osNotify(n: OsNotifyPayload): Promise<boolean> {
  if (typeof window === "undefined") return false;
  const notify = window.fasttShell?.notify;
  if (typeof notify === "function") {
    try {
      return (await notify({ id: n.id, title: n.title, body: n.body, href: n.href ?? "" })) === true;
    } catch (err) {
      console.warn("[osNotify] desktop notify failed:", err);
      return false;
    }
  }
  if (typeof Notification === "undefined" || Notification.permission !== "granted") return false;
  try {
    const shown = new Notification(n.title, { body: n.body, tag: n.id });
    const href = n.href;
    if (href) {
      shown.onclick = () => {
        window.focus();
        openNotification(href);
        shown.close();
      };
    }
    return true;
  } catch (err) {
    console.warn("[osNotify] OS Notification threw:", err);
    return false;
  }
}
