"use client";

/**
 * FocusModeSettings — Focus mode's settings under its checkbox in the gear
 * menu while it is on (Infloww's Focus mode settings, 04-messages-pro P2):
 * "Pause incoming messages" and "Hide chats with muted notifications"
 * (`useFocusModeSettings`).
 */

import { cn } from "@/lib/utils";
import { MENU_ITEM } from "./MenuParts";
import type { FocusModeSettings as Settings } from "./useFocusModeSettings";

const ROWS: { key: keyof Settings; label: string }[] = [
  { key: "pause", label: "Pause incoming messages" },
  { key: "hideMuted", label: "Hide chats with muted notifications" },
];

export function FocusModeSettings({ settings, onChange }: {
  settings: Settings;
  onChange: (next: Settings) => void;
}) {
  return (
    <div role="group" aria-label="Focus mode settings">
      {ROWS.map(({ key, label }) => (
        // Indented under Focus mode, whose settings they are.
        <label key={key} className={cn(MENU_ITEM, "cursor-pointer select-none pl-7")}>
          <input
            type="checkbox"
            checked={settings[key]}
            onChange={(e) => onChange({ ...settings, [key]: e.target.checked })}
            className="shrink-0"
          />
          <span>{label}</span>
        </label>
      ))}
    </div>
  );
}
