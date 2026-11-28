"use client";


import { useReducer } from "react";

import { unsaved } from "@/components/automations/sentDraft";
import { VariantsField } from "@/components/compose/VariantsField";
import { IfHelp, IfInput, IfLearn, IfSwitch, SaveRow, saveVerdict } from "@/components/ui/infloww";
import { EditorFooter } from "@/components/ui/ifModal";
import { useAutomationRules, useSaveRule, type AutomationRule } from "@/hooks/useAutomations";
import { useAccountPlatform } from "@/hooks/useCan";
import { PLATFORM_NAME, useFallbackPlatform } from "@/lib/platform";

import {
  afterOfDisabled, buildSave, initWelcomeState, mergeTarget, welcomeIssues, welcomePlatformCopy,
  welcomeReducer, type WelcomeDraft, type WelcomeEdit,
} from "./delayedWelcomeForm";
import { MAX_VARIANTS, TEXT_MAX } from "./lifecycleForm";
import { FollowUpsField } from "./LifecycleMessageEditor";
import { SmartMessageFields } from "./SmartMessageFields";

export function DelayedWelcomeEditor({ accountId, onTouched }: {
  accountId: string | null;
  onTouched: () => void;
}) {
  const rulesQ = useAutomationRules(accountId);
  const live = (rulesQ.data ?? []).find((r) => r.kind === "send_welcome" && r.account_id === accountId) ?? null;
  if (rulesQ.isLoading) return <p className="text-[14px] text-fg-dim">Loading…</p>;
  return <Form accountId={accountId} live={live} onTouched={onTouched} />;
}

function Form({ accountId, live, onTouched }: {
  accountId: string | null;
  live: AutomationRule | null;
  onTouched: () => void;
}) {
  const save = useSaveRule(accountId);
  const fallback = useFallbackPlatform();
  const platform = useAccountPlatform(accountId) ?? fallback;
  const name = PLATFORM_NAME[platform];
  const { refusal, afterLabel } = welcomePlatformCopy(platform);
  const [state, rawDispatch] = useReducer(welcomeReducer, live, initWelcomeState);
  if (live !== state.live && !save.isPending) rawDispatch({ type: "live", rule: live });
  // A save PATCHes the payload merged: a PATCH replaces it whole, so the rule's other knobs would be lost.
  const rule = mergeTarget(state);
  const { draft } = state;
  const dispatch = (a: WelcomeEdit) => {
    onTouched();
    rawDispatch(a);
    if (!save.isPending) save.reset();
  };
  const edit = (patch: Partial<Omit<WelcomeDraft, "extras">>) => dispatch({ type: "patch", patch });
  const { enabled, minutes, afterOf, extras } = draft;
  const { problem, invalid, refused } = welcomeIssues(draft, refusal);

  function submit() {
    const req = accountId ? buildSave(draft, rule, accountId, refusal) : null;
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
        <IfSwitch label={afterLabel}
          checked={afterOf} disabled={afterOfDisabled(draft, refusal)} onChange={(on) => edit({ afterOf: on })} />
        {refusal && <p className="text-warn">{refusal}</p>}
        {afterOf && !refusal && (
          <IfHelp>
            Checked once per run on {name}; while it is off or empty, the welcome above goes out as usual.
            {!draft.followUps.some((f) => f.text.trim()) && ` With no follow-up, a fan ${name} welcomes gets nothing from us.`}
          </IfHelp>
        )}
      </div>

      <EditorFooter>
        <SaveRow onSave={submit} disabled={!accountId || !!problem || invalid || refused}
          save={saveVerdict(save, !unsaved(state))} />
      </EditorFooter>
    </div>
  );
}
