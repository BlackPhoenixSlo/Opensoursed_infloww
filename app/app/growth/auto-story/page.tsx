import type { Metadata } from "next";

import AutoStoriesTab from "@/components/settings/AutoStoriesTab";

export const metadata: Metadata = { title: "Auto Story" };

// My Automations > Auto Story (ours, docs/infloww-screens.md §4.1). Backed by
// the `auto_stories` automation (service/automations/auto_stories.py). The tab
// renders its own PageFrame (creator column, Learn, "Edit raw JSON").
export default function Page() {
  return <AutoStoriesTab />;
}
