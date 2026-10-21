"use client";

/**
 * Sales Settings (docs/spec/settings-tabs/phase-03-roles-sales.md): three
 * toggles and the earnings attribution rules, saved whole to the `sales`
 * Settings blob behind the Load gate. Subscriptions, Streams & Referrals are
 * credited by the shift schedule, with only the chatter opt-in to choose.
 * Every field is applied (docs/spec/phase-04-apply-stored-settings.md, story
 * 55), so the Panel carries no "not applied yet" note: the toggles and rules
 * credit sales in Employee reports and the Timesheet's Recorded earnings
 * (service/sales_attribution.py), and "Multiple employees per shift" is also
 * the Relay's Shift overlap rule (service/shifts_api.py), which Shift Settings
 * on the Shift schedule edits too.
 *
 * Versioned (roadmap W6 6.4): a save takes effect from "Set effective date", now by default, and a sale reads the
 * version in effect when it was made, so a backdated save recredits only the sales from then (SettingsVersions).
 */

import { useSettingsBlob } from "@/lib/settingsBlob";
import { BlobNotes, Field, RadioGroup, Section, SettingsPanel, ToggleRow } from "@/components/settings/SettingsPanel";
import { SaveRow } from "@/components/settings/StickySaveBar";
import SettingsVersions from "@/components/settings/SettingsVersions";

type Attribution = {
  messages: "shift" | "sender" | "converters";
  posts_tips: "shift" | "converters";
  subscriptions_chatter_opt_in: boolean;
};
type SalesBlob = {
  exclude_welcome: boolean;
  exclude_of_fee: boolean;
  multi_employee_shift: boolean;
  attribution: Attribution;
};

const DEFAULTS: SalesBlob = {
  exclude_welcome: false,
  exclude_of_fee: false,
  multi_employee_shift: false,
  attribution: { messages: "shift", posts_tips: "shift", subscriptions_chatter_opt_in: false },
};

const TOGGLES = [
  { key: "exclude_welcome", title: "Exclude welcome messages" },
  { key: "exclude_of_fee", title: "Exclude the 20% OnlyFans fee" },
  { key: "multi_employee_shift", title: "Multiple employees per shift" },
] as const;

const MESSAGES = [
  { value: "shift", label: "Shift schedule" },
  { value: "sender", label: "Message sender" },
  { value: "converters", label: "Converters" },
] as const;
const POSTS_TIPS = [
  { value: "shift", label: "Shift schedule" },
  { value: "converters", label: "Converters" },
] as const;

/** One option row: a radio or checkbox and its text, side by side. */
const OPTION = "inline-flex items-center gap-2 cursor-pointer";

/** The attribution radiogroups' layout: one wrapping row. */
const GROUP = "flex flex-wrap gap-x-6 gap-y-2";

export default function SalesSettingsTab() {
  const blob = useSettingsBlob<SalesBlob>("sales", DEFAULTS);
  const v = blob.value;
  // Merged key by key: a stored partial `attribution` still renders and saves every key (spec story 26).
  const attribution = { ...DEFAULTS.attribution, ...v.attribution };
  const attribute = (patch: Partial<Attribution>) => blob.set({ attribution: { ...attribution, ...patch } });

  return (
    <SettingsPanel
      title="Sales Settings"
      actions={<SaveRow {...blob.save} gateNote={null} look="settings" onSave={() => blob.commit({ attribution })} />}
    >
      <BlobNotes className="mb-4" note={blob.save.gateNote} q={blob.query} />
      <Section>
        {TOGGLES.map((t) => (
          <ToggleRow key={t.key} title={t.title} checked={v[t.key]} onChange={(on) => blob.set({ [t.key]: on })} />
        ))}
      </Section>
      <Section title="Earnings types and attribution rules">
        <div className="text-[length:var(--if-fs)] text-[var(--if-fg)]">
          <Field label="Messages">
            <RadioGroup
              aria-label="Messages"
              name="sales-messages"
              value={attribution.messages}
              options={MESSAGES}
              onChange={(messages) => attribute({ messages })}
              rowClassName={OPTION}
              className={GROUP}
            />
          </Field>
          <Field label="Posts and Tips">
            <RadioGroup
              aria-label="Posts and Tips"
              name="sales-posts-tips"
              value={attribution.posts_tips}
              options={POSTS_TIPS}
              onChange={(posts_tips) => attribute({ posts_tips })}
              rowClassName={OPTION}
              className={GROUP}
            />
          </Field>
          <Field label="Subscriptions, Streams & Referrals">
            <div className={GROUP}>
              <span>Shift schedule</span>
              <label className={OPTION}>
                <input
                  type="checkbox"
                  checked={attribution.subscriptions_chatter_opt_in}
                  onChange={(e) => attribute({ subscriptions_chatter_opt_in: e.target.checked })}
                  className="w-4 h-4 accent-[var(--if-accent)] cursor-pointer"
                />
                Opt in to chatters
              </label>
            </div>
          </Field>
          <p className="text-[length:var(--if-fs-sm)] text-[var(--if-fg-3)]">
            Shift schedule credits sales only while Time tracking is on.
          </p>
        </div>
      </Section>
      <SettingsVersions effective={blob.effective} history={blob.history}
        recomputes="sales credited to employees (Employee reports, the Timesheet's Recorded earnings)" />
    </SettingsPanel>
  );
}
