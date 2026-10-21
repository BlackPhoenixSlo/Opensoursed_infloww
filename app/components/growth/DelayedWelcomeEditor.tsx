"use client";

/**
 * The Delayed welcome editor on Smart Messages (ticket 43, rebound by the
 * owner's ruling of 2026-10-18, Phase 2 N1): our `send_welcome` automation,
 * not OnlyFans' own welcome slot.
 *
 * It edits the rule's on/off, its cadence, its `message` and the message's
 * Smart Message settings (`SmartMessageFields`: media and price, Infloww's
 * random "after delay", Effective / Expiry, Auto-unsend; no Frequency, a fan
 * is welcomed once). The cadence (`every_seconds`) is how often `send_welcome` checks
 * for new subscribers, so a new fan is welcomed within that many minutes. The
 * message, when set, is the whole welcome: one DM, `{name}` filled with the
 * fan's name; with several variants each fan gets one at random (`message`
 * is then their list); left empty, the rule sends the welcome the Brain's
 * welcome lane shapes. The Smart Messages extras (06 P3): follow-ups that stop
 * once the fan replies, and "OnlyFans' welcome is message 1" (while OnlyFans'
 * own welcome is on, the rule sends no welcome, only the follow-ups; while it
 * is off, the rule's welcome goes out as usual). Saving an existing rule
 * PATCHes those fields and writes the payload back MERGED (a PATCH replaces
 * the whole payload), so every other knob (the question, the GIF, the pacing
 * and the follow-back) stays as the Brain set it.
 * With no rule yet, Save creates the one the old Brain welcome lane created
 * (`WELCOME_CREATE_DEFAULTS` below), switched off unless the owner ticks Enabled,
 * with Infloww's 2～5 minute delay for a new welcome (`resetTemplateDefaultData`,
 * index.9f50f370.js @14443789). The media, price and Auto-unsend go out with
 * the message only: left empty, the Brain's welcome keeps its own image.
 */

import { useState } from "react";

import { Button, Input } from "@/components/ui/primitives";
import { useAutomationRules, useCreateRule, useUpdateRule } from "@/hooks/useAutomations";

import {
  FollowUpsField, VariantsField, badDelay, cleanFollowUps, type FollowUpDraft,
} from "./LifecycleMessageEditor";
import {
  SmartMessageFields, collectExtras, extrasDraft, extrasOfPayload, type ExtrasDraft,
} from "./SmartMessageFields";

/** The welcome rule's default cadence: poll OF's new-subscriber feed every
 *  5 min (the send_welcome spec's {every_seconds: 300}). */
const WELCOME_DEFAULT_EVERY_S = 300;

/** Default 3rd-bubble question, stamped at rule creation (the sender treats an
 *  absent key as off, so older rules don't change; "" is explicitly off). */
const WELCOME_QUESTION_DEFAULT = "what's yours?";

/** The six welcome booleans a brand-new rule is born with. They mirror the
 *  relay catalog's `default` for each key (`automation_rules_api`'s
 *  send_welcome entry; `case_every_catalogued_bool_honours_its_default` holds
 *  the two sides together). `time_only: true` is a creation default only: the
 *  sender reads an absent `time_only` as off on purpose (C-N7). `follow_back`
 *  and `follow_back_gate` drive a money-spending lane, not a bubble. */
const WELCOME_CREATE_DEFAULTS = {
  time_only: true,
  skip_time_bubble: false,
  human_pace: true,
  stop_on_reply: true,
  follow_back: true,
  follow_back_gate: true,
};

/** Infloww's delay for a new welcome: 2～5 minutes. */
const WELCOME_DELAY: [number, number] = [2, 5];

type Draft = { enabled: boolean; minutes: number; variants: string[]; followUps: FollowUpDraft[]; afterOf: boolean };

