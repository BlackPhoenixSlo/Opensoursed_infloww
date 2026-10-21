"use client";

/**
 * The Relay's typed employee cap refusal (`employee_limit`: service/employees.py `_employee_limit`, a 409
 * with `{limit, active}`) as a modal instead of an error line. Renders nothing for any other error.
 */

import { RelayError } from "@/lib/relay";
import { errorCode } from "@/lib/twoFactor";
import { IF_BTN_PRIMARY } from "@/components/settings/SettingsPanel";
import { IfModal } from "@/components/ui/infloww";

export const isEmployeeLimit = (err: unknown) => errorCode(err) === "employee_limit";

export default function EmployeeLimitModal({ error, onClose }: { error: unknown; onClose: () => void }) {
  if (!isEmployeeLimit(error)) return null;
  const detail = ((error as RelayError).body as { detail: { limit?: number; active?: number } }).detail;
  return (
    <IfModal
      title="Employee limit reached"
      onClose={onClose}
      footer={<button type="button" className={IF_BTN_PRIMARY} onClick={onClose}>OK</button>}
    >
      <p>
        Your organization has {detail.active ?? detail.limit} active employees, the most it can have
        {detail.limit != null ? ` (${detail.limit})` : ""}. Deactivate an employee to make room for another.
      </p>
    </IfModal>
  );
}
