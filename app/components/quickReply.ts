/** The bell's quick reply field (NotificationQuickReply) as one state: the line typed, a send in flight, how the
 *  last one ended, and its failed bubble (if any) with the line it carries. Pure, so the component only dispatches. */
import type { SendSettled } from "@/hooks/useSendMessage";

export type QuickReplyOutcome = { ok: true } | { ok: false; reason: string };

export interface QuickReplyState {
  text: string;
  sending: boolean;
  outcome: QuickReplyOutcome | null;
  /** The last failed send's bubble (still in the thread, flagged failed) and the line it carries: the next
   *  submit retries or replaces it rather than leaving it behind to be re-sent later. */
  failed: { tempId: number; text: string } | null;
}

export type QuickReplyAction =
  | { type: "type"; text: string }
  | { type: "submit" }
  /** `tempId`: the bubble the attempt used (none when it threw before one showed). */
  | { type: "settled"; outcome: QuickReplyOutcome; tempId?: number }
  /** The failed line went out from the Thread meanwhile: nothing to send, the field clears. */
  | { type: "done" }
  /** The failed line is being re-sent from the Thread right now: no second send. */
  | { type: "busy" };

export const QUICK_REPLY_EMPTY: QuickReplyState = { text: "", sending: false, outcome: null, failed: null };

export function quickReplyReducer(s: QuickReplyState, a: QuickReplyAction): QuickReplyState {
  switch (a.type) {
    case "type":
      return s.sending ? s : { ...s, text: a.text };
    case "submit":
      return canSubmit(s) ? { ...s, sending: true, outcome: null } : s;
    case "settled":
      // A sent line clears; a failed one stays for another try, its bubble remembered.
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

/** The failed bubble as the Thread has it now: still in the send stash (failed, retryable), delivered (sent since,
 *  e.g. by the Thread's Retry; per sendStash.delivered) and pending (a Thread Retry in flight). */
export interface FailedBubble { stashed: boolean; delivered: boolean; pending: boolean }

/** What a submit does, so each intended message is one bubble and one send: the failed bubble's own line again
 *  retries it, another line drops it and sends anew. If the Thread got there first: a Retry in flight → no send
 *  (busy); the line delivered → same line is done, another is a plain send; the bubble neither stashed nor
 *  delivered (discarded) → a plain send. */
export function planSubmit(s: QuickReplyState, bubble: FailedBubble): QuickReplyPlan {
  const payload = buildPayload(s);
  if (!s.failed) return { kind: "send", payload };
  const same = s.failed.text === payload.text;
  if (bubble.pending) return same ? { kind: "busy" } : { kind: "send", payload };
  if (bubble.stashed) return same ? { kind: "retry", tempId: s.failed.tempId } : { kind: "replace", tempId: s.failed.tempId, payload };
  if (bubble.delivered && same) return { kind: "done" };
  return { kind: "send", payload };
}

/** A send's end as the field reads it: settled, refused (undefined) or thrown. */
export type SendEnded = SendSettled | undefined | { error: unknown };

/** How a send ended, as the field says it: only a send that went out is "Sent"; refused (no outcome), failed,
 *  discarded mid-way or thrown is not. */
export function outcomeOf(ended: SendEnded): QuickReplyOutcome {
  if (ended && "sent" in ended && ended.sent) return { ok: true };
  if (ended && "error" in ended) {
    return { ok: false, reason: (ended.error instanceof Error && ended.error.message) || "Send failed." };
  }
  return { ok: false, reason: (ended && !ended.sent && ended.failure?.reason) || "Send failed." };
}
