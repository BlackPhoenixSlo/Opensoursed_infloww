"use client";

/**
 * AI keys: the owner's own LLM keys (AgencyKeysCard) in a Settings Panel, then the
 * server's Google Drive key for the vault importer (DriveKeyCard, master-only to edit).
 * Hidden from a Chatter (SETTINGS_TABS chatterHidden); the relay owner-gates the keys
 * routes regardless.
 */

import AgencyKeysCard from "@/components/setup/AgencyKeysCard";
import DriveKeyCard from "@/components/setup/DriveKeyCard";
import { SettingsPanel } from "@/components/settings/SettingsPanel";

export default function AiKeysTab() {
  return (
    <SettingsPanel title="AI keys">
      <div className="space-y-4">
        <AgencyKeysCard />
        <DriveKeyCard />
      </div>
    </SettingsPanel>
  );
}
