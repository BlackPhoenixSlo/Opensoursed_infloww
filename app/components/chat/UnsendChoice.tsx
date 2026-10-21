"use client";

/**
 * Unsend from the Thread (ChatSurface's `onUnsend`). A bubble that went out
 * in a mass send, while OF still lets that queue be unsent, asks the scope up
 * front, as Infloww does (04-messages-pro.md P3): "Unsend from this
 * conversation" (the default) or "Unsend for all recipients". Any other
 * bubble keeps the one confirm, and when OF's reply still names a live queue
 * it gets the follow-up "Also unsend it for all recipients?" (once per queue).
 *
 * The calls are unchanged (`useUnsendMessage`): the per-chat DELETE, then,
 * for all recipients, the DELETE of the queue OF echoes back.
 *
 * A role denied "unsend" gets no `onUnsend` (the bubble shows no Unsend); one
 * denied "mass-message" unsends from this chat only, never asked about the
 * queue (its DELETE is a mass-message action).
 */

import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";

import { useActionAllowed } from "@/components/shell/useGrantedPages";
import type { OFMessage } from "@/lib/relay";
import type { useUnsendMessage } from "@/hooks/useUnsendMessage";

export type UnsendScope = "chat" | "all";
type Unsender = Pick<ReturnType<typeof useUnsendMessage>, "unsendOne" | "unsendQueue">;

/** `onUnsend` for the Thread, and the scope dialog to render while it asks. */
export function useUnsendChoice(unsender: Unsender): { onUnsend: ((msg: OFMessage) => void) | undefined; dialog: ReactNode } {
  const allowed = useActionAllowed("unsend");
  const queueAllowed = useActionAllowed("mass-message");
  // Queue ids already offered the follow-up in this session — unsending
  // several bubbles of one broadcast prompts once.
  const promptedQueuesRef = useRef<Set<number>>(new Set());
  const [ask, setAsk] = useState<OFMessage | null>(null);

  /** `scope` is the dialog's choice; null when the bubble was not known as
   *  mass-sent, so a queue OF echoes gets the follow-up confirm. */
  const run = useCallback(async (msg: OFMessage, scope: UnsendScope | null) => {
    let resp: Awaited<ReturnType<Unsender["unsendOne"]>> = null;
    try {
      resp = await unsender.unsendOne(msg);
    } catch (err) {
      const reason = err instanceof Error ? err.message : String(err);
      window.alert(`Couldn't unsend: ${reason}`);
      return;
    }
    if (scope === "chat" || !queueAllowed) return;
    // A `queue` block means a mass message; it can go for all recipients
    // only while OF says so (canUnsend, not yet canceled).
    const queue = resp?.queue;
    if (!queue?.id) {
      if (scope === "all") window.alert("Unsent from this conversation only: OF returned no mass send to unsend for all recipients.");
      return;
    }
    const open = !queue.isCanceled && queue.canUnsend !== false;
    if (scope === "all") {
      if (!open) {
        window.alert("Unsent from this conversation only: OF no longer lets this mass send be unsent for all recipients.");
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
      if (!window.confirm(`This message was part of a mass send. ${summary} Also unsend it for all recipients?`)) return;
    }
    try {
      await unsender.unsendQueue(queue.id);
    } catch (err) {
      const reason = err instanceof Error ? err.message : String(err);
      window.alert(`Mass-unsend failed: ${reason}`);
    }
  }, [unsender, queueAllowed]);

  const onUnsend = useCallback((msg: OFMessage) => {
    const id = Number(msg.id);
    if (!Number.isFinite(id) || id <= 0) return;
    if (queueAllowed && msg.isFromQueue && msg.canUnsendQueue !== false) {
      setAsk(msg);
      return;
    }
    if (!window.confirm("Unsend this message from this chat? OF allows this within ~24h.")) return;
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

/** The scope dialog: two options, this conversation preselected; Escape or
 *  a click on the backdrop cancels. */
function UnsendChoiceDialog({
  onChoose, onCancel,
}: {
  onChoose: (scope: UnsendScope) => void;
  onCancel: () => void;
}) {
  const [scope, setScope] = useState<UnsendScope>("chat");

  // Mounted only while it asks. A `document` listener runs before the
  // `window` ones of Find (`ChatSearch`) and the overlay Fan insights, and
  // stops the key there (as `ChatGallery`), so one Escape closes only this.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      e.stopPropagation();
      onCancel();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onCancel]);

  const option = (value: UnsendScope, label: string) => (
    <label className="flex items-center gap-2 cursor-pointer">
      <input type="radio" name="unsend-scope" checked={scope === value} onChange={() => setScope(value)} />
      <span>{label}</span>
    </label>
  );

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/50" onClick={onCancel}>
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Unsend message"
        className="w-80 max-w-full rounded-lg border border-border bg-panel p-4 text-fg shadow-2xl space-y-3"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="font-semibold">Unsend message</div>
        <div className="text-fg-dim">This message was part of a mass send. OF allows unsending within ~24h.</div>
        {option("chat", "Unsend from this conversation")}
        {option("all", "Unsend for all recipients")}
        <div className="flex justify-end gap-3">
          <button type="button" onClick={onCancel} className="text-fg-dim hover:text-fg">Cancel</button>
          <button type="button" onClick={() => onChoose(scope)} className="text-err">Unsend</button>
        </div>
      </div>
    </div>
  );
}
