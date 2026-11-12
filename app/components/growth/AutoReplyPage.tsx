"use client";

/**
 * My AI Chatter > Auto-reply (ours; Infloww has no counterpart). The owner's
 * ask: "just autoreply, with options to pick folder who to reply".
 *
 * One switch, the timing (a delay, optionally randomised up to 2x) and WHO to
 * reply to, over the existing `autoreply` engine
 * (service/automations/autoreply.py) and its blob (`/admin/autoreply-config`).
 * WHO is two sources and a fan qualifies on either: (a) folders, an OF custom
 * list (the same lists the Messages Pro folder chips and the mass composer
 * target, so the picker is the house `ListColumn` over `useFanLists`) with an
 * optional spend cap; (b) new fans, subscribed recently and spent little.
 * Photos: two opt-ins, describing the photo he sent (a DeepInfra key) and
 * skipping messages that are only a photo. Human style, at the bottom: the
 * engine's realism layers (human style, typos, non-native English, space before
 * "?"), the same `autoreply` keys of the style blob (`/admin/style-config`)
 * the Settings Auto Convo tab edits; all default ON. Then "AI model (all AI
 * automations)": the ACCOUNT's AI model + effort (`/admin/account-config`,
 * shared with every AI automation that has no pin of its own), sent by the same
 * Save only when it changed; "Default" = null, labelled from the server's
 * `default_model`. A failed config read hides the row (the rest of the page
 * still saves). Under the Save, Model info (ModelInfoBlock, shared with Get to
 * know fans) with its own Save.
 *
 * On Infloww's look (page-parity ticket 16): the page header holds the creator
 * select (`?creator=`), Learn (the blurb), the On / Off pill and the Auto-reply
 * switch, which saves the moment it flips (its own PUT of the stored blob with
 * only `enabled` changed; the far-down Save is for the rest). The form is the
 * S4S-settings blocks with a switch row per option.
 */

import { useReducer } from "react";
import Link from "next/link";
import { useMutation } from "@tanstack/react-query";

import { IfInput, IfLearn, IfSelect, IfSwitch, SaveRow } from "@/components/ui/infloww";
import { AiKeyNotice } from "@/components/AiKeyNotice";
import { ListColumn, useFanLists } from "@/components/audience/fanLists";
import { HeaderSwitch } from "@/components/automations/HeaderSwitch";
import { HumanStyleBlock, useHumanStyle, usePageSave } from "@/components/automations/HumanStyleBlock";
import { ModelInfoBlock } from "@/components/automations/ModelInfoBlock";
import { unsaved } from "@/components/automations/sentDraft";
import { FormBlock, NoCreator, SwitchRow, useAutomationCreator } from "@/components/automations/automationPage";
import type { CreatorPick } from "@/components/shell/CreatorRail";
import { PageFrame } from "@/components/shell/PageFrame";
import { useAccountConfig, useAccountConfigBusy, useSaveAccountConfig, type AccountConfigResp, type BrainConfig } from "@/hooks/useAccountConfig";
import {
  useAutoreplyConfig,
  useSaveAutoreplyConfig,
  type AutoreplyConfig,
  type AutoreplyKeyState,
} from "@/hooks/useAutoreplyConfig";

import {
  answersWith, autoReplyReducer, brainPayload, buildPayload, canSubmit, effortChoices, initState, LIMITS, pickOf,
  randomiseOn, switchPayload, type AutoReplyDraft, type AutoReplyEdit, type NumberKey, type SwitchKey,
} from "./autoReplyForm";

const TITLE = "Auto-reply";
const NUMBER = "w-20";

const LEARN = (
  <IfLearn tip={<>When a fan messages and nobody has answered him in time, the AI sends him one casual reply in the
    creator&apos;s voice. A human reply first always wins; restricted fans are always left alone.</>}>
    <span className="max-sm:sr-only">Learn</span>
  </IfLearn>
);

export default function AutoReplyPage() {
  const { accountId, creators, loading } = useAutomationCreator();
  if (!accountId) {
    return <PageFrame title={TITLE} creators={creators} actions={LEARN}><NoCreator loading={loading} /></PageFrame>;
  }
  // Keyed, so switching creator re-seeds the form from that creator's blob.
  return <AutoReplyForm key={accountId} accountId={accountId} creators={creators} />;
}

/** The load gate: the fields only mount once the stored blob is in hand, so
 *  a failed read can never be saved over the account's real settings. */
function AutoReplyForm({ accountId, creators }: { accountId: string; creators: CreatorPick }) {
  const cfgQ = useAutoreplyConfig(accountId);
  const brainQ = useAccountConfig(accountId);
  if (cfgQ.isLoading || brainQ.isLoading || !cfgQ.data) {
    return (
      <PageFrame title={TITLE} creators={creators} actions={LEARN}>
        {cfgQ.isLoading || brainQ.isLoading ? <NoCreator loading /> : (
          <p className="text-[14px] text-err">
            {(cfgQ.error as Error)?.message || "Could not load the Auto-reply settings."}
          </p>
        )}
      </PageFrame>
    );
  }
  return (
    <AutoReplyFields
      accountId={accountId}
      creators={creators}
      stored={cfgQ.data.config ?? {}}
      defaults={cfgQ.data.defaults ?? {}}
      visionKey={cfgQ.data.vision_key}
      brain={brainQ.data}
      refetching={cfgQ.isFetching}
    />
  );
}

