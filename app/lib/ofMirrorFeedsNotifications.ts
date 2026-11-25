"use client";


import type { OFUserMini } from "@/lib/relay";
import { dayOf, dropClass, fill, handleOf, linkUser, make, nameOf, otherAvatar, setIcon, stamp, track, userHref, valid } from "@/lib/ofMirrorDom";

export interface MirrorNotification {
  type?: string;
  text?: string | null;
  replacePairs?: Record<string, string>;
  createdAt?: string;
  isRead?: boolean;
  user?: OFUserMini;
  fromUser?: OFUserMini;
}

export const NOTIFICATIONS: Record<string, string> = {
  "notifications/index": "/api/of/v2/users/notifications?limit=20",
  "notifications/subscribed": "/api/of/v2/users/notifications?limit=20&type=subscribed",
  "notifications/commented": "/api/of/v2/users/notifications?limit=20&type=commented",
  "notifications/mentioned": "/api/of/v2/users/notifications?limit=20&type=mentioned",
  "notifications/tip": "/api/of/v2/users/notifications?limit=20&type=tip",
  "notifications/purchases": "/api/of/v2/users/notifications?limit=20&type=purchases",
  "notifications/favorited": "/api/of/v2/users/notifications?limit=20&type=favorited",
  "notifications/message": "/api/of/v2/users/notifications?limit=20&type=message",
  "notifications/deactivated_media": "/api/of/v2/users/notifications?limit=20&type=deactivated_media",
  "notifications/tags": "/api/of/v2/release-forms/mentions?limit=20",
};

const TAGS = "notifications/tags";

export function relatedUserOf(params: URLSearchParams): string | null {
  const v = params.get("related_user")?.trim() ?? "";
  return /^\d+$/.test(v) ? v : null;
}

export function notificationsRoute(page: string, relatedUser: string | null): string | null {
  if (!Object.hasOwn(NOTIFICATIONS, page)) return null;
  const route = NOTIFICATIONS[page];
  return relatedUser && page !== TAGS ? `${route}&related_user=${encodeURIComponent(relatedUser)}` : route;
}

export function notificationsHref(page: string, relatedUser: string | null): string {
  const tab = page.slice("notifications/".length);
  const path = `/of-manager/notifications${tab && tab !== "index" ? `/${tab}` : ""}`;
  return relatedUser ? `${path}?related_user=${encodeURIComponent(relatedUser)}` : path;
}

export type NotificationCounts = Record<string, number | null | undefined>;
export const NOTIFICATION_COUNTS = "/api/of/v2/users/notifications/count";

const tabCount = (n: unknown, max = 9999) => {
  const v = Number(n);
  return !v || v <= 0 ? "" : v > max ? `${max}+` : `${v}`;
};

export function applyNotificationCounts(doc: Document, counts: NotificationCounts, newTags?: number | null) {
  for (const a of doc.querySelectorAll("a.b-tabs__nav__link[href^='/of-manager/notifications']")) {
    const label = a.querySelector(".b-tabs__nav__text");
    if (!label) continue;
    const type = (a.getAttribute("href") ?? "").slice("/of-manager/notifications/".length) || "all";
    const text = type === "tags" ? tabCount(newTags) : tabCount(counts[type], type === "all" ? 99 : undefined);
    const span = doc.createElement("span");
    span.className = "b-tabs__nav__count";
    span.textContent = ` ${text} `;
    fill(doc, [...label.querySelectorAll<HTMLElement>(".b-tabs__nav__count")], text ? [span] : [], [label]);
  }
}

const NOTIFICATION_ICONS: Record<string, string> = { subscribed: "icon-follow", tip: "icon-price", tipped: "icon-price" };

