"use client";

/**
 * Employees > "Shift schedule" (docs/spec/phase-02-shifts-time-tracking.md, App; Inventory §3.8), in the look of
 * Infloww's legacy `Index$1` (bundle @16768636; page-parity ticket 18): the 48px header with the Agency's time zone
 * and a gear for "Shift Settings", then antd line tabs "Shift schedule" / "Shift history" (`?tab=history`) with
 * "Create shift(s)" or "Export" at the tab bar's right.
 *
 * The week is the Agency's: its week start day (Monday when never saved; spec phase-04, story 20) and its time zone
 * (Settings › Your Preferences, `useAgencyTimeZone`), cut by `zonedWeek`, so `from` / `to`, the day columns, today
 * and the tile times all read in that zone. "Date:" steps a week either way and "This week" comes home; the Creator
 * and Employee filters go to `GET /admin/shifts`, the Employee group filter (its sub-groups included) is applied to
 * the week's occurrences here, and "Reset" clears all three. Filters apply as they are picked (no "Search"). The
 * grid is `ShiftGrid`; "Shift history" is `ShiftHistory` (the Timesheet, by Employee or by Creator) or `ShiftRecords`
 * ("By shift", one row per worked shift) over the same week, picked by its "Group by" strip. Owner-only: a chatter reaching the
 * route by URL gets a sentence, and the Relay 403s the endpoints anyway.
 *
 * Infloww's tip says Shift times do not follow daylight saving time; ours do (each Shift keeps its `tz`), so the
 * same yellow line says that instead.
 *
 * ASSUMPTION: the Employee filter offers the whole active roster including chatters' Mirror Employees (they can be
 * on a Shift), and the Creator filter offers the owner's Creators from /admin/accounts. Rung 5: the two lists the
 * app already loads. Overturned by Inventory evidence of other choices.
 */

import { useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, Info, Plus, Settings } from "lucide-react";

import { useUser } from "@/contexts/UserContext";
import { useActionAllowed } from "@/components/shell/useGrantedPages";
import { useIsChatterOnly } from "@/components/shell/useIsChatterOnly";
import { IfButton, IfSegmented, IfSelect, IfTabs, InflowwPageHeader, type IfOption } from "@/components/ui/infloww";
import { useAccounts } from "@/hooks/useAccounts";
import { useRoster } from "@/hooks/useRoster";
import { useTabParam } from "@/hooks/useTabParam";
import { useAgencyTimeZone, useWeekStart } from "@/lib/appliedSettings";
import { downloadCsv } from "@/lib/csv";
import { groupsInTreeOrder, useEmployeeGroups } from "@/lib/employeeGroups";
import { pushNotice } from "@/lib/notices";
import {
  useShiftRecords, useShiftWeek, useTimesheet, weekRangeLabel, zonedWeek, type ShiftOccurrence, type TimesheetGroup,
} from "@/lib/shifts";
import { utcOffsetLabel } from "@/lib/utcOffset";
import ShiftGrid, { type GridRow } from "@/components/shifts/ShiftGrid";
import ShiftHistory, { historyCells, historyHeads } from "@/components/shifts/ShiftHistory";
import ShiftRecords, { recordCells, recordHeads, type RecordNames } from "@/components/shifts/ShiftRecords";
import ShiftsWindow, { type ShiftPreset } from "@/components/shifts/ShiftsWindow";
import { useShiftDelete } from "@/components/shifts/ShiftScopeDialog";
import ShiftSettingsDialog from "@/components/shifts/ShiftSettingsDialog";

type Tab = "scheduling" | "history";
const isHistory = (v: string): v is "history" => v === "history";
const TZ_TIP = "Shift times are shown in your organization's time zone (Settings › Your Preferences)";