function AutoReplyFields({
  accountId, creators, stored, defaults, visionKey, brain, refetching,
}: {
  accountId: string;
  creators: CreatorPick;
  stored: AutoreplyConfig;
  defaults: AutoreplyConfig;
  visionKey?: AutoreplyKeyState;
  brain?: AccountConfigResp;
  /** The blob is being re-read: `stored` may be behind the last PUT, so the header switch waits. */
  refetching: boolean;
}) {
  const replyM = useSaveAutoreplyConfig(accountId);
  // The header switch's own PUT, so its pending/error never reads as the page Save's.
  const switchM = useSaveAutoreplyConfig(accountId);
  const brainM = useSaveAccountConfig(accountId);
  // A brain PUT (Model info's, or this Save's own) or re-read is out: this Save's brain copy may be stale, so it waits.
  const brainBusy = useAccountConfigBusy(accountId);
  // Seeded once from defaults ⊕ stored; a refetch does not re-seed (autoReplyForm.ts).
  const [state, dispatch] = useReducer(autoReplyReducer, undefined, () => initState({ ...defaults, ...stored }, brain));
  // One Save, two PUTs (the brain's only when the model moved): one mutation, pending until both settle, failed if
  // either did (its error shown), so a half-landed Save never reads "Saved".
  const saveM = useMutation<void, Error, { reply: AutoreplyConfig; brain: BrainConfig | null }>({
    mutationFn: async ({ reply, brain: b }) => {
      const runs = await Promise.allSettled([
        ...(b ? [brainM.mutateAsync(b).then(() => dispatch({ type: "brainSaved", pick: pickOf(b) }))] : []),
        replyM.mutateAsync(reply),
      ]);
      // Both failed: the blob's error shows (it is the last run), as before the one mutation.
      const failed = runs.findLast((r): r is PromiseRejectedResult => r.status === "rejected");
      if (failed) throw failed.reason;
    },
  });
  const style = useHumanStyle("autoreply", accountId);
  const { customLists, isLoading: listsLoading } = useFanLists(accountId);
  const { draft } = state;
  const verdict = usePageSave(saveM, style, unsaved(state), dispatch);

  const sw = (k: SwitchKey) => (on: boolean) => verdict.edit({ type: "switch", k, on });
  /** A number input's bounds and edit, from `LIMITS[k]`. */
  const num = (k: NumberKey) => ({
    min: LIMITS[k][0], max: LIMITS[k][1],
    onChange: (e: { target: { value: string } }) => verdict.edit({ type: "number", k, raw: e.target.value }),
  });
  const { delay } = draft;
  const noSource = !canSubmit(draft);

  // Saves at once: flips the draft (and its sent copy, so "Saved" holds), PUTs the stored blob with only `enabled`
  // changed, and flips back if that PUT fails. Waits while the page Save or a re-read is out (`stored` behind).
  const flip = (on: boolean) => {
    const body = switchPayload(defaults, stored, on);
    if (!body) return;
    dispatch({ type: "switched", on });
    switchM.mutate(body, { onError: () => dispatch({ type: "switched", on: !on }) });
  };
  const switchRefused = !draft.enabled && !switchPayload(defaults, stored, true);

  const save = () => verdict.save(() => {
    saveM.mutate({ reply: buildPayload(draft, stored), brain: brain ? brainPayload(state, brain) : null });
  });

  return (
    <PageFrame
      title={TITLE}
      creators={creators}
      actions={<>{LEARN}<HeaderSwitch label={TITLE} checked={draft.enabled} loading={switchM.isPending}
        disabled={refetching || saveM.isPending || switchRefused} onChange={flip} /></>}
    >
      <div className="max-w-[720px] space-y-8">
        {/* Missing key, or the key the last run was refused on (401/402/403). */}
        <AiKeyNotice accountId={accountId} kinds={["autoreply"]} />

        {switchM.isError && (
          <p className="text-[12px] text-err">Couldn&apos;t switch Auto-reply: {switchM.error.message}</p>
        )}

        <FormBlock title="When to reply">
          <label className="flex flex-wrap items-center gap-2 text-[14px] text-fg">
            <span>If nobody answered within</span>
            <IfInput
              type="number"
              aria-label="Reply delay in minutes"
              className={NUMBER}
              value={delay}
              {...num("delay")}
            />
            <span className="text-[12px] text-muted">min (0 = right away)</span>
          </label>
          <SwitchRow
            label="Randomise"
            hint={delay > 0 ? `each reply lands between ${delay} and ${delay * 2} min` : "needs a delay above 0"}
            checked={randomiseOn(draft)}
            disabled={delay === 0}
            onChange={sw("randomise")}
          />
        </FormBlock>

        <FormBlock title={<>Who to reply to <span className="text-[14px] font-normal text-muted">(a fan matching either)</span></>}>
          <SwitchRow label="Fans in folders" checked={draft.foldersOn} onChange={sw("foldersOn")}>
            {draft.foldersOn && (
              <>
                <ListColumn
                  lists={customLists}
                  loading={listsLoading}
                  selected={draft.folders}
                  onToggle={(id) => verdict.edit({ type: "toggleFolder", id })}
                  emptyLabel="No folders on this account yet. Create a list on OnlyFans first."
                />
                {draft.folders.size === 0 && (
                  <div className="text-[12px] text-muted">No folder ticked = every fan.</div>
                )}
                <div className="flex flex-wrap items-center gap-2 text-[14px] text-fg">
                  <IfSwitch aria-label="Only if he spent less than" checked={draft.capOn} onChange={sw("capOn")} />
                  <span>Only if he spent less than $</span>
                  <IfInput
                    type="number"
                    aria-label="Folder spend cap in dollars"
                    className={NUMBER}
                    step={1}
                    disabled={!draft.capOn}
                    value={draft.cap}
                    {...num("cap")}
                  />
                </div>
              </>
            )}
          </SwitchRow>

          <SwitchRow label="New fans" checked={draft.newOn} onChange={sw("newOn")}>
            {draft.newOn && (
              <div className="flex flex-wrap items-center gap-2 text-[14px] text-fg">
                <span>Subscribed less than</span>
                <IfInput
                  type="number"
                  aria-label="New fan window in hours"
                  className={NUMBER}
                  value={draft.newHours}
                  {...num("newHours")}
                />
                <span>hours ago and spent less than $</span>
                <IfInput
                  type="number"
                  aria-label="New fan spend cap in dollars"
                  className={NUMBER}
                  step={1}
                  value={draft.newMax}
                  {...num("newMax")}
                />
              </div>
            )}
          </SwitchRow>

          {!draft.foldersOn && !draft.newOn && (
            <div className="text-[12px] text-warn">Turn on folders or new fans, or nobody gets a reply.</div>
          )}
        </FormBlock>

        <FormBlock title="Photos he sends">
          <SwitchRow
            label="Describe photos fans send"
            hint="The AI looks at the photo it is answering and reacts to it. Off, it still replies, without claiming to know what is in the photo."
            checked={draft.describe}
            onChange={sw("describe")}
          >
            {visionKey && !visionKey.available && (
              <div className="text-[12px] text-muted">
                Needs a DeepInfra key.{" "}
                <Link href="/settings/ai-keys" className="text-accent hover:text-accent-hover">
                  Add a DeepInfra key in Settings → AI keys
                </Link>
                .
              </div>
            )}
          </SwitchRow>
          <SwitchRow
            label="Don't reply to photo-only messages"
            hint="A message that is only a photo, with no text, gets no auto-reply."
            checked={draft.skipPhotoOnly}
            onChange={sw("skipPhotoOnly")}
          />
        </FormBlock>

        <HumanStyleBlock style={style} />

        {brain && <ModelBlock draft={draft} brain={brain} edit={verdict.edit} />}

        <SaveRow save={verdict} onSave={save} disabled={noSource || switchM.isPending || brainBusy} />

        {/* Same read as the AI model row: with it failed there is nothing to edit (and a re-mount would re-read it
            under the load gate above). */}
        {brain && <ModelInfoBlock accountId={accountId} />}
      </div>
    </PageFrame>
  );
}

