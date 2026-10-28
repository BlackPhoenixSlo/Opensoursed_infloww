import type { Metadata } from "next";

import { SmartListsPage } from "@/components/growth/SmartListsTab";

export const metadata: Metadata = { title: "Smart lists" };

export default function Page() {
  return <SmartListsPage />;
}
