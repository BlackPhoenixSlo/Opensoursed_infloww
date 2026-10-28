import type { Metadata } from "next";

import { PromotionPage } from "@/components/growth/PromotionTab";

export const metadata: Metadata = { title: "Profile promotion" };

export default function Page() {
  return <PromotionPage />;
}
