"use client";

/**
 * The Permission editor (docs/spec/settings-tabs/phase-03-roles-sales.md): one
 * Permission role's pages, one radio-drawn checkbox each, under the tabs
 * "Operations" / "Growth" / "OF Manager", plus its Data scope. The pages come
 * from the nav (`permissionTabs`), so a nav change shows up here unedited.
 * It is its own Panel, as Infloww's editor is a full page: the 48px header has
 * a back chevron before the role's name and "Save" at the right. "Save" hands
 * the role back with every page explicit; "Back" drops the edits.
 * Under a page with Function permissions (lib/permissionActions.ts) each action
 * has its own checkbox, usable while its page is ticked. An action is one switch
 * under every page showing it (the Relay refuses it once any of its keys is
 * false): on unless the role stores one false, and "Save" stores them all alike.
 * Under the Dashboard each card a role can hide (lib/dashboardCards.ts) has one too, on unless stored false.
 * A role is Applied only while Role enforcement is on (ADR-0012).
 */

import { useState, type ReactNode } from "react";

import { isDivider, isGroup, isPermissionPage, PERMISSION_PAGES, SIDEBAR, type NavNode } from "@/lib/nav";
import { IF_BTN_PRIMARY, RADIO, RadioGroup, Section, SettingsPanel, TABLE_ROW } from "@/components/settings/SettingsPanel";
import { IfTabs } from "@/components/ui/infloww";
import { CARD_PERMISSIONS, pageCards } from "@/lib/dashboardCards";
import { EXTRA_LABEL } from "@/lib/openinflowwwwExtras";
import { PAGE_ACTIONS, pageActions } from "@/lib/permissionActions";
import { cn } from "@/lib/utils";

type Scope = "all" | "subordinates" | "self";
export interface PermissionRole {
  id: string;
  name: string;
  description: string;
  permissions: Record<string, boolean>;
  scope: Scope;
  /** Role Settings' Status switch off: the role grants nothing until it is on again. */
  disabled?: boolean;
}

const TABS = ["Operations", "Growth", "OF Manager"] as const;
type PermissionTab = (typeof TABS)[number];
interface PageGroup {
  title: string;
  pages: { label: string; href: string }[];
  /** The nav group is `chatterOptIn` (My Automations): off for chatters unless ticked here. */
  optIn?: boolean;
}

/** The note under an opt-in group (ours, so it carries the extra label). */
export const OPT_IN_NOTE =
  "Off for chatters by default, except Get to know fans. Tick a page to let this role open it; it applies while Enforce role permissions is on.";

/** The editor's tabs from the nav: "Growth" and "OF Manager" are those groups' children; "Operations"
 *  is every other non-divider link, top-level links first under "General", then each
 *  remaining group under its own label, in nav order. `SIDEBAR_FOOTER` is not a page, nor is a link
 *  with a `permission`, top-level or a child (Focus rides Messages Pro's) — `isPermissionPage`. */
export function permissionTabs(sidebar: NavNode[] = SIDEBAR): { tab: PermissionTab; groups: PageGroup[] }[] {
  const general: PageGroup = { title: "General", pages: [] };
  const groups: Record<PermissionTab, PageGroup[]> = { Operations: [general], Growth: [], "OF Manager": [] };
  for (const n of sidebar) {
    if (isDivider(n)) continue;
    if (!isGroup(n)) {
      // A link that answers to another page's grant (Focus) is not a page of its own.
      if (isPermissionPage(n)) general.pages.push({ label: n.label, href: n.href });
      continue;
    }
    const tab = n.label === "Growth" || n.label === "OF Manager" ? n.label : "Operations";
    groups[tab].push({
      title: n.label,
      pages: n.children.filter(isPermissionPage).map(({ label, href }) => ({ label, href })),
      ...(n.chatterOptIn ? { optIn: true } : {}),
    });
  }
  return TABS.map((tab) => ({ tab, groups: groups[tab] }));
}

const TAB_PAGES = permissionTabs();
/** Every page a Permission role grants or denies, keyed by href in its
 *  `permissions`: nav.ts's `PERMISSION_PAGES`, the one owner of the list. */
export const PAGE_HREFS = [...PERMISSION_PAGES];

const SCOPES: { value: Scope; label: string }[] = [
  { value: "all", label: "All data" },
  { value: "subordinates", label: "Self and subordinates" },
  { value: "self", label: "Data about self" },
];

