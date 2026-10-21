import type { Metadata } from "next";

import SmartMessagesPage from "@/components/growth/SmartMessagesPage";

export const metadata: Metadata = { title: "Smart Messages" };

export default function Page() {
  return <SmartMessagesPage />;
}
