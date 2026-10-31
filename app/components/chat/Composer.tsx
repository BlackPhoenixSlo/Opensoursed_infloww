"use client";

/**
 * Composer — the chat's draft state and its send. The chrome is
 * `ComposerToolbar`'s two rows: the button row with the inline input, and the
 * bottom toolbar ending in Send (docs/spec/phase-04-composer-ppv-vault.md).
 *
 * Send routes through the chat's owning account_id, not the global scope
 * — this is the whole point of Unified Inbox. Parent passes accountId
 * (== chat.__accountId) so this works whether scope is "all" or a single
 * model.
 *
 * Enter sends; Shift+Enter inserts a newline. A draft that is "/" + a keyword
 * lists the matching Scripts, and Enter loads the first instead of sending
 * (look-and-feel ticket 150). The "PPV" pill opens the
 * `PpvRow`; a typed "PPV price" > 0 sends `price` and `lockedText`. The Vault
 * icon opens VaultPicker; picked media show as tiles in the PPV row and ride
 * along on send as `attached`. Upload (the computer's file chooser), a file
 * dropped on the Composer or an image pasted into the input uploads to the
 * vault (`useComposerUploads`); each file is a chip until it lands, then a tile
 * like a Vault pick. Send does not wait for a file still uploading: the send
 * takes the upload over (`uploads.handOff`) and goes out when it lands.
 * Schedule and the Timed message do wait, as scheduling needs the media ids.
 *
 * Attaching media (a Vault pick, an upload, a drop, a paste) opens the PPV
 * row with its price, whose free previews stepper then shows inline; a price
 * of 0 (or none) sends the media free (TODO.md A2, A3).
 */

import { useEffect, useLayoutEffect, useReducer, useRef, useState } from "react";

import { cn } from "@/lib/utils";
import { MP } from "@/lib/messagesPro";
import { type VaultMedia } from "@/lib/relay";
import { type FanId } from "@/lib/fanId";
import { isImeComposing } from "@/lib/ime";
import { useChatDraft } from "@/lib/chatDrafts";
import { useFanVaultHistory } from "@/hooks/useFanVaultHistory";
import { scriptPickWarning } from "@/lib/messageScripts";
import { isUploadable, useComposerUploads } from "@/hooks/useComposerUploads";
import { useReorder } from "@/hooks/useReorder";
import { EXECUTOR_MAX_MINUTES, type SendOutcome } from "@/hooks/useSendMessage";
import { useQueueKeys } from "@/hooks/useQueueKeys";

import dynamic from "next/dynamic";

