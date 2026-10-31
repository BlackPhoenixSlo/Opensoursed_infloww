/**
 * composerDraft — the chat Composer's draft beyond its text: the PPV price
 * and lock, attached media and their free previews, the schedule, @-tagged
 * creators and GIFs. A pure reducer, so a send clears it and a refused
 * schedule restores it in one step each, and `canSend` / `buildSendArgs`
 * read one value instead of ten.
 *
 *   • The text is not here: it is the chat's sessionStorage draft
 *     (`useChatDraft`), which the Fan List reads too.
 *   • `sent` empties the draft, `lockedText` included (it used to ride on to
 *     the next PPV). `restore` puts a snapshot back: a refused schedule's
 *     (`afterRefusedSchedule` decides whether it may overwrite what the
 *     chatter has done since, or is offered beside it).
 *   • A template is a snapshot (`pickTemplate`, lib/composeDraft
 *     `applyTemplate`): media, preview count, price and GIF replace what was
 *     there; a free one clears the price and the lock. Its tags join the
 *     picked ones. A paid one opens the PPV row. (The Composer sets the text.)
 *     A Script step's template is `script`, so its send advances the Script;
 *     `sent` and the FM bubble's AI draft (`dropScript`) forget it, `clearPpv`
 *     keeps it (the text it rode on stays).
 *   • A Vault pick (`pickVault`) replaces the picked media wholesale but keeps
 *     an upload still transcoding (`_claim`) and an uploaded item's own files
 *     and blob preview; media with a suggested price set the price to the
 *     highest of them and open the PPV row.
 *   • Blob previews are a side effect and stay out of it (useBlobPreviews).
 */

import { applyTemplate, canBeFreePreview } from "@/lib/composeDraft";
import type { VaultMedia } from "@/lib/relay";
import { parsePrice, sanitizePriceInput } from "@/lib/priceInput";
import { priceNote } from "@/lib/sendGuards";
import type { PendingUpload } from "@/hooks/useComposerUploads";

import { gifPlan } from "./composerSubmit";
import type { PickedGif } from "./GifPicker";
import type { PickedTemplate } from "./TemplatePicker";
import type { TaggedCreatorChoice } from "./TagCreatorsPicker";

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

export interface ComposerDraft {
  /** As typed (sanitized); `parsePrice` reads it. */
  price: string;
  /** The PPV pill. */
  priceOpen: boolean;
  /** Opt-in (asks #6 + #17). */
  lockedText: boolean;
  attached: VaultMedia[];
  /** How many leading tiles are FREE previews; may exceed `attached` (read
   *  through `effectivePreviewCount`). */
  previewCount: number;
  scheduleOpen: boolean;
  /** datetime-local value, no tz suffix. */
  scheduleAt: string;
  taggedCreators: TaggedCreatorChoice[];
  /** OF takes ONE GIF per send; the rest go as GIF-only sends after it. */
  pickedGifs: PickedGif[];
  /** The Script step this draft was loaded from; its send advances the Script. */
  script: { scriptId: string; scriptStep: number } | null;
}

export const EMPTY_DRAFT: ComposerDraft = {
  price: "", priceOpen: false, lockedText: false, attached: [], previewCount: 0,
  scheduleOpen: false, scheduleAt: "", taggedCreators: [], pickedGifs: [], script: null,
};

export type DraftAction =
  | { type: "pickTemplate"; t: PickedTemplate }
  | { type: "pickVault"; picked: VaultMedia[] }
  /** Uploads that landed; an id already attached is not added twice. */
  | { type: "uploaded"; media: VaultMedia[] }
  /** Tiles dragged into a new order. */
  | { type: "reorder"; attached: VaultMedia[] }
  | { type: "removeAttachment"; id: number }
  | { type: "setPrice"; raw: string }
  | { type: "setPriceOpen"; open: boolean }
  | { type: "setLockText"; on: boolean }
  /** The free previews stepper: one more / fewer than the count it shows. */
  | { type: "stepPreviews"; by: 1 | -1 }
  /** Either field alone leaves the other as it is. */
  | { type: "schedule"; open?: boolean; at?: string }
  | { type: "addGif"; gif: PickedGif }
  | { type: "removeGif"; id: string }
  | { type: "setTags"; tags: TaggedCreatorChoice[] }
  /** The PPV row's Clear: everything it lists goes (the text stays). */
  | { type: "clearPpv" }
  /** The FM bubble's AI draft replaces the text: it is no Script step. */
  | { type: "dropScript" }
  | { type: "sent" }
  | { type: "restore"; snapshot: ComposerDraft };

