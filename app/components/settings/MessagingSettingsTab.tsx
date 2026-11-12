"use client";

/**
 * Messaging settings (docs/spec/settings-tabs/phase-04-time-tracking-messaging.md): the AI translation
 * switch, saved on flip to the `messaging` Settings blob behind the Load gate.
 *
 * The switch is Applied (docs/spec/phase-04-apply-stored-settings.md, stories 56-59): off, it disables a
 * chatter's translate switch in the Composer and `/admin/translate` refuses the chatter. Never saved, it
 * counts as on, so its default here is on. Translation is Google's free keyless endpoint
 * (service/translate_api.py), which takes no instructions, so the old AI Translator prompt editor is gone
 * (owner, 2026-11-11); the blob's `prompt` key stays in every PUT so a stored one survives.
 */

import { useEffect, useEffectEvent } from "react";
import Link from "next/link";
import { Languages } from "lucide-react";

import { useSettingsBlob } from "@/lib/settingsBlob";
import { BlobNotes, Card, SettingsPanel, Switch } from "@/components/settings/SettingsPanel";

type MessagingBlob = { ai_translation: boolean; prompt: string };
const DEFAULTS: MessagingBlob = { ai_translation: true, prompt: "" };

/** The switch's name. */
const AI_TRANSLATION = "Enable AI translation in Messages Pro for employees in your organization";
/** The card's one help line, 32px in so it lines up with the title past the 20px icon and its 12px gap. */
const HELP = "ml-8 text-[length:var(--if-fs-sm)] leading-5 text-[var(--if-fg-2)]";
const LINK = "text-[var(--if-accent)] hover:underline underline-offset-2";

export default function MessagingSettingsTab() {
  const blob = useSettingsBlob<MessagingBlob>("messaging", DEFAULTS);
  const error = blob.save.error;

  // Shown flipped at once; a failed save drops the change, so the switch flips back and the error stays.
  const flip = (on: boolean) => {
    blob.set({ ai_translation: on });
    blob.commit({ ai_translation: on });
  };
  const dropChange = useEffectEvent(() => blob.reset());
  useEffect(() => {
    if (error) dropChange();
  }, [error]);

  return (
    <SettingsPanel title="Messaging settings">
      <BlobNotes className="mb-4" note={blob.save.gateNote} q={blob.query} />
      <Card
        title="AI translation"
        icon={<Languages size={20} aria-hidden />}
        control={
          <Switch
            checked={blob.value.ai_translation}
            label={AI_TRANSLATION}
            onChange={blob.loaded && !blob.save.saving ? flip : undefined}
          />
        }
      >
        <p className={HELP}>
          Lets employees translate chats in{" "}
          <Link href="/messages-pro" className={LINK}>Messages Pro</Link>. Owners always can.
        </p>
        {error && (
          <p role="alert" className="ml-8 mt-2 text-[length:var(--if-fs-sm)] text-[var(--if-danger)]">
            {error}
          </p>
        )}
      </Card>
    </SettingsPanel>
  );
}
