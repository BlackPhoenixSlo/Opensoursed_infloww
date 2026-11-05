"use client";

/**
 * IdleOverlay — what the window shows in Idle mode (`useIdleMode`): Infloww's
 * full-screen "has gone idle due to inactivity" with its Return button. Any
 * input leaves Idle mode, the button included.
 */

import { createPortal } from "react-dom";

import { IfButton, IfModal } from "@/components/ui/infloww";
import { useIdleMode } from "@/hooks/useIdleMode";
import { BRAND_NAME } from "@/lib/brand";

const stay = () => {};

export function IdleOverlay() {
  const idle = useIdleMode();
  if (!idle) return null;
  return createPortal(
    // Over every other modal (theirs are z-50/60): the wrapper lifts IfModal's mask. On <body>, after every layer
    // open under it, so it is also the top modal layer (keys go to it, not to a portaled picker under it).
    <div className="relative z-[80]">
      <IfModal title={`${BRAND_NAME} has gone idle due to inactivity`} width={416} closable={false} keyboard={false}
        onClose={stay} footer={<IfButton variant="primary">Return to {BRAND_NAME}</IfButton>}>
        <p className="text-fg-dim">Live updates are paused until you return.</p>
      </IfModal>
    </div>,
    document.body,
  );
}
