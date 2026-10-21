import type { Metadata } from "next";

import ReadyMadePanel from "@/components/automations/ReadyMadePanel";

export const metadata: Metadata = { title: "Auto Post" };

// My Automations > Auto Post (ours, docs/infloww-screens.md §4.1). Backed by
// the `auto_posts` automation (service/automations/auto_posts.py). The panel
// renders its own PageFrame: its header holds the creator select and "New auto post".
export default function Page() {
  return <ReadyMadePanel only="auto_posts" />;
}
