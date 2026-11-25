import type { Metadata } from "next";

import AutoReplyPage from "@/components/growth/AutoReplyPage";

export const metadata: Metadata = { title: "Auto-reply" };

export default function Page() {
  return <AutoReplyPage />;
}
