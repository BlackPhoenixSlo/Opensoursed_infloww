import type { Metadata } from "next";
import { Suspense } from "react";
import { redirect } from "next/navigation";

import { TrackingLinksPage } from "@/components/growth/TrackingLinksTab";

export const metadata: Metadata = { title: "Tracking links" };

const MOVED = new Map([["bio", "/growth/bio-pages"], ["redirects", "/growth/redirect-links"]]);

export default async function Page({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const tab = (await searchParams).tab;
  const to = typeof tab === "string" ? MOVED.get(tab) : undefined;
  if (to) redirect(to);
  return <Suspense fallback={null}><TrackingLinksPage /></Suspense>;
}
