"use client";

/**
 * Your Preferences (docs/spec/settings-tabs/phase-01-account-preferences.md):
 * Report time zone, Time zone, Week start day and Language, saved whole to the
 * `preferences` Settings blob behind the Load gate. The time zones and week
 * start are Applied (ADR-0012, docs/spec/phase-04-apply-stored-settings.md);
 * Language is not applied yet, so the note names only it.
 *
 * The zone lists and the browser's zone are read through useSyncExternalStore
 * with empty server snapshots, so the server-rendered markup never disagrees
 * with the browser's ICU data during hydration.
 */

import { useSyncExternalStore } from "react";

import { useSettingsBlob } from "@/lib/settingsBlob";
import { BlobNotes, Field, FieldSelect, NotAppliedYet, Section, SettingsPanel } from "@/components/settings/SettingsPanel";
import { SaveRow } from "@/components/settings/StickySaveBar";
import PlatformSwitches from "@/components/settings/PlatformSwitches";

type Preferences = {
  report_tz: string;
  tz: string;
  week_start: "monday" | "sunday";
  language: "en" | "es";
};

const NO_ZONES: string[] = [];
let zones: string[] | null = null;
const browserZones = () => (zones ??= Intl.supportedValuesOf("timeZone"));
const browserZone = () => Intl.DateTimeFormat().resolvedOptions().timeZone;
const subscribe = () => () => {};

const WEEK_STARTS = [
  { value: "monday", label: "Monday" },
  { value: "sunday", label: "Sunday" },
] as const;
const LANGUAGES = [
  { value: "en", label: "English" },
  { value: "es", label: "Spanish" },
] as const;

/** Every zone this browser knows, plus `value` when the list lacks it, so a stored zone stays selected; 400+
 *  zones, so the list has a filter box. */
function ZoneSelect({ id, value, list, onChange, describedBy }: {
  id: string;
  value: string;
  list: string[];
  onChange: (zone: string) => void;
  describedBy?: string;
}) {
  const all = value && !list.includes(value) ? [value, ...list] : list;
  const options = all.map((z) => ({ value: z, label: z }));
  return <FieldSelect searchable id={id} aria-describedby={describedBy} value={value} options={options} onChange={onChange} />;
}

export default function PreferencesTab() {
  const list = useSyncExternalStore(subscribe, browserZones, () => NO_ZONES);
  const zone = useSyncExternalStore(subscribe, browserZone, () => "");
  const blob = useSettingsBlob<Preferences>("preferences", {
    report_tz: zone, tz: zone, week_start: "monday", language: "en",
  });
  const v = blob.value;

  return (
    <SettingsPanel title="Your Preferences" actions={<SaveRow {...blob.save} gateNote={null} look="settings" />}>
      <Field label="Report time zone" htmlFor="pref-report-tz">
        <p id="pref-report-tz-desc" className="pt-2 mb-2 text-[length:var(--if-fs)] text-[var(--if-fg-3)]">
          Your preferred time zone for Creator and fan reports
        </p>
        <ZoneSelect
          id="pref-report-tz"
          describedBy="pref-report-tz-desc"
          value={v.report_tz}
          list={list}
          onChange={(report_tz) => blob.set({ report_tz })}
        />
      </Field>
      <Field label="Time zone" htmlFor="pref-tz">
        <ZoneSelect id="pref-tz" value={v.tz} list={list} onChange={(tz) => blob.set({ tz })} />
      </Field>
      <Field label="Week start day" htmlFor="pref-week-start">
        <FieldSelect
          id="pref-week-start"
          value={v.week_start}
          options={WEEK_STARTS}
          onChange={(week_start) => blob.set({ week_start })}
        />
      </Field>
      <Section title="Language Settings">
        <Field label="Language" htmlFor="pref-language">
          <FieldSelect
            id="pref-language"
            value={v.language}
            options={LANGUAGES}
            onChange={(language) => blob.set({ language })}
          />
        </Field>
      </Section>
      <PlatformSwitches />
      <div className="flex flex-col gap-3">
        <NotAppliedYet fields={["Language"]} />
        <BlobNotes note={blob.save.gateNote} q={blob.query} />
      </div>
    </SettingsPanel>
  );
}
