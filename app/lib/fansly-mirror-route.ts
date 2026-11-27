import { FANSLY_MIRROR_SECTIONS, type FanslyMirrorSection } from "@/lib/fansly-mirror-pages";
import { FANSLY_NAV, findNavLink, isGroup, visibleLinks, type NavFilter } from "@/lib/nav";

type Table = Record<string, FanslyMirrorSection>;

export type FanslyRoute =
  | { kind: "built"; href: string; label: string }
  | { kind: "redirect"; to: string }
  | { kind: "mirror"; key: string; label: string; title: string; src: string }
  | null;

const BUILT: ReadonlySet<string> = new Set(["scheduled", "lists", "notifications", "earning-statistics"]);
const REDIRECTS: Readonly<Record<string, string>> = { "statistics/earnings": "/fansly-manager/earning-statistics" };

export function fanslyRouteOf(section: string, path: readonly string[], creator: string | null, table: Table = FANSLY_MIRROR_SECTIONS): FanslyRoute {
  const href = `/fansly-manager/${section}`;
  const label = findNavLink(href)?.label;
  if (!label) return null;
  if (path.length === 0 && BUILT.has(section)) return { kind: "built", href, label };
  const at = `${section}/${path.join("/")}`;
  if (Object.hasOwn(REDIRECTS, at)) return { kind: "redirect", to: withCreator(REDIRECTS[at], creator) };
  const s = Object.hasOwn(table, section) ? table[section] : undefined;
  if (!s) return null;
  const sub = path.join("/") || s.index;
  if (!Object.hasOwn(s.pages, sub)) return null;
  const key = `${section}/${sub || "index"}`;
  return { kind: "mirror", key, label, title: `${label}: ${s.pages[sub]}`, src: `/fansly-mirror/pages/${key}.html` };
}

export function withCreator(href: string, creator: string | null): string {
  if (!creator) return href;
  const hashAt = href.indexOf("#");
  const base = hashAt < 0 ? href : href.slice(0, hashAt);
  const hash = hashAt < 0 ? "" : href.slice(hashAt);
  const queryAt = base.indexOf("?");
  if (queryAt >= 0 && new URLSearchParams(base.slice(queryAt + 1)).has("creator")) return href;
  return `${base}${queryAt < 0 ? "?" : "&"}creator=${encodeURIComponent(creator)}${hash}`;
}

const MANAGER_LINKS = FANSLY_NAV.flatMap((n) => (isGroup(n) ? n.children : []))
  .filter((l) => l.href.startsWith("/fansly-manager/"));

export function firstFanslyPage(f: NavFilter): string | null {
  return visibleLinks(MANAGER_LINKS, f)[0]?.href ?? null;
}

export function routableFanslyPages(table: Table = FANSLY_MIRROR_SECTIONS): string[] {
  return Object.entries(table).flatMap(([section, { pages }]) =>
    Object.keys(pages).flatMap((sub) => {
      const r = fanslyRouteOf(section, sub ? sub.split("/") : [], null, table);
      return r?.kind === "mirror" && r.key === `${section}/${sub || "index"}` ? [r.key] : [];
    }),
  );
}
