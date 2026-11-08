"use client";

/**
 * The editor for Smart Messages' lifecycle Triggers: Nearing expiry, Expired,
 * Resubscribe and Birthday (Infloww's SmartMessageAutoRulesType 5-8). Each is
 * one on/off, up to 10 messages and, for the two expiry Triggers, Infloww's
 * "[N] hour(s)" (Nearing expiry 1..120, Expired 12..120, default 24), saved
 * through `/admin/lifecycle-message-config`. Off by default; with nothing
 * saved, the message starts as Infloww's own default script for the Trigger.
 * Each fan gets one message and one of its variants at random; a message may
 * carry follow-ups that stop once the fan replies and, on Nearing expiry only,
 * a renewal discount set before it goes out (the Relay refuses more than
 * OnlyFans grants for the page's price). The Smart Message settings
 * (`SmartMessageFields`: media and price, Frequency, Effective / Expiry,
 * Auto-unsend) save with it and go out with whichever message is sent.
 * Infloww's "after delay" option is not wired. On a free page the three
 * Triggers Infloww keeps for paid pages cannot be switched on. Below the form:
 * the fans it reached who then bought. `FollowUpsField` is shared with the
 * Delayed welcome editor.
 */

import { useId, useReducer } from "react";

import { VariantsField } from "@/components/compose/VariantsField";
import { IF_TABLE, IfButton, IfHelp, IfInput, IfLearn, IfNativeSelect, IfSwitch, IfTextArea, SaveRow, saveVerdict } from "@/components/ui/infloww";
import { EditorFooter } from "@/components/ui/ifModal";
import {
  useLifecycleMessageBuyers, useLifecycleMessageConfig, useSaveLifecycleMessageConfig,
  type LifecycleKind, type LifecycleMessageConfig,
} from "@/hooks/useLifecycleMessageConfig";
import { useFreePageRefusal } from "@/hooks/usePaidPage";
import { fmtCents } from "@/lib/format";
import { cn } from "@/lib/utils";

import {
  FOLLOW_UP_DELAY_MAX as DELAY_MAX, MAX_VARIANTS, TEXT_MAX, badDelay, badMonths, buildPayload, initLifecycle, lifecycleIssues, lifecycleReducer,
  type FollowUpDraft, type LifecycleAction, type MessageDraft,
} from "./lifecycleForm";
import { SmartMessageFields } from "./SmartMessageFields";

// The Relay's bounds (automations/lifecycle_messages.py).
const MAX_MESSAGES = 10;
const MAX_FOLLOW_UPS = 5;
const DISCOUNT_PERCENTS = Array.from({ length: 12 }, (_, i) => (i + 1) * 5);

/** Infloww's `isPaidAutoRules` (index.9f50f370.js @14441992): refused on a free page. */
export const PAID_ONLY_KINDS: ReadonlySet<LifecycleKind> = new Set<LifecycleKind>([
  "expiry_message", "expired_message", "resubscribe_message",
]);

interface Copy {
  title: string;
  blurb: string;
  /** Infloww's default script for the Trigger, verbatim: the first of its
   *  random picks (`resetTemplateDefaultData`, index.9f50f370.js @14445781,
   *  @14446277, @14446639, @14447069). */
  example: string;
  /** The rule sentence around N, for the two Triggers that have one. */
  hours?: { before: string; after: string; min: number; max: number };
}

export const LIFECYCLE_COPY: Record<LifecycleKind, Copy> = {
  expiry_message: {
    title: "Nearing expiry",
    blurb: "Sends this message to a fan whose subscription ends within the hours below and is not set to renew: once ever, or once for every subscription that nears its end.",
    example: "Hey, {name}! I think your subscription is about to end.. And I would hate it if you miss out on our latest content!",
    // The bundle's rule label, with its U+2019 (ruleOptions, @14775371).
    hours: { before: "Fan’s subscription near expiry within", after: "hour(s)", min: 1, max: 120 },
  },
  expired_message: {
    title: "Expired",
    blurb: "Sends this message to a fan whose subscription ended, the hours below after it ended: once ever, or once every time one ends.",
    example: "I miss you, {name}! Please renew your subscription to rejoin the fun!",
    hours: { before: "Fan’s subscription expired", after: "hour(s) ago", min: 12, max: 120 },
  },
  resubscribe_message: {
    title: "Resubscribe",
    blurb: "Sends this message to a fan who subscribes again after his subscription lapsed: once ever, or on every return.",
    example: "Welcome back, {name}! We're thrilled to have you again!",
  },
  birthday_message: {
    title: "Birthday",
    blurb: "Sends this message to a fan on his birthday (the Birthday in his Fan insights): once ever, or every year.",
    example: "It's your special day, {name}! Have a fantastic birthday!",
  },
};

