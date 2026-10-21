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
 * the fans it reached who then bought. `VariantsField` and `FollowUpsField`
 * are shared with the Delayed welcome editor.
 */

import { useState } from "react";

import { Button, Input, Textarea } from "@/components/ui/primitives";
import {
  useLifecycleMessageBuyers, useLifecycleMessageConfig, useSaveLifecycleMessageConfig,
  type LifecycleKind, type LifecycleMessage, type LifecycleMessageConfig,
} from "@/hooks/useLifecycleMessageConfig";
import { useFreePageRefusal } from "@/hooks/usePaidPage";
import { fmtCents } from "@/lib/format";

import { SmartMessageFields, collectExtras, extrasDraft, type ExtrasDraft } from "./SmartMessageFields";

// The Relay's bounds (automations/lifecycle_messages.py).
const MAX_MESSAGES = 10;
const MAX_VARIANTS = 10;
const MAX_FOLLOW_UPS = 5;
const DELAY_MAX = 7 * 24 * 60;
const DISCOUNT_PERCENTS = Array.from({ length: 12 }, (_, i) => (i + 1) * 5);
const SELECT = "bg-bg border border-border rounded-lg px-3 py-2 text-sm disabled:opacity-50";

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

export default function LifecycleMessageEditor({ accountId, kind }: {
  accountId: string | null; kind: LifecycleKind;
}) {
  const q = useLifecycleMessageConfig(accountId, kind);
  if (!accountId) return <p className="text-sm text-fg-dim">Pick a Creator first.</p>;
  if (q.isError) return <p className="text-sm text-err">Couldn&apos;t load this Creator&apos;s message.</p>;
  if (!q.data) return <p className="text-sm text-fg-dim">Loading…</p>;
  return <Form key={kind} accountId={accountId} kind={kind} initial={q.data.config} />;
}

export interface FollowUpDraft {
  text: string;
  /** Minutes, as typed. */
  delay: string;
}

/** A follow-up's delay is a whole number of minutes from 1 to a week. */
export function badDelay(f: FollowUpDraft): boolean {
  const n = Number(f.delay);
  return !!f.text.trim() && !(Number.isInteger(n) && n >= 1 && n <= DELAY_MAX);
}

/** The typed follow-ups that have text, as the Relay stores them. */
export function cleanFollowUps(steps: FollowUpDraft[]) {
  return steps.filter((f) => f.text.trim()).map((f) => ({ text: f.text.trim(), delay_minutes: Number(f.delay) }));
}

export function VariantsField({ id, label, variants, placeholder, onChange }: {
  id: string; label: string; variants: string[]; placeholder?: string; onChange: (v: string[]) => void;
}) {
  return (
    <div className="space-y-1">
      <label htmlFor={`${id}-0`} className="block text-sm">{label}</label>
      {variants.map((v, i) => (
        <div key={i} className="flex items-start gap-2">
          <Textarea
            id={`${id}-${i}`}
            aria-label={i ? `${label}, variant ${i + 1}` : undefined}
            value={v}
            maxLength={1000}
            placeholder={i === 0 ? placeholder : "Another way to say it"}
            onChange={(e) => onChange(variants.map((x, j) => (j === i ? e.target.value : x)))}
            className="font-sans text-sm"
          />
          {variants.length > 1 && (
            <Button type="button" size="sm" variant="ghost" onClick={() => onChange(variants.filter((_, j) => j !== i))}>
              Remove
            </Button>
          )}
        </div>
      ))}
      <div className="flex items-center gap-3">
        {variants.length < MAX_VARIANTS && (
          <Button type="button" size="sm" variant="secondary" onClick={() => onChange([...variants, ""])}>
            Add variant
          </Button>
        )}
        {variants.length > 1 && <span className="text-[11px] text-fg-dim">Each fan gets one of these at random.</span>}
      </div>
    </div>
  );
}

export function FollowUpsField({ id, steps, onChange }: {
  id: string; steps: FollowUpDraft[]; onChange: (s: FollowUpDraft[]) => void;
}) {
  const set = (i: number, patch: Partial<FollowUpDraft>) =>
    onChange(steps.map((f, j) => (j === i ? { ...f, ...patch } : f)));
  return (
    <div className="space-y-2">
      {steps.map((f, i) => (
        <div key={i} className="space-y-1 rounded-lg border border-border p-2">
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <label htmlFor={`${id}-${i}-delay`}>Follow-up {i + 1}, if no reply after</label>
            <Input
              id={`${id}-${i}-delay`}
              type="number"
              min={1}
              max={DELAY_MAX}
              value={f.delay}
              onChange={(e) => set(i, { delay: e.target.value })}
              className="!w-[90px]"
            />
            <span>minute(s)</span>
            <Button type="button" size="sm" variant="ghost" onClick={() => onChange(steps.filter((_, j) => j !== i))}>
              Remove
            </Button>
          </div>
          <Textarea
            aria-label={`Follow-up ${i + 1}`}
            value={f.text}
            maxLength={1000}
            onChange={(e) => set(i, { text: e.target.value })}
            className="font-sans text-sm"
          />
          {badDelay(f) && <p className="text-sm text-warn">The delay is a whole number of minutes from 1 to {DELAY_MAX}.</p>}
        </div>
      ))}
      {steps.length < MAX_FOLLOW_UPS && (
        <Button type="button" size="sm" variant="secondary" onClick={() => onChange([...steps, { text: "", delay: "60" }])}>
          Add follow-up
        </Button>
      )}
      <p className="text-[11px] text-fg-dim">
        Each follow-up waits its delay after the one before it. Once the fan replies, the rest are not sent.
      </p>
    </div>
  );
}

