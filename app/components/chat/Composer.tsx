"use client";


import { useEffect, useLayoutEffect, useReducer, useRef, useState } from "react";

import { cn } from "@/lib/utils";
import { MP } from "@/lib/messagesPro";
import { type VaultMedia } from "@/lib/relay";
import { type FanId } from "@/lib/fanId";
import { isImeComposing } from "@/lib/ime";
import { readChatRich, useChatDraft, writeChatRich } from "@/lib/chatDrafts";
import { useFanVaultHistory } from "@/hooks/useFanVaultHistory";
import { scriptPickWarning } from "@/lib/messageScripts";
import { isUploadable, useComposerUploads } from "@/hooks/useComposerUploads";
import { useReorder } from "@/hooks/useReorder";
import { SCRIPT_SOURCE } from "@/lib/chatSlots";
import { EXECUTOR_MAX_MINUTES, type SendOutcome } from "@/hooks/useSendMessage";
import { useQueueKeys } from "@/hooks/useQueueKeys";
import { markScriptSent } from "@/hooks/useSavedReplies";

import dynamic from "next/dynamic";

import { EmojiPickerButton, insertAtCursor } from "./EmojiBar";
import { EmojiFavouritesButton, QuickEmojiRow } from "./EmojiFavourites";
import { CopilotPicker } from "./CopilotPicker";
import { GifPickerButton, GifPickerStrip } from "./GifPicker";
import { TemplatePicker, type PickedTemplate } from "./TemplatePicker";
import { isOfHtml, OF_TEXT_MAX, ofPreviewText } from "@/lib/ofRichText";
import { editorPlain } from "@/lib/ofRichTextEditor";
import { PLAIN_MODE, richMode } from "@/lib/ofRichMode";
import { OfRichTextEditor, type OfRichTextEditorHandle } from "@/components/ui/OfRichTextEditor";
import { useCanOrFallback } from "@/hooks/useCan";
import { TagCreatorsPicker, TaggedCreatorChips, type TaggedCreatorChoice } from "./TagCreatorsPicker";
import {
  EMPTY_DRAFT, afterRefusedSchedule, buildSendArgs, richFromEditor, richText, canBeFreePreview, canSend, composerDraft, isEmptyLiveDraft,
  composerView, sentReplyId, type FullDraft, type LiveDraft, type SendArgs,
} from "./composerDraft";
import { gifPlan, scheduledToast } from "./composerSubmit";
import { ComposerToolbar } from "./ComposerToolbar";
import { OutboundTranslationStrip, outboundTranslationKey, useOutboundTranslation } from "./OutboundTranslation";
import { FreePreviews, PpvRow, toLocalInput } from "./PpvRow";
import { PpvTiles } from "./PpvTiles";
import {
  dismissRefusedOffer, dispatchRefusedOffers, isOfferHere, offerRefusedSchedule, readRefusedOffers, useRefusedOffers,
  type RefusedOffer,
} from "./refusedOffers";
import { useBlobPreviews } from "./useBlobPreviews";
import { useScriptSuggestions } from "./useScriptSuggestions";
import { TimedMessagePopover, TimedReminderNotice } from "./TimedMessagePopover";
import { ReplyStrip, type QuotedReply } from "./ReplyStrip";
import { SensitiveWordWarning } from "./SensitiveWordWarning";
import { useSensitiveHits } from "@/lib/sensitiveWords";
import { claimSendGap, SEND_GAP_NOTE } from "@/lib/sendGuards";
import { ifConfirm } from "@/components/ui/ifConfirm";

export type { SendArgs } from "./composerDraft";

const VaultPicker = dynamic(
  () => import("./VaultPicker").then((m) => m.VaultPicker),
  { ssr: false },
);

const StepAction = SCRIPT_SOURCE?.StepAction ?? null;

export interface ComposerApi {
  applyTemplate(t: PickedTemplate): void;
}

