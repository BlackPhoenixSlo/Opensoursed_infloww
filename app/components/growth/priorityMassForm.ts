/**
 * priorityMassForm — the Priority mass message composer's one state: the
 * audience (audienceReducer, delegated as is) plus the message content.
 *
 *   • A real account switch resets the audience only (audienceReducer); the
 *     text, media and price stay.
 *   • `launchError` is the one "can this go" check, in the order the user
 *     sees the reasons; `buildPayload` the POST body.
 */

import type { VaultMedia } from "@/lib/relay";
import { SENSITIVE_BLOCK_MESSAGE } from "@/lib/sensitiveWords";
import {
  audienceError, audienceReducer, buildAudiencePayload, initAudience,
  type AudienceAction, type AudienceState,
} from "@/components/audience/audienceReducer";

export interface PriorityMassState extends AudienceState {
  text: string;
  attached: VaultMedia[];
  /** The price input as typed (sanitized). */
  price: string;
  previewCount: number;
  lockedText: boolean;
}

export type PriorityMassAction =
  | AudienceAction
  | { type: "setText"; text: string }
  | { type: "setAttached"; attached: VaultMedia[] }
  | { type: "setPrice"; price: string }
  | { type: "setPreviewCount"; n: number }
  | { type: "setLockedText"; on: boolean };

export function initPriorityMass(accountId: string | null): PriorityMassState {
  return { ...initAudience(accountId), text: "", attached: [], price: "", previewCount: 0, lockedText: false };
}

export function priorityMassReducer(s: PriorityMassState, a: PriorityMassAction): PriorityMassState {
  switch (a.type) {
    case "setText": return { ...s, text: a.text };
    case "setAttached": return { ...s, attached: a.attached };
    case "setPrice": return { ...s, price: a.price };
    case "setPreviewCount": return { ...s, previewCount: a.n };
    case "setLockedText": return { ...s, lockedText: a.on };
    default: return audienceReducer(s, a);
  }
}

export const numericPrice = (s: Pick<PriorityMassState, "price">): number => Number(s.price) || 0;

/** Why this can't launch, or null when it can. `sensitive`: the text has blocked words. */
export function launchError(s: PriorityMassState, sensitive: boolean): string | null {
  if (sensitive) return SENSITIVE_BLOCK_MESSAGE;
  if (!s.accountId) return "Pick a Creator.";
  if (!s.text.trim() && s.attached.length === 0) return "Add a text or media.";
  const audErr = audienceError(s);
  if (audErr) return audErr;
  if (numericPrice(s) > 0 && s.attached.length === 0) return "A priced message needs media.";
  return null;
}

/** The `POST /admin/priority-mass/runs` body. */
export function buildPayload(s: PriorityMassState) {
  const price = numericPrice(s);
  return {
    account_id: s.accountId,
    text: s.text.trim(),
    media_files: s.attached.map((m) => m.id),
    previews: price > 0 ? s.attached.slice(0, s.previewCount).map((m) => m.id) : [],
    price,
    locked_text: price > 0 && s.lockedText,
    ...buildAudiencePayload(s),
  };
}
