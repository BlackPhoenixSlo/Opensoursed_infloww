/**
 * Full AI Chat's Test chat state (docs/spec/phase-03a-full-ai-writers-test-chat.md › App changes): two windows, L on
 * the saved checkpoint and R on the draft, each its own session of one `pair`. One composer (`text`, `edit`) sends his
 * Fan line to both (`send`); each side's answer (`turnResult`) is shown after its `wait_s` (`revealAt`, `reveal`) or at once with
 * skip-wait. A failed request keeps its Turn number for `retry`; a 409 reloads that side (`sessionLoaded`). Anything
 * for a `pair` that is no longer current (a late answer after `newChat`) is ignored. Pure: the hook
 * (`useFullAiTestChat`) does the requests and timers, the components only dispatch.
 *
 * L/R exist only in the page's code, never in requests or UI text; every request says `side: "checkpoint" | "draft"` (spec › `full_ai_test`).
 * Config (ticket 39): `loaded` takes GET /admin/full-ai/config; a settings control or the JSON editor dispatches
 * `editDraft` then `saveDraft` (the PUT); `draftSaved` / `configFailed` / `stale` end it
 * (`configFailed` is any failed config request: the read, a PUT, a Save or Roll back). `commit` marks a Save or
 * Roll back in flight, `saved` / `rolledBack` land it. Send waits while an edit is unstored or storing: the draft side's
 * Turn reads the stored draft only.
 * An applied draft from elsewhere (ticket 57: the assistant's Apply invalidates the config query, the hook dispatches the
 * refetch) is `externalDraft` with the whole body (rev is one counter for the whole config): a newer `rev` is adopted, or
 * with an unsaved edit raises `conflict` until `keepMine` (take its checkpoint and rev; the hook then re-stores the page's
 * draft on it through `saveDraft`, `keepMineSave`) or `takeTheirs` (adopt it whole). Never overwritten silently.
 * Selling (ticket 49): a reply may carry an `offer`; Buy / Decline on a priced one dispatches `settle` (that Turn's
 * `settle` pending), the hook POSTs `buildSettlePayload` and lands `settled` (done, the outcome) or `settleFailed`
 * (failed: buttons back with the message).
 * A settle lives on its Turn, not in `pending`, so it never blocks Send.
 * His photo: `attach` puts one (already shrunk) image on the composer, `detach` drops it; Send with one first owes the
 * photo request (`describing`: described ONCE for both sides), then `photoDescribed` owes both sides' Turns carrying it
 * (`photo` in `buildTurnPayload`), or `photoFailed` puts his line and image back in the composer with the message.
 */

import type { Route } from "@/hooks/useFullAiToday";
import { CASUAL_STYLE } from "@/lib/fullAiStyle";

export type UiSide = "L" | "R";
export type TestSide = "checkpoint" | "draft";
export const UI_SIDES: readonly UiSide[] = ["L", "R"];
export const SIDE_OF: Record<UiSide, TestSide> = { L: "checkpoint", R: "draft" };

/** The PPV the last text bubble carries (`full_ai_test.send`): the Offer's ref, price and media ids. */
export interface Ppv { ref: number; price_cents: number; media: number[]; previews: number[] }
/** One of her bubbles: text (the last one may carry the PPV), or a GIF (`{gif: <giphy id>, tag}`). */
export type Part = { text: string; ppv?: Ppv } | { gif: string; tag: string };
/** A reply's Offer (`full_ai_test.offer_of`): `price_cents` > 0 priced, 0 a free item, null a tease. */
export interface Offer {
  kind: string;
  ref: number;
  price_cents: number | null;
  list_cents: number | null;
  media: number[];
  previews: number[];
  refusal: string | null;
}
export type Outcome = "bought" | "declined";
/** One Writer call; `rewrite` marks the Claim audit's rewrite pass (`full_ai_turn._claim_audit`), appended after the
 *  first pass. */
export interface Attempt { writer: string; outcome: string; ms: number; rewrite?: boolean }
/** The separate caption call's path (`caption_writer` "caption" on a PPV Turn, full_ai_turn._caption). */
export interface CaptionPath { writer: "caption" | "chat"; model: string | null; outcome: string; ms: number; attempts: Attempt[] }

