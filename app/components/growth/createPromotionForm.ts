/**
 * Create promotion's form state (CreatePromotionModal only dispatches): the Name, OF's fields (`PromotionForm`), Keep
 * running (the new campaign takes the flag from any other; null = not touched: off for a Free trial, on otherwise,
 * so a burst cannot hand out free subs by default), Re-create at 90% filled (`preempt`, the second tick: ticked by
 * default, sent only with Keep running on, and only an Offer limit of 10 or more pre-empts), the Free trial's Re-create
 * limit, the Kept campaign the dialog
 * shows it takes over from (`takenFrom`, sent back so a change meanwhile is refused), the last error, and the
 * earlier create the relay could not settle (`unresolved`: its reservation id, which "It did not go through —
 * create anyway" clears). `canSubmit` gates the Create; `buildPayload` is the POST /admin/promotions body
 * (docs/spec/phase-01-promo-preempt.md).
 */

import { PROMOTION_DEFAULTS, promotionBody, type PromotionForm } from "@/lib/ofMirrorOffers";

/** The campaign that keeps running now (it loses the flag to a new one with Keep running on). */
export interface TakenFrom {
  id: number;
  name: string;
}

export interface CreatePromotionState {
  name: string;
  form: PromotionForm;
  keepRunning: boolean | null;
  preempt: boolean;
  recreateLimit: number;
  takenFrom: TakenFrom | null;
  err: string | null;
  unresolved: number | null;
}

/** The relay's bounds for a Free trial's Re-create limit. */
export const RECREATE_MIN = 1;
export const RECREATE_MAX = 10;

export type Action =
  | { type: "name"; value: string }
  | { type: "edit"; patch: Partial<PromotionForm> }
  | { type: "keepRunning"; on: boolean }
  | { type: "preempt"; on: boolean }
  | { type: "recreateLimit"; value: number }
  | { type: "takenFromLoaded"; kept: TakenFrom | null }
  | { type: "failed"; err: string }
  | { type: "unresolved"; id: number; err: string }
  | { type: "clear" };

export const INITIAL_CREATE: CreatePromotionState = {
  name: "", form: PROMOTION_DEFAULTS, keepRunning: null, preempt: true, recreateLimit: 3, takenFrom: null, err: null, unresolved: null,
};

export function createPromotionReducer(state: CreatePromotionState, action: Action): CreatePromotionState {
  switch (action.type) {
    case "name":
      return { ...state, name: action.value };
    case "edit":
      return { ...state, form: { ...state.form, ...action.patch } };
    case "keepRunning":
      return { ...state, keepRunning: action.on };
    case "preempt":
      return { ...state, preempt: action.on };
    case "recreateLimit":
      return { ...state, recreateLimit: action.value };
    case "takenFromLoaded":
      return state.takenFrom?.id === action.kept?.id && state.takenFrom?.name === action.kept?.name
        ? state : { ...state, takenFrom: action.kept };
    case "failed":
      return { ...state, err: action.err, unresolved: null };
    case "unresolved":
      return { ...state, err: action.err, unresolved: action.id };
    case "clear":
      return state.err === null && state.unresolved === null ? state : { ...state, err: null, unresolved: null };
  }
}

/** Keep running as the operator sees it: untouched = off for a Free trial, on for a discount. */
export function keepRunningOn(s: CreatePromotionState): boolean {
  return s.keepRunning ?? s.form.kind !== "trial";
}

/** The smallest Claim cap that pre-empts (the relay's: 90% of a smaller cap leaves no room); 0 is unlimited. */
export const PREEMPT_MIN_CAP = 10;

/** Re-create at 90% filled can act on this Claim cap; under it the promo re-creates after it ends. */
export function preemptUsable(cap: number): boolean {
  return cap >= PREEMPT_MIN_CAP;
}

/** Re-create at 90% filled as sent: ticked, Keep running on, and a cap it can act on. */
export function preemptOn(s: CreatePromotionState): boolean {
  return s.preempt && keepRunningOn(s) && preemptUsable(s.form.limit);
}

/** A Free trial kept running carries a Re-create limit. */
const trialKept = (s: CreatePromotionState) => s.form.kind === "trial" && keepRunningOn(s);

/** Why Create is refused, or null: a name (the one field OF does not default); a Free trial kept running needs an
 *  Offer limit and a Re-create limit of 1-10 (the relay refuses it too). */
export function blockReason(s: CreatePromotionState): string | null {
  if (s.name.trim() === "") return "Name is required.";
  if (trialKept(s) && s.form.limit < 1) return "A free trial with unlimited claims can't keep running — set an Offer limit first.";
  if (trialKept(s) && !(s.recreateLimit >= RECREATE_MIN && s.recreateLimit <= RECREATE_MAX)) {
    return `The Re-create limit is ${RECREATE_MIN}-${RECREATE_MAX}.`;
  }
  return null;
}

export function canSubmit(s: CreatePromotionState): boolean {
  return blockReason(s) === null;
}

/** The line naming the campaign that loses Keep running to this one, or null when none keeps running. */
export function takeoverNotice(keptName: string | null | undefined): string | null {
  return keptName ? `Keep running moves from “${keptName}” to this promotion.` : null;
}

export interface CreatePromotionPayload {
  name: string;
  discount: number;
  subscribe_counts: number;
  subscribe_days: number;
  finish_days: number;
  message: string;
  promo_type: string[];
  auto_reactivate: boolean;
  recreate_limit?: number;
  /** Re-create at 90% filled; only with Keep running on. False under a cap of 10: it could never act there. */
  preempt?: boolean;
  /** The Kept campaign the dialog showed (null: none); the relay answers 409 keep_running_moved if it changed. */
  expect_taken_from?: number | null;
  resolve_open?: number;
}

/** `resolve`: the operator's "create anyway" — clear the unresolved create on the way. */
export function buildPayload(s: CreatePromotionState, resolve = false): CreatePromotionPayload {
  const body = promotionBody(s.form);
  return {
    name: s.name.trim(), discount: body.discount, subscribe_counts: body.subscribe_counts,
    subscribe_days: body.subscribe_days, finish_days: body.finish_days, message: body.message.trim(),
    promo_type: [...body.type], auto_reactivate: keepRunningOn(s),
    ...(trialKept(s) ? { recreate_limit: s.recreateLimit } : {}),
    ...(keepRunningOn(s) ? { expect_taken_from: s.takenFrom?.id ?? null, preempt: preemptOn(s) } : {}),
    ...(resolve && s.unresolved !== null ? { resolve_open: s.unresolved } : {}),
  };
}

/** The relay's 409 `keep_running_moved` body → the campaign keeping running now (`kept`, null: none), else undefined. */
export function movedTo(body: unknown): { kept: TakenFrom | null } | undefined {
  const d = (body as { detail?: { reason?: unknown; taken_from?: unknown } } | null)?.detail;
  if (d?.reason !== "keep_running_moved") return undefined;
  const t = d.taken_from as { id?: unknown; name?: unknown } | null | undefined;
  return { kept: t && typeof t.id === "number" && typeof t.name === "string" ? { id: t.id, name: t.name } : null };
}