export default function LifecycleMessageEditor({ accountId, kind, onTouched }: {
  accountId: string | null; kind: LifecycleKind;
  /** Called on each user edit (the dialog's Escape gate). */
  onTouched: () => void;
}) {
  const q = useLifecycleMessageConfig(accountId, kind);
  if (!accountId) return <p className="text-[14px] text-fg-dim">Pick a Creator first.</p>;
  if (q.isError) return <p className="text-[14px] text-err">Couldn&apos;t load this Creator&apos;s message.</p>;
  if (!q.data) return <p className="text-[14px] text-fg-dim">Loading…</p>;
  return <Form key={kind} accountId={accountId} kind={kind} initial={q.data.config} onTouched={onTouched} />;
}

export function FollowUpsField({ id, steps, onChange }: {
  id: string; steps: FollowUpDraft[]; onChange: (s: FollowUpDraft[]) => void;
}) {
  const set = (i: number, patch: Partial<FollowUpDraft>) =>
    onChange(steps.map((f, j) => (j === i ? { ...f, ...patch } : f)));
  return (
    <div className="space-y-2">
      {steps.map((f, i) => (
        <div key={i} className="space-y-2 rounded-md border border-border p-3">
          <div className="flex flex-wrap items-center gap-2">
            <label htmlFor={`${id}-${i}-delay`}>Follow-up {i + 1}, if no reply after</label>
            <IfInput
              id={`${id}-${i}-delay`}
              type="number"
              min={1}
              max={DELAY_MAX}
              value={f.delay}
              onChange={(e) => set(i, { delay: e.target.value })}
              className="w-[90px]"
            />
            <span>minute(s)</span>
            <IfButton variant="link" className="ml-auto" onClick={() => onChange(steps.filter((_, j) => j !== i))}>
              Remove
            </IfButton>
          </div>
          <IfTextArea
            aria-label={`Follow-up ${i + 1}`}
            value={f.text}
            maxLength={TEXT_MAX}
            rows={2}
            onChange={(e) => set(i, { text: e.target.value })}
          />
          {badDelay(f) && <p className="text-warn">The delay is a whole number of minutes from 1 to {DELAY_MAX}.</p>}
        </div>
      ))}
      {steps.length < MAX_FOLLOW_UPS && (
        <IfButton variant="link" onClick={() => onChange([...steps, { text: "", delay: "60" }])}>
          Add follow-up
        </IfButton>
      )}
      <IfHelp className="mt-0">Each follow-up waits its delay after the one before; a reply stops the rest.</IfHelp>
    </div>
  );
}

