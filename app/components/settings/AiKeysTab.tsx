"use client";

/**
 * AI keys: the owner's own LLM keys (AgencyKeysCard's fields) with Save in the Panel header, as every Settings
 * tab, then each Creator's daily AI spend limit (AiSpendCapCard, its own Save), then the server's Google Drive key
 * for the vault importer and the server's fallback TypeSafe (Jev) key, used by any agency with none of its own (ServerKeyCard, master-only to edit, own Save: a different store, /admin/secrets), then the owner's
 * access tokens for an AI app (AccessTokensCard, its own dialog). Hidden from a Chatter (SETTINGS_TABS chatterHidden); the relay
 * owner-gates the keys routes regardless.
 */

import AgencyKeysCard from "@/components/setup/AgencyKeysCard";
import DriveKeyCard, { ServerKeyCard } from "@/components/setup/DriveKeyCard";
import AccessTokensCard from "@/components/settings/AccessTokensCard";
import AiSpendCapCard from "@/components/settings/AiSpendCapCard";
import { useKeyDraft } from "@/hooks/useKeyDraft";
import { useSaveTenantKeys } from "@/hooks/useTenantKeys";
import { IF_BTN_PRIMARY, Section, SettingsPanel } from "@/components/settings/SettingsPanel";

const NOTE = "text-[length:var(--if-fs-sm)] leading-5 text-[var(--if-fg-2)]";

export default function AiKeysTab() {
  const saveM = useSaveTenantKeys();
  const keys = useKeyDraft(saveM.mutateAsync, "Saved — takes effect on the next message.");

  return (
    <SettingsPanel
      title="AI keys"
      actions={
        <button type="button" className={IF_BTN_PRIMARY} disabled={!keys.dirty || saveM.isPending} onClick={() => void keys.save()}>
          {saveM.isPending ? "Saving…" : "Save"}
        </button>
      }
    >
      <p className={`mb-4 ${NOTE}`}>
        The keys your models&apos; AI runs on. Only your account uses them. Leave a field blank to keep the stored key.
      </p>
      {keys.note && <p role="status" className={`mb-4 ${NOTE}`}>{keys.note}</p>}
      <Section>
        <AgencyKeysCard keys={keys} pending={saveM.isPending} />
      </Section>
      <Section>
        <AiSpendCapCard />
      </Section>
      <Section title="TypeSafe / Jev (server fallback key)">
        <ServerKeyCard
          name="TYPESAFE_API_KEY"
          intro="Used for any agency that has not saved its own TypeSafe key above."
          savedNote="Saved — Jev uses it on its next read."
        />
      </Section>
      <Section title="Google Drive (server key)">
        <DriveKeyCard />
      </Section>
      <Section>
        <AccessTokensCard />
      </Section>
    </SettingsPanel>
  );
}
