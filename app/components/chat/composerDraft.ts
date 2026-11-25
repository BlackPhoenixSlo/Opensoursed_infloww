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
 *   • OF's rich text (bold, italic, colour, size): the text's markup lives in
 *     `rich` beside its plain text (the Composer's `text`, what the Fan List,
 *     "/" search, translation and sensitive words read); the send carries the
 *     markup while the text is still that plain text (`richText`), so text
 *     replaced from outside (Use translation) goes plain with no flag to keep.
 *     The rich editor's edits set it (`setRich`); a formatted template sets
 *     it only where the account takes OF markup (`pickTemplate`'s `rich`: an
 *     OnlyFans account, never Fansly). "Aa" (`aa`) and the box it puts the
 *     text in are `mode`, lib/ofRichMode's state machine.
 *   • Blob previews are a side effect and stay out of it (useBlobPreviews).
 */

import { applyTemplate, canBeFreePreview } from "@/lib/composeDraft";
import { isSourceScript } from "@/lib/chatSlots";
import { hasOfFormatting, isOfHtml } from "@/lib/ofRichText";
import { PLAIN_MODE, richMode, type RichMode } from "@/lib/ofRichMode";
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
  attached?: VaultMedia[];
  // Vault media ids sent UNLOCKED when price > 0; the locked/unlocked split is per media id, not by position
  previews?: number[];
  scheduledAt?: string;
  // Picker guarantees taggable creators: OF 400s otherwise
  taggedUsers?: number[];
  // OF accepts a single GIF per send; the parent splits multiple
  giphyId?: string;
  uploads?: PendingUpload[];
}

export interface ComposerDraft {
  price: string;
  priceOpen: boolean;
  lockedText: boolean;
  attached: VaultMedia[];
  previewCount: number;
  scheduleOpen: boolean;
  scheduleAt: string;
  taggedCreators: TaggedCreatorChoice[];
  pickedGifs: PickedGif[];
  script: { scriptId: string; scriptStep: number } | null;
  rich: { html: string; plain: string } | null;
  mode: RichMode;
  replyId: number | null;
}

export const EMPTY_DRAFT: ComposerDraft = {
  price: "", priceOpen: false, lockedText: false, attached: [], previewCount: 0,
  scheduleOpen: false, scheduleAt: "", taggedCreators: [], pickedGifs: [], script: null, rich: null, replyId: null,
  mode: PLAIN_MODE,
};

const PPV_EMPTY: Pick<
  ComposerDraft, "price" | "priceOpen" | "lockedText" | "attached" | "previewCount" | "scheduleOpen" | "scheduleAt" | "pickedGifs"
> = {
  price: "", priceOpen: false, lockedText: false, attached: [], previewCount: 0, scheduleOpen: false, scheduleAt: "",
  pickedGifs: [],
};

export function sentReplyId(d: ComposerDraft): number | null {
  return d.replyId != null && !isSourceScript(d.script?.scriptId) ? d.replyId : null;
}

export type DraftAction =
  | { type: "pickTemplate"; t: PickedTemplate; allowRich: boolean }
  | { type: "aa" }
  | { type: "setRich"; rich: { html: string; plain: string } | null }
  | { type: "pickVault"; picked: VaultMedia[] }
  | { type: "uploaded"; media: VaultMedia[] }
  | { type: "reorder"; attached: VaultMedia[] }
  | { type: "removeAttachment"; id: number }
  | { type: "setPrice"; raw: string }
  | { type: "setPriceOpen"; open: boolean }
  | { type: "setLockText"; on: boolean }
  | { type: "stepPreviews"; by: 1 | -1 }
  | { type: "schedule"; open?: boolean; at?: string }
  | { type: "addGif"; gif: PickedGif }
  | { type: "removeGif"; id: string }
  | { type: "setTags"; tags: TaggedCreatorChoice[] }
  | { type: "clearPpv" }
  | { type: "dropScript" }
  | { type: "endScript"; scriptId: string }
  | { type: "sent" }
  | { type: "clear" }
  | { type: "restore"; snapshot: ComposerDraft };

