import { todayLine, type TodayStrip } from "./leakCoverage";

export function LeakTodayStrip({ strip }: { strip: TodayStrip }) {
  return (
    <section aria-label="Today" className="mb-4 min-w-0 break-words text-[14px] text-fg">
      {todayLine(strip)}
    </section>
  );
}
