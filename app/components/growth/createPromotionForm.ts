import { PROMOTION_DEFAULTS, promotionBody, type PromotionForm } from "@/lib/ofMirrorOffers";

export interface TakenFrom {
  id: number;
  name: string;
}

export interface CreatePromotionState {
  name: string;
  form: PromotionForm;
  keepRunning: boolean | null;
  preempt: boolean;
  recreateLimit: number | null;
  takenFrom: TakenFrom | null;
  err: string | null;
  unresolved: number | null;
}

export const RECREATE_MIN = 1;
export const RECREATE_MAX = 10;

export type Action =
  | { type: "name"; value: string }
  | { type: "edit"; patch: Partial<PromotionForm> }
  | { type: "keepRunning"; on: boolean }
  | { type: "preempt"; on: boolean }
  | { type: "recreateLimit"; value: number | null }
  | { type: "takenFromLoaded"; kept: TakenFrom | null }
  | { type: "failed"; err: string }
  | { type: "unresolved"; id: number; err: string }
  | { type: "clear" };

export const INITIAL_CREATE: CreatePromotionState = {
  name: "", form: PROMOTION_DEFAULTS, keepRunning: null, preempt: true, recreateLimit: null, takenFrom: null, err: null, unresolved: null,
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

export function keepRunningOn(s: CreatePromotionState): boolean {
  // Untouched: off for a Free trial so a burst cannot hand out free subs by default.
  return s.keepRunning ?? s.form.kind !== "trial";
}

// Mirrors service/promo_keep_decide PREEMPT_MIN_CAP: 90% of a smaller cap leaves no room.
export const PREEMPT_MIN_CAP = 10;

export function preemptUsable(cap: number): boolean {
  return cap >= PREEMPT_MIN_CAP;
}

export function preemptOn(s: CreatePromotionState): boolean {
  return s.preempt && keepRunningOn(s) && preemptUsable(s.form.limit);
}

const trialKept = (s: CreatePromotionState) => s.form.kind === "trial" && keepRunningOn(s);

export function blockReason(s: CreatePromotionState): string | null {
  if (s.name.trim() === "") return "Name is required.";
  if (trialKept(s) && s.form.limit < 1) return "A free trial with unlimited claims can't keep running — set an Offer limit first.";
  if (trialKept(s) && s.recreateLimit !== null && !(s.recreateLimit >= RECREATE_MIN && s.recreateLimit <= RECREATE_MAX)) {
    return `The Re-create limit is ${RECREATE_MIN}-${RECREATE_MAX}.`;
  }
  return null;
}

export function canSubmit(s: CreatePromotionState): boolean {
  return blockReason(s) === null;
}

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
  preempt?: boolean;
  expect_taken_from?: number | null;
  resolve_open?: number;
}

export function buildPayload(s: CreatePromotionState, resolve = false): CreatePromotionPayload {
  const body = promotionBody(s.form);
  return {
    name: s.name.trim(), discount: body.discount, subscribe_counts: body.subscribe_counts,
    subscribe_days: body.subscribe_days, finish_days: body.finish_days, message: body.message.trim(),
    promo_type: [...body.type], auto_reactivate: keepRunningOn(s),
    ...(trialKept(s) && s.recreateLimit !== null ? { recreate_limit: s.recreateLimit } : {}),
    ...(keepRunningOn(s) ? { expect_taken_from: s.takenFrom?.id ?? null, preempt: preemptOn(s) } : {}),
    ...(resolve && s.unresolved !== null ? { resolve_open: s.unresolved } : {}),
  };
}

export function landed(body: unknown): boolean {
  return (body as { detail?: { reason?: unknown } } | null)?.detail?.reason === "create_landed";
}

export function movedTo(body: unknown): { kept: TakenFrom | null } | undefined {
  const d = (body as { detail?: { reason?: unknown; taken_from?: unknown } } | null)?.detail;
  if (d?.reason !== "keep_running_moved") return undefined;
  const t = d.taken_from as { id?: unknown; name?: unknown } | null | undefined;
  return { kept: t && typeof t.id === "number" && typeof t.name === "string" ? { id: t.id, name: t.name } : null };
}
