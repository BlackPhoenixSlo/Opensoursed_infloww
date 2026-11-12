"use client";

/**
 * Your Preferences' per-browser switches: the app's own theme (useTheme, the avatar menu's
 * Light/Dark mode), then, as Infloww's, "Synchronize platform
 * display settings" (our theme on OF Manager's mirror, useOfTheme) and
 * notifications per platform (the toaster's pings, notifSettings). Both are
 * this browser's own choices in localStorage, applied at once, so they sit
 * outside the Preferences blob and its Save. Fansly has no display sync: it
 * has no platform page here for our display settings to reach.
 */

import { useSyncExternalStore } from "react";

import { useTheme } from "@/hooks/useTheme";
import { useNotificationSettings } from "@/hooks/useNotificationSettings";
import { DEFAULT_NOTIF_SETTINGS } from "@/lib/notifSettings";
import { PLATFORM_NAME, PLATFORMS } from "@/lib/platform";
import { useOfDisplaySync, writeOfDisplaySync } from "@/lib/ofMirrorTheme";
import { Section, ToggleRow } from "@/components/settings/SettingsPanel";

const noSubscribe = () => () => {};

export default function PlatformSwitches() {
  const sync = useOfDisplaySync();
  const { theme, setTheme } = useTheme();
  const { settings, update } = useNotificationSettings();
  // useNotificationSettings reads localStorage in its first render; the server's markup and hydration show the
  // defaults, and the stored switches right after.
  const hydrated = useSyncExternalStore(noSubscribe, () => true, () => false);
  const platforms = hydrated ? settings.platforms : DEFAULT_NOTIF_SETTINGS.platforms;
  return (
    <>
      <p className="mb-4 text-[length:var(--if-fs-sm)] text-[var(--if-fg-3)]">
        The switches below apply at once on this browser; they need no Save.
      </p>
      <Section title="Appearance">
        <ToggleRow
          title="Dark mode"
          description="This app's theme; off = light"
          checked={hydrated ? theme === "dark" : true}
          onChange={(dark) => setTheme(dark ? "dark" : "light")}
        />
      </Section>
      <Section title="Synchronize platform display settings">
        <ToggleRow
          title="OnlyFans"
          description="OF Manager pages follow this app's theme"
          checked={sync}
          onChange={writeOfDisplaySync}
        />
      </Section>
      <Section title="Platform notifications">
        {PLATFORMS.map((p) => (
          <ToggleRow
            key={p}
            title={PLATFORM_NAME[p]}
            checked={platforms[p]}
            onChange={(on) => update({ platforms: { ...settings.platforms, [p]: on } })}
          />
        ))}
      </Section>
    </>
  );
}
