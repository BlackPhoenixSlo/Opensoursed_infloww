/**
 * The control catalogue of the Dashboard's KPI header: every control
 * `DashboardHeader` takes from the Layout capture
 * (`docs/infloww-layouts/dashboard.md`), in capture order, with its verbatim
 * label, its kind, the capture's Item ID and Source, its Inventory tag
 * (`docs/infloww-screens.md` §3.1) and whether it is wired
 * (docs/spec/infloww-parity-round-2/phase-01-dashboard.md, Interfaces).
 *
 * The header renders from this list, and the page test (`app/page.render.test.tsx`)
 * checks the rendered tree against it and each entry against the capture file
 * on disk, so a label typed from memory fails. Precedent:
 * `components/growth/smartMessagesControls.ts`. A Not wired entry renders
 * disabled with `title="not wired"` and no figure.
 *
 * Omitted, recorded in `.scratch/infloww-parity-round-2/rechecks/dashboard.md`:
 * every Inventory §3.1 header control is in the capture, so none is left out
 * for being Clone-only; the bundle's "Set by your organization" info icon is
 * the time zone's tooltip entry below.
 */

import type { Period } from "@/lib/dateRange";

export type DashboardControl = {
  /** The key the header renders it under (`data-control`). */
  key: string;
  /** The capture's Items ID. */
  id: `dashboard#${number}`;
  kind: "label" | "switch" | "tab" | "tile";
  /** The verbatim labels, in the capture's order: one, or a switch's options. */
  labels: readonly string[];
  /** Every Source part the capture's row cites, verbatim. */
  sources: readonly string[];
  /** The Inventory §3.1 tag, or null where §3.1 does not tag the control. */
  inventory: string | null;
  wired: boolean;
  /** A tab's period id. */
  period?: Period;
};

const J = "index.9f50f370.js";
/** The later bundle whose `DashboardFilterBar` adds a fifth period tab (capture #96). */
const J2 = "index.b50b8e61.js";

export const DASHBOARD_HEADER = [
  // The earnings card's title row, left: title, its tooltip, the time zone and its tooltip.
  { key: "title", id: "dashboard#13", kind: "label", labels: ["Creator earnings overview"],
    sources: [`${J} @11243074`], inventory: null, wired: true },
  { key: "titleTip", id: "dashboard#14", kind: "label",
    labels: ["An overview of total earnings based on your managed Creators during this period"],
    sources: [`${J} @11243102`], inventory: null, wired: true },
  { key: "timeZone", id: "dashboard#16", kind: "label", labels: ["UTC"],
    sources: [`${J} @7143613`, `${J} @11242265`], inventory: "[CL]", wired: true },
  { key: "timeZoneTip", id: "dashboard#19", kind: "label", labels: ["Set by your organization"],
    sources: [`${J} @11242336`], inventory: null, wired: true },
  // Right: `FilterBtns$1`, the earnings select then the four period tabs, then the later bundle's Last month.
  { key: "basis", id: "dashboard#20", kind: "switch", labels: ["Gross earnings", "Net earnings"],
    sources: [`${J} @11232424`, `${J} @11232463`], inventory: "[CL]", wired: true },
  { key: "yesterday", id: "dashboard#22", kind: "tab", labels: ["Yesterday"],
    sources: [`${J} @11232154`], inventory: "[CL]", wired: true, period: "yesterday" },
  { key: "today", id: "dashboard#23", kind: "tab", labels: ["Today"],
    sources: [`${J} @11232192`], inventory: "[CL]", wired: true, period: "today" },
  { key: "week", id: "dashboard#24", kind: "tab", labels: ["This week"],
    sources: [`${J} @11232222`], inventory: "[CL]", wired: true, period: "week" },
  { key: "month", id: "dashboard#25", kind: "tab", labels: ["This month"],
    sources: [`${J} @11232255`], inventory: "[CL]", wired: true, period: "month" },
  { key: "lastMonth", id: "dashboard#96", kind: "tab", labels: ["Last month"],
    sources: [`${J2} @11252393`], inventory: null, wired: true, period: "lastMonth" },
  // `IncomeOverview`: Total earnings, then three columns of two channels.
  { key: "total", id: "dashboard#36", kind: "tile", labels: ["Total earnings"],
    sources: [`${J} @11237146`], inventory: "[CL, PAL]", wired: true },
  { key: "subscriptions", id: "dashboard#44", kind: "tile", labels: ["Subscriptions"],
    sources: [`${J} @11237638`], inventory: "[CL]", wired: true },
  { key: "tips", id: "dashboard#45", kind: "tile", labels: ["Tips"],
    sources: [`${J} @11238009`], inventory: "[CL]", wired: true },
  { key: "posts", id: "dashboard#46", kind: "tile", labels: ["Posts"],
    sources: [`${J} @11238470`], inventory: "[CL]", wired: true },
  { key: "referrals", id: "dashboard#47", kind: "tile", labels: ["Referrals"],
    sources: [`${J} @11238833`], inventory: "[CL]", wired: true },
  { key: "messages", id: "dashboard#48", kind: "tile", labels: ["Messages"],
    sources: [`${J} @11239315`], inventory: "[CL]", wired: true },
  { key: "streams", id: "dashboard#49", kind: "tile", labels: ["Streams"],
    sources: [`${J} @11239701`], inventory: "[CL]", wired: true },
  // The bottom box's "Employee sales" card, the per-employee read (ticket 26), and its tooltip.
  { key: "employeeSales", id: "dashboard#79", kind: "tile", labels: ["Employee sales"],
    sources: [`${J} @11244153`], inventory: "[CL]", wired: true },
  { key: "employeeSalesTip", id: "dashboard#80", kind: "label",
    labels: ["Employee sales growth and trends determined by your team’s sales settings"],
    sources: [`${J} @11244170`], inventory: null, wired: true },
] as const satisfies readonly DashboardControl[];

export type DashboardControlKey = (typeof DASHBOARD_HEADER)[number]["key"];

/** The entry under `key`. */
export function control(key: DashboardControlKey): DashboardControl {
  return DASHBOARD_HEADER.find((c) => c.key === key)!;
}

/** The capture's default tab (#3, `useState("week")`). */
export const DEFAULT_PERIOD: Period = "week";

/** The earnings basis: the switch's option values, as the bundle names them (#20). */
export type Basis = "Gross" | "Net";

/** The capture's default basis (#4, `useState("Net")`). */
export const DEFAULT_BASIS: Basis = "Net";

/** The period tabs, in capture order. */
export const PERIOD_TABS = DASHBOARD_HEADER.filter(
  (c): c is Extract<(typeof DASHBOARD_HEADER)[number], { kind: "tab" }> => c.kind === "tab",
);

export function isPeriod(v: string): v is Period {
  return PERIOD_TABS.some((t) => t.period === v);
}
