import type { Metadata } from "next";
import { Suspense } from "react";
import { redirect } from "next/navigation";

import { TrackingLinksPage } from "@/components/growth/TrackingLinksTab";

export const metadata: Metadata = { title: "Tracking links" };

/** Its former tabs are Growth entries of their own (11-12): old `?tab=` links land there. */
const MOVED = new Map([["bio", "/growth/bio-pages"], ["redirects", "/growth/redirect-links"]]);

export default async function Page({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const tab = (await searchParams).tab;
  const to = typeof tab === "string" ? MOVED.get(tab) : undefined;
  if (to) redirect(to);
  return <Suspense fallback={null}><TrackingLinksPage /></Suspense>;
}
