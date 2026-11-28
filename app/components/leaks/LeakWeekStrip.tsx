import { weekLine, type WeekStrip } from "./leakCoverage";

export function LeakWeekStrip({ strip }: { strip: WeekStrip }) {
  return (
    <section aria-label="This week" className="mb-4 min-w-0 break-words text-[14px] text-fg">
      {weekLine(strip)}
    </section>
  );
}
