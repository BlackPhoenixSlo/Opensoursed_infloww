import type { Metadata } from "next";

import ShiftSchedule from "@/components/shifts/ShiftSchedule";

export const metadata: Metadata = { title: "Shift schedule" };

/** The page draws its own Infloww header (the time zone label and the Shift Settings gear) and full-width tabs, so
 *  it does not sit in `PageFrame`. */
export default function Page() {
  return <ShiftSchedule />;
}
