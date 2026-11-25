import type { Metadata } from "next";

import ReadyMadePanel from "@/components/automations/ReadyMadePanel";

export const metadata: Metadata = { title: "Auto Post" };

export default function Page() {
  return <ReadyMadePanel only="auto_posts" />;
}
