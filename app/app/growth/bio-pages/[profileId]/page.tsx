"use client";

/** /growth/bio-pages/[profileId]: one bio page's editor (Growth → Bio pages → a row). */
import { use } from "react";

import { BioEditor } from "@/components/growth/bio/BioEditor";

export default function BioEditorPage({ params }: { params: Promise<{ profileId: string }> }) {
  const { profileId } = use(params);
  return <BioEditor profileId={profileId} />;
}
