"use client";

import { Suspense, useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { NotAvailable } from "@/components/shell/NotAvailable";
import { DeniedPagePanel } from "@/components/shell/DeniedPage";
import { useFlags } from "@/components/shell/useFlags";
import { useGrantedPages } from "@/components/shell/useGrantedPages";
import { useIsChatterOnly } from "@/components/shell/useIsChatterOnly";
import { firstFanslyPage, withCreator } from "@/lib/fansly-mirror-route";

export default function Page() {
  return (
    <Suspense fallback={null}>
      <Landing />
    </Suspense>
  );
}

function Landing() {
  const router = useRouter();
  const creator = useSearchParams()?.get("creator") ?? null;
  const flags = useFlags();
  const chatterOnly = useIsChatterOnly();
  const grantedPages = useGrantedPages();
  const to = flags ? firstFanslyPage({ chatterOnly, grantedPages, flags }) : null;
  useEffect(() => {
    if (to) router.replace(withCreator(to, creator));
  }, [to, creator, router]);

  if (!flags || to) return null;
  if (!flags.fansly_manager) return <NotAvailable label="Fansly Manager" />;
  return <DeniedPagePanel />;
}
