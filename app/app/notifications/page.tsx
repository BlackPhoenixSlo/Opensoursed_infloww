import type { Metadata } from "next";

import NotificationsPage from "@/components/NotificationsPage";

export const metadata: Metadata = { title: "Notifications" };

/** The full Notifications page, reached from the top bar bell's "See all"
 *  (docs/spec/phase-05-remaining-parity-gaps.md, item 5). */
export default function Page() {
  return <NotificationsPage />;
}
