"use client";

/**
 * AiSpendCapCard — Settings → AI keys, one Creator's daily AI spend limit
 * (`account_ai_config.daily_cost_cap_cents`, the account-config PUT; rules in
 * aiSpendCap.ts). llm_client reserves every AI call of the Creator (chat,
 * automations, vault describes) against it, per provider per UTC day, and reads
 * it per call, so a raise lets the very next call through.
 *
 * Owner-only: the tab is hidden from a Chatter, and the relay ignores a
 * Chatter's value anyway. The Creator is picked in the card header (the one in
 * scope, else the first); the form remounts per Creator so an edit never
 * carries over.
 */

import { useState } from "react";

import { useScope } from "@/contexts/ScopeContext";
import { useActiveAccounts } from "@/hooks/useAccounts";
import { useAccountConfig, useSaveAccountConfig, type AccountConfigResp } from "@/hooks/useAccountConfig";
import { IfCreatorSelect, IfHelp, IfInput, IfLabel, SaveRow, saveVerdict } from "@/components/ui/infloww";
import { Card } from "@/components/ui/primitives";
import { Skeleton } from "@/components/ui/Skeleton";

import { canSaveCap, capError, centsToDollars, dollarsToCents, providerName, spentText } from "./aiSpendCap";

export default function AiSpendCapCard() {
  const { accountId: scoped } = useScope();
  const accounts = useActiveAccounts();
  const [picked, setPicked] = useState<string | null>(null);
  const accountId = picked ?? scoped ?? accounts[0]?.id ?? null;
  if (accounts.length === 0) return null;
  return (
    <Card className="space-y-4" data-testid="ai-cap-card">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <h2 className="text-lg font-semibold">Daily AI spend limit</h2>
          <p className="text-sm text-fg-dim">
            Per creator. Covers every AI call for this creator: chat replies, automations and vault photo
            describes.
          </p>
        </div>
        <IfCreatorSelect accounts={accounts} value={accountId} onChange={setPicked} />
      </div>
      {accountId && <CapLoader key={accountId} accountId={accountId} />}
    </Card>
  );
}

function CapLoader({ accountId }: { accountId: string }) {
  const cfgQ = useAccountConfig(accountId);
  if (!cfgQ.data?.config) {
    if (cfgQ.isError) {
      return <p className="text-sm text-err">{(cfgQ.error as Error)?.message || "Could not load the limit."}</p>;
    }
    return <div role="status" aria-label="Loading" className="space-y-3"><Skeleton className="h-4 w-40" /><Skeleton className="h-8 w-32" /></div>;
  }
  return <CapForm accountId={accountId} resp={cfgQ.data} />;
}

function CapForm({ accountId, resp }: { accountId: string; resp: AccountConfigResp }) {
  const saveM = useSaveAccountConfig(accountId);
  const stored = resp.config.daily_cost_cap_cents;
  const [raw, setRaw] = useState(() => centsToDollars(stored));
  const err = capError(raw, stored);
  const spend = resp.ai_spend_today?.providers ?? [];
  const inputId = `ai-cap-${accountId}`;

  return (
    <div className="space-y-3 text-[14px]">
      <div>
        <IfLabel htmlFor={inputId}>Daily AI spend limit ($/day)</IfLabel>
        <div className="flex items-center gap-2 text-fg">
          <span aria-hidden>$</span>
          <IfInput
            id={inputId}
            inputMode="decimal"
            aria-label="Daily AI spend limit in dollars"
            aria-describedby={`${inputId}-help`}
            className="w-28"
            value={raw}
            onChange={(e) => { setRaw(e.target.value); if (!saveM.isIdle) saveM.reset(); }}
          />
          <span className="text-muted">per day</span>
        </div>
        <IfHelp id={`${inputId}-help`}>
          Each AI provider this creator uses (for example the chat model&apos;s and the photo describer&apos;s)
          can spend up to this much per day; resets at 00:00 UTC. 0 pauses all AI for this creator. A change
          applies to the next AI call. Up to $100.
        </IfHelp>
      </div>
      <div className="text-[12px] text-fg-dim" data-testid="ai-cap-spend">
        {spend.length === 0 ? "No AI spend yet today (UTC)." : (
          <>
            Today (UTC):{" "}
            {spend.map((p, i) => (
              <span key={p.provider}>
                {i > 0 && " · "}
                {providerName(p.provider)} {spentText(p.spent_millicents)}
                {p.flagged && <span className="text-warn"> (hit the limit)</span>}
              </span>
            ))}
            {" "}of ${centsToDollars(stored)} each.
          </>
        )}
      </div>
      <SaveRow
        label="Save limit"
        save={saveVerdict(saveM)}
        warn={err}
        disabled={!canSaveCap(raw, stored)}
        onSave={() => saveM.mutate({ ...resp.config, daily_cost_cap_cents: dollarsToCents(raw)! })}
      />
    </div>
  );
}
