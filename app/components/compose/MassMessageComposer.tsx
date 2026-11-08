"use client";

/**
 * MassMessageComposer — modal for broadcasting a single message to many
 * fans via POST /api/of/v2/messages/queue. With `scheduled_date` the
 * relay routes to schedule_mass_message; without it, send_mass_message
 * fires immediately.
 *
 * Audience mirrors the desktop app: include vs exclude columns. Include
 * accepts any combination of OF's five system audiences (fans / recent /
 * following / rebill_off / tagged) and any of the model's custom fan
 * lists. Exclude is custom-lists-only (OF doesn't accept system audience
 * names in excludeUserLists).
 *
 * Callers mount it only while the modal is open and unmount it on close, so
 * closing it is the reset: nothing carries over to the next open.
 */

import { useCallback, useEffect, useId, useReducer, useRef, useState } from "react";
import { Lock, X } from "lucide-react";

import { usePlatformAccounts } from "@/hooks/useAccounts";
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
import { fanOutLocked, includedTargets } from "./fanOut";
import { MediaTray } from "./MediaTray";
import { useOfRichAllowed } from "@/hooks/useOfRichAllowed";
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

interface MassMessageComposerProps {
  onClose: () => void;
  /** "online" reveals the live-targeting panel (online-only, unread, recent-
   *  chat include, recent-activity excludes, auto-unsend) and titles the modal
   *  "Mass Online". "standard" is the classic list-based broadcast. */
  mode?: "standard" | "online";
  /** The account the form opens on (a single-Creator scope's); the picker,
   *  all-models switch and schedule field stay. */
  forcedAccountId?: string;
  /** Tag what Infloww's OF mass message lacks as "Inflowwww extra": the
   *  per-broadcast Auto-unsend (Infloww offers per-message Auto-unsend on
   *  Priority mass and Automated messages only). Growth > Smart Messages
   *  asks; Messages Pro's New menu does not, because its extras audit admits
   *  only catalogued names (lib/openinflowwwwExtras). */
  labelExtras?: boolean;
}

/** The form's automatic actions (no user edit): the audience seeding and the GIF strip opening. */
const isMassSeed = (a: MassAction, s: MassForm) =>
  isAudienceSeed(a, s) || (a.type === "field" && a.k === "gifPickerOpen");