/** "UTC+02:00 ⓘ" after the title: the zone the grid reads in (00's report-time-zone look). */
function TzLabel({ zone }: { zone: string }) {
  return (
    <span className="flex shrink-0 items-center gap-1 text-[14px] text-fg-dim tabular-nums">
      <span suppressHydrationWarning>{utcOffsetLabel(zone)}</span>
      <span role="img" aria-label={TZ_TIP} title={TZ_TIP} className="cursor-help">
        <Info className="h-3.5 w-3.5" aria-hidden />
      </span>
    </span>
  );
}

export default function ShiftSchedule() {
  const chatterOnly = useIsChatterOnly();
  const tz = useAgencyTimeZone();
  const [settingsOpen, setSettingsOpen] = useState(false);
  return (
    <div className="min-w-0">
      <InflowwPageHeader
        title="Shift schedule"
        extra={<TzLabel zone={tz} />}
        actions={!chatterOnly && (
          <button type="button" aria-label="Shift Settings" title="Shift Settings" onClick={() => setSettingsOpen(true)}
            className="grid h-6 w-6 place-items-center text-fg-dim hover:text-accent">
            <Settings className="h-5 w-5" aria-hidden />
          </button>
        )}
      />
      {chatterOnly
        ? <p className="px-6 py-4 text-sm text-fg-dim">Only the agency owner manages the Shift schedule.</p>
        : <WeekCalendar tz={tz} />}
      {settingsOpen && <ShiftSettingsDialog onClose={() => setSettingsOpen(false)} />}
    </div>
  );
}

/** A query item: "Label:" 14px T1 at line-height 28px, 8px before its control, 15px right of and under it. */
function Query({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="mb-[15px] mr-[15px] flex min-w-0 max-w-full items-center">
      <span className="mr-2 shrink-0 text-[14px] leading-7 text-fg">{label}</span>
      {children}
    </div>
  );
}

function WeekField({ label, onPrev, onNext }: { label: string; onPrev: () => void; onNext: () => void }) {
  const arrow = "grid h-6 w-6 place-items-center rounded text-muted hover:text-accent";
  return (
    <span className="inline-flex h-8 w-[250px] min-w-0 items-center justify-between rounded-md border border-border bg-bg px-1 text-[14px] text-fg">
      <button type="button" aria-label="Previous week" className={arrow} onClick={onPrev}>
        <ChevronLeft className="h-4 w-4" aria-hidden />
      </button>
      <span className="truncate tabular-nums">{label}</span>
      <button type="button" aria-label="Next week" className={arrow} onClick={onNext}>
        <ChevronRight className="h-4 w-4" aria-hidden />
      </button>
    </span>
  );
}

