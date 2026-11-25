"use client";


import { Badge } from "@/components/ui/primitives";

export interface AgencyKeyFacts {
  accounts: number;
  live_accounts: number;
  blocked_accounts: number;
  providers_set: string[];
  missing_providers?: string[];
}

// Keyed on MISSING providers: keys resolve per provider, so an agency with only a DeepInfra key still fails chat replies closed.
export function needsKey(a: AgencyKeyFacts): boolean {
  if (a.live_accounts <= 0) return false;
  return a.missing_providers
    ? a.missing_providers.length > 0
    : a.providers_set.length === 0;
}

export function AgencyKeyBadges({ agency }: { agency: AgencyKeyFacts }) {
  return (
    <>
      <span className="text-xs">
        {agency.live_accounts > 0 ? (
          <span className="text-ok">{agency.live_accounts} live</span>
        ) : (
          <span className="text-fg-dim/70">no live model</span>
        )}
      </span>
      <span className="text-xs text-fg-dim">
        of {agency.accounts} model{agency.accounts === 1 ? "" : "s"}
      </span>
      <span className="text-xs">
        {agency.providers_set.length > 0 && !needsKey(agency) ? (
          <span className="text-fg-dim">key: {agency.providers_set.join(", ")}</span>
        ) : needsKey(agency) ? (
          <span className="text-warn">
            needs {(agency.missing_providers ?? []).join(", ") || "a key"}
          </span>
        ) : (
          <span className="text-fg-dim/70">no key</span>
        )}
      </span>
      {/* Blocked: two keyed agencies claim the model, so the relay refuses rather than guess whose money; no key fixes it. */}
      {agency.blocked_accounts > 0 && (
        <Badge color="err">
          {agency.blocked_accounts} blocked — two owners, two keys
        </Badge>
      )}
    </>
  );
}
