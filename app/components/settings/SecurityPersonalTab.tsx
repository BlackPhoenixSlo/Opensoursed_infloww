"use client";

/**
 * Security (personal) (docs/spec/settings-tabs/phase-02-security.md): Infloww's bordered cards. The
 * Current session card names the signed-in User from `GET /auth/me` (the impersonated user under
 * impersonation) and signs out through `useUser().logout`, the avatar menu's path. Two-factor
 * authentication and Other sessions are TwoFactorCard.tsx (service/account_security.py). The Relay has
 * no password change, so that card's button is Not wired (ADR-0008).
 */

import { useState } from "react";

import { useUser } from "@/contexts/UserContext";
import { Card, IF_BTN, NotWired, SettingsPanel } from "@/components/settings/SettingsPanel";
import { OtherSessionsCard, TwoFactorCard } from "@/components/settings/TwoFactorCard";

/** A card tip: the bundle's `translation-item-tips`, 12px / 20px T2. */
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
        <Card title="Password" control={<NotWired label="Change password" />} />
        <TwoFactorCard />
      </div>
    </SettingsPanel>
  );
}
