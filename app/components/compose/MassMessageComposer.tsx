"use client";


import { useCallback, useEffect, useId, useLayoutEffect, useMemo, useReducer, useRef, useState } from "react";
import { Lock, X } from "lucide-react";

import { usePlatformAccounts } from "@/hooks/useAccounts";
import { useAccountPlatform, useCanOrFallback } from "@/hooks/useCan";
import { accountPlatform, useFallbackPlatform } from "@/lib/platform";
import { onlineCountLabel, useOnlineSubscribers } from "@/hooks/useOnlineSubscribers";
import { useAllModelsInclude } from "@/hooks/useAllModelsInclude";
import { useSmartLists } from "@/hooks/useSmartLists";
import { useFunnels } from "@/hooks/useFunnels";
import { useEmployee } from "@/contexts/EmployeeContext";
import { VaultPicker } from "@/components/chat/VaultPicker";
import { EmojiPickerButton, EmojiQuickRow } from "@/components/chat/EmojiBar";
import { GifPickerButton, GifPickerStrip } from "@/components/chat/GifPicker";
import { TemplatePicker, type PickedTemplate } from "@/components/chat/TemplatePicker";
import { TagCreatorsPicker, TaggedCreatorChips } from "@/components/chat/TagCreatorsPicker";
import { useFanLists } from "@/components/audience/fanLists";
import { massExcludeListId } from "@/components/audience/audienceReducer";
import { useSensitiveHits } from "@/lib/sensitiveWords";
import { isOfHtml, ofPlainText } from "@/lib/ofRichText";
import { SensitiveWordWarning } from "@/components/chat/SensitiveWordWarning";
import { IfButton, IfHelp, IfInput, IfLabel, IfModal, IfNativeSelect } from "@/components/ui/infloww";

import { sanitizePriceInput } from "@/lib/priceInput";

import { AudiencePanel } from "./AudiencePanel";
import { FanOutResults, FanOutStatus } from "./FanOutResults";
import { IncludeModelsChips } from "./IncludeModelsChips";
import { massSendFrom, massSenders } from "./massSenders";
import { fanOutLocked } from "./fanOut";
import { MediaTray } from "./MediaTray";
import { AaButton, ComposeTextBox, type ComposeTextBoxHandle } from "./ComposeTextBox";
import { OnlineTargetingPanel } from "./OnlineTargetingPanel";
import { ScheduleField } from "./ScheduleField";
import { useMassSend } from "./useMassSend";
import { isAudienceSeed, useTouched } from "./useTouched";
import {
  confirmPrompt, effectivePrice, fieldAction, gifNote, initMassForm, massMessageReducer, validateMass,
  type MassAction, type MassField, type MassForm,
} from "./massMessageReducer";
import { fmtPrice } from "@/lib/format";
import { ifConfirm } from "@/components/ui/ifConfirm";

interface MassMessageComposerProps {
  onClose: () => void;
  mode?: "standard" | "online";
  forcedAccountId?: string;
  labelExtras?: boolean;
}

const isMassSeed = (a: MassAction, s: MassForm) =>
  isAudienceSeed(a, s) || (a.type === "field" && a.k === "gifPickerOpen");

