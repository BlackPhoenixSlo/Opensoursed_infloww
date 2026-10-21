import { OF_MIRROR_SECTIONS } from "@/lib/of-mirror-pages";

/**
 * The mirrored page an OF Manager URL shows (app/of-manager/[section]/[[...path]]): its key under of-mirror/pages
 * (`<section>/<sub, or "index" for "">`; the section root shows its index sub) and its OF title; null if the mirror has none.
 */
export function mirrorPageOf(section: string, path: readonly string[] = []): { key: string; title: string } | null {
  const s = Object.hasOwn(OF_MIRROR_SECTIONS, section) ? OF_MIRROR_SECTIONS[section] : undefined;
  if (!s) return null;
  const sub = path.join("/") || s.index;
  if (!Object.hasOwn(s.pages, sub)) return null;
  return { key: `${section}/${sub || "index"}`, title: s.pages[sub] };
}

/** Collections' Following list (its users: GET /api/of/v2/lists/following/users). */
const FOLLOWING = "/of-manager/collections/user-lists/list?list=following";
/** Settings' promotion campaign and subscription bundle dialogs. */
const PROMOTION = "/of-manager/settings/subscription/promotion-campaign/modal-1";
const BUNDLE = "/of-manager/settings/subscription/promotion-campaign/modal-2";

/**
 * OF Manager URLs that show another page: Following's Users page and its All, Active, Expired and Attention required
 * chips (the sidebar's Following count links Active) open Collections' Following list, and Following's New message pages
 * New message's own. The Relay reads that list's users;
 * it has no read of OF's subscriptions to fill Following's own page or filter it by those chips.
 */
const REDIRECTS: Record<string, string> = {
  "collections/user-lists/subscriptions": FOLLOWING,
  "collections/user-lists/subscriptions/active": FOLLOWING,
  "collections/user-lists/subscriptions/expired": FOLLOWING,
  "collections/user-lists/subscriptions/attention": FOLLOWING,
  // Following's own New message and its Users and Exclude tabs (captured with no list row): New message's, Following
  // ticked (`?to=`, useOfChat) or the tab open (`?list=`).
  "messages/send/sendlist-following": "/of-manager/messages/send?to=following",
  "messages/send/list-users": "/of-manager/messages/send?list=users",
  "messages/send/list-exclude": "/of-manager/messages/send?list=exclude",
  // The promotion and bundle dialogs' dropdowns, captured open on a disabled select (OF's pointer-events: none, so their
  // options took no click): no page opens them, as each dialog's select opens OF's list itself (ofMirrorOffers).
  "settings/subscription/promotion-campaign/state-promo-dropdowns-0": PROMOTION,
  "settings/subscription/promotion-campaign/state-promo-dropdowns-1": PROMOTION,
  "settings/subscription/promotion-campaign/state-promo-dropdowns-2": PROMOTION,
  "settings/subscription/promotion-campaign/state-bundle-discount-dropdown": BUNDLE,
  "settings/subscription/promotion-campaign/state-bundle-duration-dropdown": BUNDLE,
};

/** The OF Manager URL an /of-manager/<section>/<path> URL redirects to (REDIRECTS), or null to show its own page. */
export function mirrorRedirectOf(section: string, path: readonly string[] = []): string | null {
  const key = [section, ...path].join("/");
  return Object.hasOwn(REDIRECTS, key) ? REDIRECTS[key] : null;
}

/** The mirrored page's key an /of-manager href opens (its query and hash dropped); null for any other href. */
export function mirrorPageOfHref(href: string): string | null {
  const m = /^\/of-manager\/([^/?#]+)([^?#]*)/.exec(href);
  return m ? (mirrorPageOf(m[1], m[2].split("/").filter(Boolean))?.key ?? null) : null;
}

/** A mirror document's (or frame src's) page: its key under of-mirror/pages; null for any other path (about:blank). */
export function mirrorPageOfPath(pathname: string): string | null {
  return /^\/of-mirror\/pages\/(.+)\.html$/.exec(pathname)?.[1] ?? null;
}
