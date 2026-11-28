import { sendKey } from "@/lib/opId";
import { SENSITIVE_BLOCK_MESSAGE } from "@/lib/sensitiveWords";
import { previewIdsFor, textBoxReducer, wireMedia, type TextBoxAction } from "@/lib/composeDraft";
import { isOfHtml, OF_TEXT_MAX, ofPlainText, TEXT_TOO_LONG } from "@/lib/ofRichText";
import { plainLength } from "@/lib/ofRichTextEditor";
import { PLAIN_MODE, type RichMode } from "@/lib/ofRichMode";
import { localDatetimeToIso } from "@/lib/scheduleHistory";
import { DEFAULT_PLATFORM, type AccountPlatform, type Platform } from "@/lib/platform";
import { priceNote } from "@/lib/sendGuards";
import type { PickedGif } from "@/components/chat/GifPicker";
import type { TaggedCreatorChoice, VaultMedia } from "@/lib/relay";
import {
  audienceReducer, initAudience, isAccountSwitch, resetAudience, toggled, without,
  type AudienceAction, type AudienceState,
} from "@/components/audience/audienceReducer";

import { fanOutLocked, fanOutReducer, initFanOut, noTargetsReason, type FanOutAction, type FanOutState } from "./fanOut";

export type MassLaunch = AccountPlatform | null;

export interface MassForm extends AudienceState, FanOutState {
  platform: Platform;
  launch: MassLaunch;
  allModels: boolean;
  text: string;
  mode: RichMode;
  attached: VaultMedia[];
  price: string;
  previewCount: number;
  lockedText: boolean;
  smartInclude: Set<number>;
  smartExclude: Set<number>;
  schedule: string;
  funnelId: number | null;
  taggedCreators: TaggedCreatorChoice[];
  pickedGifs: PickedGif[];
  gifPickerOpen: boolean;
  gifFailures: GifFailure[] | null;
  onlineOnly: boolean;
  unreadLimit: string;
  recentChatHours: string;
  recentChatLimit: string;
  excludeRepliedHours: string;
  excludeInboundHours: string;
  unsendAfterHours: string;
  minTotalSpent: string;
  minTipped: string;
  subscribedOverDays: string;
  expiredOverDays: string;
  opId: string | null;
}

export interface GifFailure {
  id: string;
  title?: string;
  error: string;
}

export type MassField =
  | "text" | "attached" | "price" | "previewCount" | "lockedText" | "schedule" | "funnelId"
  | "taggedCreators" | "gifPickerOpen"
  | "onlineOnly" | "unreadLimit" | "recentChatHours" | "recentChatLimit" | "excludeRepliedHours"
  | "excludeInboundHours" | "unsendAfterHours" | "minTotalSpent" | "minTipped"
  | "subscribedOverDays" | "expiredOverDays";

export type MassAction =
  | { [K in MassField]: { type: "field"; k: K; v: MassForm[K] } }[MassField]
  | { type: "appendText"; v: string }
  | Exclude<AudienceAction, { type: "setAccount" }>
  | { type: "setAccount"; id: string | null; platform?: Platform }
  | { type: "launchPlatform"; platform: MassLaunch }
  | { type: "cycleSystem"; id: string }
  | { type: "toggleSmartInclude"; id: number }
  | { type: "toggleSmartExclude"; id: number }
  | { type: "setAllModels"; on: boolean }
  | TextBoxAction
  | { type: "addGif"; gif: PickedGif }
  | { type: "removeGif"; id: string }
  | { type: "gifSendsFailed"; failed: GifFailure[] }
  | { type: "opMinted"; id: string }
  | FanOutAction;

export function fieldAction<K extends MassField>(
  k: K, v: MassForm[K],
): Extract<MassAction, { type: "field"; k: K }> {
  return { type: "field", k, v } as Extract<MassAction, { type: "field"; k: K }>;
}

export function initMassForm(accountId: string | null = null, platform: Platform = DEFAULT_PLATFORM, launch: MassLaunch = null): MassForm {
  return {
    ...initAudience(accountId),
    ...initFanOut(),
    platform,
    launch,
    allModels: false,
    text: "",
    mode: PLAIN_MODE,
    attached: [],
    price: "",
    previewCount: 0,
    lockedText: false,
    smartInclude: new Set(),
    smartExclude: new Set(),
    schedule: "",
    funnelId: null,
    taggedCreators: [],
    pickedGifs: [],
    gifPickerOpen: false,
    gifFailures: null,
    onlineOnly: true,
    unreadLimit: "",
    recentChatHours: "",
    recentChatLimit: "",
    excludeRepliedHours: "",
    excludeInboundHours: "",
    unsendAfterHours: "",
    minTotalSpent: "",
    minTipped: "",
    subscribedOverDays: "",
    expiredOverDays: "",
    opId: null,
  };
}

