"use client";

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
  const handle = useChatMessages({ accountId, fanId });
  const meQ = useQuery(ofMeQuery(accountId));
  const sender = useSendMessage({
    accountId, fanId, hookHandle: handle,
    fromUserId: meQ.data?.id,
    fromUserName: meQ.data?.name ?? meQ.data?.username ?? "you",
  });

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!canSubmit(state)) return;
    // A failed send keeps its bubble; resending retries or replaces it: one bubble, one send per message.
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
