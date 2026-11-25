import type { Metadata } from "next";

import ReadyMadePanel from "@/components/automations/ReadyMadePanel";

export const metadata: Metadata = { title: "Auto Mass" };

export default function Page() {
  return <ReadyMadePanel only="mass_premade" />;
}
