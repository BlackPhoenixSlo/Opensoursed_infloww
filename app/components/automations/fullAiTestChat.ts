import { sameConfig, type ConfigBody, type FullAiConfig } from "@/components/automations/fullAiConfig";
import type { Route } from "@/hooks/useFullAiToday";
import { errText } from "@/lib/errText";
import { RelayError } from "@/lib/relay";

export type { FullAiConfig };

export type UiSide = "L" | "R";
export type TestSide = "checkpoint" | "draft";
export const UI_SIDES: readonly UiSide[] = ["L", "R"];
export const SIDE_OF: Record<UiSide, TestSide> = { L: "checkpoint", R: "draft" };

export interface HeatCheck {
  cap: number; score: number | null; level: number | null; outcome: "ok" | "regen_ok" | "over_sent" | "error";
  ms: number | null; version: string; redo_score?: number | null; first_level?: number; error?: string;
}

export interface Ppv { ref: number; price_cents: number; media: number[]; previews: number[] }
export type Part = { text: string; ppv?: Ppv } | { gif: string; tag: string };
export interface Offer {
  kind: string;
  ref: number;
  price_cents: number | null;
  list_cents: number | null;
  media: number[];
  previews: number[];
  items?: OfferItem[];
  refusal: string | null;
}
export interface OfferItem { id: number; kind: string; seconds: number | null }
export type Outcome = "bought" | "declined";
export interface Attempt { writer: string; outcome: string; ms: number; rewrite?: boolean }
export interface CaptionPath { writer: "caption" | "chat"; model: string | null; outcome: string; ms: number; attempts: Attempt[] }

export interface TurnResponse {
  row_id: number | null;
  route: Route;
  heat: number;
  route_row: string;
  dropped: string[];
  parts: Part[];
  writer: string | null;
  attempts: Attempt[];
  wait_s: number;
  status: "sent" | "failed" | "no_send";
  fan_info: Record<string, unknown>;
  offer?: Offer | null;
  caption?: CaptionPath | null;
  photo?: FanPhoto | null;
  scene?: { n: number; stage: string; heat: number } | null;
  price?: { list_cents: number; jev_cents: number | null; error: string | null } | null;
  dropped_reason?: string | null;
  heat_check?: HeatCheck | null;
}

export interface FanPhoto {
  desc: string | null;
  thumb: string;
  outcome: string;
  model: string | null;
  ms: number | null;
  read?: boolean;
}
export const MEDIA_ONLY = "[sent a photo or video]";
export const photoCaption = (p: FanPhoto) => (p.read && p.desc ? p.desc : MEDIA_ONLY);

export interface Turn {
  n: number;
  text: string;
  photo?: FanPhoto | null;
  result: TurnResponse;
  settle?: Settle;
}
export type Settle = { kind: "pending" | "done"; outcome: Outcome } | { kind: "failed"; error: string };
export interface PendingTurn {
  n: number; text: string; photo?: FanPhoto; inFlight: boolean; error: string | null;
  replyTo?: number;
}
export interface Describing { text: string; image: string; replyTo?: number }
export interface SideState {
  turns: Turn[];
  pending: PendingTurn | null;
  revealAt: number | null;
}

export interface TestChatState {
  pair: string;
  skipWait: boolean;
  text: string;
  photo: string | null;
  describing: Describing | null;
  photoError: string | null;
  replyTo: number | null;
  sides: Record<UiSide, SideState>;
  checkpoint: FullAiConfig | null;
  previous: FullAiConfig | null;
  draft: FullAiConfig | null;
  rev: number;
  dirty: boolean;
  savingDraft: boolean;
  committing: boolean;
  stale: boolean;
  audienceSaving: number;
  errors: string[];
  conflict: ConfigBody | null;
  held: ConfigBody | null;
}

