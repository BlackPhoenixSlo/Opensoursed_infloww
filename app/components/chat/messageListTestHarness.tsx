/**
 * The helpers the `MessageList` render suites share (`MessageList.test.tsx`
 * and `MessageList.timeRow.test.tsx`): a synthetic message builder, the list's
 * base props, and lookups for a bubble box and the time row under it.
 *
 * The relay mock stays in `composerTestHarness`; vi.mock is hoisted per test
 * file, so each suite declares it itself. This module imports only types from
 * `@/lib/relay`.
 */
import type { OFMessage } from "@/lib/relay";

/** A message as the DB seeds it: an explicit `_side` off `direction`. */
export type SeedMsg = OFMessage & { _side?: "left" | "right" };

export function msg(over: Partial<SeedMsg> & { id: number | string }): OFMessage {
  return {
    text: "",
    fromUser: { id: 0 },
    createdAt: "2026-06-04T12:00:00.000Z",
    media: [],
    ...over,
  } as OFMessage;
}

export const baseProps = {
  accountId: "acct1",
  isLoading: false,
  isError: false,
  hasOlder: false,
  loadingOlder: false,
  onLoadOlder: () => {},
  onRetry: () => {},
};

/** The inner bubble box, the element carrying `data-msg-id`. */
export function bubbleBox(container: HTMLElement, id: number | string): HTMLElement {
  const el = container.querySelector(`[data-msg-id="${id}"]`);
  if (!el) throw new Error(`no bubble for msg ${id}`);
  return el as HTMLElement;
}

/** The time row under a bubble (Part C): the bubble box's next sibling in
 *  its column, when that carries `data-time-row`. */
export function timeRow(container: HTMLElement, id: number | string): HTMLElement | null {
  const next = bubbleBox(container, id).nextElementSibling;
  return next?.hasAttribute("data-time-row") ? (next as HTMLElement) : null;
}
