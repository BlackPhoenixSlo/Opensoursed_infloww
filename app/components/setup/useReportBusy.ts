import { useEffect, useRef } from "react";

export function useReportBusy(busy: boolean, report?: (busy: boolean) => void) {
  const ref = useRef(report);
  useEffect(() => {
    ref.current = report;
    report?.(busy);
  }, [busy, report]);
  useEffect(() => () => ref.current?.(false), []);
}
