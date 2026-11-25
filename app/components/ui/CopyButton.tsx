"use client";


import { useState } from "react";

import { Button } from "@/components/ui/primitives";

export function CopyButton({
  text, label = "Copy", doneLabel = "✓ Copied", holdMs = 1200, className, bare = false,
}: { text: string; label?: string; doneLabel?: string; holdMs?: number; className?: string; bare?: boolean }) {
  const [done, setDone] = useState(false);
  const onClick = async () => {
    if (done) return;
    try {
      // insecure origin: no fake "Copied"
      if (!navigator.clipboard?.writeText) return;
      await navigator.clipboard.writeText(text);
      setDone(true);
      setTimeout(() => setDone(false), holdMs);
    } catch { }
  };
  const shown = done ? doneLabel : label;
  if (bare) return <button type="button" className={className} onClick={onClick} title={text}>{shown}</button>;
  return <Button size="sm" variant="ghost" className={className} onClick={onClick} title={text}>{shown}</Button>;
}
