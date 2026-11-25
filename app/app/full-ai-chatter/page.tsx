import type { Metadata } from "next";

import FullAiChatterPage from "@/components/automations/FullAiChatterPage";

export const metadata: Metadata = { title: "Full AI Chat" };

export default function Page() {
  return <FullAiChatterPage />;
}
