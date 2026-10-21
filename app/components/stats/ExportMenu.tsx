"use client";

/**
 * ExportMenu — the reports' Export pop-up (roadmap W5 5.9), Creator reports' and Employee reports' alike. Infloww's
 * Creator export asks All data fields or Selected fields ("As selected in custom metrics"), Gross or Net, and Display
 * total, by day or both; its Employee export total, daily per employee and by creator (05-analytics M22, W8). The
 * page passes the choices it has and `build`, which shapes the sections from its reads; this downloads them as CSV
 * or Excel (lib/reportExport.ts). Hidden where the role denies Export CSV, as the Relay refuses the Excel form.
 */

import { Upload } from "lucide-react";
import { useState } from "react";

import { useActionAllowed } from "@/components/shell/useGrantedPages";
import { MENU_PANEL, useOutsideClose } from "@/components/ui/Menu";
import { Button } from "@/components/ui/primitives";
import { type ExportFormat, type Section, exportSections } from "@/lib/reportExport";
import { cn } from "@/lib/utils";

export type ExportDisplay = "total" | "day" | "creator";

export interface ExportChoice {
  /** The displays ticked, in the order offered; at least one. */
  displays: ExportDisplay[];
  /** All data fields, else the fields on screen. */
  allFields: boolean;
  /** OnlyFans' own net, else gross. */
  net: boolean;
  format: ExportFormat;
}

const DISPLAY_LABEL: Record<ExportDisplay, string> = {
  total: "Display total", day: "Display by day", creator: "Display by creator",
};
const LEGEND = "text-[11px] uppercase tracking-wide text-fg-dim mb-1";
const OPTION = "flex items-center gap-2 py-0.5 text-xs text-fg";

export default function ExportMenu({ fileName, sheet, displays, fields = false, net, build, className }: {
  /** The download's name, no extension. */
  fileName: string;
  /** The Excel sheet's name. */
  sheet: string;
  /** The displays offered, the first ticked to start. */
  displays: readonly ExportDisplay[];
  /** Offer All data fields / Selected fields. */
  fields?: boolean;
  /** Offer Gross / Net, starting at this basis; no choice without it. */
  net?: boolean;
  build: (choice: ExportChoice) => Section[] | Promise<Section[]>;
  /** The trigger's classes. */
  className?: string;
}) {
  const allowed = useActionAllowed("export");
  const { open, setOpen, ref } = useOutsideClose();
  const [picked, setPicked] = useState<Set<ExportDisplay>>(() => new Set(displays.slice(0, 1)));
  const [allFields, setAllFields] = useState(false);
  const [netPick, setNetPick] = useState<boolean | null>(null);
  const [format, setFormat] = useState<ExportFormat>("csv");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (!allowed) return null;

  const chosen = displays.filter((d) => picked.has(d));
  const toggle = (d: ExportDisplay) => setPicked((prev) => {
    const next = new Set(prev);
    if (next.has(d)) next.delete(d); else next.add(d);
    return next;
  });
  const download = async () => {
    setBusy(true);
    setError(null);
    try {
      const sections = await build({ displays: chosen, allFields, net: netPick ?? net ?? false, format });
      await exportSections(fileName, sheet, sections, format);
      setOpen(false);
    } catch (e) {
      setError((e as Error)?.message || "Export failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div ref={ref} className="relative inline-block text-left">
      <Button type="button" size="sm" variant="secondary" aria-haspopup="dialog" aria-expanded={open}
        onClick={() => setOpen((o) => !o)} className={className}>
        <Upload size={16} aria-hidden />
        Export
      </Button>
      {open && (
        <div role="dialog" aria-label="Export" className={cn(MENU_PANEL, "right-0 w-60 p-3 space-y-3")}>
          {fields && (
            <fieldset>
              <legend className={LEGEND}>Fields</legend>
              <label className={OPTION}>
                <input type="radio" checked={allFields} onChange={() => setAllFields(true)} />All data fields
              </label>
              <label className={OPTION} title="As selected in Custom metrics">
                <input type="radio" checked={!allFields} onChange={() => setAllFields(false)} />Selected fields
              </label>
            </fieldset>
          )}
          {net !== undefined && (
            <fieldset>
              <legend className={LEGEND}>Earnings</legend>
              <label className={OPTION}>
                <input type="radio" checked={!(netPick ?? net)} onChange={() => setNetPick(false)} />Gross
              </label>
              <label className={OPTION}>
                <input type="radio" checked={netPick ?? net} onChange={() => setNetPick(true)} />Net
              </label>
            </fieldset>
          )}
          <fieldset>
            <legend className={LEGEND}>Display</legend>
            {displays.map((d) => (
              <label key={d} className={OPTION}>
                <input type="checkbox" checked={picked.has(d)} onChange={() => toggle(d)} />{DISPLAY_LABEL[d]}
              </label>
            ))}
          </fieldset>
          <fieldset>
            <legend className={LEGEND}>Format</legend>
            <label className={OPTION}>
              <input type="radio" checked={format === "csv"} onChange={() => setFormat("csv")} />CSV
            </label>
            <label className={OPTION}>
              <input type="radio" checked={format === "xlsx"} onChange={() => setFormat("xlsx")} />Excel (.xlsx)
            </label>
          </fieldset>
          {error && <p role="alert" className="text-xs text-err">{error}</p>}
          <Button type="button" size="sm" className="w-full" disabled={busy || chosen.length === 0} onClick={download}>
            {busy ? "Preparing…" : "Download"}
          </Button>
        </div>
      )}
    </div>
  );
}
