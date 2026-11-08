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
 * (`WELCOME_CREATE_DEFAULTS`, delayedWelcomeForm.ts), switched off unless the owner ticks Enabled,
 * with Infloww's 2～5 minute delay for a new welcome (`resetTemplateDefaultData`,
 * index.9f50f370.js @14443789). The media, price and Auto-unsend go out with
 * the message only: left empty, the Brain's welcome keeps its own image.
 */

import { useReducer } from "react";

import { unsaved } from "@/components/automations/sentDraft";
import { VariantsField } from "@/components/compose/VariantsField";
import { IfHelp, IfInput, IfLearn, IfSwitch, SaveRow, saveVerdict } from "@/components/ui/infloww";
import { EditorFooter } from "@/components/ui/ifModal";
import { useAutomationRules, useSaveRule, type AutomationRule } from "@/hooks/useAutomations";

import {
  buildSave, initWelcomeState, mergeTarget, welcomeIssues, welcomeReducer, type WelcomeDraft, type WelcomeEdit,
} from "./delayedWelcomeForm";
import { MAX_VARIANTS, TEXT_MAX } from "./lifecycleForm";
import { FollowUpsField } from "./LifecycleMessageEditor";
import { SmartMessageFields } from "./SmartMessageFields";

export function DelayedWelcomeEditor({ accountId, onTouched }: {
  accountId: string | null;
  /** Called on each user edit (the dialog's Escape gate). */
  onTouched: () => void;
}) {
  const rulesQ = useAutomationRules(accountId);
  const live = (rulesQ.data ?? []).find((r) => r.kind === "send_welcome" && r.account_id === accountId) ?? null;
  if (rulesQ.isLoading) return <p className="text-[14px] text-fg-dim">Loading…</p>;
  return <Form accountId={accountId} live={live} onTouched={onTouched} />;
}

function Form({ accountId, live, onTouched }: {
  accountId: string | null;
  /** The rule as the cache reads it (null: none, or its read failed). */
  live: AutomationRule | null;
  onTouched: () => void;
}) {
  const save = useSaveRule(accountId);
  const [state, rawDispatch] = useReducer(welcomeReducer, live, initWelcomeState);
  // A newer read (a refetch, another tab, the first read after a failed one, the rule deleted) goes to the reducer:
  // an untouched form follows it, an edit stays. Held while a save runs, so the draft it sent is not replaced unseen.
  if (live !== state.live && !save.isPending) rawDispatch({ type: "live", rule: live });
  // What a save merges into (null = create it).
  const rule = mergeTarget(state);
  const { draft } = state;
  // Every edit is the user's: it tells the dialog (its Escape gate) and clears the last save's line, but not while
  // that save runs (Save stays disabled; on land the edit stays and "Saved" stays off: `unsaved`).
  const dispatch = (a: WelcomeEdit) => {
    onTouched();
    rawDispatch(a);
    if (!save.isPending) save.reset();
  };
  const edit = (patch: Partial<Omit<WelcomeDraft, "extras">>) => dispatch({ type: "patch", patch });
  const { enabled, minutes, afterOf, extras } = draft;
  const { problem, invalid } = welcomeIssues(draft);

  function submit() {
    const req = accountId ? buildSave(draft, rule, accountId) : null;
    if (!req) return;
    rawDispatch({ type: "saved" });
    save.mutate(req, {
      onSuccess: (r) => rawDispatch({ type: "landed", rule: r }),
      onError: () => rawDispatch({ type: "failed" }),
    });
  }

  return (
    <div className="space-y-4 text-[14px]">
      <div className="flex items-center justify-between gap-4">
        <p className="text-fg-dim">
          Sends every new subscriber one welcome.
          {!rule && " This Creator has none yet: Save creates it."}
        </p>
        <IfLearn tip={<>
          Write the welcome below; use {"{name}"} for the fan&apos;s name. Left empty, it sends the welcome set up in
          Brain. The media, price and Auto-unsend go out with your message; the welcome set up in Brain keeps its own
          image. The delay counts from the subscribe, checked as often as set here.
        </>} />
      </div>
      <div className="flex flex-wrap items-center gap-6">
        <IfSwitch label="Enabled" checked={enabled} onChange={(on) => edit({ enabled: on })} />
        <label className="flex items-center gap-2">
          <span>Check every (minutes)</span>
          <IfInput
            type="number"
            min={1}
            value={String(minutes)}
            onChange={(e) => edit({ minutes: Math.max(1, Number(e.target.value) || 1) })}
            className="w-20"
          />
        </label>
      </div>
      <IfHelp className="-mt-2">A new fan is welcomed within this many minutes.</IfHelp>
      {/* Infloww's editor placeholder (index.9f50f370.js @15332026). */}
      <VariantsField
        id="dw-message"
        label="Message"
        variants={draft.variants}
        placeholder="Enter your message..."
        max={MAX_VARIANTS}
        maxLength={TEXT_MAX}
        onChange={(variants) => edit({ variants })}
      />

      {accountId && (
        <SmartMessageFields
          accountId={accountId}
          id="dw"
          draft={extras}
          onChange={(patch) => dispatch({ type: "patchExtras", patch })}
          delay
        />
      )}
      {problem && <p className="text-warn">{problem}</p>}

      <FollowUpsField id="dw-fu" steps={draft.followUps} onChange={(followUps) => edit({ followUps })} />
      <div>
        <IfSwitch label="OnlyFans' welcome message is message 1: while it is on, send only the follow-ups"
          checked={afterOf} onChange={(on) => edit({ afterOf: on })} />
        {afterOf && (
          <IfHelp>
            Checked once per run on OnlyFans; while it is off or empty, the welcome above goes out as usual.
            {!draft.followUps.some((f) => f.text.trim()) && " With no follow-up, a fan OnlyFans welcomes gets nothing from us."}
          </IfHelp>
        )}
      </div>

      <EditorFooter>
        <SaveRow onSave={submit} disabled={!accountId || !!problem || invalid}
          save={saveVerdict(save, !unsaved(state))} />
      </EditorFooter>
    </div>
  );
}
