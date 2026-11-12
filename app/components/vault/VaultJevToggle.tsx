"use client";

/** The Jev v8 vault flags opt-in (`account_ai_config.vault_jev_enabled`, service/vault_jev.py) in the Extras
 *  drawer, beside Describe all: when on, every photo the describe / flags sweeps touch first gets TypeSafe Jev +
 *  NudeNet. Saves on toggle through the account-config PUT, sending the stored config back with only this key
 *  changed (the PUT replaces what it holds). `jev` is the describe plan's readiness block. */

import { useQueryClient } from "@tanstack/react-query";

import { IfSwitch } from "@/components/ui/infloww";
import { useAccountConfig, useSaveAccountConfig } from "@/hooks/useAccountConfig";

export interface JevPlan {
  enabled: boolean;
  /** NudeNet + the TypeSafe key are present; without them the pass refuses (never a Jev-only answer). */
  ready: boolean;
  reason: string;
}

export default function VaultJevToggle({ accountId, jev }: { accountId: string; jev?: JevPlan }) {
  const cfgQ = useAccountConfig(accountId);
  const saveM = useSaveAccountConfig(accountId);
  const qc = useQueryClient();
  const cfg = cfgQ.data?.config;
  if (!cfg) return null;
  const on = !!cfg.vault_jev_enabled;
  return (
    <div data-testid="vault-jev-toggle" className="rounded-lg border border-border px-3 py-2 space-y-1">
      <div
        className="flex items-center gap-3"
        title="Photos only. Before describe, each photo gets the Jev v8 flags (TypeSafe Jev + NudeNet): its price lane and what is bare. About $0.0004 a photo, billed to this account's daily AI cap. Clips keep the regular flags."
      >
        <IfSwitch
          aria-label="Jev v8 flags"
          checked={on}
          loading={saveM.isPending}
          onChange={(v) => saveM.mutate({ ...cfg, vault_jev_enabled: v }, {
            // the plan carries the readiness line
            onSuccess: () => qc.invalidateQueries({ queryKey: ["vault-describe-plan", accountId] }),
          })}
        />
        <span className="text-sm text-fg">Jev v8 flags (photos)</span>
      </div>
      {on && jev?.enabled && !jev.ready && (
        <p className="text-[11px] text-warn">Jev is refusing on this server: {jev.reason}</p>
      )}
      {saveM.isError && <p className="text-[11px] text-err">{saveM.error?.message || "Could not save."}</p>}
    </div>
  );
}
