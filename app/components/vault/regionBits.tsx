/**
 * The vision-flags bits the Flags review cards draw: a region's name, a region state's colours,
 * the "over" lines (what covers a region), the item's meta line, and its reasons list.
 */

import { AlertTriangle } from "lucide-react";

export const REGION_LABEL: Record<string, string> = {
  breasts_vis: "breasts",
  vulva_vis: "vulva",
  anus_vis: "anus",
};

/** A region state's colours for the Flags review's picked button. */
export const STATE_TONE: Record<"strong", Record<string, string>> = {
  strong: {
    bare: "border-err/70 bg-err/20 text-err",
    covered: "border-info/70 bg-info/20 text-info",
    not_in_frame: "border-muted/70 bg-muted/20 text-fg-dim",
  },
};

/** What covers each region ("vulva: thong"), one line each; nothing when no region has one. */
export function OverLines({ over }: { over: Record<string, string> }) {
  const named = Object.entries(over).filter(([, v]) => v);
  if (!named.length) return null;
  return (
    <p className="text-[12px] text-muted leading-snug">
      {named.map(([r, v]) => (
        <span key={r} className="block">
          {REGION_LABEL[r] ?? r}: <b className="text-fg">{v}</b>
        </span>
      ))}
    </p>
  );
}

/** "#id · kind · explicitness · clothing_state", then the lanes it sits in when given. */
export function MediaMeta({ item, lanes = [] }: {
  item: { media_id: number; kind: string; explicitness: string; clothing_state: string };
  lanes?: string[];
}) {
  return (
    <p className="text-[12px] text-muted">
      #{item.media_id} · {item.kind} · {item.explicitness} · {item.clothing_state}
      {lanes.length > 0 && ` · ${lanes.join(", ")}`}
    </p>
  );
}

/** Why the card is here, one warning line each; nothing when empty. */
export function Reasons({ items, tone }: { items: string[]; tone: "warn" | "err" }) {
  if (!items.length) return null;
  return (
    <ul className="space-y-0.5">
      {items.map((w) => (
        <li key={w} className={`flex items-start gap-1 text-[12px] leading-snug ${tone === "warn" ? "text-warn" : "text-err"}`}>
          <AlertTriangle className="mt-px h-3.5 w-3.5 shrink-0" aria-hidden />
          {w}
        </li>
      ))}
    </ul>
  );
}