interface MessageDraft {
  variants: string[];
  followUps: FollowUpDraft[];
  discount: { percent: number; months: string } | null;
}

const toDraft = (m: LifecycleMessage): MessageDraft => ({
  variants: m.variants.length ? m.variants : [""],
  followUps: m.follow_ups.map((f) => ({ text: f.text, delay: String(f.delay_minutes) })),
  discount: m.discount && { percent: m.discount.percent, months: String(m.discount.months) },
});

const EMPTY: MessageDraft = { variants: [""], followUps: [], discount: null };

function badMonths(d: MessageDraft): boolean {
  const n = Number(d.discount?.months);
  return !!d.discount && !(Number.isInteger(n) && n >= 1 && n <= 12);
}

function Form({ accountId, kind, initial }: {
  accountId: string; kind: LifecycleKind; initial: LifecycleMessageConfig;
}) {
  const copy = LIFECYCLE_COPY[kind];
  const save = useSaveLifecycleMessageConfig(accountId, kind);
  const freeRefusal = useFreePageRefusal(accountId);
  const refusal = PAID_ONLY_KINDS.has(kind) ? freeRefusal : null;
  const [enabled, setEnabled] = useState(initial.enabled);
  const [messages, setMessages] = useState<MessageDraft[]>(
    initial.messages?.length ? initial.messages.map(toDraft) : [{ ...EMPTY, variants: [initial.text || copy.example] }]);
  const [hours, setHours] = useState(String(initial.hours ?? 24));
  const [extras, setExtras] = useState<ExtrasDraft>(() => extrasDraft(initial));
  const collected = collectExtras(extras, { frequency: true });
  const problem = typeof collected === "string" ? collected : null;
  const n = Number(hours);
  const badHours = !!copy.hours && !(Number.isInteger(n) && n >= copy.hours.min && n <= copy.hours.max);
  const clean: LifecycleMessage[] = messages
    .map((m) => ({
      variants: m.variants.map((v) => v.trim()).filter(Boolean),
      follow_ups: cleanFollowUps(m.followUps),
      discount: m.discount && { percent: m.discount.percent, months: Number(m.discount.months) },
    }))
    .filter((m) => m.variants.length);
  const missingText = enabled && !clean.length;
  const invalid = messages.some((m) => m.followUps.some(badDelay) || badMonths(m));
  const refused = !!refusal && enabled;
  const id = `lm-${kind}`;
  const setMessage = (i: number, patch: Partial<MessageDraft>) =>
    setMessages(messages.map((m, j) => (j === i ? { ...m, ...patch } : m)));

  return (
    <div className="space-y-6">
      <form
        className="space-y-4"
        onSubmit={(e) => {
          e.preventDefault();
          if (missingText || badHours || invalid || refused || typeof collected === "string") return;
          save.mutate({ enabled, messages: clean, ...(copy.hours ? { hours: n } : {}), ...collected });
        }}
      >
        <div>
          <h3 className="text-base font-semibold">{copy.title}</h3>
          <p className="text-sm text-fg-dim">
            {copy.blurb} Fans whose moment came before you turned this on are not chased. Skip-listed, paused and
            blacklisted fans are left out. Use {"{name}"} for the fan&apos;s name. Only the owner can turn it on.
          </p>
          {kind === "expired_message" && (
            <p className="text-sm text-fg-dim">
              The fan is followed first, unless his profile is paid. OnlyFans may still refuse a message to a fan
              whose subscription ended.
            </p>
          )}
        </div>
        <label className="flex items-center gap-2 text-sm">
          {/* On a free page it can be switched off, never on. */}
          <input
            type="checkbox"
            checked={enabled}
            disabled={!!refusal && !enabled}
            onChange={(e) => setEnabled(e.target.checked)}
          />
          On
        </label>
        {refusal && <p className="text-sm text-warn">{refusal}</p>}
        {copy.hours && (
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <label htmlFor={`${id}-hours`}>{copy.hours.before}</label>
            <Input
              id={`${id}-hours`}
              type="number"
              min={copy.hours.min}
              max={copy.hours.max}
              value={hours}
              onChange={(e) => setHours(e.target.value)}
              className="!w-[90px]"
            />
            <span>{copy.hours.after}</span>
          </div>
        )}
        {messages.map((m, i) => (
          <div key={i} className="space-y-3 rounded-lg border border-border p-3">
            <div className="flex items-center justify-between">
              <span className="text-sm font-semibold">Message {i + 1}</span>
              {messages.length > 1 && (
                <Button type="button" size="sm" variant="ghost" onClick={() => setMessages(messages.filter((_, j) => j !== i))}>
                  Remove message
                </Button>
              )}
            </div>
            <VariantsField
              id={i ? `${id}-${i}-text` : `${id}-text`}
              label="Message"
              variants={m.variants}
              placeholder={copy.example}
              onChange={(variants) => setMessage(i, { variants })}
            />
            <FollowUpsField id={`${id}-${i}-fu`} steps={m.followUps} onChange={(followUps) => setMessage(i, { followUps })} />
            {kind === "expiry_message" && (
              <div className="flex flex-wrap items-center gap-2 text-sm">
                <label className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={!!m.discount}
                    onChange={(e) => setMessage(i, { discount: e.target.checked ? { percent: 10, months: "1" } : null })}
                  />
                  Give a renewal discount of
                </label>
                <select
                  aria-label="Discount percent"
                  value={m.discount?.percent ?? 10}
                  disabled={!m.discount}
                  onChange={(e) => m.discount && setMessage(i, { discount: { ...m.discount, percent: Number(e.target.value) } })}
                  className={SELECT}
                >
                  {DISCOUNT_PERCENTS.map((p) => <option key={p} value={p}>{p}%</option>)}
                </select>
                <span>for</span>
                <Input
                  aria-label="Discount months"
                  type="number"
                  min={1}
                  max={12}
                  value={m.discount?.months ?? "1"}
                  disabled={!m.discount}
                  onChange={(e) => m.discount && setMessage(i, { discount: { ...m.discount, months: e.target.value } })}
                  className="!w-[70px]"
                />
                <span>month(s), set just before the message goes out</span>
                {badMonths(m) && <p className="w-full text-warn">The discount runs 1 to 12 months.</p>}
              </div>
            )}
          </div>
        ))}
        {messages.length < MAX_MESSAGES && (
          <div className="flex items-center gap-3">
            <Button type="button" size="sm" variant="secondary" onClick={() => setMessages([...messages, EMPTY])}>
              Add message
            </Button>
            {messages.length > 1 && <span className="text-[11px] text-fg-dim">Each fan gets one message at random.</span>}
          </div>
        )}
        <SmartMessageFields
          accountId={accountId}
          id={id}
          draft={extras}
          onChange={(patch) => setExtras((d) => ({ ...d, ...patch }))}
          frequency
        />
        {problem && <p className="text-sm text-warn">{problem}</p>}
        {badHours && copy.hours && (
          <p className="text-sm text-warn">Hours must be a whole number from {copy.hours.min} to {copy.hours.max}.</p>
        )}
        {missingText && <p className="text-sm text-warn">Write a message to turn this on.</p>}
        {save.isError && <p className="text-sm text-err">Couldn&apos;t save: {save.error.message}</p>}
        {save.isSuccess && !save.isPending && <p className="text-sm text-fg-dim">Saved.</p>}
        <Button
          type="submit"
          variant="primary"
          size="sm"
          disabled={missingText || badHours || invalid || refused || !!problem || save.isPending}
        >
          {save.isPending ? "Saving…" : "Save"}
        </Button>
      </form>
      <Buyers accountId={accountId} kind={kind} />
    </div>
  );
}

