"use client";

/**
 * Billing (docs/spec/settings-tabs/phase-05-billing-balance-about.md): Infloww's subscription layout with
 * honest content. Inflowwww is self-hosted and free, so the plan card says so, every payment action is
 * Not wired, and the invoice table is empty. The subtab is local state with no route of its own. The
 * Panel reads and writes nothing (ADR-0008).
 */

import { useState } from "react";

import { Card, NotWired, SettingsPanel, SettingsTable, TABLE_ROW } from "@/components/settings/SettingsPanel";
import { EmptyState, IfTabs } from "@/components/ui/infloww";

const SUBTABS = ["Infloww subscription", "AI Copilot"] as const;
type Subtab = (typeof SUBTABS)[number];
const COLUMNS = ["Invoice", "Period", "Amount", "Status"];

export default function BillingTab() {
  const [active, setActive] = useState<Subtab>(SUBTABS[0]);

  return (
    <SettingsPanel title="Billing">
      {/* Infloww's line tabs sit right under the 48px header. */}
      <IfTabs
        aria-label="Billing"
        tabs={SUBTABS.map((t) => ({ value: t, label: t }))}
        value={active}
        onChange={setActive}
        className="px-0 md:-mt-6 border-[var(--if-line)]"
      />
      <div role="tabpanel" aria-label={active}>
        {active === SUBTABS[0] && (
          <>
            <div className="mt-6">
              <Card title="Inflowwww — self-hosted, free">
                <div className="flex flex-wrap gap-3">
                  <NotWired label="Pricing plans" />
                  <NotWired label="Update card" />
                  <NotWired label="Cancel subscription" />
                  <NotWired label="Billing information" />
                </div>
              </Card>
            </div>
            {/* The bundle's 75px filter row, its one action at the right. */}
            <div className="h-[75px] flex items-center justify-end">
              <NotWired label="Make a Payment" />
            </div>
          </>
        )}
        {/* Empty on both subtabs: Inflowwww bills nothing. */}
        <div className={active === SUBTABS[0] ? undefined : "mt-6"}>
          <SettingsTable columns={COLUMNS} small>
            <tr className={TABLE_ROW}>
              <td colSpan={COLUMNS.length}>
                <EmptyState kind="data" size="sm" text="No invoices" />
              </td>
            </tr>
          </SettingsTable>
        </div>
      </div>
    </SettingsPanel>
  );
}
