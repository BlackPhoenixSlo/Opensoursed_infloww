"use client";

/**
 * Messaging settings (docs/spec/settings-tabs/phase-04-time-tracking-messaging.md): the AI translation
 * switch, saved on flip, and the AI Translator prompt, edited behind "Edit", both saved to the
 * `messaging` Settings blob behind the Load gate.
 *
 * The switch is Applied (docs/spec/phase-04-apply-stored-settings.md, stories 56-59): off, it disables a
 * chatter's translate switch in the Composer and `/admin/translate` refuses the chatter. Never saved, it
 * counts as on, so its default here is on. Translation is Google's free keyless endpoint
 * (service/translate_api.py), which takes no instructions, so the prompt is stored but never used: its card
 * says so instead of a "not applied yet" note (the LLM tier was vetoed, ticket 28 closed 2026-10-16).
 */

import { useEffect, useEffectEvent, useState } from "react";
import Link from "next/link";
import { Languages, SquarePen } from "lucide-react";

import { useSettingsBlob } from "@/lib/settingsBlob";
import { BlobNotes, Card, FieldTextarea, IF_BTN, SettingsPanel, Switch } from "@/components/settings/SettingsPanel";
import { SaveRow } from "@/components/settings/StickySaveBar";

type MessagingBlob = { ai_translation: boolean; prompt: string };
const DEFAULTS: MessagingBlob = { ai_translation: true, prompt: "" };

/** The switch's name and its caption: the bundle's caption under the card title. */
const AI_TRANSLATION = "Enable AI translation in Messages Pro for employees in your organization";
/** A card's caption, 32px in so it lines up with the title past the 20px icon and its 12px gap. */
const CAPTION = "ml-8 text-[length:var(--if-fs-sm)] leading-5 text-[var(--if-fg-2)]";
/** A card's note under its caption: what the setting actually does here. */
const NOTE = "ml-8 mt-2 text-[length:var(--if-fs-sm)] leading-5 text-[var(--if-fg-3)]";
/** An in-app link inside a note. */
const LINK = "text-[var(--if-accent)] hover:underline underline-offset-2";

/** The prompt box's counter limit: Infloww's `n/2000`. */
const PROMPT_MAX = 2000;

/** The card whose save was asked. */
type Asker = "switch" | "prompt";

export default function MessagingSettingsTab() {
  const blob = useSettingsBlob<MessagingBlob>("messaging", DEFAULTS);
  const error = blob.save.error;
  /** The prompt editor's text; null while the card shows the stored prompt. It reaches the hook only on
   *  Save, so a flip never sends it (spec, Implementation Decisions). */
  const [draft, setDraft] = useState<string | null>(null);

  // A save PUTs the hook's whole `value` as it stands when it runs, and a `set` has not reached `value`
  // until the next render. So each card only `set`s its change and asks; this effect saves on the render
  // that holds it (spec, Interfaces). Every ask is a new object, so the effect runs once per ask, and
  // `asked.by` says whose save a `save.error` is. A saved prompt closes the editor.
  const [asked, setAsked] = useState<{ by: Asker } | null>(null);
  const saveValue = useEffectEvent((by: Asker) => blob.commit({}, by === "prompt" ? () => setDraft(null) : undefined));
  useEffect(() => {
    if (asked) saveValue(asked.by);
  }, [asked]);
  const ask = (by: Asker, patch: Partial<MessagingBlob>) => {
    blob.set(patch);
    setAsked({ by });
  };
  const errorOf = (by: Asker) => (asked?.by === by ? error : null);

  // A failed save drops its change from the hook: the switch flips back, and a failed prompt stays out of
  // the next flip's PUT while the editor keeps it in `draft`. The error stays shown until the next ask.
  const dropChange = useEffectEvent(() => blob.reset());
  useEffect(() => {
    if (error) dropChange();
  }, [error]);

  return (
    <SettingsPanel title="Messaging settings">
      <BlobNotes note={blob.save.gateNote} q={blob.query} />
      <Card
        box="filled"
        title="AI translation"
        icon={<Languages size={20} aria-hidden />}
        control={
          <Switch
            checked={blob.value.ai_translation}
            label={AI_TRANSLATION}
            onChange={blob.loaded && !blob.save.saving ? (on) => ask("switch", { ai_translation: on }) : undefined}
          />
        }
      >
        <p className={CAPTION}>{AI_TRANSLATION}</p>
        <p className={NOTE}>
          A chat&apos;s text messages are translated to English when someone turns on &ldquo;Use translation&rdquo; in
          the{" "}
          <Link href="/messages-pro" className={LINK}>
            Messages Pro
          </Link>{" "}
          composer or presses Translate on a message, using Google&apos;s free translate service (no API key needed).
          Off, your{" "}
          <Link href="/employees" className={LINK}>
            employees
          </Link>{" "}
          can&apos;t turn on &ldquo;Use translation&rdquo;, don&apos;t see Translate on messages, and the server
          refuses their requests; owner logins keep it.
        </p>
        {errorOf("switch") && (
          <p role="alert" className="ml-8 mt-2 text-[length:var(--if-fs-sm)] text-[var(--if-danger)]">
            {error}
          </p>
        )}
      </Card>
      <Card
        box="filled"
        title="AI Translator prompt"
        icon={<SquarePen size={20} aria-hidden />}
        control={
          draft === null ? (
            <button type="button" className={IF_BTN} disabled={!blob.loaded} onClick={() => setDraft(blob.value.prompt)}>
              Edit
            </button>
          ) : (
            <div className="flex items-center gap-2">
              <button
                type="button"
                className={IF_BTN}
                onClick={() => {
                  setDraft(null);
                  if (asked?.by === "prompt") setAsked(null);
                }}
              >
                Cancel
              </button>
              <SaveRow
                look="settings"
                onSave={() => ask("prompt", { prompt: draft })}
                saving={blob.save.saving}
                canSave={blob.loaded}
                error={errorOf("prompt")}
              />
            </div>
          )
        }
      >
        <p className={CAPTION}>Instructions such as tone, style and specific vocabulary for translations</p>
        <p className={NOTE}>
          Saved for your organization, but not used: Google&apos;s free translate service takes no instructions.
        </p>
        {/* Always the textarea, as Infloww: read-only until Edit, as tall as its text (100-200px). */}
        <div className="relative ml-8 mt-3 w-[calc(100%-2rem)]">
          <FieldTextarea
            aria-label="AI Translator prompt"
            readOnly={draft === null}
            placeholder="No prompt set"
            maxLength={PROMPT_MAX}
            value={draft ?? blob.value.prompt}
            onChange={(e) => setDraft(e.target.value)}
            className="w-full pb-6 [field-sizing:content] min-h-[100px] max-h-[200px]"
          />
          <span aria-hidden className="absolute right-3 bottom-1.5 text-[length:var(--if-fs-sm)] text-[var(--if-fg-3)]">
            {(draft ?? blob.value.prompt).length}/{PROMPT_MAX}
          </span>
        </div>
      </Card>
    </SettingsPanel>
  );
}
