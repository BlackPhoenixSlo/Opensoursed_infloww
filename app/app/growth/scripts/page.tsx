import type { Metadata } from "next";

import ScriptsPage from "@/components/growth/ScriptsPage";

export const metadata: Metadata = { title: "Scripts" };

// Growth > Scripts: the bundle's script manager over our saved replies (ticket 35).
export default function Page() {
  return <ScriptsPage />;
}
