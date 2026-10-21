import type { Metadata } from "next";

import ReadyMadePanel from "@/components/automations/ReadyMadePanel";

export const metadata: Metadata = { title: "Auto Mass" };

// My Automations > Auto Mass (ours, like Auto Post). Saved mass messages that
// send on a schedule, resend and auto-unsend. Backed by the `mass_premade`
// automation (service/automations/mass_premade.py), which sends through
// `send_mass_message` (OF's messages/queue) and unsends through
// `unsend_messages`. The panel renders its own PageFrame (creator select, "New auto mass").
export default function Page() {
  return <ReadyMadePanel only="mass_premade" />;
}