export function composerDraft(s: ComposerDraft, a: DraftAction): ComposerDraft {
  switch (a.type) {
    case "pickTemplate": {
      const { scriptId, scriptStep } = a.t;
      const script = scriptId && typeof scriptStep === "number" ? { scriptId, scriptStep } : null;
      return { ...applyTemplate(s, a.t), priceOpen: a.t.price > 0, script };
    }
    case "pickVault": {
      const byId = new Map(s.attached.map((m) => [m.id, m]));
      const attached = [
        ...a.picked.map((p) => {
          const had = byId.get(p.id);
          return had ? { ...p, ...had, files: had.files ?? p.files } : p;
        }),
        ...s.attached.filter((m) => m._claim),
      ];
      // A bundle is worth the HIGHEST suggested price in it; unpriced media
      // leave the typed price alone.
      const top = a.picked.reduce((max, m) => {
        const c = m._ai?.suggested_price_cents;
        return typeof c === "number" && c > max ? c : max;
      }, 0);
      return top > 0
        ? { ...s, attached, price: (top / 100).toFixed(2), priceOpen: true }
        : { ...s, attached };
    }
    case "uploaded": {
      const have = new Set(s.attached.map((m) => m.id));
      return { ...s, attached: [...s.attached, ...a.media.filter((m) => !have.has(m.id))] };
    }
    case "reorder":
      return { ...s, attached: a.attached };
    case "removeAttachment":
      return { ...s, attached: s.attached.filter((m) => m.id !== a.id) };
    case "setPrice":
      return { ...s, price: sanitizePriceInput(a.raw) };
    case "setPriceOpen":
      return { ...s, priceOpen: a.open };
    case "setLockText":
      return { ...s, lockedText: a.on };
    case "stepPreviews":
      // From the count on show: a stored count past the tiles is clamped first.
      return {
        ...s,
        previewCount: Math.max(0, Math.min(s.attached.length, effectivePreviewCount(s) + a.by)),
      };
    case "schedule":
      return { ...s, scheduleOpen: a.open ?? s.scheduleOpen, scheduleAt: a.at ?? s.scheduleAt };
    case "addGif":
      return {
        ...s,
        pickedGifs: s.pickedGifs.some((p) => p.id === a.gif.id) ? s.pickedGifs : [...s.pickedGifs, a.gif],
      };
    case "removeGif":
      return { ...s, pickedGifs: s.pickedGifs.filter((p) => p.id !== a.id) };
    case "setTags":
      return { ...s, taggedCreators: a.tags };
    case "clearPpv":
      // Tags are not in the PPV row, and the Script step rides on the text: both stay.
      return { ...EMPTY_DRAFT, taggedCreators: s.taggedCreators, script: s.script };
    case "dropScript":
      return { ...s, script: null };
    case "sent":
      return EMPTY_DRAFT;
    case "restore":
      return a.snapshot;
  }
}

/** Nothing on the draft: what `sent` leaves. */
export function isEmptyDraft(d: ComposerDraft): boolean {
  return (
    d.price === "" && !d.priceOpen && !d.lockedText && d.attached.length === 0 && d.previewCount === 0 &&
    !d.scheduleOpen && d.scheduleAt === "" && d.taggedCreators.length === 0 && d.pickedGifs.length === 0 &&
    d.script == null
  );
}

/** A Composer's whole draft: the text and the rest. */
export interface FullDraft {
  text: string;
  draft: ComposerDraft;
}

/** Where a refused schedule's draft goes: back into an untouched Composer
 *  (still as `sent` left it), else, once the chatter has typed or attached
 *  since, or left the chat (`now` null: no Composer to go back into), as an
 *  offer to restore it. Nothing is lost. */
export function afterRefusedSchedule(now: FullDraft | null): "restore" | "offer" {
  return now != null && now.text === "" && isEmptyDraft(now.draft) ? "restore" : "offer";
}

/** A price > 0, else null: a typed price > 0 is the sole paid signal. */
export function paidPrice(d: ComposerDraft): number | null {
  const price = parsePrice(d.price);
  return price != null && price > 0 ? price : null;
}

/** Clamped on read so removing tiles never leaves FREE badges past the end. */
export function effectivePreviewCount(d: ComposerDraft): number {
  return Math.max(0, Math.min(d.previewCount, d.attached.length));
}

/** A scheduled send: the schedule is on with a time still ahead. */
export function isScheduling(d: ComposerDraft, now: number): boolean {
  return d.scheduleOpen && !!d.scheduleAt && new Date(d.scheduleAt).getTime() > now;
}

export interface SendCtx {
  /** The draft text (`useChatDraft`). */
  text: string;
  disabled?: boolean;
  /** OF lets this chat be sent to. */
  chatCanSend: boolean;
  /** A file is still uploading / one failed (`useComposerUploads`). */
  uploading: boolean;
  uploadFailed: boolean;
  now: number;
}

