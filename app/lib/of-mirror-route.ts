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

/** The mirrored page's key an /of-manager href opens (its query and hash dropped); null for any other href. */
export function mirrorPageOfHref(href: string): string | null {
  const m = /^\/of-manager\/([^/?#]+)([^?#]*)/.exec(href);
  return m ? (mirrorPageOf(m[1], m[2].split("/").filter(Boolean))?.key ?? null) : null;
}

/** A mirror document's (or frame src's) page: its key under of-mirror/pages; null for any other path (about:blank). */
export function mirrorPageOfPath(pathname: string): string | null {
  return /^\/of-mirror\/pages\/(.+)\.html$/.exec(pathname)?.[1] ?? null;
}