/** POST /admin/full-ai/test/turn's answer. */
export interface TurnResponse {
  row_id: number | null;
  route: Route;
  heat: number;
  route_row: string;
  dropped: string[];
  parts: Part[];
  /** The Writer that answered; null on `failed` / `no_send`. */
  writer: string | null;
  attempts: Attempt[];
  wait_s: number;
  status: "sent" | "failed" | "no_send";
  /** The facts the test Fan gave so far (the session's fold). */
  fan_info: Record<string, unknown>;
  /** The Offer this reply made; absent / null on none. */
  offer?: Offer | null;
  /** Who wrote the PPV's caption; absent unless `caption_writer` is "caption" on a PPV Turn. */
  caption?: CaptionPath | null;
  /** His photo as this side read it; absent without one. */
  photo?: FanPhoto | null;
}

/** POST /admin/full-ai/test/photo's answer, sent back with each side's Turn; `read` (on a recorded Turn only): that
 *  side's `describe_fan_photos` was on and a description exists, so its Router and Writer read it. */
export interface FanPhoto {
  desc: string | null;
  thumb: string;
  outcome: string;
  model: string | null;
  ms: number | null;
  read?: boolean;
}
/** What his photo bubble prints under the thumbnail: the description his side read, else the line it read instead. */
export const MEDIA_ONLY = "[sent a photo or video]";
export const photoCaption = (p: FanPhoto) => (p.read && p.desc ? p.desc : MEDIA_ONLY);

export interface Turn {
  n: number;
  text: string;
  photo?: FanPhoto | null;
  result: TurnResponse;
  /** Its Offer's Buy / Decline: in flight, settled, or failed (buttons back, with the message). Absent: never pressed. */
  settle?: Settle;
}
export type Settle = { kind: "pending" | "done"; outcome: Outcome } | { kind: "failed"; error: string };
/** The request a side owes: in flight, or failed and waiting for a retry with the same `n`. */
export interface PendingTurn { n: number; text: string; photo?: FanPhoto; inFlight: boolean; error: string | null }
/** The photo request Send owes before either side's Turn: his line and the image (a data URL). */
export interface Describing { text: string; image: string }
export interface SideState {
  turns: Turn[];
  pending: PendingTurn | null;
  /** Epoch ms the newest reply shows at; null = shown. */
  revealAt: number | null;
}

/** The five human-texting layers (`full_ai_config.STYLE_LAYERS`), in the server's order. */
export const STYLE_LAYERS = ["texting", "nonnative", "spacing", "typos", "painful"] as const;
export type StyleLayer = (typeof STYLE_LAYERS)[number];
export type StyleLayers = Record<StyleLayer, boolean>;

/** One side of Full AI Chat's config (`full_ai_config.DEFAULTS` keys): draft, checkpoint or previous. The page edits the
 *  named keys, the JSON the rest; they are optional, as a hand-typed JSON draft may lack them until the server
 *  refuses it. */
export interface FullAiConfig {
  reply_speed?: string;
  /** The stored human-texting layers; `text_style` is only the legacy write alias (never stored). */
  style?: Partial<StyleLayers>;
  text_style?: string;
  /** Ordered: the first is the Writer, the rest its fallbacks. */
  writers?: string[];
  gifs?: boolean;
  sell_on?: boolean;
  /** PPV caption: "chat" (default) = the chat Writer's last bubble, "caption" = its own call. */
  caption_writer?: string;
  /** Content folders: `include: []` = all (ticket 49, `sellFoldersForm.ts`). */
  folders?: { include: string[]; exclude: string[] };
  [key: string]: unknown;
}
/** GET /admin/full-ai/config's body; every config write answers the same shape. */
export interface ConfigBody {
  checkpoint: FullAiConfig;
  previous: FullAiConfig | null;
  draft: FullAiConfig;
  rev: number;
  errors: string[];
  /** The models a `writers` entry may name (the Writer select's options). */
  writer_models?: string[];
}

export interface TestChatState {
  pair: string;
  skipWait: boolean;
  /** The composer's Fan line. */
  text: string;
  /** The composer's attached image (a shrunk data URL), or null. */
  photo: string | null;
  /** The photo request in flight, or null. */
  describing: Describing | null;
  /** Why the last photo request failed (cleared by the next edit / attach / Send). */
  photoError: string | null;
  sides: Record<UiSide, SideState>;
  /** null until `loaded`. */
  checkpoint: FullAiConfig | null;
  previous: FullAiConfig | null;
  /** The draft as shown: the stored one, or an edit not yet stored (`dirty`). */
  draft: FullAiConfig | null;
  rev: number;
  dirty: boolean;
  savingDraft: boolean;
  /** A Save or Roll back in flight. */
  committing: boolean;
  /** Someone stored meanwhile: reload before anything else is written. */
  stale: boolean;
  /** Field errors ("<key>: <why>") or a failed write's message. */
  errors: string[];
  /** A newer draft stored elsewhere while the page had an unsaved edit: Keep mine / Take theirs pending. */
  conflict: ConfigBody | null;
}

