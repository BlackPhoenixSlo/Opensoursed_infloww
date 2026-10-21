"use client";

/**
 * Time tracking (docs/spec/settings-tabs/phase-04-time-tracking-messaging.md): the clock-out policy,
 * shown read-only and edited behind "Edit", saved whole to the `time-tracking` Settings blob behind
 * the Load gate. The Relay reads the blob at request time (service/shifts_api.py): "Enable time tracking" lets
 * chatters clock in and out, so the Panel no longer says "not applied yet" (docs/spec/phase-02-shifts-time-tracking.md,
 * App).
 *
 * Since w4-a, as Infloww's `ClockSetting` (bundle @10663332): "Auto clock out" after N minutes of inactivity (10
 * when never saved), and "Enable clock in and clock out for", a checkbox per role (the built-in Owner, Admin, Team
 * Leader, Chatter and Creator, then the `roles` blob's) with "Select all", saved as `role_ids`; the Relay's clock-in and the top bar's Clock button
 * follow it. Infloww's "restart their Infloww app" line is left out: ours applies on the next status read.
 *
 * Checked against the live Infloww app (w5-a, .scratch/infloww-live/05-*.png): with the switch off only "Enable
 * time tracking" shows; Auto clock out and the role list appear once it is on (unsaved too), the minutes field is
 * 48px in the line's small grey text, and the role boxes sit flush with "Select all".
 *
 * Since w5-a, as live Infloww: a blob that never saved `role_ids` shows every role unticked and the Relay lets nobody
 * clock in until the list is saved; the minutes are 1 to 999 (Infloww's InputInteger max).
 *
 * Versioned (roadmap W6 6.4): a save takes effect from "Set effective date" (in the edit view), now by default;
 * Shift schedule credit reads the version in effect at the sale (SettingsVersions). The auto clock-out of a shift
 * still open always follows the settings in effect now.
 */

import { useEffect, useEffectEvent, useState } from "react";

import { withBuiltIns, type RolesBlob } from "@/lib/roles";
import { useSettingsBlob } from "@/lib/settingsBlob";
import { BlobNotes, Card, FieldInput, IF_BTN, SettingsPanel, Switch } from "@/components/settings/SettingsPanel";
import { SaveRow } from "@/components/settings/StickySaveBar";
import SettingsVersions from "@/components/settings/SettingsVersions";

type TimeTrackingBlob = {
  enabled: boolean; auto_clock_out_minutes: number; clock_in_reminder: boolean;
  /** "Enable clock in and clock out for"; absent until first saved. */
  role_ids?: string[];
};
const DEFAULTS: TimeTrackingBlob = { enabled: false, auto_clock_out_minutes: 10, clock_in_reminder: false };

/** The edit view's values, the minutes as the field's text so 0, "", -5 and 1.5 can be shown and refused. */
type Draft = { enabled: boolean; minutes: string; clock_in_reminder: boolean; role_ids: string[] };

const CHECKBOX = "h-4 w-4 accent-[var(--accent)] cursor-pointer disabled:cursor-default";

/** The field's text for a stored minutes value. A stored non-number is not coerced (spec, Implementation
 *  Decisions): it shows an empty field, which fails `validMinutes` like a typed one. */
const minutesText = (stored: unknown) => (typeof stored === "number" ? String(stored) : "");

/** Infloww's Auto clock out field caps at 999 (InputInteger max, bundle @10663332); the Relay refuses more. */
const MAX_MINUTES = 999;

/** Whole minutes from 1 to 999 ("" is 0). */
function validMinutes(text: string): boolean {
  const n = Number(text);
  return Number.isInteger(n) && n >= 1 && n <= MAX_MINUTES;
}