export function DelayedWelcomeEditor({ accountId }: { accountId: string | null }) {
  const rulesQ = useAutomationRules(accountId);
  const rule = (rulesQ.data ?? []).find((r) => r.kind === "send_welcome" && r.account_id === accountId) ?? null;
  const create = useCreateRule(accountId);
  const update = useUpdateRule(accountId);

  // The form shows the rule (or, with none, the Brain's defaults) until the
  // owner edits it; a successful save drops the edit so the saved rule shows.
  const [draft, setDraft] = useState<Draft | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [extrasEdit, setExtrasEdit] = useState<ExtrasDraft | null>(null);
  const stored = rule?.payload ?? {};
  const saved = stored.message;
  const savedVariants = (Array.isArray(saved) ? saved : [saved]).filter((v): v is string => typeof v === "string");
  const savedSteps = Array.isArray(stored.follow_ups) ? stored.follow_ups as { text?: unknown; delay_minutes?: unknown }[] : [];
  const cur: Draft = draft ?? {
    enabled: rule?.is_enabled ?? false,
    minutes: Math.max(1, Math.round((rule?.every_seconds ?? WELCOME_DEFAULT_EVERY_S) / 60)),
    variants: savedVariants.length ? savedVariants : [""],
    followUps: savedSteps.map((f) => ({ text: String(f.text ?? ""), delay: String(f.delay_minutes ?? "") })),
    afterOf: stored.after_of_welcome === true,
  };
  const { enabled, minutes, afterOf } = cur;
  const edit = (patch: Partial<Draft>) => {
    setDraft({ ...cur, ...patch });
    setMsg(null);
  };
  const extras = extrasEdit ?? extrasDraft(
    rule ? extrasOfPayload(rule.payload) : { delay_range: WELCOME_DELAY }, WELCOME_DELAY);
  const collected = collectExtras(extras, { delay: true });
  const problem = typeof collected === "string" ? collected : null;
  const invalid = cur.followUps.some(badDelay);
  const saving = create.isPending || update.isPending;

  async function save() {
    if (!accountId || typeof collected === "string" || invalid) return;
    setMsg(null);
    const every_seconds = Math.max(60, Math.round(minutes * 60));
    const variants = cur.variants.map((v) => v.trim()).filter(Boolean);
    const followUps = cleanFollowUps(cur.followUps);
    // One text stays a string; several are the variants' list. The follow-up
    // knobs are written once used, so a rule that never had them keeps its shape.
    const smart = {
      message: variants.length > 1 ? variants : (variants[0] ?? ""),
      ...(followUps.length || "follow_ups" in stored ? { follow_ups: followUps } : {}),
      ...(afterOf || "after_of_welcome" in stored ? { after_of_welcome: afterOf } : {}),
    };
    try {
      if (rule) {
        await update.mutateAsync({
          id: rule.id, is_enabled: enabled, every_seconds,
          payload: { ...(rule.payload ?? {}), ...smart, ...collected },
        });
      } else {
        await create.mutateAsync({
          account_id: accountId, kind: "send_welcome", name: "Welcome new subscribers",
          every_seconds, is_enabled: enabled,
          payload: {
            ...WELCOME_CREATE_DEFAULTS, question: WELCOME_QUESTION_DEFAULT, gif_id: "", ...smart,
            ...collected,
          },
        });
      }
      setDraft(null);
      setExtrasEdit(null);
      setMsg("Saved.");
    } catch (e) {
      setMsg((e as Error)?.message || "Save failed");
    }
  }

  if (rulesQ.isLoading) return <p className="text-sm text-fg-dim">Loading…</p>;
  return (
    <div className="space-y-3 text-sm">
      <p className="text-fg-dim">
        Sends every new subscriber one welcome. Write it below; use {"{name}"} for the fan&apos;s name. Left empty,
        it sends the welcome set up in Brain.
        {!rule && " This Creator has none yet: Save creates it."}
      </p>
      <div className="flex flex-wrap items-end gap-4">
        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={enabled}
            onChange={(e) => edit({ enabled: e.target.checked })}
            className="accent-accent"
          />
          Enabled
        </label>
        <label className="flex items-center gap-1.5">
          <span>Check every (minutes)</span>
          <Input
            type="number"
            min={1}
            value={String(minutes)}
            onChange={(e) => edit({ minutes: Math.max(1, Number(e.target.value) || 1) })}
            className="!w-20"
          />
        </label>
      </div>
      <p className="text-[11px] text-fg-dim">
        It checks for new subscribers this often, so a new fan is welcomed within this many minutes.
      </p>
      {/* Infloww's editor placeholder (index.9f50f370.js @15332026). */}
      <VariantsField
        id="dw-message"
        label="Message"
        variants={cur.variants}
        placeholder="Enter your message..."
        onChange={(variants) => edit({ variants })}
      />

      {accountId && (
        <SmartMessageFields
          accountId={accountId}
          id="dw"
          draft={extras}
          onChange={(patch) => { setExtrasEdit({ ...extras, ...patch }); setMsg(null); }}
          delay
        />
      )}
      <p className="text-[11px] text-fg-dim">
        The media, price and Auto-unsend go out with your message; the welcome set up in Brain keeps its own image.
        The delay counts from the subscribe, checked as often as above.
      </p>
      {problem && <p className="text-warn">{problem}</p>}

      <FollowUpsField id="dw-fu" steps={cur.followUps} onChange={(followUps) => edit({ followUps })} />
      <label className="flex items-center gap-2">
        <input
          type="checkbox"
          checked={afterOf}
          onChange={(e) => edit({ afterOf: e.target.checked })}
          className="accent-accent"
        />
        OnlyFans&apos; welcome message is message 1: while it is on, send only the follow-ups
      </label>
      {afterOf && (
        <p className="text-[11px] text-fg-dim">
          Checked once per run on OnlyFans. While OnlyFans&apos; welcome message is off or empty, the welcome above goes
          out as usual.
          {!cur.followUps.some((f) => f.text.trim()) && " With no follow-up, a fan OnlyFans welcomes gets nothing from us."}
        </p>
      )}

      <div className="flex items-center gap-3">
        <Button size="sm" variant="primary" onClick={save} disabled={!accountId || saving || !!problem || invalid}>
          {saving ? "Saving…" : "Save"}
        </Button>
        {msg && <span className="text-[11px] text-fg-dim">{msg}</span>}
      </div>
    </div>
  );
}
