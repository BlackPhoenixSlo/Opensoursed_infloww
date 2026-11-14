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
 */

import type { Route } from "@/hooks/useFullAiToday";

export type UiSide = "L" | "R";
export type TestSide = "checkpoint" | "draft";
export const UI_SIDES: readonly UiSide[] = ["L", "R"];
export const SIDE_OF: Record<UiSide, TestSide> = { L: "checkpoint", R: "draft" };

/** One of her bubbles: text, or a GIF (`{gif: <giphy id>, tag}`). */
export type Part = { text: string } | { gif: string; tag: string };
export interface Attempt { writer: string; outcome: string; ms: number }

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
}

export interface Turn { n: number; text: string; result: TurnResponse }
/** The request a side owes: in flight, or failed and waiting for a retry with the same `n`. */
export interface PendingTurn { n: number; text: string; inFlight: boolean; error: string | null }
export interface SideState {
  turns: Turn[];
  pending: PendingTurn | null;
  /** Epoch ms the newest reply shows at; null = shown. */
  revealAt: number | null;
}

/** One side of Full AI Chat's config (`full_ai_config.DEFAULTS` keys): draft, checkpoint or previous. The page edits the
 *  three named keys, the JSON the rest; they are optional, as a hand-typed JSON draft may lack them until the server
 *  refuses it. */
export interface FullAiConfig {
  reply_speed?: string;
  text_style?: string;
  gifs?: boolean;
  [key: string]: unknown;
}
/** GET /admin/full-ai/config's body; every config write answers the same shape. */
export interface ConfigBody {
  checkpoint: FullAiConfig;
  previous: FullAiConfig | null;
  draft: FullAiConfig;
  rev: number;
  errors: string[];
}

export interface TestChatState {
  pair: string;
  skipWait: boolean;
  /** The composer's Fan line. */
  text: string;
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
  | { type: "send" }
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
  | { type: "takeTheirs" };

const EMPTY_SIDE: SideState = { turns: [], pending: null, revealAt: null };

export function initTestChat(pair: string, skipWait = false): TestChatState {
  return {
    pair, skipWait, text: "", sides: { L: EMPTY_SIDE, R: EMPTY_SIDE },
    checkpoint: null, previous: null, draft: null, rev: 0,
    dirty: false, savingDraft: false, committing: false, stale: false, errors: [], conflict: null,
  };
}

/** Why Send waits on the config, or null: an edit not stored yet would not reach the draft side's Turn. */
export function sendBlock(state: TestChatState): string | null {
  if (state.conflict) return "Keep mine or Take theirs first";
  return state.dirty || state.savingDraft ? "Save draft first" : null;
}

/** Send is allowed with a Fan line typed, neither side owing a request or hiding a reply (a Turn is never cut in
 *  two), the draft stored and no Save / Roll back out. */
export function canSend(state: TestChatState): boolean {
  return state.text.trim() !== "" && sendBlock(state) === null && !state.committing
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
export interface TurnPayload { pair: string; side: TestSide; n: number; text: string }

/** The side's owed request; `n` = its Turn count + 1, the same on a retry. */
export function buildTurnPayload(state: TestChatState, ui: UiSide): TurnPayload | null {
  const p = state.sides[ui].pending;
  if (!p) return null;
  return { pair: state.pair, side: SIDE_OF[ui], n: p.n, text: p.text };
}

const withSide = (state: TestChatState, ui: UiSide, side: SideState): TestChatState =>
  ({ ...state, sides: { ...state.sides, [ui]: side } });

export function testChatReducer(state: TestChatState, action: TestChatAction): TestChatState {
  switch (action.type) {
    case "edit":
      return { ...state, text: action.text };
    case "send": {
      if (!canSend(state)) return state;
      const text = state.text.trim();
      const owe = (s: SideState): SideState =>
        ({ ...s, pending: { n: s.turns.length + 1, text, inFlight: true, error: null } });
      return { ...state, text: "", sides: { L: owe(state.sides.L), R: owe(state.sides.R) } };
    }
    case "turnResult": {
      const s = state.sides[action.side];
      if (action.pair !== state.pair || s.pending?.n !== action.n) return state;
      return withSide(state, action.side, {
        turns: [...s.turns, { n: action.n, text: s.pending.text, result: action.result }],
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
      return withSide(state, action.side, { turns: action.turns, pending: null, revealAt: null });
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
      return { ...state, pair: action.pair, text: "", sides: { L: EMPTY_SIDE, R: EMPTY_SIDE } };
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
  }
}

/** A stored config body taken whole (`loaded`, an adopted `externalDraft`, Take theirs): nothing unstored is left. */
function adopt(state: TestChatState, { checkpoint, previous, draft, rev, errors }: ConfigBody): TestChatState {
  return { ...state, checkpoint, previous, draft, rev, errors,
    dirty: false, savingDraft: false, committing: false, stale: false, conflict: null };
}

/** One row of GET /admin/full-ai/test/session (`full_ai_test.session_row`): the turn answer minus `dropped`, plus
 *  its side, Turn number, his line and when it was recorded. `wait_s` is null on a Turn that sent nothing. */
export type SessionRow = Omit<TurnResponse, "dropped" | "wait_s"> & {
  side: TestSide; n: number; text: string; wait_s: number | null; created_at: string;
};
/** The session read's body: both sides' rows, oldest first. */
export interface SessionBody { rows: SessionRow[] }

/** One side's Turns from the session read. A reloaded Turn is already recorded, so it carries no rows dropped. */
export function sessionTurns(body: SessionBody, side: TestSide): Turn[] {
  return body.rows.filter((r) => r.side === side).map(({ side: _s, created_at: _c, n, text, wait_s, ...rest }) => ({
    n, text, result: { ...rest, dropped: [], wait_s: wait_s ?? 0 },
  }));
}

// ── What a window prints (pure, so the component only renders) ─────────────────────────────────────────────────────

/** The line under a reply: Route, Heat, matched row and, when she answered, the Writer and how many fell before it. */
export function replyLine(r: TurnResponse): string {
  const head = `Route ${r.route} · Heat ${r.heat} · Row ${r.route_row}`;
  if (r.status !== "sent" || !r.writer) return head;
  // The chain stops at the first Writer that answers, so every attempt before the last fell.
  return `${head} · Writer ${r.writer} · ${r.attempts.length - 1} fell before`;
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
/** Human style is on unless the config says formal (the server's default is the casual style). */
export const humanStyleOn = (cfg: FullAiConfig | null) => cfg?.text_style !== "formal";
const onOff = (on: boolean) => (on ? "on" : "off");

/** A side's config for its window header: reply speed, Human style, GIFs. */
export function configLine(cfg: FullAiConfig): string {
  const speed = cfg.reply_speed ?? DEFAULT_SPEED;
  const label = REPLY_SPEEDS.find((o) => o.value === speed)?.label ?? speed;
  return `Reply ${label} · Human style ${onOff(humanStyleOn(cfg))} · GIFs ${onOff(cfg.gifs === true)}`;
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
