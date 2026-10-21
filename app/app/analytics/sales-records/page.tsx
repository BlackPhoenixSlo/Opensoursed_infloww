import type { Metadata } from "next";

import StatsReport from "@/components/stats/StatsReport";

export const metadata: Metadata = { title: "Sales records" };

// Employee reports' second tab, as in Infloww (page-parity ticket 27); the URL stays this page's own.
export default function Page() {
  return <StatsReport view="employee" tab="sales" />;
}
