import type { Metadata } from "next";

import ShiftSchedule from "@/components/shifts/ShiftSchedule";

export const metadata: Metadata = { title: "Shift schedule" };

export default function Page() {
  return <ShiftSchedule />;
}
