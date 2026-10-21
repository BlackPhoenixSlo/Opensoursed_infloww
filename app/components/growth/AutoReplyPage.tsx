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
 *
 * The save sends the STORED blob back with only this page's fields changed:
 * the PUT replaces the whole blob, and the engine's other knobs (quiet hours,
 * reply caps) must keep whatever they hold. The style PUT merges, so it sends
 * only the boxes touched here and an untouched default stays a default.
 */

import { useState, type ReactNode } from "react";
import Link from "next/link";

import { IfButton, IfInput, IfLearn, IfSwitch } from "@/components/ui/infloww";
import { AiKeyNotice } from "@/components/AiKeyNotice";
import { ListColumn, useFanLists } from "@/components/audience/fanLists";
import { FormBlock, NoCreator, SwitchRow, useAutomationCreator } from "@/components/automations/automationPage";
import { PageFrame } from "@/components/shell/PageFrame";
import {
  useAutoreplyConfig,
  useSaveAutoreplyConfig,
  type AutoreplyConfig,
  type AutoreplyKeyState,
} from "@/hooks/useAutoreplyConfig";
import {
  useSaveStyleConfig,
  useStyleConfig,
  type StyleConfig,
} from "@/hooks/useStyleConfig";

const TITLE = "Auto-reply";
const NUMBER = "w-20";

/** Upper bound on the delay this page offers: the engine stops covering a
 *  message after `silence_max_minutes` (default 1115), so a delay (or its
 *  randomised 2x) past it would never fire. */
const MAX_DELAY_MIN = 240;
const MAX_HOURS = 8760;

/** The `autoreply` realism layers in the style blob, as the engine reads them
 *  (service/automations/autoreply.py). Space before "?" only applies while
 *  Non-native is on, so it is disabled (value kept) while that is off. */
const STYLE_BOXES: { key: keyof StyleConfig; label: string; hint: string; parent?: keyof StyleConfig }[] = [
  { key: "autoreply", label: "Human style",
    hint: "Short lowercase bursts, up to 3 quick bubbles, no robotic dashes or echoing." },
  { key: "typos_autoreply", label: "Realistic typos",
    hint: 'The occasional thumb-typo, sometimes with a "*fix" bubble. Names, prices and links are never touched.' },
  { key: "nonnative_autoreply", label: "Non-native English",
    hint: "Reads like a non-native speaker: consistent signature misspellings and slightly broken grammar." },
  { key: "nonnative_spacing_autoreply", label: 'Space before "?"',
    hint: '"you like it ?", part of the non-native register. Needs Non-native English.', parent: "nonnative_autoreply" },
];

const LEARN = (
  <IfLearn tip={<>When a fan messages and nobody has answered him in time, the AI sends him one casual reply in the
    creator&apos;s voice. A human reply first always wins; restricted fans are always left alone.</>}>
    <span className="max-sm:sr-only">Learn</span>
  </IfLearn>
);

const toCents = (dollars: number) => Math.round(dollars * 100);
const toDollars = (cents: number) => Math.round(cents) / 100;
/** A number input's value, clamped; blank / junk reads as `lo`. */
const clamp = (raw: string, lo: number, hi: number) =>
  Math.max(lo, Math.min(Number(raw) || lo, hi));

export default function AutoReplyPage() {
  const { accountId, picker, loading } = useAutomationCreator();
  if (!accountId) {
    return <PageFrame title={TITLE} extra={picker} actions={LEARN}>{!loading && <NoCreator />}</PageFrame>;
  }
  // Keyed, so switching creator re-seeds the form from that creator's blob.
  return <AutoReplyForm key={accountId} accountId={accountId} picker={picker} />;
}

/** The load gate: the fields only mount once the stored blob is in hand, so
 *  a failed read can never be saved over the account's real settings. */
