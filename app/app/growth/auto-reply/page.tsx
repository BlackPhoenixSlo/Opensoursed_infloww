import type { Metadata } from "next";

import AutoReplyPage from "@/components/growth/AutoReplyPage";

export const metadata: Metadata = { title: "Auto-reply" };

// My Automations > Auto-reply (ours, like Auto Post and Auto Story). Backed by
// the `autoreply` automation (service/automations/autoreply.py). The page
// renders its own PageFrame (creator column, Learn, the Auto-reply switch).
export default function Page() {
  return <AutoReplyPage />;
}
