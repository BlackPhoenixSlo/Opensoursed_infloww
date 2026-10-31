/**
 * massMessageReducer — MassMessageComposer's form: one state, one reducer,
 * and the pure rules the component only calls.
 *
 *   • The custom-list audience is audience/audienceReducer's AudienceState,
 *     embedded (`accountId`, `includes`, `excludes`, `seededFor`): toggles,
 *     `setAccount` and the MASSDMEXCLUDE `seedExclude` delegate to it, so
 *     include / exclude stay mutually exclusive, the seed lands once per
 *     account (a manual untick sticks), and the first pick (null → A) keeps
 *     what was clicked.
 *   • The Smart Lists (saved segments) follow the same include / exclude rule.
 *     System audiences cycle include-only (OF ignores system names in
 *     `excludedLists`, so an exclude state would be a silent over-send).
 *   • The whole audience (lists, Smart Lists, the seed) resets to the system
 *     default (audienceReducer `resetAudience`, plus no Smart Lists) on a real
 *     account change (audienceReducer `isAccountSwitch`) and on the all-models
 *     switch, each in ONE reducer step (`audienceReset`). Turning all-models off leaves no account, so
 *     AccountPicker's auto-seed then dispatches a null → A `setAccount`, which
 *     keeps the (already default) audience. Forgetting the seed means the
 *     next settle of the account's lists seeds it again.
 *   • A real account change drops what belongs to the old account: vault
 *     media, preview count, tagged creators (`dropAccountScoped`). All-models
 *     on drops those plus the account, price and lock (all-models broadcasts
 *     are free text).
 *   • The fan-out lifecycle is compose/fanOut's slice: results merge by
 *     account, a retry broadcasts only from the included models without a
 *     success (`fanOutTargets`), and while a round is in flight or once a
 *     model sent it the content is locked (every action here but the
 *     lifecycle ones is refused; Start over, `discardResults`, unlocks the
 *     latter). The all-models switch clears the results. The round itself is
 *     compose/massFanOut `massFanOutRound`.
 *   • `pickTemplate` is lib/composeDraft `applyTemplate`.
 *   • `validateMass` is the ONE check the Broadcast button and the send
 *     mutation both read; `buildMassBody` the one body (media, schedule and
 *     the first GIF come from the form itself); `gifOnlyForm` the form of a
 *     trailing GIF's own send; `confirmPrompt` the question before a send.
 *   • The send itself (pending / error) is useMassSend's useMutation; only
 *     what it can't hold lives here: the fan-out slice, and `gifFailures` —
 *     the broadcast landed but some trailing GIF sends failed, so the form is
 *     spent: validateMass refuses it (Broadcast stays off) and the failures
 *     are listed until it is closed.
 */

import { SENSITIVE_BLOCK_MESSAGE } from "@/lib/sensitiveWords";
import { applyTemplate, previewIdsFor, wireMedia } from "@/lib/composeDraft";
import { localDatetimeToIso } from "@/lib/scheduleHistory";
import { priceNote } from "@/lib/sendGuards";
import type { PickedGif } from "@/components/chat/GifPicker";
import type { PickedTemplate } from "@/components/chat/TemplatePicker";
import type { TaggedCreatorChoice, VaultMedia } from "@/lib/relay";
import {
  audienceReducer, initAudience, isAccountSwitch, resetAudience, toggled, without,
  type AudienceAction, type AudienceState,
} from "@/components/audience/audienceReducer";

import { fanOutLocked, fanOutReducer, initFanOut, noTargetsReason, type FanOutAction, type FanOutState } from "./fanOut";

/** `seededFor` is the account the MASSDMEXCLUDE list was auto-excluded for;
 *  null = not yet (since the last audience reset). */
