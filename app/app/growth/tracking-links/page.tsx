import type { Metadata } from "next";

import GrowthTabPage from "@/components/growth/GrowthTabPage";

export const metadata: Metadata = { title: "Tracking links" };

export default function Page() {
  return <GrowthTabPage tab="tracking" />;
}