export type TestChatAction =
  | { type: "edit"; text: string }
  | { type: "attach"; image: string }
  | { type: "detach" }
  | { type: "send" }
  | { type: "photoDescribed"; pair: string; photo: FanPhoto }
  | { type: "photoFailed"; pair: string; error: string }
  | { type: "turnResult"; pair: string; side: UiSide; n: number; result: TurnResponse; now: number }
  | { type: "turnFailed"; pair: string; side: UiSide; n: number; error: string }
  | { type: "retry"; side: UiSide }
  | { type: "sessionLoaded"; pair: string; side: UiSide; turns: Turn[] }
  | { type: "reveal"; side: UiSide; now: number }
  | { type: "toggleSkip" }
  | { type: "newChat"; pair: string }
  | { type: "loaded"; body: ConfigBody }
  | { type: "editDraft"; draft: FullAiConfig }
  | { type: "saveDraft" }
  | { type: "draftSaved"; rev: number; draft: FullAiConfig }
  | { type: "configFailed"; errors: string[] }
  | { type: "commit" }
  | { type: "saved"; rev: number }
  | { type: "rolledBack"; rev: number }
  | { type: "stale" }
  | { type: "externalDraft"; body: ConfigBody }
  | { type: "keepMine" }
  | { type: "takeTheirs" }
  | { type: "settle"; side: UiSide; rowId: number; outcome: Outcome }
  | { type: "settled"; pair: string; side: UiSide; rowId: number; outcome: Outcome }
  | { type: "settleFailed"; pair: string; side: UiSide; rowId: number; error: string };

const EMPTY_SIDE: SideState = { turns: [], pending: null, revealAt: null };

export function initTestChat(pair: string, skipWait = false): TestChatState {
  return {
    pair, skipWait, text: "", photo: null, describing: null, photoError: null, sides: { L: EMPTY_SIDE, R: EMPTY_SIDE },
    checkpoint: null, previous: null, draft: null, rev: 0,
    dirty: false, savingDraft: false, committing: false, stale: false, errors: [], conflict: null,
  };
}

/** Why Send waits on the config, or null: an edit not stored yet would not reach the draft side's Turn. Every edit
 *  stores at once, so an unstored edit is one in flight or one the server refused. */
export function sendBlock(state: TestChatState): string | null {
  if (state.conflict) return "Keep mine or Take theirs first";
  if (state.savingDraft) return "Storing draft…";
  return state.dirty ? "Draft not stored — fix it or Reload" : null;
}

/** Send is allowed with a Fan line typed or an image attached, no photo request out, neither side owing a request or
 *  hiding a reply (a Turn is never cut in two), the draft stored and no Save / Roll back out. */
export function canSend(state: TestChatState): boolean {
  return (state.text.trim() !== "" || state.photo !== null) && state.describing === null
    && sendBlock(state) === null && !state.committing
    && UI_SIDES.every((s) => state.sides[s].pending === null && state.sides[s].revealAt === null);
}

/** Same config whatever the key order (the server's JSON may order a side's keys differently). */
function stable(v: unknown): unknown {
  if (Array.isArray(v)) return v.map(stable);
  if (v && typeof v === "object") {
    return Object.fromEntries(Object.keys(v).sort().map((k) => [k, stable((v as Record<string, unknown>)[k])]));
  }
  return v;
}
export const sameConfig = (a: unknown, b: unknown) => JSON.stringify(stable(a)) === JSON.stringify(stable(b));

/** A control (or the JSON editor) may edit the draft: loaded, nothing out, not stale, no Keep mine / Take theirs pending. */
export function canEdit(state: TestChatState): boolean {
  return state.draft !== null && !state.savingDraft && !state.committing && !state.stale && state.conflict === null;
}

/** Keep mine's draft PUT: the page's draft on the conflict's rev; null without a conflict. */
export function keepMineSave(state: TestChatState): { draft: FullAiConfig; rev: number } | null {
  return state.conflict && state.draft ? { draft: state.draft, rev: state.conflict.rev } : null;
}

