export const TOKEN_DAYS = [30, 90, 365] as const;
export type TokenDays = (typeof TOKEN_DAYS)[number];
export const DEFAULT_DAYS: TokenDays = 90;

export function toTokenDays(v: string | number): TokenDays {
  const n = Number(v);
  return (TOKEN_DAYS as readonly number[]).includes(n) ? (n as TokenDays) : DEFAULT_DAYS;
}
export const NAME_MAX = 64;

export interface AccessTokensForm {
  open: boolean;
  name: string;
  days: TokenDays;
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

export function canSubmit(s: AccessTokensForm): boolean {
  const name = s.name.trim();
  return s.open && s.created === null && name.length > 0 && name.length <= NAME_MAX;
}

export function buildPayload(s: AccessTokensForm): { name: string; days: TokenDays } {
  return { name: s.name.trim(), days: s.days };
}
