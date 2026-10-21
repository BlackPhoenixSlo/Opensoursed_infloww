import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { OfMirrorFrame } from "@/components/of-manager/OfMirrorFrame";
import { findNavLink } from "@/lib/nav";
import { mirrorPageOf } from "@/lib/of-mirror-route";

/** OF Manager: a static mirror of the OnlyFans creator UI, one section per sidebar item (docs/routes.md). */

type Props = { params: Promise<{ section: string; path?: string[] }> };

/** The mirrored page for a URL: its file and title, or null if the mirror has none. */
function pageOf(section: string, path?: string[]) {
  // The section root shows its index page (settings: OF's settings root is the profile page).
  const p = mirrorPageOf(section, path);
  if (!p) return null;
  const label = findNavLink(`/of-manager/${section}`)?.label ?? section;
  return { src: `/of-mirror/pages/${p.key}.html`, title: `${label}: ${p.title}` };
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { section, path } = await params;
  return { title: pageOf(section, path)?.title ?? "OF Manager" };
}

export default async function Page({ params }: Props) {
  const { section, path } = await params;
  const page = pageOf(section, path);
  if (!page) notFound();
  return <OfMirrorFrame src={page.src} title={page.title} />;
}