function AutoReplyForm({ accountId, picker }: { accountId: string; picker: ReactNode }) {
  const cfgQ = useAutoreplyConfig(accountId);
  if (cfgQ.isLoading || !cfgQ.data) {
    return (
      <PageFrame title={TITLE} extra={picker} actions={LEARN}>
        {cfgQ.isLoading ? <p className="text-[14px] text-muted">Loading…</p> : (
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
      picker={picker}
      stored={cfgQ.data.config ?? {}}
      defaults={cfgQ.data.defaults ?? {}}
      visionKey={cfgQ.data.vision_key}
    />
  );
}

function AutoReplyFields({
  accountId, picker, stored, defaults, visionKey,
}: {
  accountId: string;
  picker: ReactNode;
  stored: AutoreplyConfig;
  defaults: AutoreplyConfig;
  visionKey?: AutoreplyKeyState;
}) {
  const saveM = useSaveAutoreplyConfig(accountId);
  const styleQ = useStyleConfig(accountId);
  const styleM = useSaveStyleConfig(accountId);
  // Only the boxes touched here; the rest render the stored/default value.
  const [styleEdits, setStyleEdits] = useState<StyleConfig>({});
  const styleEff: StyleConfig = {
    ...styleQ.data?.defaults, ...styleQ.data?.config, ...styleEdits,
  };
  const { customLists, isLoading: listsLoading } = useFanLists(accountId);
  const eff = { ...defaults, ...stored };
  const [enabled, setEnabled] = useState(!!eff.enabled);
  const [delay, setDelay] = useState(eff.silence_min_minutes ?? 24);
  const [randomise, setRandomise] = useState(
    (eff.step_in_max_minutes ?? 0) > (eff.silence_min_minutes ?? 24));
  const [foldersOn, setFoldersOn] = useState(eff.folders_enabled ?? true);
  const [folders, setFolders] = useState<Set<string>>(
    () => new Set((eff.list_ids ?? []).map(String)));
  const [capOn, setCapOn] = useState(eff.folder_max_spend_cents != null);
  const [cap, setCap] = useState(toDollars(eff.folder_max_spend_cents ?? 50_000));
  const [newOn, setNewOn] = useState(!!eff.new_fans_enabled);
  const [newHours, setNewHours] = useState(eff.new_fan_hours ?? 72);
  const [newMax, setNewMax] = useState(toDollars(eff.new_fan_max_spend_cents ?? 1_000));
  const [describe, setDescribe] = useState(!!eff.describe_photos);
  const [skipPhotoOnly, setSkipPhotoOnly] = useState(!!eff.skip_photo_only);

  const touch = () => {
    if (saveM.isSuccess || saveM.isError) saveM.reset();
    if (styleM.isSuccess || styleM.isError) styleM.reset();
  };
  const setStyle = (key: keyof StyleConfig, on: boolean) => {
    touch();
    setStyleEdits((prev) => ({ ...prev, [key]: on }));
  };
  const edit = <T,>(setter: (v: T) => void) => (v: T) => { touch(); setter(v); };
  const toggleFolder = (id: string) => {
    touch();
    setFolders((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };
  // Both sources off = nobody qualifies: an "on" switch that never replies.
  const noSource = enabled && !foldersOn && !newOn;

  const save = () => {
    if (Object.keys(styleEdits).length > 0) {
      styleM.mutate(styleEdits, { onSuccess: () => setStyleEdits({}) });
    }
    saveM.mutate({
      ...stored,
      enabled,
      silence_min_minutes: delay,
      // Randomise = each reply lands somewhere in [delay, 2 x delay]; the
      // engine's step-in range does the draw. 0 = a fixed delay.
      step_in_max_minutes: randomise && delay > 0 ? delay * 2 : 0,
      folders_enabled: foldersOn,
      list_ids: [...folders].map(Number),
      folder_max_spend_cents: capOn ? toCents(cap) : null,
      new_fans_enabled: newOn,
      new_fan_hours: newHours,
      new_fan_max_spend_cents: toCents(newMax),
      describe_photos: describe,
      skip_photo_only: skipPhotoOnly,
    });
  };
  const pending = saveM.isPending || styleM.isPending;
  const saveError = saveM.error?.message || styleM.error?.message;

  return (
    <PageFrame
      title={TITLE}
      extra={picker}
      actions={<>{LEARN}<IfSwitch label={<span className="max-sm:sr-only">Auto-reply</span>} aria-label="Auto-reply"
        checked={enabled} onChange={edit(setEnabled)} /></>}
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
              min={0}
              max={MAX_DELAY_MIN}
              value={delay}
              onChange={(e) => edit(setDelay)(clamp(e.target.value, 0, MAX_DELAY_MIN))}
            />
            <span className="text-[12px] text-muted">min (0 = right away)</span>
          </label>
          <SwitchRow
            label="Randomise"
            hint={delay > 0 ? `each reply lands between ${delay} and ${delay * 2} min` : "needs a delay above 0"}
            checked={randomise && delay > 0}
            disabled={delay === 0}
            onChange={edit(setRandomise)}
          />
        </FormBlock>

        <FormBlock title={<>Who to reply to <span className="text-[14px] font-normal text-muted">(a fan matching either)</span></>}>
          <SwitchRow label="Fans in folders" checked={foldersOn} onChange={edit(setFoldersOn)}>
            {foldersOn && (
              <>
                <ListColumn
                  lists={customLists}
                  loading={listsLoading}
                  selected={folders}
                  onToggle={toggleFolder}
                  emptyLabel="No folders on this account yet. Create a list on OnlyFans first."
                />
                {folders.size === 0 && (
                  <div className="text-[12px] text-muted">No folder ticked = every fan.</div>
                )}
                <div className="flex flex-wrap items-center gap-2 text-[14px] text-fg">
                  <IfSwitch aria-label="Only if he spent less than" checked={capOn} onChange={edit(setCapOn)} />
                  <span>Only if he spent less than $</span>
                  <IfInput
                    type="number"
                    aria-label="Folder spend cap in dollars"
                    className={NUMBER}
                    min={0}
                    step={1}
                    disabled={!capOn}
                    value={cap}
                    onChange={(e) => edit(setCap)(clamp(e.target.value, 0, 100_000))}
                  />
                </div>
              </>
            )}
          </SwitchRow>

          <SwitchRow label="New fans" checked={newOn} onChange={edit(setNewOn)}>
            {newOn && (
              <div className="flex flex-wrap items-center gap-2 text-[14px] text-fg">
                <span>Subscribed less than</span>
                <IfInput
                  type="number"
                  aria-label="New fan window in hours"
                  className={NUMBER}
                  min={1}
                  max={MAX_HOURS}
                  value={newHours}
                  onChange={(e) => edit(setNewHours)(clamp(e.target.value, 1, MAX_HOURS))}
                />
                <span>hours ago and spent less than $</span>
                <IfInput
                  type="number"
                  aria-label="New fan spend cap in dollars"
                  className={NUMBER}
                  min={0}
                  step={1}
                  value={newMax}
                  onChange={(e) => edit(setNewMax)(clamp(e.target.value, 0, 100_000))}
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
            checked={describe}
            onChange={edit(setDescribe)}
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
            checked={skipPhotoOnly}
            onChange={edit(setSkipPhotoOnly)}
          />
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
                onChange={(on) => setStyle(key, on)}
              />
            ))}
          </FormBlock>
        )}

        <div className="flex items-center gap-3">
          <IfButton variant="primary" onClick={save} disabled={pending || noSource} className="min-w-[76px]">
            {pending ? "Saving…" : "Save"}
          </IfButton>
          {saveM.isSuccess && !pending && !styleM.isError && (
            <span className="text-[12px] text-ok">Saved</span>
          )}
          {(saveM.isError || styleM.isError) && (
            <span className="text-[12px] text-err">{saveError || "Save failed"}</span>
          )}
        </div>
      </div>
    </PageFrame>
  );
}