/** Save (the stored draft becomes the checkpoint): something to save, nothing unstored, out, stale or refused. */
export function canSave(state: TestChatState): boolean {
  return canEdit(state) && !state.dirty && state.errors.length === 0 && !sameConfig(state.draft, state.checkpoint);
}

/** Roll back (swap the checkpoint and the previous one): a previous to go to, nothing out, not stale. */
export function canRollback(state: TestChatState): boolean {
  return canEdit(state) && state.previous !== null;
}

/** POST /admin/full-ai/test/turn's body without `account_id`. */
export interface TurnPayload { pair: string; side: TestSide; n: number; text: string; photo?: FanPhoto }

/** The side's owed request; `n` = its Turn count + 1, the same on a retry. */
export function buildTurnPayload(state: TestChatState, ui: UiSide): TurnPayload | null {
  const p = state.sides[ui].pending;
  if (!p) return null;
  const base = { pair: state.pair, side: SIDE_OF[ui], n: p.n, text: p.text };
  return p.photo ? { ...base, photo: p.photo } : base;
}

const owe = (s: SideState, text: string, photo?: FanPhoto): SideState =>
  ({ ...s, pending: { n: s.turns.length + 1, text, ...(photo ? { photo } : {}), inFlight: true, error: null } });

const withSide = (state: TestChatState, ui: UiSide, side: SideState): TestChatState =>
  ({ ...state, sides: { ...state.sides, [ui]: side } });

/** Buy / Decline may be pressed: a priced Offer, no outcome yet, no settle in flight. */
export function canSettle(turn: Turn): boolean {
  return (turn.result.offer?.price_cents ?? 0) > 0 && (!turn.settle || turn.settle.kind === "failed");
}

/** POST /admin/full-ai/test/settle's body. */
export interface SettlePayload { account_id: string; pair: string; side: TestSide; row_id: number; outcome: Outcome }

export function buildSettlePayload(
  state: TestChatState, ui: UiSide, rowId: number, outcome: Outcome, accountId: string,
): SettlePayload {
  return { account_id: accountId, pair: state.pair, side: SIDE_OF[ui], row_id: rowId, outcome };
}

/** The side with the Turn of `rowId` changed by `fn`; the same state when no Turn matches or `fn` keeps it. */
function withTurn(state: TestChatState, ui: UiSide, rowId: number, fn: (t: Turn) => Turn): TestChatState {
  const s = state.sides[ui];
  const i = s.turns.findIndex((t) => t.result.row_id === rowId);
  if (i < 0) return state;
  const next = fn(s.turns[i]);
  if (next === s.turns[i]) return state;
  return withSide(state, ui, { ...s, turns: s.turns.map((t, j) => (j === i ? next : t)) });
}

