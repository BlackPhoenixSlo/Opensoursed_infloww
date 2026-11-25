"use client";


import Link from "next/link";
import { usePathname } from "next/navigation";
import { LockKeyhole } from "lucide-react";

import { useGrantedPages } from "@/components/shell/useGrantedPages";
import { useIsChatterOnly } from "@/components/shell/useIsChatterOnly";
import { useAppliedSettings } from "@/lib/appliedSettings";
import { deniedPage } from "@/lib/nav";

export function DeniedPagePanel({ noPages = false }: { noPages?: boolean }) {
  return (
    <div className="max-w-shell mx-auto p-3 sm:p-6">
      <div className="rounded-xl border border-border bg-panel p-10 grid place-items-center text-center gap-3">
        <LockKeyhole aria-hidden className="w-8 h-8 text-fg-dim" />
        {noPages ? (
          <>
            <p className="text-fg font-medium">Your role does not give you any pages yet</p>
            <p className="text-fg-dim">
              Ask your agency owner to set up your role. Meanwhile, the{" "}
              <Link href="/help-center" className="text-accent hover:underline">Help center</Link> is open to you.
            </p>
          </>
        ) : (
          <p className="text-fg font-medium">Your role does not allow this page</p>
        )}
      </div>
    </div>
  );
}

export default function DeniedPageGate({ children }: { children: React.ReactNode }) {
  const pathname = usePathname() ?? "/";
  const chatterOnly = useIsChatterOnly();
  const loading = useAppliedSettings().isLoading;
  const granted = useGrantedPages();
  if (chatterOnly && loading) return null;
  if (deniedPage(pathname, granted)) return <DeniedPagePanel noPages={granted?.size === 0} />;
  return <>{children}</>;
}