function WeekCalendar({ tz }: { tz: string }) {
  const { user } = useUser();
  const router = useRouter();
  const pathname = usePathname();
  const queryClient = useQueryClient();
  const firstDay = useWeekStart();
  const exportAllowed = useActionAllowed("export");
  const [tab, setTab] = useState<Tab>("scheduling");
  useTabParam("tab", isHistory, setTab);
  // The shown week is "this week" plus `weeksAway`, so it follows the week start and the zone once the Applied
  // settings load, and "This week" re-reads the clock.
  const [now, setNow] = useState(() => new Date());
  const [weeksAway, setWeeksAway] = useState(0);
  const { days } = zonedWeek(now, firstDay, tz, weeksAway);
  const [employeeId, setEmployeeId] = useState("");
  const [accountId, setAccountId] = useState("");
  const [groupId, setGroupId] = useState("");
  const [group, setGroup] = useState<TimesheetGroup>("employee");
  // "By shift": Shift records in place of the Timesheet (roadmap W6 6.6); `group` keeps the Timesheet's grouping.
  const [byShift, setByShift] = useState(false);
  // null = closed; { editing: null } = "Create shift(s)" (a preset from an empty cell); else that Shift.
  const [shiftsWindow, setShiftsWindow] = useState<{ editing: ShiftOccurrence | null; preset?: ShiftPreset } | null>(null);

  const week = useShiftWeek({ weekStart: days[0].start, weekEnd: days[6].end, employeeId, accountId }, !!user);
  const sheet = useTimesheet(days[0].start, days[6].end, group, !!user && tab === "history" && !byShift);
  const records = useShiftRecords(days[0].start, days[6].end, !!user && tab === "history" && byShift);
  const roster = useRoster({ includeDisabled: false, includeChatterMirrors: true });
  const accounts = useAccounts().data?.accounts ?? [];
  const groups = useEmployeeGroups(!!user).data?.groups ?? [];

  const pickTab = (t: Tab) => {
    setTab(t);
    router.replace(t === "history" ? `${pathname}?tab=history` : pathname, { scroll: false });
  };
  const prev = () => setWeeksAway((n) => n - 1);
  const next = () => setWeeksAway((n) => n + 1);
  const weekField = (
    <>
      <Query label="Date:">
        <WeekField label={weekRangeLabel(days)} onPrev={prev} onNext={next} />
      </Query>
      <IfButton variant="link" className="mb-[15px] mr-[15px]" onClick={() => { setNow(new Date()); setWeeksAway(0); }}>
        This week
      </IfButton>
    </>
  );

  // The Employee group filter: the picked group and every group under it.
  const inGroup = new Set<number>();
  if (groupId) {
    const add = (id: number) => { inGroup.add(id); groups.filter((g) => g.parent_id === id).forEach((g) => add(g.id)); };
    add(Number(groupId));
  }
  const groupOf = new Map(roster.rows.map((e) => [e.id, e.group_id ?? null]));
  const all = week.data?.occurrences ?? [];
  const shown = groupId
    ? all.filter((o) => o.employees.some((e) => inGroup.has(groupOf.get(e.id) ?? -1)))
    : all;

  // One row per Creator on a shown Shift (just the picked Creator when the filter is on), by name.
  const accountById = new Map(accounts.map((a) => [a.id, a]));
  const rowIds = accountId ? [accountId] : [...new Set(shown.flatMap((o) => o.accounts.map((a) => a.id)))];
  const rows: GridRow[] = rowIds.map((id) => {
    const meta = accountById.get(id);
    const fromShift = shown.flatMap((o) => o.accounts).find((a) => a.id === id)?.display_name;
    const name = meta?.nickname || meta?.name || fromShift || id;
    return { account: meta ?? { id, nickname: name }, name };
  }).sort((a, b) => a.name.localeCompare(b.name));

  const employeeOptions: IfOption[] = roster.rows.map((e) => ({ value: String(e.id), label: e.display_name }));
  const creatorOptions: IfOption[] = accounts.map((a) => ({ value: a.id, label: a.nickname || a.id }));
  const groupOptions: IfOption[] = groupsInTreeOrder(groups).map(({ group: g, depth }) => ({
    value: String(g.id), text: g.name, label: <span style={{ paddingLeft: depth * 16 }}>{g.name}</span>,
  }));

  /** A tile's Delete: an occurrence of a weekly series asks its scope first, a one-off confirms. */
  const del = useShiftDelete({
    onDone: () => void queryClient.invalidateQueries({ queryKey: ["shifts"] }),
    onError: (e, o) => pushNotice({
      id: `shift-cancel:${o.shift_id}`, text: e instanceof Error ? e.message : String(e), label: "Shift schedule",
    }),
  });

  const historyRows = sheet.data?.rows ?? [];
  const recordRows = records.data?.records ?? [];
  const recordNames: RecordNames = {
    employee: (id) => roster.rows.find((e) => e.id === id)?.display_name ?? (id == null ? "—" : `Employee #${id}`),
    creator: (id) => id == null ? "All creators" : accountById.get(id)?.nickname || id,
  };
  const extra = tab === "scheduling" ? (
    <IfButton variant="primary" icon={Plus} aria-label="Create shift(s)" className="max-sm:px-2"
      onClick={() => setShiftsWindow({ editing: null })}>
      <span className="max-sm:hidden">Create shift(s)</span>
    </IfButton>
  ) : exportAllowed && (
    <IfButton disabled={(byShift ? recordRows : historyRows).length === 0}
      onClick={() => downloadCsv(`shift-${byShift ? "records" : "history"}-${days[0].date}.csv`, byShift
        ? [recordHeads(tz), ...recordRows.map((r) => recordCells(r, tz, recordNames))]
        : [historyHeads(group), ...historyRows.map(historyCells)])}>
      Export
    </IfButton>
  );

  return (
    <>
      <IfTabs<Tab>
        aria-label="Shift schedule"
        className="mx-6 mt-2.5 px-0"
        tabs={[{ value: "scheduling", label: "Shift schedule" }, { value: "history", label: "Shift history" }]}
        value={tab}
        onChange={pickTab}
        extra={extra}
      />

      {tab === "scheduling" ? (
        <div className="px-6 pb-6">
          <div className="mb-[5px] mt-6 flex items-start justify-between">
            <div className="flex min-w-0 flex-1 flex-wrap items-center">
              {weekField}
              <Query label="Creator:">
                <IfSelect aria-label="Creator" placeholder="Creator" className="w-[200px]" value={accountId}
                  options={creatorOptions} onChange={setAccountId} />
              </Query>
              <Query label="Employee:">
                <IfSelect aria-label="Employee" placeholder="Employee" className="w-[200px]" value={employeeId}
                  options={employeeOptions} onChange={setEmployeeId} />
              </Query>
              <Query label="Employee group:">
                <IfSelect aria-label="Employee group" placeholder="Group" className="w-[200px]" value={groupId}
                  options={groupOptions} onChange={setGroupId} />
              </Query>
            </div>
            <IfButton className="mb-[15px] mr-[15px] shrink-0"
              onClick={() => { setEmployeeId(""); setAccountId(""); setGroupId(""); }}>
              Reset
            </IfButton>
          </div>
          <p className="flex items-center gap-2 pb-4 text-[14px] text-[#b8991a]">
            <Info className="h-4 w-4 shrink-0" aria-hidden />
            Shift times follow daylight saving time in each Shift&apos;s time zone.
          </p>
          <ShiftGrid
            days={days}
            tz={tz}
            now={now}
            rows={rows}
            occurrences={shown}
            colourOrder={all}
            loading={week.isLoading}
            error={week.isError ? `Couldn't load the Shift schedule: ${week.error?.message ?? "unknown error"}` : null}
            onRetry={() => void week.refetch()}
            onPrev={prev}
            onNext={next}
            onEdit={(o) => setShiftsWindow({ editing: o })}
            onDelete={del.request}
            onCreate={(id, date) => setShiftsWindow({ editing: null, preset: { accountId: id, date } })}
          />
        </div>
      ) : (
        <div className="px-6 py-[15px]">
          <div className="flex flex-wrap items-center">{weekField}</div>
          <section aria-label="Shift history" className="space-y-4">
            <IfSegmented
              aria-label="Group by"
              value={byShift ? "shift" : group}
              onChange={(v: TimesheetGroup | "shift") => {
                setByShift(v === "shift");
                if (v !== "shift") setGroup(v);
              }}
              options={[
                { value: "employee", label: "By employee" }, { value: "account", label: "By creator" },
                { value: "shift", label: "By shift" },
              ]}
            />
            {byShift ? (
              <ShiftRecords records={records} tz={tz} names={recordNames}
                employees={roster.rows.map((e) => ({ id: e.id, label: e.display_name }))} />
            ) : <ShiftHistory sheet={sheet} group={group} />}
          </section>
        </div>
      )}

      {shiftsWindow && (
        <ShiftsWindow
          editing={shiftsWindow.editing}
          preset={shiftsWindow.preset}
          defaultTz={tz}
          employees={roster.rows.map((e) => ({ id: e.id, label: e.display_name }))}
          creators={accounts.map((a) => ({ id: a.id, label: a.nickname || a.id }))}
          onClose={() => setShiftsWindow(null)}
        />
      )}
      {del.dialog}
    </>
  );
}
