"use client";

/**
 * My Automations > Get to know fans (ours). The AI info-gather automation
 * (`welcome_chatter_for_info`, service/automations/welcome_chatter_for_info.py) on a page of its own: the header
 * switch turns the kind on or off for the creator (`/admin/automation-rules/switch`, which creates its rule from
 * the catalog defaults the first time); once the rule exists the page shows its settings (the message cutoff and
 * the closing PPV, from the rule's payload) and the engine's Human style boxes (the style blob, as Auto-reply's
 * page shows its own), saved together by one Save. Model info is the account's short note every chat prompt pins
 * (`account_ai_config.model_notes`, through `_persona.compose_persona`: this automation and Auto-reply).
 *
 * Model info is for anyone with access to the account. The switch and settings ride the rule routes, which this
 * page does not grant on its own (service/permissions.py PAGE_MAP), so a role without them sees why instead.
 *
 * Both saves send the STORED value back with only this page's fields changed: the rule PATCH and the account-config
 * PUT each replace what they hold (the rule's cadence and dev knobs, the rest of the brain keep theirs). The style
 * PUT merges, so it sends only the boxes touched here.
 */

import { useReducer, useState } from "react";

import { AiKeyNotice } from "@/components/AiKeyNotice";
import { VaultPicker } from "@/components/chat/VaultPicker";
import { MediaTray } from "@/components/compose/MediaTray";
import { FormBlock, NoCreator, SaveRow, useAutomationCreator } from "@/components/automations/automationPage";
import { HumanStyleBlock, useHumanStyle, usePageSave } from "@/components/automations/HumanStyleBlock";
import { unsaved } from "@/components/automations/sentDraft";
import type { CreatorPick } from "@/components/shell/CreatorRail";
import { PageFrame } from "@/components/shell/PageFrame";
import { IfButton, IfInput, IfSwitch, IfTextArea } from "@/components/ui/infloww";
import { useAccountConfig, useSaveAccountConfig, type AccountConfigResp } from "@/hooks/useAccountConfig";
import {
  useAutomationKinds, useAutomationRules, useSwitchKind, useUpdateRule, type AutomationKind, type AutomationRule,
} from "@/hooks/useAutomations";
import { VAULT_PICK_MAX } from "@/lib/ofMirrorChat";
import { Skeleton } from "@/components/ui/Skeleton";

import { buildPayload, gtkfReducer, initState, invalidReason, limitsOf } from "./getToKnowFansForm";

const TITLE = "Get to know fans";
const KIND = "welcome_chatter_for_info";
const NUMBER = "w-20";
/** account_config_api / _persona.MODEL_NOTES_MAX. */
const NOTES_MAX = 1000;