export type TestChatAction =
  | { type: "edit"; text: string }
  | { type: "attach"; image: string }
  | { type: "detach" }
  | { type: "replyTo"; n: number }
  | { type: "clearReply" }
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
  | { type: "audienceSave" }
  | { type: "audienceSaved"; body: ConfigBody }
  | { type: "audienceSaveFailed" }
  | { type: "externalDraft"; body: ConfigBody }
  | { type: "keepMine" }
  | { type: "takeTheirs" }
  | { type: "settle"; side: UiSide; rowId: number; outcome: Outcome }
  | { type: "settled"; pair: string; side: UiSide; rowId: number; outcome: Outcome }
  | { type: "settleFailed"; pair: string; side: UiSide; rowId: number; error: string };

const EMPTY_SIDE: SideState = { turns: [], pending: null, revealAt: null };

// L/R exist only in the page's code; every request says side: checkpoint | draft.
export function initTestChat(pair: string, skipWait = false): TestChatState {
  return {
    pair, skipWait, text: "", photo: null, describing: null, photoError: null, replyTo: null,
    sides: { L: EMPTY_SIDE, R: EMPTY_SIDE },
    checkpoint: null, previous: null, draft: null, rev: 0,
    dirty: false, savingDraft: false, committing: false, stale: false, audienceSaving: 0, errors: [], conflict: null,
    held: null,
  };
}

// The draft side's Turn reads the stored draft only, so Send waits while an edit is unstored.
export function sendBlock(state: TestChatState): string | null {
  if (state.conflict) return "Keep mine or Take theirs first";
  if (state.savingDraft) return "Saving draft…";
  return state.dirty ? "Draft not saved: fix it or Reload" : null;
}

// A Turn is never cut in two: no side may owe a request or hide a reply.
export function canSend(state: TestChatState): boolean {
  return (state.text.trim() !== "" || state.photo !== null) && state.describing === null
    && sendBlock(state) === null && !state.committing
    && UI_SIDES.every((s) => state.sides[s].pending === null && state.sides[s].revealAt === null);
}

export function canEdit(state: TestChatState): boolean {
  return state.draft !== null && !state.savingDraft && !state.committing && !state.stale && state.conflict === null
    && state.describing === null && state.audienceSaving === 0;
}

export function keepMineSave(state: TestChatState): { draft: FullAiConfig; rev: number } | null {
  return state.conflict && state.draft && state.describing === null
    ? { draft: state.draft, rev: state.conflict.rev } : null;
}

export function canSave(state: TestChatState): boolean {
  return canEdit(state) && !state.dirty && state.errors.length === 0 && !sameConfig(state.draft, state.checkpoint);
}

/** Roll back (swap the checkpoint and the previous one): a previous to go to, nothing out, not stale. */
export function canRollback(state: TestChatState): boolean {
  return canEdit(state) && state.previous !== null;
}

export interface TurnPayload { pair: string; side: TestSide; n: number; text: string; photo?: FanPhoto; reply_to_n?: number }

export function buildTurnPayload(state: TestChatState, ui: UiSide): TurnPayload | null {
  const p = state.sides[ui].pending;
  if (!p) return null;
  return { pair: state.pair, side: SIDE_OF[ui], n: p.n, text: p.text, ...(p.photo ? { photo: p.photo } : {}),
    ...(p.replyTo ? { reply_to_n: p.replyTo } : {}) };
}

const owe = (s: SideState, text: string, photo?: FanPhoto, replyTo?: number | null): SideState =>
  ({ ...s, pending: { n: s.turns.length + 1, text, ...(photo ? { photo } : {}), ...(replyTo ? { replyTo } : {}),
    inFlight: true, error: null } });

const nextN = (state: TestChatState) => Math.min(...UI_SIDES.map((s) => state.sides[s].turns.length)) + 1;

function unsent(state: TestChatState, d: Describing, why: string): TestChatState {
  const text = [d.text, state.text].filter((t) => t.trim() !== "").join(" ");
  return { ...state, describing: null, text, photo: d.image, photoError: why, replyTo: d.replyTo ?? state.replyTo };
}

const withSide = (state: TestChatState, ui: UiSide, side: SideState): TestChatState =>
  ({ ...state, sides: { ...state.sides, [ui]: side } });

// A settle lives on its Turn, not in pending, so it never blocks Send.
export function canSettle(turn: Turn): boolean {
  return (turn.result.offer?.price_cents ?? 0) > 0 && (!turn.settle || turn.settle.kind === "failed");
}

