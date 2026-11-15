/**
 * Plugin slots: the places shared code lets an optional feature add to it,
 * so shared code never names or imports one. A plugin is a directory
 * `plugins/<name>/`: `register.ts` default-exports its data slots (a
 * `ChatPlugin`, read here) and `ui.ts` its component slots (a `ChatUiPlugin`,
 * read by lib/chatUiSlots.ts). The barrels `lib/plugins.generated.register.ts` and
 * `lib/plugins.generated.ui.ts` (gitignored, written by `lib/pluginBarrel.js`
 * when `next dev`, `next build` or vitest starts) import every one there is;
 * each is typed to its barrel's plugin type, so a plugin file with no field
 * of its slot type fails tsc (type plugin files with `satisfies` to catch any
 * misplaced field). No `plugins/` directory: every slot empty. tsc alone (no dev
 * server or test run yet) falls back to `lib/noPlugins.ts` (tsconfig `paths`).
 *
 * The cycle rule: this module imports the register barrel, so nothing a
 * `register.ts` imports, however indirectly, may import a value from this
 * module (or from lib/nav.ts and the other readers of it); its modules would
 * run before the slots exist. A plugin imports types only from here. Anything
 * that does reach a reader (a Window header button reaching nav.ts) goes in
 * `ui.ts`, whose barrel only chatUiSlots imports. Slots are read once, at
 * module load.
 *
 * Who reads each slot is on its field in `ChatPlugin`.
 */
import type { ComponentType } from "react";

import type { FanId } from "@/lib/fanId";
import type { NavLink } from "@/lib/nav";
import { PLUGINS } from "@/lib/plugins.generated.register";
import type { FanRecord } from "@/lib/relayTypes";

export interface NavLinkSlot {
  /** The OnlyFans sidebar group's label it joins. */
  group: string;
  link: NavLink;
  /** Before the group's own links; else after them. */
  first?: boolean;
}

export interface ChatPlugin {
  /** nav.ts: sidebar links added to an OnlyFans group. */
  navLinks?: readonly NavLinkSlot[];
  /** nav.ts `openPopout`: Messages Pro routes that are a mode of the window,
   *  not a place in it; the plain Messages Pro link takes the window from them
   *  to the inbox. moneyRailStorage `surfaceOf` puts them on Messages Pro's
   *  surface (one Notif setting with it). */
  popoutModeRoutes?: readonly string[];
  /** Composer slots (block below): useScriptSuggestions, the Composer,
   *  TemplatePicker, composerDraft and the scripts settings read it. */
  scriptSource?: ScriptSourceSlot;
  /** totalSpend `storedSpendCents`: a Fan's lifetime spend as the plugin
   *  knows it; Fan insights' Total spend takes it when it beats our ledger's. */
  fanSpendCents?: (fan: FanRecord) => number | null | undefined;
  /** AgencyNotifications `consentFixHref`: the page where a Creator's consent
   *  switch is (first plugin's; none: Settings › OnlyFans consent). */
  consentFixHref?: (accountId: string) => string;
}

export const NAV_LINK_SLOTS: readonly NavLinkSlot[] = PLUGINS.flatMap((p) => p.navLinks ?? []);
export const POPOUT_MODE_ROUTES: ReadonlySet<string> = new Set(PLUGINS.flatMap((p) => p.popoutModeRoutes ?? []));

// ---- Composer slots -------------------------------------------------------

/** The step a script source offers next (the Composer's "Next in" bubble). */
export interface SourceStep {
  scriptId: string;
  step: number;
  /** The bubble's label and the pick's title. */
  label: string;
  text: string;
}

/** A source of scripts whose progress the server keeps, offered in a fan
 *  chat when no user Script has a step to go. One per app (the first
 *  plugin's). */
export interface ScriptSourceSlot {
  /** Whether a script id is this source's: a send of one counts no saved
   *  reply, the scripts settings never list one, and the Scripts picker
   *  hides one unless it is the chat's current one or searched for. */
  owns: (scriptId: string | null | undefined) => boolean;
  /** A Scripts picker search starting with this lists all of its scripts. */
  searchPrefix: string;
  /** The Scripts picker's header over the current script's rows: `<id> · <label>`. */
  label: string;
  /** A hook, called on every Composer render: the chat's current script and
   *  its next step; `markSent` after a send that rode one of its steps
   *  (not a failed one), `dismiss` on the bubble's ✕. */
  useSource: (accountId: string | null, fanId: FanId | null, fanSpokeLastAt: string | null) => {
    scriptId: string | null;
    next: SourceStep | null;
    dismiss: () => void;
    markSent: (scriptId: string, step: number) => void;
  };
  /** Drawn inside its next-step bubble, whose click and Enter load the step:
   *  it stops its own events from reaching the bubble. `onDraft` puts a draft
   *  in the composer as a suggestion (no script pick). */
  StepAction?: ComponentType<{ accountId: string; fanId: FanId; replyAt: string | null; onDraft: (text: string) => void }>;
}

export const SCRIPT_SOURCE: ScriptSourceSlot | null = PLUGINS.find((p) => p.scriptSource)?.scriptSource ?? null;

/** Whether `scriptId` is the script source's (never without one). */
export function isSourceScript(scriptId: string | null | undefined): boolean {
  return !!SCRIPT_SOURCE?.owns(scriptId);
}

// ---- Chat UI slots ----------------------------------------------------------

export const FAN_SPEND_SOURCES: readonly ((fan: FanRecord) => number | null | undefined)[] =
  PLUGINS.flatMap((p) => (p.fanSpendCents ? [p.fanSpendCents] : []));
export const CONSENT_FIX_HREF: (accountId: string) => string =
  PLUGINS.find((p) => p.consentFixHref)?.consentFixHref
  ?? ((accountId) => `/settings/consent?account=${encodeURIComponent(accountId)}`);