export function composerDraft(s: ComposerDraft, a: DraftAction): ComposerDraft {
  switch (a.type) {
    case "pickTemplate": {
      const { scriptId, scriptStep } = a.t;
      const script = scriptId && typeof scriptStep === "number" ? { scriptId, scriptStep } : null;
      const rich = a.allowRich && hasOfFormatting(a.t.displayText) ? { html: a.t.displayText.trim(), plain: a.t.text } : null;
      const mode = richMode(s.mode, { type: "loaded", formatted: !!rich, allowed: a.allowRich });
      return { ...applyTemplate(s, a.t), priceOpen: a.t.price > 0, script, rich, mode, replyId: a.t.replyId ?? null };
    }
    case "aa":
      return { ...s, mode: richMode(s.mode, { type: "aa", formatted: s.rich != null }) };
    case "setRich": {
      const mode = richMode(s.mode, { type: "edited", formatted: a.rich != null });
      return a.rich?.html === s.rich?.html && mode === s.mode ? s : { ...s, rich: a.rich, mode };
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
      return { ...s, ...PPV_EMPTY };
    case "endScript":
      return s.script?.scriptId === a.scriptId ? { ...s, script: null } : s;
    case "dropScript":
      return { ...s, script: null, replyId: null };
    case "sent":
    case "clear":
      return { ...EMPTY_DRAFT, mode: richMode(s.mode, { type: "sent" }) };
    case "restore":
      return a.snapshot;
  }
}

export function isEmptyDraft(d: ComposerDraft): boolean {
  return (
    d.price === "" && !d.priceOpen && !d.lockedText && d.attached.length === 0 && d.previewCount === 0 &&
    !d.scheduleOpen && d.scheduleAt === "" && d.taggedCreators.length === 0 && d.pickedGifs.length === 0 &&
    d.script == null && d.rich == null && d.replyId == null
  );
}

export function richFromEditor(value: string, plainOf: (html: string) => string): { text: string; rich: ComposerDraft["rich"] } {
  if (!isOfHtml(value)) return { text: value, rich: null };
  const plain = plainOf(value);
  return { text: plain, rich: { html: value, plain } };
}

export function richText(d: ComposerDraft, text: string): string | null {
  return d.rich && d.rich.plain.trim() === text.trim() ? d.rich.html : null;
}

export interface FullDraft {
  text: string;
  draft: ComposerDraft;
}

export interface LiveDraft extends FullDraft {
  uploadChips: number;
}

export function isEmptyLiveDraft({ text, draft, uploadChips }: LiveDraft): boolean {
  return text === "" && uploadChips === 0 && isEmptyDraft(draft);
}

export function afterRefusedSchedule(now: LiveDraft | null): "restore" | "offer" {
  return now != null && isEmptyLiveDraft(now) ? "restore" : "offer";
}

export function paidPrice(d: ComposerDraft): number | null {
  const price = parsePrice(d.price);
  return price != null && price > 0 ? price : null;
}

export function effectivePreviewCount(d: ComposerDraft): number {
  return Math.max(0, Math.min(d.previewCount, d.attached.length));
}

export function isScheduling(d: ComposerDraft, now: number): boolean {
  return d.scheduleOpen && !!d.scheduleAt && new Date(d.scheduleAt).getTime() > now;
}

export interface SendCtx {
  text: string;
  disabled?: boolean;
  chatCanSend: boolean;
  uploading: boolean;
  uploadFailed: boolean;
  now: number;
}

export const FAILED_UPLOAD_NOTE = "Retry or remove the failed upload first";

export function scheduleWaitReason(ctx: Pick<SendCtx, "uploading" | "uploadFailed">): string | null {
  if (ctx.uploadFailed) return FAILED_UPLOAD_NOTE;
  return ctx.uploading ? "Wait for the upload to finish before scheduling" : null;
}

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
  uploadChips: number;
}

export function composerView(d: ComposerDraft, ctx: ViewCtx) {
  const price = parsePrice(d.price);
  const paid = paidPrice(d);
  const previews = effectivePreviewCount(d);
  // OF refuses a paid price under $3
  const priceError = priceNote(price);
  const holds = d.attached.length > 0 || d.pickedGifs.length > 0 || ctx.uploadChips > 0 || paid != null;
  const ppvHeld = holds || d.scheduleOpen;
  return {
    paid,
    priceLabel: paid == null ? "" : `$${paid % 1 === 0 ? paid : paid.toFixed(2)}`,
    priceError,
    previews,
    showDivider: paid != null && previews > 0 && previews < d.attached.length,
    ppvHeld,
    ppvRowOpen: d.priceOpen || ppvHeld,
    held: holds,
    scheduling: isScheduling(d, ctx.now),
    canSend: canSend(d, ctx),
    sendBlockedReason: sendBlockedReason(d, ctx),
    timedBlockedReason: scheduleWaitReason(ctx) ?? priceError,
  };
}

export function buildSendArgs(
  d: ComposerDraft,
  opts: { text: string; delayMinutes?: number; now: number; plainOnly?: boolean },
): SendArgs {
  // plainOnly: a Fansly account, or a translation sent in the draft's place, never sends OF markup
  const args: SendArgs = { text: (!opts.plainOnly && richText(d, opts.text)) || opts.text };
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
    // datetime-local has no tz suffix: the Date constructor reads it as local
    args.scheduledAt = new Date(d.scheduleAt).toISOString();
  }
  return args;
}

// The FREE-badge render shares lib/composeDraft's rule so the UI never promises a free teaser the wire layer drops
export { canBeFreePreview };
