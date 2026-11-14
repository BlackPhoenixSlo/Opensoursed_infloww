/**
 * The "Set price" dialog's form (VaultFolderRail): the dollars typed, the write in flight, and its error. A pure
 * reducer (the dialog only dispatches), `parseDollars` (the text as whole cents inside the relay's [$10, $200]),
 * `canSave` and `buildPayload`, the POST /admin/vault-ai/folder-prices body (Clear posts `price_cents: null`).
 * An agency's folder price is what Full AI Chat's sell executor lists that folder's items at; our DB only, no OF write.
 */

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

/** The dialog's first state: the folder's price in dollars ("25", "24.99"), or empty when unpriced. */
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

/** "25", "$25", "24.99", "24.5" -> cents; blank, junk, more than 2 decimals or outside [$10, $200] -> null. */
export function parseDollars(text: string): number | null {
  const m = /^\$?\s*(\d{1,3})(?:\.(\d{1,2}))?$/.exec(text.trim());
  if (!m) return null;
  const cents = Number(m[1]) * 100 + Number((m[2] ?? "").padEnd(2, "0"));
  return cents >= MIN_CENTS && cents <= MAX_CENTS ? cents : null;
}

/** "$25" on whole dollars, else "$24.99" (the chip). */
export function formatPrice(cents: number): string {
  return `$${formatDollars(cents)}`;
}

function formatDollars(cents: number): string {
  return cents % 100 === 0 ? String(cents / 100) : (cents / 100).toFixed(2);
}

/** Save is on for a valid price that differs from the stored one, while nothing is in flight. */
export function canSave(state: FolderPriceForm, current: number | null): boolean {
  const cents = parseDollars(state.text);
  return !state.busy && cents !== null && cents !== current;
}

/** Save's body from the form; Clear's (`state` null) posts `price_cents: null`. */
export function buildPayload(accountId: string, ref: string, state: FolderPriceForm | null) {
  return { account_id: accountId, ref, price_cents: state === null ? null : parseDollars(state.text) };
}
