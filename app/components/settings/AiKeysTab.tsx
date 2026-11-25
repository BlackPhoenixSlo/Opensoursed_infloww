"use client";


import AgencyKeysCard from "@/components/setup/AgencyKeysCard";
import ServerKeyCard from "@/components/setup/ServerKeyCard";
import AccessTokensCard from "@/components/settings/AccessTokensCard";
import AiSpendCapCard from "@/components/settings/AiSpendCapCard";
import { useKeyDraft } from "@/hooks/useKeyDraft";
import { useSaveTenantKeys } from "@/hooks/useTenantKeys";
import { IF_BTN_PRIMARY, Section, SettingsPanel } from "@/components/settings/SettingsPanel";

const DRIVE_INTRO = "Lets Vault Pro import from a Google Drive folder link. A plain Google API key with the Drive API "
  + "enabled — the folder itself must be shared as \"Anyone with the link can view\".";
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
          savedNote="Saved — Jev (the off-script check, Full AI, the vault AI) uses it on its next call for every agency without its own key."
        />
      </Section>
      <Section title="Google Drive (server key)">
        <ServerKeyCard
          name="GOOGLE_DRIVE_API_KEY"
          intro={DRIVE_INTRO}
          savedNote="Saved — Drive import works on the next upload."
        />
      </Section>
      <Section>
        <AccessTokensCard />
      </Section>
    </SettingsPanel>
  );
}
