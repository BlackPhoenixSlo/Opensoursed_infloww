"use client";

/**
 * The "Purchased" Trigger's editor (ticket 44, owner ruling N2 position B): the
 * purchase_followup automation's on/off, its one message text and its Smart
 * Message settings (`SmartMessageFields`: media and price, Infloww's random
 * "after delay", Frequency, Effective / Expiry, Auto-unsend), saved through
 * `/admin/purchase-followup-config`.
 * Our editor, not Infloww's seven-step wizard; the dialog around it carries
 * the "Inflowwww extra" tag. Off by default; with no text saved, the message
 * starts as Infloww's own default script for the Trigger.
 */

import { useState } from "react";

import { Button, Textarea } from "@/components/ui/primitives";
import {
  usePurchaseFollowupConfig, useSavePurchaseFollowupConfig, type PurchaseFollowupConfig,
} from "@/hooks/usePurchaseFollowupConfig";

import { SmartMessageFields, collectExtras, extrasDraft, type ExtrasDraft } from "./SmartMessageFields";

/** The first of Infloww's default scripts for "Fan purchases PPV"
 *  (`resetTemplateDefaultData`, index.9f50f370.js @14445308), verbatim. */
export const PURCHASE_TEMPLATE = "Thanks for your purchase, {name}! You're in for a treat!";

export default function PurchaseFollowupEditor({ accountId }: { accountId: string | null }) {
  const q = usePurchaseFollowupConfig(accountId);
  if (!accountId) return <p className="text-sm text-fg-dim">Pick a Creator first.</p>;
  if (q.isError) return <p className="text-sm text-err">Couldn&apos;t load this Creator&apos;s purchase message.</p>;
  if (!q.data) return <p className="text-sm text-fg-dim">Loading…</p>;
  return <Form accountId={accountId} initial={q.data.config} />;
}

function Form({ accountId, initial }: { accountId: string; initial: PurchaseFollowupConfig }) {
  const save = useSavePurchaseFollowupConfig(accountId);
  const [enabled, setEnabled] = useState(initial.enabled);
  const [text, setText] = useState(initial.text || PURCHASE_TEMPLATE);
  const [opened] = useState<ExtrasDraft>(() => extrasDraft(initial));
  const [extras, setExtras] = useState<ExtrasDraft>(opened);
  const collected = collectExtras(extras, { delay: true, frequency: true, initial: opened });
  const problem = typeof collected === "string" ? collected : null;
  const missingText = enabled && !text.trim();

  return (
    <form
      className="space-y-4"
      onSubmit={(e) => {
        e.preventDefault();
        if (!missingText && typeof collected !== "string") save.mutate({ enabled, text: text.trim(), ...collected });
      }}
    >
      <div>
        <h3 className="text-base font-semibold">Message on purchase</h3>
        <p className="text-sm text-fg-dim">
          Sends this message to a fan who unlocks a PPV after you turn this on, once the delay below has passed:
          once ever, or every time but at most once in 2 hours however many he unlocks. A purchase still unanswered
          a day after its delay ran out is dropped. Skip-listed, paused and blacklisted fans are left out. Use {"{name}"} for the fan&apos;s name. Only
          the owner can turn it on.
        </p>
      </div>
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
        On
      </label>
      <div className="space-y-1">
        <label htmlFor="pf-text" className="block text-sm">Message</label>
        <Textarea
          id="pf-text"
          value={text}
          maxLength={1000}
          onChange={(e) => setText(e.target.value)}
          className="font-sans text-sm"
        />
      </div>
      <SmartMessageFields
        accountId={accountId}
        id="pf"
        draft={extras}
        onChange={(patch) => setExtras((d) => ({ ...d, ...patch }))}
        delay
        frequency
      />
      {problem && <p className="text-sm text-warn">{problem}</p>}
      {missingText && <p className="text-sm text-warn">Write a message to turn this on.</p>}
      {save.isError && <p className="text-sm text-err">Couldn&apos;t save: {save.error.message}</p>}
      {save.isSuccess && !save.isPending && <p className="text-sm text-fg-dim">Saved.</p>}
      <Button type="submit" variant="primary" size="sm" disabled={missingText || !!problem || save.isPending}>
        {save.isPending ? "Saving…" : "Save"}
      </Button>
    </form>
  );
}