export const FAILED_UPLOAD_NOTE = "Retry or remove the failed upload first";

/** Why a schedule (the Schedule button, the Timed message) must wait: it
 *  needs the media ids now, so a running upload holds it. */
export function scheduleWaitReason(ctx: Pick<SendCtx, "uploading" | "uploadFailed">): string | null {
  if (ctx.uploadFailed) return FAILED_UPLOAD_NOTE;
  return ctx.uploading ? "Wait for the upload to finish before scheduling" : null;
}

/** Why Send is held, shown on it. An immediate send takes a running upload
 *  over, so only a failed one holds it; OF refuses a paid price under $3. */
export function sendBlockedReason(d: ComposerDraft, ctx: SendCtx): string | null {
  const uploadReason = isScheduling(d, ctx.now)
    ? scheduleWaitReason(ctx)
    : ctx.uploadFailed ? FAILED_UPLOAD_NOTE : null;
  return uploadReason ?? priceNote(parsePrice(d.price));
}

export function canSend(d: ComposerDraft, ctx: SendCtx): boolean {
  return (
    !ctx.disabled &&
    ctx.chatCanSend &&
    sendBlockedReason(d, ctx) == null &&
    (ctx.text.trim().length > 0 || d.attached.length > 0 || d.pickedGifs.length > 0 || ctx.uploading)
  );
}

export interface ViewCtx extends SendCtx {
  /** Upload chips on show (`useComposerUploads`), failed ones included. */
  uploadChips: number;
}

/** What the Composer shows, derived from the draft in one place. */
export function composerView(d: ComposerDraft, ctx: ViewCtx) {
  const price = parsePrice(d.price);
  const paid = paidPrice(d);
  const previews = effectivePreviewCount(d);
  const priceError = priceNote(price);
  // What the PPV row lists keeps it open, whatever the pill says (spec, The
  // PPV row; Clone messages.js:1838).
  const holds = d.attached.length > 0 || d.pickedGifs.length > 0 || ctx.uploadChips > 0 || paid != null;
  const ppvHeld = holds || d.scheduleOpen;
  return {
    paid,
    /** The tiles' paid badge: "$5", "$5.50"; "" when free. */
    priceLabel: paid == null ? "" : `$${paid % 1 === 0 ? paid : paid.toFixed(2)}`,
    /** OF refuses a price under $3 that is not free (shown above the input). */
    priceError,
    previews,
    /** The free ↑ / paid ↓ divider sits between the tiles. */
    showDivider: paid != null && previews > 0 && previews < d.attached.length,
    ppvHeld,
    ppvRowOpen: d.priceOpen || ppvHeld,
    /** What leaving this Fan would lose: the per-Fan draft keeps only the text. */
    held: holds,
    scheduling: isScheduling(d, ctx.now),
    canSend: canSend(d, ctx),
    sendBlockedReason: sendBlockedReason(d, ctx),
    /** Why the Timed message waits: a running upload, else the price. */
    timedBlockedReason: scheduleWaitReason(ctx) ?? priceError,
  };
}

/** The send's args from the draft, uploads aside (the Composer hands those
 *  over only once the send is sure to go). `text` is the trimmed body. A
 *  Timed message's `delayMinutes` wins over the schedule's time; a time
 *  already past sends at once. Only the first GIF rides along. */
export function buildSendArgs(
  d: ComposerDraft,
  opts: { text: string; delayMinutes?: number; now: number },
): SendArgs {
  const args: SendArgs = { text: opts.text };
  const price = paidPrice(d);
  if (price != null) {
    args.price = price;
    args.lockedText = d.lockedText;
    const free = effectivePreviewCount(d);
    if (free > 0) args.previews = d.attached.slice(0, free).filter(canBeFreePreview).map((m) => m.id);
  }
  if (d.attached.length > 0) args.attached = d.attached;
  if (d.taggedCreators.length > 0) args.taggedUsers = d.taggedCreators.map((c) => c.id);
  const { first: gif } = gifPlan(d.pickedGifs);
  if (gif) args.giphyId = gif.id;
  if (opts.delayMinutes && opts.delayMinutes > 0) {
    args.scheduledAt = new Date(opts.now + opts.delayMinutes * 60_000).toISOString();
  } else if (isScheduling(d, opts.now)) {
    // datetime-local has no tz suffix: the Date constructor reads it as local.
    args.scheduledAt = new Date(d.scheduleAt).toISOString();
  }
  return args;
}

/** Whether an attached tile can ride in the numeric `previews` array (the
 *  free-teaser split): lib/composeDraft's one rule, re-exported for the
 *  FREE-badge render (PpvTiles), so the UI never promises a free teaser the
 *  wire layer drops. */
export { canBeFreePreview };
