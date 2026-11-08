"use client";

/** The bell's quick reply to a message notification (NotificationBell's QuickReply): a line sent to the Fan's chat
 *  through the Thread's send hook. Its own module so the hooks stay out of the shell's first load. */
import { useReducer, type FormEvent } from "react";
import { useQuery } from "@tanstack/react-query";

import {
  canSubmit, outcomeOf, planSubmit, QUICK_REPLY_EMPTY, quickReplyReducer, type SendEnded,
} from "@/components/quickReply";
import { useChatMessages } from "@/hooks/useChatMessages";
import { useSendMessage } from "@/hooks/useSendMessage";
import type { FanId } from "@/lib/fanId";
import { ofMeQuery } from "@/lib/ofMe";
import { sendStash } from "@/lib/sendStash";

export function QuickReplyField({ accountId, fanId, name }: { accountId: string; fanId: FanId; name: string }) {
  const [state, dispatch] = useReducer(quickReplyReducer, QUICK_REPLY_EMPTY);
  // Enabled: the thread read is what keeps the optimistic write from dating a cold thread fresh with one row.
  const handle = useChatMessages({ accountId, fanId });
  // The Creator's own OF user: the bubble's sender, so it sits on our side.
  const meQ = useQuery(ofMeQuery(accountId));
  const sender = useSendMessage({
    accountId, fanId, hookHandle: handle,
    fromUserId: meQ.data?.id,
    fromUserName: meQ.data?.name ?? meQ.data?.username ?? "you",
  });

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!canSubmit(state)) return;
    // A failed send keeps its bubble, flagged failed, in the Fan's thread: the inbox row already reads as our
    // reply, and the bubble's Retry (the send stash is shared) is the trace that it didn't go. Sending again
    // from here retries that bubble (same line) or replaces it (new line): one bubble, one send per message.
    // The Thread may have got there first: the send stash says whether the bubble is still retryable or went out;
    // its cached row whether a Thread Retry is sending it now.
    const id = state.failed?.tempId;
    const plan = planSubmit(state, {
      stashed: id != null && sendStash.get(id) !== undefined,
      delivered: id != null && sendStash.delivered(id),
      pending: id != null && !!handle.data?.find((m) => m._tempId === id)?._pending,
    });
    if (plan.kind === "done" || plan.kind === "busy") return dispatch({ type: plan.kind });
    dispatch({ type: "submit" });
    let ended: SendEnded;
    let tempId: number | undefined = plan.kind === "retry" ? plan.tempId : undefined;
    try {
      if (plan.kind === "retry") {
        ended = await sender.retry(plan.tempId);
      } else {
        if (plan.kind === "replace") sender.cancelOptimistic(plan.tempId);
        const result = await sender.send(plan.payload);
        tempId = result?.tempId;
        ended = result ? await result.settled : undefined;
      }
    } catch (error) {
      ended = { error };
    }
    dispatch({ type: "settled", outcome: outcomeOf(ended), tempId });
  };

  const { text, sending, outcome } = state;
  return (
    <form onSubmit={submit} className="mt-1 flex flex-col gap-1">
      <div className="flex gap-1.5">
        <input
          type="text"
          aria-label={`Reply to ${name}`}
          value={text}
          onChange={(e) => dispatch({ type: "type", text: e.target.value })}
          disabled={sending}
          className="min-w-0 flex-1 h-8 px-2 rounded-md border border-border bg-bg-elev-1 text-xs text-fg"
        />
        <button
          type="submit"
          disabled={!canSubmit(state)}
          className="h-8 px-3 rounded-md bg-accent text-white text-xs font-semibold disabled:opacity-50"
        >
          Send
        </button>
      </div>
      {outcome?.ok && <div role="status" className="text-xs text-ok">Sent</div>}
      {outcome && !outcome.ok && <div role="alert" className="text-xs text-err">{outcome.reason}</div>}
    </form>
  );
}
