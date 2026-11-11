import { useEffect, useRef } from "react";

/** Tells the parent (`report`) whether this child is busy: on every change, and false once more on unmount, so a child
 *  that goes away mid-run never leaves its parent waiting. AddCreatorModal's sign-in cards and proxy editor use it to
 *  fill the wizard's `busy` record. */
export function useReportBusy(busy: boolean, report?: (busy: boolean) => void) {
  const ref = useRef(report);
  useEffect(() => {
    ref.current = report;
    report?.(busy);
  }, [busy, report]);
  useEffect(() => () => ref.current?.(false), []);
}
