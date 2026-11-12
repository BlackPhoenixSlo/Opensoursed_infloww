import type { Metadata } from "next";

import { RedirectLinksPage } from "@/components/growth/RedirectLinksPanel";

export const metadata: Metadata = { title: "Redirect links" };

export default function Page() {
  return <RedirectLinksPage />;
}
