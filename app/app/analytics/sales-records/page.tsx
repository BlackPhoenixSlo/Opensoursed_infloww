import type { Metadata } from "next";

import StatsReport from "@/components/stats/StatsReport";

export const metadata: Metadata = { title: "Sales records" };

export default function Page() {
  return <StatsReport view="employee" tab="sales" />;
}
