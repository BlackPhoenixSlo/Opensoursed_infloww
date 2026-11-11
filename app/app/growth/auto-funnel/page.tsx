import type { Metadata } from "next";

import AutoFunnelPage from "@/components/automations/AutoFunnelPage";

export const metadata: Metadata = { title: "Auto Funnel" };

// My Automations > Auto Funnel (ours, like Auto Post / Auto Story / Auto-reply).
// Backed by the funnels (service/funnels_api.py) and the `reply_mass_funnel`
// automation (service/automations/reply_mass_funnel.py). The page renders its
// own PageFrame (creator column, Learn, "New funnel").
export default function Page() {
  return <AutoFunnelPage />;
}
