import type { IfOption } from "@/components/ui/infloww";
import type { AttributeTo } from "@/hooks/useStats";

const NO_ONE = "no_one";
const CLEAR = "clear";

export type ReassignEmployee = { id: number; label: string };

export function attributeTo(choice: string): AttributeTo {
  return choice === CLEAR ? null : choice === NO_ONE ? NO_ONE : Number(choice);
}

export function reassignChoices(employees: ReassignEmployee[], clear = false): IfOption[] {
  return [
    ...employees.map((e) => ({ value: String(e.id), label: e.label })),
    { value: NO_ONE, label: "No one" },
    ...(clear ? [{ value: CLEAR, label: "Clear assignment" }] : []),
  ];
}

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
