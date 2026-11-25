"use client";


import Link from "next/link";

import { Badge } from "@/components/ui/primitives";
import FanAvatar from "@/components/messages/FanAvatar";
import { fmtPrice } from "@/lib/messageFormat";
import { ofPreviewText } from "@/lib/ofRichText";
import { fmtRelTime } from "@/lib/utils";

import type { TipsListRow } from "@/hooks/useTipsList";
import { onPopoutClick } from "@/lib/nav";

interface Props {
  row: TipsListRow;
}

export default function TipRow({ row }: Props) {
  const note = row.tip_note ? ofPreviewText(row.tip_note) : "";
  const credited = row.attribution_source === "tip_message";

  const chatHref =
    row.fan_id != null ? `/messages-pro/${row.account_id}/${row.fan_id}` : null;

  const inner = (
    <div className="flex gap-3 p-3 border border-border rounded-xl bg-panel hover:border-border-light transition-colors">
      <FanAvatar
        url={row.fan.avatar_url}
        accountId={row.account_id}
        alt={row.fan.username ?? "fan"}
      />

      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 md:flex-wrap">
          <div className="flex items-center gap-2 min-w-0">
            <span className="font-medium text-fg text-sm truncate">
              @{row.fan.username || row.fan_id || "unknown"}
            </span>
            {row.fan.display_name && (
              <span className="hidden md:inline text-xs text-fg-dim truncate">
                ({row.fan.display_name})
              </span>
            )}
          </div>
          <Badge color="ok" className="hidden md:inline-flex shrink-0">
            <span>💰</span>
            <span>TIP</span>
          </Badge>
          <div className="ml-auto flex items-center gap-2 shrink-0">
            <span className="text-sm font-semibold text-fg">
              {fmtPrice(row.amount_cents)}
            </span>
            <span className="text-xs text-fg-dim">
              {fmtRelTime(row.occurred_at)}
            </span>
          </div>
        </div>

        <div className="mt-1 text-xs italic text-fg-dim line-clamp-2 break-words">
          {note ? `"${note}"` : <span className="not-italic">(no message)</span>}
        </div>

        <div className="mt-2 flex items-center gap-2 flex-wrap">
          {credited ? (
            <span className="text-[11px] text-fg-dim">
              credited: {row.attributed_employee_name ?? `#${row.attributed_employee_id}`} via tip msg
            </span>
          ) : (
            <span className="text-[11px] text-muted">
              Unattributed (standalone tip)
            </span>
          )}

          {chatHref && (
            <span className="hidden md:inline ml-auto text-xs text-fg-dim group-hover:text-accent">
              ↗ open chat
            </span>
          )}
        </div>
      </div>
    </div>
  );

  if (chatHref) {
    return (
      <Link href={chatHref} onClick={(e) => onPopoutClick(e, chatHref)} className="block group">
        {inner}
      </Link>
    );
  }
  return <div className="block">{inner}</div>;
}
