import type { Metadata } from "next";

import { TrialLinksPage } from "@/components/growth/TrialLinksTab";

export const metadata: Metadata = { title: "Free trial links" };

export default function Page() {
  return <TrialLinksPage />;
}
