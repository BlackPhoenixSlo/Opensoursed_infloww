/**
 * The reports' exports (roadmap W5 5.9; Infloww's export pop-ups, 05-analytics M22/W8): Creator reports and
 * Employee reports build their sections from the reads already on screen (the by-day ones from one more read) and
 * download them as CSV, or as Excel through `POST /admin/stats/xlsx`, which writes the rows sent and reads
 * nothing. Infloww emails its exports; ours download at once.
 */

import { downloadCsv, saveBlob } from "@/lib/csv";
import { relayFile } from "@/lib/relay";

export type Cell = string | number | null;
/** A titled table: its header row first. */
export interface Section { title: string; rows: Cell[][] }
export type ExportFormat = "csv" | "xlsx";

/** Money cents as dollars, a number to the cent (a number cell in Excel). */
export const usd = (cents: number): number => Math.round(cents) / 100;

/** One sheet of `sections`: a lone section is its own rows; several each get a title line, a blank line between. */
export function sectionsToRows(sections: Section[]): Cell[][] {
  if (sections.length === 1) return sections[0].rows;
  return sections.flatMap((s, i) => [...(i ? [[]] : []), [s.title], ...s.rows]);
}

/** Downloads `sections` as `<fileName>.csv` or `.xlsx`, `sheet` naming the Excel sheet. */
export async function exportSections(fileName: string, sheet: string, sections: Section[], format: ExportFormat) {
  const rows = sectionsToRows(sections);
  if (format === "csv") {
    downloadCsv(`${fileName}.csv`, rows.map((r) => r.map((c) => c ?? "")));
    return;
  }
  const { blob } = await relayFile("/admin/stats/xlsx", undefined, { sheet, rows });
  saveBlob(`${fileName}.xlsx`, blob);
}

/** `fn` over `items`, at most `limit` at a time, the answers in order: the by-day reads, one per Creator or day. */
export async function mapLimit<T, R>(items: readonly T[], limit: number, fn: (item: T) => Promise<R>): Promise<R[]> {
  const out: R[] = new Array(items.length);
  let next = 0;
  const worker = async () => {
    while (next < items.length) {
      const i = next++;
      out[i] = await fn(items[i]);
    }
  };
  await Promise.all(Array.from({ length: Math.min(limit, items.length) }, worker));
  return out;
}
