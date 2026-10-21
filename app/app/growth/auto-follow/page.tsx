import type { Metadata } from "next";

import GrowthTabPage from "@/components/growth/GrowthTabPage";

export const metadata: Metadata = { title: "Auto-follow" };

export default function Page() {
  return <GrowthTabPage tab="auto_follow" />;
}
