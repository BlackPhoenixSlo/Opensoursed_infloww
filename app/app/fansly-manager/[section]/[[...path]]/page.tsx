import type { Metadata } from "next";
import { notFound, redirect } from "next/navigation";

import { FanslyManagerPage } from "@/components/fansly-manager/FanslyManagerPage";
import { FanslyMirrorFrame } from "@/components/fansly-manager/FanslyMirrorFrame";
import { fanslyRouteOf } from "@/lib/fansly-mirror-route";

type Props = {
  params: Promise<{ section: string; path?: string[] }>;
  searchParams: Promise<{ creator?: string | string[] }>;
};

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { section, path = [] } = await params;
  const route = fanslyRouteOf(section, path, null);
  return route?.kind === "mirror" ? { title: route.title } : {};
}

export default async function Page({ params, searchParams }: Props) {
  const { section, path = [] } = await params;
  const { creator } = await searchParams;
  const route = fanslyRouteOf(section, path, typeof creator === "string" ? creator : null);
  if (!route) notFound();
  if (route.kind === "redirect") redirect(route.to);
  if (route.kind === "built") return <FanslyManagerPage link={{ href: route.href, label: route.label, flag: "fansly_manager" }} />;
  return <FanslyMirrorFrame src={route.src} title={route.title} />;
}
