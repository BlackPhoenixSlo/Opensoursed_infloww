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

import { useCallback, useEffect, useReducer, useRef, useState } from "react";

import { usePlatformAccounts } from "@/hooks/useAccounts";
import { onlineCountLabel, useOnlineSubscribers } from "@/hooks/useOnlineSubscribers";
import { useAllModelsInclude } from "@/hooks/useAllModelsInclude";
import { useSmartLists } from "@/hooks/useSmartLists";
import { useFunnels } from "@/hooks/useFunnels";
import { useEmployee } from "@/contexts/EmployeeContext";
import { VaultPicker } from "@/components/chat/VaultPicker";
import { EmojiPickerButton, EmojiQuickRow, insertAtCursor } from "@/components/chat/EmojiBar";
import { GifPickerButton, GifPickerStrip } from "@/components/chat/GifPicker";
import { TemplatePicker, type PickedTemplate } from "@/components/chat/TemplatePicker";
import { TagCreatorsPicker, TaggedCreatorChips } from "@/components/chat/TagCreatorsPicker";
import { useFanLists } from "@/components/audience/fanLists";
import { massExcludeListId } from "@/components/audience/audienceReducer";
import { useSensitiveHits } from "@/lib/sensitiveWords";
import { SensitiveWordWarning } from "@/components/chat/SensitiveWordWarning";

import { sanitizePriceInput } from "@/lib/priceInput";

