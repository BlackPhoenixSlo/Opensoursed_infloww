import { fromZonedInput, toZonedInput, type ClockEdit, type ClockRecord } from "@/lib/shifts";

export interface RecordForm {
  inV: string;
  outV: string;
  busy: boolean;
  error: string | null;
}

export type RecordFormAction =
  | { type: "in"; value: string }
  | { type: "out"; value: string }
  | { type: "error"; error: string }
  | { type: "saving" };

const startInputs = (r: Pick<ClockRecord, "in_utc" | "out_utc">, tz: string) => ({
  inV: toZonedInput(r.in_utc, tz),
  outV: r.out_utc ? toZonedInput(r.out_utc, tz) : "",
});

export function initialRecordForm(r: Pick<ClockRecord, "in_utc" | "out_utc">, tz: string, closing: boolean,
  now = new Date()): RecordForm {
  const start = startInputs(r, tz);
  return {
    inV: start.inV,
    outV: closing ? toZonedInput(now.toISOString(), tz) : start.outV,
    busy: false,
    error: null,
  };
}

export function recordFormReducer(state: RecordForm, action: RecordFormAction): RecordForm {
  switch (action.type) {
    case "in":
      return { ...state, inV: action.value };
    case "out":
      return { ...state, outV: action.value };
    case "error":
      return { ...state, busy: false, error: action.error };
    case "saving":
      return { ...state, busy: true, error: null };
  }
}

export type RecordCheck =
  | { kind: "unchanged" }
  | { kind: "error"; error: string }
  | { kind: "send"; body: ClockEdit };

export function validateRecord(r: Pick<ClockRecord, "in_utc" | "out_utc">, form: Pick<RecordForm, "inV" | "outV">,
  tz: string, closing: boolean): RecordCheck {
  const start = startInputs(r, tz);
  const body: ClockEdit = {};
  if (!closing && form.inV !== start.inV) {
    const v = fromZonedInput(form.inV, tz);
    if (!v) return { kind: "error", error: "Enter a clock in time." };
    body.in_utc = v;
  }
  if (closing || form.outV !== start.outV) {
    const v = fromZonedInput(form.outV, tz);
    if (!v) return { kind: "error", error: "Enter a clock out time." };
    body.out_utc = v;
  }
  if (!body.in_utc && !body.out_utc) return { kind: "unchanged" };
  const inUtc = body.in_utc ?? r.in_utc;
  const outUtc = body.out_utc ?? r.out_utc;
  if (outUtc && Date.parse(outUtc) <= Date.parse(inUtc)) {
    return { kind: "error", error: "Clock out must be after clock in." };
  }
  return { kind: "send", body };
}
