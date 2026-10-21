"use client";

/**
 * CsvExportButton — server-streamed CSV download for a Relay route's
 * `format=csv` form: the messages list (`/admin/paid-messages`), Sales
 * records (`/admin/stats/sales-records`), Fan reports' Top fans
 * (`/admin/stats/fan-report`), the Tips tab (`/admin/tips-list`) and Top
 * tippers (`/admin/top-tippers`). The caller builds the path and its query
 * string, `format=csv` included. `look="infloww"` draws Infloww's outline
 * button (`IfButton`) with the caller's label and glyph; the default is our
 * secondary button.
 *
 * Why an `<a download>` anchor click, NOT fetch().blob():
 *   • fetch().blob() materializes the whole body in JS memory before
 *     handing it to URL.createObjectURL. At the 50k row cap the file is
 *     50-200 MB; the tab will GC-stall or OOM on a tight machine.
 *   • An anchor `download` click pipes the response straight to disk via
 *     the browser's native downloader, which already handles streamed
 *     `Content-Disposition: attachment`. Zero JS allocation regardless
 *     of file size.
 *
 * Trade-off: we can't read `X-Row-Count` from a native download (the
 * response never enters JS). The backend always emits `X-Row-Count` =
 * the cap (50000), so the toast warning would be a false positive 99%
 * of the time. We rely on the inline `# TRUNCATED` sentinel row in the
 * file instead — Excel/Numbers shows it on the last line.
 */

import { useState } from "react";
import { Download, type LucideIcon } from "lucide-react";

import { IfButton } from "@/components/ui/infloww";
import { Button } from "@/components/ui/primitives";
import { useActionAllowed } from "@/components/shell/useGrantedPages";
import { resolveShareToken } from "@/lib/shareToken";

interface Props {
  /** The Relay route, e.g. `/admin/paid-messages`. */
  path: string;
  /** Its query string (no leading `?`), `format=csv` included. */
  query: string;
  /** Disabled while date range isn't populated. */
  disabled?: boolean;
  /** Tooltip; a generic one when absent.
   *  ASSUMPTION: the message tabs keep the default, so their tooltip now says "rows", not "messages". Rung 5.
   *  Overturned if those tabs should name messages again (pass `title`). */
  title?: string;
  /** The button's text; "Export CSV" when absent. */
  label?: string;
  /** The glyph before it; the download arrow when absent. */
  icon?: LucideIcon;
  /** `infloww`: Infloww's outline button (the Analytics pages); `legacy` (the default): ours. */
  look?: "legacy" | "infloww";
}

export default function CsvExportButton({
  path, query, disabled, title = "Download the filtered rows as CSV (up to 50,000 rows)", label = "Export CSV",
  icon: Icon = Download, look = "legacy",
}: Props) {
  const [busy, setBusy] = useState(false);
  // Hidden where the role denies this page's Export CSV (lib/permissionActions.ts).
  const allowed = useActionAllowed("export");

  const onClick = () => {
    if (busy || disabled) return;
    setBusy(true);
    try {
      // Inject share-token at the URL level — the caller's query doesn't
      // know about it (relay.ts owns that), but the native anchor click
      // bypasses the relay wrapper.
      const tok = resolveShareToken();
      const url = tok
        ? `${path}?${query}&t=${encodeURIComponent(tok)}`
        : `${path}?${query}`;

      const a = document.createElement("a");
      a.href = url;
      a.rel = "noopener";
      // Empty string lets the server's Content-Disposition pick the name.
      a.download = "";
      document.body.appendChild(a);
      a.click();
      a.remove();
    } finally {
      // The click is synchronous; busy is just a momentary debounce so
      // a double-click doesn't fire two downloads.
      window.setTimeout(() => setBusy(false), 500);
    }
  };

  if (!allowed) return null;
  if (look === "infloww") {
    return (
      <IfButton icon={Icon} onClick={onClick} disabled={disabled || busy} title={title}>
        {label}
      </IfButton>
    );
  }
  return (
    <Button
      type="button"
      variant="secondary"
      size="sm"
      onClick={onClick}
      disabled={disabled || busy}
      title={title}
    >
      <Icon size={14} className="inline-block mr-1" aria-hidden />
      {busy ? "Starting…" : label}
    </Button>
  );
}
