"use client";


import { Suspense } from "react";
import { useSearchParams } from "next/navigation";

import { CreatorSettingsPanel } from "@/components/settings/CreatorSettingsPanel";
import { OfConsentCard } from "@/components/settings/OfConsentCard";

export default function OfConsentTab() {
  return <Suspense fallback={null}><ConsentPanel /></Suspense>;
}

function ConsentPanel() {
  // useSearchParams suspends while the page prerenders: its own boundary.
  const linked = useSearchParams()?.get("account") ?? null;
  return (
    <CreatorSettingsPanel title="OnlyFans consent" emptyText="Select a creator to set its OnlyFans consent" linked={linked}
      card={(accountId) => <OfConsentCard accountId={accountId} />} />
  );
}