export interface MassForm extends AudienceState, FanOutState {
  allModels: boolean;
  text: string;
  attached: VaultMedia[];
  price: string;
  /** Leading N tiles are FREE previews; the rest PPV-locked. */
  previewCount: number;
  lockedText: boolean;
  /** Smart Lists (saved segments, by id) picked as include / exclude. */
  smartInclude: Set<number>;
  smartExclude: Set<number>;
  schedule: string;
  funnelId: number | null;
  taggedCreators: TaggedCreatorChoice[];
  pickedGifs: PickedGif[];
  gifPickerOpen: boolean;
  /** Set once the broadcast landed but trailing GIF sends failed (null
   *  before): the form is spent — a resend would repeat the paid broadcast. */
  gifFailures: GifFailure[] | null;
  // Online / live-targeting (mode "online"). Strings so a blank = "not applied".
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
}

/** A trailing GIF send that failed after the broadcast landed. */
export interface GifFailure {
  id: string;
  title?: string;
  error: string;
}

/** Fields a plain input sets. The audience, account, all-models switch and
 *  send lifecycle go through their own actions (they carry rules). */
export type MassField =
  | "text" | "attached" | "price" | "previewCount" | "lockedText" | "schedule" | "funnelId"
  | "taggedCreators" | "gifPickerOpen"
  | "onlineOnly" | "unreadLimit" | "recentChatHours" | "recentChatLimit" | "excludeRepliedHours"
  | "excludeInboundHours" | "unsendAfterHours" | "minTotalSpent" | "minTipped"
  | "subscribedOverDays" | "expiredOverDays";

export type MassAction =
  | { [K in MassField]: { type: "field"; k: K; v: MassForm[K] } }[MassField]
  /** Append to the text as it is now (an emoji with no textarea to insert at). */
  | { type: "appendText"; v: string }
  /** toggleInclude / toggleExclude / setAccount / seedExclude (the
   *  MASSDMEXCLUDE list, audience/audienceReducer `massExcludeListId`). */
  | AudienceAction
  | { type: "cycleSystem"; id: string }
  | { type: "toggleSmartInclude"; id: number }
  | { type: "toggleSmartExclude"; id: number }
  | { type: "setAllModels"; on: boolean }
  | { type: "pickTemplate"; t: PickedTemplate }
  | { type: "addGif"; gif: PickedGif }
  | { type: "removeGif"; id: string }
  /** The broadcast landed; these trailing GIF sends failed (the form is spent). */
  | { type: "gifSendsFailed"; failed: GifFailure[] }
  | FanOutAction;

/** The `field` action for `k` (the cast is the one TS can't prove: a
 *  generic `k` against the per-field union). */
export function fieldAction<K extends MassField>(
  k: K, v: MassForm[K],
): Extract<MassAction, { type: "field"; k: K }> {
  return { type: "field", k, v } as Extract<MassAction, { type: "field"; k: K }>;
}

/** A blank form, on `accountId` when the opener pins one. */
export function initMassForm(accountId: string | null = null): MassForm {
  return {
    ...initAudience(accountId),
    ...initFanOut(),
    allModels: false,
    text: "",
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
  };
}

/** The system-default audience (see the file header). */
function audienceReset(s: MassForm): MassForm {
  return { ...resetAudience(s), smartInclude: new Set(), smartExclude: new Set() };
}

/** What only means something on the account it was picked for. */
function dropAccountScoped(s: MassForm): MassForm {
  return { ...s, attached: [], previewCount: 0, taggedCreators: [] };
}

export function massMessageReducer(s: MassForm, a: MassAction): MassForm {
  switch (a.type) {
    case "progress":
    case "results":
    case "discardResults":
      return fanOutReducer(s, a);
    case "gifSendsFailed":
      return { ...s, gifFailures: a.failed, progress: null };
  }
  // A round in flight, or a model sent the broadcast: the content is locked.
  if (fanOutLocked(s)) return s;
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
      // The audience half (incl. the first pick, null → A, being no switch)
      // is audienceReducer's; a real switch resets the rest with it.
      const next = audienceReducer(s, a);
      return isAccountSwitch(s.accountId, a.id) ? audienceReset(dropAccountScoped(next)) : next;
    }
    case "setAllModels":
      if (a.on === s.allModels) return s;
      return audienceReset(a.on
        ? { ...dropAccountScoped(s), ...initFanOut(), allModels: true, accountId: null, price: "", lockedText: false }
        : { ...s, ...initFanOut(), allModels: false });
    case "pickTemplate":
      return applyTemplate(s, a.t);
    case "addGif":
      return s.pickedGifs.some((g) => g.id === a.gif.id)
        ? { ...s, gifPickerOpen: false }
        : { ...s, pickedGifs: [...s.pickedGifs, a.gif], gifPickerOpen: false };
    case "removeGif":
      return { ...s, pickedGifs: s.pickedGifs.filter((g) => g.id !== a.id) };
  }
}

