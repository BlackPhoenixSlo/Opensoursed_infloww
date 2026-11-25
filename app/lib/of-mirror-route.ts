import { OF_MIRROR_SECTIONS } from "@/lib/of-mirror-pages";

export function mirrorPageOf(section: string, path: readonly string[] = []): { key: string; title: string } | null {
  const s = Object.hasOwn(OF_MIRROR_SECTIONS, section) ? OF_MIRROR_SECTIONS[section] : undefined;
  if (!s) return null;
  const sub = path.join("/") || s.index;
  if (!Object.hasOwn(s.pages, sub)) return null;
  return { key: `${section}/${sub || "index"}`, title: s.pages[sub] };
}

const FOLLOWING = "/of-manager/collections/user-lists/list?list=following";
const PROMOTION = "/of-manager/settings/subscription/promotion-campaign/modal-1";
const BUNDLE = "/of-manager/settings/subscription/promotion-campaign/modal-2";

const REDIRECTS: Record<string, string> = {
  "collections/user-lists/subscriptions": FOLLOWING,
  "collections/user-lists/subscriptions/active": FOLLOWING,
  "collections/user-lists/subscriptions/expired": FOLLOWING,
  "collections/user-lists/subscriptions/attention": FOLLOWING,
  "messages/send/sendlist-following": "/of-manager/messages/send?to=following",
  "messages/send/list-users": "/of-manager/messages/send?list=users",
  "messages/send/list-exclude": "/of-manager/messages/send?list=exclude",
  "settings/subscription/promotion-campaign/state-promo-dropdowns-0": PROMOTION,
  "settings/subscription/promotion-campaign/state-promo-dropdowns-1": PROMOTION,
  "settings/subscription/promotion-campaign/state-promo-dropdowns-2": PROMOTION,
  "settings/subscription/promotion-campaign/state-bundle-discount-dropdown": BUNDLE,
  "settings/subscription/promotion-campaign/state-bundle-duration-dropdown": BUNDLE,
};

export function mirrorRedirectOf(section: string, path: readonly string[] = []): string | null {
  const key = [section, ...path].join("/");
  return Object.hasOwn(REDIRECTS, key) ? REDIRECTS[key] : null;
}

export function mirrorPageOfHref(href: string): string | null {
  const m = /^\/of-manager\/([^/?#]+)([^?#]*)/.exec(href);
  return m ? (mirrorPageOf(m[1], m[2].split("/").filter(Boolean))?.key ?? null) : null;
}

export function mirrorPageOfPath(pathname: string): string | null {
  return /^\/of-mirror\/pages\/(.+)\.html$/.exec(pathname)?.[1] ?? null;
}