export function applyNotifications(doc: Document, items: MirrorNotification[], img: (u: string) => string) {
  const views = [...doc.querySelectorAll<HTMLElement>(".b-notifications__list .vue-recycle-scroller__item-view")];
  const tpl = views.find((v) => v.querySelector(".b-notifications__list__item") && !v.querySelector(".b-list-titles a"));
  if (!tpl) return;
  const clones = items.map((n, i) => {
    const el = make(tpl);
    el.style.removeProperty("display");
    const u = n.user ?? n.fromUser;
    el.querySelector("[data-index]")?.setAttribute("data-index", String(i));
    el.querySelector(".b-notifications__list__item")?.classList.toggle("m-unread", n.isRead === false);
    const name = el.querySelector(".b-username .g-user-name");
    if (name) {
      name.classList.remove("m-verified");
      name.textContent = u ? ` ${nameOf(u)} ` : "";
    }
    const handle = el.querySelector(".g-user-username");
    if (handle) handle.textContent = u ? ` @${handleOf(u)} ` : "";
    otherAvatar(el.querySelector(".b-available-users__round-img .g-avatar"), u, img);
    linkUser(el.querySelectorAll("a.g-avatar, a.b-username, a.g-user-username"), userHref(u));
    const icon = NOTIFICATION_ICONS[n.type ?? ""];
    const badge = el.querySelector(".b-notifications__avatar__icon");
    if (icon && badge) setIcon(badge, icon);
    else badge?.remove();
    const text = el.querySelector(".b-notifications__list__item__text .g-truncated-text");
    if (text) text.replaceChildren(...notificationText(doc, Object.entries(n.replacePairs ?? {}).reduce((t, [k, v]) => t.split(k).join(v), n.text ?? "")));
    const date = el.querySelector(".g-date > span");
    const at = valid(n.createdAt);
    if (date && at) {
      date.textContent = ` ${dayOf(at)} `;
      date.setAttribute("title", stamp(at));
    } else date?.remove();
    return el;
  });
  const empty = items.length ? [...doc.querySelectorAll<HTMLElement>(".b-notifications__list .empty-message")] : [];
  const tab = items.length && doc.querySelector(".b-notifications.m-empty-page");
  if (tab) dropClass(doc, tab, "m-empty-page");
  fill(doc, [...views, ...empty], clones);
}

function notificationHref(raw: string | null): { href: string; here: boolean } | null {
  let url: URL;
  try {
    url = new URL(raw ?? "", "https://onlyfans.com");
  } catch {
    return null;
  }
  if (!raw || url.protocol !== "https:" || (url.hostname !== "onlyfans.com" && url.hostname !== "www.onlyfans.com")) return null;
  const chat = /^\/my\/chats\/chat\/(\d+)/.exec(url.pathname)?.[1];
  return chat ? { href: `/of-manager/messages/chat?chat=${chat}`, here: true } : { href: url.href, here: false };
}

export function notificationText(doc: Document, html: string): Node[] {
  const out: Node[] = [];
  const walk = (n: Node) => {
    if (n.nodeType === Node.TEXT_NODE) return void out.push(doc.createTextNode(n.textContent ?? ""));
    if (n.nodeName === "SCRIPT" || n.nodeName === "STYLE") return;
    const link = n.nodeName === "A" ? notificationHref((n as Element).getAttribute("href")) : null;
    if (!link) return n.childNodes.forEach(walk);
    const a = doc.createElement("a");
    a.textContent = n.textContent;
    a.setAttribute("href", link.href);
    a.setAttribute("target", link.here ? "_top" : "_blank");
    if (!link.here) a.setAttribute("rel", "noopener noreferrer");
    out.push(a);
  };
  new DOMParser().parseFromString(html, "text/html").body.childNodes.forEach(walk);
  const [first, last] = [out[0], out[out.length - 1]];
  if (first?.nodeType === Node.TEXT_NODE) first.textContent = first.textContent!.trimStart();
  if (last?.nodeType === Node.TEXT_NODE) last.textContent = last.textContent!.trimEnd();
  return out;
}

export function applyNotificationsStatus(doc: Document, error: string | null) {
  const text = doc.querySelector<HTMLElement>(".b-notifications__list .infinite-status-prompt:not([style*='none']) > .empty-message > span");
  if (!text) return;
  const [was, style] = [text.textContent, text.getAttribute("style")];
  track(doc, () => {
    text.textContent = was;
    if (style === null) text.removeAttribute("style");
    else text.setAttribute("style", style);
  });
  text.textContent = error === null ? "Loading notifications…" : `Could not load notifications: ${error}`;
  if (error !== null) text.style.color = "#ff4545";
}