export function testChatReducer(state: TestChatState, action: TestChatAction): TestChatState {
  switch (action.type) {
    case "edit":
      return { ...state, text: action.text, photoError: null };
    case "attach":
      return state.describing ? state : { ...state, photo: action.image, photoError: null };
    case "detach":
      return state.describing ? state : { ...state, photo: null };
    case "send": {
      if (!canSend(state)) return state;
      const text = state.text.trim();
      if (state.photo !== null) {
        return { ...state, text: "", photo: null, photoError: null, describing: { text, image: state.photo } };
      }
      return { ...state, text: "", photoError: null, sides: { L: owe(state.sides.L, text), R: owe(state.sides.R, text) } };
    }
    case "photoDescribed": {
      const d = state.describing;
      if (action.pair !== state.pair || !d) return state;
      return { ...state, describing: null,
        sides: { L: owe(state.sides.L, d.text, action.photo), R: owe(state.sides.R, d.text, action.photo) } };
    }
    case "photoFailed": {
      const d = state.describing;
      if (action.pair !== state.pair || !d) return state;
      // His line and image back in the composer (a line typed meanwhile is kept after it).
      const text = [d.text, state.text].filter((t) => t.trim() !== "").join(" ");
      return { ...state, describing: null, text, photo: d.image, photoError: action.error };
    }
    case "turnResult": {
      const s = state.sides[action.side];
      if (action.pair !== state.pair || s.pending?.n !== action.n) return state;
      const photo = action.result.photo ?? s.pending.photo;
      return withSide(state, action.side, {
        turns: [...s.turns, { n: action.n, text: s.pending.text, ...(photo ? { photo } : {}), result: action.result }],
        pending: null,
        revealAt: state.skipWait ? null : action.now + action.result.wait_s * 1000,
      });
    }
    case "turnFailed": {
      const s = state.sides[action.side];
      if (action.pair !== state.pair || s.pending?.n !== action.n) return state;
      return withSide(state, action.side, { ...s, pending: { ...s.pending, inFlight: false, error: action.error } });
    }
    case "retry": {
      const s = state.sides[action.side];
      if (!s.pending || s.pending.inFlight) return state;
      return withSide(state, action.side, { ...s, pending: { ...s.pending, inFlight: true, error: null } });
    }
    case "sessionLoaded":
      if (action.pair !== state.pair) return state;
      // The session rows carry no outcome: a Buy / Decline already settled here stays settled.
      const done = new Map(state.sides[action.side].turns.filter((t) => t.settle?.kind === "done")
        .map((t) => [t.result.row_id, t.settle]));
      const turns = action.turns.map((t) => (done.has(t.result.row_id) ? { ...t, settle: done.get(t.result.row_id) } : t));
      return withSide(state, action.side, { turns, pending: null, revealAt: null });
    case "reveal": {
      const s = state.sides[action.side];
      if (s.revealAt === null || action.now < s.revealAt) return state;
      return withSide(state, action.side, { ...s, revealAt: null });
    }
    case "toggleSkip": {
      const skipWait = !state.skipWait;
      if (!skipWait) return { ...state, skipWait };
      const shown = (s: SideState): SideState => (s.revealAt === null ? s : { ...s, revealAt: null });
      return { ...state, skipWait, sides: { L: shown(state.sides.L), R: shown(state.sides.R) } };
    }
    case "newChat":
      return { ...state, pair: action.pair, text: "", photo: null, describing: null, photoError: null,
        sides: { L: EMPTY_SIDE, R: EMPTY_SIDE } };
    case "loaded":
      return adopt(state, action.body);
    case "editDraft":
      return { ...state, draft: action.draft, dirty: true, errors: [] };
    case "saveDraft":
      return { ...state, savingDraft: true };
    case "draftSaved":
      return { ...state, draft: action.draft, rev: action.rev, dirty: false, savingDraft: false, errors: [] };
    case "configFailed":
      return { ...state, errors: action.errors, savingDraft: false, committing: false };
    case "commit":
      return { ...state, committing: true };
    case "saved":
      return { ...state, previous: state.checkpoint, checkpoint: state.draft, rev: action.rev, committing: false, errors: [] };
    case "rolledBack":
      return { ...state, checkpoint: state.previous, previous: state.checkpoint, rev: action.rev, committing: false, errors: [] };
    case "stale":
      return { ...state, stale: true, savingDraft: false, committing: false };
    case "externalDraft": {
      // A write of ours out (its answer carries the newest rev) or a Reload owed: that path settles it.
      if (state.savingDraft || state.committing || state.stale) return state;
      if (action.body.rev <= Math.max(state.rev, state.conflict?.rev ?? 0)) return state;
      return state.dirty ? { ...state, conflict: action.body } : adopt(state, action.body);
    }
    case "keepMine": {
      if (!state.conflict) return state;
      const { checkpoint, previous, rev } = state.conflict;
      return { ...state, checkpoint, previous, rev, conflict: null };
    }
    case "takeTheirs":
      return state.conflict ? adopt(state, state.conflict) : state;
    case "settle":
      return withTurn(state, action.side, action.rowId,
        (t) => (canSettle(t) ? { ...t, settle: { kind: "pending", outcome: action.outcome } } : t));
    case "settled":
      if (action.pair !== state.pair) return state;
      return withTurn(state, action.side, action.rowId,
        (t) => ({ ...t, settle: { kind: "done", outcome: action.outcome } }));
    case "settleFailed":
      if (action.pair !== state.pair) return state;
      return withTurn(state, action.side, action.rowId,
        (t) => (t.settle?.kind === "pending" ? { ...t, settle: { kind: "failed", error: action.error } } : t));
  }
}

/** A stored config body taken whole (`loaded`, an adopted `externalDraft`, Take theirs): nothing unstored is left. */
function adopt(state: TestChatState, { checkpoint, previous, draft, rev, errors }: ConfigBody): TestChatState {
  return { ...state, checkpoint, previous, draft, rev, errors,
    dirty: false, savingDraft: false, committing: false, stale: false, conflict: null };
}

