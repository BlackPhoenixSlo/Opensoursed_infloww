"use client";


import { useState } from "react";
import { Download, type LucideIcon } from "lucide-react";

import { IfButton } from "@/components/ui/infloww";
import { useActionAllowed } from "@/components/shell/useGrantedPages";
import { resolveShareToken } from "@/lib/shareToken";

interface Props {
  path: string;
  query: string;
  disabled?: boolean;
  title?: string;
  label?: string;
  icon?: LucideIcon;
}

export default function CsvExportButton({
  path, query, disabled, title = "Download the filtered rows as CSV (up to 50,000 rows)", label = "Export CSV",
  icon: Icon = Download,
}: Props) {
  const [busy, setBusy] = useState(false);
  const allowed = useActionAllowed("export");

  const onClick = () => {
    if (busy || disabled) return;
    setBusy(true);
    try {
      // Native anchor click bypasses the relay wrapper, so the share token is injected here; an anchor streams to disk where fetch().blob() would hold up to 200 MB in JS.
      const tok = resolveShareToken();
      const url = tok
        ? `${path}?${query}&t=${encodeURIComponent(tok)}`
        : `${path}?${query}`;

      const a = document.createElement("a");
      a.href = url;
      a.rel = "noopener";
      a.download = "";
      document.body.appendChild(a);
      a.click();
      a.remove();
    } finally {
      window.setTimeout(() => setBusy(false), 500);
    }
  };

  if (!allowed) return null;
  return (
    <IfButton icon={Icon} onClick={onClick} disabled={disabled || busy} title={title}>
      {label}
    </IfButton>
  );
}
