import type { Metadata } from "next";

import FullAiChatterPage from "@/components/automations/FullAiChatterPage";

export const metadata: Metadata = { title: "Full AI Chat" };

// Full AI Chat (ours, nav.ts; owner-only in the sidebar). Backed by the Shadow runner
// (service/automations/full_ai_chat.py) and its read (service/full_ai_api.py). The page renders its own PageFrame.
export default function Page() {
  return <FullAiChatterPage />;
}