import { EmojiPickerButton, insertAtCursor } from "./EmojiBar";
import { EmojiFavouritesButton, QuickEmojiRow } from "./EmojiFavourites";
import { CopilotPicker } from "./CopilotPicker";
import { GifPickerButton, GifPickerStrip } from "./GifPicker";
import { TemplatePicker, type PickedTemplate } from "./TemplatePicker";
import { TagCreatorsPicker, TaggedCreatorChips, type TaggedCreatorChoice } from "./TagCreatorsPicker";
import {
  EMPTY_DRAFT, afterRefusedSchedule, buildSendArgs, canBeFreePreview, canSend, composerDraft, composerView,
  type FullDraft, type SendArgs,
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

export type { SendArgs } from "./composerDraft";

// VaultPicker is heavy (hover-scrub state, fan-vault-history, wall-media,
// per-fan MRU localStorage). The composer mounts on every chat surface,
// but the picker only renders when the chatter clicks 📎. Dynamic +
// render-gate keeps the picker chunk off the inbox boot bundle.
const VaultPicker = dynamic(
  () => import("./VaultPicker").then((m) => m.VaultPicker),
  { ssr: false },
);

/** Imperative API exposed via `composerApiRef`. The parent can call
 *  these to drive the composer from outside (e.g. FanDrawer's
 *  "Send to chat" buttons on unsold PPVs). */
export interface ComposerApi {
  /** Replace text + attachments + price wholesale, identical to picking
   *  a saved template. Use this to populate the composer from arbitrary
   *  sources (template picker, prior message, unsold PPV, etc). */
  applyTemplate(t: PickedTemplate): void;
}

export interface ComposerProps {
  accountId: string | null;
  /** The Fan whose chat this is: every send goes to it (the parent keys the
   *  Composer by Creator and Fan), and it drives the vault picker's per-fan
   *  badges + filter. */
  fanId: FanId;
  /** The Fan's name, for a refused schedule's notice in the other chats. */
  fanName?: string | null;
  /** May resolve to the send's outcome: a send waiting on its uploads
   *  returns at once, and the extra GIFs of a multi-GIF send wait on its
   *  `settled`, going out only if it was sent, so the Fan gets them after it,
   *  in pick order. */
  onSend: (args: SendArgs) => void | Promise<SendOutcome | undefined | void>;
  disabled?: boolean;
  inflight?: number;
  placeholder?: string;
  /** When OF reports the chat as un-sendable (e.g., unsubscribed fan),
   *  pass `canSend=false` + `cannotSendReason` so the composer disables
   *  the controls and surfaces the reason instead of letting the user
   *  burn time on a guaranteed-fail send. */
  canSend?: boolean;
  cannotSendReason?: string | null;
  /** Quoted-reply context. When set, we render the `ReplyStrip` between the
   *  rows — the parent is responsible for prepending the quote text
   *  to the actual send body so the wire shape matches OF's expectations. */
  quoted?: QuotedReply | null;
  onClearQuoted?: () => void;
  /** Optional outbound ref for parents that need to drive the composer
   *  imperatively. The composer attaches a `ComposerApi` to `.current`
   *  for the lifetime of the mount; null on unmount. */
  composerApiRef?: React.MutableRefObject<ComposerApi | null>;
  /** Queue keys for a caller that steps through chats, and whether the draft holds more than its text (useQueueKeys). */
  onAdvance?: (dir: 1 | -1) => void;
  onHoldChange?: (held: boolean) => void;
}

export function Composer({
  accountId, fanId, fanName = null, onSend, disabled, inflight = 0, placeholder,
  canSend: chatCanSend = true, cannotSendReason,
  quoted, onClearQuoted,
  composerApiRef, onAdvance, onHoldChange,
}: ComposerProps) {
  // The text is the chat's draft (sessionStorage), so it survives a Fan
  // switch and the Fan List marks the row "[Draft]"; a send empties it.
  const [text, setText] = useChatDraft(accountId, fanId);
  // "/" search (look-and-feel ticket 150): the whole draft is "/" alone or "/"
  // + non-space characters. Escape closes the list until the draft changes.
  const [slashClosedFor, setSlashClosedFor] = useState<string | null>(null);
  const slashQuery = /^\/\S*$/.test(text) && text !== slashClosedFor ? text.slice(1) : null;
  // The rest of the draft — price, lock, media, previews, schedule, tags,
  // GIFs (./composerDraft). Lock-text is opt-in (asks #6 + #17); the
  // one-time migration toast below explains the change to returning users.
  const [draft, act] = useReducer(composerDraft, EMPTY_DRAFT);
  const { price, priceOpen, lockedText, attached, scheduleOpen, scheduleAt, taggedCreators, pickedGifs } = draft;
  // The whole draft as last rendered, for a refused schedule that settles
  // after the chatter has typed on (`afterRefusedSchedule`); null once the
  // chat closed (a switch remounts the Composer), as there is none to go into.
  const latestRef = useRef<FullDraft | null>({ text, draft });
  useLayoutEffect(() => {
    latestRef.current = { text, draft };
  });
  const [gifPickerOpen, setGifPickerOpen] = useState(false);
  useEffect(() => () => {
    latestRef.current = null;
  }, []);
  // The tiles' blob previews (./useBlobPreviews).
  const previews = useBlobPreviews(attached);
  const setTags = (tags: TaggedCreatorChoice[]) => act({ type: "setTags", tags });
  const [pickerOpen, setPickerOpen] = useState(false);
  /** Transient confirmation after a quick-send / scheduler fires. Lets the
   *  user know the message is queued locally — the textarea clears, so
   *  without this the action looks like nothing happened. */
  const [sendToast, setSendToast] = useState<string | null>(null);
  // Refused schedules the chatter typed on past, or left the chat during
  // (`afterRefusedSchedule`, ./refusedOffers): every chat lists them, each its
  // own notice, until restored or dismissed, never timed out or replaced by a
  // toast, as each holds the only copy of its draft.
  const { offers: refusedOffers } = useRefusedOffers();
  const toastTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  // Per-fan vault history — drives the green "BOUGHT" badge so the chatter
  // can see at a glance which attached tiles the fan already paid for (and
  // can avoid charging again).
  const fanVaultQ = useFanVaultHistory(accountId, fanId);

  // The "Next in" bubbles: the next step of the chat's user Script.
  const scripts = useScriptSuggestions(accountId, fanId);

  // Uploads from the computer. The Composer remounts per Fan chat, so they
  // are per Fan as the rest of the draft is.
  const uploads = useComposerUploads(accountId, (media) => act({ type: "uploaded", media }));
  const uploadDisabled = !!disabled || !accountId;
  // Send hands a running upload to the send; a schedule needs the media ids
  // now, so the Schedule button and the Timed message wait for it.
  const sendCtx = {
    text, disabled, chatCanSend, uploading: uploads.uploading, uploadFailed: !!uploads.failed, now: Date.now(),
  };
  // Paid, the PPV row, the price note, Send's state… (composerView).
  const view = composerView(draft, { ...sendCtx, uploadChips: uploads.chips.length });
  // Growth > Sensitive words: Infloww's chat composer warns above the input
  // and still sends (its desktop preload); the mass message composer blocks.
  // The draft in the Fan's language (Use / Send translation, Alt+T). Its
  // translation is what Send translation sends, so it is checked too.
  const outbound = useOutboundTranslation(accountId, fanId, text);
  const sensitiveHits = useSensitiveHits(`${text}\n${outbound.translated ?? ""}`, accountId);

  const reorder = useReorder(attached, (next) => act({ type: "reorder", attached: next }), (m) => m.id);
  // Surface OF's block reason at the top of the composer when sending is
  // disallowed. Saves the user from typing a message that will 400.
  const blocked = !chatCanSend;
  const queue = useQueueKeys({ accountId, fanId, held: view.held, onAdvance, onHoldChange });

  /** A notice that goes after `ms`; the next one replaces it. */
  function showToast(msg: string, opts: { ms?: number } = {}) {
    if (toastTimerRef.current) clearTimeout(toastTimerRef.current);
    setSendToast(msg);
    toastTimerRef.current = setTimeout(() => setSendToast(null), opts.ms ?? 6000);
  }

  /** A whole draft back into the Composer, over what is there. */
  function putBack(fd: FullDraft) {
    setText(fd.text);
    act({ type: "restore", snapshot: fd.draft });
  }

  /** Only in the offer's own chat (the notice offers it nowhere else). */
  function restoreOffer(offer: RefusedOffer) {
    putBack(offer);
    dispatchRefusedOffers({ type: "removed", id: offer.id });
  }

  /** Its media's blob previews go with it, unless something else shows them. */
  function dismissOffer(offer: RefusedOffer) {
    previews.forget(dismissRefusedOffer(offer, attached.map((m) => m._localPreview)));
  }

  // Clear any pending toast/migration-banner timer on unmount so it can't
  // fire setSendToast after the composer is gone (chat switches remount it).
  useEffect(() => () => {
    if (toastTimerRef.current) clearTimeout(toastTimerRef.current);
  }, []);

  /** `opts.text` replaces the draft (Send translation); `opts.advance` moves on after (useQueueKeys). */
  async function submit(opts?: { delayMinutes?: number; text?: string; advance?: boolean }) {
    const body = (opts?.text ?? text).trim();
    // One clock for the check and the send: a schedule whose time passed
    // since the render goes out at once, and is checked as one.
    const now = Date.now();
    if (!canSend(draft, { ...sendCtx, text: body, now })) return;
    // A typed price > 0 makes it PPV; a Timed message's delay wins over the
    // explicit "at". The first GIF rides on this send, the rest go as
    // GIF-only sends below (gifPlan).
    const args = buildSendArgs(draft, { text: body, delayMinutes: opts?.delayMinutes, now });
    const { trailing: trailingGifs } = gifPlan(pickedGifs);
    // Infloww's send-rate guard: a send at once within 3 s of the model's last
    // one (any of its Fans) stays in the composer, with OF's reason above it.
    if (!args.scheduledAt && !claimSendGap(accountId)) {
      showToast(`⚠ ${SEND_GAP_NOTE}`);
      return;
    }
    // A schedule's toast waits for the enqueue to SUCCEED (below; both paths
    // are server-side, so it survives reload and every chatter sees it): a
    // refused one (a Fansly PPV/media send the relay 400s) must not clear the
    // composer under a "Scheduled ✓". This snapshot hands the operator their
    // message back then; it also holds the Script step this message rode.
    const refused: FullDraft = { text, draft };
    // An identity switch while it is in flight makes its refusal stale.
    const epoch = readRefusedOffers().epoch;
    previews.markSent(draft.attached);
    setText("");
    act({ type: "sent" });
    // Files still uploading go with this send (canSend keeps a schedule from
    // getting here while one runs). The chatter types on at once.
    if (!args.scheduledAt) {
      const pending = uploads.handOff();
      if (pending.length > 0) args.uploads = pending;
    }
    textareaRef.current?.focus();
    const picked = refused.draft.script;
    let sent: SendOutcome | undefined | void;
    try {
      const sending = onSend(args);
      if (opts?.advance) queue.advanceAfter(sending, !!args.scheduledAt);
      sent = await sending;
    } catch (err) {
      // Only the scheduled paths reject up to here; an immediate send carries
      // its own failure on the red bubble (with a retry), so it must not be
      // double-reported or have its text pushed back into the composer.
      if (!args.scheduledAt) throw err;
      const why = err instanceof Error && err.message ? err.message : "unknown error";
      if (afterRefusedSchedule(latestRef.current) === "restore") {
        putBack(refused);
        showToast(`⚠ Not scheduled — ${why}`);
      } else {
        // The chatter has typed on, or left the chat: their edits stay, the
        // refused one waits beside them, in every chat. One from before an
        // identity switch is dropped, its previews revoked.
        const shown = latestRef.current?.draft.attached.map((m) => m._localPreview) ?? [];
        previews.forget(offerRefusedSchedule({ ...refused, accountId, fanId, fanName, why }, epoch, shown));
      }
      return;
    }
    if (args.scheduledAt) showToast(scheduledToast(args.scheduledAt, Date.now(), EXECUTOR_MAX_MINUTES));
    // Advance the Script if the just-sent message rode a step of one (the
    // draft's `script`, set by its template pick).
    scripts.advance(picked);
    // Fan out additional GIFs as standalone sends. Each carries only its
    // own giphyId — no text, no attachments — to mirror OF web behavior.
    // Behind a send still waiting on its files they wait too, off the
    // Composer's path, so the Fan gets them after it, in pick order; and
    // only if it went out: a discarded message (or an identity switch) or a
    // failed upload drops them (the chatter resends; Retry sends the message
    // alone).
    const sendGifs = async () => {
      for (const g of trailingGifs) await onSend({ text: "", giphyId: g.id });
    };
    if (args.uploads && sent) {
      void sent.settled.then((ended) => (ended.sent ? sendGifs() : undefined));
    } else {
      await sendGifs();
    }
  }

  // The inline input starts at one line and grows with the text; CSS
  // `max-h-48` caps it and scrolls beyond (spec, Gap row 5).
  useLayoutEffect(() => {
    const ta = textareaRef.current;
    if (!ta) return;
    ta.style.height = "auto";
    if (ta.scrollHeight) ta.style.height = `${ta.scrollHeight}px`;
  }, [text]);

  // Autofocus the textarea on mount. The Composer remounts whenever the
  // user picks a different chat (ChatSurface passes a `key` upstream),
  // so this gives them a typing cursor the same frame the chat opens —
  // no extra click needed.
  useEffect(() => {
    textareaRef.current?.focus();
  }, []);

  // No auto-seed: 0 previews is a legitimate choice on PPV (sends
  // everything locked). The ± stepper lets the user opt into a leading
  // free teaser when they want one.

  // One-time migration banner: the lockedText default flipped from true →
  // false (asks #6 + #17). Returning users who had muscle memory for the
  // old "lock text auto-on" need a heads-up. localStorage flag fires once
  // per browser, not per mount.
  useEffect(() => {
    if (typeof window === "undefined") return;
    const key = "chatterly:lockedText-default-changed-seen";
    if (localStorage.getItem(key)) return;
    showToast("Text is no longer locked by default in paid messages. Tap ‘lock text’ to lock.", { ms: 4000 });
    localStorage.setItem(key, "1");
    // eslint-disable-next-line react-hooks/exhaustive-deps -- once per mount
  }, []);

  function onKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    // An IME's Enter picks its candidate: no key here sends or moves on.
    if (isImeComposing(e)) return;
    // The open "/" list picks its first match on this Enter (TemplatePicker),
    // so "/keyword" is never sent from here, translated or not.
    if (e.key === "Enter" && !e.shiftKey && slashQuery !== null) {
      e.preventDefault();
      return;
    }
    const advance = queue.isAdvanceKey(e); // queue keys: sends (the translation too), then moves on
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

  function onEmoji(em: string) {
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

  /** "Clear": everything the PPV row lists goes, the typed text stays
   *  (spec, The PPV row; Clone messages.js:1857–1861). */
  function clearPpvRow() {
    act({ type: "clearPpv" });
    uploads.clear();
  }

  /** Image and video files dragged from the computer onto the Composer upload;
   *  a tile being reordered carries no files and is left to its own handler. */
  function onDropFiles(e: React.DragEvent) {
    const files = Array.from(e.dataTransfer?.files ?? []);
    if (files.length === 0 || uploadDisabled) return;
    e.preventDefault();
    uploads.add(files);
  }

  /** An image pasted into the input uploads instead of inserting text. A
   *  clipboard that also holds text (spreadsheet cells, rich text, which carry
   *  a picture of themselves) pastes the text. */
  function onPaste(e: React.ClipboardEvent<HTMLTextAreaElement>) {
    if (Array.from(e.clipboardData?.types ?? []).includes("text/plain")) return;
    const files = Array.from(e.clipboardData?.files ?? []).filter(isUploadable);
    if (files.length === 0 || uploadDisabled) return;
    e.preventDefault();
    uploads.add(files);
  }

  function onPickSuggestion(suggestion: string) {
    // An AI Copilot suggestion goes in at the cursor for the chatter to edit;
    // it is sent only when they press Send.
    const ta = textareaRef.current;
    if (ta) insertAtCursor(ta, text, suggestion, setText);
    else setText((t) => (t ? `${t} ${suggestion}` : suggestion));
  }

  /** A script picked in the Scripts list or the next-step suggestion: the
   *  "Use script?" guard (roadmap W4 4.2) asks first when this Fan already
   *  bought some of its media (the BOUGHT badge's history) or some was
   *  deleted from the vault. A chat-media resend (`applyTemplate`) is not a
   *  script pick, so it skips the guard. */
  function onPickScript(t: PickedTemplate) {
    const warning = scriptPickWarning(t, fanVaultQ.data?.by_media);
    if (warning && !window.confirm(`${warning}\n\nInsert it anyway?`)) return;
    onPickTemplate(t);
  }

  function onPickTemplate(t: PickedTemplate) {
    // Template = snapshot: text, media, previews, price and GIF replace the
    // draft's, so the FREE-first order baked in at save time survives. Its
    // Script step rides on the draft, so the send advances the Script.
    setText(t.text);
    act({ type: "pickTemplate", t });
    setTimeout(() => textareaRef.current?.focus(), 0);
  }

  // Publish the imperative API to the parent's ref while we're mounted.
  // Stored via a stable inner ref so `onPickTemplate`'s identity churn
  // (it captures every render's closures) doesn't keep re-firing the
  // outer effect; we just update the function inside the box each render.
  const composerApiBoxRef = useRef<ComposerApi>({
    applyTemplate: () => { /* set on first render */ },
  });
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
        // shrink-0: never let the flex parent compress the composer when
        //   the keyboard or a tall preview tray pushes the page.
        // pb safe-area: keeps the bottom toolbar above iOS Safari's home-indicator bar.
        className={cn(MP.composer.root, "shrink-0 border-[var(--inf-rule,var(--color-border))] bg-[var(--inf-pane,var(--color-panel))]")}
      >
        {/* Notices sit above row 1 so they never displace an Infloww
         *  control (spec, Layout). With no notice the wrapper is hidden, so
         *  its padding does not push row 1 down. */}
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
          <OutboundTranslationStrip t={outbound} onUse={setText} onSend={sendTranslation} canSend={view.canSend} />
          {scripts.nextSteps.map((nextStep) => (
            <div
              key={nextStep.key}
              role="button"
              tabIndex={0}
              onClick={() => onPickScript(nextStep.picked)}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  onPickScript(nextStep.picked);
                }
              }}
              title="Tap to load this step into the composer"
              className={cn(MP.ours.Composer.notice, "flex items-center border-accent/40 bg-accent/10 text-[var(--inf-accent-text,var(--color-accent))] cursor-pointer hover:bg-accent/15 focus:outline-none focus:ring-2 focus:ring-accent/50 select-none")}
            >
              <span className="font-medium shrink-0">
                ▶ Next in “{nextStep.scriptId}” · step {nextStep.label}
              </span>
              <span className="flex-1 min-w-0 text-fg-dim truncate">
                {nextStep.title ? <strong className="text-fg mr-1">{nextStep.title}:</strong> : null}
                {nextStep.text}
              </span>
              <button
                type="button"
                onClick={(e) => {
                  // Stop the row's click handler from also firing the pick —
                  // ✕ is an "end script" action, not a "pick + dismiss" combo.
                  e.stopPropagation();
                  scripts.dismiss();
                }}
                className="text-fg-dim hover:text-fg shrink-0"
                title="End script — stop suggesting next steps"
              >
                ✕
              </button>
            </div>
          ))}
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
          input={
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
              // Row 2 (look-and-feel C6): 16px at every width, which also stops
              // iOS Safari zooming in. Height follows the text, padding
              // included (see the layout effect above); the placeholder stays
              // on one line so it never grows the row.
              className={cn(MP.composer.input, MP.ours.Composer.input, "w-full bg-transparent placeholder:text-muted placeholder:truncate focus:outline-none resize-none overflow-y-auto")}
            />
          }
          ai={<CopilotPicker key={`${accountId}:${fanId}`} accountId={accountId} fanId={fanId} onPick={onPickSuggestion} />}
          scripts={
            <TemplatePicker
              accountId={accountId}
              onPick={onPickScript}
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
          accountId={accountId}
          onToggleOutbound={outbound.toggle}
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

      {/* Render-gated dynamic import: the picker chunk only fetches when
       *  the user actually opens it. Composer mounts on every chat
       *  surface so this matters for cold-inbox latency. */}
      {pickerOpen && (
        <VaultPicker
          open={pickerOpen}
          onClose={() => setPickerOpen(false)}
          accountId={accountId}
          fanId={fanId}
          // Real vault ids only: a claim's negative id is no vault item.
          initialSelectedIds={attached.filter(canBeFreePreview).map((m) => m.id)}
          onConfirm={onPicked}
          messagesPro
          // The Clone's sheet (SH1, SH2, SH5, SH6): the picker is shared with
          // other screens, so it takes them as props and never reads the module.
          sheet={MP.sheet}
        />
      )}
    </>
  );
}

/** A refused schedule's notice. Restore and ✕ only in the chat it was written
 *  in: elsewhere its draft is not shown, so ✕ there would lose its only copy
 *  unseen. */
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

/** Same shape, offset N minutes into the future. Used by ⏱'s "Send at" preset
 *  buttons (+5m, +10m, …) so picking a preset feels like a normal input
 *  fill — the input itself shows the resolved time. */
function localFutureForInput(minutes: number): string {
  return toLocalInput(new Date(Date.now() + minutes * 60_000));
}