export interface ComposerProps {
  accountId: string | null;
  fanId: FanId;
  fanSpokeLastAt?: string | null;
  fanName?: string | null;
  onSend: (args: SendArgs) => void | Promise<SendOutcome | undefined | void>;
  disabled?: boolean;
  inflight?: number;
  placeholder?: string;
  canSend?: boolean;
  cannotSendReason?: string | null;
  quoted?: QuotedReply | null;
  onClearQuoted?: () => void;
  composerApiRef?: React.MutableRefObject<ComposerApi | null>;
  onAdvance?: (dir: 1 | -1) => void;
  onHoldChange?: (held: boolean) => void;
  enterAdvances?: boolean;
}

export function Composer({
  accountId, fanId, fanSpokeLastAt = null, fanName = null, onSend, disabled, inflight = 0, placeholder,
  canSend: chatCanSend = true, cannotSendReason,
  quoted, onClearQuoted,
  composerApiRef, onAdvance, onHoldChange, enterAdvances,
}: ComposerProps) {
  const [text, setText] = useChatDraft(accountId, fanId);
  const [slashClosedFor, setSlashClosedFor] = useState<string | null>(null);
  const slashQuery = /^\/\S*$/.test(text) && text !== slashClosedFor ? text.slice(1) : null;
  const allowRich = useCanOrFallback(accountId, "rich_text");
  const [draft, act] = useReducer(composerDraft, null, () => {
    const rich = allowRich ? readChatRich(accountId, fanId) : null;
    return { ...EMPTY_DRAFT, rich, mode: richMode(PLAIN_MODE, { type: "loaded", formatted: !!rich, allowed: allowRich }) };
  });
  const savedRich = useRef(draft.rich);
  // Never save while rich text is off (cold accounts cache): this mount never read the stored markup, so null would wipe it.
  useEffect(() => {
    if (!allowRich || draft.rich === savedRich.current) return;
    savedRich.current = draft.rich;
    writeChatRich(accountId, fanId, draft.rich);
  }, [allowRich, accountId, fanId, draft.rich]);
  const richHtml = richText(draft, text);
  const { price, priceOpen, lockedText, attached, scheduleOpen, scheduleAt, taggedCreators, pickedGifs } = draft;
  const latestRef = useRef<LiveDraft | null>({ text, draft, uploadChips: 0 });
  const [gifPickerOpen, setGifPickerOpen] = useState(false);
  useEffect(() => () => {
    latestRef.current = null;
  }, []);
  const previews = useBlobPreviews(attached);
  const setTags = (tags: TaggedCreatorChoice[]) => act({ type: "setTags", tags });
  const [pickerOpen, setPickerOpen] = useState(false);
  const [sendToast, setSendToast] = useState<string | null>(null);
  const { offers: refusedOffers } = useRefusedOffers();
  const toastTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const editorRef = useRef<OfRichTextEditorHandle | null>(null);
  const richOn = allowRich && draft.mode.rich;
  const focusInput = () => (editorRef.current ? editorRef.current.focus() : textareaRef.current?.focus());
  const fanVaultQ = useFanVaultHistory(accountId, fanId);

  const scripts = useScriptSuggestions(accountId, fanId, fanSpokeLastAt);

  const uploads = useComposerUploads(accountId, (media) => act({ type: "uploaded", media }));
  const fullDraft = { text, draft, uploadChips: uploads.chips.length };
  useLayoutEffect(() => {
    latestRef.current = fullDraft;
  });
  const uploadDisabled = !!disabled || !accountId;
  const sendCtx = {
    text, disabled, chatCanSend, uploading: uploads.uploading, uploadFailed: !!uploads.failed, now: Date.now(),
  };
  const view = composerView(draft, { ...sendCtx, uploadChips: uploads.chips.length });
  const outbound = useOutboundTranslation(accountId, fanId, text);
  const sensitiveHits = useSensitiveHits(`${text}\n${outbound.translated ?? ""}`, accountId);

  const reorder = useReorder(attached, (next) => act({ type: "reorder", attached: next }), (m) => m.id);
  const blocked = !chatCanSend;
  const queue = useQueueKeys({ accountId, fanId, held: view.held, onAdvance, onHoldChange, enterAdvances });

  function showToast(msg: string, opts: { ms?: number } = {}) {
    if (toastTimerRef.current) clearTimeout(toastTimerRef.current);
    setSendToast(msg);
    toastTimerRef.current = setTimeout(() => setSendToast(null), opts.ms ?? 6000);
  }

  function putBack(fd: FullDraft) {
    setText(fd.text);
    act({ type: "restore", snapshot: fd.draft });
  }

  function restoreOffer(offer: RefusedOffer) {
    putBack(offer);
    dispatchRefusedOffers({ type: "removed", id: offer.id });
  }

  function dismissOffer(offer: RefusedOffer) {
    previews.forget(dismissRefusedOffer(offer, attached.map((m) => m._localPreview)));
  }

  useEffect(() => () => {
    if (toastTimerRef.current) clearTimeout(toastTimerRef.current);
  }, []);

  async function submit(opts?: { delayMinutes?: number; text?: string; advance?: boolean }) {
    const body = (opts?.text ?? text).trim();
    const now = Date.now();
    if (!canSend(draft, { ...sendCtx, text: body, now })) return;
    const args = buildSendArgs(draft, {
      text: body, delayMinutes: opts?.delayMinutes, now, plainOnly: !allowRich || opts?.text !== undefined,
    });
    const { trailing: trailingGifs } = gifPlan(pickedGifs);
    // Infloww's send-rate guard: a send at once within 3 s of the model's last one stays in the composer.
    if (!args.scheduledAt && !claimSendGap(accountId)) {
      showToast(`⚠ ${SEND_GAP_NOTE}`);
      return;
    }
    const refused: FullDraft = { text, draft };
    const epoch = readRefusedOffers().epoch;
    previews.markSent(draft.attached);
    emptyComposer("sent");
    if (!args.scheduledAt) {
      const pending = uploads.handOff();
      if (pending.length > 0) args.uploads = pending;
    }
    focusInput();
    const advanceScript = scripts.afterSend(refused.draft.script);
    let sent: SendOutcome | undefined | void;
    try {
      const sending = onSend(args);
      if (opts?.advance) queue.advanceAfter(sending, !!args.scheduledAt);
      sent = await sending;
    } catch (err) {
      // An immediate send carries its failure on the red bubble (with retry); only scheduled paths reject here.
      if (!args.scheduledAt) throw err;
      const why = err instanceof Error && err.message ? err.message : "unknown error";
      if (afterRefusedSchedule(latestRef.current) === "restore") {
        putBack(refused);
        showToast(`⚠ Not scheduled — ${why}`);
      } else {
        const shown = latestRef.current?.draft.attached.map((m) => m._localPreview) ?? [];
        previews.forget(offerRefusedSchedule({ ...refused, accountId, fanId, fanName, why }, epoch, shown));
      }
      return;
    }
    if (args.scheduledAt) showToast(scheduledToast(args.scheduledAt, Date.now(), EXECUTOR_MAX_MINUTES));
    advanceScript?.(!!sent?.failure);
    const replyId = sentReplyId(refused.draft);
    if (replyId != null && sent && !args.scheduledAt) {
      void sent.settled.then((ended) => (ended.sent ? markScriptSent(replyId) : undefined));
    }
    const sendGifs = async () => {
      for (const g of trailingGifs) await onSend({ text: "", giphyId: g.id });
    };
    // Extra GIFs go only after the send landed, in pick order, so the Fan gets them after it.
    if (args.uploads && sent) {
      void sent.settled.then((ended) => (ended.sent ? sendGifs() : undefined));
    } else {
      await sendGifs();
    }
  }

  useLayoutEffect(() => {
    const ta = textareaRef.current;
    if (!ta) return;
    ta.style.height = "auto";
    if (ta.scrollHeight) ta.style.height = `${ta.scrollHeight}px`;
  }, [text]);

  useEffect(() => {
    focusInput();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- once per mount
  }, []);


  function onKeyDown(e: React.KeyboardEvent<HTMLElement>) {
    // An IME's Enter picks its candidate: no key here sends or moves on.
    if (isImeComposing(e)) return;
    if (e.key === "Enter" && !e.shiftKey && slashQuery !== null) {
      e.preventDefault();
      return;
    }
    const advance = queue.isAdvanceKey(e);
    if (outboundTranslationKey(e, outbound, setText, (t) => sendTranslation(t, advance))) return;
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit({ advance });
    }
    queue.arrowKey(e, text === "" && !quoted);
  }

  function sendTranslation(translated: string, advance = false) {
    submit({ text: translated, advance });
  }

  function onRichChange(value: string) {
    const next = richFromEditor(value, editorPlain);
    setText(next.text);
    act({ type: "setRich", rich: next.rich });
    if (next.text !== slashClosedFor) setSlashClosedFor(null);
  }

  function onAa() {
    act({ type: "aa" });
    setTimeout(focusInput, 0);
  }

  function onEmoji(em: string) {
    if (editorRef.current) return editorRef.current.insert(em);
    const ta = textareaRef.current;
    if (!ta) {
      setText((t) => t + em);
      return;
    }
    insertAtCursor(ta, text, em, setText);
  }

  const openVault = () => setPickerOpen(true);

  /** The picker pre-selects from `attached`, so its pick replaces them
   *  wholesale; media with a suggested price (set in /vault) price the bundle
   *  at the highest of them. */
  function onPicked(picked: VaultMedia[]) {
    act({ type: "pickVault", picked });
  }

  function removeAttachment(id: number) {
    act({ type: "removeAttachment", id });
  }

  function clearPpvRow() {
    act({ type: "clearPpv" });
    uploads.clear();
  }

  function emptyComposer(type: "sent" | "clear") {
    setText("");
    setSlashClosedFor(null);
    savedRich.current = null;
    writeChatRich(accountId, fanId, null);
    act({ type });
  }

  function clearDraft() {
    emptyComposer("clear");
    onClearQuoted?.();
    uploads.clear();
    focusInput();
  }

  function onDropFiles(e: React.DragEvent) {
    const files = Array.from(e.dataTransfer?.files ?? []);
    if (files.length === 0 || uploadDisabled) return;
    e.preventDefault();
    uploads.add(files);
  }

  function onPaste(e: React.ClipboardEvent<HTMLElement>) {
    if (Array.from(e.clipboardData?.types ?? []).includes("text/plain")) return;
    const files = Array.from(e.clipboardData?.files ?? []).filter(isUploadable);
    if (files.length === 0 || uploadDisabled) return;
    e.preventDefault();
    uploads.add(files);
  }

  function onPickSuggestion(suggestion: string) {
    if (editorRef.current) return editorRef.current.insert(suggestion);
    const ta = textareaRef.current;
    if (ta) insertAtCursor(ta, text, suggestion, setText);
    else setText((t) => (t ? `${t} ${suggestion}` : suggestion));
  }

  function onStepDraft(draft: string) {
    act({ type: "dropScript" });
    onPickSuggestion(draft);
  }

  async function onPickScript(t: PickedTemplate) {
    const warning = scriptPickWarning(t, fanVaultQ.data?.by_media);
    if (warning && !(await ifConfirm(`${warning}\n\nInsert it anyway?`))) return;
    onPickTemplate(t);
  }

  function onPickTemplate(t: PickedTemplate) {
    setText(t.text);
    act({ type: "pickTemplate", t, allowRich });
    setTimeout(focusInput, 0);
  }

  const composerApiBoxRef = useRef<ComposerApi>({
    applyTemplate: () => { },
  });
  // Updated through a stable box so onPickTemplate's identity churn does not re-fire the effect below.
  composerApiBoxRef.current.applyTemplate = onPickTemplate;
  useEffect(() => {
    if (!composerApiRef) return;
    composerApiRef.current = composerApiBoxRef.current;
    return () => { composerApiRef.current = null; };
  }, [composerApiRef]);

  return (
    <>
      <div
        data-composer-area
        data-no-swipe
        onDragOver={(e) => {
          if (!uploadDisabled && Array.from(e.dataTransfer?.types ?? []).includes("Files")) e.preventDefault();
        }}
        onDrop={onDropFiles}
        className={cn(MP.composer.root, "shrink-0 border-[var(--inf-rule,var(--color-border))] bg-[var(--inf-pane,var(--color-panel))]")}
      >
        <div className={cn(MP.ours.Composer.notices, "empty:hidden")}>
          {blocked && (
            <div className={cn(MP.ours.Composer.notice, "bg-err/10 border-err/30 text-err")}>
              ⚠ Sending disabled
              {cannotSendReason ? ` — ${cannotSendReason}` : " — OF blocked this chat."}
            </div>
          )}
          {refusedOffers.map((offer) => (
            <RefusedOfferNotice
              key={offer.id}
              offer={offer}
              here={isOfferHere(offer, accountId, fanId)}
              onRestore={() => restoreOffer(offer)}
              onDismiss={() => dismissOffer(offer)}
            />
          ))}
          {sendToast && (
            <div className={cn(MP.ours.Composer.notice, "flex items-center bg-accent/10 border-accent/30 text-[var(--inf-accent-text,var(--color-accent))]")}>
              <span className="flex-1">{sendToast}</span>
              <button
                type="button"
                onClick={() => setSendToast(null)}
                className="text-fg-dim hover:text-fg"
                title="Dismiss"
              >
                ✕
              </button>
            </div>
          )}
          {view.priceError && (
            <div role="alert" className={cn(MP.ours.Composer.notice, "bg-err/10 border-err/30 text-err")}>
              ⚠ {view.priceError}
            </div>
          )}
          <SensitiveWordWarning hits={sensitiveHits} />
          <TimedReminderNotice accountId={accountId} fanId={fanId} />
          <OutboundTranslationStrip t={outbound} onUse={setText} onSend={sendTranslation} canSend={view.canSend}
            formatted={richOn && richHtml != null} />
          {scripts.nextSteps.map((nextStep) => {
            const loadedStep = draft.script?.scriptId === nextStep.scriptId && draft.script.scriptStep === nextStep.step;
            return (
              <div
                key={nextStep.key}
                className={cn(MP.ours.Composer.notice, "flex items-center border-accent/40 bg-accent/10 text-[var(--inf-accent-text,var(--color-accent))] select-none")}
              >
                <button
                  type="button"
                  onClick={() => onPickScript(nextStep.picked)}
                  title="Tap to load this step into the composer"
                  className="flex flex-1 min-w-0 items-center text-left cursor-pointer rounded hover:bg-accent/15 focus:outline-none focus:ring-2 focus:ring-accent/50"
                >
                  <span className="font-medium shrink-0">
                    ▶ Next in “{nextStep.scriptId}” · step {nextStep.label}
                  </span>
                  <span className="flex-1 min-w-0 text-fg-dim truncate">
                    {nextStep.title ? <strong className="text-fg mr-1">{nextStep.title}:</strong> : null}
                    {isOfHtml(nextStep.text) ? ofPreviewText(nextStep.text) : nextStep.text}
                  </span>
                </button>
                {StepAction && SCRIPT_SOURCE?.owns(nextStep.scriptId) && accountId && (
                  <StepAction key={`${accountId}:${fanId}`} accountId={accountId} fanId={fanId}
                    replyAt={fanSpokeLastAt} onDraft={onStepDraft} />
                )}
                <button
                  type="button"
                  data-testid="script-skip"
                  disabled={loadedStep}
                  onClick={() => scripts.skip(nextStep.scriptId, nextStep.step)}
                  className="ml-2 shrink-0 whitespace-nowrap text-fg-dim enabled:hover:text-fg disabled:opacity-50"
                  title={loadedStep ? "Clear the loaded step before skipping" : "Skip this step — send nothing"}
                >
                  Skip
                </button>
                <button
                  type="button"
                  data-testid="script-end"
                  onClick={() => {
                    act({ type: "endScript", scriptId: nextStep.scriptId });
                    scripts.dismiss(nextStep.scriptId);
                  }}
                  className="ml-2 shrink-0 whitespace-nowrap text-fg-dim hover:text-fg"
                  title="End script — stop suggesting next steps"
                >
                  ✕ End script
                </button>
              </div>
            );
          })}
          <TaggedCreatorChips selected={taggedCreators} onChange={setTags} />
          {gifPickerOpen && (
            <GifPickerStrip
              accountId={accountId}
              onClose={() => setGifPickerOpen(false)}
              onPick={(gif) => {
                act({ type: "addGif", gif });
                setGifPickerOpen(false);
              }}
            />
          )}
        </div>

        <ComposerToolbar
          emoji={<EmojiPickerButton onInsert={onEmoji} disabled={disabled} align="left" triggerClassName={MP.composer.buttonRowButton} messagesPro />}
          favourites={<EmojiFavouritesButton disabled={disabled} />}
          quick={<QuickEmojiRow onInsert={onEmoji} disabled={disabled || blocked} />}
          input={richOn ? (
            <OfRichTextEditor
              ref={editorRef}
              value={richHtml ?? text}
              onChange={onRichChange}
              toolbar={draft.mode.toolbar}
              disabled={disabled}
              onKeyDown={onKeyDown}
              onPaste={onPaste}
              maxLength={OF_TEXT_MAX}
              placeholder={placeholder ?? 'Press "/" + keyword to quickly search scripts'}
              aria-label="Message"
              className="w-full min-w-0 rounded-none border-0 bg-transparent"
              inputClassName={cn(MP.composer.input, MP.ours.Composer.input, MP.ours.Composer.richInput)}
            />
          ) : (
            <textarea
              ref={textareaRef}
              value={text}
              onChange={(e) => {
                setText(e.target.value);
                if (e.target.value !== slashClosedFor) setSlashClosedFor(null);
              }}
              onKeyDown={onKeyDown}
              onPaste={onPaste}
              rows={1}
              disabled={disabled}
              placeholder={placeholder ?? 'Press "/" + keyword to quickly search scripts'}
              className={cn(MP.composer.input, MP.ours.Composer.input, "w-full bg-transparent placeholder:text-muted placeholder:truncate focus:outline-none resize-none overflow-y-auto")}
            />
          )}
          ai={<CopilotPicker key={`${accountId}:${fanId}`} accountId={accountId} fanId={fanId} onPick={onPickSuggestion} />}
          scripts={
            <TemplatePicker
              accountId={accountId}
              onPick={onPickScript}
              activeScriptId={scripts.activeScriptId}
              pinnedScriptId={scripts.pinnedScriptId}
              messagesPro
              slashQuery={slashQuery}
              onSlashClose={() => setSlashClosedFor(text)}
            />
          }
          timed={
            <TimedMessagePopover
              accountId={accountId}
              fanId={fanId}
              canSend={view.canSend}
              blocked={blocked}
              sendBlockedReason={view.timedBlockedReason}
              gifCount={pickedGifs.length}
              disabled={disabled}
              onStart={(m) => submit({ delayMinutes: m })}
              onPreset={(m) => act({ type: "schedule", open: true, at: localFutureForInput(m) })}
            />
          }
          gif={
            <GifPickerButton
              open={gifPickerOpen}
              onToggle={() => setGifPickerOpen(!gifPickerOpen)}
              disabled={disabled}
              messagesPro
            />
          }
          tag={
            <TagCreatorsPicker
              accountId={accountId}
              selected={taggedCreators}
              onChange={setTags}
              disabled={disabled}
              messagesPro
            />
          }
          vaultOn={attached.length > 0}
          ppvOpen={view.ppvRowOpen}
          ppvHeld={view.ppvHeld}
          vaultDisabled={uploadDisabled}
          scheduleOn={scheduleOpen}
          canSend={view.canSend}
          sendBlockedReason={view.sendBlockedReason}
          sendLabel={view.scheduling ? "Schedule" : "Send"}
          inflight={inflight}
          disabled={disabled}
          onTogglePpv={() => act({ type: "setPriceOpen", open: !priceOpen })}
          onUploadFiles={uploads.add}
          onVault={openVault}
          onCalendar={() => act({ type: "schedule", open: !scheduleOpen })}
          onSend={() => submit()}
          onClear={quoted || !isEmptyLiveDraft(fullDraft) ? clearDraft : undefined}
          onSendNext={onAdvance ? () => submit({ advance: true }) : undefined}
          accountId={accountId}
          onToggleOutbound={outbound.toggle}
          aa={allowRich ? { on: draft.mode.toolbar, onToggle: onAa } : null}
        >
          {quoted && (
            <div className={MP.ours.Composer.reply}>
              <ReplyStrip quoted={quoted} onCancel={() => onClearQuoted?.()} />
            </div>
          )}
          {view.ppvRowOpen && (
            <PpvRow
              price={price}
              onPrice={(raw) => act({ type: "setPrice", raw })}
              lockText={lockedText}
              onLockText={(on) => act({ type: "setLockText", on })}
              scheduleOn={scheduleOpen}
              at={scheduleAt}
              onAt={(at) => act({ type: "schedule", at })}
              onClear={clearPpvRow}
              disabled={disabled}
            >
              {attached.length > 0 && (
                <FreePreviews
                  count={view.previews}
                  total={attached.length}
                  enabled={view.paid != null}
                  onStep={(by) => act({ type: "stepPreviews", by })}
                />
              )}
              <PpvTiles
                attached={attached}
                view={view}
                uploads={uploads}
                accountId={accountId}
                disabled={disabled}
                reorder={reorder}
                byMedia={fanVaultQ.data?.by_media}
                onRemove={removeAttachment}
                gifs={pickedGifs}
                onRemoveGif={(id) => act({ type: "removeGif", id })}
              />
            </PpvRow>
          )}
        </ComposerToolbar>
      </div>

      {pickerOpen && (
        <VaultPicker
          open={pickerOpen}
          onClose={() => setPickerOpen(false)}
          accountId={accountId}
          fanId={fanId}
          initialSelectedIds={attached.filter(canBeFreePreview).map((m) => m.id)}
          onConfirm={onPicked}
          messagesPro
          sheet={MP.sheet}
        />
      )}
    </>
  );
}

function RefusedOfferNotice({ offer, here, onRestore, onDismiss }: {
  offer: RefusedOffer; here: boolean; onRestore: () => void; onDismiss: () => void;
}) {
  const what = `${offer.why}: “${offer.text || "(no text)"}”`;
  return (
    <div role="alert" className={cn(MP.ours.Composer.notice, "flex items-center bg-err/10 border-err/30 text-err")}>
      <span className="flex-1">
        {here
          ? `⚠ Not scheduled — ${what}. Restore replaces your current draft with it.`
          : `⚠ Not scheduled in the chat with ${offer.fanName || "another Fan"} — ${what}. Open that chat to restore it.`}
      </span>
      {here && (
        <>
          <button type="button" onClick={onRestore} className="mr-2 underline hover:text-fg">
            Restore
          </button>
          <button type="button" onClick={onDismiss} className="text-fg-dim hover:text-fg" title="Dismiss the refused message">
            ✕
          </button>
        </>
      )}
    </div>
  );
}

function localFutureForInput(minutes: number): string {
  return toLocalInput(new Date(Date.now() + minutes * 60_000));
}