export function MassMessageComposer({
  onClose,
  mode = "standard",
  forcedAccountId,
  labelExtras = false,
}: MassMessageComposerProps) {
  const online = mode === "online";
  const activeAccounts = usePlatformAccounts();
  // The composers' shared include set (useAllModelsInclude) — a model
  // un-checked in any composer's chip strip is omitted from a broadcast here.
  const { isIncluded } = useAllModelsInclude();
  // Sends without an explicit employeeId attribute to the Automation system
  // employee (id=2). See memory: project_x_employee_id_pipeline.md — relay's
  // X-Employee-Id header is opt-in per call, no global injector.
  const { current: currentEmployee } = useEmployee();
  // The whole form (massMessageReducer).
  const [form, rawDispatch] = useReducer(massMessageReducer, forcedAccountId ?? null, initMassForm);
  // The user's dispatch: anything but the seeding and the GIF strip's open/close touches the form (Escape keeps it).
  const { touched, dispatch } = useTouched(form, rawDispatch, isMassSeed);
  const {
    allModels, accountId, text, attached, price, previewCount, lockedText, schedule, funnelId, progress, results,
    gifFailures, taggedCreators, pickedGifs, gifPickerOpen,
  } = form;
  // A round in flight, or a model sent this broadcast: the content is locked (compose/fanOut).
  const locked = fanOutLocked(form);
  // The one setter for plain fields: `set("price")(v)`.
  const set = useCallback(
    <K extends MassField>(k: K) => (v: MassForm[K]) => dispatch(fieldAction(k, v)),
    [dispatch],
  );
  // Stable: AccountPicker's auto-seed effect depends on it.
  const setAccountId = useCallback((id: string) => dispatch({ type: "setAccount", id }), [dispatch]);
  // Optional funnel: when set, the send_mass_message automation walks this
  // funnel's reply/PPV steps per replying fan after the opener lands. Resolved
  // server-side by funnel_id (send_mass_message._resolve_funnel) — only the
  // opener (this message) is sent now. Inert on the live OF-queue path.
  const funnelsQ = useFunnels();
  const [pickerOpen, setPickerOpen] = useState(false);
  // Live online count: OnlyFans' online subscribers list (Messages Pro's
  // Online Fans read, same cache), one page re-read every minute while the
  // Mass Online panel is open for one account. "20+" on a full page.
  const onlineCountQ = useOnlineSubscribers(online && !allModels ? accountId : null, 60_000);
  const onlineCount = onlineCountQ.data ? onlineCountLabel(onlineCountQ.data) : null;
  const textRef = useRef<ComposeTextBoxHandle | null>(null);
  // OF rich text: OnlyFans accounts only (all-models: the platform's, whose accounts these all are).
  const allowRich = useOfRichAllowed(allModels ? null : accountId);
  const priceId = useId();
  const funnelSelectId = useId();

  // Shared with the PPV Library broadcast picker: one OF call (same cache key),
  // one definition of "custom list". `...listsQ` keeps the raw query fields
  // (data/isLoading/isFetching) this component still reads directly.
  const { customLists, ...listsQ } = useFanLists(accountId);

  // Auto-select the standing MASSDMEXCLUDE list (audience/audienceReducer
  // `massExcludeListId`) into the exclude set — so every mass send skips it by
  // default; the operator can untick it for a one-off. The reducer's
  // `seedExclude` decides (once per account per audience reset, never in
  // all-models, never a stale account); this only reports the CURRENT
  // account's lists once they settle (guarded on !isFetching, not stale ones).
  useEffect(() => {
    if (!accountId || listsQ.isLoading || listsQ.isFetching) return;
    rawDispatch({ type: "seedExclude", accountId, listId: massExcludeListId(listsQ.data ?? []) });
    // allModels / seededFor: an audience reset re-arms the seed.
  }, [accountId, allModels, form.seededFor, listsQ.isLoading, listsQ.isFetching, listsQ.data]);

  // ── Smart Lists (saved segments) as include/exclude audiences ──────────
  // A Smart List is an internal fan-id segment (spend/recency/status/tag). On
  // send we resolve the picked lists to explicit userIds / excludedUsers, so a
  // saved segment sharpens any blast. The picks are form state (the reducer
  // resets them with the rest of the audience); the query is the segment list,
  // disabled in all-models mode (segments are per-account).
  const smartLists = useSmartLists(allModels ? null : accountId).data ?? [];

  // All-models broadcasts force free + unlocked-text (ask #4). For per-employee
  // sends, a typed price > 0 is the sole paid signal — clearing the field is
  // how the user opts back into a free send.
  const priceToSend = effectivePrice(form);

  // No auto-seed: 0 previews is a valid choice on paid broadcasts (every
  // tile locked). The ± stepper lets the user opt into a leading free
  // teaser when they want one.

  // Honour the shared include set: models the user unchecked in a
  // composer's chip strip are dropped from the broadcast fan-out; a model
  // that already took this broadcast (a partial fan-out's success) is not
  // sent it again.
  const { included: broadcastAccounts, targets } = includedTargets(activeAccounts, isIncluded, results);
  // The accounts a send goes out from.
  const sendFrom = allModels ? targets : accountId ? [accountId] : [];

  // Growth > Sensitive words: like Infloww's mass message and Smart Message
  // editors, a listed word in the text is shown under it and refuses the send.
  const sensitiveHits = useSensitiveHits(isOfHtml(text) ? ofPlainText(text) : text, allModels ? null : accountId);

  // The one validity check — the footer button, its reason line and the send
  // mutation all read this result (massMessageReducer `validateMass`).
  const invalid = validateMass(form, {
    broadcastCount: sendFrom.length,
    sensitive: sensitiveHits.length > 0,
  });

  const send = useMassSend({
    form, dispatch: rawDispatch, online, included: broadcastAccounts.map((a) => a.id), invalid, employeeId: currentEmployee?.id,
    onClose,
  });

  function close() {
    if (!send.isPending) onClose();
  }

  function onEmoji(em: string) {
    if (textRef.current) textRef.current.insert(em);
    else dispatch({ type: "appendText", v: em });
  }

  function onPickTemplate(t: PickedTemplate) {
    // Snapshot semantics (lib/composeDraft applyTemplate): text, media,
    // preview count, price + lock and GIF are replaced wholesale.
    // An OnlyFans account keeps a formatted script's markup; Fansly gets its plain text.
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
        // Escape never drops a draft the user touched; × and Cancel still close.
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
            onClick={() => {
              if (confirm(confirmPrompt(form, sendFrom.length))) send.mutate();
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
          {/* All-models switch — pivots the modal between single-account
           *  mode (vault + custom-list audiences) and fan-out mode
           *  (uploads only + system audiences only). */}
          <IncludeModelsChips
            noun="broadcast" allModels={allModels} locked={locked}
            onAllModels={(on) => dispatch({ type: "setAllModels", on })}
            accountId={accountId} onAccount={setAccountId}
          />

          {/* The content — locked (disabled) once a model sent the broadcast. */}
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
            {/* Toolbar — same composer features as the chat: recent-
             *  emojis quick row, full emoji picker, GIF picker,
             *  saved-template picker, @-tag creators picker. */}
            {/* The pickers portal above the dialog: Escape in their search boxes is theirs (useModalFocus). */}
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

          {/* Funnel — optional automated follow-up. Only the send_mass_message
           *  automation (compose-into-rule path) walks the steps; a one-off
           *  live OF-queue broadcast ignores it. */}
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

          {/* Online / live-targeting panel — only in "Mass Online" mode. */}
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

          {/* The broadcast landed but these trailing GIF sends failed. */}
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

          {/* Per-account fan-out summary, shown after a partial-success run. */}
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
