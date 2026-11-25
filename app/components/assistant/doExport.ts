export type ExportFormat = "csv" | "xlsx";

export interface ExportSlots {
  recipe: Record<string, unknown> | null;
  format: ExportFormat;
  window: { from: string; to: string; tz: string };
  labels: {
    dataset: string;
    about: string;
    creators: string[];
    all_creators: number;
    employees: string[] | null;
    kinds: string[];
    order: string;
    limit: number | null;
  };
  columns: string[];
  filename: string;
}

const strs = (v: unknown): string[] => (Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : []);
const str = (v: unknown): string => (typeof v === "string" ? v : "");
const obj = (v: unknown): Record<string, unknown> =>
  (v && typeof v === "object" && !Array.isArray(v) ? v as Record<string, unknown> : {});

export function exportSlotsFrom(raw: unknown): ExportSlots | null {
  if (!raw || typeof raw !== "object") return null;
  const r = obj(raw);
  const w = obj(r.window);
  const lb = obj(r.labels);
  const recipe = r.recipe && typeof r.recipe === "object" && !Array.isArray(r.recipe) ? r.recipe as Record<string, unknown> : null;
  const all = typeof lb.all_creators === "number" && Number.isFinite(lb.all_creators) ? lb.all_creators : 0;
  return {
    recipe,
    format: r.format === "xlsx" ? "xlsx" : "csv",
    window: { from: str(w.from), to: str(w.to), tz: str(w.tz) || "UTC" },
    labels: {
      dataset: str(lb.dataset) || "Report", about: str(lb.about), creators: strs(lb.creators), all_creators: all,
      employees: Array.isArray(lb.employees) ? strs(lb.employees) : null, kinds: strs(lb.kinds),
      order: str(lb.order),
      limit: typeof lb.limit === "number" && Number.isInteger(lb.limit) && lb.limit > 0 ? lb.limit : null,
    },
    columns: strs(r.columns),
    filename: str(r.filename) || `report.${r.format === "xlsx" ? "xlsx" : "csv"}`,
  };
}

export function exportPlanText(s: ExportSlots): string[] {
  const lb = s.labels;
  const lines = [`Report: ${lb.dataset}${lb.about ? ` — ${lb.about}` : ""}`];
  lines.push(`Dates: ${s.window.from} – ${s.window.to} (${s.window.tz})`);
  lines.push(lb.creators.length ? `Creators: ${lb.creators.join(", ")}` : `Creators: all your Creators (${lb.all_creators})`);
  if (lb.employees) lines.push(lb.employees.length ? `Employees: ${lb.employees.join(", ")}` : "Employees: all your Employees");
  if (lb.kinds.length) lines.push(`Kinds: ${lb.kinds.join(", ")}`);
  if (s.columns.length) lines.push(`Columns: ${s.columns.join(", ")}`);
  if (lb.order) lines.push(`Order: ${lb.order}`);
  lines.push(lb.limit !== null ? `Rows: top ${lb.limit}` : "Rows: all");
  lines.push(`Format: ${s.format === "xlsx" ? "Excel (.xlsx)" : "CSV"}`);
  return lines;
}

export function exportRunBody(s: ExportSlots | null): { recipe: Record<string, unknown>; format: ExportFormat } | null {
  return s?.recipe ? { recipe: s.recipe, format: s.format } : null;
}
