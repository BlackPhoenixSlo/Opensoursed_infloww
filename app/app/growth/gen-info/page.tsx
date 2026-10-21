import type { Metadata } from "next";

import GenInfoPage from "@/components/growth/GenInfoPage";

export const metadata: Metadata = { title: "Gen-Info" };

// My Automations > Gen-Info (ours, like Auto Post / Auto-reply). Backed by the daily
// `gen_info` automation (service/automations/gen_info.py) and, for fans already in the
// account, the one-shot `process_old_fans`. The page renders its own PageFrame.
export default function Page() {
  return <GenInfoPage />;
}
