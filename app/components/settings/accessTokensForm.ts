/**
 * Settings → AI keys → Access tokens: the New token dialog's state. A pure reducer (AccessTokensCard only
 * dispatches), `canSubmit` and `buildPayload`. The dialog has two faces: the form (name + expiry) and, once the
 * relay minted it, the token itself, shown this once (`created`); closing drops it for good.
 * Relay: POST /admin/owner-tokens `{ name, days }` (service/owner_tokens_api.py).
 */

export const TOKEN_DAYS = [30, 90, 365] as const;
export type TokenDays = (typeof TOKEN_DAYS)[number];
export const DEFAULT_DAYS: TokenDays = 90;

/** A select's raw value as TokenDays; anything else falls back to the default. */
export function toTokenDays(v: string | number): TokenDays {
  const n = Number(v);
  return (TOKEN_DAYS as readonly number[]).includes(n) ? (n as TokenDays) : DEFAULT_DAYS;
}
export const NAME_MAX = 64;

export interface AccessTokensForm {
  open: boolean;
  name: string;
  days: TokenDays;
  /** The minted token, shown once; null while the form shows. */
  created: { name: string; token: string } | null;
}

export type Action =
  | { type: "open" }
  | { type: "close" }
  | { type: "name"; value: string }
  | { type: "days"; value: TokenDays }
  | { type: "created"; name: string; token: string };

export const INITIAL_FORM: AccessTokensForm = { open: false, name: "", days: DEFAULT_DAYS, created: null };

export function accessTokensFormReducer(state: AccessTokensForm, action: Action): AccessTokensForm {
  switch (action.type) {
    case "open":
      return { ...INITIAL_FORM, open: true };
    case "close":
      return INITIAL_FORM;
    case "name":
      return state.created ? state : { ...state, name: action.value };
    case "days":
      return state.created ? state : { ...state, days: action.value };
    case "created":
      return state.open ? { ...state, created: { name: action.name, token: action.token } } : state;
  }
}

/** Create is on with a name (1–64 characters once trimmed) while the form, not the token, shows. */
export function canSubmit(s: AccessTokensForm): boolean {
  const name = s.name.trim();
  return s.open && s.created === null && name.length > 0 && name.length <= NAME_MAX;
}

export function buildPayload(s: AccessTokensForm): { name: string; days: TokenDays } {
  return { name: s.name.trim(), days: s.days };
}
