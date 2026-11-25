"use client";


import { useId, useRef } from "react";

import { IfButton, IfHelp, IfLabel, IfTextArea } from "@/components/ui/infloww";
import { useOutsideClose } from "@/components/ui/Menu";
import { pushNotice } from "@/lib/notices";
import { mergeCaptions, parseCaptions, type MergeResult } from "@/lib/parseCaptions";

const ACCEPT = ".csv,.tsv,.txt,.json,text/*,application/json";

export function importSummary(found: number, r: MergeResult, max?: number): string {
  if (!found) return "No captions found.";
  const parts = [`Imported ${r.added.length} caption${r.added.length === 1 ? "" : "s"}`];
  if (r.dupes) parts.push(`${r.dupes} already there`);
  if (r.dropped) parts.push(`${r.dropped} dropped (limit ${max})`);
  return parts.join(", ") + ".";
}

export function ImportCaptionsButton({ current, onImport, max, className }: {
  current: string[];
  onImport: (items: string[]) => void;
  max?: number;
  className?: string;
}) {
  const { open, setOpen, ref } = useOutsideClose<HTMLDivElement>();
  const triggerRef = useRef<HTMLButtonElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const pasteRef = useRef<HTMLTextAreaElement>(null);
  const pasteId = useId();

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
      <IfButton
        ref={triggerRef}
        variant="link"
        aria-haspopup="dialog"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className={className}
      >Import captions</IfButton>
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
        <div role="dialog" aria-label="Import captions" className="basis-full"
          onKeyDown={(e) => {
            if (e.key !== "Escape") return;
            // Escape closes this panel only: the modal skips a defaultPrevented Escape (useModalFocus)
            e.preventDefault();
            setOpen(false);
            triggerRef.current?.focus();
          }}>
          <div className="pop-menu origin-top max-w-sm space-y-3 rounded-md border border-border bg-bg p-3 text-[14px] text-fg shadow-sm">
            <IfButton className="w-full" onClick={() => fileRef.current?.click()}>
              Choose file (.csv, .txt, .json)
            </IfButton>
            <div>
              <IfLabel htmlFor={pasteId}>Or paste captions</IfLabel>
              <IfTextArea
                id={pasteId}
                ref={pasteRef}
                rows={4}
                aria-label="Paste captions"
                placeholder="One per line"
              />
              <IfHelp>{max ? `Up to ${max} variants; dupes skipped.` : "Dupes skipped."}</IfHelp>
            </div>
            <div className="flex justify-end">
              <IfButton variant="primary" onClick={() => run(pasteRef.current?.value ?? "")}>Add pasted</IfButton>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
