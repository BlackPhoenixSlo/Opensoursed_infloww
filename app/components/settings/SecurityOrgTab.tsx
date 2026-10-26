"use client";

/**
 * Security (organization) (docs/spec/settings-tabs/phase-02-security.md): Infloww's
 * "Two-factor authentication" switch, the `security` blob's `require_2fa` (service/account_security.py:
 * every employee sets up and uses 2FA at sign-in; turning it on signs out those without it), above the
 * Agency's Employees from the shared roster (`useRoster()` defaults: disabled rows kept and greyed, the
 * Employees with a login only), with each login's 2FA status and last login (`two_factor`,
 * `last_login_at` on the roster rows). "Reset" turns an Employee's 2FA off and signs them out
 * (`POST /admin/employees/{id}/2fa/reset`). Each switch flip and Reset asks first, in Infloww's words.
 */

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";

import { relay, type Employee } from "@/lib/relay";
import { useRoster } from "@/hooks/useRoster";
import { useSettingsBlob } from "@/lib/settingsBlob";
import {
  IF_BTN, IF_BTN_PRIMARY, LoadError, Section, SettingsPanel, SettingsTable, TABLE_CELL, TABLE_ROW, ToggleRow,
} from "@/components/settings/SettingsPanel";
import { IfModal } from "@/components/ui/infloww";
import { cn } from "@/lib/utils";
import { BRAND_NAME } from "@/lib/brand";

const COLUMNS = ["Name", "2FA status", "Last login", "Operations"];
const OPERATION = "text-[var(--if-accent)] cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed";

const SWITCH_COPY = {
  on: {
    title: "Enable two-factor authentication for organization?",
    body: "All employees will be required to set up and use two-factor authentication to log in to their accounts. "
      + "Employees without it are signed out until they set it up.",
  },
  off: {
    title: "Disable two-factor authentication for organisation?",
    body: "All employees will no longer be required to use two-factor authentication to log in to their accounts.",
  },
};

const twoFactorLabel = (e: Employee) => (e.two_factor == null ? "—" : e.two_factor ? "Enabled" : "Disabled");
const lastLogin = (e: Employee) => (e.last_login_at ? new Date(e.last_login_at).toLocaleString() : "—");

export default function SecurityOrgTab() {
  const { query, rows, pending } = useRoster();
  const blob = useSettingsBlob("security", { require_2fa: false });
  const [confirmSwitch, setConfirmSwitch] = useState<boolean | null>(null);
  const [resetting, setResetting] = useState<Employee | null>(null);
  const resetM = useMutation({
    mutationFn: (e: Employee) => relay.post(`/admin/employees/${e.id}/2fa/reset`, {}),
    onSuccess: () => { setResetting(null); void query.refetch(); },
  });

  const copy = confirmSwitch === null ? null : SWITCH_COPY[confirmSwitch ? "on" : "off"];

  return (
    <SettingsPanel title="Security (organization)">
      <Section>
        <ToggleRow
          title="Two-factor authentication"
          description="Require every employee in your organization to use two-factor authentication"
          checked={blob.value.require_2fa}
          onChange={(next) => { if (blob.loaded) setConfirmSwitch(next); }}
        />
        <LoadError error={blob.query.error} />
      </Section>
      <Section title="Employees">
        <LoadError error={query.error} />
        <SettingsTable columns={COLUMNS} small>
          {rows.map((e) => (
            <tr
              key={e.id}
              aria-disabled={e.is_active ? undefined : true}
              className={cn(TABLE_ROW, !e.is_active && "opacity-60")}
            >
              <td className={TABLE_CELL}>
                <span className="inline-flex items-center gap-2">
                  <span
                    aria-hidden
                    className="w-2 h-2 shrink-0 rounded-full"
                    style={{ background: e.color || "var(--if-fg-3)" }}
                  />
                  {e.display_name}
                </span>
              </td>
              <td className={TABLE_CELL}>{twoFactorLabel(e)}</td>
              <td className={TABLE_CELL}>{lastLogin(e)}</td>
              <td className={TABLE_CELL}>
                <button
                  type="button"
                  className={OPERATION}
                  disabled={!e.two_factor || !e.is_active}
                  title={!e.two_factor ? "2FA is not set up" : undefined}
                  onClick={() => { resetM.reset(); setResetting(e); }}
                >
                  Reset
                </button>
              </td>
            </tr>
          ))}
          {!pending && !query.error && rows.length === 0 && (
            <tr className={TABLE_ROW}>
              <td colSpan={COLUMNS.length} className={cn(TABLE_CELL, "text-[var(--if-fg-3)]")}>No employees</td>
            </tr>
          )}
        </SettingsTable>
      </Section>

      {copy && confirmSwitch !== null && (
        <IfModal
          title={copy.title}
          onClose={() => { setConfirmSwitch(null); blob.resetSave(); }}
          footer={
            <>
              <button type="button" className={IF_BTN} onClick={() => { setConfirmSwitch(null); blob.resetSave(); }}>
                Cancel
              </button>
              <button
                type="button"
                className={IF_BTN_PRIMARY}
                disabled={blob.save.saving}
                onClick={() => blob.commit({ require_2fa: confirmSwitch }, () => setConfirmSwitch(null))}
              >
                Confirm
              </button>
            </>
          }
        >
          <p>{copy.body}</p>
          {blob.save.error && <p role="alert" className="mt-3 text-[var(--if-danger)]">{blob.save.error}</p>}
        </IfModal>
      )}

      {resetting && (
        <IfModal
          title="Reset two-factor authentication for employee's account?"
          onClose={() => setResetting(null)}
          footer={
            <>
              <button type="button" className={IF_BTN} onClick={() => setResetting(null)}>Cancel</button>
              <button
                type="button"
                className={IF_BTN_PRIMARY}
                disabled={resetM.isPending}
                onClick={() => resetM.mutate(resetting)}
              >
                Reset
              </button>
            </>
          }
        >
          <p>
            {resetting.display_name} will be logged out of {BRAND_NAME} and will have to set up their two-factor
            authentication again.
          </p>
          {resetM.error && <p role="alert" className="mt-3 text-[var(--if-danger)]">{resetM.error.message}</p>}
        </IfModal>
      )}
    </SettingsPanel>
  );
}
