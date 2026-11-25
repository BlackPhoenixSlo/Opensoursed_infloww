"use client";


import { createPortal } from "react-dom";

import { IfButton, IfModal } from "@/components/ui/infloww";
import { useIdleMode } from "@/hooks/useIdleMode";
import { BRAND_NAME } from "@/lib/brand";

const stay = () => {};

export function IdleOverlay() {
  const idle = useIdleMode();
  if (!idle) return null;
  // z-80 on <body> after every open layer: above theirs (z-50/60) and the top modal layer, so keys reach it.
  return createPortal(
    <div className="relative z-[80]">
      <IfModal title={`${BRAND_NAME} has gone idle due to inactivity`} width={416} closable={false} keyboard={false}
        onClose={stay} footer={<IfButton variant="primary">Return to {BRAND_NAME}</IfButton>}>
        <p className="text-fg-dim">Live updates are paused until you return.</p>
      </IfModal>
    </div>,
    document.body,
  );
}
