"use client";

/**
 * My Automations > Auto-reply (ours; Infloww has no counterpart). The owner's
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
 * the Settings Auto Convo tab edits; all default ON.
 *
 * On Infloww's look (page-parity ticket 16): the page header holds the creator
 * select (`?creator=`), Learn (the blurb) and the Auto-reply switch; the form is
 * the S4S-settings blocks with a switch row per option.
 */

import { useReducer } from "react";
import Link from "next/link";

import { IfInput, IfLearn, IfSwitch } from "@/components/ui/infloww";
import { AiKeyNotice } from "@/components/AiKeyNotice";
import { ListColumn, useFanLists } from "@/components/audience/fanLists";
import { HumanStyleBlock, useHumanStyle, usePageSave } from "@/components/automations/HumanStyleBlock";
import { unsaved } from "@/components/automations/sentDraft";
import { FormBlock, NoCreator, SaveRow, SwitchRow, useAutomationCreator } from "@/components/automations/automationPage";
import type { CreatorPick } from "@/components/shell/CreatorRail";
import { PageFrame } from "@/components/shell/PageFrame";
import {
  useAutoreplyConfig,
  useSaveAutoreplyConfig,
  type AutoreplyConfig,
  type AutoreplyKeyState,
} from "@/hooks/useAutoreplyConfig";

import {
  autoReplyReducer, buildPayload, canSubmit, initState, LIMITS, randomiseOn,
  type NumberKey, type SwitchKey,
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
  if (cfgQ.isLoading || !cfgQ.data) {
    return (
      <PageFrame title={TITLE} creators={creators} actions={LEARN}>
        {cfgQ.isLoading ? <NoCreator loading /> : (
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
    />
  );
}

function AutoReplyFields({
  accountId, creators, stored, defaults, visionKey,
}: {
  accountId: string;
  creators: CreatorPick;
  stored: AutoreplyConfig;
  defaults: AutoreplyConfig;
  visionKey?: AutoreplyKeyState;
}) {
  const saveM = useSaveAutoreplyConfig(accountId);
  const style = useHumanStyle("autoreply", accountId);
  const { customLists, isLoading: listsLoading } = useFanLists(accountId);
  // Seeded once from defaults ⊕ stored; a refetch does not re-seed (autoReplyForm.ts).
  const [state, dispatch] = useReducer(autoReplyReducer, { ...defaults, ...stored }, initState);
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

  const save = () => verdict.save(() => saveM.mutate(buildPayload(draft, stored)));

  return (
    <PageFrame
      title={TITLE}
      creators={creators}
      actions={<>{LEARN}<IfSwitch label={<span className="max-sm:sr-only">Auto-reply</span>} aria-label="Auto-reply"
        checked={draft.enabled} onChange={sw("enabled")} /></>}
    >
      <div className="max-w-[720px] space-y-8">
        {/* Missing key, or the key the last run was refused on (401/402/403). */}
        <AiKeyNotice accountId={accountId} kinds={["autoreply"]} />

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

          {noSource && (
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

        <SaveRow save={verdict} onSave={save} disabled={noSource} />
      </div>
    </PageFrame>
  );
}
