import type { Metadata } from "next";

import GrowthTabPage from "@/components/growth/GrowthTabPage";

export const metadata: Metadata = { title: "Free trial links" };

export default function Page() {
  return <GrowthTabPage tab="trial" />;
}