function audienceReset(s: MassForm): MassForm {
  return { ...resetAudience(s), smartInclude: new Set(), smartExclude: new Set() };
}

function dropAccountScoped(s: MassForm): MassForm {
  return { ...s, attached: [], previewCount: 0, taggedCreators: [] };
}

function onPlatform(s: MassForm, platform?: Platform): MassForm {
  return platform && platform !== s.platform
    ? { ...s, platform, text: isOfHtml(s.text) ? ofPlainText(s.text) : s.text, mode: PLAIN_MODE }
    : s;
}

export function massMessageReducer(s: MassForm, a: MassAction): MassForm {
  switch (a.type) {
    case "progress":
    case "results":
      return fanOutReducer(s, a);
    case "discardResults": {
      const next = fanOutReducer(s, a);
      return next === s ? s : { ...next, opId: null };
    }
    case "opMinted":
      return { ...s, opId: a.id };
    case "launchPlatform": {
      const next = !fanOutLocked(s) && a.platform !== "unknown" && a.platform !== null
        ? onPlatform(s, a.platform) : s;
      return next.launch === a.platform ? next : { ...next, launch: a.platform };
    }
    case "gifSendsFailed":
      return { ...s, gifFailures: a.failed, progress: null };
  }
  // A round in flight, or a model that sent: content is locked so a paid broadcast can't be re-sent altered
  if (fanOutLocked(s)) return s;
  const next = editReducer(s, a);
  if (next === s || next.opId === null || massSendKey(next) === massSendKey(s)) return next;
  return { ...next, opId: null };
}

function massSendKey(f: MassForm): string {
  return sendKey(f.accountId, f.allModels, [...f.smartInclude], [...f.smartExclude],
    f.pickedGifs.slice(1).map((gif) => gif.id), buildMassBody(f, true));
}

function editReducer(s: MassForm, a: MassAction): MassForm {
  switch (a.type) {
    case "field":
      return s[a.k] === a.v ? s : { ...s, [a.k]: a.v };
    case "appendText":
      return { ...s, text: s.text + a.v };
    case "toggleInclude":
    case "toggleExclude":
    case "seedExclude":
      return audienceReducer(s, a);
    case "cycleSystem":
      return { ...s, includes: toggled(s.includes, a.id) };
    case "toggleSmartInclude":
      return { ...s, smartInclude: toggled(s.smartInclude, a.id), smartExclude: without(s.smartExclude, a.id) };
    case "toggleSmartExclude":
      return { ...s, smartExclude: toggled(s.smartExclude, a.id), smartInclude: without(s.smartInclude, a.id) };
    case "setAccount": {
      const next = onPlatform(audienceReducer(s, a), a.platform);
      return isAccountSwitch(s.accountId, a.id) ? audienceReset(dropAccountScoped(next)) : next;
    }
    case "setAllModels":
      if (a.on === s.allModels) return s;
      return audienceReset(a.on
        ? { ...dropAccountScoped(s), ...initFanOut(), allModels: true, accountId: null, price: "", lockedText: false }
        : { ...s, ...initFanOut(), allModels: false });
    case "pickTemplate":
    case "aa":
      return textBoxReducer(s, a);
    case "addGif":
      return s.pickedGifs.some((g) => g.id === a.gif.id)
        ? { ...s, gifPickerOpen: false }
        : { ...s, pickedGifs: [...s.pickedGifs, a.gif], gifPickerOpen: false };
    case "removeGif":
      return { ...s, pickedGifs: s.pickedGifs.filter((g) => g.id !== a.id) };
  }
  return s;
}

export function effectivePrice(f: Pick<MassForm, "allModels" | "price">): number {
  return f.allModels ? 0 : f.price ? Number(f.price) : 0;
}

export function liveMedia(f: Pick<MassForm, "allModels" | "attached">): VaultMedia[] {
  return f.allModels ? [] : f.attached;
}

export interface MassCtx {
  broadcastCount: number;
  sensitive: boolean;
}

export const MASS_ALREADY_SENT = "The broadcast was sent. Close this and start a new one to send again.";

export const MASS_ONE_GIF_ALL_MODELS = "All-models broadcasts carry one GIF: remove the extra ones";

const tooManyGifs = (f: Pick<MassForm, "allModels" | "pickedGifs">) => f.allModels && f.pickedGifs.length > 1;

export function gifNote(f: Pick<MassForm, "allModels" | "pickedGifs">): string {
  const n = f.pickedGifs.length;
  if (tooManyGifs(f)) return MASS_ONE_GIF_ALL_MODELS;
  return n > 1 ? `${n} GIFs — first rides this broadcast; rest fan out as standalone sends` : "1 GIF attached";
}

