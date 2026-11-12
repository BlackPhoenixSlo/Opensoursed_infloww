"use client";

/**
 * My AI Chatter > Get to know fans (ours). The AI info-gather automation
 * (`welcome_chatter_for_info`, service/automations/welcome_chatter_for_info.py) on a page of its own: the header
 * switch (with its On / Off pill) turns the kind on or off for the creator the moment it flips
 * (`/admin/automation-rules/switch`, which creates its rule from the catalog defaults the first time, else wakes the
 * one there). Its settings (the message cutoff and the closing PPV, the rule's payload) and the engine's Human style
 * boxes (the style blob, as Auto-reply's page shows its own) show whether it is on or off, rule or not, seeded from
 * the rule's payload else the catalog defaults, saved together by one Save; with no rule yet that Save creates it OFF
 * (getToKnowFansForm.ts `ruleSave`). Model info (ModelInfoBlock, also on Auto-reply) is the account's note every chat
 * prompt pins, with its own Save.
 *
 * Model info is for anyone with access to the account. The switch and settings ride the rule routes, which this
 * page does not grant on its own (service/permissions.py PAGE_MAP), so a role without them sees why instead.
 *
 * The rule PATCH sends the STORED payload back with only this page's fields changed (the rule's cadence and dev knobs
 * keep theirs). The style PUT merges, so it sends only the boxes touched here.
 */

import { useReducer, useState } from "react";

import { AiKeyNotice } from "@/components/AiKeyNotice";
import { VaultPicker } from "@/components/chat/VaultPicker";
import { MediaTray } from "@/components/compose/MediaTray";
import {
  FormBlock, NoCreator, useAutomationCreator,
} from "@/components/automations/automationPage";
import { HeaderSwitch } from "@/components/automations/HeaderSwitch";
import { HumanStyleBlock, useHumanStyle, usePageSave } from "@/components/automations/HumanStyleBlock";
import { FormSkeleton, ModelInfoBlock } from "@/components/automations/ModelInfoBlock";
import { unsaved } from "@/components/automations/sentDraft";
import type { CreatorPick } from "@/components/shell/CreatorRail";
import { PageFrame } from "@/components/shell/PageFrame";
import { IfInput, IfLearn, IfTextArea, SaveRow } from "@/components/ui/infloww";
import {
  useAutomationKinds, useAutomationRules, useSaveRule, useSwitchKind, type AutomationKind, type AutomationRule,
} from "@/hooks/useAutomations";
import { VAULT_PICK_MAX } from "@/lib/ofMirrorChatShared";

import { gtkfReducer, initState, invalidReason, limitsOf, ruleSave } from "./getToKnowFansForm";

const TITLE = "Get to know fans";
const KIND = "welcome_chatter_for_info";
const NUMBER = "w-20";
/** The catalog summary when the kinds read has none yet. */
const BLURB = "Chats with fans to learn about them and build their profile, then can send one closing PPV.";

const learn = (tip: string) => (
  <IfLearn tip={tip}><span className="max-sm:sr-only">Learn</span></IfLearn>
);

export default function GetToKnowFansPage() {
  const { accountId, creators, loading } = useAutomationCreator();
  if (!accountId) {
    return <PageFrame title={TITLE} creators={creators} actions={learn(BLURB)}><NoCreator loading={loading} /></PageFrame>;
  }
  // Keyed, so switching creator re-seeds the settings and the Model info box.
  return <GetToKnowFans key={accountId} accountId={accountId} creators={creators} />;
}

