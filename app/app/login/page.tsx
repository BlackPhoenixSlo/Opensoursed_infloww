"use client";

import { Suspense } from "react";

import Landing from "@/components/auth/Landing";

export default function LoginPage() {
  // useSearchParams in Landing needs a page-level Suspense for Next 16 streaming SSR.
  return (
    <Suspense fallback={null}>
      <Landing />
    </Suspense>
  );
}