const ROW = cn(TABLE_ROW, "h-12 px-[var(--if-row-px)] flex items-center gap-3 cursor-pointer");
/** A Function permission's row, indented under its page. */
const ACTION_ROW = cn(ROW, "h-10 pl-[calc(var(--if-row-px)+28px)] text-[var(--if-fg-2)] has-[:disabled]:cursor-not-allowed");

/** `<page href>#<action>` → `<action>`. */
const actionOf = (key: string) => key.slice(key.indexOf("#") + 1);
/** Every Function permission key, set as its action is. */
const actionKeys = (on: Record<string, boolean>) =>
  Object.fromEntries(Object.keys(PAGE_ACTIONS).map((key) => [key, on[actionOf(key)]]));

export default function PermissionEditor({ role, onSave, onBack, canSave, children }: {
  role: PermissionRole;
  onSave: (role: PermissionRole) => void;
  onBack: () => void;
  canSave: boolean;
  /** Shown at the top of the body (the last save's error). */
  children?: ReactNode;
}) {
  const [active, setActive] = useState<PermissionTab>(TABS[0]);
  const [allowed, setAllowed] = useState(() =>
    Object.fromEntries(PAGE_HREFS.map((href) => [href, role.permissions[href] === true])),
  );
  const [actions, setActions] = useState(() => {
    const on: Record<string, boolean> = {};
    for (const key of Object.keys(PAGE_ACTIONS)) on[actionOf(key)] = on[actionOf(key)] !== false && role.permissions[key] !== false;
    return on;
  });
  const [cards, setCards] = useState(() =>
    Object.fromEntries(Object.keys(CARD_PERMISSIONS).map((key) => [key, role.permissions[key] !== false])),
  );
  const [scope, setScope] = useState(role.scope);

  return (
    <SettingsPanel
      title={role.name}
      onBack={onBack}
      actions={
        <button
          type="button"
          className={IF_BTN_PRIMARY}
          disabled={!canSave}
          onClick={() => onSave({ ...role, permissions: { ...role.permissions, ...allowed, ...actionKeys(actions), ...cards }, scope })}
        >
          Save
        </button>
      }
    >
      <div className="text-[length:var(--if-fs)] text-[var(--if-fg)]">
        {children}
        <IfTabs
          aria-label="Permission pages"
          tabs={TABS.map((t) => ({ value: t, label: t }))}
          value={active}
          onChange={setActive}
          className="mb-6 px-0 border-[var(--if-line)]"
        />
        <div role="tabpanel" aria-label={active}>
          {TAB_PAGES.find((t) => t.tab === active)!.groups.map((g) => (
            <div key={g.title} className="mb-8">
              <h4 className={cn(g.optIn ? "mb-1" : "mb-4", "text-[length:var(--if-fs-lg)] font-[var(--if-fw-title)]")}>
                {g.title}
              </h4>
              {g.optIn && (
                <p title={EXTRA_LABEL} className="mb-4 text-[var(--if-fg-2)]">{OPT_IN_NOTE}</p>
              )}
              {g.pages.map((p) => (
                <div key={p.href}>
                  <label className={ROW}>
                    <input
                      type="checkbox"
                      value={p.href}
                      checked={allowed[p.href]}
                      onChange={(e) => setAllowed((a) => ({ ...a, [p.href]: e.target.checked }))}
                      className={RADIO}
                    />
                    {p.label}
                  </label>
                  {pageActions(p.href).map(([key, label]) => (
                    <label key={key} className={ACTION_ROW}>
                      <input
                        type="checkbox"
                        value={key}
                        aria-label={`${p.label}: ${label}`}
                        checked={actions[actionOf(key)]}
                        disabled={!allowed[p.href]}
                        onChange={(e) => setActions((a) => ({ ...a, [actionOf(key)]: e.target.checked }))}
                        className={RADIO}
                      />
                      {label}
                    </label>
                  ))}
                  {pageCards(p.href).map(([key, label]) => (
                    <label key={key} className={ACTION_ROW}>
                      <input
                        type="checkbox"
                        value={key}
                        aria-label={`${p.label}: ${label} card`}
                        checked={cards[key]}
                        disabled={!allowed[p.href]}
                        onChange={(e) => setCards((c) => ({ ...c, [key]: e.target.checked }))}
                        className={RADIO}
                      />
                      {`${label} card`}
                    </label>
                  ))}
                </div>
              ))}
            </div>
          ))}
        </div>
        <Section title="Data scope">
          <RadioGroup
            aria-label="Data scope"
            name="permission-scope"
            value={scope}
            options={SCOPES}
            onChange={setScope}
            rowClassName={ROW}
          />
        </Section>
      </div>
    </SettingsPanel>
  );
}