/** All-models broadcasts force free (ask #4); otherwise a typed price > 0 is
 *  the sole paid signal. */
export function effectivePrice(f: Pick<MassForm, "allModels" | "price">): number {
  return f.allModels ? 0 : f.price ? Number(f.price) : 0;
}

/** The tiles the live send carries (none on an all-models broadcast, which
 *  is text-only); on the wire, vault ids plus fresh-upload claims. */
export function liveMedia(f: Pick<MassForm, "allModels" | "attached">): VaultMedia[] {
  return f.allModels ? [] : f.attached;
}

export interface MassCtx {
  /** Models the all-models fan-out would send from (compose/fanOut `fanOutTargets`). */
  broadcastCount: number;
  /** The text holds a listed sensitive word. */
  sensitive: boolean;
}

/** Why a spent form (see `gifFailures`) can't be sent again. */
export const MASS_ALREADY_SENT = "The broadcast was sent. Close this and start a new one to send again.";

/** Why this form can't be sent, or null. */
export function validateMass(f: MassForm, ctx: MassCtx): string | null {
  if (f.gifFailures) return MASS_ALREADY_SENT;
  if (ctx.sensitive) return SENSITIVE_BLOCK_MESSAGE;
  if (f.allModels) {
    if (ctx.broadcastCount === 0) return noTargetsReason(f.results);
  } else if (!f.accountId) {
    return "Pick an account";
  }
  if (!f.text.trim() && liveMedia(f).length === 0 && f.pickedGifs.length === 0) {
    // All-models is text-only: media is no way out there.
    return f.allModels ? "Add text or a GIF" : "Add text, media, or a GIF";
  }
  // An include Smart List IS an audience (it replaces the list chips) — where
  // Smart Lists are offered at all (one account).
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

/** The confirm() question before a send. An include Smart List replaces the
 *  list chips as the audience (buildMassBody), so it says that plainly rather
 *  than counting groups that won't be sent to. */
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

/** The Smart Lists resolved to fan ids at send time (none on all-models). */
export interface MassResolved {
  userIds?: number[];
  excludeUserIds?: number[];
}

/** The /messages/queue body for this form. `online`: mode "online" attaches
 *  the live-targeting fields. */
export function buildMassBody(f: MassForm, online: boolean, r: MassResolved = {}): Record<string, unknown> {
  const price = effectivePrice(f);
  const media = liveMedia(f);
  const userIds = r.userIds ?? [];
  // On the OF wire userLists and userIds are UNIONED, never intersected. So
  // if we sent both, a Smart List could only ever ADD people to the blast.
  // An include segment therefore becomes the WHOLE audience and the list
  // chips drop out; that is the only way a segment can narrow a send.
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
  // Tag lists are per account: never on an all-models broadcast (a template
  // picked there still merges its tags into the form).
  if (!f.allModels && f.taggedCreators.length > 0) body.tagged_users = f.taggedCreators.map((c) => c.id);
  if (f.funnelId) body.funnel_id = f.funnelId;
  // OF accepts ONE GIF per send: the first rides this one (gifOnlyForm sends the rest).
  const gif = f.pickedGifs[0]?.id;
  if (gif) body.giphy_id = gif;
  // Only what the operator set, so the relay leaves unused filters alone.
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

/** The form of a trailing GIF's own send: the same audience, schedule and
 *  targeting, but only that GIF — no text, media, price, lock, tags or funnel
 *  (the first send carried those; a second price would charge the fan again). */
export function gifOnlyForm(f: MassForm, gif: PickedGif): MassForm {
  return {
    ...f, text: "", attached: [], price: "", lockedText: false, previewCount: 0, taggedCreators: [],
    funnelId: null, pickedGifs: [gif],
  };
}
