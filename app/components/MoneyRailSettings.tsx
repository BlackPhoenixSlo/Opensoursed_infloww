"use client";

/** The Buys & tips rail's ⚙ panel (`MoneyRail`). */

import {
  BIG_ROW_CHOICES,
  SMALL_ROW_CHOICES,
  SURFACE_VALUES,
  parseSurfaces,
  railVisibleOn,
  type RailSettings,
  type Surface,
} from "@/lib/moneyRailStorage";

/** Labels for the "Show on" surface checkboxes — keyed by the canonical
 *  Surface union, so a new surface in SURFACE_VALUES is a compile error here
 *  until it gets a label (and its checkbox appears for free). */
const SURFACE_LABELS: Record<Surface, string> = {
  inbox: "Inbox",
  popup: "Solo chat",
  group: "Group tab",
  other: "Other pages",
};
const SURFACE_CHOICES = SURFACE_VALUES.map((key) => ({ key, label: SURFACE_LABELS[key] }));

/** The ⚙ popover: where the rail shows at all, how many rows each size
 *  shows, and which models feed it. Writes straight through on every change
 *  — no Save button, the rail re-renders under you so the effect IS the
 *  feedback. */
export function SettingsPanel({
  settings,
  accounts,
  onChange,
}: {
  settings: RailSettings;
  accounts: readonly { id: string; nickname?: string | null }[];
  onChange: (s: RailSettings) => void;
}) {
  // null (= all) is rendered as every box ticked, so "all" and "everything
  // picked" look the same — which is what a user means by them anyway.
  const picked = settings.accounts;
  const isOn = (id: string) => (picked ? picked.includes(id) : true);

  const toggleAccount = (id: string) => {
    const current = picked ?? accounts.map((a) => a.id);
    const next = current.includes(id)
      ? current.filter((x) => x !== id)
      : [...current, id];
    // Unticking the last model would blank the rail forever — read that as
    // "back to all" rather than leaving a dead dock on screen.
    if (next.length === 0 || next.length === accounts.length) {
      onChange({ ...settings, accounts: null });
      return;
    }
    onChange({ ...settings, accounts: next });
  };

  const surfaceOn = (s: Surface) => railVisibleOn(settings, s);
  const toggleSurface = (s: Surface) => {
    const current = settings.surfaces ?? SURFACE_CHOICES.map((c) => c.key);
    const next = current.includes(s)
      ? current.filter((x) => x !== s)
      : [...current, s];
    // parseSurfaces applies the same guard on read, but normalise here too so
    // the ticks reflect what will actually happen: all off = back to all.
    onChange({ ...settings, surfaces: parseSurfaces(next) });
  };

  return (
    <div className="px-3 py-2.5 border-b border-border bg-bg-elev-1/30 text-[11px] space-y-2.5">
      <div>
        <span className="text-fg-dim">Show on</span>
        <div className="flex items-center flex-wrap gap-x-3 gap-y-1 mt-1">
          {SURFACE_CHOICES.map((s) => (
            <label
              key={s.key}
              className="flex items-center gap-1.5 cursor-pointer hover:text-fg text-fg-dim"
            >
              <input
                type="checkbox"
                checked={surfaceOn(s.key)}
                onChange={() => toggleSurface(s.key)}
                className="accent-info"
              />
              <span>{s.label}</span>
            </label>
          ))}
        </div>
        <p className="text-[10px] text-fg-dim mt-1 leading-snug">
          Unticking the surface you&apos;re on hides the rail here instantly —
          bring it back from the 🔔 dropdown.
        </p>
      </div>

      <div className="flex items-center justify-between gap-2">
        <label htmlFor="rail-small" className="text-fg-dim">Rows when small</label>
        <select
          id="rail-small"
          value={settings.smallRows}
          onChange={(e) => onChange({ ...settings, smallRows: Number(e.target.value) })}
          className="bg-panel border border-border rounded px-1.5 py-0.5 text-fg"
        >
          {SMALL_ROW_CHOICES.map((n) => (
            <option key={n} value={n}>{n === 0 ? "0 (bar only)" : n}</option>
          ))}
        </select>
      </div>

      <div className="flex items-center justify-between gap-2">
        <label htmlFor="rail-big" className="text-fg-dim">Rows when big</label>
        <select
          id="rail-big"
          value={settings.bigRows}
          onChange={(e) => onChange({ ...settings, bigRows: Number(e.target.value) })}
          className="bg-panel border border-border rounded px-1.5 py-0.5 text-fg"
        >
          {BIG_ROW_CHOICES.map((n) => <option key={n} value={n}>{n}</option>)}
        </select>
      </div>

      <div>
        <div className="flex items-center justify-between gap-2 mb-1">
          <span className="text-fg-dim">Models</span>
          <span className="text-[10px] text-fg-dim">
            {picked ? `${picked.length}/${accounts.length}` : `all ${accounts.length}`}
          </span>
        </div>
        <div className="max-h-[104px] overflow-y-auto space-y-0.5 pr-1">
          {accounts.map((a) => (
            <label
              key={a.id}
              className="flex items-center gap-2 py-0.5 cursor-pointer hover:text-fg text-fg-dim"
            >
              <input
                type="checkbox"
                checked={isOn(a.id)}
                onChange={() => toggleAccount(a.id)}
                className="accent-info"
              />
              <span className="truncate">{a.nickname || a.id}</span>
            </label>
          ))}
        </div>
        <p className="text-[10px] text-fg-dim mt-1 leading-snug">
          Independent of the model you&apos;re scoped to — the rail watches all
          models unless you narrow it here.
        </p>
      </div>
    </div>
  );
}