function Form({ accountId, kind, initial, onTouched }: {
  accountId: string; kind: LifecycleKind; initial: LifecycleMessageConfig; onTouched: () => void;
}) {
  // One per mounted editor: the footer's Save (outside the form) submits this one.
  const formId = useId();
  const copy = LIFECYCLE_COPY[kind];
  const save = useSaveLifecycleMessageConfig(accountId, kind);
  const freeRefusal = useFreePageRefusal(accountId);
  const refusal = PAID_ONLY_KINDS.has(kind) ? freeRefusal : null;
  const [draft, rawDispatch] = useReducer(lifecycleReducer, undefined, () => initLifecycle(initial, copy.example));
  // Every action is the user's: each one tells the dialog (its Escape gate).
  const dispatch = (a: LifecycleAction) => { onTouched(); rawDispatch(a); };
  const { enabled, messages, hours, extras } = draft;
  const rules = { hours: copy.hours, refusal };
  const { problem, badHours, missingText } = lifecycleIssues(draft, rules);
  const payload = buildPayload(draft, rules);
  const id = `lm-${kind}`;
  const setMessage = (i: number, patch: Partial<MessageDraft>) => dispatch({ type: "patchMessage", i, patch });

  return (
    <div className="space-y-6 text-[14px]">
      <form
        id={formId}
        className="space-y-4"
        onSubmit={(e) => {
          e.preventDefault();
          if (payload) save.mutate(payload);
        }}
      >
        <div className="flex items-center justify-between gap-4">
          <h3 className="text-[14px] font-medium text-fg">{copy.title}</h3>
          <IfLearn tip={<>
            {copy.blurb} Fans whose moment came before you turned this on are not chased. Skip-listed, paused and
            blacklisted fans are left out. Use {"{name}"} for the fan&apos;s name. Only the owner can turn it on.
            {kind === "expired_message" && (
              " The fan is followed first, unless his profile is paid. OnlyFans may still refuse a message to a fan"
              + " whose subscription ended."
            )}
          </>} />
        </div>
        {/* On a free page it can be switched off, never on. */}
        <IfSwitch label="On" checked={enabled} disabled={!!refusal && !enabled} onChange={(on) => dispatch({ type: "setEnabled", on })} />
        {refusal && <p className="text-warn">{refusal}</p>}
        {copy.hours && (
          <div className="flex flex-wrap items-center gap-2">
            <label htmlFor={`${id}-hours`}>{copy.hours.before}</label>
            <IfInput
              id={`${id}-hours`}
              type="number"
              min={copy.hours.min}
              max={copy.hours.max}
              value={hours}
              onChange={(e) => dispatch({ type: "setHours", hours: e.target.value })}
              className="w-[90px]"
            />
            <span>{copy.hours.after}</span>
          </div>
        )}
        {messages.map((m, i) => (
          <div key={i} className="space-y-4 rounded-md border border-border p-4">
            <div className="flex items-center justify-between">
              <span className="font-medium">Message {i + 1}</span>
              {messages.length > 1 && (
                <IfButton variant="link" onClick={() => dispatch({ type: "removeMessage", i })}>
                  Remove message
                </IfButton>
              )}
            </div>
            <VariantsField
              id={i ? `${id}-${i}-text` : `${id}-text`}
              label="Message"
              variants={m.variants}
              placeholder={copy.example}
              max={MAX_VARIANTS}
              maxLength={TEXT_MAX}
              onChange={(variants) => setMessage(i, { variants })}
            />
            <FollowUpsField id={`${id}-${i}-fu`} steps={m.followUps} onChange={(followUps) => setMessage(i, { followUps })} />
            {kind === "expiry_message" && (
              <div className="flex flex-wrap items-center gap-2">
                <IfSwitch label="Give a renewal discount of" checked={!!m.discount}
                  onChange={(on) => setMessage(i, { discount: on ? { percent: 10, months: "1" } : null })} />
                <IfNativeSelect
                  aria-label="Discount percent"
                  value={m.discount?.percent ?? 10}
                  disabled={!m.discount}
                  onChange={(e) => m.discount && setMessage(i, { discount: { ...m.discount, percent: Number(e.target.value) } })}
                >
                  {DISCOUNT_PERCENTS.map((p) => <option key={p} value={p}>{p}%</option>)}
                </IfNativeSelect>
                <span>for</span>
                <IfInput
                  aria-label="Discount months"
                  type="number"
                  min={1}
                  max={12}
                  value={m.discount?.months ?? "1"}
                  disabled={!m.discount}
                  onChange={(e) => m.discount && setMessage(i, { discount: { ...m.discount, months: e.target.value } })}
                  className="w-[70px]"
                />
                <span>month(s), set just before the message goes out</span>
                {badMonths(m) && <p className="w-full text-warn">The discount runs 1 to 12 months.</p>}
              </div>
            )}
          </div>
        ))}
        {messages.length < MAX_MESSAGES && (
          <div>
            <IfButton variant="link" onClick={() => dispatch({ type: "addMessage" })}>
              Add message
            </IfButton>
            {messages.length > 1 && <IfHelp className="mt-0">Each fan gets one message at random.</IfHelp>}
          </div>
        )}
        <SmartMessageFields
          accountId={accountId}
          id={id}
          draft={extras}
          onChange={(patch) => dispatch({ type: "patchExtras", patch })}
          frequency
        />
        {problem && <p className="text-warn">{problem}</p>}
        {badHours && copy.hours && (
          <p className="text-warn">Hours must be a whole number from {copy.hours.min} to {copy.hours.max}.</p>
        )}
        {missingText && <p className="text-warn">Write a message to turn this on.</p>}
        <EditorFooter>
          <SaveRow form={formId} disabled={!payload} save={saveVerdict(save)} />
        </EditorFooter>
      </form>
      <Buyers accountId={accountId} kind={kind} />
    </div>
  );
}

function Buyers({ accountId, kind }: { accountId: string; kind: LifecycleKind }) {
  const q = useLifecycleMessageBuyers(accountId, kind);
  return (
    <section>
      <h4 className="font-medium">Buyers</h4>
      {q.isError && <p className="text-err">Couldn&apos;t load the buyers.</p>}
      {q.data && (
        <>
          <IfHelp className="mb-3">
            Fans this Trigger messaged who bought within {q.data.window_days} days of it (latest 200).
          </IfHelp>
          {q.data.buyers.length === 0 ? (
            <p className="text-fg-dim">No buyers yet.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className={IF_TABLE.table}>
                <thead>
                  <tr>
                    {["Fan", "Message", "Spent", "Purchases", "Last purchase"].map((h) => (
                      <th key={h} className={cn(IF_TABLE.th, IF_TABLE.thDivider)}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {q.data.buyers.map((b) => (
                    <tr key={`${b.fan_id}-${b.sent_at}`} className={IF_TABLE.row}>
                      <td className={IF_TABLE.td}>{b.name || (b.username ? `@${b.username}` : b.fan_id)}</td>
                      <td className={IF_TABLE.td}>{b.message}</td>
                      <td className={IF_TABLE.td}>{fmtCents(b.spent_cents)}</td>
                      <td className={IF_TABLE.td}>{b.purchases}</td>
                      <td className={IF_TABLE.td}>{new Date(b.last_purchase_at).toLocaleDateString()}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </section>
  );
}
