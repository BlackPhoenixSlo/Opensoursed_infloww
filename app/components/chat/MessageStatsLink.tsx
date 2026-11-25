"use client";


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
      <NotWiredMenuRow why="onlineStats">Online fans message statistics</NotWiredMenuRow>
    </>
  );
}
