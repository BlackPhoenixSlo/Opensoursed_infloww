"use client";


import { openNotification } from "@/lib/notificationLink";

export interface OsNotifyPayload {
  id: string;
  title: string;
  body: string;
  href?: string | null;
}

export function hasShellNotify(): boolean {
  return typeof window !== "undefined" && typeof window.fasttShell?.notify === "function";
}

export async function osNotify(n: OsNotifyPayload): Promise<boolean> {
  if (typeof window === "undefined") return false;
  // Desktop uses the native notification: web Notification permission never reached "granted" in packaged builds.
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
