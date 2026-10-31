/**
 * postComposerReducer — PostComposer's form: one state, one reducer, and the
 * pure rules the component only calls.
 *
 *   • What a post SENDS is derived (`sent`), never stored-and-cleared: an
 *     all-models post is text-only (price 0, no media, previews or tags), and
 *     on a subscription page (`PostCtx.paidPage`: OF has no paid-post lane
 *     there) the price reads as 0, so no previews either. The typed values
 *     stay in the form, hidden; they can't block or ride into the post.
 *   • A new account drops the old one's vault media, previews and tagged
 *     creators (they belong to that account) — only on a switch away from a
 *     real account (audience/audienceReducer `isAccountSwitch`): the first pick
 *     (null → A) has nothing to drop. All-models keeps the account (hidden:
 *     `sendAccount` reads null while it is on), so on → off is back on it with
 *     its media, no re-pick.
 *   • `pickTemplate` is lib/composeDraft `applyTemplate` (a FREE template
 *     clears a typed price).
 *   • The fan-out lifecycle is compose/fanOut's slice: results merge by
 *     account, a retry posts only to the included models without a success
 *     (`fanOutTargets`), and while a round is in flight or once a model took
 *     the post the content is locked (every action here but the lifecycle
 *     ones is refused; Start over, `discardResults`, unlocks the latter).
 *     Leaving all-models clears the results. The send's error is the
 *     component's useMutation's.
 *   • `validatePost` is the ONE check the Post button and the create mutation
 *     ask; `buildPostBody` the one body (built once, sent to every model).
 */

import { applyTemplate, previewIdsFor, wireMedia } from "@/lib/composeDraft";
import { localDatetimeToIso } from "@/lib/scheduleHistory";
import type { PickedTemplate } from "@/components/chat/TemplatePicker";
import type { TaggedCreatorChoice, VaultMedia } from "@/lib/relay";
import { isAccountSwitch } from "@/components/audience/audienceReducer";

import { fanOutLocked, fanOutReducer, initFanOut, noTargetsReason, type FanOutAction, type FanOutState } from "./fanOut";

export interface PostForm extends FanOutState {
  allModels: boolean;
  /** Kept while all-models is on (see the file header). */
  accountId: string | null;
  text: string;
  attached: VaultMedia[];
  /** The price input, "" = free. */
  price: string;
  /** Leading N tiles are FREE previews on a paid post; the rest PPV-locked. */
  previewCount: number;
  schedule: string;
  taggedCreators: TaggedCreatorChoice[];
}

/** Fields a plain input sets. */
export type PostField = "text" | "attached" | "price" | "previewCount" | "schedule" | "taggedCreators";

export type PostAction =
  | { [K in PostField]: { type: "field"; k: K; v: PostForm[K] } }[PostField]
  /** Emoji with no textarea cursor: appended to the CURRENT text. */
  | { type: "appendText"; v: string }
  | { type: "setAccount"; id: string | null }
  | { type: "setAllModels"; on: boolean }
  | { type: "pickTemplate"; t: PickedTemplate }
  | FanOutAction;

/** The `field` action for `k` (the cast is the one TS can't prove: a
 *  generic `k` against the per-field union). */
export function postFieldAction<K extends PostField>(
  k: K, v: PostForm[K],
): Extract<PostAction, { type: "field"; k: K }> {
  return { type: "field", k, v } as Extract<PostAction, { type: "field"; k: K }>;
}

export function initPostForm(): PostForm {
  return {
    allModels: false, accountId: null, text: "", attached: [], price: "", previewCount: 0,
    schedule: "", taggedCreators: [], ...initFanOut(),
  };
}

export function postComposerReducer(s: PostForm, a: PostAction): PostForm {
  switch (a.type) {
    case "progress":
    case "results":
    case "discardResults":
      return fanOutReducer(s, a);
  }
  // A round in flight, or a model took the post: the content is locked.
  if (fanOutLocked(s)) return s;
  switch (a.type) {
    case "field":
      return s[a.k] === a.v ? s : { ...s, [a.k]: a.v };
    case "appendText":
      return { ...s, text: s.text + a.v };
    case "setAccount":
      if (a.id === s.accountId) return s;
      return isAccountSwitch(s.accountId, a.id)
        ? { ...s, accountId: a.id, attached: [], previewCount: 0, taggedCreators: [] }
        : { ...s, accountId: a.id };
    case "setAllModels":
      return a.on === s.allModels ? s : { ...s, allModels: a.on, ...initFanOut() };
    case "pickTemplate":
      return applyTemplate(s, a.t);
  }
}

/** The account a one-account post goes to: null while all-models is on
 *  (the kept account is hidden, see the file header). */
export function sendAccount(f: Pick<PostForm, "allModels" | "accountId">): string | null {
  return f.allModels ? null : f.accountId;
}

/** The typed price where it counts (NaN if it doesn't parse); null where it
 *  doesn't: all-models (text-only) and a subscription page (free only). */
function countedPrice(f: Pick<PostForm, "allModels" | "price">, paidPage: boolean): number | null {
  return f.allModels || paidPage ? null : f.price ? Number(f.price) : 0;
}

/** The price that counts — always a finite number ≥ 0 (an unparsable input
 *  reads 0 here; `validatePost` refuses it). */
export function postPrice(f: Pick<PostForm, "allModels" | "price">, paidPage: boolean): number {
  const n = countedPrice(f, paidPage) ?? 0;
  return Number.isFinite(n) && n > 0 ? n : 0;
}

/** What the post sends (the file header's derived rule). */
function sent(f: PostForm, paidPage: boolean) {
  const textOnly = f.allModels;
  return {
    price: postPrice(f, paidPage),
    media: textOnly ? [] : f.attached,
    tags: textOnly ? [] : f.taggedCreators,
  };
}

export interface PostCtx {
  /** Models the all-models fan-out would post to (compose/fanOut `fanOutTargets`). */
  broadcastCount: number;
  /** The picked account is a subscription page (free posts only). */
  paidPage: boolean;
}

/** Why this post can't be created, or null. */
export function validatePost(f: PostForm, ctx: PostCtx): string | null {
  if (f.allModels) {
    if (ctx.broadcastCount === 0) return noTargetsReason(f.results);
  } else if (!f.accountId) {
    return "Pick an account";
  }
  const typed = countedPrice(f, ctx.paidPage);
  if (typed !== null && !(Number.isFinite(typed) && typed >= 0)) return "Invalid price";
  const { price, media } = sent(f, ctx.paidPage);
  // OF rejects a priced text-only post; a free post is fine on text alone.
  // (Mirrored server-side in auto_posts: "paid_no_media".)
  if (price > 0 && media.length === 0) return "A paid post needs at least one image";
  // All-models is text-only: media is no way out there.
  if (!f.text.trim() && media.length === 0) return f.allModels ? "Add text" : "Add text or media";
  if (f.schedule && !localDatetimeToIso(f.schedule)) return "Invalid schedule date";
  return null;
}

/** The POST /api/of/v2/posts body — the same for every model of a fan-out. */
export function buildPostBody(f: PostForm, paidPage: boolean): Record<string, unknown> {
  const { price, media, tags } = sent(f, paidPage);
  const body: Record<string, unknown> = {
    text: f.text.trim(),
    media_files: media.map(wireMedia),
    price,
    posted_at: f.schedule ? localDatetimeToIso(f.schedule) : null,
  };
  const previews = previewIdsFor(media, f.previewCount, price);
  if (previews.length > 0) body.previews = previews;
  if (tags.length > 0) body.tagged_users = tags.map((c) => c.id);
  return body;
}
