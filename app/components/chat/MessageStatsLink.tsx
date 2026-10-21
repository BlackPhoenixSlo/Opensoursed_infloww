"use client";

/**
 * MessageStatsLink — the message-statistics rows (docs/spec/phase-03-chat-
 * header-message-list.md, H16, F7; ticket 91). Ticket 140: the 📈 button and
 * its own menu are gone; the Kebab menu (`ChatActionsMenu`) renders these two
 * rows, same targets and Not wired rendering
 * (docs/spec/messages-pro-look-and-feel/phase-03-chat-header.md, Kebab menu
 * order).
 *
 * "Mass message statistics" opens `/growth/smart-messages?tab=mass` in a new
 * browser tab, unscoped, because that page takes no Creator; `?tab=mass` keeps
 * it on the Mass Messages tab once Automated Messages comes first
 * (docs/spec/infloww-parity-round-2/phase-02b-auto-mass-messages.md).
 * "Online fans message statistics" is Not wired: no view shows online-fans
 * blasts on their own.
 */

import { cn } from "@/lib/utils";
import { MENU_ROW, NotWiredMenuRow } from "./MenuParts";

export function MessageStatsRows() {
  return (
    <>
      <a
        href="/growth/smart-messages?tab=mass"
        target="_blank"
        rel="noopener noreferrer"
        className={cn(MENU_ROW, "hover:bg-bg-elev-1")}
      >
        Mass message statistics
      </a>
      <NotWiredMenuRow>Online fans message statistics</NotWiredMenuRow>
    </>
  );
}
