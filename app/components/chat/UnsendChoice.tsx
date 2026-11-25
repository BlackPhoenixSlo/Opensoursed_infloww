"use client";


import { useCallback, useRef, useState, type ReactNode } from "react";

import { useActionAllowed } from "@/components/shell/useGrantedPages";
import { IfButton, IfModal } from "@/components/ui/infloww";
import type { OFMessage } from "@/lib/relay";
import type { useUnsendMessage } from "@/hooks/useUnsendMessage";
import { errText } from "@/lib/errText";
import { ifAlert, ifConfirm } from "@/components/ui/ifConfirm";

export type UnsendScope = "chat" | "all";
type Unsender = Pick<ReturnType<typeof useUnsendMessage>, "unsendOne" | "unsendQueue">;

export function useUnsendChoice(unsender: Unsender): { onUnsend: ((msg: OFMessage) => void) | undefined; dialog: ReactNode } {
  const allowed = useActionAllowed("unsend");
  const queueAllowed = useActionAllowed("mass-message");
  const promptedQueuesRef = useRef<Set<number>>(new Set());
  const [ask, setAsk] = useState<OFMessage | null>(null);

  const run = useCallback(async (msg: OFMessage, scope: UnsendScope | null) => {
    let resp: Awaited<ReturnType<Unsender["unsendOne"]>> = null;
    try {
      resp = await unsender.unsendOne(msg);
    } catch (err) {
      const reason = errText(err);
      await ifAlert(`Couldn't unsend: ${reason}`);
      return;
    }
    if (scope === "chat" || !queueAllowed) return;
    const queue = resp?.queue;
    if (!queue?.id) {
      if (scope === "all") await ifAlert("Unsent from this conversation only: OF returned no mass send to unsend for all recipients.");
      return;
    }
    const open = !queue.isCanceled && queue.canUnsend !== false;
    if (scope === "all") {
      if (!open) {
        await ifAlert("Unsent from this conversation only: OF no longer lets this mass send be unsent for all recipients.");
        return;
      }
    } else {
      if (promptedQueuesRef.current.has(queue.id)) return;
      promptedQueuesRef.current.add(queue.id);
      if (!open) return;
      const total = queue.sentCount ?? 0;
      const viewed = queue.viewedCount ?? 0;
      const summary = total
        ? `Sent to ${total} fan${total === 1 ? "" : "s"}${viewed ? `, ${viewed} viewed` : ""}.`
        : "";
      if (!(await ifConfirm(`This message was part of a mass send. ${summary} Also unsend it for all recipients?`, { danger: true }))) return;
    }
    try {
      await unsender.unsendQueue(queue.id);
    } catch (err) {
      const reason = errText(err);
      await ifAlert(`Mass-unsend failed: ${reason}`);
    }
  }, [unsender, queueAllowed]);

  const onUnsend = useCallback(async (msg: OFMessage) => {
    const id = Number(msg.id);
    if (!Number.isFinite(id) || id <= 0) return;
    if (queueAllowed && msg.isFromQueue && msg.canUnsendQueue !== false) {
      setAsk(msg);
      return;
    }
    if (!(await ifConfirm("Unsend this message from this chat? OF allows this within ~24h.", { danger: true }))) return;
    void run(msg, null);
  }, [run, queueAllowed]);

  const cancel = useCallback(() => setAsk(null), []);
  const dialog = ask && (
    <UnsendChoiceDialog
      onChoose={(scope) => {
        setAsk(null);
        void run(ask, scope);
      }}
      onCancel={cancel}
    />
  );
  return { onUnsend: allowed ? onUnsend : undefined, dialog };
}

function UnsendChoiceDialog({
  onChoose, onCancel,
}: {
  onChoose: (scope: UnsendScope) => void;
  onCancel: () => void;
}) {
  const [scope, setScope] = useState<UnsendScope>("chat");

  const option = (value: UnsendScope, label: string) => (
    <label className="flex cursor-pointer items-center gap-2">
      <input type="radio" name="unsend-scope" checked={scope === value} onChange={() => setScope(value)}
        className="h-4 w-4 accent-accent" />
      <span>{label}</span>
    </label>
  );

  return (
    <IfModal title="Unsend message" onClose={onCancel}
      footer={
        <>
          <IfButton onClick={onCancel}>Cancel</IfButton>
          <IfButton variant="primary" className="bg-err hover:bg-err/90" onClick={() => onChoose(scope)}>Unsend</IfButton>
        </>
      }>
      <p className="text-fg-dim">This message was part of a mass send. OF allows unsending within ~24h.</p>
      <div className="mt-4 flex flex-col gap-3">
        {option("chat", "Unsend from this conversation")}
        {option("all", "Unsend for all recipients")}
      </div>
    </IfModal>
  );
}
