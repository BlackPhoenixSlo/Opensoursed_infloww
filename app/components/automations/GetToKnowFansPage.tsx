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

import { useState } from "react";

import { AiKeyNotice } from "@/components/AiKeyNotice";
import { VaultPicker } from "@/components/chat/VaultPicker";
import { MediaTray } from "@/components/compose/MediaTray";
import { FormBlock, NoCreator, SwitchRow, useAutomationCreator } from "@/components/automations/automationPage";
import type { CreatorPick } from "@/components/shell/CreatorRail";
import { PageFrame } from "@/components/shell/PageFrame";
import { IfButton, IfInput, IfSwitch, IfTextArea } from "@/components/ui/infloww";
import { useAccountConfig, useSaveAccountConfig, type AccountConfigResp } from "@/hooks/useAccountConfig";
import {
  useAutomationKinds, useAutomationRules, useSwitchKind, useUpdateRule, type AutomationKind, type AutomationRule,
} from "@/hooks/useAutomations";
import { useSaveStyleConfig, useStyleConfig, type StyleConfig } from "@/hooks/useStyleConfig";
import { VAULT_PICK_MAX } from "@/lib/ofMirrorChat";
import type { VaultMedia } from "@/lib/relay";

const TITLE = "Get to know fans";
const KIND = "welcome_chatter_for_info";
const NUMBER = "w-20";
/** account_config_api / _persona.MODEL_NOTES_MAX. */
const NOTES_MAX = 1000;

/** The info-gather realism layers in the style blob (Auto-reply's STYLE_BOXES, this engine's keys). Space before
 *  "?" only applies while Non-native is on, so it is disabled (value kept) while that is off. */
const STYLE_BOXES: { key: keyof StyleConfig; label: string; hint: string; parent?: keyof StyleConfig }[] = [
  { key: "welcome_chatter_for_info", label: "Human style",
    hint: "Short lowercase bursts, up to 3 quick bubbles, no robotic dashes or echoing." },
  { key: "typos_welcome_chatter_for_info", label: "Realistic typos",
    hint: 'The occasional thumb-typo, sometimes with a "*fix" bubble. Names, prices and links are never touched.' },
  { key: "nonnative_welcome_chatter_for_info", label: "Non-native English",
    hint: "Reads like a non-native speaker: consistent signature misspellings and slightly broken grammar." },
  { key: "nonnative_spacing_welcome_chatter_for_info", label: 'Space before "?"',
    hint: '"you like it ?", part of the non-native register. Needs Non-native English.',
    parent: "nonnative_welcome_chatter_for_info" },
];

const toCents = (dollars: number) => Math.round(dollars * 100);
const toDollars = (cents: number) => Math.round(cents) / 100;

