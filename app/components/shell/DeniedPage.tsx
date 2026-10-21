"use client";

/**
 * The shell's denied-page panel (docs/spec/phase-04-apply-stored-settings.md,
 * story 34): a page the session's Permission role does not grant, opened by
 * URL, is replaced by one plain line instead of mounting, so none of its
 * queries run. A chatter's page waits for the Applied settings read, so a
 * denied page never mounts before the answer.
 *
 * ASSUMPTION: a chatter-only session renders no page until the Applied
 * settings read first answers (cached for a minute). When the read fails it
 * renders every page as before but the My Automations ones, which stay denied
 * unless the read's `opt_in` grants them (`sessionGrantedPages`). Picking
 * another Creator keeps the last answer while its read loads
 * (`placeholderData`), so the page is never unmounted. Rung 4: the Relay still
 * refuses a denied route, so a failed read only loses the panel. Overturned if
 * the wait is too visible.
 *
 * A session granted no page at all (a new chatter whose role ticks none, or
 * whose role is disabled) gets a landing pointing at the Help center, which no
 * role gates, instead of the bare denied line.
 */

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

/** `children` (the page), or the denied-page panel in its place. */
export default function DeniedPageGate({ children }: { children: React.ReactNode }) {
  const pathname = usePathname() ?? "/";
  const chatterOnly = useIsChatterOnly();
  const loading = useAppliedSettings().isLoading;
  const granted = useGrantedPages();
  if (chatterOnly && loading) return null;
  if (deniedPage(pathname, granted)) return <DeniedPagePanel noPages={granted?.size === 0} />;
  return <>{children}</>;
}
