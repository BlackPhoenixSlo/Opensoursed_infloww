"use client";

/**
 * Your Preferences (docs/spec/settings-tabs/phase-01-account-preferences.md):
 * Report time zone, Regular time zone, Week start day and "Disable free trial
 * popup", saved whole to the `preferences` Settings blob behind the Load gate.
 * All are Applied (ADR-0012, docs/spec/phase-04-apply-stored-settings.md; the
 * switch hides FreeTrialExpiredModal). Language is hidden until the app is
 * translated (owner, 2026-11-11); its stored `language` key still rides every save.
 *
 * The zone lists and the browser's zone are read through useSyncExternalStore
 * with empty server snapshots, so the server-rendered markup never disagrees
 * with the browser's ICU data during hydration.
 */

import { useSyncExternalStore } from "react";

import { useSettingsBlob } from "@/lib/settingsBlob";
import { BlobNotes, Field, FieldSelect, Section, SettingsPanel, ToggleRow } from "@/components/settings/SettingsPanel";
import { SaveRow } from "@/components/settings/StickySaveBar";
import PlatformSwitches from "@/components/settings/PlatformSwitches";

type Preferences = {
  report_tz: string;
  tz: string;
  week_start: "monday" | "sunday";
  language: "en" | "es";
  /** Absent until switched, so a save that never touched it sends only the four keys above. */
  hide_trial_popup?: boolean;
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

/** A field's one help line, between its label and its control. */
function Help({ id, children }: { id: string; children: string }) {
  return <p id={id} className="mb-2 text-[length:var(--if-fs-sm)] text-[var(--if-fg-3)]">{children}</p>;
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
        <Help id="pref-report-tz-desc">Creator and fan reports</Help>
        <ZoneSelect
          id="pref-report-tz"
          describedBy="pref-report-tz-desc"
          value={v.report_tz}
          list={list}
          onChange={(report_tz) => blob.set({ report_tz })}
        />
      </Field>
      <Field label="Regular time zone" htmlFor="pref-tz">
        <Help id="pref-tz-desc">Top bar clock and Employees&apos; monthly figures</Help>
        <ZoneSelect id="pref-tz" describedBy="pref-tz-desc" value={v.tz} list={list} onChange={(tz) => blob.set({ tz })} />
      </Field>
      <Field label="Week start day" htmlFor="pref-week-start">
        <FieldSelect
          id="pref-week-start"
          value={v.week_start}
          options={WEEK_STARTS}
          onChange={(week_start) => blob.set({ week_start })}
        />
      </Field>
      <Section title="Free trial">
        <ToggleRow
          title="Disable free trial popup"
          description="Never show the “Free trial exceeded” popup on app start"
          checked={v.hide_trial_popup === true}
          onChange={(hide_trial_popup) => blob.set({ hide_trial_popup })}
        />
      </Section>
      <PlatformSwitches />
      <BlobNotes note={blob.save.gateNote} q={blob.query} />
    </SettingsPanel>
  );
}
