import type { Metadata } from "next";
import { Suspense } from "react";

import { TrackingLinksPage } from "@/components/growth/TrackingLinksTab";

export const metadata: Metadata = { title: "Tracking links" };

export default function Page() {
  return <Suspense fallback={null}><TrackingLinksPage /></Suspense>;
}
