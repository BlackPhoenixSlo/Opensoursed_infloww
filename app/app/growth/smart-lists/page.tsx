import type { Metadata } from "next";

import GrowthTabPage from "@/components/growth/GrowthTabPage";

export const metadata: Metadata = { title: "Smart lists" };

export default function Page() {
  return <GrowthTabPage tab="smart" />;
}
