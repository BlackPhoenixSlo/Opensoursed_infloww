/**
 * The client CSV download Employee reports' Clocked hours card and modal share, and the Growth links' and the
 * reports' exports.
 */

/** A cell a spreadsheet would run as a formula (OWASP's CSV injection list); a plain number such as "-12.50" is a
 *  number, and the lone "-" the reports write for no figure is text, not one. The Relay's `csv_export.safe_cell` is
 *  the same rule. */
const FORMULA_START = /^[=+\-@\t\r]/;
const INERT = /^([+-]?\d+(\.\d+)?|-)$/;

/** One CSV field: a formula-like string prefixed by a quote so it opens as text, then quoted when it holds a
 *  quote, comma or line break. A number is written as is. */
export function csvField(v: string | number): string {
  let s = String(v);
  if (typeof v === "string" && FORMULA_START.test(s) && !INERT.test(s)) s = `'${s}`;
  return /[",\r\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

/** Saves `blob` as `fileName`; nothing is sent. */
export function saveBlob(fileName: string, blob: Blob) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = fileName;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}

/** Downloads `rows` (the first is the header) as `fileName`. */
export function downloadCsv(fileName: string, rows: Array<Array<string | number>>) {
  const lines = rows.map((cells) => cells.map(csvField).join(","));
  saveBlob(fileName, new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8" }));
}
