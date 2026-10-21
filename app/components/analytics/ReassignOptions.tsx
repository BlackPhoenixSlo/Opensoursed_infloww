import type { IfOption } from "@/components/ui/infloww";
import type { AttributeTo } from "@/hooks/useStats";

/** The pickers' "No one" (credited to nobody) and "Clear assignment" (the override removed) values. */
const NO_ONE = "no_one";
const CLEAR = "clear";

/** An Employee as a Reassign picker lists it. */
export type ReassignEmployee = { id: number; label: string };

/** A Reassign picker's value as the attribute routes' `employee_id`. */
export function attributeTo(choice: string): AttributeTo {
  return choice === CLEAR ? null : choice === NO_ONE ? NO_ONE : Number(choice);
}

/** A Reassign picker's choices: the Agency's Employees, "No one" and, with `clear`, "Clear assignment". Sales
 *  records' `IfSelect`s take them as they are; `ReassignOptions` draws them as native options. */
export function reassignChoices(employees: ReassignEmployee[], clear = false): IfOption[] {
  return [
    ...employees.map((e) => ({ value: String(e.id), label: e.label })),
    { value: NO_ONE, label: "No one" },
    ...(clear ? [{ value: CLEAR, label: "Clear assignment" }] : []),
  ];
}

/** A native Reassign picker's options (Shift records): "Choose an employee", then `reassignChoices`. */
export default function ReassignOptions({ employees, clear = false }: {
  employees: ReassignEmployee[]; clear?: boolean;
}) {
  return (
    <>
      <option value="" disabled>Choose an employee</option>
      {reassignChoices(employees, clear).map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
    </>
  );
}
