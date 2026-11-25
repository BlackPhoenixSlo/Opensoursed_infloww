import type { Metadata } from "next";

import GetToKnowFansPage from "@/components/automations/GetToKnowFansPage";

export const metadata: Metadata = { title: "Get to know fans" };

export default function Page() {
  return <GetToKnowFansPage />;
}
