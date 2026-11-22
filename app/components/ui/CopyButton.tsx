"use client";

/** Copy-to-clipboard button that flashes `doneLabel` for `holdMs`, then reads `label` again. Tracking links pass the
 *  bundle's "Link copied" held 5 s; a click during the flash copies nothing. On an insecure origin (no
 *  `navigator.clipboard`) or a blocked write it never says it copied. `className` restyles the ghost Button;
 *  `bare` drops the Button for a plain `<button>` styled by `className` alone (sign-in's 2FA text link, the
 *  Settings IF_BTN). */

import { useState } from "react";

import { Button } from "@/components/ui/primitives";

export function CopyButton({
  text, label = "Copy", doneLabel = "✓ Copied", holdMs = 1200, className, bare = false,
}: { text: string; label?: string; doneLabel?: string; holdMs?: number; className?: string; bare?: boolean }) {
  const [done, setDone] = useState(false);
  const onClick = async () => {
    if (done) return;
    try {
      if (!navigator.clipboard?.writeText) return;   // insecure origin: no fake "Copied"
      await navigator.clipboard.writeText(text);
      setDone(true);
      setTimeout(() => setDone(false), holdMs);
    } catch { /* clipboard blocked */ }
  };
  const shown = done ? doneLabel : label;
  if (bare) return <button type="button" className={className} onClick={onClick} title={text}>{shown}</button>;
  return <Button size="sm" variant="ghost" className={className} onClick={onClick} title={text}>{shown}</Button>;
}
