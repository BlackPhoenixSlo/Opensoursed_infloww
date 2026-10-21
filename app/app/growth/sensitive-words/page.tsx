import type { Metadata } from "next";

import SensitiveWordsPage from "@/components/growth/SensitiveWordsPage";

export const metadata: Metadata = { title: "Sensitive words" };

export default function Page() {
  return <SensitiveWordsPage />;
}
