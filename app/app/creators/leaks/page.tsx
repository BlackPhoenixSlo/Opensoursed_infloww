import type { Metadata } from "next";
import { Suspense } from "react";

import { LeakTracker } from "@/components/leaks/LeakTracker";

export const metadata: Metadata = { title: "Leak tracker" };

export default function Page() {
  return (
    <Suspense fallback={null}>
      <LeakTracker />
    </Suspense>
  );
}
