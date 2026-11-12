"use client";

/**
 * Co-creator tag (ticket 85): which co-creator one creator's sends @-tag, or no one. The setting is
 * account-wide (`account_ai_config.cotag_*`, the account-config PUT): of_client tags every mass message,
 * mass post, scheduled send and automation that attaches media that isn't provably solo, and a story gets
 * the @handle overlay (service/media_cotag.py). Blank is off, the default: nothing is tagged.
 *
 * The Creator is picked in the panel header, beside Save: the one in scope when it opens, else the first
 * session-backed Creator. The form remounts per Creator so unsaved edits never carry over.
 */

import { useState, type ReactNode } from "react";

import { useScope } from "@/contexts/ScopeContext";
import { useAccounts, useActiveAccounts } from "@/hooks/useAccounts";
import { CotagForm } from "@/components/automations/CotagSection";
import { SettingsPanel } from "@/components/settings/SettingsPanel";
import { SaveRow } from "@/components/settings/StickySaveBar";
import { EmptyState, IfCreatorSelect } from "@/components/ui/infloww";
import { Skeleton } from "@/components/ui/Skeleton";

const CAPTION = "mb-4 text-[length:var(--if-fs-sm)] leading-5 text-[var(--if-fg-2)]";

/** The tab's one help line. */
function Caption() {
  return (
    <p className={CAPTION}>
      @-tags this co-creator on mass messages, mass posts, automations and stories when the media isn&apos;t solo
      (messages and posts once they accept the tag request). Chat messages keep the composer&apos;s tags. Off by
      default.
    </p>
  );
}

export default function CotagTab() {
  const { accountId: scoped } = useScope();
  const accounts = useActiveAccounts();
  const accountsLoading = useAccounts().isLoading;
  const [picked, setPicked] = useState<string | null>(null);
  const accountId = picked ?? scoped ?? accounts[0]?.id ?? null;
  const picker = accounts.length > 0 && <IfCreatorSelect accounts={accounts} value={accountId} onChange={setPicked} />;
  const panel = (actions: ReactNode, body: ReactNode) => (
    <SettingsPanel title="Co-creator tag" actions={actions}>
      <Caption />
      {body}
    </SettingsPanel>
  );

  if (accountId) {
    return (
      <CotagForm key={accountId} accountId={accountId}>
        {(save, form) => panel(<>{picker}<SaveRow {...save} look="settings" /></>, <div className="max-w-xl">{form}</div>)}
      </CotagForm>
    );
  }
  return panel(
    picker,
    accountsLoading ? (
      // No Creator yet because the Creators are still loading: the form as placeholder bars.
      <div className="max-w-xl space-y-3" aria-busy="true"><Skeleton className="h-4 w-40" /><Skeleton className="h-10 w-full" /></div>
    ) : (
      <EmptyState kind="data" text="Select a creator to set its co-creator tag" className="h-[260px]" />
    ),
  );
}
