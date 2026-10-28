import type { Metadata } from "next";

import { AutoFollowPage } from "@/components/growth/AutoFollowList";

export const metadata: Metadata = { title: "Auto-follow" };

export default function Page() {
  return <AutoFollowPage />;
}
