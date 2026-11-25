"use client";


import { useState } from "react";

import { useUser } from "@/contexts/UserContext";

export function ImpersonationBanner() {
  const { user, stopImpersonating } = useUser();
  const [busy, setBusy] = useState(false);

  // Relay 403s mutating requests while impersonating; this banner explains why sends fail.
  if (!user?.impersonating) return null;

  async function onExit() {
    setBusy(true);
    try {
      await stopImpersonating();
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="relative sm:sticky top-0 z-40 bg-warn text-black text-xs sm:text-sm">
      <div className="max-w-shell mx-auto px-3 lg:px-6 py-2 flex items-center gap-3 flex-wrap">
        <span className="font-semibold">Viewing as @{user.username}</span>
        <span className="hidden sm:inline opacity-80">
          (you: @{user.impersonating.real_username}) — read-only
        </span>
        <button
          type="button"
          onClick={() => void onExit()}
          disabled={busy}
          className="ml-auto px-3 py-2 sm:px-2.5 sm:py-1 min-h-10 sm:min-h-0 rounded bg-black/15 hover:bg-black/25 font-medium disabled:opacity-50"
        >
          {busy ? "Exiting…" : "Exit impersonation"}
        </button>
      </div>
    </div>
  );
}
