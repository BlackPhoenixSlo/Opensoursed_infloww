import type { Metadata } from "next";

import GrowthTabPage from "@/components/growth/GrowthTabPage";

export const metadata: Metadata = { title: "Profile promotion" };

export default function Page() {
  return <GrowthTabPage tab="promotion" />;
}
