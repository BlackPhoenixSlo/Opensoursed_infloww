"use client";

/** The bell's quick reply to a message notification (NotificationBell's QuickReply): a line sent to the Fan's chat
 *  through the Thread's send hook. Its own module so the hooks stay out of the shell's first load. */
import { useState, type FormEvent } from "react";

import { useChatMessages } from "@/hooks/useChatMessages";
import { useSendMessage } from "@/hooks/useSendMessage";
import type { FanId } from "@/lib/fanId";

export function QuickReplyField({ accountId, fanId, name }: { accountId: string; fanId: FanId; name: string }) {
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const [outcome, setOutcome] = useState<{ ok: true } | { ok: false; reason: string } | null>(null);
  const handle = useChatMessages({ accountId, fanId });
  const sender = useSendMessage({ accountId, fanId, hookHandle: handle });

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const body = text.trim();
    if (!body || sending) return;
    setSending(true);
    setOutcome(null);
    const result = await sender.send({ text: body });
    setSending(false);
    if (!result || result.failure) {
      // The field is where this reply is retried: the failed bubble's Retry
      // in the Thread belongs to another instance of the hook, which holds
      // no copy of this send, so the bubble goes.
      if (result) sender.cancelOptimistic(result.tempId);
      setOutcome({ ok: false, reason: result?.failure?.reason || "Send failed." });
    } else {
      setText("");
      setOutcome({ ok: true });
    }
  };

  return (
    <form onSubmit={submit} className="mt-1 flex flex-col gap-1">
      <div className="flex gap-1.5">
        <input
          type="text"
          aria-label={`Reply to ${name}`}
          value={text}
          onChange={(e) => setText(e.target.value)}
          disabled={sending}
          className="min-w-0 flex-1 h-8 px-2 rounded-md border border-border bg-bg-elev-1 text-xs text-fg"
        />
        <button
          type="submit"
          disabled={sending || !text.trim()}
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
