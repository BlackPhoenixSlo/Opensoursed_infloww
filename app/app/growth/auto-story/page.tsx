import type { Metadata } from "next";

import AutoStoriesTab from "@/components/settings/AutoStoriesTab";

export const metadata: Metadata = { title: "Auto Story" };

export default function Page() {
  return <AutoStoriesTab />;
}
