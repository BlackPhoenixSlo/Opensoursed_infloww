"use client";

/**
 * Billing: one line. Inflowwww is self-hosted and free, so there is no plan, card, payment or invoice to show
 * (owner, 2026-11-11: the Infloww-parity placeholders did nothing). The Panel reads and writes nothing.
 */

import { SettingsPanel } from "@/components/settings/SettingsPanel";
import { BRAND_NAME } from "@/lib/brand";

export default function BillingTab() {
  return (
    <SettingsPanel title="Billing">
      <p className="text-[length:var(--if-fs)] text-[var(--if-fg-2)]">
        {BRAND_NAME} is self-hosted and free: nothing to pay, no invoices.
      </p>
    </SettingsPanel>
  );
}
