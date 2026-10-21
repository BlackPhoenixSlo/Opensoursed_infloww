import type { Metadata } from "next";

import GetToKnowFansPage from "@/components/automations/GetToKnowFansPage";

export const metadata: Metadata = { title: "Get to know fans" };

// My Automations > Get to know fans (ours). Backed by the `welcome_chatter_for_info`
// automation (service/automations/welcome_chatter_for_info.py) and the account's
// Model info note (account_ai_config.model_notes).
export default function Page() {
  return <GetToKnowFansPage />;
}