import { AudiencePanel } from "./AudiencePanel";
import { FanOutResults, FanOutStatus } from "./FanOutResults";
import { IncludeModelsChips } from "./IncludeModelsChips";
import { fanOutLocked, includedTargets } from "./fanOut";
import { MediaTray } from "./MediaTray";
import { OnlineTargetingPanel } from "./OnlineTargetingPanel";
import { ScheduleField } from "./ScheduleField";
import { useMassSend } from "./useMassSend";
import {
  confirmPrompt, effectivePrice, fieldAction, gifNote, initMassForm, massMessageReducer, validateMass,
  type MassField, type MassForm,
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
  const [form, dispatch] = useReducer(massMessageReducer, forcedAccountId ?? null, initMassForm);
  const {
    allModels, accountId, text, attached, price, previewCount, lockedText, schedule, funnelId, progress, results,
    gifFailures, taggedCreators, pickedGifs, gifPickerOpen,
  } = form;
  // A round in flight, or a model sent this broadcast: the content is locked (compose/fanOut).
  const locked = fanOutLocked(form);
  // The one setter for plain fields: `set("price")(v)`.
  const set = useCallback(
    <K extends MassField>(k: K) => (v: MassForm[K]) => dispatch(fieldAction(k, v)),
    [],
  );
  // Stable: AccountPicker's auto-seed effect depends on it.
  const setAccountId = useCallback((id: string) => dispatch({ type: "setAccount", id }), []);
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
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);

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
    dispatch({ type: "seedExclude", accountId, listId: massExcludeListId(listsQ.data ?? []) });
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
  const sensitiveHits = useSensitiveHits(text, allModels ? null : accountId);

  // The one validity check — the footer button, its reason line and the send
  // mutation all read this result (massMessageReducer `validateMass`).
  const invalid = validateMass(form, {
    broadcastCount: sendFrom.length,
    sensitive: sensitiveHits.length > 0,
  });

  const send = useMassSend({
    form, dispatch, online, included: broadcastAccounts.map((a) => a.id), invalid, employeeId: currentEmployee?.id,
    onClose,
  });

  function close() {
    if (!send.isPending) onClose();
  }

  function onEmoji(em: string) {
    const ta = textareaRef.current;
    if (!ta) {
      dispatch({ type: "appendText", v: em });
      return;
    }
    insertAtCursor(ta, text, em, set("text"));
  }

  function onPickTemplate(t: PickedTemplate) {
    // Snapshot semantics (lib/composeDraft applyTemplate): text, media,
    // preview count, price + lock and GIF are replaced wholesale.
    dispatch({ type: "pickTemplate", t });
    setTimeout(() => textareaRef.current?.focus(), 0);
  }

  const isPPV = priceToSend > 0;
  const isScheduled = !!schedule;

  return (
    <div
      className="fixed inset-0 z-50 bg-black/50 grid place-items-center p-0 sm:p-4"
      onClick={close}
    >
      {/* min-h-0 / min-w-0: a grid item's auto minimum is its content, so on a
       *  phone (h-full, no max-h) the panel grew to the form's full height and
       *  width, past the screen, and the body never scrolled to Send. */}
      <div
        onClick={(e) => e.stopPropagation()}
        className="min-h-0 min-w-0 w-full h-full sm:h-auto max-w-none sm:max-w-[640px] max-h-none sm:max-h-[90vh] flex flex-col bg-panel border-0 sm:border border-border rounded-none sm:rounded-xl shadow-2xl"
      >
        <header className="px-4 py-3 border-b border-border flex items-center justify-between">
          <h2 className="text-sm font-semibold">
            {online ? "New Mass Online message" : "New mass message"}
          </h2>
          <button
            type="button"
            onClick={close}
            className="text-fg-dim hover:text-fg text-lg leading-none w-11 h-11 -mr-2 -my-2 grid place-items-center shrink-0 md:w-auto md:h-auto md:mr-0 md:my-0 md:inline"
            title="Close"
          >×</button>
        </header>

        <div className="flex-1 overflow-y-auto p-4 space-y-3">
          {/* All-models switch — pivots the modal between single-account
           *  mode (vault + custom-list audiences) and fan-out mode
           *  (uploads only + system audiences only). */}
          <IncludeModelsChips
            noun="broadcast" allModels={allModels} locked={locked}
            onAllModels={(on) => dispatch({ type: "setAllModels", on })}
            accountId={accountId} onAccount={setAccountId}
          />

          {/* The content — locked (disabled) once a model sent the broadcast. */}
          <fieldset disabled={locked} className="min-w-0 space-y-3 disabled:opacity-60">
          <div className="space-y-1.5">
            <textarea
              ref={textareaRef}
              value={text}
              onChange={(e) => set("text")(e.target.value)}
              placeholder="What's the broadcast?"
              rows={4}
              className="w-full bg-bg border border-border rounded-md px-3 py-2 text-base md:text-sm placeholder:text-muted focus:outline-none focus:border-accent resize-y"
            />
            <SensitiveWordWarning hits={sensitiveHits} />
            {/* Toolbar — same composer features as the chat: recent-
             *  emojis quick row, full emoji picker, GIF picker,
             *  saved-template picker, @-tag creators picker. */}
            <div className="flex items-center gap-1.5 flex-wrap">
              <EmojiQuickRow onInsert={onEmoji} />
              <EmojiPickerButton align="left" onInsert={onEmoji} />
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
              <div className="flex items-center gap-1.5 flex-wrap bg-bg/60 border border-border rounded-md px-2 py-2">
                <span className="text-[10px] uppercase tracking-wide text-fg-dim mr-1">gifs</span>
                {pickedGifs.map((g) => (
                  <div key={g.id} className="relative w-14 h-14 rounded-md overflow-hidden border border-border bg-bg-elev-1">
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img src={g.thumbUrl} alt={g.title || "GIF"} className="w-full h-full object-cover" />
                    <button
                      type="button"
                      onClick={() => dispatch({ type: "removeGif", id: g.id })}
                      className="absolute top-0.5 right-0.5 w-6 h-6 md:w-4 md:h-4 rounded-full bg-black/70 text-white grid place-items-center text-[10px] opacity-80 hover:opacity-100"
                      aria-label="Remove GIF"
                    >
                      ✕
                    </button>
                  </div>
                ))}
                <span className="ml-auto text-[10px] text-fg-dim">
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
            <>
              <div className="flex items-center gap-2">
                <label className="text-xs text-fg-dim shrink-0">Price (USD):</label>
                <input
                  type="text"
                  inputMode="decimal"
                  value={price}
                  onChange={(e) => set("price")(sanitizePriceInput(e.target.value))}
                  placeholder="0 (free)"
                  className="flex-1 bg-bg border border-border rounded-md px-2 py-1.5 text-base md:text-xs focus:outline-none focus:border-accent"
                />
                <span className={isPPV ? "text-warn text-[11px]" : "text-fg-dim text-[11px]"}>
                  {isPPV ? `🔒 PPV ${fmtPrice(Math.round(priceToSend * 100))}` : "free"}
                </span>
              </div>
              {isPPV && (
                <label className="flex items-center gap-2 text-xs text-fg-dim cursor-pointer">
                  <input
                    type="checkbox"
                    checked={lockedText}
                    onChange={(e) => set("lockedText")(e.target.checked)}
                  />
                  Lock the text too (fan must pay to read)
                </label>
              )}
            </>
          )}

          <ScheduleField
            scope={allModels ? "all-models" : accountId}
            value={schedule}
            onChange={set("schedule")}
          />

          {/* Funnel — optional automated follow-up. Only the send_mass_message
           *  automation (compose-into-rule path) walks the steps; a one-off
           *  live OF-queue broadcast ignores it. */}
          <div className="flex items-center gap-2">
            <label className="text-xs text-fg-dim shrink-0">Funnel follow-up:</label>
            <select
              value={funnelId ?? ""}
              onChange={(e) => set("funnelId")(e.target.value ? Number(e.target.value) : null)}
              className="min-w-0 flex-1 bg-bg border border-border rounded-md px-2 py-1.5 text-base md:text-xs focus:outline-none focus:border-accent"
            >
              <option value="">— none (just send the opener) —</option>
              {(funnelsQ.data ?? []).map((f) => (
                <option key={f.id} value={f.id}>
                  {f.name} ({f.step_count} step{f.step_count === 1 ? "" : "s"})
                </option>
              ))}
            </select>
          </div>
          {funnelId != null && (
            <div className="text-[10px] text-fg-dim -mt-1">
              After this opener lands, the funnel walks its reply / PPV steps per
              replying fan (resolved by the automation, not this live send).
            </div>
          )}

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
            <div role="alert" className="border border-border rounded-md p-3 space-y-1 text-[11px]">
              <div className="font-medium">
                Broadcast sent — {gifFailures.length} of {pickedGifs.length - 1} extra GIF
                send{pickedGifs.length === 2 ? "" : "s"} failed
              </div>
              {gifFailures.map((g) => (
                <div key={g.id} className="text-err">✗ GIF {g.title || g.id} — {g.error}</div>
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

        <footer className="px-4 py-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] sm:pb-3 border-t border-border flex items-center justify-end gap-2">
          <FanOutStatus
            progress={progress} verb="Sending" invalid={invalid} error={send.error?.message ?? null} results={results}
          />
          <button
            type="button"
            onClick={onClose}
            disabled={send.isPending}
            className="text-xs px-3 py-1.5 rounded border border-border hover:border-border-light text-fg-dim hover:text-fg disabled:opacity-50"
          >
            {gifFailures ? "Close" : "Cancel"}
          </button>
          <button
            type="button"
            onClick={() => {
              if (confirm(confirmPrompt(form, sendFrom.length))) send.mutate();
            }}
            disabled={send.isPending || invalid !== null}
            title={invalid ?? undefined}
            className="text-xs px-4 py-1.5 rounded bg-accent text-white font-medium hover:bg-accent-hover disabled:opacity-50"
          >
            {send.isPending
              ? (isScheduled ? "Scheduling…" : "Broadcasting…")
              : (isScheduled ? "Schedule" : "Broadcast")}
          </button>
        </footer>
      </div>

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
    </div>
  );
}

