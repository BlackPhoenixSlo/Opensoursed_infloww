import { describe, expect, it } from "vitest";

import { exportPlanText, exportRunBody, exportSlotsFrom, type ExportSlots } from "./doExport";

const RECIPE = { dataset: "employee_sales", window: { from: "2026-03-09", to: "2026-03-14" }, creators: [], employees: [3] };
const SLOTS: ExportSlots = {
  recipe: RECIPE, format: "csv",
  window: { from: "2026-03-09", to: "2026-03-14", tz: "Europe/London" },
  labels: {
    dataset: "Employee sales", about: "sales credited to each Employee", creators: [], all_creators: 2,
    employees: ["Anna"], kinds: ["Tips", "PPV"], order: "Total, high to low", limit: 20,
  },
  columns: ["Employee", "Total"], filename: "employee_sales_2026-03-09_2026-03-14.csv",
};

describe("exportSlotsFrom", () => {
  it("keeps good slots as they are", () => {
    expect(exportSlotsFrom(SLOTS)).toEqual(SLOTS);
  });
  it.each<[string, unknown, ExportSlots | null]>([
    ["no slots", null, null],
    ["not an object", "junk", null],
    ["every field missing", {}, {
      recipe: null, format: "csv", window: { from: "", to: "", tz: "UTC" },
      labels: { dataset: "Report", about: "", creators: [], all_creators: 0, employees: null, kinds: [], order: "", limit: null },
      columns: [], filename: "report.csv",
    }],
  ])("%s", (_, raw, want) => expect(exportSlotsFrom(raw)).toEqual(want));
  it("junk fields read as their safe default", () => {
    const s = exportSlotsFrom({ ...SLOTS, recipe: ["x"], format: "pdf", labels: { ...SLOTS.labels, creators: [1, "Mia"], employees: "x", all_creators: "2", order: 3, limit: 0 } })!;
    expect(s.recipe).toBeNull();
    expect(s.format).toBe("csv");
    expect(s.labels.creators).toEqual(["Mia"]);
    expect(s.labels.employees).toBeNull();
    expect(s.labels.all_creators).toBe(0);
    expect(s.labels.order).toBe("");
    expect(s.labels.limit).toBeNull();
  });
});

describe("exportPlanText", () => {
  it.each<[string, ExportSlots, string[]]>([
    ["all Creators, named Employees, kinds, CSV", SLOTS, [
      "Report: Employee sales — sales credited to each Employee",
      "Dates: 2026-03-09 – 2026-03-14 (Europe/London)",
      "Creators: all your Creators (2)",
      "Employees: Anna",
      "Kinds: Tips, PPV",
      "Columns: Employee, Total",
      "Order: Total, high to low",
      "Rows: top 20",
      "Format: CSV",
    ]],
    ["named Creators, no Employee dimension, no kinds, Excel",
      { ...SLOTS, format: "xlsx", columns: [], labels: { ...SLOTS.labels, dataset: "Sales", about: "", creators: ["Mia Rose", "Luna"], employees: null, kinds: [], order: "Tips, high to low", limit: null } }, [
        "Report: Sales",
        "Dates: 2026-03-09 – 2026-03-14 (Europe/London)",
        "Creators: Mia Rose, Luna",
        "Order: Tips, high to low",
        "Rows: all",
        "Format: Excel (.xlsx)",
      ]],
    ["every Employee, no order sent", { ...SLOTS, labels: { ...SLOTS.labels, employees: [], order: "" } }, [
      "Report: Employee sales — sales credited to each Employee",
      "Dates: 2026-03-09 – 2026-03-14 (Europe/London)",
      "Creators: all your Creators (2)",
      "Employees: all your Employees",
      "Kinds: Tips, PPV",
      "Columns: Employee, Total",
      "Rows: top 20",
      "Format: CSV",
    ]],
  ])("%s", (_, slots, want) => expect(exportPlanText(slots)).toEqual(want));
});

describe("exportRunBody", () => {
  it.each<[string, ExportSlots | null, unknown]>([
    ["the recipe and the format", SLOTS, { recipe: RECIPE, format: "csv" }],
    ["xlsx", { ...SLOTS, format: "xlsx" }, { recipe: RECIPE, format: "xlsx" }],
    ["an unresolved name (no recipe) sends nothing", { ...SLOTS, recipe: null }, null],
    ["no slots", null, null],
  ])("%s", (_, slots, want) => expect(exportRunBody(slots)).toEqual(want));
});
