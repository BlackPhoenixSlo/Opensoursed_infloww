"use client";

/** Ours: the Creator's two vault switches (`useVaultSettings`), both off by default. In the Extras drawer, for
 *  whoever may edit the folders (not a folder-limited chatter). Each is one server boolean, saved on the tap. */

import { useState } from "react";

import { useQueryClient } from "@tanstack/react-query";

import { IfSwitch } from "@/components/ui/infloww";
import { setVaultSetting, useVaultSettings, type VaultSettings } from "@/hooks/useVaultSettings";

const ROWS: { key: keyof VaultSettings; label: string; help: string }[] = [
  {
    key: "folder_price_final",
    label: "Folder price is final",
    help: "Full AI Chat sells media from a priced folder at exactly the saved price: no AI pricing, no tease price, no haggling. Off: the AI decides the price.",
  },
  {
    key: "standard_folders",
    label: "Standard folders",
    help: "Sorts described media into a fixed list of categories. Media in Needs Review is not sold until you file it.",
  },
];

export default function VaultSettingsSwitches({ accountId }: { accountId: string }) {
  const qc = useQueryClient();
  const settings = useVaultSettings(accountId);
  const [saving, setSaving] = useState<keyof VaultSettings | null>(null);
  const [failed, setFailed] = useState(false);
  if (!settings.data) return null;
  const data = settings.data;
  async function toggle(key: keyof VaultSettings, value: boolean) {
    setSaving(key);
    setFailed(false);
    try {
      await setVaultSetting(qc, accountId, { [key]: value });
    } catch {
      setFailed(true);
    } finally {
      setSaving(null);
    }
  }
  return (
    <section data-testid="vault-settings-switches" className="space-y-3 border-t border-border pt-3">
      {ROWS.map((row) => (
        <div key={row.key} className="space-y-1">
          <IfSwitch
            checked={data[row.key]}
            loading={saving === row.key}
            disabled={saving !== null}
            onChange={(value) => void toggle(row.key, value)}
            label={row.label}
          />
          <p className="text-xs text-fg-dim">{row.help}</p>
        </div>
      ))}
      {failed && <p role="alert" className="text-xs text-err">Couldn&apos;t save. Try again.</p>}
    </section>
  );
}
