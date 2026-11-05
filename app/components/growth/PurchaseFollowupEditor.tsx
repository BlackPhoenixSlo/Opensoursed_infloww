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

import { useId, useState } from "react";

import { IfButton, IfHelp, IfLabel, IfLearn, IfSwitch, IfTextArea } from "@/components/ui/infloww";
import { EditorFooter } from "@/components/ui/ifModal";
import {
  usePurchaseFollowupConfig, useSavePurchaseFollowupConfig, type PurchaseFollowupConfig,
} from "@/hooks/usePurchaseFollowupConfig";

import { SmartMessageFields, collectExtras, extrasDraft, type ExtrasDraft } from "./SmartMessageFields";

/** The first of Infloww's default scripts for "Fan purchases PPV"
 *  (`resetTemplateDefaultData`, index.9f50f370.js @14445308), verbatim. */
export const PURCHASE_TEMPLATE = "Thanks for your purchase, {name}! You're in for a treat!";

export default function PurchaseFollowupEditor({ accountId }: { accountId: string | null }) {
  const q = usePurchaseFollowupConfig(accountId);
  if (!accountId) return <p className="text-[14px] text-fg-dim">Pick a Creator first.</p>;
  if (q.isError) return <p className="text-[14px] text-err">Couldn&apos;t load this Creator&apos;s purchase message.</p>;
  if (!q.data) return <p className="text-[14px] text-fg-dim">Loading…</p>;
  return <Form accountId={accountId} initial={q.data.config} />;
}

function Form({ accountId, initial }: { accountId: string; initial: PurchaseFollowupConfig }) {
  // One per mounted editor: the footer's Save (outside the form) submits this one.
  const formId = useId();
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
      id={formId}
      className="space-y-4 text-[14px]"
      onSubmit={(e) => {
        e.preventDefault();
        if (!missingText && typeof collected !== "string") save.mutate({ enabled, text: text.trim(), ...collected });
      }}
    >
      <div className="flex items-center justify-between gap-4">
        <h3 className="text-[14px] font-medium text-fg">Message on purchase</h3>
        <IfLearn tip={<>
          Sends this message to a fan who unlocks a PPV after you turn this on, once the delay below has passed:
          once ever, or every time but at most once in 2 hours however many he unlocks. A purchase still unanswered
          a day after its delay ran out is dropped. Skip-listed, paused and blacklisted fans are left out. Only
          the owner can turn it on.
        </>} />
      </div>
      <IfSwitch label="On" checked={enabled} onChange={setEnabled} />
      <div>
        <IfLabel htmlFor="pf-text">Message</IfLabel>
        <IfTextArea
          id="pf-text"
          value={text}
          maxLength={1000}
          rows={4}
          onChange={(e) => setText(e.target.value)}
        />
        <IfHelp>Use {"{name}"} for the fan&apos;s name.</IfHelp>
      </div>
      <SmartMessageFields
        accountId={accountId}
        id="pf"
        draft={extras}
        onChange={(patch) => setExtras((d) => ({ ...d, ...patch }))}
        delay
        frequency
      />
      {problem && <p className="text-warn">{problem}</p>}
      {missingText && <p className="text-warn">Write a message to turn this on.</p>}
      {save.isError && <p className="text-err">Couldn&apos;t save: {save.error.message}</p>}
      <EditorFooter>
        {save.isSuccess && !save.isPending && <span className="mr-auto text-fg-dim">Saved.</span>}
        <IfButton type="submit" form={formId} variant="primary" disabled={missingText || !!problem || save.isPending}>
          {save.isPending ? "Saving…" : "Save"}
        </IfButton>
      </EditorFooter>
    </form>
  );
}