export function MassMessageComposer({
  onClose,
  mode = "standard",
  forcedAccountId,
  labelExtras = false,
}: MassMessageComposerProps) {
  const online = mode === "online";
  const platformAccounts = usePlatformAccounts();
  const fallbackPlatform = useFallbackPlatform();
  const launchPlatform = useAccountPlatform(forcedAccountId);
  const launch = forcedAccountId ? launchPlatform ?? "unknown" : null;
  const openPlatform = launchPlatform ?? fallbackPlatform;
  const { isIncluded } = useAllModelsInclude();
  // No explicit employeeId attributes the send to the Automation system employee (id=2); X-Employee-Id is opt-in per call.
  const { current: currentEmployee } = useEmployee();
  const [form, rawDispatch] = useReducer(massMessageReducer, null, () => initMassForm(forcedAccountId ?? null, openPlatform, launch));
  const { touched, dispatch } = useTouched(form, rawDispatch, isMassSeed);
  useEffect(() => {
    rawDispatch({ type: "launchPlatform", platform: launch });
  }, [launch]);
  const activeAccounts = useMemo(() => massSenders(platformAccounts, form.platform), [platformAccounts, form.platform]);
  const {
    allModels, accountId, text, attached, price, previewCount, lockedText, schedule, funnelId, progress, results,
    gifFailures, taggedCreators, pickedGifs, gifPickerOpen,
  } = form;
  const locked = fanOutLocked(form);
  const set = useCallback(
    <K extends MassField>(k: K) => (v: MassForm[K]) => dispatch(fieldAction(k, v)),
    [dispatch],
  );
  // Stable per roster: AccountPicker's auto-seed effect depends on it.
  const setAccountId = useCallback((id: string) => {
    const a = platformAccounts.find((x) => x.id === id);
    dispatch({ type: "setAccount", id, platform: a ? accountPlatform(a) : undefined });
  }, [dispatch, platformAccounts]);
  // Funnel steps run server-side per replying fan after the opener; inert on the live OF-queue path.
  const funnelsQ = useFunnels();
  const [pickerOpen, setPickerOpen] = useState(false);
  const onlineCountQ = useOnlineSubscribers(online && !allModels ? accountId : null, 60_000);
  const onlineCount = onlineCountQ.data ? onlineCountLabel(onlineCountQ.data) : null;
  const textRef = useRef<ComposeTextBoxHandle | null>(null);
  const allowRich = useCanOrFallback(allModels ? activeAccounts[0]?.id : accountId, "rich_text");
  const priceId = useId();
  const funnelSelectId = useId();

  const { customLists, ...listsQ } = useFanLists(accountId);

  // The standing MASSDMEXCLUDE list is pre-selected into exclude so mass sends skip it by default; the operator can untick it.
  useEffect(() => {
    if (!accountId || listsQ.isLoading || listsQ.isFetching) return;
    rawDispatch({ type: "seedExclude", accountId, listId: massExcludeListId(listsQ.data ?? []) });
  }, [accountId, allModels, form.seededFor, listsQ.isLoading, listsQ.isFetching, listsQ.data]);

  const smartLists = useSmartLists(allModels ? null : accountId).data ?? [];

  // All-models broadcasts force free + unlocked text; per-employee, a typed price > 0 is the sole paid signal.
  const priceToSend = effectivePrice(form);


  // A forced or saved Creator outside the sender list (expired session) still sends, unless her Platform can't mass message.
  const accountMaySend = useCanOrFallback(accountId, "mass_message");
  const sendFrom = massSendFrom(
    { ...form, launch }, platformAccounts, isIncluded, accountMaySend,
  );

  const sensitiveHits = useSensitiveHits(isOfHtml(text) ? ofPlainText(text) : text, allModels ? null : accountId);

  const invalid = validateMass(form, {
    broadcastCount: sendFrom.length,
    sensitive: sensitiveHits.length > 0,
  });

  const latestSend = useRef({ targets: sendFrom, platform: form.platform });
  useLayoutEffect(() => {
    latestSend.current = { targets: sendFrom, platform: form.platform };
  }, [sendFrom, form.platform]);

  const send = useMassSend({
    form, dispatch: rawDispatch, online, invalid, employeeId: currentEmployee?.id,
    onClose,
    isEligible: (id) => latestSend.current.platform === form.platform && latestSend.current.targets.includes(id),
  });

  function close() {
    if (!send.isPending) onClose();
  }

  function onEmoji(em: string) {
    if (textRef.current) textRef.current.insert(em);
    else dispatch({ type: "appendText", v: em });
  }

  function onPickTemplate(t: PickedTemplate) {
    dispatch({ type: "pickTemplate", t, rich: allowRich });
    setTimeout(() => textRef.current?.focus(), 0);
  }

  const isPPV = priceToSend > 0;
  const isScheduled = !!schedule;

  return (
    <>
      <IfModal
        title={online ? "New Mass Online message" : "New mass message"}
        width={722}
        size="editor"
        onClose={close}
        keyboard={!touched}
        footer={<>
          <FanOutStatus
            progress={progress} verb="Sending" invalid={invalid} error={send.error?.message ?? null} results={results}
          />
          <IfButton onClick={onClose} disabled={send.isPending}>
            {gifFailures ? "Close" : "Cancel"}
          </IfButton>
          <IfButton
            variant="primary"
            onClick={async () => {
              if (!await ifConfirm(confirmPrompt(form, sendFrom.length))) return;
              const current = latestSend.current;
              if (current.platform !== form.platform) return;
              if (current.targets.length !== sendFrom.length || !sendFrom.every((id) => current.targets.includes(id))) return;
              send.mutate(current.targets);
            }}
            disabled={send.isPending || invalid !== null}
            title={invalid ?? undefined}
          >
            {send.isPending
              ? (isScheduled ? "Scheduling…" : "Broadcasting…")
              : (isScheduled ? "Schedule" : "Broadcast")}
          </IfButton>
        </>}
      >
        <div className="space-y-4">
          <IncludeModelsChips
            noun="broadcast" accounts={activeAccounts} allModels={allModels} locked={locked}
            onAllModels={(on) => dispatch({ type: "setAllModels", on })}
            accountId={accountId} onAccount={setAccountId}
          />

          <fieldset disabled={locked} className="min-w-0 space-y-4 disabled:opacity-60">
          <div className="space-y-2">
            <ComposeTextBox
              ref={textRef}
              value={text}
              onChange={set("text")}
              placeholder="What's the broadcast?"
              rows={4}
              rich={allowRich && form.mode.rich}
              toolbar={form.mode.toolbar}
              disabled={locked}
            />
            <SensitiveWordWarning hits={sensitiveHits} />
            <div className="flex items-center gap-1.5 flex-wrap">
              <EmojiQuickRow onInsert={onEmoji} />
              <EmojiPickerButton align="left" onInsert={onEmoji} />
              {allowRich && <AaButton on={form.mode.toolbar} onToggle={() => dispatch({ type: "aa" })} />}
              <GifPickerButton
                open={gifPickerOpen}
                onToggle={() => set("gifPickerOpen")(!gifPickerOpen)}
              />
              <TemplatePicker
                accountId={accountId}
                onPick={onPickTemplate}
                hideImageTemplates
              />
              {!allModels && (
                <TagCreatorsPicker
                  accountId={accountId}
                  selected={taggedCreators}
                  onChange={set("taggedCreators")}
                />
              )}
            </div>
            {gifPickerOpen && (
              <GifPickerStrip
                accountId={accountId}
                onClose={() => set("gifPickerOpen")(false)}
                onPick={(gif) => dispatch({ type: "addGif", gif })}
              />
            )}
            {pickedGifs.length > 0 && (
              <div className="flex flex-wrap items-center gap-2 rounded-md border border-border p-2">
                <span className="mr-1 text-[12px] text-fg-dim">GIFs</span>
                {pickedGifs.map((g) => (
                  <div key={g.id} className="relative w-14 h-14 rounded-md overflow-hidden border border-border bg-bg-elev-1">
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img src={g.thumbUrl} alt={g.title || "GIF"} className="w-full h-full object-cover" />
                    <button
                      type="button"
                      onClick={() => dispatch({ type: "removeGif", id: g.id })}
                      className="absolute top-0.5 right-0.5 w-6 h-6 md:w-4 md:h-4 rounded-full bg-black/70 text-white grid place-items-center opacity-80 hover:opacity-100"
                      aria-label="Remove GIF"
                      title="Remove GIF"
                    >
                      <X className="h-3 w-3" aria-hidden />
                    </button>
                  </div>
                ))}
                <span className="ml-auto text-[12px] text-muted">
                  {gifNote(form)}
                </span>
              </div>
            )}
            {!allModels && taggedCreators.length > 0 && (
              <TaggedCreatorChips selected={taggedCreators} onChange={set("taggedCreators")} />
            )}
          </div>

          {!allModels && (
            <MediaTray
              accountId={accountId}
              attached={attached}
              onChange={set("attached")}
              onOpenVaultPicker={() => setPickerOpen(true)}
              price={priceToSend}
              previewCount={previewCount}
              onPreviewCountChange={set("previewCount")}
            />
          )}

          {!allModels && (
            <div>
              <IfLabel htmlFor={priceId}>Price (USD)</IfLabel>
              <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
                <IfInput
                  id={priceId}
                  type="text"
                  inputMode="decimal"
                  value={price}
                  onChange={(e) => set("price")(sanitizePriceInput(e.target.value))}
                  placeholder="0 (free)"
                  className="w-40 max-md:text-base"
                />
                {isPPV ? (
                  <span className="inline-flex items-center gap-1 text-[14px] text-warn">
                    <Lock className="h-3.5 w-3.5" aria-hidden />PPV {fmtPrice(Math.round(priceToSend * 100))}
                  </span>
                ) : (
                  <span className="text-[14px] text-muted">Free</span>
                )}
                {isPPV && (
                  <label className="flex cursor-pointer select-none items-center gap-2 text-[14px] text-fg">
                    <input
                      type="checkbox"
                      checked={lockedText}
                      onChange={(e) => set("lockedText")(e.target.checked)}
                      className="h-4 w-4 accent-accent"
                    />
                    Lock the text too (fan must pay to read)
                  </label>
                )}
              </div>
            </div>
          )}

          <ScheduleField
            scope={allModels ? "all-models" : accountId}
            value={schedule}
            onChange={set("schedule")}
          />

          <div>
            <IfLabel htmlFor={funnelSelectId}>Funnel follow-up</IfLabel>
            <IfNativeSelect
              id={funnelSelectId}
              value={funnelId ?? ""}
              onChange={(e) => set("funnelId")(e.target.value ? Number(e.target.value) : null)}
              className="w-full min-w-0"
            >
              <option value="">None (just send the opener)</option>
              {(funnelsQ.data ?? []).map((f) => (
                <option key={f.id} value={f.id}>
                  {f.name} ({f.step_count} step{f.step_count === 1 ? "" : "s"})
                </option>
              ))}
            </IfNativeSelect>
            {funnelId != null && (
              <IfHelp>
                After this opener lands, the funnel walks its reply / PPV steps per replying fan.
              </IfHelp>
            )}
          </div>

          <AudiencePanel
            form={form}
            dispatch={dispatch}
            customLists={customLists}
            listsLoading={listsQ.isLoading}
            smartLists={smartLists}
          />

          {online && (
            <OnlineTargetingPanel
              form={form}
              set={set}
              onlineCount={onlineCount}
              labelExtras={labelExtras}
              isScheduled={isScheduled}
            />
          )}
          </fieldset>

          {gifFailures && (
            <div role="alert" className="space-y-1 rounded-md border border-border p-3 text-[12px]">
              <div className="text-[14px] font-medium">
                Broadcast sent — {gifFailures.length} of {pickedGifs.length - 1} extra GIF
                send{pickedGifs.length === 2 ? "" : "s"} failed
              </div>
              {gifFailures.map((g) => (
                <div key={g.id} className="text-err">GIF {g.title || g.id} — {g.error}</div>
              ))}
            </div>
          )}

          {results && (
            <FanOutResults
              results={results} noun="broadcast" locked={locked} busy={send.isPending}
              onStartOver={() => dispatch({ type: "discardResults" })}
            />
          )}
        </div>
      </IfModal>

      <VaultPicker
        open={pickerOpen}
        onClose={() => setPickerOpen(false)}
        accountId={accountId}
        fanId={null}
        initialSelectedIds={attached.map((m) => m.id)}
        onConfirm={(p) => {
          set("attached")(p);
          setPickerOpen(false);
        }}
      />
    </>
  );
}
