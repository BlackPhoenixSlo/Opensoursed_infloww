"use client";

/**
 * AgencyKeysCard — Settings → AI keys, YOUR agency's LLM keys: the provider fields only. The edit state
 * (`useKeyDraft`) and the Save live in AiKeysTab, whose Panel header carries Save like every Settings tab.
 *
 * Every OF account you own bills the key you paste here, so no other agency on
 * this server can spend on your credential and you cannot spend on theirs. That
 * is the whole reason this card is separate from KeysCard (Creators → Inflowwww
 * extras, founder only), which holds the SERVER's own house keys.
 *
 * The edit rules that keep a stored key safe (placeholder-not-value, blank
 * means unchanged, send only what changed) live in useKeyDraft, shared with
 * that card.
 */

import { useTenantKeys } from "@/hooks/useTenantKeys";
import { LABELS, HELP, wrongFieldWarning } from "@/components/setup/providerFields";
import type { KeyDraft } from "@/hooks/useKeyDraft";
import { Badge } from "@/components/ui/primitives";
import { Skeleton } from "@/components/ui/Skeleton";
import { FieldInput } from "@/components/settings/SettingsPanel";
import { ifConfirm } from "@/components/ui/ifConfirm";

export default function AgencyKeysCard({ keys, pending }: {
  /** The tab's draft: the typed fields, and `clear` for one stored key. */
  keys: Pick<KeyDraft, "draft" | "setField" | "clear">;
  /** A save or clear is in flight. */
  pending: boolean;
}) {
  const { data, isLoading, error } = useTenantKeys();
  const { draft, setField, clear } = keys;

  const providers = data?.providers ?? {};
  const shared = data?.shared_accounts ?? [];

  return (
    <div className="space-y-4">

      {shared.some((a) => a.contested.length > 0) && (
        <div className="rounded-md border border-err/40 bg-err/5 p-3 space-y-1">
          <p className="text-sm font-medium text-err">
            AI is stopped on{" "}
            {shared.filter((a) => a.contested.length > 0).length === 1
              ? "a provider of 1 model"
              : `a provider of ${shared.filter((a) => a.contested.length > 0).length} models`}{" "}
            — two owners, two keys
          </p>
          <p className="text-[11px] text-fg-dim">
            Two accounts are linked to each of these and BOTH have a key for the
            provider, so nothing says whose key pays and the relay refuses rather
            than bill the wrong one. Clear the key on the owner who should not
            pay, remove one owner in Admin → Manage (revoke), or have one of them
            transfer it to the other.
          </p>
          <ul className="text-[11px] text-fg-dim">
            {shared
              .filter((a) => a.contested.length > 0)
              .map((a) => (
                <li key={a.account_id}>
                  <span className="font-medium">{a.nickname}</span> — shared by{" "}
                  {a.owners.join(", ")}; both keyed for{" "}
                  {a.contested.map((p) => LABELS[p] ?? p).join(", ")}
                </li>
              ))}
          </ul>
        </div>
      )}

      {shared.some((a) => a.contested.length === 0) && (
        <div className="rounded-md border border-border bg-bg-elev-1 p-3 space-y-1">
          <p className="text-sm font-medium">
            {shared.filter((a) => a.contested.length === 0).length === 1
              ? "1 model has"
              : `${shared.filter((a) => a.contested.length === 0).length} models have`}{" "}
            two owners — AI keeps running
          </p>
          <p className="text-[11px] text-fg-dim">
            Each provider bills whichever owner has a key for it. A provider
            neither owner has set is silent until one of you adds it.
          </p>
          <ul className="text-[11px] text-fg-dim">
            {shared
              .filter((a) => a.contested.length === 0)
              .map((a) => (
                <li key={a.account_id}>
                  <span className="font-medium">{a.nickname}</span> — shared by{" "}
                  {a.owners.join(", ")}
                  {Object.keys(a.pays).length > 0 && (
                    <>
                      ; bills{" "}
                      {Object.entries(a.pays)
                        .map(([p, who]) => `${LABELS[p] ?? p} → ${who}`)
                        .join(", ")}
                    </>
                  )}
                </li>
              ))}
          </ul>
        </div>
      )}

      {isLoading && <div className="space-y-2" aria-busy="true"><Skeleton className="h-4 w-32" /><Skeleton className="h-9 w-full" /></div>}
      {error && (
        <div className="text-sm text-err">
          Couldn&apos;t load your key status — sign in as an account owner.
        </div>
      )}

      {Object.entries(providers).map(([name, k]) => (
        <div key={name} className="space-y-1">
          <div className="flex items-center gap-2">
            <label htmlFor={`ai-key-${name}`} className="text-[length:var(--if-fs)] text-[var(--if-fg)]">{LABELS[name] ?? name}</label>
            {k.set ? <Badge color="ok">set</Badge> : <Badge color="muted">not set</Badge>}
            {k.set && (
              <button
                type="button"
                disabled={pending}
                onClick={async () => {
                  // One click here stops every automation on every account this
                  // owner runs — the calls fail closed with no key. Worth a beat.
                  const label = LABELS[name] ?? name;
                  if (await ifConfirm(`Remove your ${label}? Your models stop replying until you add one.`, { danger: true })) {
                    void clear(name);
                  }
                }}
                className="text-[11px] text-err hover:underline disabled:opacity-40"
              >
                clear
              </button>
            )}
          </div>
          <FieldInput
            id={`ai-key-${name}`}
            type="password"
            value={draft[name] ?? ""}
            placeholder={k.set ? `${k.hint} — leave blank to keep` : "Paste key"}
            autoComplete="off"
            onChange={(e) => setField(name, e.target.value)}
          />
          {wrongFieldWarning(name, draft[name] ?? "") ? (
            <p className="text-[11px] text-warn" role="alert">
              {wrongFieldWarning(name, draft[name] ?? "")}
            </p>
          ) : (
            HELP[name] && <p className="text-[11px] text-fg-dim">{HELP[name]}</p>
          )}
        </div>
      ))}
    </div>
  );
}