export default function GetToKnowFansPage() {
  const { accountId, creators, loading } = useAutomationCreator();
  if (!accountId) {
    return <PageFrame title={TITLE} creators={creators}><NoCreator loading={loading} /></PageFrame>;
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

  return (
    <PageFrame
      title={TITLE}
      creators={creators}
      actions={
        <IfSwitch label={<span className="max-sm:sr-only">{TITLE}</span>} aria-label={TITLE}
          checked={on} disabled={!rulesQ.isSuccess} loading={switchM.isPending}
          onChange={(enable) => switchM.mutate({ kind: KIND, enable })} />
      }
    >
      <div className="max-w-[720px] space-y-8">
        <AiKeyNotice accountId={accountId} kinds={[KIND]} />

        <FormBlock title="Automation">
          {meta?.summary && <p className="text-[14px] text-fg-dim">{meta.summary}</p>}
          {rulesQ.isLoading || (rule && kindsQ.isLoading) ? (
            <FormSkeleton />
          ) : rulesQ.isError ? (
            <p className="text-[14px] text-muted">
              {(rulesQ.error as Error)?.message || "Could not load this automation."} Model info below still applies.
            </p>
          ) : !rule ? (
            <p className="text-[14px] text-muted">Turn it on above to set the message cutoff and the closing PPV.</p>
          ) : !meta ? (
            <p className="text-[14px] text-err">
              {(kindsQ.error as Error)?.message || "Could not load this automation's settings."}
            </p>
          ) : null}
          {switchM.isError && <p className="text-[12px] text-err">{switchM.error.message}</p>}
        </FormBlock>

        {rule && meta && <RuleSettings key={rule.id} accountId={accountId} rule={rule} meta={meta} />}

        <ModelInfo accountId={accountId} />
      </div>
    </PageFrame>
  );
}

/** The rule's own settings, seeded once from its payload (keyed by rule id; getToKnowFansForm.ts), plus the Human
 *  style boxes. */
function RuleSettings({ accountId, rule, meta }: { accountId: string; rule: AutomationRule; meta: AutomationKind }) {
  const updateM = useUpdateRule(accountId);
  const style = useHumanStyle(KIND, accountId);
  const [state, dispatch] = useReducer(gtkfReducer, undefined, () => initState(rule.payload, meta));
  const [picking, setPicking] = useState(false);
  const { cutoff, media, caption, price } = state.draft;
  const lim = limitsOf(meta);
  const { cutMin, cutMax, priceMin, priceMax } = lim;

  const verdict = usePageSave(updateM, style, unsaved(state), dispatch);
  const invalid = invalidReason(state.draft, lim);

  const save = () =>
    verdict.save(() => updateM.mutate({ id: rule.id, payload: buildPayload(state.draft, rule.payload) }));

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

/** A form block's fields while its read runs: a label bar over an input-sized bar, twice. */
function FormSkeleton() {
  return (
    <div role="status" aria-label="Loading" className="space-y-3">
      <Skeleton className="h-3 w-28" />
      <Skeleton className="h-10 w-full" />
      <Skeleton className="h-3 w-40" />
      <Skeleton className="h-10 w-full" />
    </div>
  );
}

/** The load gate: the box mounts only once the stored brain is in hand, so a failed read is never saved back. */
function ModelInfo({ accountId }: { accountId: string }) {
  const cfgQ = useAccountConfig(accountId);
  return (
    <FormBlock title="Model info">
      {cfgQ.data ? <ModelInfoForm accountId={accountId} resp={cfgQ.data} /> : cfgQ.isLoading ? <FormSkeleton /> : (
        <p className="text-[14px] text-err">{(cfgQ.error as Error)?.message || "Could not load Model info."}</p>
      )}
    </FormBlock>
  );
}

function ModelInfoForm({ accountId, resp }: { accountId: string; resp: AccountConfigResp }) {
  const saveM = useSaveAccountConfig(accountId);
  // Empty → the prewritten template; its lines left blank never reach a prompt.
  const [text, setText] = useState(resp.config.model_notes || resp.model_notes_template || "");

  return (
    <>
      <p className="text-[12px] text-muted">
        A few short lines about this model. The AI reads them in Get to know fans and Auto-reply chats; a line left
        blank is ignored.
      </p>
      <IfTextArea
        aria-label="Model info"
        value={text}
        onChange={(e) => {
          if (saveM.isSuccess || saveM.isError) saveM.reset();
          setText(e.target.value);
        }}
        rows={7}
        maxLength={NOTES_MAX}
      />
      <div className="flex items-center gap-3">
        <IfButton variant="primary" className="min-w-[76px]" disabled={saveM.isPending}
          onClick={() => saveM.mutate({ ...resp.config, model_notes: text })}>
          {saveM.isPending ? "Saving…" : "Save"}
        </IfButton>
        <span className="text-[12px] text-muted tabular-nums">{text.length}/{NOTES_MAX}</span>
        {saveM.isSuccess && !saveM.isPending && <span className="text-[12px] text-ok">Saved</span>}
        {saveM.isError && <span className="text-[12px] text-err">{saveM.error.message || "Save failed"}</span>}
      </div>
    </>
  );
}
