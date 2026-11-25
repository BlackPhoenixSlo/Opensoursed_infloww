import { previewIdsFor, textBoxReducer, wireMedia, type TextBoxAction } from "@/lib/composeDraft";
import { OF_TEXT_MAX, TEXT_TOO_LONG } from "@/lib/ofRichText";
import { plainLength } from "@/lib/ofRichTextEditor";
import { PLAIN_MODE, type RichMode } from "@/lib/ofRichMode";
import { localDatetimeToIso } from "@/lib/scheduleHistory";
import type { TaggedCreatorChoice, VaultMedia } from "@/lib/relay";
import { isAccountSwitch } from "@/components/audience/audienceReducer";

import { fanOutLocked, fanOutReducer, initFanOut, noTargetsReason, type FanOutAction, type FanOutState } from "./fanOut";

export interface PostForm extends FanOutState {
  allModels: boolean;
  accountId: string | null;
  text: string;
  mode: RichMode;
  attached: VaultMedia[];
  price: string;
  previewCount: number;
  schedule: string;
  taggedCreators: TaggedCreatorChoice[];
}

export type PostField = "text" | "attached" | "price" | "previewCount" | "schedule" | "taggedCreators";

export type PostAction =
  | { [K in PostField]: { type: "field"; k: K; v: PostForm[K] } }[PostField]
  | { type: "appendText"; v: string }
  | { type: "setAccount"; id: string | null }
  | { type: "setAllModels"; on: boolean }
  | TextBoxAction
  | FanOutAction;

export function postFieldAction<K extends PostField>(
  k: K, v: PostForm[K],
): Extract<PostAction, { type: "field"; k: K }> {
  return { type: "field", k, v } as Extract<PostAction, { type: "field"; k: K }>;
}

export function initPostForm(): PostForm {
  return {
    allModels: false, accountId: null, text: "", mode: PLAIN_MODE, attached: [], price: "", previewCount: 0,
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
    case "aa":
      return textBoxReducer(s, a);
  }
}

export function sendAccount(f: Pick<PostForm, "allModels" | "accountId">): string | null {
  return f.allModels ? null : f.accountId;
}

// A subscription page has no paid-post lane on OF (relay 409s a priced post): its price reads as 0.
function countedPrice(f: Pick<PostForm, "allModels" | "price">, paidPage: boolean): number | null {
  return f.allModels || paidPage ? null : f.price ? Number(f.price) : 0;
}

export function postPrice(f: Pick<PostForm, "allModels" | "price">, paidPage: boolean): number {
  const n = countedPrice(f, paidPage) ?? 0;
  return Number.isFinite(n) && n > 0 ? n : 0;
}

function sent(f: PostForm, paidPage: boolean) {
  const textOnly = f.allModels;
  return {
    price: postPrice(f, paidPage),
    media: textOnly ? [] : f.attached,
    tags: textOnly ? [] : f.taggedCreators,
  };
}

export interface PostCtx {
  broadcastCount: number;
  paidPage: boolean;
}

export function validatePost(f: PostForm, ctx: PostCtx): string | null {
  if (f.allModels) {
    if (ctx.broadcastCount === 0) return noTargetsReason(f.results);
  } else if (!f.accountId) {
    return "Pick an account";
  }
  const typed = countedPrice(f, ctx.paidPage);
  if (typed !== null && !(Number.isFinite(typed) && typed >= 0)) return "Invalid price";
  const { price, media } = sent(f, ctx.paidPage);
  // OF rejects a priced text-only post (mirrored server-side in auto_posts: paid_no_media).
  if (price > 0 && media.length === 0) return "A paid post needs at least one image";
  if (!f.text.trim() && media.length === 0) return f.allModels ? "Add text" : "Add text or media";
  if (plainLength(f.text) > OF_TEXT_MAX) return TEXT_TOO_LONG;
  if (f.schedule && !localDatetimeToIso(f.schedule)) return "Invalid schedule date";
  return null;
}

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
