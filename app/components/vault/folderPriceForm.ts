export const MIN_CENTS = 1000;
export const MAX_CENTS = 20000;

export interface FolderPriceForm {
  text: string;
  busy: boolean;
  error: string | null;
}

export type Action =
  | { type: "edit"; text: string }
  | { type: "saving" }
  | { type: "failed"; error: string };

export function initForm(cents: number | null): FolderPriceForm {
  return { text: cents == null ? "" : formatDollars(cents), busy: false, error: null };
}

export function folderPriceReducer(state: FolderPriceForm, action: Action): FolderPriceForm {
  switch (action.type) {
    case "edit":
      return { ...state, text: action.text, error: null };
    case "saving":
      return { ...state, busy: true, error: null };
    case "failed":
      return { ...state, busy: false, error: action.error };
  }
}

export function parseDollars(text: string): number | null {
  const m = /^\$?\s*(\d{1,3})(?:\.(\d{1,2}))?$/.exec(text.trim());
  if (!m) return null;
  const cents = Number(m[1]) * 100 + Number((m[2] ?? "").padEnd(2, "0"));
  return cents >= MIN_CENTS && cents <= MAX_CENTS ? cents : null;
}

export function formatPrice(cents: number): string {
  return `$${formatDollars(cents)}`;
}

function formatDollars(cents: number): string {
  return cents % 100 === 0 ? String(cents / 100) : (cents / 100).toFixed(2);
}

export function canSave(state: FolderPriceForm, current: number | null): boolean {
  const cents = parseDollars(state.text);
  return !state.busy && cents !== null && cents !== current;
}

export function buildPayload(accountId: string, ref: string, state: FolderPriceForm | null) {
  return { account_id: accountId, ref, price_cents: state === null ? null : parseDollars(state.text) };
}
