"use client";

/** /ultra/plans/[id]: one Ultra plan to check, OK and follow (an MCP client's propose_plan open_url). */
import { use } from "react";

import UltraPlanPage from "@/components/ultra/UltraPlanPage";

export default function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  return <UltraPlanPage planId={id} />;
}
