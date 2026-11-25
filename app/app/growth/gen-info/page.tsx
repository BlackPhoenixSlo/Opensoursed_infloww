import type { Metadata } from "next";

import GenInfoPage from "@/components/growth/GenInfoPage";

export const metadata: Metadata = { title: "Gen-Info" };

export default function Page() {
  return <GenInfoPage />;
}
