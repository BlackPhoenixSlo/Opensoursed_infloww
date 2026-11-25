import type { Metadata } from "next";

import ScriptsPage from "@/components/growth/ScriptsPage";

export const metadata: Metadata = { title: "Scripts" };

export default function Page() {
  return <ScriptsPage />;
}
