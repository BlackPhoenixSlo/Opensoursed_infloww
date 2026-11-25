import type { OFMessage } from "@/lib/relay";

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

export function bubbleBox(container: HTMLElement, id: number | string): HTMLElement {
  const el = container.querySelector(`[data-msg-id="${id}"]`);
  if (!el) throw new Error(`no bubble for msg ${id}`);
  return el as HTMLElement;
}

export function timeRow(container: HTMLElement, id: number | string): HTMLElement | null {
  const next = bubbleBox(container, id).nextElementSibling;
  return next?.hasAttribute("data-time-row") ? (next as HTMLElement) : null;
}