function Buyers({ accountId, kind }: { accountId: string; kind: LifecycleKind }) {
  const q = useLifecycleMessageBuyers(accountId, kind);
  return (
    <section className="space-y-2">
      <h4 className="text-sm font-semibold">Buyers</h4>
      {q.isError && <p className="text-sm text-err">Couldn&apos;t load the buyers.</p>}
      {q.data && (
        <>
          <p className="text-[11px] text-fg-dim">
            Fans this Trigger messaged who bought within {q.data.window_days} days of it (latest 200).
          </p>
          {q.data.buyers.length === 0 ? (
            <p className="text-sm text-fg-dim">No buyers yet.</p>
          ) : (
            <table className="w-full text-sm">
              <thead className="text-left text-fg-dim">
                <tr><th>Fan</th><th>Message</th><th>Spent</th><th>Purchases</th><th>Last purchase</th></tr>
              </thead>
              <tbody>
                {q.data.buyers.map((b) => (
                  <tr key={`${b.fan_id}-${b.sent_at}`}>
                    <td>{b.name || (b.username ? `@${b.username}` : b.fan_id)}</td>
                    <td>{b.message}</td>
                    <td>{fmtCents(b.spent_cents)}</td>
                    <td>{b.purchases}</td>
                    <td>{new Date(b.last_purchase_at).toLocaleDateString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </>
      )}
    </section>
  );
}
