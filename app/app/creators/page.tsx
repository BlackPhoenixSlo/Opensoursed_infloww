"use client";


import { Suspense, useCallback, useEffect, useState, type ComponentProps } from "react";
import { useSearchParams } from "next/navigation";

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
  const extInstalled = useExtensionProbe();
  const [adding, setAdding] = useState<Pick<ComponentProps<typeof AddCreatorModal>, "at" | "draft" | "linkAnother" | "expectedAccountId"> | null>(null);
  const openAt = useCallback((at: SectionKey) => setAdding({ at }), []);
  return (
    <div className="flex flex-col bg-hb-bg md:h-[calc(100dvh-var(--shell-top,3.5rem))]">
      <InflowwPageHeader title="Manage creators" actions={<AddCreatorButton onClick={() => setAdding({})} />} />
      <Suspense fallback={null}>
        <RelinkParam open={openAt} />
      </Suspense>
      {adding && (
        <AddCreatorModal
          key={adding.at ?? adding.draft?.id ?? (adding.linkAnother ? "another" : "add")}
          extInstalled={extInstalled}
          onClose={() => setAdding(null)}
          at={adding.at}
          draft={adding.draft}
          linkAnother={adding.linkAnother}
          expectedAccountId={adding.expectedAccountId}
        />
      )}

      <AccountsTable onLink={(at, expectedAccountId) => setAdding({ at, expectedAccountId })} onAdd={(from) => setAdding(from)}>
        {me?.is_admin && <MirrorFreshnessBanner />}

        <p className="md:hidden text-sm text-fg-dim" title={EXTRA_LABEL}>{DESKTOP_ONLY_LINE}</p>

        {/* Founder only: the relay 403s the house keys for anyone else; ungated, every tenant fires a guaranteed 403. */}
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
