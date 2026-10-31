"use client";

/**
 * PremadeComposer — modal for the two automation-backed "ready-made" features:
 *
 *   kind="auto_posts"   (P1/P2) — a list of feed posts, sent one by one; each
 *                        optionally auto-deletes after N hours (a self-cleaning
 *                        feed). Submits {posts:[…]}.
 *   kind="mass_premade" (P3)    — a list of ready broadcasts; each can resend
 *                        later and/or auto-unsend on a timer. Submits {messages:[…]}.
 *
 * Unlike MassMessageComposer (which hits /api/of/v2/messages/queue for an
 * immediate send), this enqueues a one-shot automation job via
 * POST /admin/automation/enqueue — the worker runs it on the next tick and
 * chains the follow-up delete/resend jobs itself. The whole list rides in the
 * job payload; the automation drips it out one item at a time.
 *
 * `dry_run` enqueues a plan-only job (no real post/send) — the plan lands in
 * the run's stats on the Automations page.
 */
import type { Kind } from "./premadeRows";
import { PremadeForm } from "./PremadeForm";

export { PremadeForm };

/** Modal wrapper around the shared form — used from the legacy automations surfaces. */
export function PremadeComposer({
  open,
  onClose,
  kind,
}: {
  open: boolean;
  onClose: () => void;
  kind: Kind;
}) {
  if (!open) return null;
  const title =
    kind === "auto_posts"
      ? "Auto Posts (self-cleaning feed)"
      : "Premade Mass (send · resend · unsend)";
  return (
    <div
      className="fixed inset-0 z-50 bg-black/50 grid place-items-center p-0 sm:p-4"
      onClick={onClose}
    >
      {/* min-h-0 / min-w-0: a grid item's auto minimum is its content, so on a
       *  phone (h-full, no max-h) the panel grew past the screen and the body
       *  never scrolled to the footer. Same fix as MassMessageComposer. */}
      <div
        onClick={(e) => e.stopPropagation()}
        className="min-h-0 min-w-0 w-full h-full sm:h-auto max-w-none sm:max-w-[640px] max-h-none sm:max-h-[90vh] flex flex-col bg-panel border-0 sm:border border-border rounded-none sm:rounded-xl shadow-2xl"
      >
        <header className="px-4 py-3 border-b border-border flex items-center justify-between">
          <h2 className="text-sm font-semibold">{title}</h2>
          <button
            type="button"
            onClick={onClose}
            className="text-fg-dim hover:text-fg text-lg leading-none w-11 h-11 -mr-2 -my-2 grid place-items-center shrink-0 md:w-auto md:h-auto md:mr-0 md:my-0 md:inline"
            title="Close"
          >×</button>
        </header>
        <div className="flex-1 overflow-y-auto p-4">
          <PremadeForm kind={kind} onDone={onClose} />
        </div>
      </div>
    </div>
  );
}
