"use client";


import { useEffect, useEffectEvent } from "react";
import Link from "next/link";
import { Languages } from "lucide-react";

import { useSettingsBlob } from "@/lib/settingsBlob";
import { BlobNotes, Card, SettingsPanel, Switch } from "@/components/settings/SettingsPanel";

type MessagingBlob = { ai_translation: boolean; prompt?: string };
const DEFAULTS: MessagingBlob = { ai_translation: true };

const AI_TRANSLATION = "Enable AI translation in Messages Pro for employees in your organization";
const HELP = "ml-8 text-[length:var(--if-fs-sm)] leading-5 text-[var(--if-fg-2)]";
const LINK = "text-[var(--if-accent)] hover:underline underline-offset-2";

export default function MessagingSettingsTab() {
  const blob = useSettingsBlob<MessagingBlob>("messaging", DEFAULTS);
  const error = blob.save.error;

  const flip = (on: boolean) => {
    blob.set({ ai_translation: on });
    // undefined: JSON drops the retired `prompt` key, which the relay would refuse if a stored legacy value is over its limit.
    blob.commit({ ai_translation: on, prompt: undefined });
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
