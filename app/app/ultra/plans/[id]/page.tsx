"use client";

import { use } from "react";

import UltraPlanPage from "@/components/ultra/UltraPlanPage";

export default function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  return <UltraPlanPage planId={id} />;
}
