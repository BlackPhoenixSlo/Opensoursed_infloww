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

import { Fragment, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";

import { cn } from "@/lib/utils";
import { MP } from "@/lib/messagesPro";
import { type VaultMedia } from "@/lib/relay";
import { revokePreviews } from "@/lib/blobPreviews";
import { proxyImage } from "@/lib/mediaUrl";
import { type FanId } from "@/lib/fanId";
import { useChatDraft } from "@/lib/chatDrafts";
import { useFanVaultHistory } from "@/hooks/useFanVaultHistory";
import { scriptPickWarning } from "@/lib/messageScripts";
import {
  isUploadable, uploadErrorText, useComposerUploads, type PendingUpload,
} from "@/hooks/useComposerUploads";
import { useReorder } from "@/hooks/useReorder";
import { useSavedReplies } from "@/hooks/useSavedReplies";
import { useScriptCursor } from "@/hooks/useScriptCursor";
import { EXECUTOR_MAX_MINUTES, type SendOutcome } from "@/hooks/useSendMessage";
import { useQueueKeys } from "@/hooks/useQueueKeys";

import dynamic from "next/dynamic";

import { EmojiPickerButton, insertAtCursor } from "./EmojiBar";
import { EmojiFavouritesButton, QuickEmojiRow } from "./EmojiFavourites";
import { CopilotPicker } from "./CopilotPicker";
import { GifPickerButton, GifPickerStrip, type PickedGif } from "./GifPicker";
import {
  TemplatePicker,
  templateMediaToVault,
  fromLocal as savedReplyToPicked,
  type PickedTemplate,
} from "./TemplatePicker";
import { TagCreatorsPicker, TaggedCreatorChips, type TaggedCreatorChoice } from "./TagCreatorsPicker";
import { ComposerToolbar } from "./ComposerToolbar";
import { OutboundTranslationStrip, outboundTranslationKey, useOutboundTranslation } from "./OutboundTranslation";
import { FreePreviews, PpvRow, toLocalInput } from "./PpvRow";
import { TimedMessagePopover, TimedReminderNotice } from "./TimedMessagePopover";
import { ReplyStrip, type QuotedReply } from "./ReplyStrip";
import { SensitiveWordWarning } from "./SensitiveWordWarning";
import { useSensitiveHits } from "@/lib/sensitiveWords";
import { claimSendGap, priceNote, SEND_GAP_NOTE } from "@/lib/sendGuards";

// VaultPicker is heavy (hover-scrub state, fan-vault-history, wall-media,
// per-fan MRU localStorage). The composer mounts on every chat surface,
// but the picker only renders when the chatter clicks 📎. Dynamic +
// render-gate keeps the picker chunk off the inbox boot bundle.
const VaultPicker = dynamic(
  () => import("./VaultPicker").then((m) => m.VaultPicker),
  { ssr: false },
);

export interface SendArgs {
  text: string;
  price?: number;
  lockedText?: boolean;
  /** Vault items the sender attached. The hook extracts ids for the
   *  wire payload AND uses the file URLs to seed the optimistic bubble's
   *  media — without that, attached PPV messages render text-only. */
  attached?: VaultMedia[];
  /** Vault media ids that should be sent UNLOCKED (free previews) when
   *  `price > 0`. Order doesn't matter to OF — the locked/unlocked split
   *  is per-media-id, not by position. Omit / `[]` ⇒ everything locked. */
  previews?: number[];
  /** ISO 8601 send-at timestamp. When set, the relay queues via the
   *  /messages/scheduled endpoint instead of sending immediately. */
  scheduledAt?: string;
  /** OF user ids of creators to @-tag (sent as `userTags`). Picker
   *  guarantees these are valid taggable creators — OF 400s otherwise. */
  taggedUsers?: number[];
  /** Giphy id (e.g. "0ndspgUFbm9iQtyX2Q"). OF accepts a single GIF per
   *  send — when the user picks multiple, the parent splits the call. */
  giphyId?: string;
  /** Files still uploading when Send was pressed; the send goes out once they
   *  land, their media after `attached`. Never set on a scheduled send. */
  uploads?: PendingUpload[];
}

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
  /** When the composer is bound to a single fan (chat surface), passing
   *  fanId here unlocks the vault picker's per-fan badges + filter. Mass-
   *  send composers leave this null. */
  fanId?: FanId | null;
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
  accountId, fanId = null, onSend, disabled, inflight = 0, placeholder,
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
  const [priceOpen, setPriceOpen] = useState(false);
  const [price, setPrice] = useState<string>("");
  // Default OFF per DA ruling on asks #6 + #17: lock-text is opt-in. The
  // one-time migration toast below explains the change to returning users.
  const [lockText, setLockText] = useState(false);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [attached, setAttached] = useState<VaultMedia[]>([]);
  // How many leading tiles are FREE previews; rest are PPV-locked. Default
  // 1 once the user attaches any media in PPV mode (matches OF desktop's
  // "first tile is the unlocked teaser" convention) — but only if the user
  // hasn't already adjusted it. The touched-ref below preserves explicit
  // user choices (including "0 previews — fully locked").
  const [previewCount, setPreviewCount] = useState<number>(0);
  const previewCountTouchedRef = useRef(false);
  const bumpPreviewCount = (updater: (c: number) => number) => {
    previewCountTouchedRef.current = true;
    setPreviewCount(updater);
  };
  const [scheduleOpen, setScheduleOpen] = useState(false);
  const [scheduleAt, setScheduleAt] = useState<string>("");
  const [taggedCreators, setTaggedCreators] = useState<TaggedCreatorChoice[]>([]);
  // Picked GIFs. OF accepts ONE GIF per send (top-level `giphyId`, sibling
  // of `mediaFiles`). When the user picks multiple, the submit handler
  // fans them out as separate sends — verified live 2026-05-23.
  const [pickedGifs, setPickedGifs] = useState<PickedGif[]>([]);
  const [gifPickerOpen, setGifPickerOpen] = useState(false);
  /** Transient confirmation after a quick-send / scheduler fires. Lets the
   *  user know the message is queued locally — the textarea clears, so
   *  without this the action looks like nothing happened. */
  const [sendToast, setSendToast] = useState<string | null>(null);
  const toastTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  // Per-fan vault history — drives the green "BOUGHT" badge so the chatter
  // can see at a glance which attached tiles the fan already paid for (and
  // can avoid charging again). Only meaningful for single-fan composers
  // (fanId set); mass-send variants render gray/red without bought-state.
  const fanVaultQ = useFanVaultHistory(accountId, fanId ?? null, fanId != null);

  // Script-cursor state — remembers the last sent script step per chat so
  // the composer can suggest the next step in the same script. The cursor
  // survives reloads (localStorage) and is sticky: typing a one-off reply
  // between script steps does NOT clear it, so the user can resume the
  // sequence after side-conversations. Cleared on manual dismiss only.
  const [scriptCursor, setScriptCursor] = useScriptCursor(accountId, fanId ?? null);
  // Captures the most-recently-picked template so a successful submit can
  // advance the script cursor on the same render. A ref (not state) keeps
  // the side-effect off the dependency chain.
  const lastPickedRef = useRef<PickedTemplate | null>(null);
  // We only need the saved-reply list when a cursor exists — gate the
  // fetch so cold chats don't pay a /admin/saved-replies roundtrip just
  // to render the empty composer.
  const replyQ = useSavedReplies(scriptCursor ? accountId : null);
  // Every template at step N+1, not just the first: a Script may hold
  // several per step ("2.1/2.2", e.g. bought / not bought), and the
  // chatter picks the branch.
  const nextStepReplies = useMemo(() => {
    if (!scriptCursor || !replyQ.data) return [];
    const target = scriptCursor.step + 1;
    return replyQ.data.filter(
      (r) =>
        (r.script_id ?? "") === scriptCursor.scriptId &&
        r.script_step === target,
    );
  }, [scriptCursor, replyQ.data]);

  // Uploads from the computer. The Composer remounts per Fan chat, so they
  // are per Fan as the rest of the draft is.
  const uploads = useComposerUploads(accountId, (media) =>
    setAttached((prev) => {
      const have = new Set(prev.map((m) => m.id));
      return [...prev, ...media.filter((m) => !have.has(m.id))];
    }),
  );
  const uploadDisabled = !!disabled || !accountId;
  // Unsent attachments' blob previews go with the draft when the chat closes.
  const attachedRef = useRef(attached);
  attachedRef.current = attached;
  useEffect(() => () => revokePreviews(attachedRef.current.map((m) => m._localPreview)), []);
  // Send hands a running upload to the send; a schedule needs the media ids
  // now, so the Schedule button and the Timed message wait for it.
  const scheduling = scheduleOpen && !!scheduleAt && new Date(scheduleAt) > new Date();
  const failedUploadReason = uploads.failed ? "Retry or remove the failed upload first" : null;
  const scheduleWaitReason = failedUploadReason
    ?? (uploads.uploading ? "Wait for the upload to finish before scheduling" : null);
  // Growth > Sensitive words: Infloww's chat composer warns above the input
  // and still sends (its desktop preload); the mass message composer blocks.
  // The draft in the Fan's language (Use / Send translation, Alt+T). Its
  // translation is what Send translation sends, so it is checked too.
  const outbound = useOutboundTranslation(accountId, fanId, text);
  const sensitiveHits = useSensitiveHits(`${text}\n${outbound.translated ?? ""}`, accountId);

  const numericPrice = parsePrice(price);
  // OF refuses a price under $3 that is not free: say so above the input
  // and hold Send and the Timed message until it is fixed.
  const priceError = priceNote(numericPrice);
  const sendBlockedReason = (scheduling ? scheduleWaitReason : failedUploadReason) ?? priceError;
  const hasAttachments = attached.length > 0;
  const reorder = useReorder(attached, setAttached, (m) => m.id);
  // Clamp on read so removing tiles never leaves previewCount past the
  // end (would render phantom FREE badges on indices beyond the array).
  const effectivePreviewCount = Math.max(0, Math.min(previewCount, attached.length));
  const showPpv = numericPrice != null && numericPrice > 0;
  const showDivider =
    showPpv && effectivePreviewCount > 0 && effectivePreviewCount < attached.length;
  const hasGifs = pickedGifs.length > 0;
  // The PPV row shows while the pill is on or the draft carries anything it
  // lists (spec, The PPV row; Clone messages.js:1838).
  const ppvRowOpen = priceOpen || hasAttachments || hasGifs || scheduleOpen || showPpv || uploads.chips.length > 0;
  const canSend =
    !disabled &&
    chatCanSend &&
    sendBlockedReason == null &&
    (text.trim().length > 0 || hasAttachments || hasGifs || uploads.uploading) &&
    (!priceOpen || numericPrice == null || numericPrice >= 0);
  // Surface OF's block reason at the top of the composer when sending is
  // disallowed. Saves the user from typing a message that will 400.
  const blocked = !chatCanSend;
  // What leaving this Fan would lose: the per-Fan draft keeps only the text.
  const held = hasAttachments || hasGifs || uploads.chips.length > 0 || showPpv;
  const queue = useQueueKeys({ accountId, fanId, held, onAdvance, onHoldChange });

  function showToast(msg: string) {
    if (toastTimerRef.current) clearTimeout(toastTimerRef.current);
    setSendToast(msg);
    toastTimerRef.current = setTimeout(() => setSendToast(null), 6000);
  }

  // Clear any pending toast/migration-banner timer on unmount so it can't
  // fire setSendToast after the composer is gone (chat switches remount it).
  useEffect(() => () => {
    if (toastTimerRef.current) clearTimeout(toastTimerRef.current);
  }, []);

  /** `opts.text` replaces the draft (Send translation); `opts.advance` moves on after (useQueueKeys). */
  async function submit(opts?: { delayMinutes?: number; text?: string; advance?: boolean }) {
    const body = (opts?.text ?? text).trim();
    if (!body && !hasAttachments && !hasGifs && !uploads.uploading) return;
    const args: SendArgs = { text: body };
    // Paid path: a typed price > 0 is the sole signal. (The previous
    // "Send as paid" toggle was redundant — if a price is set, the message
    // is PPV; clear the price to send free.)
    if (numericPrice != null && numericPrice > 0) {
      args.price = numericPrice;
      args.lockedText = lockText;
      if (effectivePreviewCount > 0) {
        args.previews = attached
          .slice(0, effectivePreviewCount)
          .filter(canBeFreePreview)
          .map((m) => m.id);
      }
    }
    if (hasAttachments) args.attached = attached;
    if (taggedCreators.length > 0) {
      args.taggedUsers = taggedCreators.map((c) => c.id);
    }
    // OF accepts ONE GIF per send (verified live 2026-05-23). When the
    // user picked multiple, ride the first one on this send and fan out
    // the rest as standalone GIF-only sends below.
    const firstGif = pickedGifs[0];
    const trailingGifs = pickedGifs.slice(1);
    if (firstGif) args.giphyId = firstGif.id;
    // A Timed message's delay (1–60 min) takes priority over the explicit
    // "at" — they're alternate UIs for the same idea.
    if (opts?.delayMinutes && opts.delayMinutes > 0) {
      args.scheduledAt = new Date(Date.now() + opts.delayMinutes * 60_000).toISOString();
    } else if (scheduleOpen && scheduleAt) {
      // datetime-local has no tz suffix. Treat the value as local-time and
      // let the Date constructor attach the user's tz when serializing.
      const d = new Date(scheduleAt);
      if (!Number.isNaN(d.getTime()) && d.getTime() > Date.now()) {
        args.scheduledAt = d.toISOString();
      }
    }
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
    // message back then.
    const restore = {
      text, price, priceOpen, attached, previewCount,
      previewTouched: previewCountTouchedRef.current,
      scheduleOpen, scheduleAt, taggedCreators, pickedGifs,
    };
    setText("");
    setPrice("");
    setPriceOpen(false);
    setAttached([]);
    setPreviewCount(0);
    previewCountTouchedRef.current = false;
    setScheduleOpen(false);
    setScheduleAt("");
    setTaggedCreators([]);
    setPickedGifs([]);
    setGifPickerOpen(false);
    // Files still uploading go with this send (canSend keeps a schedule from
    // getting here while one runs). The chatter types on at once.
    if (!args.scheduledAt) {
      const pending = uploads.handOff();
      if (pending.length > 0) args.uploads = pending;
    }
    textareaRef.current?.focus();
    // Take this message's Script pick now: the chatter may pick for the next
    // message before this send settles, and that pick is not ours.
    const picked = lastPickedRef.current;
    lastPickedRef.current = null;
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
      setText(restore.text);
      setPrice(restore.price);
      setPriceOpen(restore.priceOpen);
      setAttached(restore.attached);
      setPreviewCount(restore.previewCount);
      previewCountTouchedRef.current = restore.previewTouched;
      setScheduleOpen(restore.scheduleOpen);
      setScheduleAt(restore.scheduleAt);
      setTaggedCreators(restore.taggedCreators);
      setPickedGifs(restore.pickedGifs);
      lastPickedRef.current ??= picked;
      const why = err instanceof Error && err.message ? err.message : "unknown error";
      showToast(`⚠ Not scheduled — ${why}`);
      return;
    }
    if (args.scheduledAt) {
      const fireAt = new Date(args.scheduledAt).getTime();
      const minsFromNow = Math.max(1, Math.round((fireAt - Date.now()) / 60_000));
      if (fireAt - Date.now() <= EXECUTOR_MAX_MINUTES * 60_000) {
        showToast(`⏱ Scheduled · sending in ${minsFromNow} min (saved — survives reload)`);
      } else {
        showToast(`⏱ Queued on OF for ${new Date(args.scheduledAt).toLocaleString()}`);
      }
    }
    // Advance the script cursor if the just-sent message rode a template
    // with script_id + script_step set (captured from onPickTemplate above,
    // before the send).
    if (picked?.scriptId && typeof picked.scriptStep === "number") {
      setScriptCursor({ scriptId: picked.scriptId, step: picked.scriptStep });
    }
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
    if (toastTimerRef.current) clearTimeout(toastTimerRef.current);
    setSendToast("Text is no longer locked by default in paid messages. Tap ‘lock text’ to lock.");
    toastTimerRef.current = setTimeout(() => setSendToast(null), 4000);
    localStorage.setItem(key, "1");
  }, []);

  function onKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
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
      if (canSend) submit({ advance });
    }
    queue.arrowKey(e, text === "" && !quoted);
  }

  function sendTranslation(translated: string, advance = false) {
    if (canSend) submit({ text: translated, advance });
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

  function onPicked(picked: VaultMedia[]) {
    // Replace selection wholesale — the picker pre-selects from
    // `attached` so any removals/adds done inside it stick on confirm. It
    // knows vault ids only: an upload still transcoding (`_claim`) stays, and
    // an uploaded id it hands back bare keeps its files and blob preview.
    const byId = new Map(attached.map((m) => [m.id, m]));
    const next = [
      ...picked.map((p) => {
        const had = byId.get(p.id);
        return had ? { ...p, ...had, files: had.files ?? p.files } : p;
      }),
      ...attached.filter((m) => m._claim),
    ];
    dropPreviews(attached, next);
    setAttached(next);
    // Auto-price: the operator sets a per-media price in /vault, and a bundle is
    // worth the HIGHEST of what's in it — never undercharge for the best clip in
    // the set. Media with no price contribute nothing, so attaching unpriced
    // media leaves whatever price you already typed alone.
    const top = picked.reduce((max, m) => {
      const c = (m as { _ai?: { suggested_price_cents?: number | null } })._ai
        ?.suggested_price_cents;
      return typeof c === "number" && c > max ? c : max;
    }, 0);
    if (top > 0) {
      setPrice((top / 100).toFixed(2));
      setPriceOpen(true);
    }
  }

  function removeAttachment(id: number) {
    const next = attached.filter((m) => m.id !== id);
    dropPreviews(attached, next);
    setAttached(next);
  }

  /** Revoke the blob previews of attachments leaving the draft, unless a
   *  remaining one (from the same file) still shows it. Not on send: the
   *  optimistic bubble shows it until the server copy arrives. */
  function dropPreviews(before: VaultMedia[], after: VaultMedia[]) {
    const live = new Set(after.map((m) => m._localPreview));
    revokePreviews(before.map((m) => m._localPreview).filter((u) => !live.has(u)));
  }

  /** "Clear": everything the PPV row lists goes, the typed text stays
   *  (spec, The PPV row; Clone messages.js:1857–1861). */
  function clearPpvRow() {
    setPrice("");
    setLockText(false);
    setScheduleAt("");
    setScheduleOpen(false);
    dropPreviews(attached, []);
    setAttached([]);
    uploads.clear();
    setPickedGifs([]);
    setPreviewCount(0);
    previewCountTouchedRef.current = false;
    setPriceOpen(false);
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
    // Capture the picked template so a subsequent successful send can
    // advance the script cursor. Cleared by submit() so a non-template
    // send won't accidentally re-advance.
    lastPickedRef.current = t;
    // Template = snapshot. Replace text + attachments + preview-count
    // wholesale so the FREE-first ordering baked in at save time
    // survives. Merging would push the template's free tiles behind
    // whatever was already attached and break the count-based preview
    // model (leading N tiles = free).
    setText(t.text);
    const fromTemplate = templateMediaToVault(t);
    dropPreviews(attached, fromTemplate);
    setAttached(fromTemplate);
    // Reset price wholesale — a free template (price 0) must clear any
    // price the user already typed, or a "free" template would silently
    // go out as a stale PPV (numericPrice > 0 is the sole paid signal).
    setPrice(t.price > 0 ? String(t.price) : "");
    setLockText(t.price > 0 ? t.lockedText : false);
    setPriceOpen(t.price > 0);
    // Always lock previewCount to the template's count — 0 is a valid
    // "everything PPV-locked" state that must overwrite any prior value.
    previewCountTouchedRef.current = true;
    setPreviewCount(t.previews.length);
    if (t.taggedUsers.length > 0) {
      // The picker resolves names lazily; we only have ids in the
      // template. Seed placeholder chips so the user can see the tag
      // count immediately — opening the @ popover will replace them
      // with the live data on next render.
      setTaggedCreators((prev) => {
        const have = new Set(prev.map((c) => c.id));
        const additions: TaggedCreatorChoice[] = t.taggedUsers
          .filter((id) => !have.has(id))
          .map((id) => ({ id, name: `user${id}`, username: "", avatar: null }));
        return [...prev, ...additions];
      });
    }
    // GIF state is part of the snapshot too: seed the template's GIF when
    // it carries one, otherwise CLEAR any previously-picked GIF so a stale
    // pick doesn't ride along on a non-GIF template's send.
    if (t.gifId) {
      const url = t.gifUrl ?? "";
      setPickedGifs([{ id: t.gifId, thumbUrl: url, fullUrl: url, title: t.title }]);
    } else {
      setPickedGifs([]);
    }
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
          {priceError && (
            <div role="alert" className={cn(MP.ours.Composer.notice, "bg-err/10 border-err/30 text-err")}>
              ⚠ {priceError}
            </div>
          )}
          <SensitiveWordWarning hits={sensitiveHits} />
          <TimedReminderNotice accountId={accountId} fanId={fanId} />
          <OutboundTranslationStrip t={outbound} onUse={setText} onSend={sendTranslation} canSend={canSend} />
          {nextStepReplies.map((nextStepReply) => (
            <div
              key={nextStepReply.id}
              role="button"
              tabIndex={0}
              onClick={() => onPickScript(savedReplyToPicked(nextStepReply))}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  onPickScript(savedReplyToPicked(nextStepReply));
                }
              }}
              title="Tap to load this step into the composer"
              className={cn(MP.ours.Composer.notice, "flex items-center border-accent/40 bg-accent/10 text-[var(--inf-accent-text,var(--color-accent))] cursor-pointer hover:bg-accent/15 focus:outline-none focus:ring-2 focus:ring-accent/50 select-none")}
            >
              <span className="font-medium shrink-0">
                ▶ Next in “{nextStepReply.script_id}” · step {nextStepReply.script_step}
              </span>
              <span className="flex-1 min-w-0 text-fg-dim truncate">
                {nextStepReply.title ? <strong className="text-fg mr-1">{nextStepReply.title}:</strong> : null}
                {nextStepReply.text}
              </span>
              <button
                type="button"
                onClick={(e) => {
                  // Stop the row's click handler from also firing the pick —
                  // ✕ is an "end script" action, not a "pick + dismiss" combo.
                  e.stopPropagation();
                  setScriptCursor(null);
                }}
                className="text-fg-dim hover:text-fg shrink-0"
                title="End script — stop suggesting next steps"
              >
                ✕
              </button>
            </div>
          ))}
          <TaggedCreatorChips selected={taggedCreators} onChange={setTaggedCreators} />
          {gifPickerOpen && (
            <GifPickerStrip
              accountId={accountId}
              onClose={() => setGifPickerOpen(false)}
              onPick={(g) => {
                setPickedGifs((prev) => (
                  prev.some((p) => p.id === g.id) ? prev : [...prev, g]
                ));
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
              canSend={canSend}
              blocked={blocked}
              sendBlockedReason={scheduleWaitReason ?? priceError}
              gifCount={pickedGifs.length}
              disabled={disabled}
              onStart={(m) => submit({ delayMinutes: m })}
              onPreset={(m) => {
                setScheduleOpen(true);
                setScheduleAt(localFutureForInput(m));
              }}
            />
          }
          gif={
            <GifPickerButton
              open={gifPickerOpen}
              onToggle={() => setGifPickerOpen((v) => !v)}
              disabled={disabled}
              messagesPro
            />
          }
          tag={
            <TagCreatorsPicker
              accountId={accountId}
              selected={taggedCreators}
              onChange={setTaggedCreators}
              disabled={disabled}
              messagesPro
            />
          }
          vaultOn={hasAttachments}
          ppvOpen={ppvRowOpen}
          vaultDisabled={uploadDisabled}
          scheduleOn={scheduleOpen}
          canSend={canSend}
          sendBlockedReason={sendBlockedReason}
          sendLabel={scheduling ? "Schedule" : "Send"}
          inflight={inflight}
          disabled={disabled}
          onTogglePpv={() => setPriceOpen(!ppvRowOpen)}
          onUploadFiles={uploads.add}
          onVault={openVault}
          onCalendar={() => setScheduleOpen((v) => !v)}
          onSend={() => submit()}
          accountId={accountId}
          onToggleOutbound={fanId != null ? outbound.toggle : undefined}
        >
          {quoted && (
            <div className={MP.ours.Composer.reply}>
              <ReplyStrip quoted={quoted} onCancel={() => onClearQuoted?.()} />
            </div>
          )}
          {ppvRowOpen && (
            <PpvRow
              price={price}
              onPrice={(raw) => setPrice(sanitizePriceInput(raw))}
              lockText={lockText}
              onLockText={setLockText}
              scheduleOn={scheduleOpen}
              at={scheduleAt}
              onAt={setScheduleAt}
              onClear={clearPpvRow}
              disabled={disabled}
            >
              {hasAttachments && (
                <FreePreviews
                  count={effectivePreviewCount}
                  total={attached.length}
                  enabled={showPpv}
                  onChange={bumpPreviewCount}
                />
              )}
              {attached.map((m, idx) => {
                const rawThumb =
                  m.files?.thumb?.url ||
                  m.files?.squarePreview?.url ||
                  m.files?.preview?.url ||
                  null;
                // A just-uploaded file shows its own blob: preview (the CDN has
                // not seen it yet; a claim has no `files` at all).
                const thumb = m._localPreview || proxyImage(rawThumb, accountId);
                // A tile only renders FREE if it's within the preview range
                // AND would actually survive the `previews` filter on send. A
                // still-uploading `_claim` tile is sent as media but cannot be
                // referenced by id in `previews`, so OF locks it — showing FREE
                // there would lie about what the fan sees. Render it as PPV.
                const isFreeTile = idx < effectivePreviewCount && canBeFreePreview(m);
                const isDragging = reorder.draggingIndex === idx;
                const isDragOver = reorder.dragOverIndex === idx && !isDragging;
                const priceLabel = numericPrice != null && numericPrice > 0
                  ? `$${numericPrice % 1 === 0 ? numericPrice : numericPrice.toFixed(2)}`
                  : "";
                // Three-state badge: BOUGHT (green) wins over the PPV split —
                // this fan already paid for this vault item, so the chatter
                // should know before sending it again. Falls through to the
                // free/paid colors below when no purchase record exists.
                const fanEntry = fanVaultQ.data?.by_media[String(m.id)];
                const wasBought = fanEntry?.was_purchased === true;
                return (
                  <Fragment key={m.id}>
                    {showDivider && idx === effectivePreviewCount && (
                      <div
                        className={cn(MP.ours.Composer.divider, "flex flex-col items-center justify-center uppercase select-none border-dashed border-fg-dim/60")}
                        title="Items left of this line are free previews; items right are PPV-locked"
                        aria-hidden
                      >
                        <span className="text-fg-dim leading-none">free ↑</span>
                        <span className="text-muted leading-none">/</span>
                        <span className="text-err leading-none">paid ↓</span>
                      </div>
                    )}
                    <div
                      draggable={!disabled}
                      onDragStart={(e) => reorder.onDragStart(e, idx)}
                      onDragOver={(e) => reorder.onDragOver(e, idx)}
                      onDrop={(e) => reorder.onDrop(e, idx)}
                      onDragEnd={reorder.onDragEnd}
                      tabIndex={0}
                      onKeyDown={(e) => {
                        if (e.key === "ArrowLeft") {
                          e.preventDefault();
                          reorder.onKeyboardMove(idx, -1);
                        } else if (e.key === "ArrowRight") {
                          e.preventDefault();
                          reorder.onKeyboardMove(idx, 1);
                        }
                      }}
                      className={cn(
                        MP.ppvRow.attachment,
                        "relative overflow-hidden bg-bg-elev-1 group select-none",
                        "motion-safe:transition-transform motion-safe:duration-150",
                        "cursor-grab active:cursor-grabbing",
                        "focus:outline-none focus:ring-2 focus:ring-accent",
                        isDragging ? "opacity-40 border-accent" : "border-border",
                        isDragOver && "ring-2 ring-accent",
                      )}
                    >
                      {thumb ? (
                        <img src={thumb} alt="" loading="lazy" decoding="async" draggable={false} className="w-full h-full object-cover pointer-events-none" />
                      ) : (
                        <div className={cn(MP.ours.Composer.tileType, "w-full h-full grid place-items-center text-fg-dim")}>
                          {m.type}
                        </div>
                      )}
                      {(showPpv || wasBought) && (
                        <div
                          className={cn(
                            MP.ours.Composer.tileBadge,
                            "absolute text-white shadow",
                            wasBought
                              ? "bg-ok"
                              : isFreeTile ? "bg-[var(--inf-offline,var(--color-fg-dim))]" : "bg-err",
                          )}
                          title={
                            wasBought
                              ? "BOUGHT — this fan has already purchased this item"
                              : isFreeTile
                                ? "Free preview — fans see this before paying"
                                : "PPV-locked — fans see this after paying"
                          }
                        >
                          {wasBought ? "BOUGHT" : isFreeTile ? "FREE" : priceLabel || "PPV"}
                        </div>
                      )}
                      <button
                        type="button"
                        onClick={() => removeAttachment(m.id)}
                        className={cn(MP.ppvRow.attachmentRemove, MP.ours.Composer.tileRemove, "absolute bg-black/75 text-white")}
                        aria-label="Remove attachment"
                      >
                        ✕
                      </button>
                    </div>
                  </Fragment>
                );
              })}
              {uploads.chips.map((u) => (
                <div
                  key={u.key}
                  role="group"
                  aria-label={u.status === "failed" ? `Upload failed: ${u.file.name}` : `Uploading ${u.file.name}`}
                  title={u.status === "failed" ? `${u.file.name}: ${u.error ?? ""}` : `Uploading ${u.file.name}…`}
                  className={cn(
                    MP.ppvRow.attachment,
                    "relative overflow-hidden bg-bg-elev-1",
                    u.status === "failed" ? cn(MP.ours.Composer.uploadFailed, "w-auto flex items-center border-err/50 text-err") : "border-border",
                  )}
                >
                  {u.status === "uploading" ? (
                    <>
                      {u.previewUrl && u.file.type.startsWith("image/") && (
                        // eslint-disable-next-line @next/next/no-img-element
                        <img src={u.previewUrl} alt="" className="w-full h-full object-cover opacity-50" />
                      )}
                      <span role="status" aria-label="Uploading" className="absolute inset-0 grid place-items-center">
                        <span aria-hidden className="size-4 rounded-full border-2 border-fg-dim/40 border-t-accent motion-safe:animate-spin" />
                      </span>
                    </>
                  ) : (
                    <>
                      <span className="truncate min-w-0">⚠ {uploadErrorText(u.error ?? "")}</span>
                      <button
                        type="button"
                        onClick={() => uploads.retry(u.key)}
                        className="shrink-0 underline hover:text-fg"
                      >
                        Retry
                      </button>
                    </>
                  )}
                  <button
                    type="button"
                    onClick={() => uploads.remove(u.key)}
                    className={cn(MP.ppvRow.attachmentRemove, MP.ours.Composer.tileRemove, "absolute bg-black/75 text-white")}
                    aria-label="Remove upload"
                  >
                    ✕
                  </button>
                </div>
              ))}
              {pickedGifs.map((g) => (
                <div
                  key={g.id}
                  title={pickedGifs.length > 1 ? `${pickedGifs.length} GIFs — sent as separate messages` : "1 GIF attached"}
                  className={cn(MP.ppvRow.attachment, "relative overflow-hidden border-border bg-bg-elev-1")}
                >
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={g.thumbUrl} alt={g.title || "GIF"} className="w-full h-full object-cover" />
                  <button
                    type="button"
                    onClick={() => setPickedGifs((prev) => prev.filter((p) => p.id !== g.id))}
                    className={cn(MP.ppvRow.attachmentRemove, MP.ours.Composer.tileRemove, "absolute bg-black/75 text-white")}
                    aria-label="Remove GIF"
                  >
                    ✕
                  </button>
                </div>
              ))}
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
          initialSelectedIds={attached.filter((m) => !m._claim && m.id > 0).map((m) => m.id)}
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

/** Same shape, offset N minutes into the future. Used by ⏱'s "Send at" preset
 *  buttons (+5m, +10m, …) so picking a preset feels like a normal input
 *  fill — the input itself shows the resolved time. */
function localFutureForInput(minutes: number): string {
  return toLocalInput(new Date(Date.now() + minutes * 60_000));
}


/** Whether an attached tile can ride in the numeric `previews` array (the
 *  free-teaser split). A freshly-uploaded item still transcoding carries a
 *  `_claim` instead of a real vault id, so it CAN be sent as media but
 *  CANNOT be referenced by id in `previews` — OF would lock it. Keeping the
 *  send-time filter and the FREE-badge render in one predicate stops the UI
 *  from promising a free teaser the wire layer silently drops. */
function canBeFreePreview(m: VaultMedia): boolean {
  return !m._claim && Number.isFinite(m.id) && m.id > 0;
}

/** Accept "5", "5.00", "5,50". Returns null on garbage so submit stays
 *  free of guard-clauses on every read. */
function parsePrice(raw: string): number | null {
  const cleaned = raw.replace(/\s/g, "").replace(",", ".");
  if (!cleaned) return null;
  const n = Number(cleaned);
  if (!Number.isFinite(n)) return null;
  return n;
}

/** Strip everything except digits and a single decimal separator from
 *  PPV input. Lets the user type "12.56" but bounces letters / "+5" /
 *  multiple dots so a paid send can never ship a malformed body. Empty
 *  string passes through so backspace clears the field cleanly. */
export function sanitizePriceInput(raw: string): string {
  // Allow commas as a decimal alias — `parsePrice` normalises to dot.
  const cleaned = raw.replace(/[^\d.,]/g, "").replace(/,/g, ".");
  const dot = cleaned.indexOf(".");
  if (dot === -1) return cleaned;
  // Keep only the FIRST decimal point; strip subsequent dots.
  return cleaned.slice(0, dot + 1) + cleaned.slice(dot + 1).replace(/\./g, "");
}
