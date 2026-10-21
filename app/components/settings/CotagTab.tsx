"use client";

/**
 * Co-creator tag (ticket 85): which co-creator one creator's sends @-tag, or no one. The setting is
 * account-wide (`account_ai_config.cotag_*`, the account-config PUT): of_client tags every mass message,
 * mass post, scheduled send and automation that attaches media that isn't provably solo, and a story gets
 * the @handle overlay (service/media_cotag.py). Blank is off, the default: nothing is tagged.
 *
 * The Creator is picked in the panel header, as on Your Balance: the one in scope when it opens, else the
 * first session-backed Creator. The card remounts per Creator so unsaved edits never carry over.
 */

import { useState } from "react";

import { useScope } from "@/contexts/ScopeContext";
import { useActiveAccounts } from "@/hooks/useAccounts";
import { CotagCard } from "@/components/automations/CotagSection";
import { SettingsPanel } from "@/components/settings/SettingsPanel";
import { EmptyState, IfCreatorSelect } from "@/components/ui/infloww";

const CAPTION = "mb-4 text-[length:var(--if-fs-sm)] leading-5 text-[var(--if-fg-2)]";

export default function CotagTab() {
  const { accountId: scoped } = useScope();
  const accounts = useActiveAccounts();
  const [picked, setPicked] = useState<string | null>(null);
  const accountId = picked ?? scoped ?? accounts[0]?.id ?? null;
  const picker = accounts.length > 0 && <IfCreatorSelect accounts={accounts} value={accountId} onChange={setPicked} />;

  return (
    <SettingsPanel title="Co-creator tag" actions={picker}>
      <p className={CAPTION}>
        Applies to all of this creator&apos;s sends with media: mass messages, mass posts, automations and
        stories. A chat message you write yourself keeps the tags you pick in the composer. Off by default
        (No co-creator tag).
      </p>
      {accountId ? (
        <div className="max-w-xl">
          <CotagCard key={accountId} accountId={accountId} />
        </div>
      ) : (
        <EmptyState kind="data" text="Select a creator to set its co-creator tag" className="h-[260px]" />
      )}
    </SettingsPanel>
  );
}
