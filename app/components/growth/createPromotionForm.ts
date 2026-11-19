/**
 * Create promotion's form state (CreatePromotionModal only dispatches): the Name, OF's fields (`PromotionForm`), Keep
 * running (on by default: the new campaign takes the flag from any other) and the last error. `canSubmit` gates the
 * Create; `buildPayload` is the POST /admin/promotions body.
 */

import { PROMOTION_DEFAULTS, promotionBody, type PromotionForm } from "@/lib/ofMirrorOffers";

export interface CreatePromotionState {
  name: string;
  form: PromotionForm;
  keepRunning: boolean;
  err: string | null;
}

export type Action =
  | { type: "name"; value: string }
  | { type: "edit"; patch: Partial<PromotionForm> }
  | { type: "keepRunning"; on: boolean }
  | { type: "failed"; err: string }
  | { type: "clear" };

export const INITIAL_CREATE: CreatePromotionState = { name: "", form: PROMOTION_DEFAULTS, keepRunning: true, err: null };

export function createPromotionReducer(state: CreatePromotionState, action: Action): CreatePromotionState {
  switch (action.type) {
    case "name":
      return { ...state, name: action.value };
    case "edit":
      return { ...state, form: { ...state.form, ...action.patch } };
    case "keepRunning":
      return { ...state, keepRunning: action.on };
    case "failed":
      return { ...state, err: action.err };
    case "clear":
      return state.err === null ? state : { ...state, err: null };
  }
}

/** A name is the one field OF does not default. */
export function canSubmit(s: CreatePromotionState): boolean {
  return s.name.trim() !== "";
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
}

export function buildPayload(s: CreatePromotionState): CreatePromotionPayload {
  const body = promotionBody(s.form);
  return {
    name: s.name.trim(), discount: body.discount, subscribe_counts: body.subscribe_counts,
    subscribe_days: body.subscribe_days, finish_days: body.finish_days, message: body.message.trim(),
    promo_type: [...body.type], auto_reactivate: s.keepRunning,
  };
}