/** One row of GET /admin/full-ai/test/session (`full_ai_test.session_row`): the turn answer minus `dropped`, plus
 *  its side, Turn number, his line and when it was recorded. `wait_s` is null on a Turn that sent nothing. */
export type SessionRow = Omit<TurnResponse, "dropped" | "wait_s" | "photo"> & {
  side: TestSide; n: number; text: string; wait_s: number | null; created_at: string; photo?: FanPhoto | null;
};
/** The session read's body: both sides' rows, oldest first. */
export interface SessionBody { rows: SessionRow[] }

/** One side's Turns from the session read. A reloaded Turn is already recorded, so it carries no rows dropped. */
export function sessionTurns(body: SessionBody, side: TestSide): Turn[] {
  return body.rows.filter((r) => r.side === side).map(({ side: _s, created_at: _c, n, text, wait_s, photo, ...rest }) => ({
    n, text, ...(photo ? { photo } : {}), result: { ...rest, dropped: [], wait_s: wait_s ?? 0 },
  }));
}

// ── What a window prints (pure, so the component only renders) ─────────────────────────────────────────────────────

/** How a PPV bubble stands, from its Turn's Offer: the settled outcome, the price (Buy / Decline go under it while
 *  `canSettle`), "Free", or nothing (no Offer, or a tease with no price). */
export type PpvLine = { kind: "settled"; dollars: number; paid: boolean } | { kind: "price"; dollars: number } | { kind: "free" };
export function ppvLine(t: Turn): PpvLine | null {
  const cents = t.result.offer?.price_cents;
  if (cents == null) return null;
  if (cents === 0) return { kind: "free" };
  return t.settle?.kind === "done" ? { kind: "settled", dollars: cents / 100, paid: t.settle.outcome === "bought" }
    : { kind: "price", dollars: cents / 100 };
}

/** The line under a reply: Route, Heat, matched row and, when she answered, the Writer and how many fell before it
 *  with each one's outcome ("1 fell before (euryale-v2.3 no_key)"). */
export function replyLine(r: TurnResponse): string {
  const head = `Route ${r.route} · Heat ${r.heat} · Row ${r.route_row}`;
  if (r.status !== "sent" || !r.writer) return head;
  // The chain stops at the first Writer that answers, so every failed first-pass attempt fell before it; the Claim
  // audit's rewrite attempts are not Writers falling.
  const fell = r.attempts.filter((a) => !a.rewrite && a.outcome !== "ok");
  const why = fell.length ? ` (${outcomesLine(fell)})` : "";
  const cap = !r.caption ? "" : r.caption.writer === "caption" ? ` · Caption ${r.caption.model}` : ` · Caption chat (${r.caption.outcome})`;
  return `${head} · Writer ${r.writer} · ${fell.length} fell before${why}${cap}`;
}

/** The text in place of her bubbles on a Turn with none; null when she answered. */
export function noReplyText(r: TurnResponse): string | null {
  if (r.status === "no_send") {
    return r.route_row === "says_under_18" ? "no reply (under 18)"
      : r.route_row === "promo" ? "no reply (promo)" : `no reply (${r.route_row})`;
  }
  if (r.status === "failed") {
    return r.attempts.every((a) => a.outcome !== "ok") ? "no reply: all writers failed" : "no reply: the reply chain dropped it";
  }
  return null;
}

/** The reply speeds (`full_ai_config.REPLY_SPEEDS`) with their labels, and the one a config without the key runs on. */
export const REPLY_SPEEDS = [{ value: "0-2m", label: "0-2 min" }, { value: "0-15-60", label: "0-15-60" }];
export const DEFAULT_SPEED = "0-2m";
const allLayers = (on: boolean) => Object.fromEntries(STYLE_LAYERS.map((k) => [k, on])) as StyleLayers;

/** The side's layers as the server reads them (`full_ai_config.style_layers`): a valid legacy `text_style` wins
 *  (formal = all off, girl = all on), then `style`; a config with neither is the server default, all on. */
export function styleLayers(cfg: FullAiConfig | null): StyleLayers {
  const ts = cfg?.text_style;
  if (ts === CASUAL_STYLE || ts === "formal") return allLayers(ts === CASUAL_STYLE);
  if (!cfg?.style) return allLayers(true);
  const s = cfg.style;
  return Object.fromEntries(STYLE_LAYERS.map((k) => [k, s[k] === true])) as StyleLayers;
}