export function validateMass(f: MassForm, ctx: MassCtx): string | null {
  if (f.gifFailures) return MASS_ALREADY_SENT;
  if (ctx.sensitive) return SENSITIVE_BLOCK_MESSAGE;
  if (ctx.broadcastCount === 0) return f.allModels ? noTargetsReason(f.results) : "Pick an account";
  if (!f.text.trim() && liveMedia(f).length === 0 && f.pickedGifs.length === 0) {
    return f.allModels ? "Add text or a GIF" : "Add text, media, or a GIF";
  }
  if (plainLength(f.text) > OF_TEXT_MAX) return TEXT_TOO_LONG;
  if (tooManyGifs(f)) return MASS_ONE_GIF_ALL_MODELS;
  if (f.includes.size === 0 && (f.allModels || f.smartInclude.size === 0)) {
    return f.allModels
      ? "Pick at least one audience list to include"
      : "Pick at least one audience list or Smart List to include";
  }
  const price = effectivePrice(f);
  if (!Number.isFinite(price) || price < 0) return "Invalid price";
  const note = priceNote(price);
  if (note) return note;
  if (f.schedule && !localDatetimeToIso(f.schedule)) return "Invalid schedule date";
  return null;
}

const plural = (n: number, one: string) => `${n} ${one}${n === 1 ? "" : "s"}`;

export function confirmPrompt(
  f: Pick<MassForm, "allModels" | "schedule" | "includes" | "smartInclude">,
  broadcastCount: number,
): string {
  const action = f.schedule ? "Schedule" : "Broadcast";
  const target = f.allModels
    ? plural(broadcastCount, "model")
    : f.smartInclude.size > 0
      ? `${plural(f.smartInclude.size, "Smart List")} only`
      : plural(f.includes.size, "audience group");
  return `${action} from ${target}?`;
}

export interface MassResolved {
  userIds?: number[];
  excludeUserIds?: number[];
}

export function buildMassBody(f: MassForm, online: boolean, r: MassResolved = {}): Record<string, unknown> {
  const price = effectivePrice(f);
  const media = liveMedia(f);
  const userIds = r.userIds ?? [];
  // OF unions userLists and userIds: an include segment must be the WHOLE audience, else it could only add recipients
  const segmentIsAudience = userIds.length > 0;
  const body: Record<string, unknown> = {
    text: f.text.trim(),
    scheduled_date: f.schedule ? localDatetimeToIso(f.schedule) : null,
    user_lists: segmentIsAudience ? [] : Array.from(f.includes),
    user_ids: userIds,
    excluded_users: r.excludeUserIds ?? [],
    excluded_user_lists: Array.from(f.excludes),
    price,
    locked_text: !f.allModels && f.lockedText && price > 0,
    media_files: media.map(wireMedia),
  };
  const previews = previewIdsFor(media, f.previewCount, price);
  if (previews.length > 0) body.previews = previews;
  if (!f.allModels && f.taggedCreators.length > 0) body.tagged_users = f.taggedCreators.map((c) => c.id);
  if (f.funnelId) body.funnel_id = f.funnelId;
  const gif = f.pickedGifs[0]?.id;
  if (gif) body.giphy_id = gif;
  // OF accepts ONE GIF per send: the first rides this one, gifOnlyForm sends the rest
  if (online) {
    const num = (s: string): number | null => {
      const n = Number(s);
      return s.trim() !== "" && Number.isFinite(n) && n > 0 ? n : null;
    };
    if (f.onlineOnly) body.online_only = true;
    const ul = num(f.unreadLimit);
    if (ul) body.unread_limit = Math.floor(ul);
    const rch = num(f.recentChatHours);
    if (rch) body.recent_chat_hours = rch;
    const rcl = num(f.recentChatLimit);
    if (rcl) body.recent_chat_limit = Math.floor(rcl);
    const erh = num(f.excludeRepliedHours);
    if (erh) body.exclude_replied_hours = erh;
    const eih = num(f.excludeInboundHours);
    if (eih) body.exclude_inbound_hours = eih;
    const uah = num(f.unsendAfterHours);
    if (uah) body.unsend_after_hours = uah;
    const mts = num(f.minTotalSpent);
    if (mts) body.min_total_spent = mts;
    const mt = num(f.minTipped);
    if (mt) body.min_tipped = mt;
    const sod = num(f.subscribedOverDays);
    if (sod) body.subscribed_over_days = sod;
    const eod = num(f.expiredOverDays);
    if (eod) body.expired_over_days = eod;
  }
  return body;
}

// A second price would charge the fan again
export function gifOnlyForm(f: MassForm, gif: PickedGif): MassForm {
  return {
    ...f, text: "", attached: [], price: "", lockedText: false, previewCount: 0, taggedCreators: [],
    funnelId: null, pickedGifs: [gif],
  };
}
