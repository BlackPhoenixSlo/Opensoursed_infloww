import type { SendSettled } from "@/hooks/useSendMessage";

export type QuickReplyOutcome = { ok: true } | { ok: false; reason: string };

export interface QuickReplyState {
  text: string;
  sending: boolean;
  outcome: QuickReplyOutcome | null;
  failed: { tempId: number; text: string } | null;
}

export type QuickReplyAction =
  | { type: "type"; text: string }
  | { type: "submit" }
  | { type: "settled"; outcome: QuickReplyOutcome; tempId?: number }
  | { type: "done" }
  | { type: "busy" };

export const QUICK_REPLY_EMPTY: QuickReplyState = { text: "", sending: false, outcome: null, failed: null };

export function quickReplyReducer(s: QuickReplyState, a: QuickReplyAction): QuickReplyState {
  switch (a.type) {
    case "type":
      return s.sending ? s : { ...s, text: a.text };
    case "submit":
      return canSubmit(s) ? { ...s, sending: true, outcome: null } : s;
    case "settled":
      if (a.outcome.ok) return { text: "", sending: false, outcome: a.outcome, failed: null };
      return {
        text: s.text, sending: false, outcome: a.outcome,
        failed: a.tempId == null ? null : { tempId: a.tempId, text: buildPayload(s).text },
      };
    case "done":
      return QUICK_REPLY_EMPTY;
    case "busy":
      return { ...s, outcome: { ok: false, reason: BUSY_REASON } };
  }
}

export const BUSY_REASON = "Already sending from the chat.";

export const canSubmit = (s: QuickReplyState) => !s.sending && s.text.trim() !== "";

export const buildPayload = (s: QuickReplyState) => ({ text: s.text.trim() });

export type QuickReplyPlan =
  | { kind: "send"; payload: { text: string } }
  | { kind: "retry"; tempId: number }
  | { kind: "replace"; tempId: number; payload: { text: string } }
  | { kind: "done" }
  | { kind: "busy" };

export interface FailedBubble { stashed: boolean; delivered: boolean; pending: boolean }

export function planSubmit(s: QuickReplyState, bubble: FailedBubble): QuickReplyPlan {
  const payload = buildPayload(s);
  if (!s.failed) return { kind: "send", payload };
  const same = s.failed.text === payload.text;
  if (bubble.pending) return same ? { kind: "busy" } : { kind: "send", payload };
  if (bubble.stashed) return same ? { kind: "retry", tempId: s.failed.tempId } : { kind: "replace", tempId: s.failed.tempId, payload };
  if (bubble.delivered && same) return { kind: "done" };
  return { kind: "send", payload };
}

export type SendEnded = SendSettled | undefined | { error: unknown };

export function outcomeOf(ended: SendEnded): QuickReplyOutcome {
  if (ended && "sent" in ended && ended.sent) return { ok: true };
  if (ended && "error" in ended) {
    return { ok: false, reason: (ended.error instanceof Error && ended.error.message) || "Send failed." };
  }
  return { ok: false, reason: (ended && !ended.sent && ended.failure?.reason) || "Send failed." };
}