export interface SettlePayload { account_id: string; pair: string; side: TestSide; row_id: number; outcome: Outcome }

export function buildSettlePayload(
  state: TestChatState, ui: UiSide, rowId: number, outcome: Outcome, accountId: string,
): SettlePayload {
  return { account_id: accountId, pair: state.pair, side: SIDE_OF[ui], row_id: rowId, outcome };
}

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
    case "replyTo":
      return Number.isInteger(action.n) && action.n >= 1 && action.n < nextN(state) ? { ...state, replyTo: action.n } : state;
    case "clearReply":
      return { ...state, replyTo: null };
    case "send": {
      if (!canSend(state)) return state;
      const text = state.text.trim(), r = state.replyTo;
      if (state.photo !== null) {
        return { ...state, text: "", photo: null, photoError: null, replyTo: null,
          describing: { text, image: state.photo, ...(r ? { replyTo: r } : {}) } };
      }
      return { ...state, text: "", photoError: null, replyTo: null,
        sides: { L: owe(state.sides.L, text, undefined, r), R: owe(state.sides.R, text, undefined, r) } };
    }
    case "photoDescribed": {
      const d = state.describing;
      if (action.pair !== state.pair || !d) return state;
      const block = sendBlock(state);
      if (block) return unsent(state, d, `Not sent: ${block}`);
      return { ...state, describing: null,
        sides: { L: owe(state.sides.L, d.text, action.photo, d.replyTo), R: owe(state.sides.R, d.text, action.photo, d.replyTo) } };
    }
    case "photoFailed": {
      const d = state.describing;
      if (action.pair !== state.pair || !d) return state;
      return unsent(state, d, action.error);
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
      return { ...state, pair: action.pair, text: "", photo: null, describing: null, photoError: null, replyTo: null,
        sides: { L: EMPTY_SIDE, R: EMPTY_SIDE } };
    case "loaded":
      return offerHeld(adopt(state, action.body));
    case "editDraft":
      return { ...state, draft: action.draft, dirty: true, errors: [] };
    case "saveDraft":
      return { ...state, savingDraft: true };
    case "draftSaved":
      return offerHeld({ ...state, draft: action.draft, rev: action.rev, dirty: false, savingDraft: false, errors: [] });
    case "configFailed":
      return offerHeld({ ...state, errors: action.errors, savingDraft: false, committing: false });
    case "commit":
      return { ...state, committing: true };
    case "saved":
      return offerHeld({ ...state, previous: state.checkpoint, checkpoint: state.draft, rev: action.rev, committing: false, errors: [] });
    case "rolledBack":
      return offerHeld({ ...state, checkpoint: state.previous, previous: state.checkpoint, rev: action.rev, committing: false, errors: [] });
    case "stale":
      return { ...state, stale: true, savingDraft: false, committing: false };
    case "audienceSave":
      return { ...state, audienceSaving: state.audienceSaving + 1 };
    case "audienceSaved":
      return audienceSaved({ ...state, audienceSaving: Math.max(0, state.audienceSaving - 1) }, action.body);
    case "audienceSaveFailed":
      return { ...state, audienceSaving: Math.max(0, state.audienceSaving - 1) };
    case "externalDraft":
      return offer(state, action.body);
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

export const STALE_TEXT = "Someone saved this config meanwhile. Reload.";

const relayBody = (e: unknown) => (e instanceof RelayError ? (e.body as { errors?: unknown; rev?: unknown } | null) : null);
const refused409 = (e: unknown): boolean =>
  e instanceof RelayError && e.status === 409 && typeof relayBody(e)?.rev !== "number";

export function writeFailed(e: unknown): TestChatAction {
  if (e instanceof RelayError && e.status === 409 && !refused409(e)) return { type: "stale" };
  const errors = relayBody(e)?.errors;
  return { type: "configFailed", errors: Array.isArray(errors) ? errors.map(String) : [errText(e, "Request failed")] };
}

/** Who live answers (owner 2026-11-15): not how the AI behaves, so one value on every side, written only by
 *  `PUT config/audience` (the config writes carry the stored ones over). */
export const AUDIENCE_KEYS = ["fans", "top_spend_cents"] as const;
export type AudiencePatch = Partial<Pick<FullAiConfig, (typeof AUDIENCE_KEYS)[number]>>;

const withAudience = (c: FullAiConfig | null, src: FullAiConfig | null): FullAiConfig | null => {
  if (!c || !src) return c;
  const out = { ...c };
  for (const k of AUDIENCE_KEYS) if (k in src) Object.assign(out, { [k]: src[k] });
  return out;
};

export type AudienceResult = { kind: "ok" } | { kind: "failed"; reason: string };

export function audienceFailed(e: unknown): AudienceResult {
  if (refused409(e)) return { kind: "failed", reason: errText(e, "Refused") };
  if (e instanceof RelayError && e.status === 409) return { kind: "failed", reason: "Someone saved this config meanwhile. Try again." };
  const errors = relayBody(e)?.errors;
  return { kind: "failed", reason: Array.isArray(errors) ? errors.map(String).join(" ") : errText(e, "Request failed") };
}

// Dropped when no newer than the page's rev, so a slower answer never puts old values back.
function audienceSaved(state: TestChatState, body: ConfigBody): TestChatState {
  if (body.rev <= Math.max(state.rev, state.held?.rev ?? 0, state.conflict?.rev ?? 0)) return state;
  const src = body.checkpoint;
  const s = { ...state, checkpoint: withAudience(state.checkpoint, src), previous: withAudience(state.previous, src),
    draft: withAudience(state.draft, src) };
  if (state.savingDraft || state.committing) return { ...s, held: body };
  return body.rev === state.rev + 1 ? { ...s, rev: body.rev } : offer(s, body);
}

// Never overwrites an unsaved edit silently: it raises the conflict.
function offer(state: TestChatState, body: ConfigBody): TestChatState {
  if (state.savingDraft || state.committing || state.stale) {
    return { ...state, held: state.held && state.held.rev > body.rev ? state.held : body };
  }
  if (body.rev <= Math.max(state.rev, state.conflict?.rev ?? 0)) return state;
  return state.dirty ? { ...state, conflict: body } : adopt(state, body);
}

const offerHeld = (state: TestChatState): TestChatState => (state.held ? offer({ ...state, held: null }, state.held) : state);

function adopt(state: TestChatState, { checkpoint, previous, draft, rev, errors }: ConfigBody): TestChatState {
  return { ...state, checkpoint, previous, draft, rev, errors,
    dirty: false, savingDraft: false, committing: false, stale: false, conflict: null };
}

export type SessionRow = Omit<TurnResponse, "dropped" | "wait_s" | "photo"> & {
  side: TestSide; n: number; text: string; wait_s: number | null; created_at: string; photo?: FanPhoto | null;
};
export interface SessionBody { rows: SessionRow[] }

export function sessionTurns(body: SessionBody, side: TestSide): Turn[] {
  return body.rows.filter((r) => r.side === side).map(({ side: _s, created_at: _c, n, text, wait_s, photo, ...rest }) => ({
    n, text, ...(photo ? { photo } : {}), result: { ...rest, dropped: [], wait_s: wait_s ?? 0 },
  }));
}


export type PpvLine = { kind: "settled"; dollars: number; paid: boolean } | { kind: "price"; dollars: number } | { kind: "free" };
export function ppvLine(t: Turn): PpvLine | null {
  const cents = t.result.offer?.price_cents;
  if (cents == null) return null;
  if (cents === 0) return { kind: "free" };
  return t.settle?.kind === "done" ? { kind: "settled", dollars: cents / 100, paid: t.settle.outcome === "bought" }
    : { kind: "price", dollars: cents / 100 };
}

const clock = (secs: number) => {
  const h = Math.floor(secs / 3600), m = Math.floor((secs % 3600) / 60), ss = String(secs % 60).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${ss}` : `${m}:${ss}`;
};

export function mediaLine(offer: Offer): string | null {
  const locked = new Set(offer.media);
  const items = (offer.items ?? []).filter((i) => locked.has(i.id));
  if (!items.length) return null;
  const kinds = [...new Set(["photo", "video", ...items.map((i) => i.kind)])];
  const counts = kinds.map((k) => [k, items.filter((i) => i.kind === k).length] as const).filter(([, n]) => n > 0);
  const head = counts.map(([k, n]) => `${n} ${k}${n > 1 ? "s" : ""}`).join(" + ");
  const videos = items.filter((i) => i.kind === "video");
  const timed = videos.length > 0 && videos.every((i) => i.seconds);
  return timed ? `${head} · ${clock(videos.reduce((t, i) => t + (i.seconds ?? 0), 0))}` : head;
}

export function replyLine(r: TurnResponse): string {
  const head = `Route ${r.route} · Heat ${r.heat} · Row ${r.route_row}`;
  if (r.status !== "sent" || !r.writer) return head;
  // The chain stops at the first Writer that answers; the Claim audit's rewrite attempts are not Writers falling.
  const fell = r.attempts.filter((a) => !a.rewrite && a.outcome !== "ok");
  const why = fell.length ? ` (${outcomesLine(fell)})` : "";
  const cap = !r.caption ? "" : r.caption.writer === "caption" ? ` · Caption ${r.caption.model}` : ` · Caption chat (${r.caption.outcome})`;
  return `${head} · Writer ${r.writer} · ${fell.length} fell before${why}${cap}${sceneTail(r)}${heatTail(r.heat_check)}`;
}

const usd = (c: number) => `$${c % 100 ? (c / 100).toFixed(2) : c / 100}`;

function sceneTail(r: TurnResponse): string {
  const s = r.scene ? ` · scene ${r.scene.stage} · ${r.scene.n}` : "";
  const p = r.price;
  const px = p && p.jev_cents != null && p.jev_cents !== p.list_cents ? ` · price Jev ${usd(p.jev_cents)} (list ${usd(p.list_cents)})`
    : p?.error ? ` · price Jev failed (list ${usd(p.list_cents)})` : "";
  return s + px;
}

export function heatTail(h: HeatCheck | null | undefined): string {
  if (!h) return "";
  if (h.outcome === "error" || h.level == null) return " · Heat check failed";
  const lvl = ` · reply level ${h.level} of Heat ${h.cap}`;
  if (h.outcome === "regen_ok") return `${lvl} · rewritten${h.first_level != null ? ` (was ${h.first_level})` : ""}`;
  return h.outcome === "over_sent" ? `${lvl} · over Heat, sent` : lvl;
}

export function noReplyText(r: TurnResponse): string | null {
  if (r.status === "no_send") {
    return r.route_row === "says_under_18" ? "no reply (under 18)"
      : r.route_row === "promo" ? "no reply (promo)" : `no reply (${r.route_row})`;
  }
  if (r.status === "failed") {
    if (writersFailed(r)) return "no reply: all writers failed";
    return `no reply: the reply chain dropped it${r.dropped_reason ? ` (${DROP_WORDS[r.dropped_reason] ?? r.dropped_reason})` : ""}`;
  }
  return null;
}

const DROP_WORDS: Record<string, string> = { empty: "nothing left to send", banned: "sensitive word", echo: "repeated his line" };

export const writersFailed = (r: TurnResponse) => r.status === "failed" && r.attempts.every((a) => a.outcome !== "ok");

export const outcomesLine = (attempts: Attempt[]) => attempts.map((a) => `${a.writer} ${a.outcome}`).join(" · ");

const FACT_LABEL: [string, string][] = [
  ["real_name", "name"], ["his_age", "age"], ["home_country", "country"], ["home_city", "city"],
  ["hobbies", "hobbies"], ["occupation", "job"], ["fetishes", "fetishes"],
];

export function factsLine(fanInfo: Record<string, unknown> | undefined): string {
  const got = FACT_LABEL.flatMap(([k, label]) => {
    const v = fanInfo?.[k];
    return v === undefined || v === null || String(v).trim() === "" ? [] : [`${label} ${String(v)}`];
  });
  return got.length ? got.join(" · ") : "No facts yet";
}
