"use client";

/**
 * Settings › OnlyFans consent: one Creator's "Auto-accept OnlyFans consent" switch (OfConsentCard).
 * The Creator is picked in the panel header (CreatorSettingsPanel): `?account=<id>` (a consent notice's link) when it
 * is one of the session-backed Creators, else the one in scope, else the first.
 */

import { Suspense } from "react";
import { useSearchParams } from "next/navigation";

import { CreatorSettingsPanel } from "@/components/settings/CreatorSettingsPanel";
import { OfConsentCard } from "@/components/settings/OfConsentCard";

export default function OfConsentTab() {
  // useSearchParams suspends while the page prerenders: its own boundary.
  return <Suspense fallback={null}><ConsentPanel /></Suspense>;
}

function ConsentPanel() {
  const linked = useSearchParams()?.get("account") ?? null;
  return (
    <CreatorSettingsPanel title="OnlyFans consent" emptyText="Select a creator to set its OnlyFans consent" linked={linked}
      card={(accountId) => <OfConsentCard accountId={accountId} />} />
  );
}
