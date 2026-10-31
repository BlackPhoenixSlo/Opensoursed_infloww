/**
 * The report filters the Messages report lists (paid, tips, top tippers) start their query string with: the window,
 * then the model and the employee, each left off when unset. A builder adds its own params after these.
 */
export interface ReportQueryParams {
  from: string | null;
  to: string | null;
  account_id?: string | null;
  employee_id?: number | null;
}

export function reportQuery(params: ReportQueryParams): URLSearchParams {
  const qs = new URLSearchParams();
  if (params.from) qs.set("from", params.from);
  if (params.to) qs.set("to", params.to);
  if (params.account_id) qs.set("account_id", params.account_id);
  if (params.employee_id != null) qs.set("employee_id", String(params.employee_id));
  return qs;
}
