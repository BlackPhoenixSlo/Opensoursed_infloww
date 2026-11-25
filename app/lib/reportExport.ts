import { downloadCsv, saveBlob } from "@/lib/csv";
import { relayFile } from "@/lib/relay";

export type Cell = string | number | null;
export interface Section { title: string; rows: Cell[][] }
export type ExportFormat = "csv" | "xlsx";

export const usd = (cents: number): number => Math.round(cents) / 100;

export function sectionsToRows(sections: Section[]): Cell[][] {
  if (sections.length === 1) return sections[0].rows;
  return sections.flatMap((s, i) => [...(i ? [[]] : []), [s.title], ...s.rows]);
}

export async function exportSections(fileName: string, sheet: string, sections: Section[], format: ExportFormat) {
  const rows = sectionsToRows(sections);
  if (format === "csv") {
    downloadCsv(`${fileName}.csv`, rows.map((r) => r.map((c) => c ?? "")));
    return;
  }
  const { blob } = await relayFile("/admin/stats/xlsx", undefined, { sheet, rows });
  saveBlob(`${fileName}.xlsx`, blob);
}

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
