"use client";

import { seedInline, type InlineData } from "@/lib/inlineBoot";

export default function InlineBoot({ data }: { data: InlineData | null }) {
  if (data && typeof window !== "undefined") seedInline(data);
  return null;
}
