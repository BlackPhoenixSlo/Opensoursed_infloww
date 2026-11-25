"use client";


import Link from "next/link";
import { TriangleAlert } from "lucide-react";

import { consentFixHref, pinnedName, useAgencyPinned } from "@/components/AgencyNotifications";
import { OPEN_AGENCY_EVENT } from "@/components/notificationBellReducer";

const VIEW_CLS = "h-[26px] px-2.5 shrink-0 inline-flex items-center rounded-md bg-nav-surface hover:bg-nav-hover "
  + "text-nav-fg-active text-xs font-medium";

export function ConsentBanner() {
  const pinned = useAgencyPinned();
  if (pinned.length === 0) return null;
  const names = [...new Set(pinned.map(pinnedName))].join(", ");
  const accounts = [...new Set(pinned.map((n) => n.account_id))];
  const fix = accounts.length === 1 ? consentFixHref(accounts[0]) : null;
  return (
    <div
      data-consent-banner
      role="alert"
      className="mx-3 mb-2 h-10 px-3 rounded-lg bg-[rgba(255,161,95,.14)] flex items-center gap-2 text-sm text-warn"
    >
      <TriangleAlert aria-hidden className="w-4 h-4 shrink-0" />
      <span className="flex-1 min-w-0 truncate" title={pinned.map((n) => n.text).join("\n")}>
        <span className="font-medium">{names}</span>
        <span className="sm:hidden">: OnlyFans consent form needed</span>
        <span className="hidden sm:inline">
          : OnlyFans needs a signed consent form. Media mass messages and PPVs fail until the creator signs.
        </span>
      </span>
      {fix
        ? <Link href={fix} className={VIEW_CLS}>View</Link>
        : (
          <button type="button" onClick={() => window.dispatchEvent(new Event(OPEN_AGENCY_EVENT))} className={VIEW_CLS}>
            View
          </button>
        )}
    </div>
  );
}
