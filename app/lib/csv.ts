// OWASP CSV-injection start chars; relay csv_export.safe_cell is the same rule
const FORMULA_START = /^[=+\-@\t\r]/;
const INERT = /^([+-]?\d+(\.\d+)?|-)$/;

export function csvField(v: string | number): string {
  let s = String(v);
  if (typeof v === "string" && FORMULA_START.test(s) && !INERT.test(s)) s = `'${s}`;
  return /[",\r\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

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

export function downloadCsv(fileName: string, rows: Array<Array<string | number>>) {
  const lines = rows.map((cells) => cells.map(csvField).join(","));
  saveBlob(fileName, new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8" }));
}
