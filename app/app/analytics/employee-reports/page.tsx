import type { Metadata } from "next";

import StatsReport from "@/components/stats/StatsReport";

export const metadata: Metadata = { title: "Employee reports" };

export default function Page() {
  return <StatsReport view="employee" />;
}
