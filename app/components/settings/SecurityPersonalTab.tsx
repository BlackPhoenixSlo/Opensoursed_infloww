"use client";


import { useState } from "react";

import { useUser } from "@/contexts/UserContext";
import { Card, IF_BTN, SettingsPanel } from "@/components/settings/SettingsPanel";
import { OtherSessionsCard, TwoFactorCard } from "@/components/settings/TwoFactorCard";

const TIP = "text-[length:var(--if-fs-sm)] leading-5 text-[var(--if-fg-2)]";

export default function SecurityPersonalTab() {
  const { user, logout } = useUser();
  const [signingOut, setSigningOut] = useState(false);

  return (
    <SettingsPanel title="Security (personal)">
      <div className="flex flex-col gap-6">
        <Card
          title="Current session"
          control={
            <button
              type="button"
              className={IF_BTN}
              disabled={signingOut}
              onClick={() => { setSigningOut(true); void logout(); }}
            >
              Sign out
            </button>
          }
        >
          <p className={TIP}>You are signed in as {user?.username || "—"}.</p>
        </Card>
        <OtherSessionsCard />
        <TwoFactorCard />
      </div>
    </SettingsPanel>
  );
}