function GetToKnowFans({ accountId, creators }: { accountId: string; creators: CreatorPick }) {
  const kindsQ = useAutomationKinds();
  const rulesQ = useAutomationRules(accountId);
  const switchM = useSwitchKind(accountId);

  const rules = (rulesQ.data ?? []).filter((r) => r.kind === KIND);
  // The row the switch keeps on (ensure_kind_rule: the running one, else the oldest).
  const rule = rules.find((r) => r.is_enabled) ?? rules[0] ?? null;
  const on = rules.some((r) => r.is_enabled);
  const meta = kindsQ.data?.find((k) => k.kind === KIND);

  const actions = (
    <>
      {learn(meta?.summary || BLURB)}
      <HeaderSwitch label={TITLE} checked={on} disabled={!rulesQ.isSuccess} loading={switchM.isPending}
        onChange={(enable) => switchM.mutate({ kind: KIND, enable })} />
    </>
  );

  return (
    <PageFrame title={TITLE} creators={creators} actions={actions}>
      <div className="max-w-[720px] space-y-8">
        <AiKeyNotice accountId={accountId} kinds={[KIND]} />

        {rulesQ.isSuccess && (
          <p className="text-[14px] text-fg-dim">
            {on ? "On: it is chatting with fans now." : "Off: nothing is sent. The settings below are kept."}
          </p>
        )}
        {switchM.isError && <p className="text-[12px] text-err">{switchM.error.message}</p>}
        {rulesQ.isLoading || kindsQ.isLoading ? (
          <FormSkeleton />
        ) : rulesQ.isError ? (
          <p className="text-[14px] text-muted">
            {(rulesQ.error as Error)?.message || "Could not load this automation."} Model info below still applies.
          </p>
        ) : !meta ? (
          <p className="text-[14px] text-err">
            {(kindsQ.error as Error)?.message || "Could not load this automation's settings."}
          </p>
        ) : null}

        {/* Once per creator, on or off, rule or not: the switch creating or parking the rule never re-seeds it, and a
            failed refetch (data kept) never unmounts the typed settings. */}
        {rulesQ.data !== undefined && meta && <RuleSettings accountId={accountId} rule={rule} meta={meta} />}

        <ModelInfoBlock accountId={accountId} />
      </div>
    </PageFrame>
  );
}

/** The rule's own settings, seeded once from its payload, else the catalog defaults (getToKnowFansForm.ts), plus the
 *  Human style boxes. */
function RuleSettings({ accountId, rule, meta }: {
  accountId: string; rule: AutomationRule | null; meta: AutomationKind;
}) {
  const saveM = useSaveRule(accountId);
  const style = useHumanStyle(KIND, accountId);
  const [state, dispatch] = useReducer(gtkfReducer, undefined, () => initState(rule?.payload, meta));
  const [picking, setPicking] = useState(false);
  const { cutoff, media, caption, price } = state.draft;
  const lim = limitsOf(meta);
  const { cutMin, cutMax, priceMin, priceMax } = lim;

  const verdict = usePageSave(saveM, style, unsaved(state), dispatch);
  const invalid = invalidReason(state.draft, lim);

  // A rule this page's last Save created counts until the rules refetch shows it, so a second Save PATCHes it.
  const save = () =>
    verdict.save(() => saveM.mutate(ruleSave(state.draft, rule ?? saveM.data ?? null, meta, accountId)));

  return (
    <>
      <FormBlock title="When the chat ends">
        <label className="flex flex-wrap items-center gap-2 text-[14px] text-fg">
          <span>Stop after</span>
          <IfInput
            type="number"
            aria-label="Message cutoff"
            className={NUMBER}
            min={cutMin}
            max={cutMax}
            value={cutoff}
            onChange={(e) => verdict.edit({ type: "field", k: "cutoff", v: e.target.value })}
          />
          <span className="text-[12px] text-muted">fan messages if his info is still not gathered</span>
        </label>

        <div className="space-y-2">
          <div className="text-[14px] text-fg">Closing PPV</div>
          <p className="text-[12px] text-muted">
            Sent once, as his last message from this chat. No media = no PPV, it just stops.
          </p>
          <MediaTray
            accountId={accountId}
            attached={media}
            onChange={(next) => verdict.edit({ type: "field", k: "media", v: next.slice(0, VAULT_PICK_MAX) })}
            onOpenVaultPicker={() => setPicking(true)}
          />
          {picking && (
            <VaultPicker
              open
              onClose={() => setPicking(false)}
              accountId={accountId}
              initialSelectedIds={media.map((m) => m.id)}
              onConfirm={(next) => { verdict.edit({ type: "field", k: "media", v: next.slice(0, VAULT_PICK_MAX) }); setPicking(false); }}
            />
          )}
          <IfTextArea
            aria-label="Closing PPV caption"
            rows={3}
            value={caption}
            onChange={(e) => verdict.edit({ type: "field", k: "caption", v: e.target.value })}
          />
          <label className="flex flex-wrap items-center gap-2 text-[14px] text-fg">
            <span>Price $</span>
            <IfInput
              type="number"
              aria-label="Closing PPV price in dollars"
              className={NUMBER}
              min={priceMin}
              max={priceMax}
              step={1}
              value={price}
              onChange={(e) => verdict.edit({ type: "field", k: "price", v: e.target.value })}
            />
            <span className="text-[12px] text-muted">${priceMin} to ${priceMax}</span>
          </label>
        </div>
      </FormBlock>

      <HumanStyleBlock style={style} />

      <SaveRow save={verdict} onSave={save} disabled={!!invalid} warn={invalid} />
    </>
  );
}