/** The Human style master switch: on / off when every layer agrees, mixed otherwise. */
export type HumanStyle = "on" | "off" | "mixed";
export function humanStyle(cfg: FullAiConfig | null): HumanStyle {
  const v = Object.values(styleLayers(cfg));
  return v.every(Boolean) ? "on" : v.some(Boolean) ? "mixed" : "off";
}
/** The layers that are off, in plain words ("typos, spacing"), for the mixed state's hint. */
const LAYER_WORD: Record<StyleLayer, string> = {
  texting: "texting style", nonnative: "non-native", spacing: "spacing", typos: "typos", painful: "painful texting",
};
export const layersOff = (cfg: FullAiConfig | null) =>
  STYLE_LAYERS.filter((k) => !styleLayers(cfg)[k]).map((k) => LAYER_WORD[k]).join(", ");

/** The master switch's edit: every layer on or off. */
export const humanStylePatch = (on: boolean): Partial<FullAiConfig> => ({ style: allLayers(on), text_style: undefined });
/** The Typos switch's edit: the typos layer alone. Both drop a legacy `text_style` (it would win over `style`). */
export const typosPatch = (cfg: FullAiConfig | null, on: boolean): Partial<FullAiConfig> =>
  ({ style: { ...styleLayers(cfg), typos: on }, text_style: undefined });

/** `full_ai_config.MAX_WRITERS`. */
export const MAX_WRITERS = 4;
/** The Writer select's edit: `model` first, the others keep their order as fallbacks (a full list drops its last). */
export function writerPatch(cfg: FullAiConfig | null, model: string): Partial<FullAiConfig> {
  const rest = (cfg?.writers ?? []).filter((w) => w !== model);
  return { writers: [model, ...rest].slice(0, MAX_WRITERS) };
}

/** The Writer checklist's tick: an unticked model joins the chain's end, a ticked one leaves it. Null when refused:
 *  the last Writer (the server needs 1) or a full chain (`MAX_WRITERS`). */
export function toggleWriterPatch(cfg: FullAiConfig | null, model: string): Partial<FullAiConfig> | null {
  const ws = cfg?.writers ?? [];
  if (ws.includes(model)) return ws.length > 1 ? { writers: ws.filter((w) => w !== model) } : null;
  return ws.length < MAX_WRITERS ? { writers: [...ws, model] } : null;
}

/** A side's Writer chain for its window header, in the order tried. */
export const writersLine = (cfg: FullAiConfig) => `Writers ${(cfg.writers ?? []).join(" → ") || "none"}`;

const onOff = (on: boolean) => (on ? "on" : "off");

/** A side's config for its window header: reply speed, Human style (+ "Typos off" unless all off), GIFs. */
export function configLine(cfg: FullAiConfig): string {
  const speed = cfg.reply_speed ?? DEFAULT_SPEED;
  const label = REPLY_SPEEDS.find((o) => o.value === speed)?.label ?? speed;
  const hs = humanStyle(cfg);
  const typos = hs !== "off" && !styleLayers(cfg).typos ? " · Typos off" : "";
  return `Reply ${label} · Human style ${hs}${typos} · GIFs ${onOff(cfg.gifs === true)} · Caption ${cfg.caption_writer ?? "chat"}`;
}

/** Each Writer's outcome, in chain order. */
export const outcomesLine = (attempts: Attempt[]) => attempts.map((a) => `${a.writer} ${a.outcome}`).join(" · ");

/** `_EXTRACT_FIELDS` (welcome_chatter_for_info.py) in their order, with the words the window header shows. */
const FACT_LABEL: [string, string][] = [
  ["real_name", "name"], ["his_age", "age"], ["home_country", "country"], ["home_city", "city"],
  ["hobbies", "hobbies"], ["occupation", "job"], ["fetishes", "fetishes"],
];

/** The facts the test Fan gave, for the window header; "No facts yet" when none. */
export function factsLine(fanInfo: Record<string, unknown> | undefined): string {
  const got = FACT_LABEL.flatMap(([k, label]) => {
    const v = fanInfo?.[k];
    return v === undefined || v === null || String(v).trim() === "" ? [] : [`${label} ${String(v)}`];
  });
  return got.length ? got.join(" · ") : "No facts yet";
}
