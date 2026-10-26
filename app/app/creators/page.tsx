"use client";

/**
 * /creators — Creators > "Manage creators" (was /setup, which redirects here),
 * in the order of the Layout capture docs/infloww-layouts/creators-manage.md
 * (docs/spec/infloww-parity-round-2/phase-04-creators-pages.md):
 *   • the page title and, beside it, "Add creator" (creators-manage#3, #4, #7,
 *     #9), which opens AddCreatorModal: Infloww's Add creator steps (Creator
 *     details, platform, proxy, sign-in, linked, account details), its
 *     sign-in step our Inflowwww extras, PasteCurlCard (the extension path)
 *     and FanslyPasteSessionCard. Desk-only sign-in.
 *   • the extension probe, once on mount (useExtensionProbe); the modal reads
 *     its answer and never probes.
 *   • `?relink=browserbase` (a 2FA notification's link) opens the modal at Browserbase login, once (RelinkParam).
 *   • AccountsTable  — the filter bar (CreatorFilterBar), the creator table and
 *                      its footer at the page's foot, filtering and paging on
 *                      the client. A row's recovery actions open the same modal
 *                      at the section that performs them, titled "Link creator
 *                      account"; a Creator with no account and "Link another
 *                      account" open it at its platform step (`onAdd`). Edit and
 *                      Delete are the table's own modals. The extras below sit between its table and
 *                      its footer.
 *   • DriftBanner    — only while a model is stale; an Inflowwww extra kept
 *                      outside the disclosure, since an alert hidden in a
 *                      closed disclosure fails its purpose.
 *   • MirrorFreshnessBanner — founder only, beside it: OF Manager's mirror is
 *                      behind OF's live build (a maintainer's re-capture).
 *   • one collapsed "Inflowwww extras" disclosure, founder only, holding
 *     ManagedAgencyKeysCard and KeysCard (the server's house keys). YOUR
 *     agency's LLM keys live in Settings → AI keys.
 *   (ProxiesTable lives on Creators > Custom proxy, /creators/proxy.)
 */

import { Suspense, useCallback, useEffect, useState, type ComponentProps } from "react";
import { useSearchParams } from "next/navigation";

import DriftBanner from "@/components/setup/DriftBanner";
import MirrorFreshnessBanner from "@/components/setup/MirrorFreshnessBanner";
import AccountsTable from "@/components/setup/AccountsTable";
import AddCreatorModal, {
  AddCreatorButton, DESKTOP_ONLY_LINE, type SectionKey,
} from "@/components/setup/AddCreatorModal";
import { useExtensionProbe } from "@/components/setup/useExtensionProbe";
import { InflowwPageHeader } from "@/components/ui/infloww";
import KeysCard from "@/components/setup/KeysCard";
import ManagedAgencyKeysCard from "@/components/setup/ManagedAgencyKeysCard";
import { useUser } from "@/contexts/UserContext";
import { EXTRA_LABEL, EXTRAS_OVERFLOW_LABEL } from "@/lib/openinflowwwwExtras";

export default function SetupPage() {
  const { user: me } = useUser();
  // Once, on mount, so the Route walk still sees the probe on /creators; the modal reads this answer.
  const extInstalled = useExtensionProbe();
  // null: closed; `at` set: opened from a row, at that section; `draft` / `linkAnother`: at the platform step.
  const [adding, setAdding] = useState<Pick<ComponentProps<typeof AddCreatorModal>, "at" | "draft" | "linkAnother"> | null>(null);
  const openAt = useCallback((at: SectionKey) => setAdding({ at }), []);
  return (
    // Full width, as HBLayout is: the old 1152px cap would stop the header rule and the table short (creators-manage#4,
    // #27). From 768px up the page is the window's height below the top bar, so the table's footer keeps the page's
    // foot (#53; the house height, as SettingsShell takes it).
    // The HB page body, #0d0d0d (page-parity 02).
    <div className="flex flex-col bg-hb-bg md:h-[calc(100dvh-var(--shell-top,3.5rem))]">
      {/* 48px header, 0 24px, a bottom rule; the title 16px weight 600, "Add creator" at the right (creators-manage#4,
          #7, #9). */}
      <InflowwPageHeader title="Manage creators" actions={<AddCreatorButton onClick={() => setAdding({})} />} />
      {/* useSearchParams suspends while the page prerenders: its own boundary, so nothing else waits. */}
      <Suspense fallback={null}>
        <RelinkParam open={openAt} />
      </Suspense>
      {adding && (
        <AddCreatorModal
          extInstalled={extInstalled}
          onClose={() => setAdding(null)}
          at={adding.at}
          draft={adding.draft}
          linkAnother={adding.linkAnother}
        />
      )}

      {/* The table draws the content's padding (creators-manage#12) and its footer; our extras sit between them. */}
      <AccountsTable onLink={(at) => setAdding({ at })} onAdd={(from) => setAdding(from)}>
        <DriftBanner />
        {me?.is_admin && <MirrorFreshnessBanner />}

        <p className="md:hidden text-sm text-fg-dim" title={EXTRA_LABEL}>{DESKTOP_ONLY_LINE}</p>

        {/* Founder only. Other agencies' keys: the card also returns null on a 403, but
            only AFTER the answer lands; without this gate every tenant paints the founder
            heading for the whole in-flight window and fires one guaranteed 403 per page
            view. The SERVER's house keys: the relay 403s both verbs for anyone else, so an
            agency that saw this card would get a broken panel and a wrong idea about whose
            keys these are. Hidden, not disabled. */}
        {me?.is_admin && (
          <details className="hidden md:block">
            <summary title={EXTRAS_OVERFLOW_LABEL} className="cursor-pointer text-[12px] text-muted">
              {EXTRAS_OVERFLOW_LABEL}
            </summary>
            <div className="mt-4 space-y-6">
              <ManagedAgencyKeysCard />
              <KeysCard />
            </div>
          </details>
        )}
      </AccountsTable>
    </div>
  );
}

/** `?relink=browserbase` (a 2FA notification's link) opens the modal at Browserbase login, also when the link is
 *  clicked with this page already open (the param changes, the page stays mounted). The param is dropped at once,
 *  so a reload or Back does not reopen the modal; any other value is dropped and ignored. */
function RelinkParam({ open }: { open: (at: SectionKey) => void }) {
  const at = useSearchParams().get("relink");
  useEffect(() => {
    if (at === null) return;
    const url = new URL(window.location.href);
    url.searchParams.delete("relink");
    window.history.replaceState(window.history.state, "", url.pathname + url.search + url.hash);
    if (at === "browserbase") open(at);
  }, [at, open]);
  return null;
}
