import type { Metadata } from "next";

import AutoFunnelPage from "@/components/automations/AutoFunnelPage";

export const metadata: Metadata = { title: "Auto Funnel" };

export default function Page() {
  return <AutoFunnelPage />;
}