export default function GetToKnowFansPage() {
  const { accountId, creators, loading } = useAutomationCreator();
  if (!accountId) {
    return <PageFrame title={TITLE} creators={creators}>{!loading && <NoCreator />}</PageFrame>;
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
            <p className="text-[14px] text-muted">Loading…</p>
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

/** A knob's catalog default (automation_rules_api._CATALOG, the value the engine reads when the key is absent). */
function knobOf(meta: AutomationKind, key: string) {
  return meta.knobs.find((k) => k.key === key);
}

/** The rule's own settings, seeded once from its payload (keyed by rule id), plus the Human style boxes. */
function RuleSettings({ accountId, rule, meta }: { accountId: string; rule: AutomationRule; meta: AutomationKind }) {
  const updateM = useUpdateRule(accountId);
  const styleQ = useStyleConfig(accountId);
  const styleM = useSaveStyleConfig(accountId);
  const p = rule.payload;
  const cutoffKnob = knobOf(meta, "max_fan_messages");
  const priceKnob = knobOf(meta, "closing_ppv_price_cents");
  const cutMin = cutoffKnob?.min ?? 3;
  const cutMax = cutoffKnob?.max ?? 100;
  const priceMin = toDollars(priceKnob?.min ?? 300);
  const priceMax = toDollars(priceKnob?.max ?? 20_000);

  // Numbers stay as typed (a min of 3 would fight every keystroke); they are checked before Save.
  const [cutoff, setCutoff] = useState(String(p.max_fan_messages ?? cutoffKnob?.default ?? 10));
  // Saved ids render as plain tiles; tiles picked this session keep their thumbnails.
  const [media, setMedia] = useState<VaultMedia[]>(() =>
    (Array.isArray(p.closing_ppv_media_ids) ? p.closing_ppv_media_ids : [])
      .map((id) => ({ id: Number(id), type: "photo" }) as VaultMedia));
  const [picking, setPicking] = useState(false);
  const [caption, setCaption] = useState(String(p.closing_ppv_text ?? knobOf(meta, "closing_ppv_text")?.default ?? ""));
  const [price, setPrice] = useState(String(toDollars(Number(p.closing_ppv_price_cents ?? priceKnob?.default ?? 1000))));
  const [styleEdits, setStyleEdits] = useState<StyleConfig>({});
  const styleEff: StyleConfig = { ...styleQ.data?.defaults, ...styleQ.data?.config, ...styleEdits };

  const touch = () => {
    if (updateM.isSuccess || updateM.isError) updateM.reset();
    if (styleM.isSuccess || styleM.isError) styleM.reset();
  };
  const edit = <T,>(setter: (v: T) => void) => (v: T) => { touch(); setter(v); };

  const cutoffN = Number(cutoff);
  const priceN = Number(price);
  const invalid =
    !Number.isInteger(cutoffN) || cutoffN < cutMin || cutoffN > cutMax
      ? `Message cutoff: ${cutMin} to ${cutMax}.`
      : price.trim() === "" || !Number.isFinite(priceN) || priceN < priceMin || priceN > priceMax
        ? `Price: $${priceMin} to $${priceMax}.`
        : null;

  const save = () => {
    if (Object.keys(styleEdits).length > 0) {
      styleM.mutate(styleEdits, { onSuccess: () => setStyleEdits({}) });
    }
    updateM.mutate({
      id: rule.id,
      payload: {
        ...rule.payload,
        max_fan_messages: cutoffN,
        closing_ppv_media_ids: media.map((m) => m.id),
        closing_ppv_text: caption,
        closing_ppv_price_cents: toCents(priceN),
      },
    });
  };
  const pending = updateM.isPending || styleM.isPending;
  const saveError = updateM.error?.message || styleM.error?.message;

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
            onChange={(e) => edit(setCutoff)(e.target.value)}
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
            onChange={(next) => edit(setMedia)(next.slice(0, VAULT_PICK_MAX))}
            onOpenVaultPicker={() => setPicking(true)}
          />
          {picking && (
            <VaultPicker
              open
              onClose={() => setPicking(false)}
              accountId={accountId}
              initialSelectedIds={media.map((m) => m.id)}
              onConfirm={(next) => { edit(setMedia)(next.slice(0, VAULT_PICK_MAX)); setPicking(false); }}
            />
          )}
          <IfTextArea
            aria-label="Closing PPV caption"
            rows={3}
            value={caption}
            onChange={(e) => edit(setCaption)(e.target.value)}
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
              onChange={(e) => edit(setPrice)(e.target.value)}
            />
            <span className="text-[12px] text-muted">${priceMin} to ${priceMax}</span>
          </label>
        </div>
      </FormBlock>

      {styleQ.data && (
        <FormBlock title="Human style">
          {STYLE_BOXES.map(({ key, label, hint, parent }) => (
            <SwitchRow
              key={key}
              label={label}
              hint={hint}
              checked={!!styleEff[key]}
              disabled={!!parent && !styleEff[parent]}
              onChange={(v) => { touch(); setStyleEdits((prev) => ({ ...prev, [key]: v })); }}
            />
          ))}
        </FormBlock>
      )}

      <div className="flex items-center gap-3">
        <IfButton variant="primary" onClick={save} disabled={pending || !!invalid} className="min-w-[76px]">
          {pending ? "Saving…" : "Save"}
        </IfButton>
        {invalid && <span className="text-[12px] text-warn">{invalid}</span>}
        {updateM.isSuccess && !pending && !styleM.isError && <span className="text-[12px] text-ok">Saved</span>}
        {(updateM.isError || styleM.isError) && (
          <span className="text-[12px] text-err">{saveError || "Save failed"}</span>
        )}
      </div>
    </>
  );
}

/** The load gate: the box mounts only once the stored brain is in hand, so a failed read is never saved back. */
function ModelInfo({ accountId }: { accountId: string }) {
  const cfgQ = useAccountConfig(accountId);
  return (
    <FormBlock title="Model info">
      {cfgQ.data ? <ModelInfoForm accountId={accountId} resp={cfgQ.data} /> : (
        <p className={cfgQ.isLoading ? "text-[14px] text-muted" : "text-[14px] text-err"}>
          {cfgQ.isLoading ? "Loading…" : (cfgQ.error as Error)?.message || "Could not load Model info."}
        </p>
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
