import type { Metadata } from "next";

import { BioPagesPage } from "@/components/growth/bio/BioPagesPanel";

export const metadata: Metadata = { title: "Bio pages" };

export default function Page() {
  return <BioPagesPage />;
}