/** The account's reply model: Default (the server's `default_model`) or a pinned id, plus its effort when the
 *  model takes one (`effort_options[model]`, per provider); the line under it names what runs now. */
function ModelBlock({ draft, brain, edit }: {
  draft: AutoReplyDraft; brain: AccountConfigResp; edit: (a: AutoReplyEdit) => void;
}) {
  const efforts = effortChoices(draft, brain);
  const models = [
    { value: "", label: `Default (${brain.default_model})` },
    ...brain.model_options.map((m) => ({ value: m, label: m })),
  ];
  return (
    <FormBlock title="AI model (all AI automations)">
      <div className="flex flex-wrap items-center gap-2 text-[14px] text-fg">
        <span className="w-16">Model</span>
        <IfSelect aria-label="Model" value={draft.model} options={models}
          onChange={(model) => edit({ type: "model", model })} className="w-[240px] max-sm:flex-1" />
      </div>
      {efforts.length > 0 && (
        <div className="flex flex-wrap items-center gap-2 text-[14px] text-fg">
          <span className="w-16">Effort</span>
          <IfSelect aria-label="Reasoning effort" value={draft.effort}
            options={[{ value: "", label: "Model default" }, ...efforts.map((e) => ({ value: e, label: e }))]}
            onChange={(effort) => edit({ type: "effort", effort })} className="w-[240px] max-sm:flex-1" />
        </div>
      )}
      <div className="text-[12px] text-muted">
        Answers with <span className="text-fg">{answersWith(draft, brain)}</span>. Account-wide: every AI automation
        without a model of its own uses it too.
      </div>
    </FormBlock>
  );
}
