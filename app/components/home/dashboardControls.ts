import type { Period } from "@/lib/dateRange";

export type DashboardControl = {
  key: string;
  id: `dashboard#${number}`;
  kind: "label" | "switch" | "tab" | "tile";
  labels: readonly string[];
  sources: readonly string[];
  inventory: string | null;
  wired: boolean;
  period?: Period;
  ours?: true;
};

const J = "index.9f50f370.js";
const J2 = "index.b50b8e61.js";

export const DASHBOARD_HEADER = [
  { key: "title", id: "dashboard#13", kind: "label", labels: ["Creator earnings overview"],
    sources: [`${J} @11243074`], inventory: null, wired: true },
  { key: "titleTip", id: "dashboard#14", kind: "label",
    labels: ["An overview of total earnings based on your managed Creators during this period"],
    sources: [`${J} @11243102`], inventory: null, wired: true },
  { key: "timeZone", id: "dashboard#16", kind: "label", labels: ["UTC"],
    sources: [`${J} @7143613`, `${J} @11242265`], inventory: "[CL]", wired: true },
  { key: "timeZoneTip", id: "dashboard#19", kind: "label", labels: ["Set by your organization"],
    sources: [`${J} @11242336`], inventory: null, wired: true },
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
  { key: "last30Days", id: "dashboard#96", kind: "tab", labels: ["Last 30 days"],
    sources: [`${J2} @11252393`], inventory: null, wired: true, ours: true, period: "last30Days" },
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
  { key: "chargebacks", id: "dashboard#49", kind: "tile", labels: ["Chargebacks"],
    sources: [`${J} @11239701`], inventory: "[CL]", wired: true, ours: true },
  { key: "employeeSales", id: "dashboard#79", kind: "tile", labels: ["Employee sales"],
    sources: [`${J} @11244153`], inventory: "[CL]", wired: true },
  { key: "employeeSalesTip", id: "dashboard#80", kind: "label",
    labels: ["Employee sales growth and trends determined by your team’s sales settings"],
    sources: [`${J} @11244170`], inventory: null, wired: true },
] as const satisfies readonly DashboardControl[];

export type DashboardControlKey = (typeof DASHBOARD_HEADER)[number]["key"];

export function control(key: DashboardControlKey): DashboardControl {
  return DASHBOARD_HEADER.find((c) => c.key === key)!;
}

export const DEFAULT_PERIOD: Period = "week";

export type Basis = "Gross" | "Net";

export const DEFAULT_BASIS: Basis = "Net";

export const PERIOD_TABS = DASHBOARD_HEADER.filter(
  (c): c is Extract<(typeof DASHBOARD_HEADER)[number], { kind: "tab" }> => c.kind === "tab",
);

export function isPeriod(v: string): v is Period {
  return PERIOD_TABS.some((t) => t.period === v);
}
