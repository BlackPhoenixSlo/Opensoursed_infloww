import type { Metadata } from "next";

import { TrackingLinksPage } from "@/components/growth/TrackingLinksTab";

export const metadata: Metadata = { title: "Tracking links" };

export default function Page() {
  return <TrackingLinksPage />;
}