export default function TimeTrackingTab() {
  const blob = useSettingsBlob<TimeTrackingBlob>("time-tracking", DEFAULTS);
  const rolesBlob = useSettingsBlob<RolesBlob>("roles", { roles: [] });
  const roles = withBuiltIns(rolesBlob.value.roles ?? []);
  const v = blob.value;
  const editable = blob.loaded;
  const stored: Draft = {
    enabled: v.enabled,
    minutes: minutesText(v.auto_clock_out_minutes),
    clock_in_reminder: v.clock_in_reminder,
    role_ids: Array.isArray(v.role_ids) ? v.role_ids : [],
  };
  /** Null in the read view, where every control is disabled. */
  const [draft, setDraft] = useState<Draft | null>(null);
  const shown = draft ?? stored;
  const change = draft ? (patch: Partial<Draft>) => setDraft({ ...draft, ...patch }) : undefined;
  const valid = validMinutes(shown.minutes);
  /** The Load gate's note, in the body; a failed load also gets Retry there (settingsBlob.ts). */
  const gateNote = blob.save.gateNote;

  // A save PUTs the hook's whole `value` as it stands when it runs, and a `set` has not reached `value`
  // until the next render. So Save only `set`s the draft and asks; this effect saves on the render that
  // holds it (spec, Interfaces), and a success returns to the read view.
  const [saveAsked, setSaveAsked] = useState(0);
  const saveValue = useEffectEvent(() => blob.commit({}, () => setDraft(null)));
  useEffect(() => {
    if (saveAsked) saveValue();
  }, [saveAsked]);

  const save = (d: Draft) => {
    blob.set({
      enabled: d.enabled, auto_clock_out_minutes: Number(d.minutes), clock_in_reminder: d.clock_in_reminder,
      role_ids: d.role_ids,
    });
    setSaveAsked((n) => n + 1);
  };
  /** Back to the loaded values: drops the draft, and the edits a failed save left in the hook. */
  const cancel = () => {
    blob.reset();
    setDraft(null);
  };

  return (
    <SettingsPanel
      title="Time tracking"
      actions={
        draft ? (
          <>
            <button type="button" className={IF_BTN} onClick={cancel}>
              Cancel
            </button>
            <SaveRow {...blob.save} look="settings" canSave={blob.save.canSave && valid} onSave={() => save(draft)} />
          </>
        ) : (
          <button type="button" className={IF_BTN} disabled={!editable} onClick={() => setDraft(stored)}>
            Edit
          </button>
        )
      }
    >
      <BlobNotes className="mb-4" note={draft ? null : gateNote} q={blob.query} />
      <div className="flex flex-col gap-6">
        <Card
          title="Enable time tracking"
          control={
            <Switch
              checked={shown.enabled}
              label="Enable time tracking"
              // Off hides the minutes field, so a bad value there falls back rather than block Save unseen.
              onChange={change && ((enabled) => change(enabled || validMinutes(shown.minutes) ? { enabled }
                : { enabled, minutes: validMinutes(stored.minutes) ? stored.minutes : String(DEFAULTS.auto_clock_out_minutes) }))}
            />
          }
        >
          <p className="text-[length:var(--if-fs-sm)] leading-5 text-[var(--if-fg-2)]">
            Track your team’s work hours with a clock in and clock out function
          </p>
        </Card>
        {shown.enabled && (
          <Card title="Auto clock out">
            <p className="flex flex-wrap items-center text-[length:var(--if-fs-sm)] text-[var(--if-fg-2)]">
              Users will be automatically clocked out after
              <FieldInput
                type="number"
                min={1}
                max={MAX_MINUTES}
                step={1}
                aria-label="Auto clock out time"
                value={shown.minutes}
                disabled={!change}
                onChange={change && ((e) => change({ minutes: e.target.value }))}
                className="w-12 px-2 mx-2 [appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none"
              />
              minute(s) of inactivity
            </p>
            {!valid && (
              <p role="alert" className="mt-2 text-[length:var(--if-fs-sm)] text-[var(--if-danger)]">
                Enter 1 to 999 minutes.
              </p>
            )}
          </Card>
        )}
        {shown.enabled && (
          <RoleList roles={roles} ids={shown.role_ids}
            onChange={change && ((role_ids) => change({ role_ids }))} />
        )}
        <Card
          title="Clock-in reminder"
          control={
            <Switch
              checked={shown.clock_in_reminder}
              label="Clock-in reminder"
              onChange={change && ((on) => change({ clock_in_reminder: on }))}
            />
          }
        />
      </div>
      <div className="mt-6">
        <SettingsVersions effective={blob.effective} history={blob.history} editing={!!draft}
          recomputes="sales credited by Shift schedule (which needs Time tracking on)"
          also="Auto clock out applies to shifts still open, whatever the date." />
      </div>
    </SettingsPanel>
  );
}

/** "Enable clock in and clock out for": "Select all", then a checkbox per role; disabled in the read view. */
function RoleList({ roles, ids, onChange }: {
  roles: { id: string; name: string }[];
  ids: string[];
  onChange?: (ids: string[]) => void;
}) {
  const all = roles.length > 0 && roles.every((r) => ids.includes(r.id));
  const some = !all && roles.some((r) => ids.includes(r.id));
  const toggle = (id: string, on: boolean) =>
    onChange?.(on ? [...ids.filter((x) => x !== id), id] : ids.filter((x) => x !== id));
  return (
    <Card title="Enable clock in and clock out for">
      <fieldset aria-label="Enable clock in and clock out for" className="flex flex-col gap-2 text-[length:var(--if-fs)] text-[var(--if-fg)]">
        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            className={CHECKBOX}
            checked={all}
            ref={(el) => { if (el) el.indeterminate = some; }}
            disabled={!onChange}
            onChange={(e) => onChange?.(e.target.checked ? roles.map((r) => r.id) : [])}
          />
          Select all
        </label>
        {roles.map((r) => (
          <label key={r.id} className="flex items-center gap-2">
            <input
              type="checkbox"
              className={CHECKBOX}
              checked={ids.includes(r.id)}
              disabled={!onChange}
              onChange={(e) => toggle(r.id, e.target.checked)}
            />
            {r.name || r.id}
          </label>
        ))}
      </fieldset>
      <p className="mt-2 text-[length:var(--if-fs-sm)] leading-5 text-[var(--if-fg-2)]">
        Employees with no role can&apos;t clock in.
      </p>
    </Card>
  );
}
