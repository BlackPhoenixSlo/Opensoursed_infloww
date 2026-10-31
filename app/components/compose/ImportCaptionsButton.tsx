"use client";

/**
 * ImportCaptionsButton — "Import captions" for any text-variant pool: a file
 * (.csv / .txt / .json) or pasted text, parsed by `parseCaptions` and merged by
 * `mergeCaptions` (a lone blank variant is replaced, else appended; dupes of the
 * pool skipped; `max` = the pool's cap). `onImport` gets only the captions that
 * fit; the outcome is toasted. Nothing parsed / nothing fits → toast, no change.
 *
 * Its root is `display: contents`, so in the caller's `flex flex-wrap` row the
 * trigger sits beside "+ add variant" and the open panel wraps onto its own
 * full-width line (no absolute popover to overflow a phone or a modal's scroll).
 */

import { useRef } from "react";

import { Button } from "@/components/ui/primitives";
import { useOutsideClose } from "@/components/ui/Menu";
import { pushNotice } from "@/lib/notices";
import { mergeCaptions, parseCaptions, type MergeResult } from "@/lib/parseCaptions";

const ACCEPT = ".csv,.tsv,.txt,.json,text/*,application/json";

/** The toast line for one import. */
export function importSummary(found: number, r: MergeResult, max?: number): string {
  if (!found) return "No captions found.";
  const parts = [`Imported ${r.added.length} caption${r.added.length === 1 ? "" : "s"}`];
  if (r.dupes) parts.push(`${r.dupes} already there`);
  if (r.dropped) parts.push(`${r.dropped} dropped (limit ${max})`);
  return parts.join(", ") + ".";
}

export function ImportCaptionsButton({ current, onImport, max, className }: {
  /** The pool as it is now (for the blank-replace, dupe and cap counts). */
  current: string[];
  onImport: (items: string[]) => void;
  max?: number;
  /** Trigger classes; default is the small accent link of the "+ add variant" rows. */
  className?: string;
}) {
  const { open, setOpen, ref } = useOutsideClose<HTMLDivElement>();
  const fileRef = useRef<HTMLInputElement>(null);
  const pasteRef = useRef<HTMLTextAreaElement>(null);

  const run = (text: string, filename?: string) => {
    const { items } = parseCaptions(text, { filename });
    const r = mergeCaptions(current, items, max);
    if (r.added.length) onImport(r.added);
    pushNotice({ id: `import-captions:${Date.now()}`, label: "Import captions", text: importSummary(items.length, r, max) });
    setOpen(false);
  };

  const onFile = async (f: File | undefined) => {
    if (!f) return;
    try { run(await f.text(), f.name); }
    catch { pushNotice({ id: `import-captions:${Date.now()}`, label: "Import captions", text: `Couldn't read ${f.name}.` }); }
    if (fileRef.current) fileRef.current.value = "";
  };

  return (
    <div ref={ref} className="contents">
      <button
        type="button"
        aria-haspopup="dialog"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className={className ?? "text-[11px] text-accent hover:underline"}
      >Import captions</button>
      <input
        ref={fileRef}
        type="file"
        accept={ACCEPT}
        aria-label="Caption file"
        data-testid="import-captions-file"
        className="hidden"
        onChange={(e) => void onFile(e.target.files?.[0])}
      />
      {open && (
        <div role="dialog" aria-label="Import captions" className="basis-full">
          <div className="pop-menu origin-top max-w-sm space-y-2 rounded-md border border-border bg-bg p-2 shadow-sm">
            <Button type="button" size="sm" variant="secondary" className="w-full" onClick={() => fileRef.current?.click()}>
              Choose file (.csv, .txt, .json)
            </Button>
            <textarea
              ref={pasteRef}
              rows={4}
              aria-label="Paste captions"
              placeholder="…or paste captions, one per line"
              className="w-full bg-bg border border-border rounded-md px-2 py-1.5 text-base md:text-xs placeholder:text-muted focus:outline-none focus:border-accent resize-y"
            />
            <div className="flex items-center justify-between gap-2">
              <span className="text-[11px] text-fg-dim">{max ? `Up to ${max} variants.` : "Dupes skipped."}</span>
              <Button type="button" size="sm" onClick={() => run(pasteRef.current?.value ?? "")}>Add pasted</Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
