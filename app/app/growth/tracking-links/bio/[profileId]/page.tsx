"use client";

/** /growth/tracking-links/bio/[profileId]: one bio page's editor (Growth → Tracking links → Bio pages → a row). */
import { use } from "react";

import { BioEditor } from "@/components/growth/bio/BioEditor";

export default function BioEditorPage({ params }: { params: Promise<{ profileId: string }> }) {
  const { profileId } = use(params);
  return <BioEditor profileId={profileId} />;
}
